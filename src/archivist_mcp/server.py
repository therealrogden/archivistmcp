from typing import Any
from fastmcp import FastMCP

from .client import ArchivistClient
from .config import load_config

config = load_config()
client = ArchivistClient(config)

mcp = FastMCP("archivist")


@mcp.tool
async def health_check() -> dict[str, Any]:
    """Verify the server can reach Archivist, the API key is valid, and the campaign ID resolves.

    Returns API health, campaign name, and campaign stats. Use this first after configuring
    the server to confirm end-to-end connectivity.
    """
    api_health = await client.health()
    campaign = await client.get(f"/v1/campaigns/{client.campaign_id}")
    stats = await client.get(f"/v1/campaigns/{client.campaign_id}/stats")
    return {
        "api_health": api_health,
        "campaign": {"id": campaign["id"], "title": campaign.get("title")},
        "stats": stats,
    }


from . import resources as _resources  # noqa: E402, F401 — registers @mcp.resource decorators
