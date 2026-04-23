"""Tests for ``register_item`` / ``promote_item_to_homebrew`` (DESIGN.md step 14)."""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode

import pytest

from archivist_mcp.tools.items import promote_item_to_homebrew, register_item
from tests.constants import CAMPAIGN_ID, ITEM_ID

ITEMS_PARENT_ID = "11111111-1111-1111-1111-111111111110"
MECH_CHILD_ID = "22222222-2222-2222-2222-222222222220"
NEW_ITEM_ID = "33333333-3333-3333-3333-333333333330"
MECH_JOURNAL_ID = "44444444-4444-4444-4444-444444444440"


def _folder_pair_response() -> dict:
    return {
        "data": [
            {"id": ITEMS_PARENT_ID, "name": "Items", "parent_id": None},
            {"id": MECH_CHILD_ID, "name": "Mechanics", "parent_id": ITEMS_PARENT_ID},
        ],
        "page": 1,
        "pages": 1,
        "total": 2,
    }


@pytest.mark.asyncio
async def test_register_item_narrative_only_always_posts(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    qi = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(method="POST", url=f"{base}/v1/items", json={"id": NEW_ITEM_ID}, status_code=201)
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/items/{NEW_ITEM_ID}",
        json={
            "id": NEW_ITEM_ID,
            "name": "Sending Stone",
            "description": "first",
            "type": "wondrous item",
        },
    )
    await register_item("Sending Stone", "first", mechanics=None)
    httpx_mock.add_response(method="POST", url=f"{base}/v1/items", json={"id": MECH_JOURNAL_ID}, status_code=201)
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/items/{MECH_JOURNAL_ID}",
        json={
            "id": MECH_JOURNAL_ID,
            "name": "Sending Stone",
            "description": "second",
            "type": "wondrous item",
        },
    )
    await register_item("Sending Stone", "second", mechanics=None)
    posts = [x for x in httpx_mock.get_requests() if x.method == "POST" and str(x.url).startswith(f"{base}/v1/items")]
    assert len(posts) == 2


@pytest.mark.asyncio
async def test_register_item_mechanics_dedupe_same_signature(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    qi = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    mech = {"damage": "1d8", "rarity": "rare"}
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/items?{qi}",
        json={
            "data": [
                {
                    "id": ITEM_ID,
                    "name": "Blade",
                    "type": "weapon",
                    "mechanics": mech,
                }
            ],
            "page": 1,
            "pages": 1,
            "total": 1,
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/items/{ITEM_ID}",
        json={"id": ITEM_ID, "name": "Blade", "type": "weapon", "mechanics": mech, "description": "x"},
    )
    r = await register_item("Blade", "new desc", mechanics=mech)
    assert r["already_exists"] is True
    assert r["item"]["id"] == ITEM_ID
    assert not any(x.method == "POST" and str(x.url).rstrip("/") == f"{base}/v1/items" for x in httpx_mock.get_requests())


@pytest.mark.asyncio
async def test_register_item_mechanics_different_signature_creates(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    qi = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/items?{qi}",
        json={
            "data": [
                {
                    "id": ITEM_ID,
                    "name": "Blade",
                    "type": "weapon",
                    "mechanics": {"damage": "1d8"},
                }
            ],
            "page": 1,
            "pages": 1,
            "total": 1,
        },
    )
    httpx_mock.add_response(method="POST", url=f"{base}/v1/items", json={"id": NEW_ITEM_ID}, status_code=201)
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/items/{NEW_ITEM_ID}",
        json={"id": NEW_ITEM_ID, "name": "Blade", "description": "d", "type": "weapon"},
    )
    qf = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(method="GET", url=f"{base}/v1/journal-folders?{qf}", json=_folder_pair_response())
    httpx_mock.add_response(method="POST", url=f"{base}/v1/journals", json={"id": MECH_JOURNAL_ID}, status_code=201)
    httpx_mock.add_response(
        method="PATCH",
        url=f"{base}/v1/items/{NEW_ITEM_ID}",
        json={"id": NEW_ITEM_ID, "name": "Blade", "description": "d\n\nSee mechanics: [[Blade — Mechanics]]"},
    )
    r = await register_item("Blade", "d", mechanics={"damage": "2d6"})
    assert r["already_exists"] is False
    posts = [x for x in httpx_mock.get_requests() if x.method == "POST" and str(x.url).rstrip("/") == f"{base}/v1/items"]
    assert len(posts) == 1


@pytest.mark.asyncio
async def test_register_item_wondrous_type_space_form_on_wire(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    from archivist_mcp.validation import ItemType

    qi = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(method="GET", url=f"{base}/v1/items?{qi}", json={"data": [], "page": 1, "pages": 1, "total": 0})
    httpx_mock.add_response(method="POST", url=f"{base}/v1/items", json={"id": NEW_ITEM_ID}, status_code=201)
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/items/{NEW_ITEM_ID}",
        json={"id": NEW_ITEM_ID, "name": "Cape", "description": "d", "type": "wondrous item"},
    )
    qf = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(method="GET", url=f"{base}/v1/journal-folders?{qf}", json=_folder_pair_response())
    httpx_mock.add_response(method="POST", url=f"{base}/v1/journals", json={"id": MECH_JOURNAL_ID}, status_code=201)
    httpx_mock.add_response(method="PATCH", url=f"{base}/v1/items/{NEW_ITEM_ID}", json={})
    await register_item(
        "Cape",
        "d",
        mechanics={"notes": "x"},
        item_type=ItemType.WONDROUS_ITEM,
    )
    post_item = next(
        x for x in httpx_mock.get_requests() if x.method == "POST" and str(x.url).rstrip("/") == f"{base}/v1/items"
    )
    body = json.loads(post_item.content.decode())
    assert body["type"] == "wondrous item"


@pytest.mark.asyncio
async def test_promote_item_to_homebrew_upserts_journal_and_patches_item(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/items/{ITEM_ID}",
        json={"id": ITEM_ID, "name": "Sword", "description": "plain", "type": "weapon"},
    )
    qf = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(method="GET", url=f"{base}/v1/journal-folders?{qf}", json=_folder_pair_response())
    qj = urlencode({"campaign_id": CAMPAIGN_ID, "page": 1, "size": 50})
    httpx_mock.add_response(
        method="GET",
        url=f"{base}/v1/journals?{qj}",
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    httpx_mock.add_response(method="POST", url=f"{base}/v1/journals", json={"id": MECH_JOURNAL_ID}, status_code=201)
    httpx_mock.add_response(method="PATCH", url=f"{base}/v1/items/{ITEM_ID}", json={})
    r = await promote_item_to_homebrew(ITEM_ID, mechanics={"damage": "1d8", "rarity": "rare", "notes": "n"})
    assert r["mechanics_journal_id"] == MECH_JOURNAL_ID
    patches = [x for x in httpx_mock.get_requests() if x.method == "PATCH" and ITEM_ID in str(x.url)]
    assert patches
    pb = json.loads(patches[-1].content.decode())
    assert "See mechanics:" in pb["description"]
