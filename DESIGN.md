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
| Resource list shape | Slim lists only. Every list resource returns `id`, `name`/`title`, `type` where applicable, `tags` where applicable, and `updated_at`, plus a small set of type-specific extensions. Full entity records are available exclusively via `{id}` resources. Rationale: a campaign with 100 NPCs must not cost 50k tokens to browse. |
| Pagination | List resources accept `page`, `page_size` (capped at 50), and `cursor` where the API supports it. Unparameterized fetches return the first page only — no silent multi-page aggregation. Claude pages explicitly when it needs more. |
| Discovery path | `search_entities` is the primary discovery surface for "find the X with property Y". List resources exist for browsing and paging, not searching. |
| Composites | Composites live in **tools**, not resources. E.g. `draft_session_summary` internally fetches session + beats + moments + cast-analysis; `archivist://session/{id}` returns only session metadata. Resources stay single-responsibility so Claude (and caches) can reason about their cost. |
| Error handling | Exponential backoff with jitter on `GET` (2 retries max, on 429 / 5xx). Fail-fast on `POST`/`PATCH`/`DELETE` — no retries on writes. Upstream errors surface as raw MCP tool errors with status + response body so Claude can reason about the failure. |
| Caching | In-process TTL cache. 60 s for list URIs, 5 min for detail URIs, no cache on `search_entities`. Tool writes synchronously invalidate affected URI prefixes before returning. |
| Input validation | Pydantic on every tool input via `Annotated[Type, Field(description="…")]`. String fields capped (50 KB for `content`, 1 KB for names/titles). Path IDs validated as UUIDs before any API call. No output validation — trust upstream shapes. |
| Commit-archive transactionality | Equality-guarded: if the proposed content equals the current value (whitespace-normalized), skip archive + PATCH and return `already_current=true`. When content differs: archive-first, fail-fast. If archive fails, abort before touching the original. If archive succeeds but the PATCH fails, surface the error — the archived copy is the safety net, no rollback attempted. |
| Testing | Unit tests with recorded-but-synthesized fixtures. `scripts/record_fixtures.py` hits a live campaign, scrubs content (UUIDs, names, timestamps → deterministic fakes) while preserving shape, commits fixtures under `tests/fixtures/`. `scripts/check_fixture_drift.py` re-records and shape-diffs against committed copies. Fixtures are safe to commit publicly. |
| Observability | Structured JSON logs to stderr (stdout is reserved for MCP protocol). Log level via `ARCHIVIST_LOG_LEVEL`. Logged events: startup, HTTP request method/URL/status/duration, cache hit/miss, tool invocation with duration + outcome, resource read. No external sinks. |
| Distribution | `uvx`-installable as `archivist-mcp`. Packaging (entry point, credentials fallback, README MCP snippets) lands at step 17 and is installed via `uvx --from git+https://...` during the rest of the build. Actual PyPI publish is gated on step 19 polish so users don't pin a half-baked `0.1.0`. API key reads from `ARCHIVIST_API_KEY` env var first, falls back to `~/.config/archivist-mcp/credentials.toml`. Streamable-HTTP transport stays in-tree as an advanced opt-in via `ARCHIVIST_TRANSPORT=http`. |
| `/v1/ask` streaming | Upstream answers stream as HTTP chunked `text/plain` (markdown lines), not SSE/NDJSON. Token budgets arrive on response headers (`x-monthly-remaining-tokens`, `x-hourly-remaining-tokens`). The tool maps those to snake_case in the return payload. MCP progress notifications forward text chunks when the client sends a `progressToken` on `tools/call`; otherwise `report_progress` is a no-op and the full answer still returns when the stream completes. |
| Concurrency | Single-flight on reads (per-URI `asyncio.Lock` coalesces concurrent reads of the same URI into one upstream call). Sequential writes (one global write lock). Cache invalidation runs synchronously after each write before the lock releases. |
| MCP resource-list semantics | `resources/list` returns URI templates for per-entity URIs (`archivist://session/{id}`, etc.) plus concrete entries only for campaign-scoped list URIs (`archivist://sessions`, `archivist://quests`, etc.). No eager enumeration of individual entities. |

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

Single process, single API key, single campaign. The server is a thin adapter: HTTP client + schema typing + a few **tool-level** composite operations (e.g. `draft_session_summary`) that bundle multiple REST calls into one MCP tool call. Resources stay single-responsibility — composites never live in the resource layer.

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

Resources are partitioned into **slim list views** and **full-detail single-entity views**. List resources return just enough fields for Claude to decide what to fetch next. Full records live behind `{id}` resources. This is a deliberate choice to bound context cost on long-running campaigns: a browse of 100 NPCs should cost ~2k tokens, not ~50k.

| URI | Backing endpoint | Shape | Purpose |
|---|---|---|---|
| `archivist://campaign` | `GET /v1/campaigns/{id}` | full | Campaign record |
| `archivist://campaign/stats` | `GET /v1/campaigns/{id}/stats` | full | Aggregate counts |
| `archivist://campaign/links` | `GET /v1/campaigns/{id}/links` | slim list | Entity graph edges |
| `archivist://sessions` | `GET /v1/sessions?campaign_id=…` | slim list | Sessions ordered by `session_date` |
| `archivist://session/{id}` | `GET /v1/sessions/{id}` | full | Session metadata only (no beats/moments) |
| `archivist://session/{id}/beats` | `GET /v1/beats?game_session_id={id}` | slim list | Beats for this session |
| `archivist://session/{id}/moments` | `GET /v1/moments?session_id={id}` | slim list | Moments for this session |
| `archivist://session/{id}/cast-analysis` | `GET /v1/sessions/{id}/cast-analysis` | full | Cast analysis; `null` when absent |
| `archivist://beats` | `GET /v1/beats?campaign_id=…` | slim list | All beats in the campaign |
| `archivist://beat/{id}` | `GET /v1/beats/{id}` | full | Single beat |
| `archivist://moments` | `GET /v1/moments?campaign_id=…` | slim list | All moments in the campaign |
| `archivist://moment/{id}` | `GET /v1/moments/{id}` | full | Single moment |
| `archivist://quests` | `GET /v1/quests?campaign_id=…` | slim list | Quest list (no expanded objectives) |
| `archivist://quest/{id}` | `GET /v1/quests/{id}` | full | Quest with expanded objectives, progress log, refs |
| `archivist://characters` | `GET /v1/characters?campaign_id=…` | slim list | Cast list (PCs + NPCs) |
| `archivist://character/{id}` | `GET /v1/characters/{id}` | full | Single character |
| `archivist://items` | `GET /v1/items?campaign_id=…` | slim list | Compendium list |
| `archivist://item/{id}` | `GET /v1/items/{id}` + linked mechanics journal | full | Item with statblock |
| `archivist://factions` | `GET /v1/factions?campaign_id=…` | slim list | Faction list |
| `archivist://faction/{id}` | `GET /v1/factions/{id}` | full | Single faction |
| `archivist://locations` | `GET /v1/locations?campaign_id=…` | slim list | Location list |
| `archivist://location/{id}` | `GET /v1/locations/{id}` | full | Single location |
| `archivist://journals` | `GET /v1/journals?campaign_id=…` | slim list | Journal metadata list |
| `archivist://journal/{id}` | `GET /v1/journals/{id}` | full (plain-text) | `content` only; `content_rich` stripped. We never read or write `content_rich` in v1. |
| `archivist://journal-folders` | `GET /v1/journal-folders?campaign_id=…` | slim list | Folder tree for placement |
| `archivist://journal-folder/{id}` | `GET /v1/journal-folders/{id}` | full | Single folder |

**Slim list shape.** Every list resource returns a page of objects with a small, predictable set of fields. The base shape varies slightly by entity because the Archivist API is not uniform — only journals / quests / journal-folders carry `updated_at`, only journals carry `tags`, moments return their full `content` in list responses (which we truncate), and so on. Rather than invent fields, we project what the API actually returns.

**Base fields (all slim lists):** `id`, plus `name` or `title`.

**Per-entity slim projections:**

- **Sessions** — `title`, `session_date`, `has_summary` (bool), `summary_length` (char count; 0 when unset)
- **Quests** — `name`, `status`, `objective_count`, `completion_pct` (derived from objectives), `updated_at`, `tags`
- **Characters** — `name`, `type` (PC/NPC passthrough), `is_player` (derived: `type == "PC"`), `has_speaker` (derived: `player is not None`)
- **Items** — `name`, `type` (enum passthrough), `has_mechanics` (derived: mechanics journal exists in the configured folder for this item name)
- **Factions** — `name`, `alignment` if present
- **Locations** — `name`, `is_root` (derived: no parent location)
- **Beats** — `id`, `title`, `session_id`, `sequence`, `is_root` (derived: no parent beat)
- **Moments** — `id`, `session_id`, `timestamp`, `content_excerpt` (first 120 chars of `content`)
- **Journals** — `title`, `folder_id`, `updated_at`, `tags`
- **Journal folders** — `id`, `name`, `parent_id`, `is_root` (derived: `parent_id is None`)
- **Campaign links** — `from_id`, `from_type`, `to_id`, `to_type`, `alias`

**Derivation cost is bounded.** Derivations that require an extra API call (currently only `has_mechanics`) are serviced by the cached `archivist://journal-folders` + mechanics-folder listing. One cached fetch covers an entire items-list rendering; total extra API cost per slim list render is at most one mechanics-folder listing per 60 s TTL window.

**What we deliberately don't derive:** `is_completed` / `is_active` / `is_published` (redundant with `status` — Claude reads the enum), `has_cast_analysis` and `has_transcript` (expensive per-item probe), `link_count` (requires a graph traversal per entity).

If Claude needs every field of every entity in a list, that is a signal to either filter via `search_entities` or accept the cost and page through explicitly, fetching `{id}` URIs for the records that actually matter.

**Pagination.** List resources accept query parameters forwarded to the Archivist API: `page`, `page_size` (server-side cap: 50), and `cursor` where supported. An unparameterized list fetch returns the first page only — there is no silent multi-page aggregation on the server side. Claude pages explicitly when it needs more, which keeps the per-call cost legible and cacheable.

**Discovery via search, not enumeration.** For "find the artifact the party took from the lich" or "which NPC did they last speak to in Waterdeep", `search_entities` is the preferred path. List resources exist for browsing and paging; they are not a search API. The `search_entities` tool is mandatory, not optional, for this reason — see the Tools section.

`search_entities` is a **lexical + typed-filter** surface: text match plus typed parameters like `types=["character"]`, `status="active"`, `has_mechanics=true`. It runs server-side so matched entities are filtered before reaching Claude's context. Semantic / RAG-style queries ("what does Elara know about the artifact") belong to `ask_archivist`, which wraps Archivist's own `/v1/ask`. The two are intentionally separate: lexical filters for "find this thing," RAG for "reason over my campaign."

**When lexical search misses, escalate to `ask_archivist`.** If `search_entities` returns zero or obviously-wrong results for a conceptual query ("the artifact the party took from the lich"), Claude's next move is `ask_archivist` — not a list enumeration. This ordering matters: list-page enumeration is the context-exhaustion path we built slim projections to avoid. Search → ask is cheap; search → enumerate is expensive. No formal recall SLOs or hit-rate targets in v1 — we'll revisit if real use surfaces systemic misses.

**Composites belong in tools.** The older composite `archivist://session/{id}` (bundling session + beats + moments + cast-analysis into one resource) has been dissolved. Single-responsibility resources make each URI's cost predictable. When a workflow genuinely needs several endpoints' worth of data in one round-trip (e.g., drafting a session summary), the composite lives in the **tool** that needs it, not the resource.

### Tools (writes and active operations)

Total surface: **10 tools**. Kept tight on purpose.

| Tool | Effect |
|---|---|
| `ask_archivist(question, asker_id?, gm_permissions?)` | Wraps `POST /v1/ask` with `stream: true`. Default `gm_permissions=false`, `asker_id=null`. Returns `{"answer": "<markdown>", "tokens": {"monthly_tokens_remaining", "hourly_tokens_remaining", ...}}` — budgets from response headers when streaming (integers); optional JSON token fields on streamed lines override header snapshot. Emits MCP progress per decoded chunk when the host supports progress. |
| `draft_session_summary(session_id, style?, length?, include_cast_analysis=False)` | Internally fetches session + beats + moments (and cast-analysis when `include_cast_analysis=True`), returns a draft summary. **Does not write.** Cast analysis is silently skipped on 404 (e.g., play-by-post sessions). |
| `commit_session_summary(session_id, summary, title?)` | `PATCH /v1/sessions/{id}`. If a prior non-empty summary exists, archives it to `Summary History/` first (see Versioning). Returns prior summary verbatim in the response. |
| `draft_campaign_summary(guidance?)` | Aggregates session summaries + quests + key entities, drafts a new campaign description or long-form overview. |
| `commit_campaign_summary(target, content)` | `target="description"` → `PATCH /v1/campaigns/{id}`. `target="overview"` → upserts the pinned `Campaign Overview` journal entry. Same archival rule as session summaries. |
| `upsert_journal_entry(folder_id, title, content, tags?)` | For long-form overviews and statblock journals. Idempotent on `(folder_id, title)`. Sends `content` (markdown) only; no `content_rich`. |
| `register_item(name, description, mechanics?, type?, image?, tags?)` | Creates the Item. If `mechanics` is provided, also creates a paired statblock journal entry in the mechanics folder with cross-wikilinks. No tier enum; the presence of `mechanics` *is* the decision. |
| `promote_item_to_homebrew(item_id, mechanics)` | Adds the mechanics journal to an existing Item (e.g., players enchant an existing weapon). Updates the Item description to add a wikilink to the new journal. |
| `link_entities(from_id, from_type, to_id, to_type, alias?)` | Wraps `POST /v1/campaigns/{id}/links`. |
| `search_entities(query, types?, filters?)` | Lexical multi-type search across characters/items/factions/locations/quests/journals. Accepts typed filters (e.g. `status="active"`, `has_mechanics=true`, `is_player=false`). Returns slim-shape results ranked by relevance. Not cached. For semantic / RAG-style questions, use `ask_archivist`. |

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
2. Claude → resource archivist://sessions → finds latest by session_date (slim list)
3. Claude → tool draft_session_summary(session_id, style="recap")
   ↳ Server fetches session + beats + moments (+ cast-analysis if opted in)
     internally — Claude does not orchestrate these reads.
   ↳ Returns draft, includes prior summary verbatim for diff comparison.
4. User reviews / asks for revisions in chat
5. Claude → tool commit_session_summary(session_id, summary=<approved>)
   ↳ Server PATCHes; returns confirmation + token count
```

Two-step (draft → commit) is mandatory. Never collapse into a single tool.

### Campaign summary

Same draft → review → commit shape. `draft_campaign_summary` aggregates (paging the slim lists as needed, fetching full records only where required):
- `campaign.description` (current)
- All session summaries in chronological order — fetched per-session via `archivist://session/{id}`, since the sessions slim list carries `summary_length` but not the summary text itself
- All quests with status (slim list has `status` — sufficient)
- Top N characters / factions by link count

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

**Partial-failure reporting.** If step 2 succeeds but step 3 fails, the commit tool returns an error whose payload includes the archived entry's `folder_id`, `title`, and `journal_id`, so the caller can delete or reconcile it manually in the Archivist web app. The failure is also logged as a distinct `orphan_archive` event with the same fields, making the orphan discoverable from server logs without needing the original tool response. No automated reconciliation is attempted — the archived copy exists as a safety net, and Archivist's UI already has the affordances to clean it up.

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

## Operational concerns

The cross-cutting behaviors that every resource and tool relies on. These are the implementations behind the Decisions table above.

### Error handling and retries

`GET` requests retry on transient failure: two retries max, exponential backoff with jitter (base 0.25 s, factor 2, jitter ±25 %), only on `429` and `5xx`. `4xx` other than `429` fails immediately. `POST`/`PATCH`/`DELETE` never retry — writes are surfaced verbatim so Claude or the user can decide whether to retry.

All upstream errors that make it past the retry policy are rethrown as raw MCP tool errors. The error payload carries: HTTP status, endpoint, response body (truncated to 2 KB), and a correlation ID that appears in the server logs. We do not paper over errors with friendly messages — Claude is better at diagnosing a real `422` than a translated "invalid input".

### Caching

A single in-process TTL cache lives alongside the httpx client.

- **List URIs** (`archivist://sessions`, `archivist://quests`, etc.): 60 s TTL.
- **Detail URIs** (`archivist://session/{id}`, etc.): 5 min TTL.
- **`search_entities`**: not cached. Search is a discovery surface and results should reflect the latest state.
- **`archivist://journal-folders`**: 5 min TTL, shared with detail URIs. This cache backs the `has_mechanics` derivation on Item slim lists.

Writes (every tool that `POST`s, `PATCH`es, or `DELETE`s) invalidate by URI prefix synchronously before returning. A `commit_session_summary` invalidates `archivist://session/{id}` and `archivist://sessions`. `register_item` invalidates `archivist://items` and — if a mechanics journal was created — `archivist://journals` and `archivist://journal-folders`. Invalidation rules live in one module so the mapping is auditable.

No distributed cache. No persistent cache. The cache dies with the process.

### Concurrency

FastMCP can dispatch multiple tool/resource calls concurrently. Two races matter:

1. **Cold-cache duplicate fetches.** Two reads of the same URI arriving at the same time should coalesce into one upstream call. A per-URI `asyncio.Lock` guards the fetch+cache-populate critical section. Later arrivals wait on the lock and read the warm cache when it releases.
2. **Write-after-write on the same entity.** A global `asyncio.Lock` serializes writes. Two `commit_session_summary` calls on the same session can't interleave the archive + PATCH steps.

Reads and writes can still overlap. Cache invalidation is synchronous within the write lock, so any read that starts after a write completes sees fresh data. A read in flight when a write begins may return the pre-write value — this is the accepted behavior.

### Idempotency

Writes never retry automatically (see *Error handling and retries*), but Claude can invoke the same tool twice in a session and users can re-trigger a flow after a crash. Every write tool defines a natural-key idempotency rule so duplicate invocations don't corrupt campaign state. No `request_id` tokens, no server-side dedupe window — natural keys are sufficient for a single-user stdio MCP.

- **`commit_session_summary` / `commit_campaign_summary`** — **equality-guarded**. Before archiving, the tool fetches the current summary and compares it (after normalizing whitespace and trailing newlines) to the proposed content. If they match, the tool skips archive + PATCH entirely and returns `{"already_current": true, "session_id": ...}`. This gives deterministic idempotency independent of wall-clock: the same commit invoked five seconds apart is a no-op, not a duplicate archive entry. When content differs, the archive step runs as before; the archive title uses an ISO timestamp for ordering (not for dedupe — the equality guard is the dedupe primitive).
- **`upsert_journal_entry`** — idempotent on `(folder_id, title)`. Second call updates content in place.
- **`register_item`** — dedupes on **`(name, mechanics_signature)`** when a `mechanics` payload is provided, where `mechanics_signature` is the SHA-256 of the canonically-serialized mechanics JSON. If an existing Item in the campaign has the same name *and* an identical mechanics signature, the tool returns it with `{"already_exists": true}` instead of creating a duplicate. When `mechanics` is not provided, **no dedupe is attempted** — the tool creates the Item unconditionally. Rationale: a campaign may legitimately contain multiple distinct "Potion of Healing" or "Sending Stone" narrative entries that the user is tracking as separate story instances. Only identical homebrew-with-mechanics definitions collapse; narrative-only registrations do not. If dedupe behavior is ever needed for a specific narrative item, the caller can `search_entities` first.
- **`promote_item_to_homebrew`** — upserts the mechanics journal on `(mechanics_folder_id, "{Item.name} — Mechanics")`. Second call updates the existing journal.
- **`link_entities`** — dedupes on `(from_id, from_type, to_id, to_type)`. On collision returns the existing edge (updating `alias` if provided).

`ask_archivist`, `draft_session_summary`, `draft_campaign_summary`, and `search_entities` have no write side-effects and so need no idempotency rules.

### Input validation

Every tool signature uses Pydantic via `Annotated[Type, Field(description="…")]`. The `description` becomes the MCP tool schema description, so Claude sees field-level guidance, not just types.

Hard caps on string fields:
- `content` (journals, moments, summaries): 50 KB.
- `name`, `title`, `alias`: 1 KB.
- `tags[i]`: 64 B, max 32 tags per entity.
- `mechanics` (free-form dict): 16 KB serialized.

Path parameters typed as UUIDs (`session_id`, `beat_id`, `moment_id`, `quest_id`, `character_id`, `item_id`, `faction_id`, `location_id`, `journal_id`, `folder_id`) are validated as UUID strings before the call hits `client.get`. Malformed IDs fail at the tool boundary with a clear message instead of a 404 round-trip.

We do not validate **outputs**. Upstream shapes are trusted; drift is caught by the fixture-diff script, not by runtime parsing.

### Observability

Structured JSON logs to **stderr only** (stdout is reserved for the MCP protocol when running over stdio). One JSON object per line, suitable for `grep`, `jq`, or a log-shipping sidecar.

Log level configurable via `ARCHIVIST_LOG_LEVEL` (default `INFO`).

Events logged:

- `startup` — transport, campaign ID (masked), base URL.
- `http_request` — method, path, status, duration_ms, retries, correlation_id.
- `cache` — hit / miss / invalidate, URI, ttl_remaining_s.
- `tool_invocation` — name, duration_ms, outcome (`ok` / `error`), input sizes, correlation_id.
- `resource_read` — URI, duration_ms, outcome.
- `error` — correlation_id, phase, exception class, message, response body (truncated).

API keys never appear in logs. Campaign IDs are rendered as the last 4 characters of the UUID.

No external sinks (no Sentry, no OTLP, no file output). A user who wants remote logging can pipe stderr into anything they like.

### Testing

Unit tests against a synthesized-fixture fake. Live API never hit in the automated suite. Tests ship with the code they verify — every build-order step lists its own test requirements, and no step is "done" until its tests pass. There is no late-stage test backfill phase.

**Test design principles:**

- **Tests assert behavior, not implementation.** "After a write, the next read returns fresh data" — not "the invalidation-map contains URI X." Lets us refactor internals without rewriting tests.
- **Mock only the HTTP boundary** (via `pytest-httpx`). Never mock code we own. Projections, cache, concurrency, validation, tools — all exercised as real code paths.
- **One test file per production module.** `test_cache.py`, `test_projections.py`, `test_search.py`, etc. File structure mirrors `src/archivist_mcp/`.
- **Failure modes get dedicated tests.** If code exists for a partial-failure path, that path is exercised. Archive-first commit has an injected-PATCH-failure test. Retry policy has a 429/5xx injection test. Cache invalidation has a write-during-read overlap test.
- **Determinism.** Fixtures are static, clocks are frozen via `freezegun` where time matters (TTL expiry, timestamps in archive titles), UUIDs in fixtures are deterministic per scrub rules.

**What qualifies as "tested" for each category:**

| Category | Bar |
|---|---|
| **Resources** | Slim-list shape asserted field-by-field against a fixture; pagination params forwarded correctly; error passthrough preserves upstream status. |
| **Tools (reads)** | Tool returns the documented payload for the happy path + at least one error case. Progress-notification streaming tested by asserting emitted notifications on the MCP context. |
| **Tools (writes)** | Happy path + idempotency (double-invocation returns same state, no duplicate side-effects) + natural-key collision test + partial-failure injection where applicable. |
| **Projections** | Each entity projection tested with a representative fixture; derivations (`is_player`, `completion_pct`, `has_mechanics`, etc.) covered explicitly including boundary cases (PC with no player, quest with zero objectives). |
| **Cache** | Hit / miss, TTL expiry, URI-prefix invalidation, write-then-read freshness. |
| **Concurrency** | Single-flight coalescing under concurrent cold-URI reads (only one upstream call happens); write serialization (two overlapping writes run sequentially); read-during-write returns a valid value. |
| **Validation** | Every size cap, UUID rejection, enum rejection, `mechanics` bare-scalar rejection, description/field metadata present in generated MCP schema. |
| **Retries** | 429 + 5xx retried with expected backoff; 4xx (except 429) not retried; writes fail fast. |
| **Logging** | Each event schema emitted for its triggering action; API key absent from all event output; campaign ID masked. |

**Coverage expectations:**

- Every write path has an idempotency test.
- Every cache invalidation rule has a fresh-read test.
- Every documented failure mode has a failure-injection test.
- No percentage-based coverage target. Branch coverage on write paths and error paths is the bar; line coverage on happy-path reads will follow naturally.

**Running tests:**

- `pytest tests/` — runs the whole suite offline. No credentials, no network. CI-runnable.
- `python scripts/check_fixture_drift.py` — re-records fixtures against a live campaign and shape-diffs against committed copies. Requires credentials; run manually or on a cron. Non-zero exit on drift.
- `python scripts/record_fixtures.py` — re-records and commits fresh fixtures after an intentional API upgrade.

**Fixture lifecycle:**

- Fixtures are committed as scrubbed artifacts under `tests/fixtures/`.
- Re-record when the API shape changes (drift script reports non-zero) or when a new endpoint enters the test surface.
- Schema-shape diffs are the signal — content diffs are expected and ignored by the drift script.

Two scripts support fixture maintenance:

- `scripts/record_fixtures.py --campaign-id=<uuid>` — runs against a live campaign, scrubs responses, writes fixtures to `tests/fixtures/`. Requires real credentials. Only run manually, never in CI.
- `scripts/check_fixture_drift.py --campaign-id=<uuid>` — re-records into a temp dir, shape-diffs against committed fixtures, reports added / removed / changed fields. Exits non-zero on drift. Optional scheduled run (cron / CI).

### Distribution

Distributed as `archivist-mcp`, run via `uvx` so users install and launch in one line. The PyPI publish is gated on step 19 polish to avoid shipping a half-baked `0.1.0` that early users pin. Until then, the same command installs from git:

```bash
# Pre-publish (build order steps 17+):
uvx --from git+https://github.com/<owner>/archivist-mcp archivist-mcp

# Post-publish (step 19 onward):
uvx archivist-mcp
```

MCP config reference (one server entry per campaign):

```json
{
  "mcpServers": {
    "archivist-strahd": {
      "command": "uvx",
      "args": ["archivist-mcp"],
      "env": { "ARCHIVIST_CAMPAIGN_ID": "uuid-of-strahd-campaign" }
    },
    "archivist-homebrew": {
      "command": "uvx",
      "args": ["archivist-mcp"],
      "env": { "ARCHIVIST_CAMPAIGN_ID": "uuid-of-homebrew-campaign" }
    }
  }
}
```

The API key is not in the MCP config. It's read from (in order):

1. `ARCHIVIST_API_KEY` env var — wins if set. Useful for CI / containers.
2. `~/.config/archivist-mcp/credentials.toml` (platform-appropriate path on Windows and macOS) — single file the user edits once:

   ```toml
   api_key = "..."
   ```

This keeps per-campaign MCP entries free of credential duplication and avoids committing secrets into a shared MCP config. The streamable-HTTP transport ships in-tree but is not the default; it activates only when `ARCHIVIST_TRANSPORT=http` is set (see Local-now, remote-later).

## Configuration

`.env` is a **developer-convenience file only** — for running the probe script or a local server without shelling out env exports. Production runs read the same variables from the process env, which the MCP JSON config sets per instance. `ARCHIVIST_CAMPAIGN_ID` is deliberately **not** in `.env.example`: campaign ID belongs in the per-instance JSON MCP config (that's how multi-campaign works), not in a dev-machine dotfile that implies a single default.

```
# Credentials (prefer ~/.config/archivist-mcp/credentials.toml for long-lived use)
ARCHIVIST_API_KEY=...                             # optional if credentials.toml is set

# Optional overrides
ARCHIVIST_BASE_URL=https://api.myarchivist.ai     # override for staging
ARCHIVIST_MECHANICS_FOLDER=Items/Mechanics        # auto-created if missing
ARCHIVIST_OVERVIEW_FOLDER=Campaign Overview
ARCHIVIST_HISTORY_FOLDER=Summary History

# Operational
ARCHIVIST_LOG_LEVEL=INFO                          # DEBUG / INFO / WARNING / ERROR
ARCHIVIST_TRANSPORT=stdio                         # or "http" for streamable-http
```

For the probe script (`scripts/probe_contracts.py`), `ARCHIVIST_CAMPAIGN_ID` is required at invocation time — pass it via the environment when running the script (`ARCHIVIST_CAMPAIGN_ID=... python scripts/probe_contracts.py`), not via `.env`.

## Local-now, remote-later

Transport is a runtime concern, not a code concern. The same module exposes both:

```python
# src/archivist_mcp/__main__.py
import os
from .server import mcp

if os.getenv("ARCHIVIST_TRANSPORT") == "http":
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
├── scripts/
│   ├── probe_contracts.py          # live-API probe for open wire-format questions
│   ├── record_fixtures.py          # live-campaign recorder + scrubber
│   └── check_fixture_drift.py      # shape-diff committed fixtures vs. live
├── src/
│   └── archivist_mcp/
│       ├── __init__.py
│       ├── __main__.py             # transport entry (stdio | streamable-http)
│       ├── config.py               # env + credentials.toml loader
│       ├── server.py               # FastMCP instance, registers everything
│       ├── client.py               # httpx wrapper + retry policy
│       ├── cache.py                # TTL cache, URI-prefix invalidation
│       ├── concurrency.py          # single-flight read lock, global write lock
│       ├── projections.py          # slim-list shaping per entity
│       ├── validation.py           # Pydantic field caps, UUID checks
│       ├── logging_.py             # structured JSON stderr logger
│       ├── resources.py            # @mcp.resource definitions
│       ├── tools/
│       │   ├── ask.py              # ask_archivist with progress-notification streaming
│       │   ├── summaries.py        # draft_/commit_ pairs, archive-first commits
│       │   ├── compendium.py       # register_item, promote_item_to_homebrew
│       │   ├── journals.py
│       │   ├── links.py            # link_entities
│       │   └── search.py           # search_entities (lexical + typed filters)
│       ├── prompts.py              # @mcp.prompt definitions
│       ├── templates/
│       │   └── statblock.md.j2     # Jinja for mechanics journals
│       └── models.py               # Pydantic mirrors of Archivist schemas
└── tests/
    ├── conftest.py                 # pytest-httpx fixture wiring
    ├── unit/
    │   ├── test_client.py
    │   ├── test_cache.py
    │   ├── test_projections.py
    │   ├── test_validation.py
    │   ├── test_resources.py
    │   ├── test_summaries.py
    │   ├── test_compendium.py
    │   └── test_search.py
    └── fixtures/                   # scrubbed API responses (safe to commit)
```

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tool accidentally overwrites a hand-edited summary | Always `draft_*` before `commit_*`. Commit returns the prior value, *and* archives it to `Summary History/` when overwriting an existing summary. |
| RAG bloat from too many mechanics journals | Mechanics journals only created when `mechanics` is explicitly passed to `register_item`. Free-form `tags` allow exclusion at retrieval time if needed. |
| Lexical schema drift breaking journal writes | We never send `content_rich`. Markdown-only via `content` until we have a verified Lexical example to copy from. |
| API key exposure | Local stdio only in v1. Key never crosses process boundary. `.env` in `.gitignore`. |
| Token limits on `/v1/ask` (monthly + hourly) | Surface `monthly_tokens_remaining` / `hourly_tokens_remaining` in the tool return (parsed from `x-monthly-remaining-tokens` / `x-hourly-remaining-tokens` response headers when streaming). |
| Wikilink drift if item is renamed | Renames go through a tool that updates both the Item description and the linked journal title in one operation. |
| Sessions PATCH-only | Acknowledged, not a problem — we never need to create sessions, only edit. |
| Context exhaustion on long-running campaigns (100+ NPCs, items, journals) | Slim list resources + search-first discovery + explicit pagination. Lists never return more than one page without Claude asking for it, and never return full entity records. |
| Stale cache after external writes (user edits in Archivist web app while server is running) | TTLs are intentionally short (60 s lists, 5 min details). No cache on `search_entities`. Writes through this server invalidate eagerly; external writes surface within one TTL window. Persistent cache explicitly rejected so a restart always clears stale state. |
| Duplicate upstream requests under concurrent tool calls | Per-URI single-flight lock coalesces cold-cache fetches into one request; global write lock serializes writes. Documented in Concurrency. |
| Fixture drift hiding backend shape changes | `scripts/check_fixture_drift.py` compares committed fixtures against a fresh recording and fails on schema diff. Run before any release, and optionally on a cron. |
| Credentials ending up in a shared MCP config | API key supports a `~/.config/archivist-mcp/credentials.toml` fallback so the MCP config holds only the campaign ID per server entry. The .gitignore already excludes .env. |

## Open questions (deferred, not blocking v1)

Questions 2 and 3 are resolved by the contract probe (build order step 13) and closed below with recorded evidence. Questions 1 and 4 remain open until real use surfaces a forcing answer.

1. **In-app rendering of markdown statblocks** — once we run a real `register_item` call, inspect how the journal entry looks in the Archivist app. If it's ugly enough to bother the user, export a similar journal entry the user has hand-built in the app, copy its `content_rich` shape as a Lexical template, and switch to sending both fields.
2. **`Item.type` wire format for multi-word values** — **Closed (step 13)**. Live probe run `contract_probe_20260420T144536Z` accepted all tested variants (`"wondrous item"`, `"wondrous_item"`, `"wondrous-item"`). See **Contract probe results**.
3. **Mechanics field shape** — **Closed (step 13)**. Live probe run `contract_probe_20260420T144536Z` accepted typed object payloads, loose object payloads, and scalar string payloads for `mechanics`. See **Contract probe results**.
4. **Rename handling** — Item rename should propagate to the linked journal title and update wikilinks in both directions. Unclear whether Archivist's wikilink sync handles renames or only initial linking. Test before committing to a rename tool.

## Contract probe results

*Status: complete — build-order step 13 evidence recorded.*

### Probe: `Item.type` wire format for multi-word enum values

- **Date:** 2026-04-20
- **Closes:** Open Question #2
- **Tested payloads:**
  - Payload A (`control_weapon`): `{"campaign_id":"cmg3twddd0021jl0gesepxuit","description":"Disposable probe entity for contract validation.","name":"probe-step13-20260420T144536Z-control-weapon","type":"weapon"}`
  - Payload B (`wondrous_item_space`): `{"campaign_id":"cmg3twddd0021jl0gesepxuit","description":"Disposable probe entity for contract validation.","name":"probe-step13-20260420T144536Z-type-space","type":"wondrous item"}`
  - Payload C (`wondrous_item_underscore`): `{"campaign_id":"cmg3twddd0021jl0gesepxuit","description":"Disposable probe entity for contract validation.","name":"probe-step13-20260420T144536Z-type-underscore","type":"wondrous_item"}`
  - Payload D (`wondrous_item_hyphen`): `{"campaign_id":"cmg3twddd0021jl0gesepxuit","description":"Disposable probe entity for contract validation.","name":"probe-step13-20260420T144536Z-type-hyphen","type":"wondrous-item"}`
- **Upstream responses:**
  - Payload A -> HTTP 200, body excerpt: returned item `type: "weapon"`.
  - Payload B -> HTTP 200, body excerpt: returned item `type: "wondrous item"`.
  - Payload C -> HTTP 200, body excerpt: returned item `type: "wondrous_item"`.
  - Payload D -> HTTP 200, body excerpt: returned item `type: "wondrous-item"`.
- **Accepted wire format / shape:** Archivist currently accepts all tested multi-word variants (`space`, `underscore`, and `hyphen`).
- **Validator decision:** Client should normalize to one canonical outgoing representation (`"wondrous item"`) for deterministic writes, while accepting and preserving all observed variants when reading legacy data.
- **Commit:** Pending (set to the implementation commit SHA that locks this mapping).

### Probe: `mechanics` payload accepted shape

- **Date:** 2026-04-20
- **Closes:** Open Question #3
- **Tested payloads:**
  - Payload A (`control_no_mechanics`): `{"campaign_id":"cmg3twddd0021jl0gesepxuit","description":"Disposable probe entity for contract validation.","name":"probe-step13-20260420T144536Z-control-no-mech","type":"weapon"}`
  - Payload B (`typed_object`): `{"campaign_id":"cmg3twddd0021jl0gesepxuit","description":"Disposable probe entity for contract validation.","mechanics":{"attunement":false,"damage":"1d8 slashing","mastery":"Sap","notes":"Probe typed payload.","properties":["versatile (1d10)"],"rarity":"rare"},"name":"probe-step13-20260420T144536Z-mech-typed","type":"weapon"}`
  - Payload C (`loose_object`): `{"campaign_id":"cmg3twddd0021jl0gesepxuit","description":"Disposable probe entity for contract validation.","mechanics":{"active":true,"charges":3,"custom_field":{"nested":[1,2,3]},"free_text":"Probe loose payload."},"name":"probe-step13-20260420T144536Z-mech-loose","type":"weapon"}`
  - Payload D (`invalid_scalar`): `{"campaign_id":"cmg3twddd0021jl0gesepxuit","description":"Disposable probe entity for contract validation.","mechanics":"invalid_scalar_payload","name":"probe-step13-20260420T144536Z-mech-invalid-scalar","type":"weapon"}`
- **Upstream responses:**
  - Payload A -> HTTP 200.
  - Payload B -> HTTP 200.
  - Payload C -> HTTP 200.
  - Payload D -> HTTP 200.
- **Accepted wire format / shape:** Archivist currently accepts object and scalar-string `mechanics` payloads for item creation.
- **Validator decision:** Accept `mechanics` as an unconstrained JSON value in the client boundary for compatibility, and compute `mechanics_signature` from canonical JSON serialization regardless of structure.
- **Commit:** Pending (set to the implementation commit SHA that locks this validation decision).

Probe artifact references:
- `scripts/probe-results/contract_probe_20260420T144536Z.json`
- `scripts/probe-results/contract_probe_20260420T144536Z.md`

Every probe that closes an Open Question gets one entry here using the template below. Each entry is **auditable evidence**: what was sent, what came back, and the decision that was baked into the code. This converts step 13 from "remember to paste results back" into a structured closure with a defined shape.

**Entry template:**

```
### Probe: <question title>

- **Date:** YYYY-MM-DD
- **Closes:** Open Question #<n>
- **Tested payloads:**
  - Payload A: <exact JSON sent>
  - Payload B: <exact JSON sent>
  - …
- **Upstream responses:**
  - Payload A → HTTP <status>, body excerpt: `…`
  - Payload B → HTTP <status>, body excerpt: `…`
- **Accepted wire format / shape:** <the answer>
- **Validator decision:** <what was baked into `validation.py` / `models.py` / a mapping table>
- **Commit:** <git SHA of the code change that locked the decision>
```

First probes expected: `Item.type` wire format for multi-word values; `mechanics` payload accepted shape. (Completed in `contract_probe_20260420T144536Z`.)

## Build order

Status: **✓ done**, **~ partial**, **◯ planned**.

Every step lists its own `Tests:` acceptance gate. A step is not "done" until those tests pass alongside the code they verify. Tests are written with the step, never deferred to a later phase.

1. **✓** Project skeleton + `client.py` + `config.py` + `health_check` tool. Smoke-test against the real API.
   - **Tests:** `health_check` returns `title="Archivist MCP"` and reports live connectivity; smoke test executes against the real API.
2. **✓** Granular resources. The original composite `archivist://session/{id}` has been dissolved into single-responsibility URIs: `campaign`, `campaign/stats`, `campaign/links`; `sessions`, `session/{id}`, `session/{id}/beats`, `session/{id}/moments`, `session/{id}/cast-analysis`; `beats`, `beat/{id}`; `moments`, `moment/{id}`; `quests`, `quest/{id}`; `characters`, `character/{id}`; `items`, `item/{id}`; `factions`, `faction/{id}`; `locations`, `location/{id}`; `journals`, `journal/{id}`; `journal-folders`, `journal-folder/{id}`. `archivist://campaigns` was removed (single-campaign servers don't enumerate campaigns; discovery belongs in a setup helper, not the running MCP surface). Test scaffolding (`pytest-httpx` wiring in `conftest.py`, fixture directory layout under `tests/fixtures/`, first scrubbed fixtures per entity kind) landed with this step so every subsequent step has a home for its tests.
   - **Tests:** each resource returns the expected shape on a recorded fixture and surfaces a 404 for unknown IDs; absence test confirms `archivist://campaigns` is unregistered; `conftest.py` fixtures load cleanly; at least one fixture exists per entity kind touched in this step.
3. **✓** Slim-list field projection (`projections.py`). One `project_slim(entity, kind)` function per entity kind, matching the per-entity projections in the Resources section. Includes the derivations (`is_player`, `has_speaker`, `completion_pct`, `is_root`, `has_summary`, `summary_length`, `content_excerpt`, `has_mechanics`). Measure before/after token cost on a real campaign and record it in the PR description.
   - **Tests:** `project_slim` unit test per entity kind covering shape, included/excluded keys, and each derivation's truthy + edge cases (e.g. `completion_pct` at 0/50/100; `has_summary` with empty string vs. whitespace vs. real content). Token-cost delta recorded in the PR body.
4. **✓** Pagination passthrough. List resources accept `page`, `page_size`, and `cursor` parameters and forward them to `client.get`. Default `page_size=50`; cap at 50 server-side. Document the params in each list resource's docstring. Verify in Claude Desktop that fetching page 2 works.
   - **Tests:** params forwarded verbatim via `httpx` mock assertions; `page_size` above 50 is clamped; `cursor` round-trips; end-to-end manual verification in Claude Desktop noted in PR.
5. **✓** `validation.py` — Pydantic `Annotated[..., Field(description=...)]` wrappers, size caps (50 KB `content`, 1 KB names/titles, 32 tags max), UUID-format check for path IDs. Every tool signature picks its types from here. **Type decisions locked by step 13 probe:** `Item.type` is an `Enum` whose `.value` is the canonical space-form string (`"wondrous item"`, not `"wondrous_item"`); serializer emits `.value`. `mechanics` is typed as `dict[str, Any] | None` — the probe showed Archivist accepts bare scalars (e.g. a plain string), but we reject them at our boundary to prevent garbage from reaching RAG. 16 KB cap on canonical-JSON serialization of the dict, consistent with the size caps above.
   - **Tests:** each cap rejects with `ValidationError` at the boundary; UUID validator accepts canonical form and rejects garbage; `Item.type` enum serializes to the canonical space form on `.model_dump()`; `mechanics` rejects a bare string/int/list but accepts `dict[str, Any]` and `None`; 16 KB mechanics cap triggers on canonical-JSON length, not raw-dict size.
6. **✓** `cache.py` + `concurrency.py` — TTL cache (60 s lists, 5 min details), URI-prefix invalidation, per-URI single-flight read lock, global write lock. `client.py` is rewired to read through the cache and retry policy.
   - **Tests:** cache hit/miss; TTL expiry (freezegun); URI-prefix invalidation under overlapping prefixes; manual invalidation vs. automatic TTL; single-flight — two concurrent cold reads of the same URI produce exactly one upstream call; global write lock serializes two concurrent writes; write-during-read ordering preserved.
7. **✓** Retry policy in `client.py` — exponential backoff + jitter on `GET` (2 retries, only on 429/5xx). Fail-fast on writes. Errors surface as MCP tool errors with correlation IDs.
   - **Tests:** 429 and 5xx injection each trigger 2 retries with backoff (jitter stubbed deterministic); exhaustion surfaces an error carrying a correlation ID; non-retryable 4xx (e.g. 400, 404) surfaces immediately; writes (POST/PATCH/DELETE) never retry, even on 5xx.
8. **✓** `logging_.py` — structured JSON logs to stderr, level from `ARCHIVIST_LOG_LEVEL`, event schema per Observability. API key masking, campaign ID masking.
   - **Tests:** every emitted log line parses as JSON; API key is masked in every event (including errors); campaign ID is masked; `ARCHIVIST_LOG_LEVEL` is respected; event schema matches the Observability section's shape.
9. **✓** `search_entities(query, types?, filters?)` tool — lexical search with typed filters, slim-shape results. The discovery surface; required before heavy workflow tools that would otherwise enumerate lists.
   - **Tests:** `types` filter narrows results to the requested kinds; filter combinations AND correctly; empty-result path returns `[]`, not an error; invalid filter is rejected with a clear validation error; results are slim-shape (verified against `project_slim` output).
10. **✓** `ask_archivist` tool with MCP progress-notification streaming when the client supplies a progress token. Return value includes assembled `answer` (chunked `text/plain` body) and `tokens` with snake_case budget keys from response headers; JSON-shaped stream lines can override token fields.
    - **Tests:** progress notifications emitted in order during a mocked stream; the final returned string equals the concatenation of streamed chunks; token-budget fields present under snake_case keys (header path + invalid-header skip); upstream mid-stream error surfaces as an MCP tool error with a correlation ID; client cancellation is honored (no further chunks after cancel).
11. **◯** `draft_session_summary` + `commit_session_summary`. Archive-first commit logic (`Summary History/` upsert, then PATCH, no rollback).
    - **Tests:** `draft_*` returns the candidate with no side effects (no HTTP writes observed); `commit_*` archives first, then PATCHes; equality guard — whitespace-normalized content that matches the current summary short-circuits to a no-op (no archive, no PATCH); injected PATCH failure after successful archive produces the documented orphan-report error payload and logs the `commit.partial_failure` event; end-to-end happy path on a recorded fixture.
12. **◯** Campaign summary tools (`draft_campaign_summary`, `commit_campaign_summary`).
    - **Tests:** mirror step 11 — draft purity, archive-first commit, equality guard, PATCH-failure orphan reporting.
13. **✓** `scripts/probe_contracts.py` — contract probe against a live campaign that exercises the write paths whose shapes were Open Questions: `Item.type` wire format for multi-word enum values, and the accepted shape of the `mechanics` payload in Items. Ran 2026-04-20 as `contract_probe_20260420T144536Z`; artifacts at `scripts/probe-results/contract_probe_20260420T144536Z.{json,md}`. Results recorded in the **Contract probe results** section; Open Questions 2 and 3 closed. **Validator decisions baked in:** (a) `Item.type` — send canonical `"wondrous item"` (space form) on write, accept any variant on read; (b) `mechanics` — treat as unconstrained JSON at the API boundary; `mechanics_signature` is SHA-256 over canonical JSON serialization regardless of structure. See step 5 for how these decisions flow into `validation.py`.
    - **Tests:** `--dry-run` path validates the matrix + report generation without network calls; probe artifact JSON validates against its schema; probe Markdown renders without template errors.
14. **◯** `upsert_journal_entry`, then `register_item` / `promote_item_to_homebrew`. Auto-creates the mechanics folder on first use. **`Item.type` is sent in the canonical space form** (`"wondrous item"`, etc.) per step 13's probe decision; the mapping lives in `validation.py`. Natural-key idempotency per the *Idempotency* section: `register_item` with a `mechanics` payload dedupes on `(name, mechanics_signature)` and returns the existing item with `already_exists=true` only when both match; narrative-only registrations (no `mechanics`) always create a new item so legitimate story duplicates (e.g. two Sending Stones) remain distinct.
    - **Tests:** `upsert_journal_entry` creates-then-updates the same key without duplication; mechanics folder is auto-created on first item registration with mechanics; `register_item` with mechanics returns the same item with `already_exists=true` when `(name, mechanics_signature)` matches; `register_item` with a different mechanics payload for the same name creates a new item; narrative-only `register_item` always creates, even with a duplicate name; `Item.type` goes out on the wire as canonical space form (verified via `httpx` mock body assertion); `promote_item_to_homebrew` moves the journal entry and updates the item type.
15. **◯** `link_entities` tool. Dedupes on `(from_id, from_type, to_id, to_type)`.
    - **Tests:** first call creates the link; second call with identical tuple returns `already_exists=true` and the existing link; tuples differing in any field create a new link.
16. **◯** Prompts — all ten from the table above.
    - **Tests:** each prompt renders with a representative argument set and produces non-empty output; required arguments surface a clear error when missing; optional arguments default as documented.
17. **◯** Packaging (no PyPI publish yet) — `uvx`-ready packaging, console-script entry point, credentials-file fallback, README with MCP config snippets for both Claude Desktop and Claude Code. During build steps 17–19 users install via `uvx --from git+https://...`; this proves the install flow end-to-end without burning a PyPI version. Includes credential hardening: startup permission check on `credentials.toml` (warn if world-readable on Unix; warn if non-owner ACLs grant read on Windows), README section on rotation (edit the file / swap the env var, restart the server).
    - **Tests:** credential loader reads from the fallback path when env vars absent; env vars take precedence over the file; world-readable `credentials.toml` on Unix emits the documented warning (not an error) at startup; Windows permission check runs without raising on a normal user profile; `uvx --from git+https://<local-path-or-url> archivist-mcp --help` runs in a clean temp environment.
18. **~** Fixture maintenance tooling — `scripts/record_fixtures.py` (with content-scrub pass) and `scripts/check_fixture_drift.py`. These are operator scripts that keep the fixtures recorded in steps 1–17 aligned with the live API; they do not add new behavior tests. `record_fixtures.py` shipped with Chunk 1; `check_fixture_drift.py` remains planned for Chunk 6.
    - **Tests:** `record_fixtures.py` writes files containing no API key, no raw campaign ID, and no un-scrubbed user content (verified via regex scan on a recorded sample); `check_fixture_drift.py` returns non-zero and names the affected file when a recorded fixture's shape differs from a mocked "live" response; both scripts are idempotent on a clean tree.
19. **◯** Polish: README with end-to-end examples, rename-handling open question closure.
    - **Tests:** the end-to-end example commands execute in a throwaway environment (or are explicitly marked as manual-only in the README); rename-handling decision is recorded in the Decisions table with a test pinning the chosen behavior.
20. **◯** PyPI publish — cut `0.1.0`, publish `archivist-mcp` to PyPI, flip the README install instruction from the git URL form to the plain `uvx archivist-mcp` form. Deliberately the final step so every earlier rough edge is already filed off before a version gets pinned in the wild.
    - **Tests:** `uvx archivist-mcp --help` works against the published artifact in a clean temp environment; `pip install archivist-mcp==0.1.0` succeeds on a supported Python version; version metadata in `pyproject.toml` matches the published tag.

Steps 3–8 are the operational foundation (projections, validation, cache, concurrency, retries, logging). They must land before any heavy tool work (steps 9+); building tools on top of unbounded list resources or an uncached client invites rework. Step 13 (contract probes) is deliberately a dedicated gate before Item-path work — the wire-format questions are cheap to answer with a real request but expensive to guess wrong. **Testing is built alongside every step, not deferred.** Each step's `Tests:` bullet is its acceptance gate. Step 18 exists only for fixture maintenance tooling (record + drift-check), which supports the tests written in steps 1–17 rather than replacing them. Step 20 (PyPI publish) is intentionally the very last step so every rough edge is filed off before a version number gets pinned in the wild; steps 17–19 run against a git-URL install, which proves the packaging without burning a version.
