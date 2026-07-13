# Dreaming Layer (Background Memory Consolidation) — Design, v1.6.0

**Goal:** Background memory formation ("dreaming") that analyzes conversations
and household activity, then consolidates durable facts into the existing
MemoryStore — scheduled, observed, and controlled entirely through native HA
patterns (automations, entities, events, services).

**Philosophy:** The integration provides the *capability* (an AI Task-style
entity + service that dreams once when told to). HA provides the *policy*
(when to dream, what to feed it, what to do afterward) via user automations.
We don't build a scheduler — HA **is** the scheduler.

---

## Architecture

```
┌─ capture (passive, always on) ─────────────────────────────┐
│ conversation turns → rolling TranscriptBuffer (Store-backed│
│ ring buffer, 7 days / 200 exchanges cap, local only)       │
└────────────────────────────────────────────────────────────┘
                          │
     automation fires litellm_conversation.dream (e.g. 3am)
                          │
┌─ dream (one LLM call) ─────────────────────────────────────┐
│ prompt = current memories + transcripts since last dream   │
│          [+ optional logbook activity summary]             │
│ response_format = json_schema (add/update/delete ops)      │
└────────────────────────────────────────────────────────────┘
                          │
        apply ops to MemoryStore (same caps/dedup as v1.5)
                          │
┌─ observe (native HA surfaces) ─────────────────────────────┐
│ • todo.*_memories updates live (existing entity)           │
│ • sensor.*_last_dream + attributes (ops applied, tokens)   │
│ • event litellm_conversation_dream_completed on the bus    │
│   → user automations can notify: "Nova learned 3 things"   │
└────────────────────────────────────────────────────────────┘
```

## Components

### 1. TranscriptBuffer (`memory.py` addition or `transcripts.py`)

- Captured at the end of `_async_handle_chat_log` for **conversation**
  entities only (not AI Task — task runs are machine-generated, low signal,
  and would pollute dreams with camera-check noise).
- Ring buffer in a second `Store` (`litellm_conversation.transcripts`):
  `[{when, conversation_id, role, text}]`, capped at 200 user/assistant
  exchanges AND 7 days (whichever trims first). Tool-call internals are NOT
  captured — only user text + final assistant text (privacy + token size).
- **Off by default?** No — on by default with README disclosure, because
  the todo-UI already establishes "the assistant keeps data locally", and
  an off-by-default buffer means first dream = empty = broken first
  impression. Opt-out: a `switch`-less minimal approach — document
  `litellm_conversation.forget_transcripts` service + buffer auto-trims.
  (Revisit if anyone objects; Edgar approved capture in this design.)

### 2. The dream operation (`dreaming.py`)

One LLM call per dream (NOT per conversation):

- **Input assembly:**
  - Current memory list (id + text) — this is what solves dedup/contradiction
  - Transcripts since `last_dream_at` watermark (from the buffer)
  - Optional: logbook activity digest (see §4) when `include_activity: true`
- **Model:** the entry's first `ai_task_data` subentry model, overridable
  per-call via service field `model:` — cheap Haiku for nightly dreams.
- **Structured output** (existing `response_format` machinery, selector
  schema): `{operations: [{op: add|update|delete, id?, text?, reason}]}`
- **Prompt rules (the important part):**
  - Only durable facts: preferences, corrections, recurring patterns,
    household facts. Never transient state ("lights are on"), never
    secrets/codes, never speculation.
  - Prefer UPDATE over ADD when a memory on the same subject exists.
  - CONSOLIDATE: merge redundant memories.
  - DELETE contradicted/stale memories (cite which transcript contradicts).
  - Empty operations list is a valid, expected outcome.
- **Apply:** ops run through MemoryStore (existing caps enforced — a dream
  can never blow past 50×300). Per-op failures logged, not fatal.
- **Watermark:** `last_dream_at` stored alongside the buffer; dream only
  reads newer transcripts, so daily dreams don't re-analyze old material.

### 3. HA-native control surface

- **Service `litellm_conversation.dream`** (registered like remember/forget):
  fields `include_activity: bool = false`, `model: str?` (optional override),
  `dry_run: bool = false` (returns ops WITHOUT applying — lets cautious users
  wire a notify-and-confirm automation). Returns response data:
  `{added: n, updated: n, deleted: n, operations: [...], tokens: n}`.
- **Scheduling = user automation** (documented in README, not shipped code):
  ```yaml
  automation:
    - alias: "Nightly dreaming"
      triggers: [{trigger: time, at: "03:00:00"}]
      actions:
        - action: litellm_conversation.dream
          data: {include_activity: true}
  ```
- **Event `litellm_conversation_dream_completed`** fired on the bus with the
  same summary payload → automations can notify ("Nova consolidated 3
  memories"), or chain (dry-run review flows).
- **`sensor.*_last_dream`** (timestamp device class, diagnostic category,
  attributes: added/updated/deleted counts, token usage, transcript count).
  Feeds the existing usage sensors too (dream tokens are usage).

### 4. Activity ingestion (the "activity tab")

The logbook's `EventProcessor` (verified API) gives exactly what the UI's
activity feed shows. But raw logbook is firehose noise (every state change).
Design:

- `include_activity: true` pulls logbook events for the dream window,
  **filtered to high-signal domains** (automation triggers, script runs,
  person/zone changes, lock/alarm/cover actions — not every light toggle),
  capped at ~300 events, rendered as a compact text digest.
- Purpose: teaches dreams *household rhythm* facts ("garage door often left
  open evenings", "Maria arrives ~17:30 weekdays") that conversations never
  mention.
- v1.6.0 ships it behind the service flag (default false) — conversations
  are the proven-value input; activity is the experiment. Promote later if
  dreams from it are good.

## What we deliberately do NOT build

- **No built-in scheduler** (no config-flow "dream time" option) — HA
  automations are strictly more flexible and it's the pattern-native answer.
- **No embeddings/RAG** — 50-memory scale doesn't need retrieval.
- **No per-user profiles** (LangMem-style) — HA voice doesn't reliably
  attribute speakers; household-level memory matches reality here. Revisit
  if HA voice grows speaker ID.
- **No automatic post-conversation extraction** (per-conversation LLM calls)
  — that's the expensive design dreaming exists to avoid.

## Failure/edge behavior

- No new transcripts since watermark → dream returns `{added: 0, ...}`
  without an LLM call (cheap no-op; automations can run unconditionally).
- LLM/JSON failure → `HomeAssistantError` from the service (visible in
  automation traces), watermark NOT advanced (next dream retries the window).
- HA restart mid-buffer → Store-backed, survives.

## Task breakdown (build order)

1. TranscriptBuffer + capture hook in `_async_handle_chat_log` (conversation
   subentries only) + tests (ring trim, watermark, restart survival)
2. Dream prompt builder + ops schema + apply logic (pure functions) + tests
   (dedup-update, delete-contradiction, cap enforcement, malformed ops)
3. `dream` service + dry_run + event firing + tests
4. `sensor.*_last_dream` + usage-sensor feed + tests
5. Activity digest (logbook EventProcessor, domain filter) + tests
6. README (Dreaming section: how it works, automation recipes incl. dry-run
   review flow, privacy note on the transcript buffer) + release v1.6.0

Estimated: comparable to v1.5.0 (one long session).

## Open questions for Edgar

1. Transcript capture on-by-default (with README disclosure + trim service) — OK?
2. Dream model default: first ai_task subentry's model, or hardcode suggest-Haiku in docs and leave model unset = conversation model?
3. Ship a blueprint (easy import for the nightly automation) or README YAML only?
