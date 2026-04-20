"""Pydantic boundary types for MCP tools (size caps, UUID paths, Item.type, mechanics).

Canonical rules follow DESIGN.md and step-13 contract probes.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Annotated, Any, Literal, TypeAlias
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer
from pydantic_core import PydanticCustomError

# --- sizes (DESIGN.md) ---
_CONTENT_MAX = 50 * 1024
_SHORT_TEXT_MAX = 1024
_TAG_MAX_LEN = 64
_TAG_MAX_COUNT = 32
_MECHANICS_JSON_MAX = 16 * 1024

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def canonical_json(value: Any) -> str:
    """Deterministic JSON for hashing and mechanics size limits."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def mechanics_signature(mechanics: dict[str, Any] | None) -> str | None:
    """SHA-256 of canonical JSON mechanics, or None when mechanics is absent."""
    if mechanics is None:
        return None
    payload = canonical_json(mechanics).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_uuid_string(v: str) -> str:
    if not _UUID_RE.match(v):
        raise PydanticCustomError("uuid_string", "Value is not a canonical UUID string")
    # normalize to lowercase hyphenated form
    return str(UUID(v))


def _validate_content(v: str) -> str:
    if len(v) > _CONTENT_MAX:
        raise PydanticCustomError("string_too_long", "content exceeds maximum length")
    return v


def _validate_short_text(v: str) -> str:
    if len(v) > _SHORT_TEXT_MAX:
        raise PydanticCustomError("string_too_long", "text exceeds maximum length")
    return v


def _validate_nonempty_short_text(v: str) -> str:
    """Search / ask query: non-whitespace, max 1 KB (DESIGN short-text cap)."""
    if not isinstance(v, str):
        raise PydanticCustomError("type_error", "expected string")
    if not v.strip():
        raise PydanticCustomError("empty_str", "Must not be empty or whitespace-only")
    if len(v) > _SHORT_TEXT_MAX:
        raise PydanticCustomError("string_too_long", "text exceeds maximum length")
    return v


def _validate_optional_asker_id(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if len(s) > _SHORT_TEXT_MAX:
        raise PydanticCustomError("string_too_long", "asker_id exceeds maximum length")
    return s


def _validate_tags(v: list[str]) -> list[str]:
    if len(v) > _TAG_MAX_COUNT:
        raise PydanticCustomError("too_many_tags", "Too many tags (max 32)")
    for t in v:
        if len(t) > _TAG_MAX_LEN:
            raise PydanticCustomError("tag_too_long", "Tag exceeds maximum length")
    return v


def _validate_mechanics_dict(v: Any) -> dict[str, Any] | None:
    """Archivist accepts scalars; we reject non-objects at our boundary."""
    if v is None:
        return None
    if isinstance(v, dict):
        encoded = canonical_json(v).encode("utf-8")
        if len(encoded) > _MECHANICS_JSON_MAX:
            raise PydanticCustomError(
                "mechanics_too_large",
                "mechanics canonical JSON exceeds maximum size",
            )
        return v
    raise PydanticCustomError(
        "mechanics_type",
        "mechanics must be a JSON object or null",
    )


class ItemType(str, Enum):
    """Canonical wire values (lowercase, space for multi-word)."""

    WEAPON = "weapon"
    ARMOR = "armor"
    SHIELD = "shield"
    TOOL = "tool"
    POTION = "potion"
    SCROLL = "scroll"
    CONSUMABLE = "consumable"
    ARTIFACT = "artifact"
    WONDROUS_ITEM = "wondrous item"
    DEVICE = "device"


def parse_item_type(value: str | ItemType) -> ItemType:
    """Accept upstream variants; normalize separators to spaces before lookup."""
    if isinstance(value, ItemType):
        return value
    s = str(value).strip().lower().replace("_", " ").replace("-", " ")
    try:
        return ItemType(s)
    except ValueError as exc:
        raise PydanticCustomError("item_type", f"Unknown Item.type value: {value!r}") from exc


def _serialize_item_type(v: ItemType) -> str:
    return v.value


# Annotated aliases for tool signatures (MCP schema picks up Field descriptions)
ContentStr = Annotated[
    str,
    Field(description="Plain text or markdown body; max 50 KB."),
    AfterValidator(_validate_content),
]

ShortNameStr = Annotated[
    str,
    Field(description="Short name field; max 1 KB."),
    AfterValidator(_validate_short_text),
]

ShortTitleStr = Annotated[
    str,
    Field(description="Title field; max 1 KB."),
    AfterValidator(_validate_short_text),
]

AliasStr = Annotated[
    str,
    Field(description="Link alias; max 1 KB."),
    AfterValidator(_validate_short_text),
]

TagsList = Annotated[
    list[str],
    Field(description="Up to 32 tags, each max 64 characters."),
    AfterValidator(_validate_tags),
]

UuidPathStr = Annotated[
    str,
    Field(description="UUID string for Archivist path parameters."),
    AfterValidator(_validate_uuid_string),
]

MechanicsDict = Annotated[
    dict[str, Any] | None,
    Field(
        default=None,
        description="Structured mechanics JSON object, or null. Scalars are rejected.",
    ),
    AfterValidator(_validate_mechanics_dict),
]

ItemTypeField = Annotated[
    ItemType,
    Field(description="Item category; canonical serialized form uses spaces for multi-word types."),
    BeforeValidator(parse_item_type),
    PlainSerializer(_serialize_item_type, return_type=str, when_used="json"),
]

ProjectionKind: TypeAlias = Literal[
    "campaign_link",
    "session",
    "quest",
    "character",
    "item",
    "faction",
    "location",
    "beat",
    "moment",
    "journal",
    "journal_folder",
]

# Kinds returned by GET /v1/search (DESIGN.md search_entities); maps 1:1 to ProjectionKind.
EntityKind: TypeAlias = Literal["character", "item", "faction", "location", "quest", "journal"]


class SearchFilters(BaseModel):
    """Typed filter bag for lexical search; unknown keys are rejected (``extra='forbid'``).

    Values are forwarded as query parameters to ``GET /v1/search`` when set.
    """

    model_config = ConfigDict(extra="forbid")

    is_player: bool | None = Field(default=None, description="Filter characters where type is PC.")
    has_summary: bool | None = Field(
        default=None,
        description="Filter sessions with a non-empty summary (searchable session rows only).",
    )
    has_mechanics: bool | None = Field(
        default=None, description="Filter items that include a non-empty mechanics object."
    )
    completion_pct_gte: int | None = Field(
        default=None, ge=0, le=100, description="Minimum quest objective completion percent."
    )
    status: str | None = Field(
        default=None,
        description="Filter by status (e.g. quest status); max 1 KB.",
        max_length=_SHORT_TEXT_MAX,
    )


NonEmptySearchStr = Annotated[
    str,
    Field(description="Non-empty search string; max 1 KB."),
    AfterValidator(_validate_nonempty_short_text),
]

AskerIdStr = Annotated[
    str | None,
    Field(
        default=None,
        description="Optional Archivist user id to scope journal access for /v1/ask.",
    ),
    AfterValidator(_validate_optional_asker_id),
]

__all__ = [
    "AliasStr",
    "AskerIdStr",
    "ContentStr",
    "EntityKind",
    "ItemType",
    "ItemTypeField",
    "MechanicsDict",
    "NonEmptySearchStr",
    "ProjectionKind",
    "SearchFilters",
    "ShortNameStr",
    "ShortTitleStr",
    "TagsList",
    "UuidPathStr",
    "canonical_json",
    "mechanics_signature",
    "parse_item_type",
]
