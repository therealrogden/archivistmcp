"""read_session, read_beat, read_moment."""

from __future__ import annotations

import logging
from typing import Any, Literal

from ..api_lists import fetch_all_list_pages
from ..client import ArchivistClient, ArchivistUpstreamError
from ..server import client, mcp
from ..validation import UuidPathStr

_LOG = logging.getLogger(__name__)
_EXCERPT = 400


def _truncate_excerpt(text: str) -> str:
    if len(text) <= _EXCERPT:
        return text
    return text[:_EXCERPT] + "…"


def _shape_beat_row(b: dict[str, Any], *, include_excerpts: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": b.get("id"),
        "title": b.get("label"),
        "sequence": b.get("index"),
    }
    if include_excerpts:
        c = b.get("content")
        if isinstance(c, str) and c:
            row["content"] = _truncate_excerpt(c)
    return row


async def _beat_row_resolved(archivist: ArchivistClient, b: dict[str, Any]) -> dict[str, Any]:
    bid = b.get("id")
    if isinstance(b.get("content"), str) and b.get("content"):
        return _shape_beat_row(b, include_excerpts=True)
    if isinstance(bid, str):
        detail = await archivist.get(f"/v1/beats/{bid}", with_links=True)
        if isinstance(detail, dict):
            return _shape_beat_row(detail, include_excerpts=True)
    return _shape_beat_row(b, include_excerpts=True)


def _shape_moment_row(m: dict[str, Any], *, include_excerpts: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": m.get("id"),
        "session_id": m.get("session_id"),
        "label": m.get("label"),
        "index": m.get("index"),
    }
    if include_excerpts:
        c = m.get("content")
        if isinstance(c, str) and c:
            row["content"] = _truncate_excerpt(c)
    return row


@mcp.tool
async def read_session(
    session_id: UuidPathStr,
    include: list[Literal["beats", "moments", "cast_analysis"]] = [],
    include_excerpts: bool = False,
) -> dict[str, Any]:
    """Fetch a session; optional beats, moments, and cast-analysis fanouts (read-only)."""
    raw = await client.get(f"/v1/sessions/{session_id}", with_links=True)
    if not isinstance(raw, dict):
        return raw
    result: dict[str, Any] = dict(raw)
    inc = frozenset(include)
    if "beats" in inc:
        beats = await fetch_all_list_pages(
            client,
            "/v1/beats",
            campaign_id=client.campaign_id,
            game_session_id=session_id,
        )
        ordered = sorted(beats, key=lambda x: (x.get("index") is None, x.get("index", 0)))
        if include_excerpts:
            result["beats"] = [await _beat_row_resolved(client, b) for b in ordered]
        else:
            result["beats"] = [_shape_beat_row(b, include_excerpts=False) for b in ordered]
    if "moments" in inc:
        moments = await fetch_all_list_pages(
            client,
            "/v1/moments",
            campaign_id=client.campaign_id,
            session_id=session_id,
        )
        ordered_m = sorted(moments, key=lambda x: (x.get("index") is None, x.get("index", 0)))
        result["moments"] = [_shape_moment_row(m, include_excerpts=include_excerpts) for m in ordered_m]
    if "cast_analysis" in inc:
        try:
            ca = await client.get(f"/v1/sessions/{session_id}/cast-analysis")
            if isinstance(ca, dict):
                result["cast_analysis"] = ca
        except ArchivistUpstreamError as exc:
            if exc.status_code != 404:
                raise
            _LOG.debug("cast-analysis 404 for session %s (omitted)", session_id)
    return result


@mcp.tool
async def read_beat(beat_id: UuidPathStr) -> dict[str, Any]:
    """Fetch one beat (read-only). Wikilink markup is preserved."""
    return await client.get(f"/v1/beats/{beat_id}", with_links=True)


@mcp.tool
async def read_moment(moment_id: UuidPathStr) -> dict[str, Any]:
    """Fetch one moment (read-only). Wikilink markup is preserved."""
    return await client.get(f"/v1/moments/{moment_id}", with_links=True)
