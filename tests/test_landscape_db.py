"""Tests for tools/landscape_db.py, the SQLite FTS5 query layer behind the ctei-landscape MCP server."""
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

import landscape_db
from conftest import REFERENCE, write_ficha


def test_index_holds_every_entry(landscape, built):
    landscape.search("laboratorios")
    con = sqlite3.connect(built / "data" / "landscape.db")
    assert con.execute("select count(*) from entries").fetchone()[0] == 4
    assert con.execute("select count(*) from entries_fts").fetchone()[0] == 4


def test_search_is_accent_insensitive_and_ranked(landscape):
    hits = landscape.search("innovacion distrital")
    assert hits[0]["id"] == "CT101"
    assert "snippet" in hits[0] and "score" in hits[0]
    assert [h["id"] for h in landscape.search("tecnología")] == [h["id"] for h in landscape.search("tecnologia")]


def test_search_finds_vocabulary_names_and_ignores_fts_syntax(landscape):
    assert "CT102" in [h["id"] for h in landscape.search("Reserva de equipos")]
    assert landscape.search('"laboratorios" AND (reserva* -') == landscape.search("laboratorios reserva")
    assert landscape.search("de la por") == []


def test_search_filters_kind_scope_topic_year_and_match(landscape):
    assert [h["id"] for h in landscape.search("CRIS", kind="software")] == ["CT301"]
    assert [h["id"] for h in landscape.search("", scope="latam")] == ["CT501"]
    assert {h["id"] for h in landscape.search("", topic="f13")} == {"CT301", "CT501"}
    assert {h["id"] for h in landscape.search("", year_from=2021)} == {"CT101", "CT501"}
    assert landscape.search("laboratorios CRIS", match="all") == []
    assert {h["id"] for h in landscape.search("laboratorios CRIS", match="any")} >= {"CT102", "CT301"}
    with pytest.raises(ValueError):
        landscape.search("", scope="marte")


def test_empty_query_lists_newest_first(landscape):
    assert [h["id"] for h in landscape.search("")] == ["CT501", "CT101", "CT102", "CT301"]


def test_get_entry_returns_record_markdown_and_evidence(landscape):
    e = landscape.get_entry("ct301")
    assert e["evidencia"] == ["https://example.org/cris", "doi:10.1234/cris.2015"]
    assert e["markdown"].startswith("---\nid: CT301")
    assert e["topic_names"] == ["Software de gestión de la investigación (CRIS)", "Gestión y seguimiento de proyectos"]
    assert e["alcance_nombre"] == "Internacional"
    assert landscape.get_entry("CT999") is None


def test_related_entries_merge_typed_relations_similarity_and_cluster(landscape):
    rel = landscape.related_entries("CT101")
    assert {"id": "CT102", "tipo": "similar-a", "direction": "out",
            "titulo": "Red Nacional de Laboratorios"} in rel["relations"]
    assert 1 <= len(rel["similar"]) <= 5 and "similitud" in rel["similarity_note"]
    assert all(s["id"] != "CT101" for s in rel["same_cluster"])
    assert landscape.related_entries("CT501")["relations"][0] == {
        "id": "CT301", "tipo": "estudiado-en", "direction": "in", "titulo": "Sistema CRIS de código abierto"}
    assert landscape.related_entries("CT999") is None


def test_actor_service_matrix_aggregates_with_ids_counts_and_scopes(landscape):
    mat = landscape.actor_service_matrix()
    assert mat["entries"] == 4
    uni = next(r for r in mat["actores"] if r["label"] == "universidad")
    assert uni == {"label": "universidad", "name": "Universidad o institución de educación superior", "count": 3,
                   "entries": ["CT101", "CT102", "CT301"],
                   "by_scope": {"bogota": 1, "nacional": 1, "latam": 0, "internacional": 1}}
    rep = next(r for r in mat["interacciones"] if r["label"] == "reporte-indicadores")
    assert rep["entries"] == ["CT301", "CT501"]
    assert mat["by_scope"] == {"bogota": 1, "nacional": 1, "latam": 1, "internacional": 1}


def test_actor_service_matrix_filters_scope_and_topic(landscape):
    assert landscape.actor_service_matrix(scope="bogota")["entries"] == 1
    mat = landscape.actor_service_matrix(topic="F01")
    assert mat["entries"] == 2
    assert {r["label"] for r in mat["servicios"]} == {
        "directorio-actores", "emparejamiento-oferta-demanda", "convocatorias", "acceso-laboratorios", "reserva-equipos"}


def test_coverage_gaps_with_a_reference_outside_the_repo(landscape, outside_reference, built):
    assert not str(outside_reference).startswith(str(built))
    gaps = landscape.coverage_gaps(reference_path=str(outside_reference))
    assert gaps["available"] is True and gaps["reference_id"] == "CT000"
    actor_gaps = [g["label"] for g in gaps["actores"]["gaps"]]
    # universidad and empresa are in the reference; "Centro de Investigación" normalizes to centro-de-investigacion,
    # which is not the vocabulary label centro-investigacion, so it stays a gap: the comparison is literal.
    assert "universidad" not in actor_gaps and "empresa" not in actor_gaps
    assert actor_gaps[0] == "investigador"  # two supporting entries, the largest gap first
    assert next(g for g in gaps["actores"]["gaps"] if g["label"] == "investigador")["entries"] == ["CT301", "CT501"]
    assert "servicio-propio" in gaps["servicios"]["reference_only"]
    assert "directorio-actores" in gaps["servicios"]["shared"]
    assert gaps["total_gaps"] == sum(len(gaps[f]["gaps"]) for f in ("actores", "servicios", "interacciones"))


def test_coverage_gaps_reads_the_reference_path_from_the_environment(landscape, outside_reference, monkeypatch):
    monkeypatch.setenv("CTEI_REFERENCE_PATH", str(outside_reference))
    assert landscape.coverage_gaps()["available"] is True


def test_coverage_gaps_without_reference_returns_a_clear_message(landscape, monkeypatch, tmp_path):
    monkeypatch.delenv("CTEI_REFERENCE_PATH", raising=False)
    out = landscape.coverage_gaps()
    assert out["available"] is False
    assert "CTEI_REFERENCE_PATH" in out["message"] and "reference_path" in out["message"]
    missing = landscape.coverage_gaps(reference_path=str(tmp_path / "nope.md"))
    assert missing["available"] is False and "nope.md" in missing["message"]


def test_coverage_gaps_never_reads_ct000_from_the_public_fichas(landscape, built, monkeypatch):
    monkeypatch.delenv("CTEI_REFERENCE_PATH", raising=False)
    write_ficha(built, "CT000-hema.md", REFERENCE)
    assert landscape.coverage_gaps(reference_id="CT000")["available"] is False


def test_coverage_gaps_accepts_the_public_hema_description(landscape, built, monkeypatch):
    monkeypatch.delenv("CTEI_REFERENCE_PATH", raising=False)
    write_ficha(built, "HEMA-publico.md", REFERENCE.replace("id: CT000", "id: HEMA-publico"))
    out = landscape.coverage_gaps(reference_id="HEMA-publico")
    assert out["available"] is True and out["reference_id"] == "HEMA-publico"


def test_taxonomy_lists_topics_types_scopes_and_clusters_with_counts(landscape):
    tax = landscape.taxonomy()
    f13 = next(t for t in tax["topics"] if t["id"] == "F13")
    assert f13 == {"id": "F13", "name": "Software de gestión de la investigación (CRIS)", "entries": 2}
    assert len(tax["topics"]) == 14
    assert {t["id"]: t["entries"] for t in tax["types"]}["plataforma"] == 2
    assert {s["id"]: s["entries"] for s in tax["scopes"]} == {"bogota": 1, "nacional": 1, "latam": 1, "internacional": 1}
    assert sum(c["entries"] for c in tax["clusters"]) == 4
    assert tax["relations"] == ["similar-a", "implementa", "estudiado-en"]


def test_export_copies_fichas_and_a_matrix_into_an_existing_folder(landscape, tmp_path):
    dest = tmp_path / "insumos"
    dest.mkdir()
    out = landscape.export(["CT101", "ct301", "CT999"], str(dest))
    names = sorted(Path(p).name for p in out["written"])
    assert names == ["ctei-CT101-plataforma-bogota.md", "ctei-CT301-cris-internacional.md", "ctei-landscape-matriz.md"]
    assert out["missing"] == ["CT999"]
    matriz = (dest / "ctei-landscape-matriz.md").read_text(encoding="utf-8")
    assert "Fichas consideradas: 2." in matriz and "CT101, CT301" in matriz
    assert (dest / "ctei-CT101-plataforma-bogota.md").read_text(encoding="utf-8").startswith("---\nid: CT101")


def test_export_refuses_a_missing_folder(landscape, tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        landscape.export(["CT101"], str(tmp_path / "no-such-dir"))
    assert not (tmp_path / "no-such-dir").exists()


def test_default_paths_use_the_checkout_data_when_present(built):
    tools = built / "tools"
    tools.mkdir()
    assert landscape_db.default_paths(tools) == (built / "data" / "landscape.json", built / "data" / "landscape.db")


def test_default_paths_in_an_installed_wheel_cache_the_index(tmp_path, monkeypatch):
    pkg = tmp_path / "site-packages" / "ctei_landscape"
    (pkg / "data").mkdir(parents=True)
    (pkg / "data" / "landscape.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert landscape_db.default_paths(pkg) == (pkg / "data" / "landscape.json",
                                               tmp_path / "cache" / "ctei-landscape" / "landscape.db")


def test_index_rebuilds_when_landscape_json_changes(landscape, built):
    assert len(landscape.search("")) == 4
    path = built / "data" / "landscape.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["entries"] = doc["entries"][:1]
    path.write_text(json.dumps(doc), encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))
    assert len(landscape.search("")) == 1


def test_empty_reference_env_var_counts_as_unset(landscape, monkeypatch):
    monkeypatch.setenv("CTEI_REFERENCE_PATH", "")
    out = landscape.coverage_gaps()
    assert out["available"] is False and "CTEI_REFERENCE_PATH" in out["message"]
