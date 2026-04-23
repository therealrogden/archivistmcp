# Wire-Format Audit Probes — 2026-04-23

Live API calls used to verify MCP implementation against `ArchivistAPIReference.md.txt`.

## Variables

```bash
BASE=https://api.myarchivist.ai
CID=cmg3twddd0021jl0gesepxuit
SID=bec1qufan6rj60n1k1ilvdjb   # session "No Choice But the Blade"
```

API key from `$ARCHIVIST_API_KEY` env var.

## 1. Quests — field names + pagination param

```bash
# size=2: confirms server accepts "size", returns 2 rows
curl -s -H "x-api-key: $ARCHIVIST_API_KEY" "$BASE/v1/quests?campaign_id=$CID&page=1&size=2"

# page_size=2: server ignores it, returns default 20 rows
curl -s -H "x-api-key: $ARCHIVIST_API_KEY" "$BASE/v1/quests?campaign_id=$CID&page=1&page_size=2"
```

**Result:** Live rows use `quest_name` (not `name`). Numeric `objective_count` /
`completed_objective_count` on list rows — no `objectives[]` array. `page_size` is silently
ignored; server only recognizes `size`.

## 2. Beats — field names + game_session_id filter

```bash
curl -s -H "x-api-key: $ARCHIVIST_API_KEY" "$BASE/v1/beats?campaign_id=$CID&game_session_id=$SID&size=2"
```

**Result:** Live rows use `label` and `index` (not `title` / `sequence`). `game_session_id`
filter is honored by the server (not documented in the reference). Rows also carry
`game_session_ids` (array) alongside the scalar `game_session_id`.

## 3. Moments — field names

```bash
curl -s -H "x-api-key: $ARCHIVIST_API_KEY" "$BASE/v1/moments?campaign_id=$CID&session_id=$SID&size=2"
```

**Result:** Live rows use `label` and `index`. No `timestamp`, no `content`, no `created_at`
on list rows. MCP field `timestamp` is a phantom.

## 4. Campaign links — from_type casing

```bash
# Title Case — returns results
curl -s -H "x-api-key: $ARCHIVIST_API_KEY" "$BASE/v1/campaigns/$CID/links?from_type=Character&size=2"

# lowercase — returns zero results
curl -s -H "x-api-key: $ARCHIVIST_API_KEY" "$BASE/v1/campaigns/$CID/links?from_type=character&size=2"
```

**Result:** Server requires Title Case (`Character`, `Location`, etc.). Lowercase returns
`{"total": 0}`. CLAUDE.md "gotcha" bullet and `tests/fixtures/campaign/links.json` are wrong.

## 5. Characters — field names

```bash
curl -s -H "x-api-key: $ARCHIVIST_API_KEY" "$BASE/v1/characters?campaign_id=$CID&size=2"
```

**Result:** Live rows use `character_name` only — no `name` field. `character_display_name()`
falls through to `character_name` correctly; fix is functional.

## Summary of confirmed findings

| Check | MCP reads | Wire sends | Status |
|---|---|---|---|
| Quest name | `name` | `quest_name` | **Bug** |
| Quest counts | `objectives[]` (array) | `objective_count` / `completed_objective_count` (int) | **Bug** |
| Beat label | `title` | `label` | **Bug** |
| Beat order | `sequence` | `index` | **Bug** |
| Moment label | *(missing)* | `label` | **Bug** |
| Moment time | `timestamp` | *(field absent on list rows)* | **Bug** |
| Pagination param | `page_size` | `size` | **Bug** |
| Links from_type | `"character"` (lowercase) | `"Character"` (Title Case required) | **Bug** |
| Character name | `character_display_name()` tries `name` then `character_name` | `character_name` only | **Works** (minor ordering redundancy) |

## Re-run — implementation gate (2026-04-23)

All list probes from sections 1–5 re-run with live `$ARCHIVIST_API_KEY`; behavior matches the 2026-04-23 findings above (quest `quest_name` + flat counts, beat `label`/`index` + `game_session_ids`, moment `label`/`index` without `content`/`timestamp` on list rows, links Title Case only, `page_size` vs `size` for list pagination).

`GET /v1/search?...` returned `404` for the probe URLs used here (lexical search path may be unavailable in this environment); **wikilink** code leaves `page_size` as-is until a live `200` proves `size` is required.

## Detail endpoint snapshots (Bugs 1–6) — 2026-04-23

| Entity | ID | Keys vs list |
|--------|-----|----------------|
| Quest | `9063c32a-2ede-4d61-8dd1-01290e1f5dda` | `quest_name` (same as list). Detail has `objectives[]`; list rows use `objective_count` / `completed_objective_count` only. |
| Beat | `cml1mj2qr00000tb3wu01qdyu` | `label` and `index` (no `title` / `sequence`). |
| Moment | `bvywxaavdw264q0gztmx1031` | `label` and `index` (same as list). Detail includes `content` and `created_at`; list rows have neither `content` nor `timestamp`. |
