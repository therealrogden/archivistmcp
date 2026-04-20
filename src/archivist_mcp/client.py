"""HTTP client for Archivist: cache, single-flight reads, GET retries, serialized writes."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .cache import (
    Cache,
    invalidation_url_prefixes,
    ttl_seconds_for_request_url,
)
from .concurrency import WriteLock, single_flight_read
from .config import Config
from .logging_ import emit_cache, emit_client_request, get_logger

_LOG = get_logger("client")

BACKOFF_BASE_SECONDS = 0.25
BACKOFF_FACTOR = 2
MAX_GET_ATTEMPTS = 3
BODY_SNIPPET_MAX = 2048


def _default_jitter() -> float:
    return 0.75 + random.random() * 0.5


@dataclass(frozen=True)
class AskStreamEnd:
    """Sentinel yielded last by :meth:`ArchivistClient.stream_ask` with token-budget metadata."""

    tokens: dict[str, Any]


class ArchivistUpstreamError(Exception):
    """Raised when Archivist returns an error after the retry policy has been applied (GET) or immediately (writes)."""

    def __init__(
        self,
        *,
        correlation_id: str,
        status_code: int | None,
        uri: str,
        body: str,
    ) -> None:
        self.correlation_id = correlation_id
        self.status_code = status_code
        self.uri = uri
        self.body = body
        super().__init__(f"upstream {status_code} for {uri} [{correlation_id}]")


def _token_fields_from_obj(obj: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "monthlyTokensRemaining",
        "hourlyTokensRemaining",
        "input_tokens",
        "output_tokens",
        "total_tokens",
    )
    return {k: obj[k] for k in keys if k in obj}


def _text_deltas_from_json_obj(obj: Any) -> list[str]:
    """Best-effort extraction of streamed assistant text from Archivist / OpenAI-like shapes."""
    if isinstance(obj, str) and obj:
        return [obj]
    if not isinstance(obj, dict):
        return []
    out: list[str] = []
    for key in ("content", "text", "token"):
        v = obj.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    ans = obj.get("answer")
    if isinstance(ans, str) and ans:
        out.append(ans)
    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        d0 = choices[0]
        if isinstance(d0, dict):
            delta = d0.get("delta")
            if isinstance(delta, dict):
                c = delta.get("content")
                if isinstance(c, str) and c:
                    out.append(c)
    return out


def _parse_ask_stream_line(line: str) -> tuple[list[str], dict[str, Any]]:
    """One SSE or NDJSON line → text chunks and token-field updates."""
    s = line.strip()
    if not s:
        return [], {}
    if s.startswith("data:"):
        s = s[5:].strip()
    if s == "[DONE]":
        return [], {}
    try:
        obj: Any = json.loads(s)
    except json.JSONDecodeError:
        return ([s] if s else []), {}
    if not isinstance(obj, dict):
        return [], {}
    return _text_deltas_from_json_obj(obj), _token_fields_from_obj(obj)


class ArchivistClient:
    def __init__(
        self,
        config: Config,
        timeout: float = 30.0,
        *,
        cache: Cache | None = None,
        jitter_factory: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        client_kw: dict[str, Any] = {
            "base_url": config.base_url,
            "headers": {"x-api-key": config.api_key},
            "timeout": timeout,
        }
        if transport is not None:
            client_kw["transport"] = transport
        self._client = httpx.AsyncClient(**client_kw)
        self._cache = cache if cache is not None else Cache()
        self._jitter_factory = jitter_factory or _default_jitter
        self._sleep = sleep if sleep is not None else asyncio.sleep

    @property
    def campaign_id(self) -> str:
        return self._config.campaign_id

    def _build_url(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> str:
        req = self._client.build_request(method, path, params=params)
        return str(req.url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        return await self.get("/health")

    def _response_body_snippet(self, response: httpx.Response) -> str:
        try:
            text = response.text
        except Exception:
            text = ""
        if len(text) > BODY_SNIPPET_MAX:
            return text[:BODY_SNIPPET_MAX]
        return text

    def _json_or_empty(self, response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def _sleep_backoff(self, attempt_index: int) -> None:
        delay = BACKOFF_BASE_SECONDS * (BACKOFF_FACTOR**attempt_index) * self._jitter_factory()
        await self._sleep(delay)

    async def _execute_get_with_retries(self, path: str, params: dict[str, Any] | None, url_key: str) -> Any:
        correlation_id = str(uuid.uuid4())
        last_response: httpx.Response | None = None
        for attempt in range(MAX_GET_ATTEMPTS):
            t0 = time.perf_counter()
            response = await self._client.get(path, params=params)
            duration_ms = (time.perf_counter() - t0) * 1000
            uri = str(response.request.url)
            emit_client_request(
                _LOG,
                uri=uri,
                method="GET",
                status=response.status_code,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                level=(logging.INFO if response.is_success else logging.WARNING),
            )
            last_response = response
            if response.is_success:
                return self._json_or_empty(response)
            if response.status_code != 429 and not (500 <= response.status_code <= 599):
                raise ArchivistUpstreamError(
                    correlation_id=correlation_id,
                    status_code=response.status_code,
                    uri=uri,
                    body=self._response_body_snippet(response),
                )
            if attempt == MAX_GET_ATTEMPTS - 1:
                break
            await self._sleep_backoff(attempt)

        assert last_response is not None
        raise ArchivistUpstreamError(
            correlation_id=correlation_id,
            status_code=last_response.status_code,
            uri=str(last_response.request.url),
            body=self._response_body_snippet(last_response),
        )

    async def get(self, path: str, **params: Any) -> Any:
        p = params or None
        url_key = self._build_url("GET", path, params=p)

        async def guarded() -> Any:
            ttl = ttl_seconds_for_request_url(url_key)
            if ttl is None:
                return await self._execute_get_with_retries(path, p, url_key)
            cached = self._cache.get(url_key)
            if cached is not None:
                remaining = self._cache.ttl_remaining_seconds(url_key)
                emit_cache(_LOG, uri=url_key, action="hit", ttl_remaining_s=remaining)
                return cached
            emit_cache(_LOG, uri=url_key, action="miss", ttl_remaining_s=None)
            gen_at_miss = self._cache.generation()
            body = await self._execute_get_with_retries(path, p, url_key)
            if self._cache.generation() == gen_at_miss:
                self._cache.set(url_key, body, ttl)
            return body

        return await single_flight_read(url_key, guarded)

    async def _write_once(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        correlation_id = str(uuid.uuid4())
        t0 = time.perf_counter()
        if method == "POST":
            response = await self._client.post(path, json=json_body)
        elif method == "PATCH":
            response = await self._client.patch(path, json=json_body)
        elif method == "DELETE":
            response = await self._client.delete(path)
        else:
            raise ValueError(method)
        duration_ms = (time.perf_counter() - t0) * 1000
        uri = str(response.request.url)
        emit_client_request(
            _LOG,
            uri=uri,
            method=method,
            status=response.status_code,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            level=(logging.INFO if response.is_success else logging.WARNING),
        )
        if not response.is_success:
            raise ArchivistUpstreamError(
                correlation_id=correlation_id,
                status_code=response.status_code,
                uri=uri,
                body=self._response_body_snippet(response),
            )
        for prefix in invalidation_url_prefixes(self._config.base_url, method, path):
            self._cache.invalidate_prefix(prefix)
        return self._json_or_empty(response)

    async def post(self, path: str, json: dict[str, Any]) -> Any:
        async with WriteLock():
            return await self._write_once("POST", path, json_body=json)

    async def patch(self, path: str, json: dict[str, Any]) -> Any:
        async with WriteLock():
            return await self._write_once("PATCH", path, json_body=json)

    async def delete(self, path: str) -> None:
        async with WriteLock():
            await self._write_once("DELETE", path, json_body=None)

    async def search_entities_get(self, params: dict[str, Any]) -> Any:
        """Lexical search (``GET /v1/search``); uncached, GET retries only."""
        return await self.get("/v1/search", **params)

    async def stream_ask(self, json_body: dict[str, Any]) -> AsyncIterator[str | AskStreamEnd]:
        """POST ``/v1/ask`` with ``stream: true``; yields text chunks then :class:`AskStreamEnd`.

        Does not use the write lock or response-body cache (read-only streaming POST).
        No automatic retries on failure.
        """
        correlation_id = str(uuid.uuid4())
        merged_tokens: dict[str, Any] = {}
        t0 = time.perf_counter()
        uri = self._build_url("POST", "/v1/ask", params=None)
        try:
            async with self._client.stream("POST", "/v1/ask", json=json_body) as response:
                uri = str(response.request.url)
                if response.status_code >= 400:
                    await response.aread()
                    emit_client_request(
                        _LOG,
                        uri=uri,
                        method="POST",
                        status=response.status_code,
                        duration_ms=(time.perf_counter() - t0) * 1000,
                        correlation_id=correlation_id,
                        level=logging.WARNING,
                    )
                    raise ArchivistUpstreamError(
                        correlation_id=correlation_id,
                        status_code=response.status_code,
                        uri=uri,
                        body=self._response_body_snippet(response),
                    )
                async for line in response.aiter_lines():
                    text_parts, tok = _parse_ask_stream_line(line)
                    merged_tokens.update(tok)
                    for part in text_parts:
                        yield part
                duration_ms = (time.perf_counter() - t0) * 1000
                emit_client_request(
                    _LOG,
                    uri=uri,
                    method="POST",
                    status=response.status_code,
                    duration_ms=duration_ms,
                    correlation_id=correlation_id,
                    level=logging.INFO,
                )
        except ArchivistUpstreamError:
            raise
        except asyncio.CancelledError:
            emit_client_request(
                _LOG,
                uri=uri,
                method="POST",
                status=None,
                duration_ms=(time.perf_counter() - t0) * 1000,
                correlation_id=correlation_id,
                level=logging.WARNING,
            )
            raise
        except Exception as exc:
            emit_client_request(
                _LOG,
                uri=uri,
                method="POST",
                status=None,
                duration_ms=(time.perf_counter() - t0) * 1000,
                correlation_id=correlation_id,
                level=logging.WARNING,
            )
            raise ArchivistUpstreamError(
                correlation_id=correlation_id,
                status_code=None,
                uri=uri,
                body=str(exc)[:BODY_SNIPPET_MAX],
            ) from exc
        yield AskStreamEnd(tokens=merged_tokens)