"""Tests for tools/build_landscape.py: validation against data/vocabulario.json, relations, clusters, outputs."""
import codecs
import json
import subprocess
import sys

import pytest

import build_landscape
from conftest import FICHAS, REPO, write_ficha


def landscape_json(root):
    return json.loads((root / "data" / "landscape.json").read_text(encoding="utf-8"))


def broken(field_line, replacement, name="CT101-plataforma-bogota.md"):
    text = FICHAS[name]
    assert field_line in text
    return text.replace(field_line, replacement)


def messages(exc):
    return [f"{i['file']}: {i['field']}: {i['message']}" for i in exc.value.issues]


def test_valid_build_writes_entries_without_the_template(built):
    doc = landscape_json(built)
    assert [e["id"] for e in doc["entries"]] == ["CT101", "CT102", "CT301", "CT501"]
    e = doc["entries"][0]
    assert e["file"] == "CT101-plataforma-bogota.md"
    assert e["consultado"] == "2026-11-01"
    assert e["secciones"]["ideas"].startswith("Emparejamiento automático")
    assert doc["vocabulario"]["alcances"]["bogota"] == "Bogotá"


@pytest.mark.parametrize("old,new,field,fragment", [
    ("actores: [universidad, empresa, emprendedor]", "actores: [universidad, robot]", "actores", "unknown label 'robot'"),
    ("tipo: plataforma", "tipo: portal", "tipo", "unknown tipo 'portal'"),
    ("alcance: bogota", "alcance: regional", "alcance", "unknown alcance 'regional'"),
    ('evidencia: ["https://example.org/plataforma-distrital"]', "evidencia: []", "evidencia", "missing required field"),
    ("consultado: 2026-11-01\nrelacionados: [{id: CT102", "relacionados: [{id: CT102", "consultado", "missing required field"),
    ("temas: [F01, F03]", "temas: [F01, F99]", "temas", "unknown label 'F99'"),
    ("relacionados: [{id: CT102, tipo: similar-a}]", "relacionados: [{id: CT102, tipo: copia-de}]", "relacionados", "unknown relation tipo"),
    ("relacionados: [{id: CT102, tipo: similar-a}]", "relacionados: [{id: CT999, tipo: similar-a}]", "relacionados", "CT999"),
    ('evidencia: ["https://example.org/plataforma-distrital"]', 'evidencia: ["sitio oficial"]', "evidencia", "not a URL, a DOI"),
])
def test_validation_errors_name_file_and_field(full_root, old, new, field, fragment):
    write_ficha(full_root, "CT101-plataforma-bogota.md", broken(old, new))
    with pytest.raises(build_landscape.ValidationFailed) as exc:
        build_landscape.build(full_root, site=False)
    hits = [m for m in messages(exc) if m.startswith(f"fichas/CT101-plataforma-bogota.md: {field}:") and fragment in m]
    assert hits, messages(exc)
    assert not (full_root / "data" / "landscape.json").exists()


def test_duplicate_id_is_an_error_naming_both_files(full_root):
    write_ficha(full_root, "CT101-copia.md", FICHAS["CT101-plataforma-bogota.md"])
    with pytest.raises(build_landscape.ValidationFailed) as exc:
        build_landscape.build(full_root, site=False)
    dup = [m for m in messages(exc) if "duplicate id CT101" in m]
    assert dup and "CT101-plataforma-bogota.md" in dup[0] and "CT101-copia.md" in dup[0] and ": id: " in dup[0]


def test_private_reference_id_is_refused_even_when_lenient(full_root):
    text = FICHAS["CT102-red-nacional.md"].replace("id: CT102", "id: CT000")
    write_ficha(full_root, "CT000-hema.md", text)
    with pytest.raises(build_landscape.ValidationFailed):
        build_landscape.build(full_root, site=False)
    result = build_landscape.build(full_root, site=False, lenient=True)
    assert "CT000" not in [e["id"] for e in landscape_json(full_root)["entries"]]
    assert any("private Hēma reference" in i["message"] for i in result["issues"])


def test_lenient_reports_and_keeps_valid_labels(full_root):
    write_ficha(full_root, "CT101-plataforma-bogota.md",
                broken("actores: [universidad, empresa, emprendedor]", "actores: [universidad, robot]"))
    write_ficha(full_root, "CT102-red-nacional.md", FICHAS["CT102-red-nacional.md"].replace("tipo: plataforma", "tipo: portal"))
    result = build_landscape.build(full_root, site=False, lenient=True)
    doc = landscape_json(full_root)
    ids = [e["id"] for e in doc["entries"]]
    assert "CT102" not in ids  # a fatal issue (bad tipo) keeps the ficha out
    assert doc["entries"][ids.index("CT101")]["actores"] == ["universidad"]
    assert {i["field"] for i in result["issues"]} >= {"actores", "tipo"}


def test_cli_strict_exits_1_and_lenient_exits_0(full_root):
    write_ficha(full_root, "CT101-plataforma-bogota.md", broken("tipo: plataforma", "tipo: portal"))
    tool = str(REPO / "tools" / "build_landscape.py")
    strict = subprocess.run([sys.executable, tool, "--root", str(full_root), "--no-site"], capture_output=True, text=True)
    assert strict.returncode == 1
    assert "fichas/CT101-plataforma-bogota.md: tipo:" in strict.stderr
    lenient = subprocess.run([sys.executable, tool, "--root", str(full_root), "--no-site", "--lenient"],
                             capture_output=True, text=True)
    assert lenient.returncode == 0, lenient.stderr
    assert "entries=3" in lenient.stdout
    assert "tipo" in lenient.stderr


def test_typed_relations_are_stored_in_both_directions_and_similarity_is_marked(built):
    doc = landscape_json(built)
    by = {e["id"]: e for e in doc["entries"]}
    assert {"id": "CT102", "tipo": "similar-a", "direction": "out"} in by["CT101"]["relacionados"]
    assert {"id": "CT101", "tipo": "similar-a", "direction": "in"} in by["CT102"]["relacionados"]
    assert {"id": "CT301", "tipo": "estudiado-en", "direction": "in"} in by["CT501"]["relacionados"]
    assert {"from": "CT301", "to": "CT501", "rel": "estudiado-en", "declared": True} in doc["links"]
    top = by["CT101"]["top5"]
    assert 1 <= len(top) <= 5 and all(t["id"] != "CT101" and 0 <= t["sim"] <= 1 for t in top)
    assert doc["similarity"]["kind"] == "similitud"


def test_every_entry_has_a_cluster_and_names_are_placeholders_once(built):
    doc = landscape_json(built)
    members = sorted(m for c in doc["clusters"] for m in c["members"])
    assert members == ["CT101", "CT102", "CT301", "CT501"]
    names_path = built / "data" / "cluster_names.json"
    names = json.loads(names_path.read_text(encoding="utf-8"))
    assert set(names) == {c["id"] for c in doc["clusters"]}
    names[doc["clusters"][0]["id"]] = "Nombre revisado"
    names_path.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    build_landscape.build(built, site=False)
    assert landscape_json(built)["clusters"][0]["name"] == "Nombre revisado"


def test_clusters_are_stable_when_entries_are_added(root):
    build_landscape.build(root, site=False, lenient=True, n_clusters=2)
    before = {m: c["id"] for c in landscape_json(root)["clusters"] for m in c["members"]}
    write_ficha(root, "CT501-articulo-latam.md", FICHAS["CT501-articulo-latam.md"])
    build_landscape.build(root, site=False)
    after = {m: c["id"] for c in landscape_json(root)["clusters"] for m in c["members"]}
    assert {k: after[k] for k in before} == before
    assert after["CT501"] in set(before.values())


def test_recluster_regroups_from_scratch(root):
    build_landscape.build(root, site=False, lenient=True, n_clusters=2)
    write_ficha(root, "CT501-articulo-latam.md", FICHAS["CT501-articulo-latam.md"])
    build_landscape.build(root, site=False, recluster=True, n_clusters=3)
    assert len(landscape_json(root)["clusters"]) == 3


def test_matrix_in_landscape_json_counts_by_scope(built):
    mat = landscape_json(built)["matrix"]
    uni = next(r for r in mat["actores"] if r["label"] == "universidad")
    assert uni["count"] == 3 and uni["entries"] == ["CT101", "CT102", "CT301"]
    assert uni["by_scope"] == {"bogota": 1, "nacional": 1, "latam": 0, "internacional": 1}


def test_runs_jsonl_is_read_and_bad_lines_are_reported(built):
    (built / "data" / "runs.jsonl").write_text(
        json.dumps({"date": "2026-11-01", "query": "emparejamiento", "scope": "bogota",
                    "fichas_consulted": ["ct101", "CT102"], "fichas_exported": ["CT101"]}) + "\n"
        + "{not json\n\n", encoding="utf-8")
    result = build_landscape.build(built, site=False)
    assert result["runs"][0]["fichas_consulted"] == ["CT101", "CT102"]
    assert any(i["file"] == "data/runs.jsonl" for i in result["issues"])


def test_site_is_rendered_with_dashboard_constellation_and_data(built):
    build_landscape.build(built, site=True)
    site = built / "docs"
    for name in ("index.html", "constelacion.html", "data/landscape.json", "logo_atenea_horizontal.png",
                 "favicon.ico", "favicon.png", "apple-touch-icon.png", "THIRD_PARTY_NOTICES.md"):
        assert (site / name).exists(), name
    retired = [codecs.decode(n, "rot13") for n in ("rfphqb_hany.fit", "ybtb_ynoVN.cat")]
    assert not any((site / n).exists() for n in retired)
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "CT101" in index and "@@" not in index
    assert 'src="logo_atenea_horizontal.png"' in index
    # Names that must not appear on the published site, stored in ROT13 so a repository-wide grep for them stays
    # empty; the GitHub repository URL is the only allowed trace of the hosting organisation.
    banned = [codecs.decode(n, "rot13") for n in
              ("hany", "havirefvqnq anpvbany", "znavmnyrf", "ynovn", "rfphqb", "napvmne", "cncrefzvgu", "cynhfvovyvgl")]
    for page_name in ("index.html", "constelacion.html", "THIRD_PARTY_NOTICES.md"):
        text = (site / page_name).read_text(encoding="utf-8").replace(build_landscape.REPO_URL, "").lower()
        for name in banned:
            assert name not in text, (page_name, name)
    page = (site / "constelacion.html").read_text(encoding="utf-8")
    assert "three.js authors, MIT License" in page
    notices = (site / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Permission is hereby granted" in notices and "tools/vendor/atlas3d/LICENSE" in notices
    assert "three.js" in (site / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    page = (site / "constelacion.html").read_text(encoding="utf-8")
    assert "CT301" in page and "@@" not in page


def test_failed_render_leaves_previous_outputs_untouched(built, monkeypatch):
    before = (built / "data" / "landscape.json").read_bytes()
    names = (built / "data" / "cluster_names.json").read_bytes()
    write_ficha(built, "CT502-otro.md", FICHAS["CT501-articulo-latam.md"].replace("CT501", "CT502"))
    monkeypatch.setattr(build_landscape, "TOOLS", built / "no-tools")
    with pytest.raises((FileNotFoundError, SystemExit)):
        build_landscape.build(built, site=True)
    assert (built / "data" / "landscape.json").read_bytes() == before
    assert (built / "data" / "cluster_names.json").read_bytes() == names
