"""Tests for ``search_entities`` (lexical search + slim projections)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from archivist_mcp.projections import project_slim
from archivist_mcp.tools.search import search_entities
from archivist_mcp.validation import NonEmptySearchStr, SearchFilters
from tests.constants import CAMPAIGN_ID
from tests.conftest import load_fixture


@pytest.mark.asyncio
async def test_search_types_character_only(httpx_mock: Any) -> None:
    base = "http://archivist.test"
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"{re.escape(base)}/v1/search\?.*"),
        json=load_fixture("search", "mixed"),
    )
    out = await search_entities("scrub", types=["character"])
    kinds = {x["kind"] for x in out}
    assert kinds == {"character"}
    assert len(out) == 1


@pytest.mark.asyncio
async def test_search_types_character_and_item_union(httpx_mock: Any) -> None:
    base = "http://archivist.test"
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"{re.escape(base)}/v1/search\?.*"),
        json=load_fixture("search", "mixed"),
    )
    out = await search_entities("scrub", types=["character", "item"])
    kinds = {x["kind"] for x in out}
    assert kinds == {"character", "item"}
    assert "faction" not in kinds
    assert len(out) == 2


@pytest.mark.asyncio
async def test_search_empty_results(httpx_mock: Any) -> None:
    base = "http://archivist.test"
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"{re.escape(base)}/v1/search\?.*"),
        json=load_fixture("search", "empty"),
    )
    out = await search_entities("nomatch")
    assert out == []


def test_search_filters_unknown_key() -> None:
    with pytest.raises(ValidationError) as ei:
        SearchFilters.model_validate({"nonsense": 1})
    err = str(ei.value).lower()
    assert "nonsense" in err


@pytest.mark.asyncio
async def test_search_each_row_matches_project_slim(httpx_mock: Any) -> None:
    base = "http://archivist.test"
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"{re.escape(base)}/v1/search\?.*"),
        json=load_fixture("search", "mixed"),
    )
    raw = load_fixture("search", "mixed")["data"]
    out = await search_entities("scrub")
    assert len(out) == len(raw)
    for item, row in zip(out, raw, strict=True):
        kind = row["kind"]
        assert isinstance(kind, str)
        assert item["kind"] == kind
        entity = {k: v for k, v in row.items() if k != "kind"}
        assert kind in ("character", "item", "faction")
        expected = project_slim(entity, kind)  # type: ignore[arg-type]
        slim_part = {k: v for k, v in item.items() if k != "kind"}
        assert slim_part == expected


def test_search_query_length_boundary() -> None:
    ta = TypeAdapter(NonEmptySearchStr)
    ta.validate_python("a" * 1024)
    with pytest.raises(ValidationError):
        ta.validate_python("a" * 1025)


@pytest.mark.asyncio
async def test_search_forwards_campaign_and_query(httpx_mock: Any) -> None:
    base = "http://archivist.test"
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"{re.escape(base)}/v1/search\?.*"),
        json=load_fixture("search", "mixed"),
    )
    await search_entities("findme", types=["quest"], filters=SearchFilters(status="active"))
    req = httpx_mock.get_request()
    assert str(req.url).startswith(f"{base}/v1/search")
    q = str(req.url)
    assert CAMPAIGN_ID in q
    assert "findme" in q
    assert "quest" in q
    assert "status=active" in q or "status=active".replace("=", "%3D") in q
