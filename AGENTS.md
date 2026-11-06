# AGENTS.md — guidance for AI coding agents

Home Assistant custom integration (HACS): LiteLLM proxy → conversation
agent, AI Tasks (vision + decision models), STT/TTS, extended LLM tools.

## Environment

- Python venv at `.venv` (Python 3.13): `source .venv/bin/activate`
- The system python3 cannot parse this code (needs 3.12+ for PEP-695 types).
- Run everything from the repo root.

```bash
python -m pytest tests/ -q                                    # full suite
python -m ruff check custom_components tests --config ruff.toml
python -m ruff format custom_components tests --config ruff.toml
just check                                                    # lint + format check + tests
```

All three must pass before any commit (`just check` runs them as CI does).
CI additionally runs **hassfest** and **HACS validation** — see gotchas below
for what those reject.

## Architecture map

- `entity.py` — base entity: `_build_request_params()` (pure; all provider
  quirks live here), `_transform_stream()`, `_convert_content_to_messages()`,
  the tool-iteration loop, attachment (vision) encoding.
- `extended_tools.py` — the "LiteLLM Extended Tools" `llm.API`: 6 tools.
  Entity-targeting tools MUST gate on `_guard_entity` (exposed-to-Assist).
- `ai_task.py` — AI Task entity (structured output, images) plus the decision
  entity (`ai_task.evaluate` via the proxy's `/v1/systemone`; needs
  LiteLLM >= 1.104.2 and HA 2026.11+).
- `schemas.py` — subentry form schemas (kept out of `config_flow.py`).

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
   after edits.
5. **Tool results are data**: tools return `{"error": ...}` dicts, never
   raise, so the model can react. Guard system domains in `call_service`
   (`BLOCKED_SERVICE_DOMAINS`), SSRF in `fetch_url`, exposure everywhere.
6. **Prompt-injection posture**: never widen the blocked-domain list without
   explicit maintainer sign-off.
7. **Usage accounting**: any new code path that calls the LLM must dispatch
   `SIGNAL_USAGE_UPDATED_{entry_id}` so the daily sensors stay honest.
8. **Tests**: pytest-homeassistant-custom-component. Pure functions get
   direct tests (SimpleNamespace fakes); no live/network tests under
   `tests/` (CI would leak/flake). Keep the suite green.

## Workflow

- One atomic commit per concern; message explains *why*.
- Changes land on `main` through a PR; release commits go directly to `main`.
- Release = bump `manifest.json` version + tag + **GitHub Release**
  (`gh release create`) — HACS installs from releases; a bare tag is
  invisible to users.
- "Pushed" ≠ "deployed": the maintainer's live HA needs a HACS update +
  restart. Say so explicitly when reporting status.

## Docs

- `README.md` — user-facing; keep the features table and examples current
  with shipped behavior.
- `docs/litellm-compat.md` — provider-quirk research notes.
- `docs/adr/` — decision records; check before reversing a past call (memory
  and dreaming were removed on purpose, see ADR 0002).
- `CONTRIBUTING.md` — human contributor guide.
