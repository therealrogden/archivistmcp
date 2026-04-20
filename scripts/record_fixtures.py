"""Record scrubbed Archivist API fixtures for offline tests.

Requires real credentials (``ARCHIVIST_API_KEY``) and ``--campaign-id``.

Usage:
    python scripts/record_fixtures.py --campaign-id=<uuid>

Writes JSON under ``tests/fixtures/<kind>/`` with deterministic scrubbing.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"
FAKE_CAMPAIGN = "00000000-0000-0000-0000-00000000c001"


def scrub_value(obj: Any, live_campaign_id: str) -> Any:
    """Recursively scrub secrets, live campaign id, and long free-text fields."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in {"x-api-key", "authorization", "api_key", "apikey"}:
                out[k] = "<redacted>"
                continue
            if lk == "description" and isinstance(v, str) and len(v) > 120:
                out[k] = "Placeholder description (scrubbed)."
                continue
            if lk == "content" and isinstance(v, str) and len(v) > 200:
                out[k] = "Placeholder content (scrubbed)."
                continue
            out[k] = scrub_value(v, live_campaign_id)
        return out
    if isinstance(obj, list):
        return [scrub_value(x, live_campaign_id) for x in obj]
    if isinstance(obj, str):
        return obj.replace(live_campaign_id, FAKE_CAMPAIGN)
    return obj


def assert_scrubbed_file(path: Path, live_campaign_id: str) -> None:
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "x-api-key" not in lowered
    assert live_campaign_id not in text
    api_key = os.environ.get("ARCHIVIST_API_KEY", "")
    if api_key:
        assert api_key not in text


def write_json(kind: str, name: str, data: Any, live_campaign_id: str) -> None:
    scrubbed = scrub_value(data, live_campaign_id)
    out_dir = FIXTURE_ROOT / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.json"
    out_path.write_text(
        json.dumps(scrubbed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert_scrubbed_file(out_path, live_campaign_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record scrubbed fixtures from live Archivist API.")
    parser.add_argument("--campaign-id", required=True, help="Live campaign UUID to read from.")
    args = parser.parse_args()
    live_campaign_id = args.campaign_id.strip()

    api_key = os.environ.get("ARCHIVIST_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ARCHIVIST_API_KEY is required in the environment.")

    base = os.environ.get("ARCHIVIST_BASE_URL", "https://api.myarchivist.ai").rstrip("/")
    headers = {"x-api-key": api_key}

    with httpx.Client(base_url=base, headers=headers, timeout=60.0) as client:
        def get(path: str, **params: Any) -> Any:
            r = client.get(path, params=params or None)
            r.raise_for_status()
            return r.json()

        cid = live_campaign_id
        write_json("campaign", "detail", get(f"/v1/campaigns/{cid}"), live_campaign_id)
        write_json("campaign", "stats", get(f"/v1/campaigns/{cid}/stats"), live_campaign_id)
        write_json("campaign", "links", get(f"/v1/campaigns/{cid}/links"), live_campaign_id)

        sessions = get("/v1/sessions", campaign_id=cid)
        write_json("session", "list", sessions, live_campaign_id)
        s0 = (sessions.get("data") or sessions.get("items") or [None])[0]
        if not s0 or not s0.get("id"):
            raise SystemExit("Could not determine a session id from sessions list response.")
        sid = s0["id"]
        write_json("session", "detail", get(f"/v1/sessions/{sid}"), live_campaign_id)
        try:
            cast = get(f"/v1/sessions/{sid}/cast-analysis")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            cast = {"session_id": sid, "note": "no cast analysis (404 during record)"}
        write_json("session", "cast_analysis", cast, live_campaign_id)
        write_json(
            "session",
            "beats_list",
            get("/v1/beats", campaign_id=cid, game_session_id=sid),
            live_campaign_id,
        )
        write_json(
            "session",
            "moments_list",
            get("/v1/moments", campaign_id=cid, session_id=sid),
            live_campaign_id,
        )

        beats = get("/v1/beats", campaign_id=cid, game_session_id=sid)
        b0 = (beats.get("data") or beats.get("items") or [None])[0]
        if b0 and b0.get("id"):
            write_json("beat", "detail", get(f"/v1/beats/{b0['id']}"), live_campaign_id)

        moments = get("/v1/moments", campaign_id=cid, session_id=sid)
        m0 = (moments.get("data") or moments.get("items") or [None])[0]
        if m0 and m0.get("id"):
            write_json("moment", "detail", get(f"/v1/moments/{m0['id']}"), live_campaign_id)

        quests = get("/v1/quests", campaign_id=cid)
        write_json("quest", "list", quests, live_campaign_id)
        q0 = (quests.get("data") or quests.get("items") or [None])[0]
        if q0 and q0.get("id"):
            write_json("quest", "detail", get(f"/v1/quests/{q0['id']}"), live_campaign_id)

        chars = get("/v1/characters", campaign_id=cid)
        write_json("character", "list", chars, live_campaign_id)
        c0 = (chars.get("data") or chars.get("items") or [None])[0]
        if c0 and c0.get("id"):
            write_json("character", "detail", get(f"/v1/characters/{c0['id']}"), live_campaign_id)

        items = get("/v1/items", campaign_id=cid)
        write_json("item", "list", items, live_campaign_id)
        i0 = (items.get("data") or items.get("items") or [None])[0]
        if i0 and i0.get("id"):
            write_json("item", "detail", get(f"/v1/items/{i0['id']}"), live_campaign_id)

        factions = get("/v1/factions", campaign_id=cid)
        write_json("faction", "list", factions, live_campaign_id)
        f0 = (factions.get("data") or factions.get("items") or [None])[0]
        if f0 and f0.get("id"):
            write_json("faction", "detail", get(f"/v1/factions/{f0['id']}"), live_campaign_id)

        locs = get("/v1/locations", campaign_id=cid)
        write_json("location", "list", locs, live_campaign_id)
        l0 = (locs.get("data") or locs.get("items") or [None])[0]
        if l0 and l0.get("id"):
            write_json("location", "detail", get(f"/v1/locations/{l0['id']}"), live_campaign_id)

        journals = get("/v1/journals", campaign_id=cid)
        write_json("journal", "list", journals, live_campaign_id)
        j0 = (journals.get("data") or journals.get("items") or [None])[0]
        if j0 and j0.get("id"):
            write_json("journal", "detail", get(f"/v1/journals/{j0['id']}"), live_campaign_id)

        folders = get("/v1/journal-folders", campaign_id=cid)
        write_json("journal_folder", "list", folders, live_campaign_id)
        d0 = (folders.get("data") or folders.get("items") or [None])[0]
        if d0 and d0.get("id"):
            write_json(
                "journal_folder",
                "detail",
                get(f"/v1/journal-folders/{d0['id']}"),
                live_campaign_id,
            )

    print(f"[OK] Wrote scrubbed fixtures under {FIXTURE_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
