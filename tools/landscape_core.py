"""Shared logic of the CTeI landscape: ficha parsing and validation, the actor/service/interaction matrix and
the coverage gaps against a reference ficha.

Used by tools/build_landscape.py (to build data/landscape.json and the dashboard) and by tools/landscape_db.py
(the MCP query layer), so the dashboard matrix and actor_service_matrix() come from the same function.
Depends only on PyYAML.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from pathlib import Path

import yaml

LABEL_FIELDS = ("actores", "servicios", "interacciones")
LIST_FIELDS = ("temas",) + LABEL_FIELDS
REQUIRED = ("id", "titulo", "tipo", "alcance", "temas", "evidencia", "consultado")
ID_RE = re.compile(r"^CT\d{3}$")
PRIVATE_REFERENCE_ID = "CT000"
# Evidence must be checkable: a URL, a DOI or a patent publication number (e.g. US10123456B2, WO2020/123456).
EVIDENCE_RE = re.compile(
    r"^(?:https?://\S+|doi:\s*10\.\S+|10\.\d{4,9}/\S+|[A-Z]{2}[\s-]?\d[\d,./\s-]*(?:[A-Z]\d?)?)$")
# Ficha body headings (normalized) to section keys.
SECTION_KEYS = {
    "descripcion": "descripcion",
    "actores que atiende": "actores",
    "servicios": "servicios",
    "interacciones entre actores": "interacciones",
    "modelo de operacion": "modelo_operacion",
    "tecnologia": "tecnologia",
    "ideas para plataformas ctei como hema": "ideas",
    "evidencia": "evidencia",
}


class FichaError(ValueError):
    """A ficha that cannot be parsed at all (no front matter, invalid YAML)."""


def fold(text) -> str:
    """Lowercase without accents, for comparisons and headings."""
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def norm_label(label) -> str:
    """Normalized vocabulary label: accents and case folded, spaces and underscores as hyphens."""
    return re.sub(r"[\s_]+", "-", fold(label)).strip("-")


def split_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise FichaError("missing YAML front matter (the file must start with '---')")
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise FichaError("unterminated YAML front matter (no closing '---')")
    head = parts[0][3:]
    body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
    try:
        meta = yaml.safe_load(head) or {}
    except yaml.YAMLError as exc:
        raise FichaError(f"invalid YAML front matter: {exc}") from exc
    if not isinstance(meta, dict):
        raise FichaError("front matter is not a mapping")
    return meta, body


def parse_sections(body: str) -> dict:
    """Body text under each '## ' heading, keyed by SECTION_KEYS (unknown headings keep their folded name)."""
    out, key, buf = {}, None, []
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if key:
                out[key] = "\n".join(buf).strip()
            name = fold(m.group(1))
            key, buf = SECTION_KEYS.get(name, name), []
        elif key:
            buf.append(line)
    if key:
        out[key] = "\n".join(buf).strip()
    return out


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def read_ficha(path: Path) -> tuple[dict, dict]:
    """(front matter, sections) of one ficha file. Raises FichaError when it cannot be parsed."""
    meta, body = split_front_matter(Path(path).read_text(encoding="utf-8"))
    return meta, parse_sections(body)


def validate(meta: dict, vocab: dict, where: str) -> list[dict]:
    """Every problem of one ficha's front matter, as {file, field, message, severity}.

    severity "fatal": the ficha cannot enter the landscape (no usable id, bad tipo or alcance, private id);
    severity "error": the ficha can enter after dropping the offending values (unknown labels, bad relations)
    or with a gap the reviewer must fill (missing evidence or consultation date).
    """
    issues = []

    def add(field, message, severity="error"):
        issues.append({"file": where, "field": field, "message": message, "severity": severity})

    for field in REQUIRED:
        value = meta.get(field)
        if value is None or value == "" or value == []:
            add(field, "missing required field", "fatal" if field in ("id", "tipo", "alcance") else "error")
    fid = str(meta.get("id") or "")
    if fid and not ID_RE.match(fid):
        add("id", f"id {fid!r} does not match CT### (three digits)", "fatal")
    if fid == PRIVATE_REFERENCE_ID:
        add("id", "CT000 is the private Hēma reference and is never published in this repository", "fatal")
    stem = Path(where).name
    if fid and re.match(r"^CT\d{3}", stem) and not stem.startswith(fid):
        add("id", f"id {fid} does not match the file name {stem}")
    tipo = meta.get("tipo")
    if tipo is not None and tipo not in vocab["tipos"]:
        add("tipo", f"unknown tipo {tipo!r}; allowed: {', '.join(vocab['tipos'])}", "fatal")
    alcance = meta.get("alcance")
    if alcance is not None and alcance not in vocab["alcances"]:
        add("alcance", f"unknown alcance {alcance!r}; allowed: {', '.join(vocab['alcances'])}", "fatal")
    temas = as_list(meta.get("temas"))
    if temas and not 1 <= len(temas) <= 3:
        add("temas", f"{len(temas)} temas; use 1 to 3, the first is the main one")
    for field in LIST_FIELDS:
        allowed = vocab[field]
        for label in as_list(meta.get(field)):
            if str(label) not in allowed:
                add(field, f"unknown label {label!r} (not in data/vocabulario.json {field})")
    evidencia = as_list(meta.get("evidencia"))
    for ev in evidencia:
        if not isinstance(ev, str) or not EVIDENCE_RE.match(ev.strip()):
            add("evidencia", f"{ev!r} is not a URL, a DOI or a patent publication number")
    consultado = meta.get("consultado")
    if consultado not in (None, "") and not isinstance(consultado, dt.date):
        try:
            dt.date.fromisoformat(str(consultado))
        except ValueError:
            add("consultado", f"{consultado!r} is not a date (YYYY-MM-DD)")
    anio = meta.get("anio")
    if anio is not None and not (isinstance(anio, int) and 1900 <= anio <= 2100):
        add("anio", f"{anio!r} is not a year or null")
    for rel in as_list(meta.get("relacionados")):
        if not isinstance(rel, dict) or not rel.get("id") or not rel.get("tipo"):
            add("relacionados", f"{rel!r} must be {{id: CT###, tipo: ...}}")
        elif rel["tipo"] not in vocab["relaciones"]:
            add("relacionados", f"unknown relation tipo {rel['tipo']!r}; allowed: {', '.join(vocab['relaciones'])}")
    return issues


def clean_entry(meta: dict, sections: dict, vocab: dict, file_name: str) -> dict:
    """The landscape record of a ficha: known labels only, dates as ISO strings."""
    def keep(field):
        return [str(x) for x in as_list(meta.get(field)) if str(x) in vocab[field]]

    consultado = meta.get("consultado")
    if isinstance(consultado, dt.date):
        consultado = consultado.isoformat()
    anio = meta.get("anio")
    rels = [{"id": str(r["id"]), "tipo": r["tipo"]} for r in as_list(meta.get("relacionados"))
            if isinstance(r, dict) and r.get("id") and r.get("tipo") in vocab["relaciones"]]
    return {
        "id": str(meta["id"]), "file": file_name, "titulo": str(meta.get("titulo") or meta["id"]),
        "tipo": meta.get("tipo"), "alcance": meta.get("alcance"), "pais": meta.get("pais") or "",
        "operador": meta.get("operador") or "", "anio": anio if isinstance(anio, int) else None,
        "temas": keep("temas")[:3], "actores": keep("actores"), "servicios": keep("servicios"),
        "interacciones": keep("interacciones"),
        "evidencia": [str(e).strip() for e in as_list(meta.get("evidencia")) if e],
        "consultado": str(consultado) if consultado else None, "relacionados_declarados": rels,
        "secciones": sections,
    }


def label_set(meta: dict) -> dict:
    """Normalized labels of a ficha (any ficha, including a reference outside the vocabulary)."""
    return {f: sorted({norm_label(x) for x in as_list(meta.get(f)) if str(x).strip()}) for f in LIST_FIELDS}


def matrix(entries: list[dict], vocab: dict, scope: str | None = None, topic: str | None = None) -> dict:
    """Actors, services and interactions aggregated over the entries, each with its supporting ids, total
    count and count per scope. Filtered by scope (alcance key) and topic (F## among the entry's temas)."""
    scopes = list(vocab["alcances"])
    sel = [e for e in entries if (not scope or e.get("alcance") == scope)
           and (not topic or topic.upper() in (e.get("temas") or []))]
    out = {"scope": scope, "topic": topic.upper() if topic else None, "entries": len(sel),
           "by_scope": {s: sum(1 for e in sel if e.get("alcance") == s) for s in scopes}}
    for field in LABEL_FIELDS:
        rows = {}
        for e in sel:
            for label in e.get(field) or []:
                row = rows.setdefault(label, {"label": label, "name": vocab[field].get(label, label), "count": 0,
                                              "entries": [], "by_scope": {s: 0 for s in scopes}})
                if e["id"] not in row["entries"]:
                    row["entries"].append(e["id"])
                    row["count"] += 1
                    if e.get("alcance") in row["by_scope"]:
                        row["by_scope"][e["alcance"]] += 1
        for row in rows.values():
            row["entries"].sort()
        out[field] = sorted(rows.values(), key=lambda r: (-r["count"], r["label"]))
    return out


def gaps(mat: dict, reference: dict, reference_id: str) -> dict:
    """Deterministic set difference of normalized labels: what the matrix has and the reference does not
    (candidate requirements), what both share, and what only the reference has."""
    out = {"reference_id": reference_id, "available": True, "entries_compared": mat["entries"]}
    for field in LABEL_FIELDS:
        ref = set(reference.get(field) or [])
        rows = mat.get(field) or []
        have = {norm_label(r["label"]) for r in rows}
        out[field] = {
            "gaps": [{"label": r["label"], "name": r["name"], "count": r["count"], "entries": r["entries"],
                      "by_scope": r["by_scope"]} for r in rows if norm_label(r["label"]) not in ref],
            "shared": sorted(have & ref),
            "reference_only": sorted(ref - have),
        }
    out["total_gaps"] = sum(len(out[f]["gaps"]) for f in LABEL_FIELDS)
    return out


def matrix_markdown(mat: dict, vocab: dict, title: str = "Matriz de actores, servicios e interacciones") -> str:
    scopes = list(vocab["alcances"])
    head = "| Etiqueta | Total | " + " | ".join(vocab["alcances"][s] for s in scopes) + " | Fichas |"
    sep = "|---|---:|" + "---:|" * len(scopes) + "---|"
    lines = [f"# {title}", "", f"Fichas consideradas: {mat['entries']}.", ""]
    names = {"actores": "Actores", "servicios": "Servicios", "interacciones": "Interacciones"}
    for field in LABEL_FIELDS:
        lines += [f"## {names[field]}", "", head, sep]
        for r in mat[field]:
            lines.append(f"| {r['name']} (`{r['label']}`) | {r['count']} | "
                         + " | ".join(str(r["by_scope"].get(s, 0)) for s in scopes)
                         + f" | {', '.join(r['entries'])} |")
        lines.append("")
    return "\n".join(lines)
