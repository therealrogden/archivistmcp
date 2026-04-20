"""Pytest configuration: env for imports, pytest-httpx wiring, fixture loader."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from tests.constants import (
    BEAT_ID,
    CAMPAIGN_ID,
    CHARACTER_ID,
    FACTION_ID,
    FOLDER_ID,
    ITEM_ID,
    JOURNAL_ID,
    LOCATION_ID,
    MOMENT_ID,
    QUEST_ID,
    SESSION_ID,
    UNKNOWN_ID,
)

# Must run before archivist_mcp.server is imported (first test import chain).
os.environ.setdefault("ARCHIVIST_API_KEY", "test-api-key-not-real")
os.environ.setdefault("ARCHIVIST_CAMPAIGN_ID", "00000000-0000-0000-0000-00000000c001")
os.environ.setdefault("ARCHIVIST_BASE_URL", "http://archivist.test")

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


def load_fixture(kind: str, name: str) -> Any:
    """Load JSON from ``tests/fixtures/<kind>/<name>.json``."""
    path = FIXTURE_ROOT / kind / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_loader() -> Any:
    return load_fixture


def _register_default_api_routes(httpx_mock: Any) -> None:
    """Wire httpx_mock responses for all Archivist GET paths used by resources."""
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    cid = CAMPAIGN_ID

    def add(method: str, path: str, **kwargs: Any) -> None:
        httpx_mock.add_response(method=method, url=f"{base}{path}", **kwargs)

    add("GET", f"/v1/campaigns/{cid}", json=load_fixture("campaign", "detail"))
    add("GET", f"/v1/campaigns/{cid}/stats", json=load_fixture("campaign", "stats"))
    add("GET", f"/v1/campaigns/{cid}/links", json=load_fixture("campaign", "links"))

    q_sessions = urlencode({"campaign_id": cid})
    add("GET", f"/v1/sessions?{q_sessions}", json=load_fixture("session", "list"))

    add("GET", f"/v1/sessions/{SESSION_ID}", json=load_fixture("session", "detail"))
    add(
        "GET",
        f"/v1/sessions/{SESSION_ID}/cast-analysis",
        json=load_fixture("session", "cast_analysis"),
    )

    q_beats = urlencode({"campaign_id": cid, "game_session_id": SESSION_ID})
    add("GET", f"/v1/beats?{q_beats}", json=load_fixture("session", "beats_list"))

    q_moments = urlencode({"campaign_id": cid, "session_id": SESSION_ID})
    add("GET", f"/v1/moments?{q_moments}", json=load_fixture("session", "moments_list"))

    add("GET", f"/v1/beats/{BEAT_ID}", json=load_fixture("beat", "detail"))
    add("GET", f"/v1/moments/{MOMENT_ID}", json=load_fixture("moment", "detail"))

    q_quests = urlencode({"campaign_id": cid})
    add("GET", f"/v1/quests?{q_quests}", json=load_fixture("quest", "list"))
    add("GET", f"/v1/quests/{QUEST_ID}", json=load_fixture("quest", "detail"))

    q_chars = urlencode({"campaign_id": cid})
    add("GET", f"/v1/characters?{q_chars}", json=load_fixture("character", "list"))
    add("GET", f"/v1/characters/{CHARACTER_ID}", json=load_fixture("character", "detail"))

    q_items = urlencode({"campaign_id": cid})
    add("GET", f"/v1/items?{q_items}", json=load_fixture("item", "list"))
    add("GET", f"/v1/items/{ITEM_ID}", json=load_fixture("item", "detail"))

    q_factions = urlencode({"campaign_id": cid})
    add("GET", f"/v1/factions?{q_factions}", json=load_fixture("faction", "list"))
    add("GET", f"/v1/factions/{FACTION_ID}", json=load_fixture("faction", "detail"))

    q_locs = urlencode({"campaign_id": cid})
    add("GET", f"/v1/locations?{q_locs}", json=load_fixture("location", "list"))
    add("GET", f"/v1/locations/{LOCATION_ID}", json=load_fixture("location", "detail"))

    q_journals = urlencode({"campaign_id": cid})
    add("GET", f"/v1/journals?{q_journals}", json=load_fixture("journal", "list"))
    add("GET", f"/v1/journals/{JOURNAL_ID}", json=load_fixture("journal", "detail"))

    q_folders = urlencode({"campaign_id": cid})
    add("GET", f"/v1/journal-folders?{q_folders}", json=load_fixture("journal_folder", "list"))
    add(
        "GET",
        f"/v1/journal-folders/{FOLDER_ID}",
        json=load_fixture("journal_folder", "detail"),
    )

    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/beats/{UNKNOWN_ID}",
        status_code=404,
        text='{"detail":"not found"}',
    )


@pytest.fixture(autouse=True)
async def archivist_http_mock(httpx_mock: Any) -> AsyncIterator[None]:
    """Recreate the global Archivist client so it uses pytest-httpx mock transport."""
    import archivist_mcp.resources as res
    import archivist_mcp.server as srv
    from archivist_mcp.client import ArchivistClient

    # Many tests register shared routes but do not exhaust every matcher in a single test.
    httpx_mock._options.assert_all_responses_were_requested = False

    await srv.client.aclose()
    new_client = ArchivistClient(srv.config)
    srv.client = new_client
    res.client = new_client

    _register_default_api_routes(httpx_mock)

    yield

    await new_client.aclose()
