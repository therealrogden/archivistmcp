"""Slim-list projections for MCP resources (DESIGN.md Resources section)."""

from __future__ import annotations

import copy
from typing import Any

from .validation import ProjectionKind

CONTENT_EXCERPT_MAX = 120


def _has_summary_text(summary: Any) -> bool:
    if summary is None:
        return False
    if not isinstance(summary, str):
        return False
    return bool(summary.strip())


def has_summary_session(entity: dict[str, Any]) -> bool:
    """True when ``summary`` is present and non-whitespace (char-based strip)."""
    return _has_summary_text(entity.get("summary"))


def summary_length_session(entity: dict[str, Any]) -> int:
    """Character length of ``summary`` when ``has_summary`` is true; else 0."""
    if not has_summary_session(entity):
        return 0
    s = entity.get("summary")
    return len(s) if isinstance(s, str) else 0


def content_excerpt(text: Any, max_len: int = CONTENT_EXCERPT_MAX) -> str:
    """First ``max_len`` characters of ``content`` (Python string slice = UTF-16 code units in CPython for BMP; DESIGN uses char count via str slice)."""
    if not isinstance(text, str) or not text:
        return ""
    return text[:max_len]


def is_player_character(entity: dict[str, Any]) -> bool:
    """DESIGN: ``type == \"PC\"`` (case-insensitive)."""
    t = entity.get("type")
    if not isinstance(t, str):
        return False
    return t.strip().upper() == "PC"


def has_speaker_character(entity: dict[str, Any]) -> bool:
    """DESIGN: derived from ``player is not None``."""
    return entity.get("player") is not None


def character_display_name(entity: dict[str, Any]) -> str | None:
    """Return the list/detail display name for a character.

    The Archivist API documents ``character_name``; some payloads also include
    a normalized ``name``. Prefer ``name`` when both are present and non-empty.
    """
    for key in ("name", "character_name"):
        v = entity.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def has_mechanics_item(entity: dict[str, Any]) -> bool:
    """Chunk 2: non-empty ``mechanics`` dict on the entity (no extra HTTP)."""
    m = entity.get("mechanics")
    return isinstance(m, dict) and len(m) > 0


def _quest_objectives(entity: dict[str, Any]) -> list[dict[str, Any]]:
    raw = entity.get("objectives")
    if not isinstance(raw, list):
        return []
    return [o for o in raw if isinstance(o, dict)]


def objective_count_quest(entity: dict[str, Any]) -> int:
    return len(_quest_objectives(entity))


def _objective_completed(obj: dict[str, Any]) -> bool:
    if obj.get("completed") is True or obj.get("is_complete") is True:
        return True
    st = obj.get("status")
    if isinstance(st, str) and st.lower() in ("completed", "complete", "done"):
        return True
    return False


def completion_pct_quest(entity: dict[str, Any]) -> int:
    """Percent of objectives complete; 0 when there are zero objectives (no divide-by-zero)."""
    objs = _quest_objectives(entity)
    n = len(objs)
    if n == 0:
        return 0
    done = sum(1 for o in objs if _objective_completed(o))
    return int(done * 100 // n)


def _int_or_zero(v: Any) -> int:
    return v if isinstance(v, int) and v >= 0 else 0


def objective_count_quest_row(entity: dict[str, Any]) -> int:
    if isinstance(entity.get("objectives"), list):
        return objective_count_quest(entity)
    return _int_or_zero(entity.get("objective_count"))


def completion_pct_quest_row(entity: dict[str, Any]) -> int:
    if isinstance(entity.get("objectives"), list):
        return completion_pct_quest(entity)
    total = _int_or_zero(entity.get("objective_count"))
    done = _int_or_zero(entity.get("completed_objective_count"))
    if total == 0:
        return 0
    return int(done * 100 // total)


def is_root_parent_id(entity: dict[str, Any], key: str = "parent_id") -> bool:
    """True when ``parent_id`` (or ``key``) is missing or null."""
    return entity.get(key) is None


def is_root_beat(entity: dict[str, Any]) -> bool:
    """Root beat: no ``parent_beat_id`` or ``parent_id``."""
    if entity.get("parent_beat_id") is not None:
        return False
    if entity.get("parent_id") is not None:
        return False
    return True


def beat_session_id(entity: dict[str, Any]) -> str | None:
    """``session_id`` or ``game_session_id`` from API variants."""
    sid = entity.get("session_id")
    if isinstance(sid, str) and sid:
        return sid
    gid = entity.get("game_session_id")
    if isinstance(gid, str) and gid:
        return gid
    return None


def project_slim(entity: dict[str, Any], kind: ProjectionKind) -> dict[str, Any]:
    """Return the slim dict for one list row; keys match DESIGN.md per-entity rows (+ ``id`` / name/title base where applicable)."""
    if kind == "campaign_link":
        return {
            "from_id": entity["from_id"],
            "from_type": entity["from_type"],
            "to_id": entity["to_id"],
            "to_type": entity["to_type"],
            "alias": entity.get("alias"),
        }
    if kind == "session":
        return {
            "id": entity["id"],
            "title": entity.get("title"),
            "session_date": entity.get("session_date"),
            "has_summary": has_summary_session(entity),
            "summary_length": summary_length_session(entity),
        }
    if kind == "quest":
        tags = entity.get("tags")
        if not isinstance(tags, list):
            tags = []
        return {
            "id": entity["id"],
            "name": entity.get("quest_name"),
            "status": entity.get("status"),
            "objective_count": objective_count_quest_row(entity),
            "completion_pct": completion_pct_quest_row(entity),
            "updated_at": entity.get("updated_at"),
            "tags": tags,
        }
    if kind == "character":
        return {
            "id": entity["id"],
            "name": character_display_name(entity),
            "type": entity.get("type"),
            "is_player": is_player_character(entity),
            "has_speaker": has_speaker_character(entity),
        }
    if kind == "item":
        return {
            "id": entity["id"],
            "name": entity.get("name"),
            "type": entity.get("type"),
            "has_mechanics": has_mechanics_item(entity),
        }
    if kind == "faction":
        return {
            "id": entity["id"],
            "name": entity.get("name"),
            "alignment": entity.get("alignment"),
        }
    if kind == "location":
        return {
            "id": entity["id"],
            "name": entity.get("name"),
            "is_root": is_root_parent_id(entity, "parent_id"),
        }
    if kind == "beat":
        return {
            "id": entity["id"],
            "title": entity.get("label"),
            "session_id": beat_session_id(entity),
            "sequence": entity.get("index"),
            "is_root": is_root_beat(entity),
        }
    if kind == "moment":
        return {
            "id": entity["id"],
            "session_id": entity.get("session_id"),
            "label": entity.get("label"),
            "index": entity.get("index"),
            "content_excerpt": content_excerpt(entity.get("content")),
        }
    if kind == "journal":
        tags = entity.get("tags")
        if not isinstance(tags, list):
            tags = []
        return {
            "id": entity["id"],
            "title": entity.get("title"),
            "folder_id": entity.get("folder_id"),
            "updated_at": entity.get("updated_at"),
            "tags": tags,
        }
    if kind == "journal_folder":
        return {
            "id": entity["id"],
            "name": entity.get("name"),
            "parent_id": entity.get("parent_id"),
            "is_root": is_root_parent_id(entity, "parent_id"),
        }
    raise TypeError(f"unknown projection kind: {kind!r}")


def project_list_payload(payload: Any, kind: ProjectionKind) -> Any:
    """If ``payload`` is a dict with a ``data`` list, replace ``data`` with slim rows; copy other top-level keys (e.g. ``next_cursor``) unchanged."""
    if not isinstance(payload, dict):
        return payload
    raw_data = payload.get("data")
    if not isinstance(raw_data, list):
        return payload
    out = copy.copy(payload)
    out["data"] = [project_slim(item, kind) if isinstance(item, dict) else item for item in raw_data]
    return out


def clamp_page_size(page_size: int, cap: int = 50) -> int:
    return min(page_size, cap)


def pagination_params(*, page: int, page_size: int, cursor: str | None) -> dict[str, Any]:
    """Query params for list GETs; omits ``cursor`` when None."""
    ps = clamp_page_size(page_size)
    p: dict[str, Any] = {"page": page, "page_size": ps}
    if cursor is not None:
        p["cursor"] = cursor
    return p
