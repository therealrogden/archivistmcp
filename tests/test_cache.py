"""TTL cache, invalidation map, and TTL classifier."""

from __future__ import annotations

import json

import pytest
from freezegun import freeze_time

from archivist_mcp.cache import (
    DETAIL_TTL_SECONDS,
    LIST_TTL_SECONDS,
    URI_INVALIDATION_MAP,
    Cache,
    invalidation_url_prefixes,
    ttl_seconds_for_request_url,
    write_route_key,
)
from archivist_mcp.logging_ import emit_cache, get_logger, reset_logging_configuration


def test_uri_invalidation_map_keys_pinned() -> None:
    expected = frozenset(URI_INVALIDATION_MAP)
    assert set(URI_INVALIDATION_MAP) == expected
    assert len(URI_INVALIDATION_MAP) == 34


def test_write_route_key_and_invalidation_prefixes() -> None:
    from tests.constants import ITEM_ID

    assert write_route_key("PATCH", f"/v1/items/{ITEM_ID}") == "PATCH /v1/items/{id}"
    base = "http://x.test"
    p = invalidation_url_prefixes(base, "PATCH", f"/v1/items/{'a' * 8}-1111-2222-3333-444444444444")
    assert p == ("http://x.test/v1/items", "http://x.test/v1/journals", "http://x.test/v1/journal-folders")


def test_ttl_classifier() -> None:
    assert ttl_seconds_for_request_url("http://h/health") is None
    assert ttl_seconds_for_request_url("http://h/v1/search?q=x") is None
    assert ttl_seconds_for_request_url("http://h/v1/items?page=1") == LIST_TTL_SECONDS
    assert ttl_seconds_for_request_url("http://h/v1/journal-folders?page=1") == DETAIL_TTL_SECONDS
    assert ttl_seconds_for_request_url("http://h/v1/items/uuid-here-not-valid") == DETAIL_TTL_SECONDS


def test_cache_hit_avoids_upstream_counter() -> None:
    c = Cache()
    calls = 0

    def upstream() -> str:
        nonlocal calls
        calls += 1
        return "x"

    k = "http://h/v1/items?campaign_id=1"
    v = upstream()
    c.set(k, v, LIST_TTL_SECONDS)
    assert c.get(k) == "x"
    assert c.get(k) == "x"
    assert calls == 1


@freeze_time("2026-01-01 00:00:00")
def test_cache_miss_logged_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    import os

    os.environ["ARCHIVIST_LOG_LEVEL"] = "DEBUG"
    reset_logging_configuration()
    lg = get_logger("test_cache")
    emit_cache(lg, uri="http://h/v1/items?p=1", action="miss", ttl_remaining_s=None)
    err = capsys.readouterr().err
    json_lines = [ln for ln in err.strip().splitlines() if ln.strip().startswith("{")]
    assert json_lines, err
    d = json.loads(json_lines[-1])
    assert d["event"] == "cache"
    assert d["action"] == "miss"
    assert d["ttl_remaining_s"] is None


@freeze_time("2026-01-01 00:00:00")
def test_list_ttl_expiry_freezegun() -> None:
    c = Cache()
    k = "http://h/v1/sessions?campaign_id=x"
    c.set(k, {"n": 1}, LIST_TTL_SECONDS)
    with freeze_time("2026-01-01 00:00:59"):
        assert c.get(k) == {"n": 1}
    with freeze_time("2026-01-01 00:01:01"):
        assert c.get(k) is None


@freeze_time("2026-01-01 00:00:00")
def test_detail_ttl_expiry_freezegun() -> None:
    c = Cache()
    k = "http://h/v1/sessions/sess-uuid-here-0000-000000000001"
    c.set(k, {"n": 2}, DETAIL_TTL_SECONDS)
    with freeze_time("2026-01-01 00:04:59"):
        assert c.get(k) == {"n": 2}
    with freeze_time("2026-01-01 00:05:01"):
        assert c.get(k) is None


def test_invalidate_prefix_item_write_clears_items_and_sessions_unrelated() -> None:
    from tests.constants import ITEM_ID

    c = Cache()
    base = "http://archivist.test"
    items_list = f"{base}/v1/items?campaign_id=c"
    item_detail = f"{base}/v1/items/{ITEM_ID}"
    sessions = f"{base}/v1/sessions?campaign_id=c"
    c.set(items_list, 1, LIST_TTL_SECONDS)
    c.set(item_detail, 2, DETAIL_TTL_SECONDS)
    c.set(sessions, 3, LIST_TTL_SECONDS)
    for px in invalidation_url_prefixes(base, "PATCH", f"/v1/items/{ITEM_ID}"):
        c.invalidate_prefix(px)
    assert c.get(items_list) is None
    assert c.get(item_detail) is None
    assert c.get(sessions) == 3


def test_manual_invalidate_prefix() -> None:
    c = Cache()
    c.set("http://x/v1/items?p=1", 1, 60)
    c.set("http://x/v1/sessions?p=1", 2, 60)
    c.invalidate_prefix("http://x/v1/items")
    assert c.get("http://x/v1/items?p=1") is None
    assert c.get("http://x/v1/sessions?p=1") == 2
