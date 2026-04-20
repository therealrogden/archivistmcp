from typing import Any

from .client import ArchivistUpstreamError
from .projections import project_list_payload, pagination_params
from .server import client, mcp
from .validation import ProjectionKind


async def _get_slim_list(
    path: str,
    kind: ProjectionKind,
    *,
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
    **extra_params: Any,
) -> Any:
    """GET a paginated list, forward pagination to Archivist, return envelope with slim ``data`` rows."""
    params: dict[str, Any] = {**extra_params, **pagination_params(page=page, page_size=page_size, cursor=cursor)}
    body = await client.get(path, **params)
    return project_list_payload(body, kind)


@mcp.resource("archivist://campaign")
async def campaign_resource() -> dict[str, Any]:
    """Campaign record for the configured campaign."""
    return await client.get(f"/v1/campaigns/{client.campaign_id}")


@mcp.resource("archivist://campaign/stats")
async def campaign_stats_resource() -> dict[str, Any]:
    """Aggregate stats for the configured campaign."""
    return await client.get(f"/v1/campaigns/{client.campaign_id}/stats")


@mcp.resource("archivist://campaign/links{?page,page_size,cursor}")
async def campaign_links_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Entity graph links for the configured campaign (paginated).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        f"/v1/campaigns/{client.campaign_id}/links",
        "campaign_link",
        page=page,
        page_size=page_size,
        cursor=cursor,
    )


@mcp.resource("archivist://sessions{?page,page_size,cursor}")
async def sessions_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Paginated session list for the campaign, ordered by session_date.

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    List rows use the slim session projection.
    """
    return await _get_slim_list(
        "/v1/sessions",
        "session",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
    )


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
    except ArchivistUpstreamError as exc:
        if exc.status_code == 404:
            return {"cast_analysis": None}
        raise
    return {"cast_analysis": data}


@mcp.resource("archivist://session/{session_id}/beats{?page,page_size,cursor}")
async def session_beats_resource(
    session_id: str,
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Beats for this session (paginated list from ``GET /v1/beats``).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/beats",
        "beat",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
        game_session_id=session_id,
    )


@mcp.resource("archivist://session/{session_id}/moments{?page,page_size,cursor}")
async def session_moments_resource(
    session_id: str,
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Moments for this session (paginated list from ``GET /v1/moments``).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/moments",
        "moment",
        page=page,
        page_size=page_size,
        cursor=cursor,
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


@mcp.resource("archivist://quests{?page,page_size,cursor}")
async def quests_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Quest list for the campaign (slim rows; full detail via ``archivist://quest/{id}``).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/quests",
        "quest",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
    )


@mcp.resource("archivist://quest/{quest_id}")
async def quest_resource(quest_id: str) -> dict[str, Any]:
    """Single quest by ID (expanded objectives, progress log, related refs)."""
    return await client.get(f"/v1/quests/{quest_id}")


@mcp.resource("archivist://characters{?page,page_size,cursor}")
async def characters_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Cast list (PCs and NPCs) for the campaign (slim rows).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/characters",
        "character",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
    )


@mcp.resource("archivist://character/{character_id}")
async def character_resource(character_id: str) -> dict[str, Any]:
    """Single character (PC or NPC) by ID."""
    return await client.get(f"/v1/characters/{character_id}")


@mcp.resource("archivist://items{?page,page_size,cursor}")
async def items_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Item compendium list (slim rows).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/items",
        "item",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
    )


@mcp.resource("archivist://factions{?page,page_size,cursor}")
async def factions_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Faction list (slim rows).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/factions",
        "faction",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
    )


@mcp.resource("archivist://faction/{faction_id}")
async def faction_resource(faction_id: str) -> dict[str, Any]:
    """Single faction by ID."""
    return await client.get(f"/v1/factions/{faction_id}")


@mcp.resource("archivist://locations{?page,page_size,cursor}")
async def locations_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Location list (slim rows).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/locations",
        "location",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
    )


@mcp.resource("archivist://location/{location_id}")
async def location_resource(location_id: str) -> dict[str, Any]:
    """Single location by ID."""
    return await client.get(f"/v1/locations/{location_id}")


@mcp.resource("archivist://item/{item_id}")
async def item_resource(item_id: str) -> dict[str, Any]:
    """Item entity. Includes a mechanics journal entry when one is linked."""
    return await client.get(f"/v1/items/{item_id}")


@mcp.resource("archivist://journals{?page,page_size,cursor}")
async def journals_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Journal entry list for the campaign (metadata; full content via ``archivist://journal/{id}``).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/journals",
        "journal",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
    )


@mcp.resource("archivist://journal/{entry_id}")
async def journal_resource(entry_id: str) -> dict[str, Any]:
    """Journal entry with plain-text content only (content_rich is stripped)."""
    entry = await client.get(f"/v1/journals/{entry_id}")
    entry.pop("content_rich", None)
    return entry


@mcp.resource("archivist://journal-folders{?page,page_size,cursor}")
async def journal_folders_resource(
    page: int = 1,
    page_size: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Journal folder tree for the campaign (slim rows).

    Pagination is forwarded to the Archivist API: ``page`` (default 1), ``page_size`` (default 50,
    capped at 50 server-side), and optional ``cursor`` when the upstream API supports it.
    """
    return await _get_slim_list(
        "/v1/journal-folders",
        "journal_folder",
        page=page,
        page_size=page_size,
        cursor=cursor,
        campaign_id=client.campaign_id,
    )


@mcp.resource("archivist://journal-folder/{folder_id}")
async def journal_folder_resource(folder_id: str) -> dict[str, Any]:
    """Single journal folder by ID."""
    return await client.get(f"/v1/journal-folders/{folder_id}")
