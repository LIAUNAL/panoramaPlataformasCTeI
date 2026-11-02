"""Contract of the ctei-landscape MCP server: tool names, parameters and errors, through the MCP tool layer."""
import asyncio
import json

import pytest

import ctei_landscape_mcp as server
import landscape_db
from mcp.server.mcpserver.exceptions import ToolError

EXPECTED = {
    "search_landscape": {"query", "kind", "scope", "topic", "year_from", "match", "limit"},
    "get_entry": {"entry_id"},
    "related_entries": {"entry_id"},
    "actor_service_matrix": {"scope", "topic"},
    "coverage_gaps": {"reference_path", "reference_id"},
    "taxonomy": set(),
    "export_to_insumos": {"entry_ids", "dest_dir"},
}


@pytest.fixture
def mcp(landscape, monkeypatch):
    monkeypatch.setattr(server, "landscape", landscape)
    return server.mcp


def call(mcp, name, **args):
    result = asyncio.run(mcp.call_tool(name, args))
    if result.structured_content is not None:
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data
    return json.loads(result.content[0].text)


def test_tools_and_parameters_are_exactly_the_contract(mcp):
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert set(tools) == set(EXPECTED)
    for name, params in EXPECTED.items():
        assert set(tools[name].input_schema.get("properties", {})) == params, name
    assert set(tools["get_entry"].input_schema["required"]) == {"entry_id"}
    assert set(tools["export_to_insumos"].input_schema["required"]) == {"entry_ids", "dest_dir"}
    assert "required" not in tools["coverage_gaps"].input_schema or not tools["coverage_gaps"].input_schema["required"]
    assert tools["coverage_gaps"].input_schema["properties"]["reference_id"]["default"] == "CT000"


def test_search_and_get_entry_through_mcp(mcp):
    hits = call(mcp, "search_landscape", query="innovacion", scope="bogota")
    assert [h["id"] for h in hits] == ["CT101"]
    assert call(mcp, "get_entry", entry_id="CT101")["titulo"] == "Plataforma Distrital de Innovación"


def test_unknown_entry_and_bad_filter_raise_tool_errors(mcp):
    with pytest.raises(ToolError, match="search_landscape"):
        call(mcp, "get_entry", entry_id="CT999")
    with pytest.raises(ToolError, match="search_landscape"):
        call(mcp, "related_entries", entry_id="CT999")
    with pytest.raises(ToolError, match="scope"):
        call(mcp, "search_landscape", query="", scope="marte")


def test_matrix_gaps_taxonomy_and_export_through_mcp(mcp, outside_reference, tmp_path, monkeypatch):
    monkeypatch.delenv("CTEI_REFERENCE_PATH", raising=False)
    assert call(mcp, "actor_service_matrix", scope="internacional")["entries"] == 1
    assert call(mcp, "coverage_gaps")["available"] is False
    assert call(mcp, "coverage_gaps", reference_path=str(outside_reference))["total_gaps"] > 0
    assert len(call(mcp, "taxonomy")["topics"]) == 14
    with pytest.raises(ToolError, match="does not exist"):
        call(mcp, "export_to_insumos", entry_ids=["CT101"], dest_dir=str(tmp_path / "missing"))
    dest = tmp_path / "insumos"
    dest.mkdir()
    assert len(call(mcp, "export_to_insumos", entry_ids=["CT101"], dest_dir=str(dest))["written"]) == 2


def test_module_default_landscape_is_a_landscape():
    assert isinstance(server.landscape, landscape_db.Landscape)
