# Feature Ideas — ha-litellm-conversation

Original research 2026-06-26; pruned 2026-07-13 after v1.4.x shipped most of
Tier 1/2. Shipped or rejected items are dropped — see NEXT_STEPS.md for the
live roadmap and git history (`git log --follow FEATURE_IDEAS.md`) for the
full original research notes.

## Remaining ideas

### Custom System Prompt Templates with HA Variables

The prompt field is already a `TemplateSelector`, so Jinja works today.
The idea beyond that: shipped prompt presets (persona library), and
documented recipes for injecting entity/area state into the prompt.

### Multi-Agent Routing

A lightweight classifier step routing to different models per request
(cheap model for device control, big model for reasoning). LiteLLM's
server-side routing covers most of this — only worth doing client-side if
routing needs HA context (e.g. route by area or user).

### Streaming TTS (Realtime API)

Blocked on LiteLLM's realtime/websocket support maturing. Re-check
periodically; the current chunked `/v1/audio/speech` path is fine for
voice-assistant response lengths.

### Prompt Caching / Cache Hit Indicator

Surface LiteLLM cache metadata (`cache_hit`, cached token counts) as a
diagnostic attribute or debug log. Small; mostly waiting on a real need.

## Decided / historical

- **Extended tools, web search, STT, TTS, usage sensors, guardrails**: shipped (v1.2–v1.4).
- **Long-term memory (tools + todo UI + services)**: shipped (v1.5.0).
- **Dreaming (background consolidation, transcript buffer, blueprint)**: shipped (v1.6.x).
- **AI Task attachments / vision, camera-calendar-todo tools**: shipped (v1.4.0).
- **Code interpreter**: rejected — Responses-API-only; repo uses Chat Completions for Bedrock.
- **Model fallback**: rejected client-side — the LiteLLM proxy handles routing/fallback server-side.
- **MCP passthrough**: needs no code — works via HA's MCP integration + the LLM API selector.
