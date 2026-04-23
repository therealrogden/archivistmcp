"""Unit tests for archivist_mcp.projections (slim shapes + derivations)."""

from __future__ import annotations

import pytest

from archivist_mcp.projections import (
    CONTENT_EXCERPT_MAX,
    character_display_name,
    completion_pct_quest,
    content_excerpt,
    has_mechanics_item,
    has_speaker_character,
    has_summary_session,
    is_player_character,
    is_root_beat,
    is_root_parent_id,
    objective_count_quest,
    project_list_payload,
    project_slim,
    summary_length_session,
)
from archivist_mcp.validation import ProjectionKind


def _keys(kind: ProjectionKind) -> set[str]:
    e: dict = {}
    if kind == "campaign_link":
        e = {
            "from_id": "a",
            "from_type": "character",
            "to_id": "b",
            "to_type": "faction",
            "alias": "x",
        }
    elif kind == "session":
        e = {"id": "1", "title": "T", "session_date": "2026-01-01T00:00:00Z"}
    elif kind == "quest":
        e = {
            "id": "1",
            "quest_name": "Q",
            "status": "active",
            "objective_count": 0,
            "completed_objective_count": 0,
            "updated_at": None,
            "tags": [],
        }
    elif kind == "character":
        e = {"id": "1", "name": "C", "type": "NPC"}
    elif kind == "item":
        e = {"id": "1", "name": "I", "type": "weapon"}
    elif kind == "faction":
        e = {"id": "1", "name": "F"}
    elif kind == "location":
        e = {"id": "1", "name": "L", "parent_id": None}
    elif kind == "beat":
        e = {"id": "1", "title": "B", "sequence": 1, "game_session_id": "s"}
    elif kind == "moment":
        e = {"id": "1", "session_id": "s", "timestamp": "t", "content": ""}
    elif kind == "journal":
        e = {"id": "1", "title": "J", "folder_id": "f", "updated_at": None, "tags": []}
    elif kind == "journal_folder":
        e = {"id": "1", "name": "jf", "parent_id": None}
    return set(project_slim(e, kind).keys())


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("campaign_link", {"from_id", "from_type", "to_id", "to_type", "alias"}),
        ("session", {"id", "title", "session_date", "has_summary", "summary_length"}),
        (
            "quest",
            {
                "id",
                "name",
                "status",
                "objective_count",
                "completion_pct",
                "updated_at",
                "tags",
            },
        ),
        ("character", {"id", "name", "type", "is_player", "has_speaker"}),
        ("item", {"id", "name", "type", "has_mechanics"}),
        ("faction", {"id", "name", "alignment"}),
        ("location", {"id", "name", "is_root"}),
        ("beat", {"id", "title", "session_id", "sequence", "is_root"}),
        ("moment", {"id", "session_id", "timestamp", "content_excerpt"}),
        ("journal", {"id", "title", "folder_id", "updated_at", "tags"}),
        ("journal_folder", {"id", "name", "parent_id", "is_root"}),
    ],
)
def test_project_slim_key_set_exact(kind: ProjectionKind, expected: set[str]) -> None:
    assert _keys(kind) == expected


def test_session_has_summary_and_summary_length() -> None:
    base = {"id": "1", "title": "T", "session_date": "d"}
    assert has_summary_session({**base}) is False
    assert summary_length_session({**base}) == 0
    assert has_summary_session({**base, "summary": ""}) is False
    assert has_summary_session({**base, "summary": "   \n"}) is False
    assert has_summary_session({**base, "summary": " recap "}) is True
    assert summary_length_session({**base, "summary": " recap "}) == len(" recap ")


def test_character_display_name_accepts_api_wire() -> None:
    assert character_display_name({"id": "1", "character_name": "  Staring Grimlock  "}) == "Staring Grimlock"
    assert character_display_name({"id": "1", "name": "Short", "character_name": "Ignored"}) == "Short"
    assert character_display_name({"id": "1"}) is None
    assert character_display_name({"id": "1", "name": "", "character_name": "Fallback"}) == "Fallback"


def test_project_slim_character_uses_character_name() -> None:
    slim = project_slim(
        {"id": "c1", "character_name": "Staring Grimlock", "type": "NPC"},
        "character",
    )
    assert slim["name"] == "Staring Grimlock"


def test_character_is_player_and_has_speaker() -> None:
    npc = {"id": "1", "name": "N", "type": "NPC"}
    assert is_player_character(npc) is False
    pc = {"id": "2", "name": "P", "type": "PC"}
    assert is_player_character(pc) is True
    assert is_player_character({**pc, "type": "pc"}) is True
    assert has_speaker_character({**pc, "player": None}) is False
    assert has_speaker_character({**pc, "player": {"id": "x"}}) is True


def test_quest_completion_pct_and_zero_objectives() -> None:
    q0 = {"id": "1", "name": "Q", "status": "active", "objectives": []}
    assert objective_count_quest(q0) == 0
    assert completion_pct_quest(q0) == 0
    q_half = {
        "id": "1",
        "name": "Q",
        "status": "active",
        "objectives": [{"completed": True}, {"completed": False}],
    }
    assert completion_pct_quest(q_half) == 50
    q_all = {
        "id": "1",
        "name": "Q",
        "status": "active",
        "objectives": [{"completed": True}, {"completed": True}],
    }
    assert completion_pct_quest(q_all) == 100


def test_project_slim_quest_list_row_uses_quest_name_and_flat_counts() -> None:
    row = {
        "id": "1",
        "quest_name": "Q",
        "status": "active",
        "objective_count": 2,
        "completed_objective_count": 1,
        "updated_at": None,
        "tags": [],
    }
    slim = project_slim(row, "quest")
    assert slim["name"] == "Q"
    assert slim["objective_count"] == 2
    assert slim["completion_pct"] == 50


def test_project_slim_quest_detail_uses_objectives_array() -> None:
    detail = {
        "id": "1",
        "quest_name": "Q",
        "status": "active",
        "objectives": [{"completed": True}, {"completed": False}],
        "updated_at": None,
        "tags": [],
    }
    slim = project_slim(detail, "quest")
    assert slim["name"] == "Q"
    assert slim["objective_count"] == 2
    assert slim["completion_pct"] == 50


def test_location_and_journal_folder_is_root() -> None:
    assert is_root_parent_id({"parent_id": None}) is True
    assert is_root_parent_id({"parent_id": "p"}) is False


def test_beat_is_root() -> None:
    assert is_root_beat({}) is True
    assert is_root_beat({"parent_beat_id": None, "parent_id": None}) is True
    assert is_root_beat({"parent_beat_id": "x"}) is False
    assert is_root_beat({"parent_id": "y"}) is False


def test_content_excerpt_boundaries() -> None:
    s119 = "a" * 119
    assert len(content_excerpt(s119)) == 119
    s120 = "a" * 120
    assert len(content_excerpt(s120)) == 120
    s121 = "a" * 121
    assert len(content_excerpt(s121)) == CONTENT_EXCERPT_MAX
    assert content_excerpt(s121) == "a" * 120


def test_item_has_mechanics() -> None:
    assert has_mechanics_item({"mechanics": None}) is False
    assert has_mechanics_item({}) is False
    assert has_mechanics_item({"mechanics": {}}) is False
    assert has_mechanics_item({"mechanics": {"hp": 1}}) is True


def test_project_list_payload_preserves_next_cursor() -> None:
    payload = {
        "data": [{"id": "1", "title": "T", "session_date": "d"}],
        "next_cursor": "keep-me",
        "page": 1,
    }
    out = project_list_payload(payload, "session")
    assert out["next_cursor"] == "keep-me"
    assert set(out["data"][0].keys()) == {
        "id",
        "title",
        "session_date",
        "has_summary",
        "summary_length",
    }
