# Changelog

Notable changes per release, grouped Added / Changed / Fixed / Removed.
Sections from v1.3.0 onward were seeded from the tag history when this file was
introduced; from here on they are rendered with [`just changelog`](justfile)
via [git-cliff](https://git-cliff.org) and Conventional Commits
(`feat`/`fix`/`perf`/`refactor`; `docs`, `test`, `ci`, `chore` do not appear).

## [Unreleased]

## [2.1.1] - 2026-11-06

### Added

- AI Task decision models: `ai_task.evaluate` via LiteLLM `/v1/systemone` (a new decision model subentry; needs Home Assistant 2026.11+ and LiteLLM >= 1.104.2), with yes/no, choice and score questions plus image attachments.
- Home Assistant Marketplace readiness: manifest `categories` and an updated README.

### Fixed

- **Tools and structured AI tasks failed on Home Assistant 2026.9+.** Home Assistant moved schema handling to probatio, and tool and structure schemas could no longer be encoded as JSON. The integration now uses the converter matching the running release.
- Extended tools record their integration, which Home Assistant enforces from 2027.10.

## [2.1.0] - 2026-11-06

### Added

- Proxy-side spend + budget sensors from LiteLLM `/key/info` (15-min coordinator, entry's own virtual key): `proxy_spend` (USD) and `budget_utilization` (%).
- Every Chat Completions request tagged with LiteLLM metadata tags (`home-assistant`, `ha-litellm-conversation`) for spend-log slicing.
- AI Task `generate_image` via LiteLLM `/v1/images/generations`: opt-in per subentry (`image_model`, optional `image_size`/`image_quality`); `b64_json` responses only — URL-only responses are rejected on purpose (SSRF posture).

## [2.0.0] - 2026-11-05

### Removed

- **Breaking:** the dreaming subsystem (background consolidation): `dreaming.py`, transcript buffer, `select.*_dream_model`, `switch.*_transcript_capture`, `sensor.*_last_dream`, the `dream`/`clear_transcripts`/`refresh_models` services and the nightly blueprint.
- **Breaking:** the long-term memory subsystem: `MemoryStore`, the `todo.*_memories` platform, the `remember`/`forget`/`list_memories` extended tools, per-turn memory injection and the `litellm_conversation.remember`/`.forget` services. Use Home Assistant's MCP integration with a memory/RAG MCP server instead.

## [1.8.0] - 2026-07-14

### Added

- `refresh_models` service to refresh the dream-model dropdown; silenced a hassfest `CONFIG_SCHEMA` warning.

## [1.7.1] - 2026-07-14

### Changed

- Dreaming reuses the cached model list for the dream-model select (no duplicate `/v1/models` call).

### Fixed

- Onboarding: dedupe the `/v1/models` call during setup and surface a real warning instead of silently seeding a fake default model when the proxy has zero models.

## [1.7.0] - 2026-07-14

### Added

- Live model dropdown (select entity) for the dream model.

### Fixed

- Blueprint notify condition template.

## [1.6.2] - 2026-07-13

### Fixed

- Review pass: device grouping, dream serialization, diagnostics.

## [1.6.1] - 2026-07-13

### Fixed

- Declare `logbook` as `after_dependency` (hassfest).

## [1.6.0] - 2026-07-13

### Added

- Dreaming: transcript buffer + capture hook + capture switch; consolidation engine (one structured LLM call); `dream`/`clear_transcripts` services with activity digest; `sensor.*_last_dream`; nightly blueprint and dashboard recipe.

## [1.5.0] - 2026-07-13

### Added

- Store-backed memory (cap 50, 300 chars, dedup, signals); `remember`/`forget`/`list_memories` extended tools with per-turn injection; memories exposed as a native to-do list; `remember`/`forget` services.

## [1.4.2] - 2026-07-13

### Added

- Entities flip to unavailable when the proxy is unreachable; `analyze_camera`'s nested call feeds the usage sensors.

### Changed

- Subentry schemas extracted into `schemas.py`.

## [1.4.1] - 2026-07-13

### Fixed

- Structured output crashed on selector-based structures.

## [1.4.0] - 2026-07-13

### Added

- Image attachments encoded as `image_url` parts on the last user message; AI Task advertises `SUPPORT_ATTACHMENTS`; extended tools `analyze_camera`, `get_calendar_events`, `add_todo_item`.

### Changed

- The extended-tools API carries the owning config entry.

## [1.3.1] - 2026-07-12

### Added

- `call_service` forwards service response data to the model.

### Security

- Mask API key inputs and stop pre-filling the key on reconfigure; harden extended tools against prompt injection.

### Fixed

- Usage sensor state survives HA restarts.

### Changed

- Dedupe base-URL normalization, log model-fetch failures; extract request-param builder and API error mapping.

## [1.3.0] - 2026-07-12

### Added

- Web search + guardrails passthrough and token usage capture; daily usage sensors (requests, tokens in/out/total); STT and TTS platforms via LiteLLM audio endpoints; config flow for web search, guardrails and STT/TTS subentries; extended tools LLM API (`call_service`, `get_history`, `fetch_url`).

### Fixed

- Declare `recorder` as `after_dependency`.

## [1.2.0] - 2026-07-11

First tagged release: LiteLLM proxy bridge for Home Assistant — config flow
(URL + API key validated against `/v1/models`), streaming conversation agent
with tool calling, AI Task entity with structured output, and redacted
diagnostics.
