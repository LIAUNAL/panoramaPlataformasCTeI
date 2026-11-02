"""SQLite FTS5 index over data/landscape.json, the query layer of the ctei-landscape MCP server.

The index (data/landscape.db in a checkout, ~/.cache/ctei-landscape/landscape.db when installed) is derived
data: it is rebuilt automatically whenever the content of landscape.json changes and is never versioned.

    python3 tools/landscape_db.py build                  # force a rebuild
    python3 tools/landscape_db.py search "convocatorias"  # quick check from the shell
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import landscape_core as core  # noqa: E402

SCHEMA_VERSION = "1"
# Weighted for bm25(): title and operator count more than the long narrative sections.
FTS_COLUMNS = [("titulo", 5.0), ("operador", 2.0), ("pais", 1.0), ("temas", 2.0), ("actores", 2.0),
               ("servicios", 2.0), ("interacciones", 2.0), ("descripcion", 1.0), ("detalle", 1.0),
               ("ideas", 1.0)]
DETAIL_SECTIONS = ("actores", "servicios", "interacciones", "modelo_operacion", "tecnologia")
STOPWORDS = set("""a al con como de del e el en entre es la las lo los o para por que se sin su sus un una uno y
an and as at by for from in is of on or the to with""".split())
SIMILARITY_NOTE = ("similitud textual y de etiquetas calculada al generar el panorama; no es un vínculo declarado, "
                   "confírmela antes de citarla")


def default_paths(here):
    """(landscape.json, landscape.db) for this module's folder. In a checkout the data sits beside tools/ and
    the index goes to data/landscape.db; in an installed wheel the data is packaged beside the module and the
    index goes to the user cache, so the package folder is never written."""
    here = Path(here)
    if (here.parent / "data/landscape.json").exists():
        return here.parent / "data/landscape.json", here.parent / "data/landscape.db"
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return here / "data/landscape.json", cache / "ctei-landscape" / "landscape.db"


LANDSCAPE_PATH, DB_PATH = default_paths(Path(__file__).resolve().parent)


def match_query(text, match="any"):
    """Free text to a safe FTS5 query: every word is quoted, so FTS operators are inert.
    match="any" joins the words with OR, match="all" with AND."""
    words = [w for w in re.findall(r"\w+", text or "") if w.lower() not in STOPWORDS]
    return (" AND " if match == "all" else " OR ").join('"%s"' % w for w in words)


class Landscape:
    def __init__(self, landscape_path=LANDSCAPE_PATH, db_path=DB_PATH, fichas_dir=None):
        self.landscape_path = Path(landscape_path)
        self.db_path = Path(db_path)
        self.root = self.landscape_path.parent.parent
        self.fichas_dir = Path(fichas_dir) if fichas_dir else self.root / "fichas"
        self._con = None
        self._doc = None
        self._doc_fp = None

    # -- data ----------------------------------------------------------------
    def _fingerprint(self):
        return SCHEMA_VERSION + ":" + hashlib.sha256(self.landscape_path.read_bytes()).hexdigest()

    def doc(self):
        fp = self._fingerprint()
        if self._doc is None or self._doc_fp != fp:
            self._doc = json.loads(self.landscape_path.read_text(encoding="utf-8"))
            self._doc_fp = fp
        return self._doc

    def vocab(self):
        return self.doc()["vocabulario"]

    def entries(self):
        return self.doc().get("entries", [])

    # -- index ---------------------------------------------------------------
    def _stored_fingerprint(self):
        if not self.db_path.exists():
            return None
        try:
            con = sqlite3.connect(self.db_path)
            try:
                row = con.execute("select value from meta where key='fingerprint'").fetchone()
            finally:
                con.close()
            return row[0] if row else None
        except sqlite3.DatabaseError:
            return None

    def build(self):
        """Write the index to a temporary file and swap it in, so readers never see a half-built db."""
        doc = self.doc()
        vocab = doc["vocabulario"]
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.db_path.with_suffix(".db.tmp")
        if tmp.exists():
            tmp.unlink()
        con = sqlite3.connect(tmp)
        con.executescript(
            """
            create table meta(key text primary key, value text);
            create table entries(id text primary key, tipo text, alcance text, anio integer, cluster text,
                                 titulo text, doc text);
            create table entry_topics(entry_id text, topic text);
            """
        )
        cols = ", ".join(c for c, _ in FTS_COLUMNS)
        con.execute(f"create virtual table entries_fts using fts5(id unindexed, {cols}, "
                    "tokenize='unicode61 remove_diacritics 2')")
        for e in doc.get("entries", []):
            con.execute("insert into entries values(?,?,?,?,?,?,?)",
                        (e["id"], e.get("tipo"), e.get("alcance"), e.get("anio"), e.get("cluster", ""),
                         e.get("titulo", ""), json.dumps(e, ensure_ascii=False)))
            con.executemany("insert into entry_topics values(?,?)", [(e["id"], t) for t in e.get("temas", [])])
            sec = e.get("secciones") or {}

            def names(field):
                return " · ".join(f"{vocab[field].get(x, x)} {x}" for x in e.get(field, []))

            text = {"titulo": e.get("titulo", ""), "operador": e.get("operador", ""), "pais": e.get("pais", ""),
                    "temas": names("temas"), "actores": names("actores"), "servicios": names("servicios"),
                    "interacciones": names("interacciones"), "descripcion": sec.get("descripcion", ""),
                    "detalle": "\n".join(sec.get(k, "") for k in DETAIL_SECTIONS), "ideas": sec.get("ideas", "")}
            row = [e["id"]] + [text[c] for c, _ in FTS_COLUMNS]
            con.execute(f"insert into entries_fts values({', '.join('?' * len(row))})", [str(v) for v in row])
        con.execute("insert into meta values('fingerprint', ?)", (self._fingerprint(),))
        con.commit()
        con.close()
        os.replace(tmp, self.db_path)

    def con(self):
        current = self._fingerprint()
        if self._con is None or self._stored_fingerprint() != current:
            if self._con is not None:
                self._con.close()
            if self._stored_fingerprint() != current:
                self.build()
            self._con = sqlite3.connect(self.db_path, check_same_thread=False)
            self._con.row_factory = sqlite3.Row
        return self._con

    # -- queries -------------------------------------------------------------
    def _check(self, kind=None, scope=None, match="any"):
        vocab = self.vocab()
        if kind and kind not in vocab["tipos"]:
            raise ValueError(f"unknown kind {kind!r}; use one of {', '.join(vocab['tipos'])}")
        if scope and scope not in vocab["alcances"]:
            raise ValueError(f"unknown scope {scope!r}; use one of {', '.join(vocab['alcances'])}")
        if match not in ("any", "all"):
            raise ValueError("match must be 'any' or 'all'")

    @staticmethod
    def _summary(row, **extra):
        out = {"id": row["id"], "tipo": row["tipo"], "alcance": row["alcance"], "titulo": row["titulo"],
               "anio": row["anio"], "cluster": row["cluster"]}
        out.update(extra)
        return out

    def search(self, query="", kind=None, scope=None, topic=None, year_from=None, limit=10, match="any"):
        """Entries ranked by BM25 relevance; with no query, the filtered entries newest first."""
        self._check(kind, scope, match)
        con = self.con()
        where, args = [], []
        if kind:
            where.append("e.tipo = ?"); args.append(kind)
        if scope:
            where.append("e.alcance = ?"); args.append(scope)
        if topic:
            where.append("e.id in (select entry_id from entry_topics where topic = ?)"); args.append(topic.upper())
        if year_from:
            where.append("e.anio >= ?"); args.append(int(year_from))
        limit = max(1, min(int(limit or 10), 100))
        q = match_query(query, match)
        if (query or "").strip() and not q:
            return []
        if q:
            weights = ", ".join(str(w) for _, w in FTS_COLUMNS)
            sql = (f"select e.*, bm25(entries_fts, 0, {weights}) as score, "
                   "snippet(entries_fts, -1, '[', ']', '…', 14) as snip "
                   "from entries_fts join entries e on e.id = entries_fts.id where entries_fts match ? "
                   + "".join(" and " + w for w in where) + " order by score, e.id limit ?")
            rows = con.execute(sql, [q] + args + [limit]).fetchall()
            return [self._summary(r, snippet=r["snip"], score=round(-r["score"], 3)) for r in rows]
        sql = ("select e.* from entries e" + (" where " + " and ".join(where) if where else "")
               + " order by coalesce(e.anio, 0) desc, e.id limit ?")
        return [self._summary(r) for r in con.execute(sql, args + [limit]).fetchall()]

    def _entry(self, entry_id):
        row = self.con().execute("select doc from entries where id = ?", ((entry_id or "").strip().upper(),)).fetchone()
        return json.loads(row["doc"]) if row else None

    def _titulo(self, entry_id):
        e = self._entry(entry_id)
        return e["titulo"] if e else None

    def get_entry(self, entry_id):
        e = self._entry(entry_id)
        if e is None:
            return None
        vocab = self.vocab()
        e["topic_names"] = [vocab["temas"].get(t, t) for t in e.get("temas", [])]
        e["alcance_nombre"] = vocab["alcances"].get(e.get("alcance"), e.get("alcance"))
        md = self.fichas_dir / e["file"]
        e["markdown_path"] = str(md) if md.exists() else None
        e["markdown"] = md.read_text(encoding="utf-8") if md.exists() else None
        return e

    def related_entries(self, entry_id):
        e = self._entry(entry_id)
        if e is None:
            return None
        relations = [{"id": r["id"], "tipo": r["tipo"], "direction": r["direction"], "titulo": self._titulo(r["id"])}
                     for r in e.get("relacionados", [])]
        similar = [{"id": s["id"], "sim": s["sim"], "titulo": self._titulo(s["id"])} for s in e.get("top5", [])]
        same = [self._summary(r) for r in self.con().execute(
            "select * from entries where cluster = ? and id != ? order by coalesce(anio, 0) desc, id",
            (e.get("cluster", ""), e["id"]))]
        return {"id": e["id"], "titulo": e["titulo"], "cluster": e.get("cluster"), "relations": relations,
                "similar": similar, "similarity_note": SIMILARITY_NOTE, "same_cluster": same}

    def actor_service_matrix(self, scope=None, topic=None):
        self._check(scope=scope)
        return core.matrix(self.entries(), self.vocab(), scope=scope, topic=topic)

    def _reference(self, reference_path, reference_id):
        """(labels, id, None) of the reference ficha, or (None, None, message) when it is not available.

        Order: reference_path, then CTEI_REFERENCE_PATH, then a public description shipped in fichas/
        (e.g. HEMA-publico.md) or a landscape entry. The private CT000 is never read from the public fichas."""
        # An empty CTEI_REFERENCE_PATH (Aracne registers `${CTEI_REFERENCE_PATH:-}`) counts as unset.
        path = (reference_path or "").strip() or (os.environ.get("CTEI_REFERENCE_PATH") or "").strip()
        if path:
            p = Path(path).expanduser()
            if not p.is_file():
                return None, None, f"reference ficha not found: {p}"
            try:
                meta, _ = core.read_ficha(p)
            except core.FichaError as exc:
                return None, None, f"reference ficha {p} cannot be read: {exc}"
            return core.label_set(meta), str(meta.get("id") or reference_id), None
        rid = (reference_id or "").strip()
        if rid and rid.upper() != core.PRIVATE_REFERENCE_ID:
            public = self.fichas_dir / f"{rid}.md"
            if public.is_file() and not rid.upper().startswith("CT"):
                meta, _ = core.read_ficha(public)
                return core.label_set(meta), str(meta.get("id") or rid), None
            entry = self._entry(rid)
            if entry is not None:
                return core.label_set(entry), entry["id"], None
        return None, None, (
            f"no reference ficha for {rid or 'CT000'}: the Hēma reference (CT000) is private and is not part of "
            "this public repository. Pass reference_path=<path to the ficha outside the repo> or set "
            "CTEI_REFERENCE_PATH; for the public description use reference_id='HEMA-publico' when "
            "fichas/HEMA-publico.md exists.")

    def coverage_gaps(self, reference_path=None, reference_id="CT000"):
        labels, rid, message = self._reference(reference_path, reference_id)
        if labels is None:
            return {"reference_id": reference_id, "available": False, "message": message}
        entries = [e for e in self.entries() if e["id"] != rid]
        return core.gaps(core.matrix(entries, self.vocab()), labels, rid)

    def taxonomy(self):
        vocab, entries = self.vocab(), self.entries()

        def count(pred):
            return sum(1 for e in entries if pred(e))

        return {
            "topics": [{"id": t, "name": n, "entries": count(lambda e, t=t: t in e.get("temas", []))}
                       for t, n in vocab["temas"].items()],
            "types": [{"id": t, "entries": count(lambda e, t=t: e.get("tipo") == t)} for t in vocab["tipos"]],
            "scopes": [{"id": s, "name": n, "entries": count(lambda e, s=s: e.get("alcance") == s)}
                       for s, n in vocab["alcances"].items()],
            "clusters": [{"id": c["id"], "name": c["name"], "top_terms": c.get("top_terms", []),
                          "entries": len(c["members"])} for c in self.doc().get("clusters", [])],
            "relations": vocab["relaciones"],
            "labels": {f: [{"id": k, "name": v} for k, v in vocab[f].items()] for f in core.LABEL_FIELDS},
        }

    def export(self, ids, dest_dir):
        """Copy the entries' fichas and a matrix over them into an existing folder (e.g. a project's inputs)."""
        dest = Path(dest_dir).expanduser()
        if not dest.is_dir():
            raise ValueError(f"destination folder does not exist: {dest}")
        written, missing, chosen = [], [], []
        for entry_id in ids:
            e = self._entry(entry_id)
            md = self.fichas_dir / e["file"] if e else None
            if md is None or not md.exists():
                missing.append(entry_id)
                continue
            target = dest / f"ctei-{e['file']}"
            target.write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(str(target))
            chosen.append(e)
        if chosen:
            target = dest / "ctei-landscape-matriz.md"
            target.write_text(core.matrix_markdown(core.matrix(chosen, self.vocab()), self.vocab()), encoding="utf-8")
            written.append(str(target))
        return {"written": written, "missing": missing}


def main(argv):
    land = Landscape()
    if argv[:1] == ["build"]:
        land.build()
        print(f"index written to {land.db_path}")
    elif argv[:1] == ["search"] and len(argv) > 1:
        for hit in land.search(" ".join(argv[1:])):
            print(f"{hit['id']:6} {hit['score']:6} {hit['titulo'][:90]}")
    else:
        print("usage: landscape_db.py build | search <text>", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
