"""MCP resource handlers return fixture-backed shapes; campaigns list is absent."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from archivist_mcp.client import ArchivistUpstreamError
from archivist_mcp.projections import project_list_payload
from archivist_mcp.resources import (
    beat_resource,
    campaign_links_resource,
    campaign_resource,
    campaign_stats_resource,
    character_resource,
    characters_resource,
    faction_resource,
    factions_resource,
    item_resource,
    items_resource,
    journal_folder_resource,
    journal_folders_resource,
    journal_resource,
    journals_resource,
    location_resource,
    locations_resource,
    moment_resource,
    quest_resource,
    quests_resource,
    session_beats_resource,
    session_cast_analysis_resource,
    session_moments_resource,
    session_resource,
    sessions_resource,
)
from archivist_mcp.server import mcp
from archivist_mcp.validation import ProjectionKind
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
from tests.conftest import load_fixture


def _slim(kind: str, fixture_name: str, projection: ProjectionKind) -> Any:
    return project_list_payload(load_fixture(kind, fixture_name), projection)


@pytest.mark.asyncio
async def test_list_resources_excludes_campaigns() -> None:
    resources = await mcp.list_resources()
    uris = {r.uri for r in resources}
    assert "archivist://campaigns" not in uris


@pytest.mark.asyncio
async def test_list_resource_templates_excludes_campaigns() -> None:
    templates = await mcp.list_resource_templates()
    uris = {getattr(t, "uriTemplate", getattr(t, "uri_template", "")) for t in templates}
    assert "archivist://campaigns" not in uris


@pytest.mark.asyncio
async def test_campaign_resource() -> None:
    assert await campaign_resource() == load_fixture("campaign", "detail")


@pytest.mark.asyncio
async def test_campaign_stats_resource() -> None:
    assert await campaign_stats_resource() == load_fixture("campaign", "stats")


@pytest.mark.asyncio
async def test_campaign_links_resource() -> None:
    assert await campaign_links_resource() == _slim("campaign", "links", "campaign_link")


@pytest.mark.asyncio
async def test_sessions_resource() -> None:
    assert await sessions_resource() == _slim("session", "list", "session")


@pytest.mark.asyncio
async def test_session_resource() -> None:
    assert await session_resource(SESSION_ID) == load_fixture("session", "detail")


@pytest.mark.asyncio
async def test_session_cast_analysis_resource() -> None:
    expected = {"cast_analysis": load_fixture("session", "cast_analysis")}
    assert await session_cast_analysis_resource(SESSION_ID) == expected


@pytest.mark.asyncio
async def test_session_beats_resource() -> None:
    assert await session_beats_resource(SESSION_ID) == _slim("session", "beats_list", "beat")


@pytest.mark.asyncio
async def test_session_moments_resource() -> None:
    assert await session_moments_resource(SESSION_ID) == _slim("session", "moments_list", "moment")


@pytest.mark.asyncio
async def test_beat_resource() -> None:
    assert await beat_resource(BEAT_ID) == load_fixture("beat", "detail")


@pytest.mark.asyncio
async def test_moment_resource() -> None:
    assert await moment_resource(MOMENT_ID) == load_fixture("moment", "detail")


@pytest.mark.asyncio
async def test_quests_resource() -> None:
    assert await quests_resource() == _slim("quest", "list", "quest")


@pytest.mark.asyncio
async def test_quest_resource() -> None:
    assert await quest_resource(QUEST_ID) == load_fixture("quest", "detail")


@pytest.mark.asyncio
async def test_characters_resource() -> None:
    assert await characters_resource() == _slim("character", "list", "character")


@pytest.mark.asyncio
async def test_character_resource() -> None:
    assert await character_resource(CHARACTER_ID) == load_fixture("character", "detail")


@pytest.mark.asyncio
async def test_items_resource() -> None:
    assert await items_resource() == _slim("item", "list", "item")


@pytest.mark.asyncio
async def test_item_resource() -> None:
    assert await item_resource(ITEM_ID) == load_fixture("item", "detail")


@pytest.mark.asyncio
async def test_factions_resource() -> None:
    assert await factions_resource() == _slim("faction", "list", "faction")


@pytest.mark.asyncio
async def test_faction_resource() -> None:
    assert await faction_resource(FACTION_ID) == load_fixture("faction", "detail")


@pytest.mark.asyncio
async def test_locations_resource() -> None:
    assert await locations_resource() == _slim("location", "list", "location")


@pytest.mark.asyncio
async def test_location_resource() -> None:
    assert await location_resource(LOCATION_ID) == load_fixture("location", "detail")


@pytest.mark.asyncio
async def test_journals_resource() -> None:
    assert await journals_resource() == _slim("journal", "list", "journal")


@pytest.mark.asyncio
async def test_journal_resource_strips_content_rich() -> None:
    raw = load_fixture("journal", "detail")
    expected = {**raw}
    expected.pop("content_rich", None)
    assert await journal_resource(JOURNAL_ID) == expected


@pytest.mark.asyncio
async def test_journal_folders_resource() -> None:
    assert await journal_folders_resource() == _slim("journal_folder", "list", "journal_folder")


@pytest.mark.asyncio
async def test_journal_folder_resource() -> None:
    assert await journal_folder_resource(FOLDER_ID) == load_fixture("journal_folder", "detail")


@pytest.mark.asyncio
async def test_beat_unknown_id_surfaces_404() -> None:
    with pytest.raises(ArchivistUpstreamError) as excinfo:
        await beat_resource(UNKNOWN_ID)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_sessions_forwards_page_page_size_cursor(httpx_mock: Any) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    cid = CAMPAIGN_ID
    payload = load_fixture("session", "list")
    q = urlencode({"campaign_id": cid, "page": 2, "page_size": 25, "cursor": "abc"})
    httpx_mock.add_response(method="GET", url=f"{base}/v1/sessions?{q}", json=payload)
    await sessions_resource(page=2, page_size=25, cursor="abc")
    reqs = httpx_mock.get_requests(method="GET")
    match = [r for r in reqs if r.url.path == "/v1/sessions"]
    assert match, "expected a GET /v1/sessions request"
    qs = parse_qs(urlparse(str(match[-1].url)).query)
    assert qs["page"] == ["2"]
    assert qs["page_size"] == ["25"]
    assert qs["cursor"] == ["abc"]
    assert qs["campaign_id"] == [cid]


@pytest.mark.asyncio
async def test_sessions_clamps_page_size_to_50(httpx_mock: Any) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    cid = CAMPAIGN_ID
    payload = load_fixture("session", "list")
    q = urlencode({"campaign_id": cid, "page": 1, "page_size": 50})
    httpx_mock.add_response(method="GET", url=f"{base}/v1/sessions?{q}", json=payload)
    await sessions_resource(page=1, page_size=500)
    reqs = httpx_mock.get_requests(method="GET")
    match = [r for r in reqs if r.url.path == "/v1/sessions"]
    qs = parse_qs(urlparse(str(match[-1].url)).query)
    assert qs["page_size"] == ["50"]


@pytest.mark.asyncio
async def test_sessions_default_pagination_no_cursor(httpx_mock: Any) -> None:
    await sessions_resource()
    reqs = httpx_mock.get_requests(method="GET")
    match = [r for r in reqs if r.url.path == "/v1/sessions"]
    qs = parse_qs(urlparse(str(match[-1].url)).query)
    assert qs["page"] == ["1"]
    assert qs["page_size"] == ["50"]
    assert "cursor" not in qs


@pytest.mark.asyncio
async def test_sessions_preserves_next_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    import archivist_mcp.resources as res

    raw = load_fixture("session", "list")
    body = {**raw, "next_cursor": "next-page-token"}

    async def fake_get(path: str, **params: Any) -> Any:
        assert path == "/v1/sessions"
        assert params.get("page") == 1
        assert params.get("page_size") == 50
        return body

    monkeypatch.setattr(res.client, "get", fake_get)
    out = await sessions_resource()
    assert out["next_cursor"] == "next-page-token"
    assert "data" in out
    assert isinstance(out["data"], list)
