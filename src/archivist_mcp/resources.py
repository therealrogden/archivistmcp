import asyncio
from typing import Any

from .server import client, mcp


@mcp.resource("archivist://campaign")
async def campaign_resource() -> dict[str, Any]:
    """Campaign card and stats for the configured campaign."""
    campaign, stats = await asyncio.gather(
        client.get(f"/v1/campaigns/{client.campaign_id}"),
        client.get(f"/v1/campaigns/{client.campaign_id}/stats"),
    )
    return {"campaign": campaign, "stats": stats}


@mcp.resource("archivist://sessions")
async def sessions_resource() -> dict[str, Any]:
    """Paginated session list for the campaign, ordered by session_date."""
    return await client.get("/v1/sessions", campaign_id=client.campaign_id)


@mcp.resource("archivist://session/{session_id}")
async def session_resource(session_id: str) -> dict[str, Any]:
    """Composite session view: session metadata, beats, moments, and cast analysis.

    Beats and moments are fetched via include_moments=true on the session endpoint
    (include_beats has a known server-side bug; beats field will be null until fixed).
    Cast analysis is omitted (not an error) when the session has no audio transcript.
    """
    session, cast = await asyncio.gather(
        client.get(f"/v1/sessions/{session_id}", include_moments=True),
        client.get(f"/v1/sessions/{session_id}/cast-analysis"),
        return_exceptions=True,
    )
    if isinstance(session, Exception):
        raise session
    return {
        **session,
        "cast_analysis": None if isinstance(cast, Exception) else cast,
    }


@mcp.resource("archivist://quests")
async def quests_resource() -> dict[str, Any]:
    """All quests with objectives and progress log."""
    return await client.get("/v1/quests", campaign_id=client.campaign_id)


@mcp.resource("archivist://characters")
async def characters_resource() -> dict[str, Any]:
    """Full cast list (PCs and NPCs) for the campaign."""
    return await client.get("/v1/characters", campaign_id=client.campaign_id)


@mcp.resource("archivist://entities")
async def entities_resource() -> dict[str, Any]:
    """Compendium overview: items, factions, and locations."""
    items, factions, locations = await asyncio.gather(
        client.get("/v1/items", campaign_id=client.campaign_id),
        client.get("/v1/factions", campaign_id=client.campaign_id),
        client.get("/v1/locations", campaign_id=client.campaign_id),
    )
    return {"items": items, "factions": factions, "locations": locations}


@mcp.resource("archivist://item/{item_id}")
async def item_resource(item_id: str) -> dict[str, Any]:
    """Item entity. Includes a mechanics journal entry when one is linked."""
    return await client.get(f"/v1/items/{item_id}")


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
