"""Tests for ``ask_archivist`` streaming and validation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from archivist_mcp.client import ArchivistClient, ArchivistUpstreamError, AskStreamEnd
from archivist_mcp.config import load_config
from archivist_mcp.tools import ask as ask_mod
from archivist_mcp.tools.ask import ask_archivist
from archivist_mcp.validation import NonEmptySearchStr


@pytest.fixture
def ctx_mock() -> AsyncMock:
    m = AsyncMock()
    m.report_progress = AsyncMock(return_value=None)
    return m


@pytest.mark.asyncio
async def test_ask_progress_order_and_answer(ctx_mock: AsyncMock) -> None:
    async def fake_stream(_body: dict[str, Any]) -> AsyncIterator[str | AskStreamEnd]:
        yield "A"
        yield "B"
        yield "C"
        yield AskStreamEnd(
            tokens={
                "monthly_tokens_remaining": 100,
                "hourly_tokens_remaining": 10,
            }
        )

    ask_mod.client.stream_ask = fake_stream  # type: ignore[method-assign]
    try:
        out = await ask_archivist("why?", ctx=ctx_mock)
    finally:
        ask_mod.client.__dict__.pop("stream_ask", None)
    assert out["answer"] == "ABC"
    assert ctx_mock.report_progress.await_count == 3
    msgs = [c.kwargs.get("message") for c in ctx_mock.report_progress.await_args_list]
    assert msgs == ["A", "B", "C"]
    assert out["tokens"] == {"monthly_tokens_remaining": 100, "hourly_tokens_remaining": 10}


@pytest.mark.asyncio
async def test_ask_mid_stream_upstream_error(ctx_mock: AsyncMock) -> None:
    async def fake_stream(_body: dict[str, Any]) -> AsyncIterator[str | AskStreamEnd]:
        yield "A"
        raise ArchivistUpstreamError(
            correlation_id="cid-mid",
            status_code=500,
            uri="http://archivist.test/v1/ask",
            body="{}",
        )

    ask_mod.client.stream_ask = fake_stream  # type: ignore[method-assign]
    try:
        with pytest.raises(ArchivistUpstreamError) as ei:
            await ask_archivist("why?", ctx=ctx_mock)
    finally:
        ask_mod.client.__dict__.pop("stream_ask", None)
    assert ei.value.correlation_id == "cid-mid"
    assert ctx_mock.report_progress.await_count == 1


@pytest.mark.asyncio
async def test_ask_cancellation_stops_progress(ctx_mock: AsyncMock) -> None:
    closed = asyncio.Event()

    async def fake_stream(_body: dict[str, Any]) -> AsyncIterator[str | AskStreamEnd]:
        try:
            yield "A"
            await asyncio.sleep(10)
            yield "B"
            yield AskStreamEnd(tokens={})
        finally:
            closed.set()

    ask_mod.client.stream_ask = fake_stream  # type: ignore[method-assign]
    try:
        task = asyncio.create_task(ask_archivist("why?", ctx=ctx_mock))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        ask_mod.client.__dict__.pop("stream_ask", None)
    assert ctx_mock.report_progress.await_count <= 1
    await asyncio.wait_for(closed.wait(), timeout=2.0)


def _transport_ask_plain(headers: dict[str, str], body: bytes) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or not str(request.url.path).endswith("/v1/ask"):
            return httpx.Response(404, content=b"not found")
        hdrs = {
            "content-type": "text/plain; charset=utf-8",
            **headers,
        }
        return httpx.Response(200, headers=hdrs, content=body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ask_surfaces_token_budget_from_stream_headers(ctx_mock: AsyncMock) -> None:
    original = ask_mod.client
    transport = _transport_ask_plain(
        {
            "x-monthly-remaining-tokens": "5000000",
            "x-hourly-remaining-tokens": "500000",
        },
        b"hello\nworld\n",
    )
    tmp = ArchivistClient(load_config(), transport=transport)
    ask_mod.client = tmp
    try:
        out = await ask_archivist("why?", ctx=ctx_mock)
    finally:
        ask_mod.client = original
        await tmp.aclose()
    assert out["tokens"]["monthly_tokens_remaining"] == 5_000_000
    assert out["tokens"]["hourly_tokens_remaining"] == 500_000
    assert out["answer"] == "helloworld"


@pytest.mark.asyncio
async def test_ask_invalid_monthly_header_skipped_hourly_kept(ctx_mock: AsyncMock) -> None:
    original = ask_mod.client
    transport = _transport_ask_plain(
        {
            "x-monthly-remaining-tokens": "not-a-number",
            "x-hourly-remaining-tokens": "42",
        },
        b"ok\n",
    )
    tmp = ArchivistClient(load_config(), transport=transport)
    ask_mod.client = tmp
    try:
        out = await ask_archivist("why?", ctx=ctx_mock)
    finally:
        ask_mod.client = original
        await tmp.aclose()
    assert "monthly_tokens_remaining" not in out["tokens"]
    assert out["tokens"]["hourly_tokens_remaining"] == 42
    assert out["answer"] == "ok"


@pytest.mark.asyncio
async def test_ask_stream_json_token_overrides_header_snapshot(ctx_mock: AsyncMock) -> None:
    original = ask_mod.client
    transport = _transport_ask_plain(
        {
            "x-monthly-remaining-tokens": "5000000",
            "x-hourly-remaining-tokens": "500000",
        },
        b'{"monthlyTokensRemaining": 99, "hourlyTokensRemaining": 1}\n',
    )
    tmp = ArchivistClient(load_config(), transport=transport)
    ask_mod.client = tmp
    try:
        out = await ask_archivist("why?", ctx=ctx_mock)
    finally:
        ask_mod.client = original
        await tmp.aclose()
    assert out["tokens"]["monthly_tokens_remaining"] == 99
    assert out["tokens"]["hourly_tokens_remaining"] == 1


def test_ask_question_length_boundary() -> None:
    ta = TypeAdapter(NonEmptySearchStr)
    ta.validate_python("a" * 1024)
    with pytest.raises(ValidationError):
        ta.validate_python("a" * 1025)
