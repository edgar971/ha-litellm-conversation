# ha-litellm-conversation — Next Steps Plan

## Current State (v1.0.1)
- ✅ Config flow (URL + API key, validates via /v1/models)
- ✅ Conversation agent (streaming, tool calling via Responses API)
- ✅ AI Task entity (GenDataTask with structured output)
- ✅ HACS distribution working
- ✅ Inheritance fixed to match HA 2026.6 patterns

## Phase A: Local Development Setup
1. Add `devcontainer.json` for VS Code dev container development
2. Add a `scripts/develop` script that:
   - Symlinks `custom_components/litellm_conversation` into a local HA dev instance
   - Starts HA with `hass -c config/` pointing at a test config
3. Add `pytest` setup with `pytest-homeassistant-custom-component`
4. Add `ruff.toml` with HA-matching settings
5. Add GitHub Actions CI (lint + test on push)

## Phase B: Improved Config & Settings
1. **Reconfigure flow** — allow editing base_url/api_key after initial setup
2. **Options flow for subentries** — edit model/temperature/prompt without removing
3. **Dynamic model refresh** — re-fetch /v1/models when opening subentry options
4. **Error translation keys** — improve error messages shown in UI
5. **Diagnostics** — add `diagnostics.py` for HA diagnostics download (redact API key)

## Phase C: Better Logging & Debugging
1. Add proper `logging.getLogger(__name__)` throughout
2. Log model used, token count, and latency for each request
3. Log tool call sequences at debug level
4. Surface LiteLLM response headers (x-litellm-model-id, x-litellm-cache-hit) as debug info
5. Add `sensor` platform for usage tracking (requests/tokens per hour — optional entity)

## Phase D: Feature Parity with OpenAI Integration
1. **Reasoning effort** support (pass through for o-series models)
2. **Web search tool** passthrough
3. **Attachments support** in AI Task (images, files)
4. **Generate Image** support (ai_task.AITaskEntityFeature.GENERATE_IMAGE)
5. **Streaming TTS** consideration (if LiteLLM supports it)
6. **Store responses** option (LiteLLM's response storage)

## Phase E: Documentation & Polish
1. Comprehensive README with:
   - Installation instructions
   - Configuration screenshots
   - Supported features matrix
   - Troubleshooting guide
2. Add CHANGELOG.md
3. Add CONTRIBUTING.md
4. Submit to HACS default repositories

## Priority Order
Start with Phase A (dev setup) since it unblocks faster iteration on everything else.
Then Phase B (settings) and C (logging) in parallel since those address the immediate ask.
Phase D adds features. Phase E polishes for public release.
