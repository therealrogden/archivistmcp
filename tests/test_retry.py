"""GET retry policy, write fail-fast, correlation IDs in errors and logs."""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from archivist_mcp.client import ArchivistClient, ArchivistUpstreamError
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


def _client_req_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    err = capsys.readouterr().err
    out: list[dict[str, object]] = []
    for line in err.strip().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("event") == "client.request":
            out.append(d)
    return out


@pytest.mark.asyncio
async def test_get_429_retries_twice_then_success(httpx_mock: object, capsys: pytest.CaptureFixture[str]) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    u = f"{base}/v1/r-probe"
    httpx_mock.add_response(method="GET", url=u, status_code=429)
    httpx_mock.add_response(method="GET", url=u, status_code=429)
    httpx_mock.add_response(method="GET", url=u, json={"done": True})
    sleeps: list[float] = []

    async def fake_sleep(t: float) -> None:
        sleeps.append(t)

    client = ArchivistClient(_cfg(), jitter_factory=lambda: 1.0, sleep=fake_sleep)
    try:
        out = await client.get("/v1/r-probe")
        assert out == {"done": True}
        assert sleeps == [0.25, 0.5]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_500_exhaustion_raises_with_correlation_id(httpx_mock: object, capsys: pytest.CaptureFixture[str]) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    u = f"{base}/v1/r-fail"
    for _ in range(3):
        httpx_mock.add_response(method="GET", url=u, status_code=500, text="no")
    client = ArchivistClient(_cfg(), jitter_factory=lambda: 1.0, sleep=lambda _: asyncio.sleep(0))
    try:
        with pytest.raises(ArchivistUpstreamError) as ei:
            await client.get("/v1/r-fail")
        assert ei.value.status_code == 500
        cid = ei.value.correlation_id
        lines = _client_req_lines(capsys)
        assert lines[-1]["correlation_id"] == cid
        assert lines[-1]["status"] == 500
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_400_no_retry(httpx_mock: object) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    u = f"{base}/v1/r-400"
    httpx_mock.add_response(method="GET", url=u, status_code=400, text="bad")
    client = ArchivistClient(_cfg(), jitter_factory=lambda: 1.0, sleep=lambda _: asyncio.sleep(0))
    try:
        with pytest.raises(ArchivistUpstreamError) as ei:
            await client.get("/v1/r-400")
        assert ei.value.status_code == 400
        reqs = httpx_mock.get_requests(method="GET", url=u)
        assert len(reqs) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_404_no_retry(httpx_mock: object) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    u = f"{base}/v1/r-404"
    httpx_mock.add_response(method="GET", url=u, status_code=404, text="nope")
    client = ArchivistClient(_cfg(), jitter_factory=lambda: 1.0, sleep=lambda _: asyncio.sleep(0))
    try:
        with pytest.raises(ArchivistUpstreamError):
            await client.get("/v1/r-404")
        assert len(httpx_mock.get_requests(method="GET", url=u)) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_500_no_retry(httpx_mock: object) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    u = f"{base}/v1/r-post"
    httpx_mock.add_response(method="POST", url=u, status_code=500, text="err")
    client = ArchivistClient(_cfg(), sleep=lambda _: asyncio.sleep(0))
    try:
        with pytest.raises(ArchivistUpstreamError) as ei:
            await client.post("/v1/r-post", json={})
        assert ei.value.status_code == 500
        assert len(httpx_mock.get_requests(method="POST", url=u)) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_429_no_retry(httpx_mock: object) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    u = f"{base}/v1/r-post429"
    httpx_mock.add_response(method="POST", url=u, status_code=429)
    client = ArchivistClient(_cfg(), sleep=lambda _: asyncio.sleep(0))
    try:
        with pytest.raises(ArchivistUpstreamError) as ei:
            await client.post("/v1/r-post429", json={})
        assert ei.value.status_code == 429
        assert len(httpx_mock.get_requests(method="POST", url=u)) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_correlation_id_matches_exception_and_log(httpx_mock: object, capsys: pytest.CaptureFixture[str]) -> None:
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    u = f"{base}/v1/r-corr"
    httpx_mock.add_response(method="GET", url=u, status_code=400, text="x")
    client = ArchivistClient(_cfg(), sleep=lambda _: asyncio.sleep(0))
    try:
        with pytest.raises(ArchivistUpstreamError) as ei:
            await client.get("/v1/r-corr")
        cid = ei.value.correlation_id
        lines = _client_req_lines(capsys)
        assert lines and lines[-1]["correlation_id"] == cid
    finally:
        await client.aclose()
