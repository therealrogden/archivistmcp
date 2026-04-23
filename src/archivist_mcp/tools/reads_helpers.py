"""Shared helpers for read_* tools and wikilink resolution (name index, slim fetches, link fanout)."""

from __future__ import annotations

import logging

from ..api_lists import fetch_all_list_pages
from ..client import ArchivistClient, ArchivistUpstreamError
from ..projections import character_display_name, project_slim
from ..validation import EntityKind, ProjectionKind

_LOG = logging.getLogger("archivist_mcp.tools.reads_helpers")

# (entity_kind, list path, JSON field for display name on list rows)
_LIST_NAME_SPECS: list[tuple[EntityKind, str, str]] = [
    ("character", "/v1/characters", "name"),
    ("item", "/v1/items", "name"),
    ("faction", "/v1/factions", "name"),
    ("location", "/v1/locations", "name"),
    ("quest", "/v1/quests", "quest_name"),
    ("journal", "/v1/journals", "title"),
]

_DETAIL_PREFIX: dict[EntityKind, str] = {
    "character": "/v1/characters/",
    "item": "/v1/items/",
    "faction": "/v1/factions/",
    "location": "/v1/locations/",
    "quest": "/v1/quests/",
    "journal": "/v1/journals/",
}


async def build_campaign_name_index(
    client: ArchivistClient,
    campaign_id: str,
) -> dict[str, tuple[EntityKind, str, str]]:
    """Lowercase exact lookup: ``name.lower()`` -> ``(entity_kind, entity_id, canonical_name)``.

    First row wins when duplicate names exist across or within kinds (stable kind order).
    """
    index: dict[str, tuple[EntityKind, str, str]] = {}
    for kind, path, name_key in _LIST_NAME_SPECS:
        rows = await fetch_all_list_pages(client, path, campaign_id=campaign_id)
        for row in rows:
            eid = row.get("id")
            if not isinstance(eid, str):
                continue
            if kind == "character":
                name = character_display_name(row)
            else:
                v = row.get(name_key)
                if not isinstance(v, str) or not v.strip():
                    continue
                name = v.strip()
            if not name:
                continue
            key = name.casefold()
            if key in index:
                continue
            index[key] = (kind, eid, name)
    return index


async def slim_entity_by_id(
    client: ArchivistClient,
    entity_kind: EntityKind,
    entity_id: str,
    *,
    with_links: bool = True,
) -> dict[str, Any] | None:
    """GET one entity and return :func:`project_slim` row; ``None`` on 404."""
    prefix = _DETAIL_PREFIX.get(entity_kind)
    if not prefix:
        return None
    try:
        raw = await client.get(f"{prefix}{entity_id}", with_links=with_links)
    except ArchivistUpstreamError as exc:
        if exc.status_code == 404:
            return None
        raise
    if not isinstance(raw, dict):
        return None
    pk: ProjectionKind = entity_kind  # type: ignore[assignment]
    return project_slim(raw, pk)


async def character_neighbor_slugs(
    client: ArchivistClient,
    campaign_id: str,
    character_id: str,
    *,
    want_faction: bool,
    want_location: bool,
) -> dict[str, dict[str, Any] | None]:
    """Resolve first faction / location linked from ``character_id`` via campaign links."""
    want: set[str] = set()
    if want_faction:
        want.add("faction")
    if want_location:
        want.add("location")
    out: dict[str, dict[str, Any] | None] = {}
    if not want:
        return out

    rows = await fetch_all_list_pages(
        client,
        f"/v1/campaigns/{campaign_id}/links",
        from_id=character_id,
        from_type="character",
    )
    seen_kind: set[str] = set()
    for link in rows:
        to_type_raw = link.get("to_type")
        to_id = link.get("to_id")
        if not isinstance(to_type_raw, str) or not isinstance(to_id, str):
            continue
        to_type = to_type_raw.lower()
        if to_type not in want or to_type in seen_kind:
            continue
        slim = await slim_entity_by_id(client, to_type, to_id)  # type: ignore[arg-type]
        if slim is None:
            _LOG.debug("neighbor %s %s missing after link edge", to_type, to_id)
            continue
        out[to_type] = slim
        seen_kind.add(to_type)
        if seen_kind == want:
            break
    for k in want:
        out.setdefault(k, None)
    return out


__all__ = [
    "build_campaign_name_index",
    "character_neighbor_slugs",
    "slim_entity_by_id",
]
