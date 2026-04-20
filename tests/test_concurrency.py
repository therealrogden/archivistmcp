"""Single-flight reads, write lock, read vs write ordering."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

import httpx
import pytest

from archivist_mcp.cache import Cache
from archivist_mcp.client import ArchivistClient
from archivist_mcp.config import Config
from tests.constants import CAMPAIGN_ID


def _cfg() -> Config:
    return Config(
        api_key=os.environ["ARCHIVIST_API_KEY"],
        campaign_id=CAMPAIGN_ID,
        base_url=os.environ["ARCHIVIST_BASE_URL"].rstrip("/"),
        mechanics_folder="Items/Mechanics",
        overview_folder="Campaign Overview",
        history_folder="Summary History",
    )


@pytest.mark.asyncio
async def test_single_flight_two_cold_reads_one_upstream() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"data": [1]})

    transport = httpx.MockTransport(handler)
    cache = Cache()
    client = ArchivistClient(
        _cfg(),
        cache=cache,
        jitter_factory=lambda: 1.0,
        transport=transport,
    )
    try:
        a, b = await asyncio.gather(
            client.get("/v1/items", campaign_id=CAMPAIGN_ID, page=1, page_size=50),
            client.get("/v1/items", campaign_id=CAMPAIGN_ID, page=1, page_size=50),
        )
        assert a == b == {"data": [1]}
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_concurrent_reads_different_paths_two_upstream() -> None:
    paths_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths_seen.append(request.url.path)
        return httpx.Response(200, json={"path": request.url.path})

    transport = httpx.MockTransport(handler)
    client = ArchivistClient(_cfg(), cache=Cache(), transport=transport)
    try:
        await asyncio.gather(
            client.get("/v1/items", campaign_id=CAMPAIGN_ID),
            client.get("/v1/sessions", campaign_id=CAMPAIGN_ID),
        )
        assert set(paths_seen) == {"/v1/items", "/v1/sessions"}
        assert len(paths_seen) == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_concurrent_writes_serialized_upstream() -> None:
    order: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        order.append("upstream")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = ArchivistClient(_cfg(), cache=Cache(), transport=transport)
    try:
        await asyncio.gather(
            client.post("/v1/items", json={"name": "a"}),
            client.post("/v1/items", json={"name": "b"}),
        )
        assert order == ["upstream", "upstream"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_write_invalidates_before_next_read_fetches_fresh() -> None:
    """POST clears cached list; following GET sees new upstream payload."""
    phase = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            phase["n"] += 1
            return httpx.Response(200, json={"v": phase["n"]})
        return httpx.Response(200, json={"created": True})

    transport = httpx.MockTransport(handler)
    cache = Cache()
    client = ArchivistClient(_cfg(), cache=cache, transport=transport)
    try:
        first = await client.get("/v1/items", campaign_id=CAMPAIGN_ID, page=1, page_size=50)
        assert first == {"v": 1}
        second = await client.get("/v1/items", campaign_id=CAMPAIGN_ID, page=1, page_size=50)
        assert second == {"v": 1}
        await client.post("/v1/items", json={"name": "x"})
        third = await client.get("/v1/items", campaign_id=CAMPAIGN_ID, page=1, page_size=50)
        assert third == {"v": 2}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_write_during_read_skips_stale_cache_fill_subsequent_read_fresh() -> None:
    gate = threading.Event()
    posted = {"v": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if not posted["v"]:
                gate.wait(timeout=10.0)
                return httpx.Response(200, json={"phase": "during"})
            return httpx.Response(200, json={"phase": "after"})
        posted["v"] = True
        return httpx.Response(200, json={"w": 1})

    transport = httpx.MockTransport(handler)
    cache = Cache()
    client = ArchivistClient(_cfg(), cache=cache, transport=transport)
    try:
        read_task = asyncio.create_task(
            client.get("/v1/items", campaign_id=CAMPAIGN_ID, page=1, page_size=50)
        )
        await asyncio.sleep(0.05)
        await client.post("/v1/items", json={"name": "z"})
        gate.set()
        in_flight = await read_task
        assert in_flight == {"phase": "during"}
        fresh = await client.get("/v1/items", campaign_id=CAMPAIGN_ID, page=1, page_size=50)
        assert fresh == {"phase": "after"}
    finally:
        gate.set()
        await client.aclose()
