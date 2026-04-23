"""Tests for read_session composite tool."""

from __future__ import annotations

import os
import re

import pytest

from archivist_mcp.tools.read_session import read_session
from tests.constants import SESSION_ID


@pytest.mark.asyncio
async def test_read_session_base(httpx_mock: object) -> None:
    out = await read_session(SESSION_ID)
    assert out.get("id") == SESSION_ID


@pytest.mark.asyncio
async def test_read_session_beats_and_moments_no_excerpts(httpx_mock: object) -> None:
    out = await read_session(SESSION_ID, include=["beats", "moments"], include_excerpts=False)
    assert "beats" in out and len(out["beats"]) >= 1
    b0 = out["beats"][0]
    assert "content" not in b0
    assert "moments" in out and len(out["moments"]) >= 1
    m0 = out["moments"][0]
    assert "content" not in m0


@pytest.mark.asyncio
async def test_read_session_moments_with_excerpts(httpx_mock: object) -> None:
    out = await read_session(SESSION_ID, include=["moments"], include_excerpts=True)
    m0 = out["moments"][0]
    assert m0.get("label")
    assert m0.get("index") is not None
    # List rows usually omit content; when absent, no truncated excerpt is attached
    if "content" in m0:
        assert len(m0["content"]) <= 400


@pytest.mark.asyncio
async def test_read_session_cast_analysis_404_omits_key(httpx_mock: object) -> None:
    httpx_mock.reset()
    httpx_mock._options.assert_all_responses_were_requested = False
    base = os.environ["ARCHIVIST_BASE_URL"].rstrip("/")
    from tests.conftest import load_fixture

    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/sessions/{re.escape(SESSION_ID)}(\?.*)?$"),
        json=load_fixture("session", "detail"),
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/beats\?.*$"),
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/moments\?.*$"),
        json={"data": [], "page": 1, "pages": 1, "total": 0},
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(rf"^{re.escape(base)}/v1/sessions/{re.escape(SESSION_ID)}/cast-analysis(\?.*)?$"),
        status_code=404,
        text="{}",
    )
    out = await read_session(SESSION_ID, include=["cast_analysis"])
    assert "cast_analysis" not in out
