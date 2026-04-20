"""MCP resource handlers return fixture-backed shapes; campaigns list is absent."""

from __future__ import annotations

import httpx
import pytest

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
from tests.constants import (
    BEAT_ID,
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
    assert await campaign_links_resource() == load_fixture("campaign", "links")


@pytest.mark.asyncio
async def test_sessions_resource() -> None:
    assert await sessions_resource() == load_fixture("session", "list")


@pytest.mark.asyncio
async def test_session_resource() -> None:
    assert await session_resource(SESSION_ID) == load_fixture("session", "detail")


@pytest.mark.asyncio
async def test_session_cast_analysis_resource() -> None:
    expected = {"cast_analysis": load_fixture("session", "cast_analysis")}
    assert await session_cast_analysis_resource(SESSION_ID) == expected


@pytest.mark.asyncio
async def test_session_beats_resource() -> None:
    assert await session_beats_resource(SESSION_ID) == load_fixture("session", "beats_list")


@pytest.mark.asyncio
async def test_session_moments_resource() -> None:
    assert await session_moments_resource(SESSION_ID) == load_fixture("session", "moments_list")


@pytest.mark.asyncio
async def test_beat_resource() -> None:
    assert await beat_resource(BEAT_ID) == load_fixture("beat", "detail")


@pytest.mark.asyncio
async def test_moment_resource() -> None:
    assert await moment_resource(MOMENT_ID) == load_fixture("moment", "detail")


@pytest.mark.asyncio
async def test_quests_resource() -> None:
    assert await quests_resource() == load_fixture("quest", "list")


@pytest.mark.asyncio
async def test_quest_resource() -> None:
    assert await quest_resource(QUEST_ID) == load_fixture("quest", "detail")


@pytest.mark.asyncio
async def test_characters_resource() -> None:
    assert await characters_resource() == load_fixture("character", "list")


@pytest.mark.asyncio
async def test_character_resource() -> None:
    assert await character_resource(CHARACTER_ID) == load_fixture("character", "detail")


@pytest.mark.asyncio
async def test_items_resource() -> None:
    assert await items_resource() == load_fixture("item", "list")


@pytest.mark.asyncio
async def test_item_resource() -> None:
    assert await item_resource(ITEM_ID) == load_fixture("item", "detail")


@pytest.mark.asyncio
async def test_factions_resource() -> None:
    assert await factions_resource() == load_fixture("faction", "list")


@pytest.mark.asyncio
async def test_faction_resource() -> None:
    assert await faction_resource(FACTION_ID) == load_fixture("faction", "detail")


@pytest.mark.asyncio
async def test_locations_resource() -> None:
    assert await locations_resource() == load_fixture("location", "list")


@pytest.mark.asyncio
async def test_location_resource() -> None:
    assert await location_resource(LOCATION_ID) == load_fixture("location", "detail")


@pytest.mark.asyncio
async def test_journals_resource() -> None:
    assert await journals_resource() == load_fixture("journal", "list")


@pytest.mark.asyncio
async def test_journal_resource_strips_content_rich() -> None:
    raw = load_fixture("journal", "detail")
    expected = {**raw}
    expected.pop("content_rich", None)
    assert await journal_resource(JOURNAL_ID) == expected


@pytest.mark.asyncio
async def test_journal_folders_resource() -> None:
    assert await journal_folders_resource() == load_fixture("journal_folder", "list")


@pytest.mark.asyncio
async def test_journal_folder_resource() -> None:
    assert await journal_folder_resource(FOLDER_ID) == load_fixture("journal_folder", "detail")


@pytest.mark.asyncio
async def test_beat_unknown_id_surfaces_404() -> None:
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        await beat_resource(UNKNOWN_ID)
    assert excinfo.value.response.status_code == 404
