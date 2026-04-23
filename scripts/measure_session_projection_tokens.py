#!/usr/bin/env python3
"""Measure cl100k_base token count for raw vs slim session list payloads.

Used for Chunk 2 PR description (DESIGN.md build order step 3).

Usage (fixture-based, no credentials):
    python scripts/measure_session_projection_tokens.py

With a live campaign (same shape as GET /v1/sessions):
    set ARCHIVIST_MEASURE_LIVE=1 and valid ARCHIVIST_* env vars, then run this script.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


def _count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    import tiktoken

    enc = tiktoken.get_encoding(encoding_name)
    return len(enc.encode(text))


def _json_compact(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


async def _fetch_live_sessions() -> dict[str, Any]:
    from archivist_mcp.config import load_config

    cfg = load_config()
    headers = {"x-api-key": cfg.api_key}
    async with httpx.AsyncClient(base_url=cfg.base_url, headers=headers, timeout=60.0) as client:
        r = await client.get(
            "/v1/sessions",
            params={"campaign_id": cfg.campaign_id, "page": 1, "size": 50},
        )
        r.raise_for_status()
        return r.json()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))

    from archivist_mcp.projections import project_list_payload

    live = os.environ.get("ARCHIVIST_MEASURE_LIVE", "").lower() in ("1", "true", "yes")
    if live:
        raw = asyncio.run(_fetch_live_sessions())
        source = "live GET /v1/sessions"
    else:
        fixture_path = root / "tests" / "fixtures" / "session" / "list.json"
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        # Inflate rows so the delta is visible on the small scrubbed fixture (PR narrative).
        if raw.get("data") and isinstance(raw["data"], list) and raw["data"]:
            row = dict(raw["data"][0])
            row["summary"] = "x" * 4000
            row["description"] = "y" * 8000
            row["notes"] = "z" * 6000
            raw = {**raw, "data": [row] * 20}
        source = f"fixture (inflated for measurement): {fixture_path}"

    slim = project_list_payload(raw, "session")
    raw_s = _json_compact(raw)
    slim_s = _json_compact(slim)
    raw_t = _count_tokens(raw_s)
    slim_t = _count_tokens(slim_s)
    print(f"Source: {source}")
    print(f"Raw list JSON tokens (cl100k_base):  {raw_t}")
    print(f"Slim list JSON tokens (cl100k_base): {slim_t}")
    print(f"Delta (raw - slim): {raw_t - slim_t} tokens ({100.0 * (raw_t - slim_t) / max(raw_t, 1):.1f}% reduction)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
