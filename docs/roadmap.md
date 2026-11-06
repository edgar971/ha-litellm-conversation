# Roadmap

Current state, priorities, and future ideas for ha-litellm-conversation.

## Current State (v2.1.x)

- ✅ Spend/budget sensors shipped as v2.1.0; Marketplace readiness (manifest `categories`, HA 2026.11 install docs) landed right after

- ✅ Config flow (URL + API key, validates via /v1/models; reauth + reconfigure; masked key inputs)
- ✅ Conversation agent (streaming, tool calling, reasoning/thinking content via Chat Completions)
- ✅ AI Task entity (GenDataTask with structured output + **image attachments / vision**)
- ✅ AI Task generate_image (issue #4): raw `POST /v1/images/generations` through the entry client, opt-in per subentry via `image_model` (+ optional free-text `image_size`/`image_quality` passthrough). `b64_json` responses only — URL-only responses are rejected on purpose (no fetching arbitrary remote URLs); usage (when the provider reports it) feeds the daily sensors; a proxy with no image models deployed gets clean errors, not crashes
- ✅ STT platform (Whisper-compatible /v1/audio/transcriptions)
- ✅ TTS platform (/v1/audio/speech, 9 OpenAI voices)
- ✅ Usage sensors (4 daily diagnostic counters, restart-safe via RestoreSensor)
- ✅ Proxy-side spend + budget sensors (issue #3): `proxy_spend` (USD, MEASUREMENT — the proxy resets its budget window, so not total_increasing) and `budget_utilization` (%; unknown without max_budget), 15-min `/key/info` DataUpdateCoordinator using the entry's own virtual key
- ✅ Request metadata tags (`["home-assistant", "ha-litellm-conversation"]`) on every Chat Completions request → LiteLLM spend-log `request_tags` for Grafana slicing
- ✅ Web search + guardrails passthrough, reasoning effort (body param)
- ✅ Extended Tools LLM API: call_service (domain blocklist + response data), get_history, fetch_url (SSRF guard), **analyze_camera (nested vision call, usage-tracked), get_calendar_events, add_todo_item** — entity tools gated on exposed-to-Assist
- ✅ Diagnostics (redacted), dev container, pytest suite (166 tests), CI (lint + tests + hassfest + HACS)
- ✅ Entities flip unavailable on proxy connection errors (logged once per transition)
- ✅ HACS distribution working, tagged releases

### Removed in v2.0.0 (breaking)

Long-term memory and dreaming (background consolidation) were removed to keep
the integration a focused proxy bridge. For that capability, use HA's [MCP
integration](https://www.home-assistant.io/integrations/mcp/) with any
memory/RAG MCP server — it plugs into these agents via the LLM API selector
with no code here.

**Upgrade guidance:** after updating, orphaned entities
(`select.*_dream_model`, `switch.*_transcript_capture`, `sensor.*_last_dream`,
`todo.*_memories`) are cleaned up automatically on the first restart — no
manual entity removal needed. Automations calling `litellm_conversation.dream`,
`.clear_transcripts`, `.refresh_models`, `.remember`, or `.forget` will fail
until edited; the nightly-dream blueprint is gone. The transcript buffer and
memory store files in `.storage/` become orphaned data HA garbage-collects.

## Remaining Ideas (rough priority)

1. **Submit to HACS default repositories** — repo shape is ready (CI, releases, brand assets)
2. **Cache-hit indicator** — surface LiteLLM cache metadata (debug log or attribute)
3. **`create_automation` extended tool** — powerful but risky; needs careful guardrails
4. **Streaming TTS** — revisit when LiteLLM realtime support matures

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
- **Proxy-side spend/budget sensors + request metadata tags** (issue #3): shipped.
- **Long-term memory (tools + todo UI + services)**: shipped v1.5.0, **removed in v2.0.0** — use HA's MCP integration with a memory MCP server instead.
- **Dreaming (background consolidation, transcript buffer, blueprint)**: shipped v1.6.x, **removed in v2.0.0**.
- **AI Task attachments / vision, camera-calendar-todo tools**: shipped (v1.4.0).
- **Code interpreter**: rejected — Responses-API-only; repo uses Chat Completions for Bedrock.
- **Model fallback**: rejected client-side — the LiteLLM proxy handles routing/fallback server-side.
- **MCP passthrough**: needs no code — works via HA's MCP integration + the LLM API selector.
