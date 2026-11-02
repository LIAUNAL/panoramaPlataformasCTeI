"""Build the CTeI landscape: validate fichas/CT*.md, cluster them, relate them and render the static site.

Run: uv run python tools/build_landscape.py [--lenient] [--recluster] [--clusters K] [--no-site] [--root DIR]
Inputs: fichas/CT*.md (YAML front matter + fixed sections, see fichas/_plantilla.md), data/vocabulario.json
        (closed vocabulary), data/cluster_names.json (cluster names, placeholders until a person edits them),
        data/landscape.json (previous build: entries keep their cluster, new ones join the nearest centroid;
        --recluster runs k-means from scratch and rewrites the placeholder names), data/runs.jsonl (agent runs).
Outputs: data/landscape.json, data/cluster_names.json, docs/ (index.html, constelacion.html, data/landscape.json).

Validation fails the build listing every file and field (unknown label, bad tipo or alcance, missing evidencia
or consultado, duplicate id, unknown relation target). --lenient reports the same problems on stderr, drops the
offending values and keeps out only the fichas that cannot be placed (no id, duplicate id, bad tipo or alcance).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import landscape_core as core  # noqa: E402

REPO = TOOLS.parent
SEED = 7
MAX_CLUSTERS = 12
ASSETS = ("logo_atenea_horizontal.png", "favicon.png", "favicon.ico", "apple-touch-icon.png")
REPO_URL = "https://github.com/LIAUNAL/panoramaPlataformasCTeI"
STOP = """de la el en y a los las del se por con para un una que su al lo como mas o es son sus este esta
these this that with from into based using use used the of and in for on to an by at as is are be we our
plataforma plataformas sistema mediante partir traves sobre entre cada otros otras tambien desde ser
no publicada fuente consultado quien ofrece demanda""".split()


class ValidationFailed(Exception):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("\n".join(fmt(i) for i in issues))


def fmt(issue):
    return f"{issue['file']}: {issue['field']}: {issue['message']}"


# -- fichas ------------------------------------------------------------------

def load_vocab(root):
    return json.loads((root / "data/vocabulario.json").read_text(encoding="utf-8"))


def load_fichas(root, vocab, lenient):
    """Valid entries and every issue found. Raises ValidationFailed unless lenient."""
    issues, entries, seen = [], [], {}
    for path in sorted((root / "fichas").glob("CT*.md")):
        where = f"fichas/{path.name}"
        try:
            meta, sections = core.read_ficha(path)
        except core.FichaError as exc:
            issues.append({"file": where, "field": "front matter", "message": str(exc), "severity": "fatal"})
            continue
        found = core.validate(meta, vocab, where)
        fid = str(meta.get("id") or "")
        if fid and fid in seen:
            found.append({"file": where, "field": "id", "severity": "fatal",
                          "message": f"duplicate id {fid} (also in {seen[fid]})"})
        issues += found
        if any(i["severity"] == "fatal" for i in found):
            continue
        seen[fid] = where
        entries.append(core.clean_entry(meta, sections, vocab, path.name))
    ids = {e["id"] for e in entries}
    for e in entries:
        kept = []
        for r in e["relacionados_declarados"]:
            if r["id"] not in ids:
                issues.append({"file": f"fichas/{e['file']}", "field": "relacionados", "severity": "error",
                               "message": f"relation target {r['id']} is not a ficha in fichas/"})
            elif r["id"] != e["id"]:
                kept.append(r)
        e["relacionados_declarados"] = kept
    blocking = [i for i in issues if i["severity"] in ("fatal", "error")]
    if blocking and not lenient:
        raise ValidationFailed(blocking)
    return entries, issues


def load_runs(root):
    """Agent runs from data/runs.jsonl (one JSON object per line); malformed lines become warnings."""
    path, runs, issues = root / "data/runs.jsonl", [], []
    if not path.exists():
        return runs, issues
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            run = json.loads(line)
            if not isinstance(run, dict):
                raise ValueError("not an object")
        except ValueError as exc:
            issues.append({"file": "data/runs.jsonl", "field": f"line {n}", "severity": "warning",
                           "message": f"skipped, not a JSON object: {exc}"})
            continue
        for key in ("fichas_consulted", "fichas_exported"):
            run[key] = [str(x).upper() for x in core.as_list(run.get(key))]
        runs.append(run)
    return runs, issues


# -- clusters and similarity ---------------------------------------------------

def text_of(e, vocab):
    sec = e.get("secciones") or {}
    names = [vocab[f].get(x, x) for f in core.LIST_FIELDS for x in e.get(f, [])]
    return " ".join([e["titulo"], e.get("operador", ""), sec.get("descripcion", ""), sec.get("servicios", ""),
                     sec.get("interacciones", ""), sec.get("ideas", "")] + names)


def features(entries, vocab):
    """Rows: TF-IDF of the text joined with one-hot vocabulary labels (topics, actors, services, interactions,
    type and scope), both L2-normalized, so similarity reflects shared labels as much as shared words.
    Also returns the TF-IDF matrix and its terms, for cluster top terms."""
    n = len(entries)
    try:
        vec = TfidfVectorizer(stop_words=STOP, min_df=1 if n < 20 else 2, max_df=1.0 if n < 10 else 0.8,
                              ngram_range=(1, 2), sublinear_tf=True, strip_accents="unicode")
        X = vec.fit_transform([text_of(e, vocab) for e in entries]).toarray()
        terms = np.array(vec.get_feature_names_out())
    except ValueError:  # empty vocabulary
        X, terms = np.zeros((n, 1)), np.array([""])
    cols = [(f, k) for f in core.LIST_FIELDS for k in vocab[f]] + [("tipo", t) for t in vocab["tipos"]] + \
        [("alcance", a) for a in vocab["alcances"]]
    index = {c: j for j, c in enumerate(cols)}
    L = np.zeros((n, len(cols)))
    for i, e in enumerate(entries):
        for f in core.LIST_FIELDS:
            for k in e.get(f, []):
                L[i, index[(f, k)]] = 1.0
        L[i, index[("tipo", e["tipo"])]] = 1.0
        L[i, index[("alcance", e["alcance"])]] = 1.0
    Z = normalize(np.hstack([0.6 * normalize(X), 0.8 * normalize(L)]))
    return Z, X, terms


def default_k(n):
    return max(1, min(MAX_CLUSTERS, n, round(math.sqrt(n))))


def previous_clusters(root):
    path = root / "data/landscape.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {m: c["id"] for c in doc.get("clusters", []) for m in c.get("members", [])}


def assign_clusters(entries, Z, root, recluster, n_clusters):
    """Cluster id per entry. Entries keep their previous cluster; new ones join the nearest centroid of the
    kept members. Re-running k-means after adding a few fichas would reshuffle the partition and the names in
    data/cluster_names.json would point to the wrong groups, so k-means runs only with --recluster or on the
    first build."""
    n = len(entries)
    if n == 0:
        return []
    prev = {} if recluster else previous_clusters(root)
    kept = [prev.get(e["id"]) for e in entries]
    if any(kept):
        ids = sorted({c for c in kept if c})
        cent = np.array([Z[[i for i, c in enumerate(kept) if c == cid]].mean(axis=0) for cid in ids])
        cent = normalize(cent)
        labels = list(kept)
        for i, c in enumerate(kept):
            if not c:
                labels[i] = ids[int((Z[i] @ cent.T).argmax())]
        return labels
    k = max(1, min(n, n_clusters or default_k(n)))
    raw = KMeans(n_clusters=k, n_init=20, random_state=SEED).fit_predict(Z) if k > 1 else np.zeros(n, int)
    # Number clusters by their first member in id order, so the same corpus always gets the same ids.
    order = []
    for c in raw:
        if c not in order:
            order.append(c)
    return [f"C{order.index(c) + 1:02d}" for c in raw]


def build_clusters(entries, labels, X, terms, vocab, root, recluster):
    """Cluster records. Names come from data/cluster_names.json; a cluster without a name gets a placeholder
    from its top terms, written back for a person to edit. --recluster replaces every name with a placeholder,
    since the new groups no longer match the old names."""
    names_path = root / "data/cluster_names.json"
    names = {} if recluster or not names_path.exists() else json.loads(names_path.read_text(encoding="utf-8"))
    if recluster and names_path.exists():
        print("note: clusters were computed from scratch; review the placeholder names in data/cluster_names.json",
              file=sys.stderr)
    clusters = []
    for cid in sorted(set(labels)):
        idx = [i for i, c in enumerate(labels) if c == cid]
        weights = X[idx].mean(axis=0)
        top = [t for t in terms[np.argsort(-weights)][:8].tolist() if t]
        topic_counts = {}
        for i in idx:
            for t in entries[i]["temas"][:1]:
                topic_counts[t] = topic_counts.get(t, 0) + 1
        if cid not in names:
            names[cid] = "Por nombrar: " + " · ".join(top[:3]) if top else f"Por nombrar {cid}"
        clusters.append({"id": cid, "name": names[cid], "top_terms": top,
                         "topics": dict(sorted(topic_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
                         "members": sorted(entries[i]["id"] for i in idx)})
    return clusters, dict(sorted(names.items()))


def relate(entries, Z):
    """Typed relations in both directions (declared in the fichas) and the top 5 by similarity."""
    by = {e["id"]: e for e in entries}
    links = []
    for e in entries:
        e["relacionados"] = []
    for e in entries:
        for r in e["relacionados_declarados"]:
            links.append({"from": e["id"], "to": r["id"], "rel": r["tipo"], "declared": True})
    for link in links:
        out = {"id": link["to"], "tipo": link["rel"], "direction": "out"}
        inn = {"id": link["from"], "tipo": link["rel"], "direction": "in"}
        if out not in by[link["from"]]["relacionados"]:
            by[link["from"]]["relacionados"].append(out)
        if inn not in by[link["to"]]["relacionados"]:
            by[link["to"]]["relacionados"].append(inn)
    S = Z @ Z.T if len(entries) else np.zeros((0, 0))
    for k, e in enumerate(entries):
        order = [j for j in np.argsort(-S[k], kind="stable") if j != k and S[k, j] > 0][:5]
        e["top5"] = [{"id": entries[j]["id"], "sim": round(float(min(1.0, S[k, j])), 3)} for j in order]
    return links


# -- site ----------------------------------------------------------------------

def short(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1].rsplit(" ", 1)[0] + "…"


SLOT_COLORS = {"scope": "#5ad1e6", "kind": "#95a5a6", "actor": "#5aa9e6", "service": "#2ecc71",
               "interaction": "#e67e22"}
REL_COLORS = {"similar-a": "#2ecc71", "implementa": "#e8b339", "estudiado-en": "#5aa9e6"}
TIPO_ES = {"plataforma": "Plataforma", "software": "Software", "patente": "Patente", "articulo": "Artículo",
           "otro": "Otro"}


def atlas(doc):
    vocab, entries = doc["vocabulario"], doc["entries"]
    by = {e["id"]: e for e in entries}
    cname = {c["id"]: c["name"] for c in doc["clusters"]}

    def planet(pid, slot, orbit, label, detail, e, tip=None):
        ev = e["evidencia"][0] if e["evidencia"] else e["id"]
        return {"id": pid, "slot": slot, "orbit": orbit, "label": label[:90], "detail": detail,
                "tip": tip or short(f"{label}: {detail}", 90), "provenance": "ficha " + e["id"],
                "evidence": {"quote": short((e.get("secciones") or {}).get("descripcion", ""), 420),
                             "origin": ev, "retrieved": e.get("consultado") or ""}}

    systems = []
    for e in entries:
        tipo, scope = TIPO_ES.get(e["tipo"], e["tipo"]), vocab["alcances"].get(e["alcance"], e["alcance"])
        sec = e.get("secciones") or {}
        ps = [planet("sun", "sun", 0, f"{e['id']} · {e['titulo']}", f"{tipo} ({e.get('anio') or 's. f.'}). {e['titulo']}",
                     e, tip=short(f"{e['id']} · {tipo} · {scope} · {e['titulo']}", 90)),
              planet("scope", "scope", 1, f"Alcance: {scope}", e.get("pais") or scope, e, tip=f"Alcance · {scope}"),
              planet("kind", "kind", 1, f"Tipo: {tipo}", e.get("operador") or tipo, e, tip=f"Tipo · {tipo}"),
              planet("fam", "family", 1, f"{e['cluster']} {cname[e['cluster']]}", f"Clúster {e['cluster']}", e,
                     tip=short(f"Clúster {e['cluster']} · {cname[e['cluster']]}", 90))]
        for t in e["temas"][:2]:
            ps.append(planet(f"t{t}", "topic_ai", 1, f"{t} {vocab['temas'][t]}", "Función CTeI", e,
                             tip=short(f"Tema {t} · {vocab['temas'][t]}", 90)))
        for field, slot, orbit, pre, word in (("actores", "actor", 2, "a", "Actor"),
                                              ("interacciones", "interaction", 2, "i", "Interacción"),
                                              ("servicios", "service", 3, "s", "Servicio")):
            for x in e[field]:
                ps.append(planet(f"{pre}-{x}", slot, orbit, vocab[field][x], word, e,
                                 tip=short(f"{word} · {vocab[field][x]}", 90)))
        meta = {"kind": e["tipo"], "tipo": tipo, "title": e["titulo"], "name": short(e["titulo"], 44),
                "years": str(e.get("anio") or ""), "venue": " · ".join(filter(None, [e.get("operador"), e.get("pais")])),
                "alcance": e["alcance"], "scope": scope, "cluster": f"{e['cluster']} {cname[e['cluster']]}",
                "temas": [f"{t} {vocab['temas'][t]}" for t in e["temas"]],
                "actores": [vocab["actores"][x] for x in e["actores"]],
                "servicios": [vocab["servicios"][x] for x in e["servicios"]],
                "interacciones": [vocab["interacciones"][x] for x in e["interacciones"]],
                "descripcion": sec.get("descripcion", ""), "ideas": sec.get("ideas", ""),
                "evidencia": e["evidencia"], "consultado": e.get("consultado") or "",
                "relations": [{"id": r["id"], "tipo": r["tipo"], "direction": r["direction"]} for r in e["relacionados"]],
                "top5": [{"id": r["id"], "sim": r["sim"], "kind": by[r["id"]]["tipo"],
                          "title": short(by[r["id"]]["titulo"], 110)} for r in e["top5"]]}
        systems.append({"id": e["id"], "title": e["id"], "planets": ps, "meta": meta})
    links = [{"from_system": l["from"], "from": "sun", "to_system": l["to"], "to": "sun", "rel": l["rel"]}
             for l in doc["links"]]
    links += [{"from_system": s["id"], "from": "sun", "to_system": s["id"], "to": p["id"], "rel": "about"}
              for s in systems for p in s["planets"] if p["id"] != "sun"]
    return {"systems": systems, "links": links}


# Build-time additions to the vendored viewer (tools/vendor/atlas3d stays byte-identical to upstream):
# no sprite labels, centred framing, a node's own short tooltip, camera
# controls, screen projection and pause/resume.
VIEWER_PATCHES = [
    ("let U=Yh(String(at.title||nt).slice(0,64),r_);U.position.copy(xt),Mt.add(U)", ""),
    ("yt.forEach(A=>{A.visible=dt===\"groups\"})", "yt.forEach(A=>{A.visible=!1})"),
    ("n.setPixelRatio(Math.min(window.devicePixelRatio||1,2))",
     "n.setPixelRatio(Math.min(Math.max(window.devicePixelRatio||1,1),window.CTEI_MAX_DPR||2))"),
    ("n=new to({antialias:!0})",
     "n=new to({antialias:!window.CTEI_LOW_POWER,"
     "powerPreference:window.CTEI_LOW_POWER?\"low-power\":\"default\"})"),
    ("function q(){let nt=i.clientWidth||800,$=i.clientHeight||600;",
     "function q(){if(!i.clientWidth&&n.domElement.width>1)return;let nt=i.clientWidth||800,$=i.clientHeight||600;"),
    ("let at=$/Math.sin(H/2*Math.PI/180)*.8;",
     "let at=$/Math.sin(H/2*Math.PI/180)*.8/Math.min(1,(i.clientWidth||800)/(i.clientHeight||600));"),
    ("let J=k(m,_),X=J;",
     "let J=k(u.reduce((a,b)=>a.add(b),new L).multiplyScalar(1/Math.max(1,u.length)),_*.7),X=J;"),
    ("n.render(r,P),requestAnimationFrame(me)}return me(),{",
     "n.render(r,P),__paused||requestAnimationFrame(me)}let __paused=!1;return me(),{"
     "pause(){__paused=!0},resume(){__paused&&(__paused=!1,requestAnimationFrame(me))},"),
    ("s.textContent=`${A.planet.label} [${A.planet.slot}]`",
     "s.textContent=A.planet.tip||`${A.planet.label} [${A.planet.slot}]`"),
    ("layout(){return dt}}}",
     "layout(){return dt},"
     "rotating(){return Q.autoRotate},"
     "rotate(o){Q.autoRotate=o===void 0?!Q.autoRotate:!!o;return Q.autoRotate},"
     "spin(a){Q.autoRotate=!1;let d=P.position.clone().sub(Q.target).applyAxisAngle(new L(0,0,1),a);"
     "P.position.copy(Q.target).add(d)},"
     "tilt(a){Q.autoRotate=!1;let d=P.position.clone().sub(Q.target),"
     "x=new L().crossVectors(d,new L(0,0,1)).normalize();d.applyAxisAngle(x,a);"
     "P.position.copy(Q.target).add(d)},"
     "project(ks){let r=n.domElement.getBoundingClientRect(),v=new L;return ks.map(k=>{let j=l.get(k);"
     "if(j===void 0)return null;v.copy(u[j]).project(P);return{x:(v.x+1)/2*r.width,y:(1-v.y)/2*r.height,"
     "z:v.z,on:v.z<1&&Math.abs(v.x)<1&&Math.abs(v.y)<1}})}}}"),
]
VENDOR = TOOLS / "vendor/atlas3d"


# The upstream banner names the project the viewer was built for; the page keeps only the three.js credit
# that its MIT license requires.
BANNER = re.compile(r"\A\s*/\*!.*?Bundles (three\.js [\d.]+ \(https://threejs\.org\) Copyright [\d-]+ three\.js authors, "
                    r"MIT License).*?\*/", re.S)


def viewer_bundle():
    bundle = (VENDOR / "atlas3d.bundle.js").read_text(encoding="utf-8")
    m = BANNER.match(bundle)
    if not m:
        raise SystemExit("viewer banner no longer matches: update BANNER in tools/build_landscape.py")
    bundle = f"/*! {m.group(1)}; see THIRD_PARTY_NOTICES.md. */" + bundle[m.end():]
    for old, new in VIEWER_PATCHES:
        if bundle.count(old) != 1:
            raise SystemExit(f"viewer patch no longer applies: {old[:40]}")
        bundle = bundle.replace(old, new)
    return bundle


def render_pages(doc):
    """Every file of the static site as {relative path: str or Path to copy}, computed before anything is
    written, so a missing template or a viewer patch that no longer applies leaves the outputs untouched."""
    spec = importlib.util.spec_from_file_location("render_atlas", VENDOR / "render_atlas.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.PAGE = (TOOLS / "constellation_template.html").read_text(encoding="utf-8")
    mod.SLOT_COLORS.update(SLOT_COLORS)
    mod.REL_COLORS.update(REL_COLORS)
    files = {}
    page = mod.render(atlas(doc), viewer=viewer_bundle(), title="Constelación de referentes CTeI",
                      heading="Constelación de referentes CTeI: cada sistema es un referente y sus planetas son "
                              "alcance, tipo, temas, actores, interacciones y servicios")
    files["constelacion.html"] = page
    data = json.dumps(doc, ensure_ascii=False)
    template = (TOOLS / "dashboard_template.html").read_text(encoding="utf-8")
    page = template.replace("@@LANDSCAPE@@", data.replace("<", "\\u003c")).replace("@@REPO@@", REPO_URL)
    files["index.html"] = (
        '<!doctype html>\n<html lang="es">\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' + page)
    for asset in ASSETS:
        src = TOOLS / "assets" / asset
        if not src.is_file():
            raise SystemExit(f"missing site asset: {src}")
        files[asset] = src
    files["data/landscape.json"] = data
    files["THIRD_PARTY_NOTICES.md"] = third_party_notices()
    return files


def third_party_notices():
    """Notices for the software inlined in constelacion.html: the full three.js MIT text and the atlas3d viewer."""
    upstream = (VENDOR / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    mit = re.search(r"```text\n(The MIT License.*?)```", upstream, re.S)
    version = re.search(r"Version: ([\d.]+)", upstream)
    if not (mit and version):
        raise SystemExit("three.js notice not found in tools/vendor/atlas3d/THIRD_PARTY_NOTICES.md")
    return (
        "# Avisos de terceros\n\n"
        "`constelacion.html` incluye el visor 3D atlas3d, construido sobre three.js.\n\n"
        f"## three.js\n\n- Versión: {version.group(1)}\n- Fuente: https://github.com/mrdoob/three.js\n"
        "- Licencia: MIT\n\n```text\n" + mit.group(1) + "```\n\n"
        "## Visor 3D atlas3d\n\n"
        "Visor 3D atlas3d: Apache License 2.0, copia en tools/vendor/atlas3d/LICENSE; modificado para este "
        "repositorio (plantilla propia, tooltips, controles de cámara, pausa).\n")


def write_site(files, site):
    for rel, content in files.items():
        target = site / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            shutil.copyfile(content, target)
        else:
            target.write_text(content, encoding="utf-8")


# -- main ----------------------------------------------------------------------

def build(root=REPO, lenient=False, recluster=False, n_clusters=None, site=True, site_dir=None):
    root = Path(root)
    vocab = load_vocab(root)
    entries, issues = load_fichas(root, vocab, lenient)
    runs, run_issues = load_runs(root)
    issues += run_issues
    Z, X, terms = features(entries, vocab) if entries else (np.zeros((0, 1)), np.zeros((0, 1)), np.array([""]))
    labels = assign_clusters(entries, Z, root, recluster, n_clusters)
    for e, c in zip(entries, labels):
        e["cluster"] = c
    clusters, names = build_clusters(entries, labels, X, terms, vocab, root, recluster) if entries else ([], None)
    links = relate(entries, Z)
    for e in entries:
        del e["relacionados_declarados"]
    doc = {"version": 1, "vocabulario": vocab, "clusters": clusters, "links": links,
           "similarity": {"kind": "similitud", "method": "coseno sobre TF-IDF del texto y etiquetas del vocabulario",
                          "note": "el top 5 es similitud calculada, no un vínculo declarado; confírmelo antes de citarlo"},
           "matrix": core.matrix(entries, vocab), "entries": entries}
    # Everything is computed (and the site rendered in memory) before the first write.
    pages = render_pages(dict(doc, runs=runs)) if site else None
    (root / "data").mkdir(exist_ok=True)
    (root / "data/landscape.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if names is not None:
        (root / "data/cluster_names.json").write_text(json.dumps(names, ensure_ascii=False, indent=1) + "\n",
                                                      encoding="utf-8")
    if pages is not None:
        write_site(pages, Path(site_dir) if site_dir else root / "docs")
    return {"entries": len(entries), "clusters": clusters, "links": links, "runs": runs, "issues": issues}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build data/landscape.json and the docs/ site from fichas/CT*.md.")
    ap.add_argument("--lenient", action="store_true", help="report validation problems instead of failing")
    ap.add_argument("--recluster", action="store_true", help="run k-means from scratch (review cluster names after)")
    ap.add_argument("--clusters", type=int, default=None, help="number of clusters for a fresh clustering")
    ap.add_argument("--no-site", action="store_true", help="skip rendering docs/")
    ap.add_argument("--root", default=str(REPO), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        result = build(args.root, lenient=args.lenient, recluster=args.recluster, n_clusters=args.clusters,
                       site=not args.no_site)
    except ValidationFailed as exc:
        print(f"validation failed: {len(exc.issues)} problem(s)", file=sys.stderr)
        for issue in exc.issues:
            print("  " + fmt(issue), file=sys.stderr)
        print("fix the fichas or run with --lenient to build with what is valid", file=sys.stderr)
        return 1
    for issue in result["issues"]:
        print(f"{issue['severity']}: {fmt(issue)}", file=sys.stderr)
    print(f"entries={result['entries']} clusters={len(result['clusters'])} links={len(result['links'])} "
          f"runs={len(result['runs'])} issues={len(result['issues'])}")
    for c in result["clusters"]:
        print(c["id"], len(c["members"]), c["name"], "|", ", ".join(c["top_terms"][:6]), "|", c["topics"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
