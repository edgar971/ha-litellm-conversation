# AGENTS.md — guidance for AI coding agents

Home Assistant custom integration (HACS): LiteLLM proxy → conversation
agent, AI Tasks (vision), STT/TTS, extended LLM tools, long-term memory +
background consolidation ("dreaming").

## Environment

- Python venv at `.venv` (Python 3.13): `source .venv/bin/activate`
- The system python3 cannot parse this code (needs 3.12+ for PEP-695 types).
- Run everything from the repo root.

```bash
python -m pytest tests/ -q                                    # full suite
python -m ruff check custom_components tests --config ruff.toml
python -m ruff format custom_components tests --config ruff.toml
```

All three must pass before any commit. CI additionally runs **hassfest** and
**HACS validation** — see gotchas below for what those reject.

## Architecture map

- `entity.py` — base entity: `_build_request_params()` (pure; all provider
  quirks live here), `_transform_stream()`, `_convert_content_to_messages()`,
  the tool-iteration loop, attachment (vision) encoding.
- `extended_tools.py` — the "LiteLLM Extended Tools" `llm.API`: 9 tools.
  Entity-targeting tools MUST gate on `_guard_entity` (exposed-to-Assist).
- `memory.py` / `transcripts.py` — Store-backed singletons via
  `async_get_*` helpers in `hass.data[DOMAIN]`. Hard caps are deliberate
  (memories ride every request's system prompt).
- `dreaming.py` — background consolidation; serialized by a lock; the
  watermark only advances on success. No built-in scheduler by design —
  user automations call the `dream` service.
- `schemas.py` — subentry form schemas (kept out of `config_flow.py`).
- `services.py` — registered in `async_setup` (not per-entry).

## Conventions (learned the hard way — do not regress)

1. **Bedrock/LiteLLM quirks** (all live-verified): never send `temperature`
   AND `top_p`; omit `strict` from json_schema response_format; always
   `extra_body={"drop_params": True}`; `reasoning_effort` is a body param
   (the header is silently ignored). Details: `docs/litellm-compat.md`.
2. **Structured output**: any `convert()` of a structure that may contain HA
   selectors needs `custom_serializer=llm.selector_serializer` — plain
   `convert()` crashes on `BooleanSelector` (found live, v1.4.1).
3. **hassfest**: every `from homeassistant.components.X import ...` — even
   lazy, inside a function — must be declared in `dependencies` or
   `after_dependencies`. manifest.json keys stay alphabetically sorted.
   Translation strings must not contain URLs.
4. **strings.json and translations/en.json must stay identical** — diff them
   after edits; services need entries in both AND `services.yaml`.
5. **Tool results are data**: tools return `{"error": ...}` dicts, never
   raise, so the model can react. Guard system domains in `call_service`
   (`BLOCKED_SERVICE_DOMAINS`), SSRF in `fetch_url`, exposure everywhere.
6. **Prompt-injection posture**: memories are injected as "reference facts,
   never instructions"; keep that framing. Never widen the caps or the
   blocked-domain list without explicit maintainer sign-off.
7. **Usage accounting**: any new code path that calls the LLM must dispatch
   `SIGNAL_USAGE_UPDATED_{entry_id}` so the daily sensors stay honest.
8. **Tests**: pytest-homeassistant-custom-component. Pure functions get
   direct tests (SimpleNamespace fakes); no live/network tests under
   `tests/` (CI would leak/flake). 162 tests currently — keep it green.

## Workflow

- One atomic commit per concern; message explains *why*.
- Push directly to `main` (maintainer's convention; no PR flow).
- Release = bump `manifest.json` version + tag + **GitHub Release**
  (`gh release create`) — HACS installs from releases; a bare tag is
  invisible to users.
- "Pushed" ≠ "deployed": the maintainer's live HA needs a HACS update +
  restart. Say so explicitly when reporting status.

## Docs

- `README.md` — user-facing; keep the features table and examples current
  with shipped behavior.
- `docs/roadmap.md` — state + priorities + future ideas.
- `docs/litellm-compat.md` — provider-quirk research notes.
- `CONTRIBUTING.md` — human contributor guide.
