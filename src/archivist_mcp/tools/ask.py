"""``ask_archivist`` tool wrapping streaming ``POST /v1/ask``."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp.server.context import Context

from ..client import AskStreamEnd, ArchivistUpstreamError
from ..server import client, mcp
from ..validation import AskerIdStr, NonEmptySearchStr


@mcp.tool
async def ask_archivist(
    question: NonEmptySearchStr,
    asker_id: AskerIdStr = None,
    gm_permissions: bool = False,
    ctx: Context = None,  # type: ignore[assignment]  # injected by FastMCP at call time
) -> dict[str, Any]:
    """RAG question against the configured campaign.

    Upstream streams ``text/plain`` markdown over HTTP chunked encoding. When the MCP client
    sends a ``progressToken`` on ``tools/call``, each decoded text chunk is reported in order
    via ``ctx.report_progress``; without a progress token those calls are a no-op and the
    tool still returns the full ``answer`` when the stream completes.

    Returns ``{"answer": "<assembled markdown>", "tokens": {...}}``. Token budgets use
    snake_case keys ``monthly_tokens_remaining`` and ``hourly_tokens_remaining`` (sourced from
    response headers when streaming; JSON-shaped stream lines can override those values).
    """
    body: dict[str, Any] = {
        "campaign_id": client.campaign_id,
        "messages": [{"role": "user", "content": question}],
        "stream": True,
        "gm_permissions": gm_permissions,
        "asker_id": asker_id,
    }

    answer_parts: list[str] = []
    progress_i = 0
    tokens: dict[str, Any] = {}

    try:
        async for chunk in client.stream_ask(body):
            if isinstance(chunk, AskStreamEnd):
                tokens = chunk.tokens
                break
            answer_parts.append(chunk)
            progress_i += 1
            await ctx.report_progress(progress=float(progress_i), message=chunk)
    except asyncio.CancelledError:
        raise
    except ArchivistUpstreamError:
        raise

    return {"answer": "".join(answer_parts), "tokens": tokens}
