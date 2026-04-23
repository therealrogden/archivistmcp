"""Pytest configuration: env for imports, pytest-httpx wiring, fixture loader."""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

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

    def add_get(path_suffix_regex: str, **kwargs: Any) -> None:
        httpx_mock.add_response(
            method="GET",
            url=re.compile(rf"^{re.escape(base)}{path_suffix_regex}$"),
            **kwargs,
        )

    add_get(r"/health(\?.*)?", json={"status": "ok"})
    add_get(rf"/v1/campaigns/{re.escape(cid)}(\?.*)?", json=load_fixture("campaign", "detail"))
    add_get(rf"/v1/campaigns/{re.escape(cid)}/stats(\?.*)?", json=load_fixture("campaign", "stats"))
    add_get(rf"/v1/campaigns/{re.escape(cid)}/links\?.*", json=load_fixture("campaign", "links"))

    add_get(r"/v1/sessions\?.*", json=load_fixture("session", "list"))

    add_get(rf"/v1/sessions/{re.escape(SESSION_ID)}(\?.*)?", json=load_fixture("session", "detail"))
    add_get(
        rf"/v1/sessions/{re.escape(SESSION_ID)}/cast-analysis(\?.*)?",
        json=load_fixture("session", "cast_analysis"),
    )

    add_get(r"/v1/beats\?.*", json=load_fixture("session", "beats_list"))

    add_get(r"/v1/moments\?.*", json=load_fixture("session", "moments_list"))

    add_get(rf"/v1/beats/{re.escape(BEAT_ID)}(\?.*)?", json=load_fixture("beat", "detail"))
    add_get(rf"/v1/moments/{re.escape(MOMENT_ID)}(\?.*)?", json=load_fixture("moment", "detail"))

    add_get(r"/v1/quests\?.*", json=load_fixture("quest", "list"))
    add_get(rf"/v1/quests/{re.escape(QUEST_ID)}(\?.*)?", json=load_fixture("quest", "detail"))

    add_get(r"/v1/characters\?.*", json=load_fixture("character", "list"))
    add_get(rf"/v1/characters/{re.escape(CHARACTER_ID)}(\?.*)?", json=load_fixture("character", "detail"))

    add_get(r"/v1/items\?.*", json=load_fixture("item", "list"))
    add_get(rf"/v1/items/{re.escape(ITEM_ID)}(\?.*)?", json=load_fixture("item", "detail"))

    add_get(r"/v1/factions\?.*", json=load_fixture("faction", "list"))
    add_get(rf"/v1/factions/{re.escape(FACTION_ID)}(\?.*)?", json=load_fixture("faction", "detail"))

    add_get(r"/v1/locations\?.*", json=load_fixture("location", "list"))
    add_get(rf"/v1/locations/{re.escape(LOCATION_ID)}(\?.*)?", json=load_fixture("location", "detail"))

    add_get(r"/v1/journals\?.*", json=load_fixture("journal", "list"))
    add_get(rf"/v1/journals/{re.escape(JOURNAL_ID)}(\?.*)?", json=load_fixture("journal", "detail"))

    add_get(r"/v1/journal-folders\?.*", json=load_fixture("journal_folder", "list"))
    add_get(rf"/v1/journal-folders/{re.escape(FOLDER_ID)}(\?.*)?", json=load_fixture("journal_folder", "detail"))

    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/beats/{re.escape(UNKNOWN_ID)}(\?.*)?$"),
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
    import archivist_mcp.tools.ask as ask_mod
    import archivist_mcp.tools.campaign_summary as campaign_summary_mod
    import archivist_mcp.tools.items as items_mod
    import archivist_mcp.tools.journals as journals_mod
    import archivist_mcp.tools.links as links_mod
    import archivist_mcp.tools.read_session as read_session_mod
    import archivist_mcp.tools.search as search_mod
    import archivist_mcp.tools.session_summary as session_summary_mod
    import archivist_mcp.tools.wikilinks as wikilinks_mod

    search_mod.client = new_client
    ask_mod.client = new_client
    session_summary_mod.client = new_client
    campaign_summary_mod.client = new_client
    journals_mod.client = new_client
    items_mod.client = new_client
    links_mod.client = new_client
    read_session_mod.client = new_client
    wikilinks_mod.client = new_client

    _register_default_api_routes(httpx_mock)

    yield

    await new_client.aclose()
