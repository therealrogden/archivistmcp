"""Structured JSON logs to stderr (stdlib logging only)."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

_CONFIGURED = False


def reset_logging_configuration() -> None:
    """Clear handlers so the next :func:`get_logger` call re-reads ``ARCHIVIST_LOG_LEVEL`` (tests only)."""
    global _CONFIGURED
    _CONFIGURED = False
    root = logging.getLogger("archivist_mcp")
    root.handlers.clear()
    root.setLevel(logging.NOTSET)

# Strict allowlists: emitted JSON objects use exactly these keys (``null`` allowed where JSON permits).
_CLIENT_REQUEST_KEYS = frozenset(
    {"timestamp", "level", "event", "correlation_id", "uri", "method", "status", "duration_ms"}
)
_CACHE_EVENT_KEYS = frozenset({"timestamp", "level", "event", "uri", "action", "ttl_remaining_s"})
_USER_PAYLOAD_KEYS = frozenset({"timestamp", "level", "event", "body"})


class _ArchivistJsonHandler(logging.Handler):
    """Emit only records carrying ``archivist_json`` as a single JSON line."""

    terminator = "\n"

    def __init__(self, stream: Any = None) -> None:
        super().__init__(level=logging.DEBUG)
        self._stream_override = stream

    def emit(self, record: logging.LogRecord) -> None:
        payload = getattr(record, "archivist_json", None)
        if not isinstance(payload, dict):
            return
        stream = self._stream_override if self._stream_override is not None else sys.stderr
        try:
            stream.write(json.dumps(payload, separators=(",", ":")) + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        stream = self._stream_override if self._stream_override is not None else sys.stderr
        if hasattr(stream, "flush"):
            stream.flush()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _level_name(level: int) -> str:
    return logging.getLevelName(level)


def mask_api_key(value: Any) -> Any:
    """Return ``value`` with ``ARCHIVIST_API_KEY`` substrings redacted."""
    key = os.environ.get("ARCHIVIST_API_KEY", "")
    if not key or not isinstance(value, str):
        return value
    return value.replace(key, "***")


def mask_campaign_id(value: Any) -> Any:
    """Mask canonical UUID campaign IDs to ``ffff...`` (first four hex chars + ``...``)."""
    if not isinstance(value, str):
        return value
    uuid_re = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    )

    def _sub(m: re.Match[str]) -> str:
        u = m.group(0)
        return u[:4].lower() + "..."

    return uuid_re.sub(_sub, value)


def mask_sensitive(value: Any) -> Any:
    """Apply API key and campaign-id masking throughout nested structures."""
    key = os.environ.get("ARCHIVIST_API_KEY", "")
    cid = os.environ.get("ARCHIVIST_CAMPAIGN_ID", "")

    def _walk(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: _walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [_walk(v) for v in x]
        if isinstance(x, str):
            s = x
            if key:
                s = s.replace(key, "***")
            if cid:
                s = s.replace(cid, cid[:4].lower() + "..." if len(cid) >= 4 else "***")
            if key:
                s = s.replace(key, "***")
            return s
        return x

    return _walk(value)


def _validate_exact_keys(keys: frozenset[str], payload: dict[str, Any]) -> None:
    if set(payload) != keys:
        raise ValueError(f"Log key mismatch: expected {keys!r}, got {set(payload)!r}")


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = os.environ.get("ARCHIVIST_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger("archivist_mcp")
    root.handlers.clear()
    root.setLevel(level)
    h = _ArchivistJsonHandler()
    h.setLevel(level)
    root.addHandler(h)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under ``archivist_mcp`` with JSON stderr output."""
    _configure_root()
    return logging.getLogger(f"archivist_mcp.{name}")


def emit_client_request(
    logger: logging.Logger,
    *,
    uri: str,
    method: str,
    status: int | None,
    duration_ms: float,
    correlation_id: str,
    level: int = logging.INFO,
) -> None:
    if not logger.isEnabledFor(level):
        return
    payload: dict[str, Any] = {
        "timestamp": _utc_timestamp(),
        "level": _level_name(level),
        "event": "client.request",
        "correlation_id": correlation_id,
        "uri": mask_sensitive(uri),
        "method": method,
        "status": status,
        "duration_ms": round(duration_ms, 3),
    }
    _validate_exact_keys(_CLIENT_REQUEST_KEYS, payload)
    record = logger.makeRecord(
        logger.name,
        level,
        "(archivist)",
        0,
        "",
        (),
        None,
    )
    record.archivist_json = mask_sensitive(payload)
    logger.handle(record)


def emit_cache(
    logger: logging.Logger,
    *,
    uri: str,
    action: str,
    ttl_remaining_s: float | None,
    level: int = logging.INFO,
) -> None:
    if not logger.isEnabledFor(level):
        return
    payload: dict[str, Any] = {
        "timestamp": _utc_timestamp(),
        "level": _level_name(level),
        "event": "cache",
        "uri": mask_sensitive(uri),
        "action": action,
        "ttl_remaining_s": ttl_remaining_s,
    }
    _validate_exact_keys(_CACHE_EVENT_KEYS, payload)
    record = logger.makeRecord(logger.name, level, "(archivist)", 0, "", (), None)
    record.archivist_json = mask_sensitive(payload)
    logger.handle(record)


def emit_user_payload_for_tests(logger: logging.Logger, body: dict[str, Any]) -> None:
    """Log a masked arbitrary dict (tests: ``extra``-style payloads). Schema: ``logging.user_payload``."""
    if not logger.isEnabledFor(logging.INFO):
        return
    masked = mask_sensitive(body)
    payload: dict[str, Any] = {
        "timestamp": _utc_timestamp(),
        "level": "INFO",
        "event": "logging.user_payload",
        "body": masked,
    }
    _validate_exact_keys(_USER_PAYLOAD_KEYS, payload)
    record = logger.makeRecord(logger.name, logging.INFO, "(archivist)", 0, "", (), None)
    record.archivist_json = payload
    logger.handle(record)
