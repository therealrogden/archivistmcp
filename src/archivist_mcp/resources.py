from typing import Any

import httpx

from .server import client, mcp


@mcp.resource("archivist://campaign")
async def campaign_resource() -> dict[str, Any]:
    """Campaign record for the configured campaign."""
    return await client.get(f"/v1/campaigns/{client.campaign_id}")


@mcp.resource("archivist://campaign/stats")
async def campaign_stats_resource() -> dict[str, Any]:
    """Aggregate stats for the configured campaign."""
    return await client.get(f"/v1/campaigns/{client.campaign_id}/stats")


@mcp.resource("archivist://campaign/links")
async def campaign_links_resource() -> dict[str, Any]:
    """Entity graph links for the configured campaign (paginated)."""
    return await client.get(f"/v1/campaigns/{client.campaign_id}/links")


@mcp.resource("archivist://sessions")
async def sessions_resource() -> dict[str, Any]:
    """Paginated session list for the campaign, ordered by session_date."""
    return await client.get("/v1/sessions", campaign_id=client.campaign_id)


@mcp.resource("archivist://session/{session_id}")
async def session_resource(session_id: str) -> dict[str, Any]:
    """Session metadata."""
    return await client.get(f"/v1/sessions/{session_id}")


@mcp.resource("archivist://session/{session_id}/cast-analysis")
async def session_cast_analysis_resource(session_id: str) -> dict[str, Any]:
    """Cast analysis for a session; use when summarizing audio-heavy sessions.

    Returns ``cast_analysis: null`` when the session has no cast analysis (e.g. no transcript).
    """
    try:
        data = await client.get(f"/v1/sessions/{session_id}/cast-analysis")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"cast_analysis": None}
        raise
    return {"cast_analysis": data}


@mcp.resource("archivist://session/{session_id}/beats")
async def session_beats_resource(session_id: str) -> dict[str, Any]:
    """Beats for this session (paginated list from ``GET /v1/beats``)."""
    return await client.get(
        "/v1/beats",
        campaign_id=client.campaign_id,
        game_session_id=session_id,
    )


@mcp.resource("archivist://session/{session_id}/moments")
async def session_moments_resource(session_id: str) -> dict[str, Any]:
    """Moments for this session (paginated list from ``GET /v1/moments``)."""
    return await client.get(
        "/v1/moments",
        campaign_id=client.campaign_id,
        session_id=session_id,
    )


@mcp.resource("archivist://beat/{beat_id}")
async def beat_resource(beat_id: str) -> dict[str, Any]:
    """Single beat by ID."""
    return await client.get(f"/v1/beats/{beat_id}")


@mcp.resource("archivist://moment/{moment_id}")
async def moment_resource(moment_id: str) -> dict[str, Any]:
    """Single moment by ID."""
    return await client.get(f"/v1/moments/{moment_id}")


@mcp.resource("archivist://quests")
async def quests_resource() -> dict[str, Any]:
    """All quests with objectives and progress log."""
    return await client.get("/v1/quests", campaign_id=client.campaign_id)


@mcp.resource("archivist://quest/{quest_id}")
async def quest_resource(quest_id: str) -> dict[str, Any]:
    """Single quest by ID (expanded objectives, progress log, related refs)."""
    return await client.get(f"/v1/quests/{quest_id}")


@mcp.resource("archivist://characters")
async def characters_resource() -> dict[str, Any]:
    """Full cast list (PCs and NPCs) for the campaign."""
    return await client.get("/v1/characters", campaign_id=client.campaign_id)


@mcp.resource("archivist://character/{character_id}")
async def character_resource(character_id: str) -> dict[str, Any]:
    """Single character (PC or NPC) by ID."""
    return await client.get(f"/v1/characters/{character_id}")


@mcp.resource("archivist://items")
async def items_resource() -> dict[str, Any]:
    """All items for the campaign (compendium list)."""
    return await client.get("/v1/items", campaign_id=client.campaign_id)


@mcp.resource("archivist://factions")
async def factions_resource() -> dict[str, Any]:
    """All factions for the campaign."""
    return await client.get("/v1/factions", campaign_id=client.campaign_id)


@mcp.resource("archivist://faction/{faction_id}")
async def faction_resource(faction_id: str) -> dict[str, Any]:
    """Single faction by ID."""
    return await client.get(f"/v1/factions/{faction_id}")


@mcp.resource("archivist://locations")
async def locations_resource() -> dict[str, Any]:
    """All locations for the campaign."""
    return await client.get("/v1/locations", campaign_id=client.campaign_id)


@mcp.resource("archivist://location/{location_id}")
async def location_resource(location_id: str) -> dict[str, Any]:
    """Single location by ID."""
    return await client.get(f"/v1/locations/{location_id}")


@mcp.resource("archivist://item/{item_id}")
async def item_resource(item_id: str) -> dict[str, Any]:
    """Item entity. Includes a mechanics journal entry when one is linked."""
    return await client.get(f"/v1/items/{item_id}")


@mcp.resource("archivist://journals")
async def journals_resource() -> dict[str, Any]:
    """Journal entry list for the campaign (metadata; full content via ``archivist://journal/{id}``)."""
    return await client.get("/v1/journals", campaign_id=client.campaign_id)


@mcp.resource("archivist://journal/{entry_id}")
async def journal_resource(entry_id: str) -> dict[str, Any]:
    """Journal entry with plain-text content only (content_rich is stripped)."""
    entry = await client.get(f"/v1/journals/{entry_id}")
    entry.pop("content_rich", None)
    return entry


@mcp.resource("archivist://journal-folders")
async def journal_folders_resource() -> dict[str, Any]:
    """Journal folder tree for the campaign."""
    return await client.get("/v1/journal-folders", campaign_id=client.campaign_id)


@mcp.resource("archivist://journal-folder/{folder_id}")
async def journal_folder_resource(folder_id: str) -> dict[str, Any]:
    """Single journal folder by ID."""
    return await client.get(f"/v1/journal-folders/{folder_id}")
