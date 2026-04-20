"""Tests for ``ask_archivist`` streaming and validation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import TypeAdapter, ValidationError

from archivist_mcp.client import ArchivistUpstreamError, AskStreamEnd
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
                "monthlyTokensRemaining": 100,
                "hourlyTokensRemaining": 10,
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
    assert out["tokens"] == {"monthlyTokensRemaining": 100, "hourlyTokensRemaining": 10}


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


def test_ask_question_length_boundary() -> None:
    ta = TypeAdapter(NonEmptySearchStr)
    ta.validate_python("a" * 1024)
    with pytest.raises(ValidationError):
        ta.validate_python("a" * 1025)
