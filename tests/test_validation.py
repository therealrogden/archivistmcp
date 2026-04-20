"""Boundary validation types (DESIGN.md step 5 + step 13 locks)."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from archivist_mcp.validation import (
    AliasStr,
    ContentStr,
    ItemType,
    ItemTypeField,
    MechanicsDict,
    ShortNameStr,
    ShortTitleStr,
    TagsList,
    UuidPathStr,
    canonical_json,
    mechanics_signature,
    parse_item_type,
)


def test_content_cap_rejects() -> None:
    adapter = TypeAdapter(ContentStr)
    with pytest.raises(ValidationError):
        adapter.validate_python("x" * (50 * 1024 + 1))


def test_name_title_alias_caps_reject() -> None:
    for ann in (ShortNameStr, ShortTitleStr, AliasStr):
        adapter = TypeAdapter(ann)
        with pytest.raises(ValidationError):
            adapter.validate_python("y" * (1024 + 1))


def test_tags_count_and_length_reject() -> None:
    adapter = TypeAdapter(TagsList)
    with pytest.raises(ValidationError):
        adapter.validate_python(["a"] * 33)
    with pytest.raises(ValidationError):
        adapter.validate_python(["b" * 65])


def test_uuid_accepts_and_rejects() -> None:
    adapter = TypeAdapter(UuidPathStr)
    assert adapter.validate_python("00000000-0000-0000-0000-000000000001") == (
        "00000000-0000-0000-0000-000000000001"
    )
    with pytest.raises(ValidationError):
        adapter.validate_python("not-a-uuid")


def test_item_type_roundtrip_variants() -> None:
    assert parse_item_type("wondrous_item") is ItemType.WONDROUS_ITEM
    assert parse_item_type("wondrous-item") is ItemType.WONDROUS_ITEM
    assert parse_item_type("Wondrous Item") is ItemType.WONDROUS_ITEM

    class Row(BaseModel):
        model_config = ConfigDict(use_enum_values=False)
        t: ItemTypeField

    dumped = Row(t=ItemType.WONDROUS_ITEM).model_dump(mode="json")
    assert dumped["t"] == "wondrous item"
    dumped2 = Row(t="wondrous_item").model_dump(mode="json")
    assert dumped2["t"] == "wondrous item"


def test_mechanics_rejects_non_object() -> None:
    adapter = TypeAdapter(MechanicsDict)
    assert adapter.validate_python(None) is None
    assert adapter.validate_python({"a": 1}) == {"a": 1}
    for bad in ("scalar", 1, [1, 2]):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_mechanics_canonical_json_size_cap() -> None:
    adapter = TypeAdapter(MechanicsDict)
    # Build dict whose canonical JSON exceeds 16 KiB but small in Python object "size"
    inner = "x" * (17 * 1024)
    with pytest.raises(ValidationError):
        adapter.validate_python({"k": inner})


def test_mechanics_signature_deterministic_and_none() -> None:
    assert mechanics_signature(None) is None
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert mechanics_signature(a) == mechanics_signature(b)
    assert mechanics_signature({"x": 1}) != mechanics_signature({"x": 2})


def test_scrubbed_output_has_no_secrets() -> None:
    """Synthetic scrubbed output must not contain obvious secrets or live ids."""
    from scripts.record_fixtures import scrub_value

    sample = {
        "headers": {"x-api-key": "supersecret"},
        "campaign_id": "cmg3twddd0021jl0gesepxuit",
        "description": "User wrote a long private note here.",
    }
    scrubbed = scrub_value(sample, live_campaign_id="cmg3twddd0021jl0gesepxuit")
    dumped = json.dumps(scrubbed)
    assert "supersecret" not in dumped.lower()
    assert scrubbed["headers"]["x-api-key"] == "<redacted>"
    assert "cmg3twddd0021jl0gesepxuit" not in dumped
