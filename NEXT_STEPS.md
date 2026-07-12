# ha-litellm-conversation — Next Steps Plan

## Current State (v1.3.x)

- ✅ Config flow (URL + API key, validates via /v1/models; reauth + reconfigure; masked key inputs)
- ✅ Conversation agent (streaming, tool calling, reasoning/thinking content via Chat Completions)
- ✅ AI Task entity (GenDataTask with structured output)
- ✅ STT platform (Whisper-compatible /v1/audio/transcriptions)
- ✅ TTS platform (/v1/audio/speech, 9 OpenAI voices)
- ✅ Usage sensors (4 daily diagnostic counters, restart-safe via RestoreSensor)
- ✅ Web search + guardrails passthrough, reasoning effort (body param)
- ✅ Extended Tools LLM API (call_service w/ domain blocklist + response data, get_history, fetch_url w/ SSRF guard)
- ✅ Diagnostics (redacted), dev container, pytest suite (60 tests), CI (lint + tests + hassfest + HACS)
- ✅ HACS distribution working, tagged releases

## Remaining Ideas (rough priority)

1. **Submit to HACS default repositories** — repo shape is ready (CI, releases, brand assets)
2. **Attachments support** in AI Task (images/files to vision models)
3. **Generate Image** support (ai_task.AITaskEntityFeature.GENERATE_IMAGE)
4. **Cache-hit indicator** — surface LiteLLM cache metadata (debug log or attribute)
5. **`create_automation` extended tool** — powerful but risky; needs careful guardrails
6. **Streaming TTS** — revisit when LiteLLM realtime support matures

Deliberately skipped: code interpreter (Responses-API-only; repo uses Chat
Completions for Bedrock compatibility), client-side model fallback (LiteLLM
proxy handles this server-side).

See FEATURE_IDEAS.md for the full research notes behind these.
