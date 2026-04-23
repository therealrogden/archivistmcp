"""Journal entry upsert (DESIGN.md step 14)."""

from __future__ import annotations

from typing import Any

from ..api_lists import list_data
from ..server import client, mcp
from ..validation import ContentStr, ShortTitleStr, TagsList, UuidPathStr


async def find_journal_by_folder_and_title(*, folder_id: str, title: str) -> tuple[str | None, str | None]:
    """Return ``(journal_id, content)`` when a journal with the folder and title exists."""
    page = 1
    while True:
        body = await client.get(
            "/v1/journals",
            campaign_id=client.campaign_id,
            page=page,
            size=50,
        )
        rows = list_data(body)
        for row in rows:
            if row.get("folder_id") == folder_id and row.get("title") == title:
                jid = row.get("id")
                if isinstance(jid, str):
                    detail = await client.get(f"/v1/journals/{jid}")
                    c = detail.get("content") if isinstance(detail.get("content"), str) else ""
                    return jid, c
        if not rows:
            break
        pages = int(body.get("pages", 1)) if isinstance(body, dict) else 1
        if page >= pages:
            break
        page += 1
    return None, None


def _journal_create_id(body: Any) -> str | None:
    if isinstance(body, dict):
        if isinstance(body.get("id"), str):
            return body["id"]
        inner = body.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("id"), str):
            return inner["id"]
    return None


@mcp.tool
async def upsert_journal_entry(
    folder_id: UuidPathStr,
    title: ShortTitleStr,
    content: ContentStr,
    tags: TagsList | None = None,
) -> dict[str, Any]:
    """Create or update a journal entry keyed by ``(folder_id, title)``; markdown ``content`` only."""
    tag_list = list(tags) if tags is not None else []
    existing_id, _ = await find_journal_by_folder_and_title(folder_id=folder_id, title=title)
    if existing_id:
        put_body: dict[str, Any] = {
            "id": existing_id,
            "title": title,
            "content": content,
            "tags": tag_list,
            "status": "published",
        }
        await client.put("/v1/journals", json=put_body)
        return {"journal_id": existing_id, "created": False, "folder_id": folder_id, "title": title}
    post_body: dict[str, Any] = {
        "campaign_id": client.campaign_id,
        "folder_id": folder_id,
        "title": title,
        "content": content,
        "tags": tag_list,
        "status": "published",
    }
    created = await client.post("/v1/journals", json=post_body)
    new_id = _journal_create_id(created)
    if not new_id:
        raise RuntimeError(f"journal create missing id: {created!r}")
    return {"journal_id": new_id, "created": True, "folder_id": folder_id, "title": title}
