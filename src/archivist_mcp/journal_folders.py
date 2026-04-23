"""Resolve or create nested journal folders by path (e.g. ``Items/Mechanics``)."""

from __future__ import annotations

from typing import Any

from .client import ArchivistClient


def _list_page_data(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    raw = body.get("data")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


async def _all_journal_folders(client: ArchivistClient) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        body = await client.get(
            "/v1/journal-folders",
            campaign_id=client.campaign_id,
            page=page,
            size=50,
        )
        chunk = _list_page_data(body)
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


def _find_child(folders: list[dict[str, Any]], *, name: str, parent_id: str | None) -> dict[str, Any] | None:
    for f in folders:
        if f.get("name") != name:
            continue
        pid = f.get("parent_id")
        if parent_id is None and pid is None:
            return f
        if pid == parent_id:
            return f
    return None


def _post_folder_response_id(body: Any) -> str | None:
    if isinstance(body, dict):
        if isinstance(body.get("id"), str):
            return body["id"]
        inner = body.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("id"), str):
            return inner["id"]
    return None


async def ensure_journal_folder_path(client: ArchivistClient, path: str) -> str:
    """Return folder id for ``path`` (no leading/trailing slashes), creating missing segments."""
    path = path.strip().strip("/")
    if not path:
        raise ValueError("journal folder path must not be empty")
    segments = [s for s in path.split("/") if s]
    folders = await _all_journal_folders(client)
    parent_id: str | None = None
    cumulative: list[str] = []
    for seg in segments:
        cumulative.append(seg)
        path_str = "/".join(cumulative)
        found = _find_child(folders, name=seg, parent_id=parent_id)
        if found and isinstance(found.get("id"), str):
            parent_id = found["id"]
            continue
        payload: dict[str, Any] = {
            "world_id": client.campaign_id,
            "name": seg,
            "path": path_str,
        }
        if parent_id is not None:
            payload["parent_id"] = parent_id
        created = await client.post("/v1/journal-folders", json=payload)
        new_id = _post_folder_response_id(created)
        if not new_id:
            raise RuntimeError(f"journal folder create returned no id: {created!r}")
        folders.append({"id": new_id, "name": seg, "parent_id": parent_id})
        parent_id = new_id
    assert parent_id is not None
    return parent_id
