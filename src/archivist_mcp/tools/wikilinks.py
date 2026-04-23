"""Wikilink parsing, resolution against campaign entities, and MCP ``validate_wikilinks``."""

from __future__ import annotations

from typing import Any, get_args

from ..client import ArchivistClient
from ..projections import project_slim
from ..server import client, mcp
from ..validation import ContentStr, EntityKind, ProjectionKind
from .reads_helpers import build_campaign_name_index

_ENTITY_KINDS: frozenset[str] = frozenset(get_args(EntityKind))


def _parse_search_rows(body: Any) -> list[tuple[ProjectionKind, dict[str, Any], float | None]]:
    if not isinstance(body, dict):
        return []
    raw = body.get("data")
    if not isinstance(raw, list):
        return []
    out: list[tuple[ProjectionKind, dict[str, Any], float | None]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in _ENTITY_KINDS:
            continue
        pk: ProjectionKind = kind  # type: ignore[assignment]
        entity = {k: v for k, v in row.items() if k != "kind"}
        score_raw = row.get("score")
        score: float | None
        if isinstance(score_raw, (int, float)):
            score = float(score_raw)
        else:
            score = None
        out.append((pk, entity, score))
    return out


def _find_wikilink_spans(content: str) -> list[tuple[int, int, str, str | None]]:
    """Return ``(start, end_exclusive, target, alias)`` for each well-formed ``[[...]]`` span."""
    spans: list[tuple[int, int, str, str | None]] = []
    i = 0
    while True:
        j = content.find("[[", i)
        if j == -1:
            break
        k = content.find("]]", j + 2)
        if k == -1:
            break
        inner = content[j + 2 : k]
        if "[[" in inner or "]]" in inner:
            i = j + 2
            continue
        parsed = _parse_inner(inner)
        if parsed is None:
            i = j + 2
            continue
        target, alias = parsed
        if not target:
            i = k + 2
            continue
        spans.append((j, k + 2, target, alias))
        i = k + 2
    return spans


def _parse_inner(inner: str) -> tuple[str, str | None] | None:
    if "|" in inner:
        a, b = inner.split("|", 1)
        t = a.strip()
        al = b.strip()
        if not t:
            return None
        return t, al if al else None
    t = inner.strip()
    if not t:
        return None
    return t, None


def _display_name_for_kind(kind: EntityKind, slim: dict[str, Any]) -> str:
    if kind == "journal":
        v = slim.get("title")
        return str(v) if isinstance(v, str) and v else ""
    v = slim.get("name")
    return str(v) if isinstance(v, str) and v else ""


async def _search_candidates(
    archivist: ArchivistClient,
    campaign_id: str,
    query: str,
    *,
    page_size: int = 5,
) -> list[dict[str, Any]]:
    # List endpoints use query param ``size``; /v1/search is unchanged until a live 200 proves otherwise.
    body = await archivist.search_entities_get(
        {"campaign_id": campaign_id, "q": query, "page_size": page_size},
    )
    rows = _parse_search_rows(body)
    out: list[dict[str, Any]] = []
    for rank, (kind, entity, api_score) in enumerate(rows):
        slim = project_slim(entity, kind)
        name = _display_name_for_kind(kind, slim)  # type: ignore[arg-type]
        eid = slim.get("id")
        if not isinstance(eid, str):
            continue
        score = float(api_score) if api_score is not None else 1.0 / float(rank + 1)
        out.append({"name": name or eid, "entity_type": kind, "entity_id": eid, "score": score})
    return out


async def analyze_wikilinks(
    archivist: ArchivistClient,
    campaign_id: str,
    content: str,
) -> dict[str, Any]:
    """Build ``resolved`` / ``unresolved`` report for ``content`` (no mutation)."""
    spans = _find_wikilink_spans(content)
    if not spans:
        return {"resolved": [], "unresolved": []}
    index = await build_campaign_name_index(archivist, campaign_id)
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for _s, _e, target, alias in spans:
        key = target.casefold()
        hit = index.get(key)
        if hit:
            et, eid, _canon = hit
            resolved.append(
                {
                    "name": target,
                    "entity_type": et,
                    "entity_id": eid,
                    "alias": alias,
                },
            )
            continue
        candidates = await _search_candidates(archivist, campaign_id, target)
        unresolved.append({"name": target, "alias": alias, "candidates": candidates})
    return {"resolved": resolved, "unresolved": unresolved}


async def strip_unresolved_wikilinks(
    archivist: ArchivistClient,
    campaign_id: str,
    content: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Replace unresolved ``[[...]]`` with display plain text; return new body + strip log rows."""
    spans = _find_wikilink_spans(content)
    if not spans:
        return content, []
    index = await build_campaign_name_index(archivist, campaign_id)
    stripped_log: list[dict[str, Any]] = []
    replacements: list[tuple[int, int, str]] = []
    for start, end, target, alias in spans:
        key = target.casefold()
        if key in index:
            continue
        candidates = await _search_candidates(archivist, campaign_id, target)
        display = alias if alias is not None else target
        stripped_log.append({"name": target, "alias": alias, "candidates": candidates})
        replacements.append((start, end, display))
    if not replacements:
        return content, []
    parts: list[str] = []
    pos = 0
    for start, end, text in sorted(replacements):
        parts.append(content[pos:start])
        parts.append(text)
        pos = end
    parts.append(content[pos:])
    return "".join(parts), stripped_log


@mcp.tool
async def validate_wikilinks(content: ContentStr) -> dict[str, Any]:
    """Parse ``[[Name]]`` / ``[[Name|alias]]`` wikilinks, resolve against the campaign, return a report.

    Exact matches (case-insensitive) resolve to entity ids. Near-misses appear only as search
    candidates under ``unresolved``; fuzzy matches are never applied automatically.
    """
    return await analyze_wikilinks(client, client.campaign_id, content)


__all__ = ["analyze_wikilinks", "strip_unresolved_wikilinks", "validate_wikilinks"]
