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
    """RAG question against the configured campaign. Streams token text via MCP progress.

    When the host sends a progress token, each upstream text chunk is reported in order
    through ``ctx.report_progress``. The return value contains the full assembled answer and
    token budget fields from Archivist (e.g. ``monthlyTokensRemaining`` / ``hourlyTokensRemaining``)
    nested under ``tokens``.
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
