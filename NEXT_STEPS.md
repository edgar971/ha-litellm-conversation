# ha-litellm-conversation — Next Steps Plan

## Current State (v1.4.0)

- ✅ Config flow (URL + API key, validates via /v1/models; reauth + reconfigure; masked key inputs)
- ✅ Conversation agent (streaming, tool calling, reasoning/thinking content via Chat Completions)
- ✅ AI Task entity (GenDataTask with structured output + **image attachments / vision**)
- ✅ STT platform (Whisper-compatible /v1/audio/transcriptions)
- ✅ TTS platform (/v1/audio/speech, 9 OpenAI voices)
- ✅ Usage sensors (4 daily diagnostic counters, restart-safe via RestoreSensor)
- ✅ Web search + guardrails passthrough, reasoning effort (body param)
- ✅ Extended Tools LLM API: call_service (domain blocklist + response data), get_history, fetch_url (SSRF guard), **analyze_camera (nested vision call, usage-tracked), get_calendar_events, add_todo_item** — entity tools gated on exposed-to-Assist
- ✅ Diagnostics (redacted), dev container, pytest suite (108 tests), CI (lint + tests + hassfest + HACS)
- ✅ Entities flip unavailable on proxy connection errors (logged once per transition)
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

See FEATURE_IDEAS.md for the full research notes behind these.
