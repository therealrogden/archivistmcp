"""Paginated list helpers for Archivist list endpoints."""

from __future__ import annotations

from typing import Any

from .client import ArchivistClient


def list_data(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    raw = body.get("data")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


async def fetch_all_list_pages(client: ArchivistClient, path: str, **params: Any) -> list[dict[str, Any]]:
    """Fetch every page of a ``data``-enveloped list (uses ``page`` / ``size``)."""
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        body = await client.get(path, page=page, size=50, **params)
        chunk = list_data(body)
        out.extend(chunk)
        if not chunk:
            break
        pages = 1
        if isinstance(body, dict):
            pages = int(body.get("pages") or 1)
        if page >= pages:
            break
        page += 1
    return out
