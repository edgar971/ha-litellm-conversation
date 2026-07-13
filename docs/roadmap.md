# Roadmap

Current state, priorities, and future ideas for ha-litellm-conversation.

## Current State (v1.6.2)

- ✅ Config flow (URL + API key, validates via /v1/models; reauth + reconfigure; masked key inputs)
- ✅ Conversation agent (streaming, tool calling, reasoning/thinking content via Chat Completions)
- ✅ AI Task entity (GenDataTask with structured output + **image attachments / vision**)
- ✅ STT platform (Whisper-compatible /v1/audio/transcriptions)
- ✅ TTS platform (/v1/audio/speech, 9 OpenAI voices)
- ✅ Usage sensors (4 daily diagnostic counters, restart-safe via RestoreSensor)
- ✅ Web search + guardrails passthrough, reasoning effort (body param)
- ✅ Extended Tools LLM API: call_service (domain blocklist + response data), get_history, fetch_url (SSRF guard), **analyze_camera (nested vision call, usage-tracked), get_calendar_events, add_todo_item** — entity tools gated on exposed-to-Assist
- ✅ Diagnostics (redacted), dev container, pytest suite (162 tests), CI (lint + tests + hassfest + HACS)
- ✅ Entities flip unavailable on proxy connection errors (logged once per transition)
- ✅ Long-term memory: remember/forget/list_memories tools, per-turn prompt injection, todo.*_memories management UI, remember/forget services, diagnostics export (50 memories x 300 chars cap)
- ✅ Dreaming: background memory consolidation (transcript buffer + capture switch, dream service w/ dry_run + model override + activity digest, last-dream sensor, completion event, nightly blueprint)
- ✅ HACS distribution working, tagged releases

## Remaining Ideas (rough priority)

1. **Submit to HACS default repositories** — repo shape is ready (CI, releases, brand assets)
2. **Generate Image** support (ai_task.AITaskEntityFeature.GENERATE_IMAGE)
3. **Cache-hit indicator** — surface LiteLLM cache metadata (debug log or attribute)
4. **`create_automation` extended tool** — powerful but risky; needs careful guardrails
5. **Streaming TTS** — revisit when LiteLLM realtime support matures

Deliberately skipped: code interpreter (Responses-API-only; repo uses Chat
Completions for Bedrock compatibility), client-side model fallback (LiteLLM
proxy handles this server-side).

## Future ideas (research notes)


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
