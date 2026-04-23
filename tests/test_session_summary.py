"""Tests for session summary commit tools (DESIGN.md step 11)."""

from __future__ import annotations

import json
import os
import re

import pytest

from archivist_mcp.errors import CommitPartialFailureError
from archivist_mcp.logging_ import reset_logging_configuration
from archivist_mcp.tools.session_summary import commit_session_summary
from tests.constants import CAMPAIGN_ID, SESSION_ID

WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

HISTORY_FOLDER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb0"
ARCHIVE_JOURNAL_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.mark.asyncio
async def test_commit_session_summary_equality_guard(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/sessions/{re.escape(SESSION_ID)}(\?.*)?$"),
        json={
            "id": SESSION_ID,
            "campaign_id": CAMPAIGN_ID,
            "title": "S1",
            "summary": "hello\n",
            "session_date": "2026-01-01T00:00:00Z",
        },
    )
    r = await commit_session_summary(SESSION_ID, summary="hello")
    assert r.get("already_current") is True
    assert r.get("wikilinks_stripped") == []
    for req in httpx_mock.get_requests():
        assert req.method not in WRITE_METHODS


@pytest.mark.asyncio
async def test_commit_session_summary_strips_unresolved_wikilink(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    cid = CAMPAIGN_ID

    from tests.conftest import load_fixture

    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/sessions/{re.escape(SESSION_ID)}(\?.*)?$"),
        json={
            "id": SESSION_ID,
            "campaign_id": cid,
            "title": "S1",
            "summary": "",
            "session_date": "2026-01-01T00:00:00Z",
        },
    )
    for path, kind, name in [
        ("/v1/characters", "character", "list"),
        ("/v1/items", "item", "list"),
        ("/v1/factions", "faction", "list"),
        ("/v1/locations", "location", "list"),
        ("/v1/quests", "quest", "list"),
        ("/v1/journals", "journal", "list"),
    ]:
        httpx_mock.add_response(
            method="GET",
            url=re.compile(rf"^{re.escape(base)}{re.escape(path)}\?.*$"),
            json=load_fixture(kind, name),
        )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/search\?.*$"),
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    httpx_mock.add_response(
        method="PATCH",
        url=re.compile(rf"^{re.escape(base)}/v1/sessions/{re.escape(SESSION_ID)}$"),
        json={
            "id": SESSION_ID,
            "summary": "Meet Nobody at the inn.",
        },
    )
    r = await commit_session_summary(SESSION_ID, summary="Meet [[Nobody|a stranger]] at the inn.")
    assert r.get("already_current") is not True
    assert len(r.get("wikilinks_stripped") or []) == 1
    patch_req = [x for x in httpx_mock.get_requests() if x.method == "PATCH"][0]
    body = json.loads(patch_req.content.decode())
    assert body["summary"] == "Meet a stranger at the inn."


@pytest.mark.asyncio
async def test_commit_session_summary_archive_then_patch(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    from urllib.parse import urlencode

    qf = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/sessions/{re.escape(SESSION_ID)}(\?.*)?$"),
        json={
            "id": SESSION_ID,
            "campaign_id": CAMPAIGN_ID,
            "title": "S1",
            "summary": "old summary text",
            "session_date": "2026-01-01T00:00:00Z",
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/journal-folders?{qf}",
        json={
            "data": [{"id": HISTORY_FOLDER_ID, "name": "Summary History", "parent_id": None}],
            "page": 1,
            "pages": 1,
            "total": 1,
        },
    )
    httpx_mock.add_response(method="POST", url=f"{base}/v1/journals", json={"id": ARCHIVE_JOURNAL_ID}, status_code=201)
    httpx_mock.add_response(
        method="PATCH",
        url=f"{base}/v1/sessions/{SESSION_ID}",
        json={"id": SESSION_ID, "summary": "new summary"},
    )
    r = await commit_session_summary(SESSION_ID, summary="new summary")
    assert r["archived_journal_id"] == ARCHIVE_JOURNAL_ID
    methods = [x.method for x in httpx_mock.get_requests()]
    assert methods.index("POST") < methods.index("PATCH")


@pytest.mark.asyncio
async def test_commit_session_summary_patch_failure_after_archive(
    httpx_mock: object, capsys: pytest.CaptureFixture[str]
) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    os.environ["ARCHIVIST_LOG_LEVEL"] = "INFO"
    reset_logging_configuration()
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    from urllib.parse import urlencode

    qf = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/sessions/{re.escape(SESSION_ID)}(\?.*)?$"),
        json={
            "id": SESSION_ID,
            "campaign_id": CAMPAIGN_ID,
            "title": "S1",
            "summary": "old summary text",
            "session_date": "2026-01-01T00:00:00Z",
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/journal-folders?{qf}",
        json={
            "data": [{"id": HISTORY_FOLDER_ID, "name": "Summary History", "parent_id": None}],
            "page": 1,
            "pages": 1,
            "total": 1,
        },
    )
    httpx_mock.add_response(method="POST", url=f"{base}/v1/journals", json={"id": ARCHIVE_JOURNAL_ID}, status_code=201)
    httpx_mock.add_response(
        method="PATCH",
        url=f"{base}/v1/sessions/{SESSION_ID}",
        status_code=500,
        text="{}",
    )
    with pytest.raises(CommitPartialFailureError):
        await commit_session_summary(SESSION_ID, summary="new summary")
    err_lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip().startswith("{")]
    payloads = [json.loads(ln) for ln in err_lines]
    assert any(p.get("event") == "commit.partial_failure" for p in payloads)
