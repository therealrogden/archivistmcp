Archivist Developer Docs
Build on the Archivist platform. This guide covers authentication, key concepts, and common workflows.

Quick Start
Make your first request in minutes.
Authentication
Use your API key with headers.
API Reference
Endpoints, parameters, and responses.
Quick Start

Sign in to Archivist and create an API key in Account Settings → API Keys.
Save your key securely as an environment variable.
Ping the health endpoint to verify connectivity.
curl https://api.myarchivist.ai/health
Expected response:
{
  "status": "healthy",
  "service": "archivist-api",
  "version": "1.0.0",
  "environment": "production",
  "port": 8000,
  "timestamp": "2025-01-15T10:30:00.123456Z"
}
Authentication

Send your API key with every request using the x-api-key header.

curl -H "x-api-key: YOUR_API_KEY" https://api.myarchivist.ai/v1/campaigns
Do not embed keys in client-side code. Rotate compromised keys immediately.
Core Concepts

Campaign — The top-level container for your game world. All data (characters, sessions, quests, beats, moments, factions, locations, items) is scoped to a single campaign. API-created campaigns/worlds are bootstrapped with the owner as player/admin, a default GM speaker, Character Arc defaults, and default compendium field definitions.

Session — A play event in time (e.g., a table session, Discord call, play‑by‑post thread, or audio upload). Sessions have a session_date, optional title/summary, and are the primary anchor for time‑based content.

Cast Analysis — Structured analytics generated from a session transcript (talk share, pacing, dominance, questions, etc.). Stored per session and retrievable via the Cast Analysis endpoint.

Beat — A narrative unit that structures a session or storyline. Beats are hierarchical and ordered (type: "major" | "minor" | "step") with optional parent_id and index. Use beats to outline arcs and attach summaries, decisions, and consequences.

Moment — A granular highlight or quote captured during play. Moments are lightweight, optionally linked to a session, and ideal for memorable lines, rulings, or callbacks.

Character — A person in the world. Can be a PC, NPC, or other subtype. Characters support alias lists, optional backstory, and speaker_id linkage. The legacy player_name field is deprecated; responses may also include a nullable, read-only player object sourced from the linked Speaker record.

Faction — An organization or group (guilds, cults, companies). Useful for tracking influence, relationships, and agendas.

Location — A place in the world, optionally hierarchical via parent_id (e.g., City → District → Tavern).

Item — A notable object (weapons, artifacts, clues) with optional type and description.

Quest — A canonical quest-log entry for a campaign. Quests track a name, optional quest giver, category, status, structured objectives, narrative progress, and related compendium entities. The public API exposes the persisted quest state directly; session-by-session reconciliation remains an internal Archivist workflow.

Link — A relationship between two entities (Character, Faction, Location, Item, Beat, etc.) with optional alias/label. Link create/update normalizes aliases and validates that both records exist in the same campaign. Links power Archivist's wikilinks and graph views.

Journal Entries — Rich, permissioned campaign notes stored per campaign. Entries support Lexical JSON plus extracted plain text, are chunked/embedded, and are included in RAG retrieval for the Ask endpoint. When both content and content_rich are supplied, rich content is canonical. Creator manage permission is granted automatically, while other users require public visibility or explicit shares. Limits: 50,000 tokens per entry and 1,000,000 tokens per world.

Journal Folders — Hierarchical containers for journal entries. Folders include id, name, path, parent_id, and position for tree rendering.

Ask (RAG) — Question‑answering over your campaign's knowledge base. Send chat messages and optionally stream responses. Retrieval includes characters, beats, moments, sessions, and journal entries.
Data Models

Representative TypeScript interfaces for common resources. Fields may be extended over time; unknown fields should be ignored by clients.

// Common primitives
export type ID = string; // stable, opaque identifier
export type ISODate = string; // ISO 8601 timestamp

// Campaign
export interface Campaign {
  id: ID;
  title: string;
  description?: string;
  system?: string; // e.g., "D&D 5e"
  public: boolean;
  created_at: ISODate;
}

// Session
export type SessionType = 'audioUpload' | 'playByPost' | 'discordVoice' | 'other';
export interface GameSession {
  id: ID;
  campaign_id: ID;
  type: SessionType;
  title?: string;
  summary?: string;
  session_date?: ISODate;
  public: boolean;
  created_at: ISODate;
}

// Beat
export type BeatType = 'major' | 'minor' | 'step';
export interface Beat {
  id: ID;
  campaign_id: ID;
  game_session_id?: ID;
  label: string;
  type: BeatType;
  description?: string;
  index?: number; // ordering among siblings
  parent_id?: ID; // hierarchy (minor/step under a major or parent)
  created_at: ISODate;
}

// Moment
export interface Moment {
  id: ID;
  campaign_id: ID;
  session_id?: ID;
  label: string;
  content?: string; // rich text with optional wikilinks
  created_at: ISODate;
}

// Character
export type CharacterType = 'PC' | 'NPC' | 'Other';
export interface CharacterPlayer {
  id: ID;
  name?: string;
  handle?: string;
  roles: string[];
  campaign_id: ID;
  created_at: ISODate;
}

export interface Character {
  id: ID;
  campaign_id: ID;
  character_name: string;
  character_aliases: string[];
  player_name?: string; // deprecated legacy field; often null
  player?: CharacterPlayer | null; // response-only Speaker summary
  description?: string;
  backstory?: string;
  speaker_id?: ID | null;
  type?: CharacterType;
  image?: string; // HTTPS URL, max 2048 chars
  approved: boolean;
  created_at: ISODate;
}

// Faction
export interface Faction {
  id: ID;
  campaign_id: ID;
  name: string;
  description?: string;
  type?: string;
  image?: string; // HTTPS URL, max 2048 chars
  created_at: ISODate;
}

// Location
export interface Location {
  id: ID;
  campaign_id: ID;
  name: string;
  description?: string;
  type?: string;
  parent_id?: ID;
  image?: string; // HTTPS URL, max 2048 chars
  created_at: ISODate;
}

// Item
export interface Item {
  id: ID;
  campaign_id: ID;
  name: string;
  description?: string;
  type?: string;
  image?: string; // HTTPS URL, max 2048 chars
  created_at: ISODate;
}

// Quest
export type QuestCategory = 'main' | 'side' | 'faction' | 'personal' | 'n/a';
export type QuestStatus = 'planned' | 'in-progress' | 'blocked' | 'failed' | 'done' | 'n/a';
export type ObjectiveStatus = 'pending' | 'in-progress' | 'completed' | 'failed' | 'blocked';
export type QuestEntityType = 'character' | 'faction' | 'location' | 'item';

export interface QuestObjective {
  id: ID;
  text: string;
  status: ObjectiveStatus;
  order: number;
}

export interface QuestProgressEntry {
  id: ID;
  text: string;
  order: number;
  session_id?: ID | null;
  session_number?: number | null;
  session_title?: string | null;
  session_date?: ISODate | null;
}

export interface QuestRelatedEntityRef {
  id: ID;
  entity_type: QuestEntityType;
  entity_id?: ID | null;
  entity_name_snapshot?: string | null;
  label?: string | null;
  order: number;
}

export interface QuestSessionRef {
  id: ID;
  number?: number | null;
  title?: string | null;
  session_date?: ISODate | null;
}

export interface Quest {
  id: ID;
  campaign_id: ID;
  order_index: number;
  quest_name: string;
  quest_giver?: string | null;
  quest_giver_id?: ID | null; // resolved Character/Faction id when available
  quest_category: QuestCategory;
  status: QuestStatus;
  success_definition?: string | null;
  failure_conditions?: string | null;
  next_action?: string | null;
  resolution?: string | null;
  objectives: QuestObjective[];
  progress_log: string[];
  progress_log_entries: QuestProgressEntry[];
  related_characters: string[];
  related_factions: string[];
  related_locations: string[];
  related_items: string[];
  related_entity_refs: QuestRelatedEntityRef[];
  first_session?: QuestSessionRef | null;
  last_session?: QuestSessionRef | null;
  created_at: ISODate;
  updated_at?: ISODate | null;
}

// Link (relationship)
export type EntityType = 'Character' | 'Faction' | 'Location' | 'Item' | 'Beat' | 'Moment';
export interface Link {
  id: ID;
  campaign_id: ID;
  from_id: ID;
  from_type: EntityType;
  to_id: ID;
  to_type: EntityType;
  alias?: string; // label shown in UI
  created_at: ISODate;
}

// Journal Entry
export interface JournalEntry {
  id: ID;
  world_id: ID; // campaign ID
  title: string;
  summary?: string;
  content: string; // plain text content
  content_rich?: unknown; // Lexical editor state JSON
  content_metadata?: unknown;
  tags: string[];
  token_count: number; // read-only
  cover_image?: string;
  is_pinned?: boolean;
  is_public: boolean;
  status: 'draft' | 'published' | 'archived';
  published_at?: ISODate;
  archived_at?: ISODate;
  folder_id?: ID;
  permission_level?: 'view' | 'comment' | 'edit' | 'manage';
  created_at: ISODate;
  updated_at?: ISODate;
}

// Journal Folder
export interface JournalFolder {
  id: ID;
  world_id: ID; // campaign ID
  parent_id?: ID;
  name: string;
  path: string;
  description?: string;
  position: number;
  metadata?: unknown;
  created_at: ISODate;
  updated_at?: ISODate;
}

// Ask (RAG)
export interface ChatMessage { role: 'system' | 'user' | 'assistant'; content: string; }
export interface AskRequest { campaign_id: ID; messages: ChatMessage[]; stream?: boolean; }
export interface AskChunk { id: string; type: 'delta' | 'done'; content?: string; }
Conventions

Base URL: https://api.myarchivist.ai
Authentication: All endpoints require x-api-key unless otherwise noted.
Pagination: list endpoints accept page and size. The default size is server‑defined; clients should not assume a maximum.
Timestamps: All dates are returned in ISO 8601 (UTC). Client UIs should localize for display.
Idempotency: POST generally creates, PATCH updates via JSON Merge Patch where specified.
Errors: Error responses use FastAPI-style JSON bodies with a top-level detail field.
Filtering: Most list endpoints support simple filters (e.g., campaign_id, search, character_type).
Image URLs: The image field for Characters, Items, Factions, and Locations must be an HTTPS URL (max 2048 characters). HTTP URLs are rejected with a validation error.
Read-Only Properties

Certain properties are system-managed and cannot be set through POST or PATCH requests. These fields appear in GET responses but are ignored if included in create/update operations.

Campaigns: public, archived, created_at
Sessions: public, created_at
Characters: approved, created_at
Locations, Factions, Items: pending, approved, created_at
All entities: id, created_at
These properties are managed by the system based on application logic, user permissions, and moderation workflows.
Wikilinks & Relationships

Archivist supports lightweight internal links ("wikilinks") between entities and text fields. When fetching resources you can preserve this markup by passing with_links=true on supported endpoints.

Creating or updating compendium records and journal entries will sync wikilinks automatically from the saved content. Use the Links endpoints when you need to create or update graph relationships directly; link aliases are normalized and deduped server-side.
Typical Workflow

A simple sequence: create a campaign, rely on bootstrap defaults, add a character, then list sessions.

API_KEY="your-api-key"
BASE_URL="https://api.myarchivist.ai"

# 1) Create a campaign
curl -s -X POST \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My First API Campaign",
    "description": "Created via API",
    "system": "D&D 5e"
  }' \
  "$BASE_URL/v1/campaigns"
