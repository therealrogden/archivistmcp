"""In-process TTL cache and write→invalidation routing for HTTP cache keys."""

from __future__ import annotations

import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

LIST_TTL_SECONDS = 60
DETAIL_TTL_SECONDS = 300

# UUID v4 (canonical) segments in paths, normalized for write-route lookup.
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# Keys: "METHOD /v1/.../{id}/..." with UUIDs replaced by "{id}".
# Values: path prefixes (must start with "/"); combined with base_url for invalidation.
# Supersets used where DESIGN defers conditional invalidation to tools (e.g. register_item).
URI_INVALIDATION_MAP: dict[str, tuple[str, ...]] = {
    "PATCH /v1/campaigns/{id}": ("/v1/campaigns",),
    "POST /v1/campaigns/{id}/links": ("/v1/campaigns",),
    "PATCH /v1/campaigns/{id}/links/{id}": ("/v1/campaigns",),
    "DELETE /v1/campaigns/{id}/links/{id}": ("/v1/campaigns",),
    "POST /v1/sessions": ("/v1/sessions", "/v1/beats", "/v1/moments"),
    "PATCH /v1/sessions/{id}": ("/v1/sessions", "/v1/beats", "/v1/moments"),
    "DELETE /v1/sessions/{id}": ("/v1/sessions", "/v1/beats", "/v1/moments"),
    "POST /v1/beats": ("/v1/beats", "/v1/sessions"),
    "PATCH /v1/beats/{id}": ("/v1/beats", "/v1/sessions"),
    "DELETE /v1/beats/{id}": ("/v1/beats", "/v1/sessions"),
    "POST /v1/moments": ("/v1/moments", "/v1/sessions"),
    "PATCH /v1/moments/{id}": ("/v1/moments", "/v1/sessions"),
    "DELETE /v1/moments/{id}": ("/v1/moments", "/v1/sessions"),
    "POST /v1/quests": ("/v1/quests",),
    "PATCH /v1/quests/{id}": ("/v1/quests",),
    "DELETE /v1/quests/{id}": ("/v1/quests",),
    "POST /v1/characters": ("/v1/characters",),
    "PATCH /v1/characters/{id}": ("/v1/characters",),
    "DELETE /v1/characters/{id}": ("/v1/characters",),
    "POST /v1/items": ("/v1/items", "/v1/journals", "/v1/journal-folders"),
    "PATCH /v1/items/{id}": ("/v1/items", "/v1/journals", "/v1/journal-folders"),
    "DELETE /v1/items/{id}": ("/v1/items", "/v1/journals", "/v1/journal-folders"),
    "POST /v1/factions": ("/v1/factions",),
    "PATCH /v1/factions/{id}": ("/v1/factions",),
    "DELETE /v1/factions/{id}": ("/v1/factions",),
    "POST /v1/locations": ("/v1/locations",),
    "PATCH /v1/locations/{id}": ("/v1/locations",),
    "DELETE /v1/locations/{id}": ("/v1/locations",),
    "POST /v1/journals": ("/v1/journals", "/v1/journal-folders"),
    "PATCH /v1/journals/{id}": ("/v1/journals", "/v1/journal-folders"),
    "DELETE /v1/journals/{id}": ("/v1/journals", "/v1/journal-folders"),
    "POST /v1/journal-folders": ("/v1/journal-folders",),
    "PATCH /v1/journal-folders/{id}": ("/v1/journal-folders",),
    "DELETE /v1/journal-folders/{id}": ("/v1/journal-folders",),
}


class Cache:
    """Simple async-safe TTL dict keyed by full request URL strings."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._generation = 0

    def generation(self) -> int:
        """Monotonic counter bumped on invalidation; used to skip stale cache fills after races."""
        with self._lock:
            return self._generation

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() >= expires_at:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        with self._lock:
            self._data[key] = (value, time.time() + ttl_seconds)

    def ttl_remaining_seconds(self, key: str) -> float | None:
        """Seconds until expiry, or ``None`` if missing or already expired."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            _, expires_at = entry
            rem = expires_at - time.time()
            if rem <= 0:
                del self._data[key]
                return None
            return rem

    def invalidate_prefix(self, url_prefix: str) -> None:
        """Drop entries whose key starts with ``url_prefix``."""
        with self._lock:
            self._generation += 1
            doomed = [k for k in self._data if k.startswith(url_prefix)]
            for k in doomed:
                del self._data[k]


def ttl_seconds_for_request_url(url: str) -> int | None:
    """Return TTL for a fully-qualified GET URL, or ``None`` if the response must not be cached."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path == "/health":
        return None
    if path.startswith("/v1/search"):
        return None
    if path == "/v1/journal-folders":
        return DETAIL_TTL_SECONDS
    if "/v1/campaigns/" in path and path.endswith("/links"):
        return LIST_TTL_SECONDS
    list_paths = frozenset(
        {
            "/v1/sessions",
            "/v1/beats",
            "/v1/moments",
            "/v1/quests",
            "/v1/characters",
            "/v1/items",
            "/v1/factions",
            "/v1/locations",
            "/v1/journals",
        }
    )
    if path in list_paths:
        return LIST_TTL_SECONDS
    return DETAIL_TTL_SECONDS


def write_route_key(method: str, path: str) -> str | None:
    """Map a concrete HTTP path to a :data:`URI_INVALIDATION_MAP` key, if any."""
    norm = _UUID_RE.sub("{id}", path)
    key = f"{method.upper()} {norm}"
    return key if key in URI_INVALIDATION_MAP else None


def invalidation_url_prefixes(base_url: str, method: str, path: str) -> tuple[str, ...]:
    """Full URL prefixes to pass to :meth:`Cache.invalidate_prefix` for a successful write."""
    key = write_route_key(method, path)
    if key is None:
        return ()
    base = base_url.rstrip("/")
    return tuple(base + p for p in URI_INVALIDATION_MAP[key])
