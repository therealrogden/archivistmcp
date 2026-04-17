"""Smoke test for archivist-mcp scaffold.

Verifies imports, FastMCP tool registration, and the unauthenticated
/health endpoint. If real credentials are supplied via env, also
exercises the authenticated campaign endpoints.

Dummy run (no API access needed, verifies code + network path):
    ARCHIVIST_API_KEY=dummy ARCHIVIST_CAMPAIGN_ID=dummy \\
        python scripts/smoke.py

Full run (verifies auth end-to-end):
    ARCHIVIST_API_KEY=<real> ARCHIVIST_CAMPAIGN_ID=<real> \\
        python scripts/smoke.py
"""
from __future__ import annotations

import asyncio
import sys
import traceback


DUMMY = {"dummy", "test", ""}


async def main() -> int:
    print("=== archivist-mcp smoke test ===\n")

    try:
        from archivist_mcp.server import client, config, mcp
    except Exception:
        print("[FAIL] import archivist_mcp.server")
        traceback.print_exc()
        return 1
    print(f"[OK]   imports; campaign_id={config.campaign_id!r} base_url={config.base_url!r}")

    tools = await mcp.list_tools()
    tool_names = sorted(t.name for t in tools)
    print(f"[OK]   FastMCP exposes {len(tool_names)} tool(s): {tool_names}")

    try:
        health = await client.health()
        print(f"[OK]   GET /health → {health}")
    except Exception as e:
        print(f"[FAIL] GET /health → {type(e).__name__}: {e}")
        await client.aclose()
        return 1

    auth_dummy = config.api_key.lower() in DUMMY or config.campaign_id.lower() in DUMMY
    if auth_dummy:
        print("[SKIP] authenticated calls (dummy creds)")
    else:
        try:
            campaign = await client.get(f"/v1/campaigns/{config.campaign_id}")
            print(f"[OK]   GET /v1/campaigns/{{id}} → name={campaign.get('name')!r}")
            stats = await client.get(f"/v1/campaigns/{config.campaign_id}/stats")
            print(f"[OK]   GET /v1/campaigns/{{id}}/stats → {stats}")
        except Exception as e:
            print(f"[FAIL] auth call → {type(e).__name__}: {e}")
            await client.aclose()
            return 1

    await client.aclose()
    print("\n=== smoke test passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
