# ADRs

Architecture decision records for ha-litellm-conversation: the non-obvious
choices, why they were made, and what they cost. These formalize decisions
already visible in the code, docs and release history; they are backfilled, so
the dates are when the decision was actually taken (or first documented), not
when it was written down here.

| # | Decision | Status |
|---|---|---|
| [0001](0001-chat-completions-not-responses-api.md) | Use Chat Completions, not the Responses API | Accepted |
| [0002](0002-v2-removal-of-dreaming-and-memory.md) | v2.0.0 removes dreaming and long-term memory | Accepted |
| [0003](0003-no-client-side-model-fallback.md) | No client-side model fallback | Accepted |
| [0004](0004-b64-json-only-image-responses.md) | Image generation accepts `b64_json` responses only | Accepted |
