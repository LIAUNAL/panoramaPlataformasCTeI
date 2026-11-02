"""ctei-landscape MCP server (stdio): a study of CTeI platforms, software, patents and articles as input for
requirements work on platforms like Hēma.

    uvx --from git+https://github.com/LIAUNAL/panoramaPlataformasCTeI ctei-landscape-mcp   # installed from GitHub
    panoramaCTeI mcp                                                                         # from a local checkout

Every tool reads the SQLite FTS5 index from tools/landscape_db.py, rebuilt from data/landscape.json on change.
The private Hēma reference (CT000) is never part of this package: coverage_gaps reads it from a path outside
the repository (reference_path or CTEI_REFERENCE_PATH).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from landscape_db import Landscape  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

landscape = Landscape()
mcp = MCPServer(
    "ctei-landscape",
    instructions=(
        "ctei-landscape: fichas (CT###) of science, technology and innovation (CTeI) platforms, software, "
        "patents and articles in four scopes (bogota, nacional, latam, internacional), each with its actors, "
        "services and interactions from a closed vocabulary, verifiable evidence and consultation date. Use it "
        "to ground requirements of CTeI articulation platforms: search_landscape to find entries, get_entry for "
        "the full ficha, related_entries for typed relations and similar entries, actor_service_matrix for "
        "what the referents offer, coverage_gaps to compare the matrix with a reference ficha (the private "
        "Hēma reference CT000 lives outside this repository: pass reference_path or set CTEI_REFERENCE_PATH), "
        "taxonomy for filters, export_to_insumos to copy fichas and the matrix into a project's inputs folder. "
        "Ficha text is in Spanish; cite entries by id ([CT101]) and their evidence. Top-5 links are similarity, "
        "not declared relations: confirm them before citing."
    ),
)


@mcp.tool()
def search_landscape(query: str = "", kind: str | None = None, scope: str | None = None, topic: str | None = None,
                     year_from: int | None = None, match: str = "any", limit: int = 10) -> list[dict]:
    """Full-text search (BM25, accent-insensitive) over titles, operators, countries, topics, actors, services,
    interactions, description and ideas; best matches first. Common words (de, la, the…) are ignored.
    match: "any" (default, any word may match: exploring) or "all" (every word must match: precise).

    kind: plataforma | software | patente | articulo | otro. scope: bogota | nacional | latam | internacional.
    topic: F01-F14 (see taxonomy). year_from: e.g. 2020. With an empty query, lists the filtered entries newest
    first. limit: 1-100.
    """
    try:
        return landscape.search(query, kind=kind, scope=scope, topic=topic, year_from=year_from, limit=limit,
                                match=match)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def get_entry(entry_id: str) -> dict:
    """Full record of one entry (CT###) with its Markdown ficha, evidence, consultation date and topic names."""
    entry = landscape.get_entry(entry_id)
    if entry is None:
        raise ToolError(f"no entry with id {entry_id!r}; use search_landscape to find ids")
    return entry


@mcp.tool()
def related_entries(entry_id: str) -> dict:
    """Typed relations of an entry (similar-a, implementa, estudiado-en; out and in), its five most similar
    entries (similarity, not declared links) and the other entries of its cluster."""
    rel = landscape.related_entries(entry_id)
    if rel is None:
        raise ToolError(f"no entry with id {entry_id!r}; use search_landscape to find ids")
    return rel


@mcp.tool()
def actor_service_matrix(scope: str | None = None, topic: str | None = None) -> dict:
    """Actors, services and interactions aggregated over the entries (optionally one scope and/or one topic),
    each with the ids that back it, its count and its count per scope (bogota, nacional, latam, internacional)."""
    try:
        return landscape.actor_service_matrix(scope=scope, topic=topic)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def coverage_gaps(reference_path: str | None = None, reference_id: str = "CT000") -> dict:
    """What the matrix has and a reference ficha does not: candidate requirements, by actors, services and
    interactions, each with its supporting ids; plus shared labels and labels only the reference has.
    Deterministic set difference of normalized labels, no model judgment.

    The reference is read from reference_path, else from the CTEI_REFERENCE_PATH environment variable (the
    private Hēma ficha CT000, kept outside this public repository). reference_id="HEMA-publico" uses the public
    description fichas/HEMA-publico.md when it exists; an entry id (CT###) compares against that entry.
    Without a reference, returns available=false and a message saying how to provide one."""
    return landscape.coverage_gaps(reference_path=reference_path, reference_id=reference_id)


@mcp.tool()
def taxonomy() -> dict:
    """Topics (F01-F14), types, scopes and clusters with their entry counts, the relation types and the closed
    vocabulary of actors, services and interactions, to pick search filters."""
    return landscape.taxonomy()


@mcp.tool()
def export_to_insumos(entry_ids: list[str], dest_dir: str) -> dict:
    """Copy the fichas of the given entries into an existing folder, named ctei-<file>.md, plus
    ctei-landscape-matriz.md with their actor/service/interaction matrix; e.g.
    .aracne-sdlc-ai/bmad/planning-artifacts/inputs/. Refuses a folder that does not exist."""
    try:
        return landscape.export(entry_ids, dest_dir)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def main():
    mcp.run()


if __name__ == "__main__":
    main()
