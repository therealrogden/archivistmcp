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
| `archivist://journal/{id}` | `GET /v1/journals/{id}` | **Plain text only** (`content`, not `content_rich`) — token-efficient |
| `archivist://journal-folders` | `GET /v1/journal-folders?campaign_id=…` | Folder tree for placement |

**Key principle:** resources are read-cheap. The `session/{id}` resource especially: bundling four endpoints into one resource means Claude pays one round-trip to get everything it needs to summarize.

### Tools (writes and active operations)

Total surface: **10 tools**. Kept tight on purpose.

| Tool | Effect |
|---|---|
| `ask_archivist(question, asker_id?, gm_permissions?, stream=true)` | Wraps `POST /v1/ask`. Default `gm_permissions=false`, `asker_id=null`. |
| `draft_session_summary(session_id, style?, length?)` | Reads the composite session resource, returns a draft summary. **Does not write.** |
| `commit_session_summary(session_id, summary, title?)` | `PATCH /v1/sessions/{id}`. Backs up the prior summary in the response payload. |
| `draft_campaign_summary(guidance?)` | Aggregates session summaries + quests + key entities, drafts a new campaign description. |
| `commit_campaign_summary(description)` | `PATCH /v1/campaigns/{id}`. |
| `upsert_journal_entry(folder_id, title, content, content_rich?, tags?)` | For long-form overviews and statblock journals. Idempotent on `(folder_id, title)`. |
| `register_item(name, narrative_description, tier, mechanics?, type?, image?)` | **Composite**: creates the Item, and if `mechanics` is supplied, creates a paired statblock journal entry with cross-wikilinks. See Compendium section. |
| `promote_item_to_homebrew(item_id, mechanics)` | Adds the mechanics journal to an existing Item (e.g., players enchant an existing weapon). |
| `link_entities(from_id, from_type, to_id, to_type, alias?)` | Wraps `POST /v1/campaigns/{id}/links`. |
| `search_entities(query, types?)` | Multi-type fuzzy search across characters/items/factions/locations. |

### Prompts (templates the user picks from)

| Prompt | Composes |
|---|---|
| `recap-last-session` | Reads latest session resource, calls `draft_session_summary` with style="recap-for-players", presents for review. |
| `state-of-the-campaign` | Calls `draft_campaign_summary` with guidance="overview suitable for new players joining". |
| `prep-next-session` | Reads quests + last session + open beats, drafts GM prep notes (does not write back). |
| `register-found-item` | Walks user through tier classification, then calls `register_item`. |
| `summarize-faction-arc(faction_id)` | Pulls a faction + linked beats/moments/characters/quests, drafts an arc summary. |

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

Same shape. `draft_campaign_summary` aggregates:
- `campaign.description` (current)
- All `sessions[].summary` in chronological order
- All `quests[]` with status
- Top N characters/factions by link count

For long-form "State of the Campaign" overviews, the commit target is a **pinned journal entry** in a `Campaign Overview` folder rather than `campaign.description` (which is meant to be short). The prompt asks the user which target they want.

### Compendium (hybrid item tracking)

Two-layer model, summarized:

**Layer 1 — Item entity:** narrative description, `type` field carries tier classification, wikilink to the mechanics journal if one exists.

**Layer 2 — Journal Entry** in `Items / Mechanics` folder: full statblock in Lexical (table or styled blocks), plain-text fallback for RAG, tagged `["mechanics", <category>, <tier>]`, wikilink back to the Item.

**Tier classification:**

| Tier | Item entity? | Mechanics journal? | Example |
|---|---|---|---|
| `mundane-srd` | No | No | A torch, generic longsword |
| `named-mundane` | Yes | No | "Grandfather's locket" |
| `homebrew` | Yes | Yes | "Whispering Dagger" |
| `srd-magic` | Yes | No (Claude knows it) | "Bag of Holding" |
| `homeruled-srd` | Yes | Yes (just the deltas) | House-ruled "Cloak of Elvenkind" |

`register_item` enforces this branching server-side so the convention can't drift.

**Statblock journal template** (Lexical-equivalent markdown):

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

Tags applied automatically: `["mechanics", "weapon"|"armor"|"wondrous-item"|..., tier]`.

**Why not formal Links:** `Link.EntityType` enum doesn't include `JournalEntry`. Wikilinks in content are the supported path, and Archivist syncs them on save.

## Configuration

`.env`:

```
ARCHIVIST_API_KEY=...
ARCHIVIST_CAMPAIGN_ID=...
ARCHIVIST_BASE_URL=https://api.myarchivist.ai     # override for staging
ARCHIVIST_MECHANICS_FOLDER=Items/Mechanics        # auto-created if missing
ARCHIVIST_OVERVIEW_FOLDER=Campaign Overview
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
| Tool accidentally overwrites a hand-edited summary | Always `draft_*` before `commit_*`. Commit returns the prior value so it's recoverable from chat history. |
| RAG bloat from too many mechanics journals | Tier system: only `homebrew` / `homeruled-srd` get journals. Tags allow exclusion at retrieval time if needed. |
| API key exposure | Local stdio only in v1. Key never crosses process boundary. `.env` in `.gitignore`. |
| Token limits on `/v1/ask` (monthly + hourly) | Surface `monthlyTokensRemaining` / `hourlyTokensRemaining` from response in tool output so Claude / user can see it. |
| Wikilink drift if item is renamed | Renames go through a tool that updates both the Item description and the linked journal title in one operation. |
| Sessions PATCH-only | Acknowledged, not a problem — we never need to create sessions, only edit. |

## Open questions (deferred, not blocking v1)

1. **Statblock format**: markdown table (above) vs. proper Lexical nodes vs. a Homebrewery-style block. Markdown is simplest; Lexical renders better in-app.
2. **Auto-tier classification**: should `register_item` ask Claude to classify the tier given the description, or always require the caller to pass it? Manual is safer; auto is faster.
3. **Cast-analysis weighting**: should `draft_session_summary` always include cast-analysis context, or make it opt-in via a `style` flag? Probably always include but condense.
4. **Quest auto-update**: when committing a session summary, should the server also offer to draft quest progress entries for active quests mentioned in the summary? Powerful but invasive — defer.
5. **Versioning**: do we want to write each prior summary to a `Summary History` journal folder before overwriting? Cheap insurance; some users will hate the noise.

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
