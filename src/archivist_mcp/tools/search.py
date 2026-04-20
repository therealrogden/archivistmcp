"""Lexical ``search_entities`` tool (``GET /v1/search``)."""

from __future__ import annotations

from typing import Any, get_args

from ..projections import project_slim
from ..server import client, mcp
from ..validation import EntityKind, NonEmptySearchStr, ProjectionKind, SearchFilters

_ENTITY_KINDS: frozenset[str] = frozenset(get_args(EntityKind))


def _parse_search_rows(body: Any) -> list[tuple[ProjectionKind, dict[str, Any]]]:
    """Parse ``{"data": [{"kind": "character", ...}, ...]}`` from Archivist."""
    if not isinstance(body, dict):
        return []
    raw = body.get("data")
    if not isinstance(raw, list):
        return []
    out: list[tuple[ProjectionKind, dict[str, Any]]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _ENTITY_KINDS:
            continue
        pk: ProjectionKind = kind  # type: ignore[assignment]
        entity = {k: v for k, v in row.items() if k != "kind"}
        out.append((pk, entity))
    return out


def _search_query_params(
    *,
    query: str,
    types: list[EntityKind] | None,
    filters: SearchFilters | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"campaign_id": client.campaign_id, "q": query}
    if types:
        params["types"] = list(types)
    if filters is not None:
        params.update(filters.model_dump(exclude_none=True))
    return params


@mcp.tool
async def search_entities(
    query: NonEmptySearchStr,
    types: list[EntityKind] | None = None,
    filters: SearchFilters | None = None,
) -> list[dict[str, Any]]:
    """Lexical discovery across characters, items, factions, locations, quests, and journals.

    Optional ``types`` narrows entity kinds (union). Optional ``filters`` are typed and
    forwarded as query parameters; unknown filter keys are rejected at validation.
    Results use the same slim projections as list resources, plus a ``kind`` field.
    """
    params = _search_query_params(query=query, types=types, filters=filters)
    body = await client.search_entities_get(params)
    rows = _parse_search_rows(body)
    if types:
        allowed = frozenset(types)
        rows = [(k, e) for k, e in rows if k in allowed]
    results: list[dict[str, Any]] = []
    for kind, entity in rows:
        slim = project_slim(entity, kind)
        results.append({**slim, "kind": kind})
    return results
