"""Tests for ``link_entities`` (DESIGN.md step 15)."""

from __future__ import annotations

import os
from urllib.parse import urlencode

import pytest

from archivist_mcp.tools.links import link_entities
from tests.constants import CAMPAIGN_ID, CHARACTER_ID, FACTION_ID


@pytest.mark.asyncio
async def test_link_entities_create_then_dedupe(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    q = urlencode({"page": 1, "size": 50})
    link_row = {
        "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        "from_id": CHARACTER_ID,
        "from_type": "character",
        "to_id": FACTION_ID,
        "to_type": "faction",
        "alias": "ally",
    }
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/campaigns/{CAMPAIGN_ID}/links?{q}",
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base}/v1/campaigns/{CAMPAIGN_ID}/links",
        json=link_row,
        status_code=201,
    )
    r1 = await link_entities(CHARACTER_ID, "character", FACTION_ID, "faction", alias="ally")
    assert r1.get("already_exists") is False

    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/campaigns/{CAMPAIGN_ID}/links?{q}",
        json={"data": [link_row], "page": 1, "pages": 1, "total": 1},
    )
    r2 = await link_entities(CHARACTER_ID, "character", FACTION_ID, "faction")
    assert r2.get("already_exists") is True


@pytest.mark.asyncio
async def test_link_entities_different_tuple_creates(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    q = urlencode({"page": 1, "size": 50})
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/campaigns/{CAMPAIGN_ID}/links?{q}",
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base}/v1/campaigns/{CAMPAIGN_ID}/links",
        json={"id": "11111111-1111-1111-1111-111111111112"},
        status_code=201,
    )
    await link_entities(CHARACTER_ID, "character", FACTION_ID, "faction")
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/campaigns/{CAMPAIGN_ID}/links?{q}",
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{base}/v1/campaigns/{CAMPAIGN_ID}/links",
        json={"id": "22222222-2222-2222-2222-222222222223"},
        status_code=201,
    )
    await link_entities(FACTION_ID, "faction", CHARACTER_ID, "character")
    posts = [x for x in httpx_mock.get_requests() if x.method == "POST"]
    assert len(posts) == 2
