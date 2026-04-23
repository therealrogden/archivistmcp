"""Tests for wikilink validation."""

from __future__ import annotations

import os
import re

import pytest

from archivist_mcp.tools.wikilinks import validate_wikilinks


@pytest.mark.asyncio
async def test_validate_wikilinks_empty_when_no_markup() -> None:
    out = await validate_wikilinks("no brackets here")
    assert out == {"resolved": [], "unresolved": []}


@pytest.mark.asyncio
async def test_validate_wikilinks_resolves_fixture_character() -> None:
    out = await validate_wikilinks("Meet [[Scrubbed Character]] today.")
    assert len(out["resolved"]) == 1
    assert out["resolved"][0]["entity_type"] == "character"
    assert not out["unresolved"]


@pytest.mark.asyncio
async def test_validate_wikilinks_resolves_character_name_field(httpx_mock: object) -> None:
    """Archivist list rows use ``character_name``; wikilink index must still match."""
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    from tests.conftest import load_fixture

    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/characters\?.*$"),
        json={
            "data": [
                {
                    "id": "char_staring_grimlock",
                    "character_name": "Staring Grimlock",
                    "type": "NPC",
                }
            ],
            "total": 1,
            "page": 1,
            "size": 20,
            "pages": 1,
        },
    )
    for path, kind, name in [
        ("/v1/items", "item", "list"),
        ("/v1/factions", "faction", "list"),
        ("/v1/locations", "location", "list"),
        ("/v1/quests", "quest", "list"),
        ("/v1/journals", "journal", "list"),
    ]:
        httpx_mock.add_response(
            method="GET",
            url=re.compile(rf"^{re.escape(base)}{re.escape(path)}\?.*$"),
            json=load_fixture(kind, name),
        )
    out = await validate_wikilinks("[[Staring Grimlock]] nods.")
    assert len(out["resolved"]) == 1
    assert out["resolved"][0]["entity_id"] == "char_staring_grimlock"
    assert not out["unresolved"]


@pytest.mark.asyncio
async def test_validate_wikilinks_unresolved_with_search_miss(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    from tests.conftest import load_fixture

    for path, kind, name in [
        ("/v1/characters", "character", "list"),
        ("/v1/items", "item", "list"),
        ("/v1/factions", "faction", "list"),
        ("/v1/locations", "location", "list"),
        ("/v1/quests", "quest", "list"),
        ("/v1/journals", "journal", "list"),
    ]:
        httpx_mock.add_response(
            method="GET",
            url=re.compile(rf"^{re.escape(base)}{re.escape(path)}\?.*$"),
            json=load_fixture(kind, name),
        )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/search\?.*$"),
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    out = await validate_wikilinks("[[Totally Unknown Entity]]")
    assert not out["resolved"]
    assert len(out["unresolved"]) == 1
    assert out["unresolved"][0]["name"] == "Totally Unknown Entity"
