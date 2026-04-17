# Archivist MCP Server — Design Doc

## Goals

1. Use Claude (via MCP) to draft and rewrite **session summaries** with full context: beats, moments, cast analysis.
2. Use Claude to draft and rewrite **campaign summaries** and long-form campaign overviews.
3. Track **campaign-specific items** (homebrew, magical, story-significant) in a way that Archivist's RAG can retrieve both narrative *and* mechanical detail.

## Non-goals

- No bulk import of the full 5.5e SRD into the campaign. Claude already knows the rules; importing pollutes RAG.
- No re-implementation of Archivist features the web app already does well (auto-detection, transcript ingestion, audio upload).
- No multi-tenant hosting in v1. Local stdio for one user, one campaign at a time.
- No write tools that bypass review. Every write is preceded by a draft tool.

## Decisions (from intake)

| Topic | Choice |
|---|---|
| Stack | Python 3.11+ with FastMCP v2 (`pip install fastmcp`) |
| Transport | Local stdio for v1. Transport abstracted so HTTP/SSE is a config flip later. |
| Scope | Single campaign per server instance. `ARCHIVIST_CAMPAIGN_ID` env var. |
| Ask endpoint | Wrapped as a tool, exposed to Claude. |
| Statblock format | Plain markdown via `content` only. Do **not** send `content_rich` until we have a verified Lexical example from Archivist's own export. |
| Compendium tiers | None. Whether to create a mechanics journal is a single boolean: did the caller pass a `mechanics` payload? |
| Item categorization | Coarse: `Item.type` validated against Archivist's closed enum (Weapon, Armor, Shield, Tool, Potion, Scroll, Consumable, Artifact, Wondrous Item, Device). Fine: free-form `tags` on the mechanics journal. |
| Cast-analysis in summaries | Opt-in per call. Tool checks whether `cast-analysis` exists for the session before fetching (some sessions, e.g. play-by-post, won't have it). |
| Quest updates on session commit | Out of scope. Archivist already updates quests automatically when sessions are uploaded; we don't duplicate that. |
| Summary versioning | Archive prior summary to a `Summary History/` journal folder **only when overwriting an existing summary**. First-time commits are not archived. |

## Architecture

```
┌────────────────┐    stdio      ┌─────────────────────────┐    HTTPS     ┌──────────────────────┐
│ Claude Desktop │ ◄──────────► │ Archivist MCP Server    │ ◄─────────► │ api.myarchivist.ai   │
│ /  Claude Code │              │ (FastMCP, Python)       │              │  (x-api-key)         │
└────────────────┘              └─────────────────────────┘              └──────────────────────┘
                                  │
                                  ├── Resources (read-only views)
                                  ├── Tools (draft / commit / ask)
                                  └── Prompts (DM workflow templates)
```

Single process, single API key, single campaign. The server is a thin adapter: HTTP client + schema typing + a few composite operations that bundle multiple REST calls into one MCP call.

### Why FastMCP v2

- Decorator API maps cleanly to the three MCP primitives.
- Type hints become tool/resource schemas automatically.
- Async-native (matters for `/v1/ask` streaming).
- `FastMCP.from_openapi(...)` would let us auto-wrap the entire Archivist API if/when they publish a spec — for now we hand-write the surface we actually want.
- Transport is a runtime flag — same code runs over stdio, HTTP, or SSE.

### Why single-campaign

- No `campaign_id` parameter on any tool → Claude can't accidentally read or write to the wrong campaign.
- API key + campaign ID together form a single trust boundary.
- For users with multiple campaigns, run multiple server instances (different env, different MCP entry in Claude config). This is a one-line config duplication, not a code change.

## Data model usage

Mapping Archivist resources to MCP primitives, by intent rather than by REST symmetry.

### Resources (browseable, cacheable, read-only)

| URI | Backing endpoint(s) | Purpose |
|---|---|---|
| `archivist://campaign` | `GET /v1/campaigns/{id}` + `GET /v1/campaigns/{id}/stats` | Campaign card + counts |
| `archivist://sessions` | `GET /v1/sessions?campaign_id=…` | Session list, paginated |
| `archivist://session/{id}` | `GET /v1/sessions/{id}` + `GET /v1/beats?game_session_id={id}` + `GET /v1/moments?session_id={id}` + `GET /v1/sessions/{id}/cast-analysis` | **Composite**: everything needed to summarize one session |
| `archivist://quests` | `GET /v1/quests?campaign_id=…` | All quests with objectives |
| `archivist://characters` | `GET /v1/characters?campaign_id=…` | Cast list |
| `archivist://entities` | Items + Factions + Locations | Compendium overview |
| `archivist://item/{id}` | `GET /v1/items/{id}` + linked mechanics journal entry | Item with statblock |
| `archivist://journal/{id}` | `GET /v1/journals/{id}` | Returns `content` (plain text) only — token-efficient. We never read or write `content_rich` in v1. |
| `archivist://journal-folders` | `GET /v1/journal-folders?campaign_id=…` | Folder tree for placement |

**Key principle:** resources are read-cheap. The `session/{id}` resource especially: bundling four endpoints into one resource means Claude pays one round-trip to get everything it needs to summarize.

### Tools (writes and active operations)

Total surface: **10 tools**. Kept tight on purpose.

| Tool | Effect |
|---|---|
| `ask_archivist(question, asker_id?, gm_permissions?, stream=true)` | Wraps `POST /v1/ask`. Default `gm_permissions=false`, `asker_id=null`. |
| `draft_session_summary(session_id, style?, length?, include_cast_analysis=False)` | Reads the composite session resource, returns a draft summary. **Does not write.** When `include_cast_analysis=True`, fetches `/v1/sessions/{id}/cast-analysis` if it exists; silently skips it if the endpoint returns 404 (e.g., play-by-post sessions). |
| `commit_session_summary(session_id, summary, title?)` | `PATCH /v1/sessions/{id}`. If a prior non-empty summary exists, archives it to `Summary History/` first (see Versioning). Returns prior summary verbatim in the response. |
| `draft_campaign_summary(guidance?)` | Aggregates session summaries + quests + key entities, drafts a new campaign description or long-form overview. |
| `commit_campaign_summary(target, content)` | `target="description"` → `PATCH /v1/campaigns/{id}`. `target="overview"` → upserts the pinned `Campaign Overview` journal entry. Same archival rule as session summaries. |
| `upsert_journal_entry(folder_id, title, content, tags?)` | For long-form overviews and statblock journals. Idempotent on `(folder_id, title)`. Sends `content` (markdown) only; no `content_rich`. |
| `register_item(name, description, mechanics?, type?, image?, tags?)` | Creates the Item. If `mechanics` is provided, also creates a paired statblock journal entry in the mechanics folder with cross-wikilinks. No tier enum; the presence of `mechanics` *is* the decision. |
| `promote_item_to_homebrew(item_id, mechanics)` | Adds the mechanics journal to an existing Item (e.g., players enchant an existing weapon). Updates the Item description to add a wikilink to the new journal. |
| `link_entities(from_id, from_type, to_id, to_type, alias?)` | Wraps `POST /v1/campaigns/{id}/links`. |
| `search_entities(query, types?)` | Multi-type fuzzy search across characters/items/factions/locations. |

### Prompts (templates the user picks from)

| Prompt | Composes |
|---|---|
| `recap-last-session` | Reads latest session resource, calls `draft_session_summary` with style="recap-for-players", presents for review. |
| `state-of-the-campaign` | Calls `draft_campaign_summary` with guidance="overview suitable for new players joining". |
| `prep-next-session` | Reads quests + last session + open beats, drafts GM prep notes (does not write back). |
| `register-found-item` | Asks the user for narrative description, then asks "does this item have mechanics worth a statblock?" — if yes, prompts for the mechanics fields and calls `register_item` with them. |
| `summarize-faction-arc(faction_id)` | Pulls a faction + linked beats/moments/characters/quests, drafts an arc summary. |
| `character-arc(character_id)` | Same shape as faction arc, for a PC or NPC. Narrative-oriented, shareable. Uses for: retirement write-ups, recaps for late-joining players, "remind me what my character has been through." |
| `location-gazetteer(location_id)` | Pulls a location + linked NPCs/factions/items/events. For refresher before the party returns somewhere. |
| `npc-dossier(character_id)` | **Prep-oriented**, not narrative. Intended for GM's eyes before an imminent scene: motivations, what they know, alignments, last interaction, unresolved threads. Contrast with `character-arc` which is shareable. |
| `loose-ends` | Scans active quests with no recent beats, raised-but-unresolved mysteries, NPCs not seen in N sessions, items found but never used. Drafts a dangling-threads report. |
| `player-brief(asker_id)` | Thin wrapper over `ask_archivist` with `asker_id` set and `gm_permissions=false`, pre-phrased as "what does my character currently know about …". Makes permission-scoped asking discoverable for players. |

## Workflows

### Session summary

```
1. User: "Draft a recap for last week's session"
2. Claude → resource archivist://sessions → finds latest by session_date
3. Claude → resource archivist://session/{id} → gets session + beats + moments + cast-analysis
4. Claude → tool draft_session_summary(session_id, style="recap")
   ↳ Server returns draft, includes prior summary verbatim for diff comparison
5. User reviews / asks for revisions in chat
6. Claude → tool commit_session_summary(session_id, summary=<approved>)
   ↳ Server PATCHes; returns confirmation + token count
```

Two-step (draft → commit) is mandatory. Never collapse into a single tool.

### Campaign summary

Same draft → review → commit shape. `draft_campaign_summary` aggregates:
- `campaign.description` (current)
- All `sessions[].summary` in chronological order
- All `quests[]` with status
- Top N characters/factions by link count

`commit_campaign_summary(target, content)` takes one of two targets:
- `target="description"` — short blurb, PATCHes `campaign.description`.
- `target="overview"` — long-form, upserts the pinned `Campaign Overview` journal entry.

The prompt asks which one, with a sensible default based on output length (short → description, long → overview).

### Versioning (commit_session_summary, commit_campaign_summary)

Before a commit overwrites an existing non-empty summary:
1. Resolve the `Summary History/` folder (auto-create on first use).
2. Upsert a journal entry titled e.g. `Session 12 — superseded 2026-04-15T19:30Z` containing the prior summary verbatim, tagged `["summary-history", "session"]` (or `"campaign"`).
3. Then PATCH the new summary.

First-time commits (no prior summary) skip the archive step. The intent is a paper trail of *edits*, not a duplicate of every summary ever written.

### Compendium (hybrid item tracking)

Two layers, but **only one decision**: did the caller pass a `mechanics` payload?

**Layer 1 — Item entity** (always created). Narrative description plus a `type` field. `Item.type` is a closed enum — the Archivist UI exposes exactly these values:

```
Weapon · Armor · Shield · Tool · Potion · Scroll ·
Consumable · Artifact · Wondrous Item · Device
```

The API docs show lowercase on the wire (`"type": "weapon"`), so we'll send lowercase; the `"Wondrous Item"` wire format (space vs. underscore vs. hyphen) needs to be confirmed with a real request before we finalize. `register_item` validates `type` against this enum client-side and rejects unknown values early with a clear error, rather than letting Archivist 422. If a mechanics journal was created, the description ends with `See mechanics: [[{Name} — Mechanics]]`.

**Layer 2 — Journal Entry** in the mechanics folder (created only when `mechanics` is provided). Full statblock as plain-text markdown sent via `content`. Tagged with caller-supplied `tags` (free-form, e.g. `["homebrew", "cursed", "attunement"]`) plus two automatic tags: `"mechanics"` and the Item's `type` value lowercased. The `type` tag mirror lets RAG filter by item category without re-joining against the Item entity. Finer categorization that `Item.type` doesn't capture — "cursed", "homebrew", "attunement-required" — lives here on free-form tags. Includes `Linked to [[{Name}]]` for the wikilink back.

**No tier enum.** Coarse categorization is `Item.type` (closed 10-value enum). Fine categorization is free-form journal `tags`. The branching logic in `register_item` is just `if mechanics is not None: create_journal(...)`.

**What we don't store:** generic SRD items players never engage with (torches, basic longswords, mundane gear). Claude/Ask-Archivist already knows the rules; storing them pollutes RAG without adding value. The user (or Claude on the user's behalf) decides item-by-item what's worth registering.

**Statblock journal template** (markdown sent via `content`):

```
# {Name}

*Type · Rarity · Attunement*

| Property | Value |
|---|---|
| Damage | 1d8 slashing + 1d6 radiant |
| Properties | versatile (1d10), finesse |
| Mastery | Sap |
| Weight | 3 lb |

## Lore
Linked to [[{Name}]] — see narrative entry for story context.

## Mechanical notes
{Free-form text about activated abilities, charges, etc.}
```

**Why not Lexical (`content_rich`):** the `content_rich` field is documented but its schema is typed as `unknown` in Archivist's published interfaces — no spec, no version, no node-type list. Hand-constructing Lexical JSON without a verified example risks malformed entries. We send plain-text markdown via `content` only. If the in-app rendering is poor enough to bother the user, we revisit using a real Archivist-exported `content_rich` example as the template basis.

**Why not formal Links:** `Link.EntityType` enum doesn't include `JournalEntry`. Wikilinks in content are the supported path, and Archivist syncs them on save.

## Configuration

`.env`:

```
ARCHIVIST_API_KEY=...
ARCHIVIST_CAMPAIGN_ID=...
ARCHIVIST_BASE_URL=https://api.myarchivist.ai     # override for staging
ARCHIVIST_MECHANICS_FOLDER=Items/Mechanics        # auto-created if missing
ARCHIVIST_OVERVIEW_FOLDER=Campaign Overview
ARCHIVIST_HISTORY_FOLDER=Summary History
LOG_LEVEL=INFO
```

Claude Desktop config (per campaign):

```json
{
  "mcpServers": {
    "archivist-mycampaign": {
      "command": "python",
      "args": ["-m", "archivist_mcp"],
      "env": {
        "ARCHIVIST_API_KEY": "...",
        "ARCHIVIST_CAMPAIGN_ID": "..."
      }
    }
  }
}
```

## Local-now, remote-later

Transport is a runtime concern, not a code concern. The same module exposes both:

```python
# src/archivist_mcp/__main__.py
import os
from .server import mcp

if os.getenv("MCP_TRANSPORT") == "http":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8765)
else:
    mcp.run()  # stdio
```

What needs to change for remote later (deferred, not built):

- Per-request API key extraction from headers (FastMCP middleware).
- Rate limiting (campaign-scoped).
- Auth: bearer token mapped to API key + campaign on the server side, so players never see the raw Archivist key.
- Audit log of who committed which summary.

The tool surface itself doesn't change.

## Project layout

```
archivistdnd/
├── ArchivistAPIQuickStart.md       (existing)
├── ArchivistAPIReference.md.txt    (existing)
├── DESIGN.md                       (this doc)
├── README.md
├── pyproject.toml
├── .env.example
├── src/
│   └── archivist_mcp/
│       ├── __init__.py
│       ├── __main__.py             # transport entry
│       ├── server.py               # FastMCP instance, registers everything
│       ├── client.py               # httpx wrapper around api.myarchivist.ai
│       ├── resources.py            # @mcp.resource definitions
│       ├── tools/
│       │   ├── ask.py
│       │   ├── summaries.py        # draft_/commit_ pairs
│       │   ├── compendium.py       # register_item, promote_item_to_homebrew
│       │   ├── journals.py
│       │   └── search.py
│       ├── prompts.py              # @mcp.prompt definitions
│       ├── templates/
│       │   └── statblock.md.j2     # Jinja for mechanics journals
│       └── models.py               # Pydantic mirrors of Archivist schemas
└── tests/
    ├── test_client.py
    ├── test_compendium.py
    └── fixtures/                   # recorded API responses
```

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tool accidentally overwrites a hand-edited summary | Always `draft_*` before `commit_*`. Commit returns the prior value, *and* archives it to `Summary History/` when overwriting an existing summary. |
| RAG bloat from too many mechanics journals | Mechanics journals only created when `mechanics` is explicitly passed to `register_item`. Free-form `tags` allow exclusion at retrieval time if needed. |
| Lexical schema drift breaking journal writes | We never send `content_rich`. Markdown-only via `content` until we have a verified Lexical example to copy from. |
| API key exposure | Local stdio only in v1. Key never crosses process boundary. `.env` in `.gitignore`. |
| Token limits on `/v1/ask` (monthly + hourly) | Surface `monthlyTokensRemaining` / `hourlyTokensRemaining` from response in tool output so Claude / user can see it. |
| Wikilink drift if item is renamed | Renames go through a tool that updates both the Item description and the linked journal title in one operation. |
| Sessions PATCH-only | Acknowledged, not a problem — we never need to create sessions, only edit. |

## Open questions (deferred, not blocking v1)

1. **In-app rendering of markdown statblocks** — once we run a real `register_item` call, inspect how the journal entry looks in the Archivist app. If it's ugly enough to bother the user, export a similar journal entry the user has hand-built in the app, copy its `content_rich` shape as a Lexical template, and switch to sending both fields.
2. **`Item.type` wire format for multi-word values** — UI shows "Wondrous Item"; API shows lowercase singletons ("weapon"). Probe with a POST to confirm whether the wire format is `"wondrous item"`, `"wondrous_item"`, `"wondrous-item"`, or something else, and bake the mapping into the client.
3. **Mechanics field shape** — `register_item(mechanics=...)` payload structure. Loose dict vs. a typed Pydantic model (`damage`, `properties`, `mastery`, `attunement`, `rarity`, `notes`). Typed is better for the template; loose is more forgiving for one-off weird items. Probably typed-with-an-`extra` dict.
4. **Rename handling** — Item rename should propagate to the linked journal title and update wikilinks in both directions. Unclear whether Archivist's wikilink sync handles renames or only initial linking. Test before committing to a rename tool.

## Build order

1. Project skeleton + `client.py` + health-check tool. Smoke-test against the real API.
2. Resources for campaign, sessions list, single session (composite). Verify in Claude Desktop.
3. `ask_archivist` tool with streaming.
4. `draft_session_summary` + `commit_session_summary`. End-to-end test on a real session.
5. Campaign summary tools.
6. `upsert_journal_entry`, then `register_item` / `promote_item_to_homebrew`.
7. Prompts.
8. Polish: error messages, token-budget surfacing, README with Claude Desktop config snippet.

Estimate: ~1 evening per major step for someone comfortable with Python + httpx.
