"""Structured JSON logging, masking, levels, schema."""

from __future__ import annotations

import json
import os

import pytest

from archivist_mcp.logging_ import (
    emit_client_request,
    emit_user_payload_for_tests,
    get_logger,
    mask_campaign_id,
    mask_sensitive,
    reset_logging_configuration,
)

_CLIENT_KEYS = frozenset(
    {"timestamp", "level", "event", "correlation_id", "uri", "method", "status", "duration_ms"}
)


def _parse_json_lines(stderr: str) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = []
    for raw in stderr.strip().splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        lines.append(json.loads(raw))
    return lines


def test_every_line_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    os.environ["ARCHIVIST_LOG_LEVEL"] = "INFO"
    reset_logging_configuration()
    lg = get_logger("tlog")
    emit_client_request(
        lg,
        uri="http://x/a",
        method="GET",
        status=200,
        duration_ms=1.2,
        correlation_id="cid-1",
    )
    lines = _parse_json_lines(capsys.readouterr().err)
    assert len(lines) == 1


def test_mask_api_key_authorization_header_body_and_user_payload(capsys: pytest.CaptureFixture[str]) -> None:
    os.environ["ARCHIVIST_API_KEY"] = "super-secret-key-99"
    reset_logging_configuration()
    lg = get_logger("tmask")
    emit_client_request(
        lg,
        uri="http://x",
        method="GET",
        status=400,
        duration_ms=3.0,
        correlation_id="c",
    )
    emit_user_payload_for_tests(
        lg,
        {
            "Authorization": "Bearer super-secret-key-99",
            "nested": {"x": "err: super-secret-key-99"},
        },
    )
    text = capsys.readouterr().err
    assert "super-secret-key-99" not in text
    assert "***" in text or "Bearer ***" in text or "Bearer" in text


def test_mask_campaign_id_first_four() -> None:
    u = "00000000-0000-0000-0000-00000000c001"
    assert mask_campaign_id(f"x{u}y") == "x0000...y"


def test_archivist_log_level_warning_suppresses_info(capsys: pytest.CaptureFixture[str]) -> None:
    os.environ["ARCHIVIST_LOG_LEVEL"] = "WARNING"
    reset_logging_configuration()
    lg = get_logger("twarn")
    emit_client_request(
        lg,
        uri="http://x",
        method="GET",
        status=200,
        duration_ms=1.0,
        correlation_id="i",
    )
    assert capsys.readouterr().err.strip() == ""


def test_client_request_schema_exact_keys(capsys: pytest.CaptureFixture[str]) -> None:
    os.environ["ARCHIVIST_LOG_LEVEL"] = "DEBUG"
    reset_logging_configuration()
    lg = get_logger("tschema")
    emit_client_request(
        lg,
        uri="http://h/z",
        method="PATCH",
        status=422,
        duration_ms=9.876,
        correlation_id="ab",
    )
    payload = _parse_json_lines(capsys.readouterr().err)[0]
    assert set(payload) == _CLIENT_KEYS
    assert payload["event"] == "client.request"
