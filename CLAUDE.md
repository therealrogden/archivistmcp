# CLAUDE.md — Archivist MCP, orientation for agents

You are opening a Python MCP server that wraps the Archivist D&D campaign API
(`api.myarchivist.ai`). It exposes resources, tools, and prompts so a DM can
drive campaign-authoring workflows from Claude Desktop / Claude Code over
stdio. Single process, single API key, single campaign. Read this file
top-to-bottom once, then grep it on demand.

---

## Source-of-truth map

When in doubt, consult in this order:

- **`DESIGN.md`** — product and system design. The **Decisions** table
  (`DESIGN.md:16-44`) and **Build order** (`DESIGN.md:639-686`) are
  authoritative. If a topic is explained there, link from your work; do not
  re-explain it here or in commit messages.
- **`ArchivistAPIReference.md.txt`** — hand-written prose for the upstream
  REST API. Can drift. When it disagrees with a recorded fixture, trust the
  fixture.
- **`tests/fixtures/<entity>/<shape>.json`** — real API output, scrubbed via
  `scripts/record_fixtures.py`. Authoritative for field shape and casing.
- **`scripts/probe_contracts.py` + `scripts/probe-results/`** — auditable
  evidence for wire-format Open Questions. Results recorded in
  `DESIGN.md` "Contract probe results" (`DESIGN.md:~559-635`).
- **`docs/internal/claude-md-material.md`** — historical brainstorm scratch.
  Do not edit; it's a frozen artifact. This file is its synthesis.

---

## How this codebase is organized

```
src/archivist_mcp/
  server.py            FastMCP app wiring — tool/resource registration
  client.py            HTTP client: retries, cache integration, logging
  cache.py             TTL cache (60s lists, 5min details)
  concurrency.py       Per-URI read single-flight + global write lock
  config.py            Env + credentials.toml fallback
  logging_.py          Structured JSON → stderr, masks secrets
  projections.py       project_slim(entity, kind) — slim list shapes
  validation.py        Pydantic Annotated types, size caps, UUID checks
  resources.py         archivist:// resource URIs
  api_lists.py         Pagination passthrough for list endpoints
  errors.py            MCP error shapes
  journal_folders.py   Mechanics / history folder resolution
  summary_text.py      Summary body helpers
  tools/               One tool module per cohesive concern (~200 lines)
    read_campaign.py   read_character.py   read_faction.py
    read_item.py       read_location.py    read_quest.py
    read_journal.py    read_session.py     reads_helpers.py
    wikilinks.py       search.py           ask.py
    session_summary.py campaign_summary.py
    items.py           journals.py         links.py
tests/                 pytest, pytest-httpx; mirrors src layout
tests/fixtures/        scrubbed recordings
scripts/               record_fixtures.py, probe_contracts.py
DESIGN.md              product/system design — authoritative
```

**Tool module sizing.** Flat layout under `tools/` (no subpackages). Target
~200 lines; split at 300+. Group by cohesion: hub entities with diverging
fanout semantics (character, faction, location, item, quest) each get their
own `read_<entity>.py`; session-scoped reads (session, beats, moments)
cluster in `read_session.py`; shared scaffolding lives in
`reads_helpers.py`.

---

## Workflow conventions

### The summary workflow is `read_* → discuss → validate → commit`

1. Pull grounding context through the layered `read_*` tools.
2. Discuss in chat with the DM — tone, emphasis, what to link.
3. Call `validate_wikilinks(content)` before any commit.
4. Commit via `commit_session_summary` or `commit_campaign_summary`.

There is **no `draft_*` tool** — the old `draft_session_summary` /
`draft_campaign_summary` were removed. See
`src/archivist_mcp/tools/session_summary.py`,
`src/archivist_mcp/tools/campaign_summary.py`.

### Build order is the progress ledger

`DESIGN.md:639-686` lists every step with a **✓ / ~ / ◯** status and a
`Tests:` acceptance gate. Implementing a step means updating code **and**
flipping the status in the same commit.

### Contract-probe workflow (only for Open Questions)

Use probes only to close Open Questions in `DESIGN.md` that require a live
wire-format answer. Everyday "does this filter work?" — use `curl` or an
existing fixture.

1. Add probe to the matrix in `scripts/probe_contracts.py`; run it.
2. Artifacts land at `scripts/probe-results/contract_probe_<ts>.{json,md}`.
3. Record result using the template at `DESIGN.md:~618-634`.
4. Close the Open Question; cite the probe run ID in the validator decision.

### Tests land with the step

Never defer tests. Each build-order step's `Tests:` bullet is its gate;
code without passing tests is not "done".

---

## Rules that prevent common mistakes

### 1. `campaigns[id].description` **is** the long-form overview

There is no separate `overview` field. `PATCH /v1/campaigns/{id}` accepts
`title` and `description` only. Write overview content to `description`.
See `ArchivistAPIReference.md.txt:389-428`,
`src/archivist_mcp/tools/campaign_summary.py:137-161`.

### 2. Journals have four distinct roles — know which you're touching

1. **Mechanics journals** — statblocks paired to Items by `register_item`
   when `mechanics` is passed. Lives under `ARCHIVIST_MECHANICS_FOLDER`
   (default `Items/Mechanics`).
2. **Summary history archives** — prior summaries archived **on overwrite
   only**, never on first commit. Lives under `ARCHIVIST_HISTORY_FOLDER`
   (default `Summary History/`). Tags: `["summary-history", "session"]` or
   `["summary-history", "campaign"]`. Safety net, not primary storage.
3. **Free-form DM lore** — homebrew notes, handouts. Reached via the
   `archivist://journals` resource and `read_journal`.
4. **Campaign Overview journal — gone.** Dead. See rule 1.

See `DESIGN.md:25,26,29`;
`src/archivist_mcp/tools/session_summary.py:146-160`;
`src/archivist_mcp/tools/campaign_summary.py:142-157`.

### 3. Wikilinks are `[[Entity Name]]` and must round-trip

- **Reads** pass `with_links=True` to keep `[[...]]` in response bodies.
  Default for every `read_*` tool. No per-call toggle.
- **Writes** (`commit_session_summary`, `commit_campaign_summary`) pass the
  body verbatim; Archivist resolves links server-side on save
  (`DESIGN.md:~262`).
- **Canonical names only.** Always take entity names from a `read_*`
  response. Never invent or approximate — `[[Obsidian Crown]]` vs
  `[[The Obsidian Crown]]` is a broken link.
- **Rename drift** is an unsolved open question
  (`DESIGN.md:~551`); flag risks rather than working around them.

### 4. `validate_wikilinks` is the pre-commit integrity contract

Returns three buckets: `resolved` (exact single match, keep as-is),
`ambiguous` (exact across multiple entities — DM picks), `unresolved`
(no exact match; fuzzy candidates attached via `search_entities`).

- **Exact match only** for `resolved`. Fuzzy matches are **candidates on
  unresolved**, never auto-promoted. Silent wrong links are worse than no
  links.
- **On commit, strip unresolved links** (write as plain text, drop `[[]]`)
  and report them back to the DM with recommended types. Don't block the
  commit; the DM handles entity creation in the Archivist UI.

See `src/archivist_mcp/tools/wikilinks.py`.

### 5. `search_entities` is lexical, not semantic

Substring / token match. For semantic ("what's the vibe of the Obsidian
Crown") route through `ask_archivist`. Don't use `search_entities` to find
an entity by role or concept. See `DESIGN.md:35,160`;
`src/archivist_mcp/tools/search.py`.

### 6. Live wire and probes beat assumptions; fix fixtures when they drift

Example: `/v1/campaigns/{id}/links` filter params. The reference and server
both require **Title Case** (`Character`, `Location`, `Faction`, `Item`, `Quest`,
`Journal`). Lowercase returns zero results. An older
`tests/fixtures/campaign/links.json` had lowercase; it was wrong. Confirmed via
probe: `docs/internal/wire-audit-probes.md` section 4.

### 7. Resources are user-attached; tools are agent-callable

In current MCP clients you cannot proactively read resources mid-turn. If a
workflow needs **you** to fetch an entity, it needs a **tool** — hence the
`read_*` set. Resources remain valuable for human-curated attachment. Don't
propose removing them. See `DESIGN.md:30,33`.

### 8. Delete dead code when you clarify design

If a branch exists only because the system was previously misunderstood,
delete it. Don't leave "belt-and-suspenders mirror to journal" fallbacks;
they mislead the next agent. The `target="overview"` journal branch was
deleted for exactly this reason.

---

## Anti-patterns — do NOT do these

- **Do not reintroduce `draft_*` tools.** They were removed deliberately.
  Composite fetch was replaced by layered `read_*`; the skeleton return was
  cosmetic. See rule under "Workflow conventions" above.
- **Do not look for or write an `overview` field on campaigns.**
  `description` IS the overview. Rule 1.
- **Do not fuzzy-match to auto-resolve wikilinks.** Fuzzy is a candidate
  surface on `unresolved` only. Rule 4.
- **Do not block a commit on unresolved wikilinks.** Strip and report.
  Rule 4.
- **Do not pass `with_links=False` on read paths by default.** You lose
  `[[]]` markup and your wikilink validation becomes noise. Rule 3.
- **Do not add `campaign_id` to tool signatures.** Single-campaign
  invariant; the server is scoped by env var (`DESIGN.md:70-72`).
- **Do not log to stdout.** Stdout is reserved for the MCP protocol; logs
  go to stderr.
- **Do not retry writes.** GETs retry (429/5xx, 2 tries, jitter); writes
  fail fast. See `DESIGN.md:34`.
- **Do not aggregate multiple pages silently.** List resources return one
  page; pagination is explicit (`DESIGN.md:31`).
- **Do not use `search_entities` for semantic lookup.** Route to
  `ask_archivist`. Rule 5.
- **Do not treat a stale fixture or a single doc as the whole truth over the
  live API.** Re-probe (`docs/internal/wire-audit-probes.md`) and align code and
  committed fixtures. Rule 6.
- **Do not put `ARCHIVIST_CAMPAIGN_ID` in `.env.example`.** Campaign ID
  belongs in per-instance MCP config, not a dev dotfile.
- **Do not write new composite reads into resources.** Composites live in
  tools. `DESIGN.md:33`.

---

## Testing

- **HTTP mocking:** `pytest-httpx`, wired in `tests/conftest.py`.
- **Fixtures:** `tests/fixtures/<entity>/<shape>.json`. Recorded via
  `scripts/record_fixtures.py` with a scrub pass that replaces UUIDs,
  names, timestamps with deterministic fakes. Safe to commit publicly
  (regex scan in the recorder enforces this).
- **Drift check:** `scripts/check_fixture_drift.py` (planned Chunk 6) will
  re-record and shape-diff against committed copies.
- **Test-with-step:** every build-order step ships with its `Tests:` gate.
  No deferrals. See `DESIGN.md:639-686`.
- **Per-module conventions:** one test file per tool module
  (`test_read_session.py`, etc.). Exercise fixtures with regex URL mocks
  when the request path carries UUIDs.

---

## Logging and credentials

### Logging

- Structured JSON, written to **stderr** (stdout = MCP protocol — do not
  break it). Level from `ARCHIVIST_LOG_LEVEL`.
- Event schema at `DESIGN.md:~322-340`. Every tool emits at least an
  invocation event with duration + outcome.
- **API key and campaign ID are masked in every event**, including error
  paths. Do not bypass.
- Code: `src/archivist_mcp/logging_.py`.

### Credentials

- `ARCHIVIST_API_KEY` env var first; fall back to
  `~/.config/archivist-mcp/credentials.toml`.
- `ARCHIVIST_CAMPAIGN_ID` is required.
- Multi-campaign users run **multiple server instances** — one MCP config
  entry per campaign, different env.
- `.env` is a dev convenience for running probes / local work. Production
  reads the process env set by MCP client config.
- Code: `src/archivist_mcp/config.py`; details at `DESIGN.md:~434-453`.

---

## Common gotchas (living section — add as you find them)

- **"Where is the Campaign Overview stored?"** — on `campaigns[id].description`.
  Not in a journal. See rule 1.
- **"Why are my wikilinks not clickable after commit?"** — a read path
  likely dropped `[[]]` markup (missing `with_links=True`) or the write
  path mangled the body. See rule 3; commits should pass content verbatim.
- **"Why does my `from_type=character` filter return zero?"** — the server
  requires Title Case. Send `Character`, `Faction`, and so on on
  `/v1/campaigns/{id}/links`. Rule 6.
- **"Can I just call `search_entities` to find the faction the PCs hate?"**
  — no, it's lexical. Use `ask_archivist`. Rule 5.

Add new entries here whenever a session burns cycles on something a future
agent should catch in seconds.
