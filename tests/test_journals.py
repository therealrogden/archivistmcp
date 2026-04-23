"""Tests for ``upsert_journal_entry`` (DESIGN.md step 14)."""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode

import pytest

from archivist_mcp.tools.journals import upsert_journal_entry
from tests.constants import CAMPAIGN_ID, FOLDER_ID, JOURNAL_ID


@pytest.mark.asyncio
async def test_upsert_journal_entry_create_then_update(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    q = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/journals?{q}",
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base}/v1/journals",
        json={"id": JOURNAL_ID},
        status_code=201,
    )
    r1 = await upsert_journal_entry(FOLDER_ID, "My Title", "first body", tags=["a"])
    assert r1["created"] is True
    assert r1["journal_id"] == JOURNAL_ID

    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/journals?{q}",
        json={
            "data": [
                {
                    "id": JOURNAL_ID,
                    "title": "My Title",
                    "folder_id": FOLDER_ID,
                }
            ],
            "page": 1,
            "pages": 1,
            "total": 1,
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/journals/{JOURNAL_ID}",
        json={"id": JOURNAL_ID, "title": "My Title", "folder_id": FOLDER_ID, "content": "first body"},
    )
    httpx_mock.add_response(method="PUT", url=f"{base}/v1/journals", json={"id": JOURNAL_ID}, status_code=200)
    r2 = await upsert_journal_entry(FOLDER_ID, "My Title", "second body", tags=["b"])
    assert r2["created"] is False
    puts = [x for x in httpx_mock.get_requests() if x.method == "PUT"]
    assert puts
    body = json.loads(puts[-1].content.decode())
    assert body["content"] == "second body"
