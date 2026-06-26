# Feature Ideas & Exploration — ha-litellm-conversation

Research completed 2026-06-26. All references verified against latest HA (2026.6) and LiteLLM docs.

---

## 🏆 Tier 1: High-Impact, Low-Effort

### 1. Extended Tools (call_service, get_history, fetch_url)

**What:** Add custom LLM tools beyond the built-in HA Assist API — direct service calls, entity history queries, and external URL fetching.

**Why:** The [extended_openai_conversation](https://github.com/jekalmin/extended_openai_conversation) community project (5.5k+ stars) proves this is the #1 most-wanted feature. The [v2 rewrite](https://github.com/damiannos/ha-extended-openai-conversation-v2) modernized it for HA's Responses API. Your integration could offer this natively.

**Tools to add:**
- `call_service` — Let the LLM call any HA service directly (with entity validation)
- `get_history` — Query the recorder for state history over time ranges
- `fetch_url` — HTTP client for external APIs (weather, stocks, transit)
- `create_automation` — Generate and install automations from natural language

**How:** Register a custom `llm.API` class (see [HA LLM docs](https://developers.home-assistant.io/docs/core/llm/)). Users select it alongside or instead of the built-in Assist API in the subentry config.

**Effort:** Medium (2-3 files, ~300 lines)

---

### 2. MCP Server Tool Passthrough

**What:** HA already has an [MCP integration](https://www.home-assistant.io/integrations/mcp/) that exposes MCP server tools to conversation agents. Your integration already supports this via the `CONF_LLM_HASS_API` selector — any MCP tools registered in HA automatically become available to your agent.

**Why:** MCP is the emerging standard. Memory servers, web search servers, RAG pipelines — all just work if users configure the MCP integration alongside yours.

**Action needed:** Document this in your README. Maybe add a "Use with MCP" section. The code already supports it via the HA LLM API framework. Zero code changes needed!

**Effort:** None (already works), just docs

---

### 3. Web Search Tool (OpenAI Responses API native)

**What:** The OpenAI Responses API supports a native `web_search` tool type. LiteLLM proxies that route to OpenAI, Azure, or compatible providers can pass this through.

**How:** Add a `CONF_WEB_SEARCH` boolean option. When enabled, append to tools:
```python
{"type": "web_search_preview"}
```

**Reference:** The official `openai_conversation` integration already does this — see [entity.py WebSearchToolParam](https://github.com/home-assistant/core/blob/dev/homeassistant/components/openai_conversation/entity.py).

**Effort:** Low (one config option + 5 lines in entity.py)

---

### 4. STT Platform (Speech-to-Text via LiteLLM)

**What:** Add a `Platform.STT` entity so users can use Whisper (or any STT model LiteLLM supports) through your proxy for voice assistant pipelines.

**Why:** The official OpenAI integration added STT. LiteLLM can proxy Whisper API calls to OpenAI, Azure, Groq, or local whisper endpoints. Users get provider-agnostic STT.

**How:** Create `stt.py` implementing the STT platform. Accepts audio, sends to `/v1/audio/transcriptions`, returns text. Reference: [ha-openai-whisper-stt-api](https://github.com/fabio-garavini/ha-openai-whisper-stt-api).

**Effort:** Medium (new file, ~100 lines)

---

### 5. TTS Platform (Text-to-Speech via LiteLLM)

**What:** Add a `Platform.TTS` entity using LiteLLM's `/v1/audio/speech` endpoint for text-to-speech.

**Why:** Completes the voice pipeline — users can use the same proxy for STT + conversation + TTS. The official OpenAI integration has TTS.

**How:** Create `tts.py` implementing the TTS platform. Voice selection as a config option.

**Effort:** Medium (new file, ~120 lines)

---

## 🥈 Tier 2: Medium-Impact, Medium-Effort

### 6. Cost & Token Tracking Sensor

**What:** Add a `sensor` platform that tracks per-request and daily token usage and estimated cost.

**Why:** LiteLLM returns usage metadata in response headers (`x-litellm-model-id`, token counts). Surfacing this lets users monitor costs and set up alerts.

**How:** Create `sensor.py` with entities:
- `sensor.litellm_requests_today` (counter)
- `sensor.litellm_tokens_today` (total tokens)
- `sensor.litellm_cost_today` (estimated $)

Parse response metadata after each API call.

**Effort:** Medium

---

### 7. Prompt Caching / Cache Hit Indicator

**What:** LiteLLM supports prompt caching (Anthropic cache_control, OpenAI auto-cache). Surface cache hit status.

**Why:** Cost savings up to 90% with cached prompts. Users want to know if caching is working.

**How:** Read LiteLLM response headers for cache metadata. Log at debug level, optionally expose as a binary_sensor or attribute.

**Reference:** [LiteLLM Prompt Caching docs](https://docs.litellm.ai/docs/tutorials/proxy_features_safety)

**Effort:** Low

---

### 8. Model Fallback / Routing

**What:** Allow users to configure fallback models. If primary model is down or rate-limited, automatically try the next one.

**Why:** LiteLLM proxy handles this server-side, but some users run basic proxy configs. Client-side fallback adds resilience.

**How:** Add a `CONF_FALLBACK_MODELS` option (comma-separated list). On API error, retry with next model.

**Effort:** Low-Medium

---

### 9. Conversation Memory / Context Window Management

**What:** Intelligent context window management — auto-summarize old messages when approaching token limits.

**Why:** Long conversations hit token limits. Auto-summarization keeps context useful without crashing.

**How:** Track token count per conversation. When approaching `max_tokens * 0.8`, summarize older messages using the same model before sending the next request.

**Effort:** Medium-High

---

### 10. Custom System Prompt Templates with HA Variables

**What:** Allow Jinja2 templates in system prompts that resolve HA state.

**Why:** "You are a home assistant. The current time is {{ now() }}. The weather is {{ states('weather.home') }}." — dynamic context injection.

**How:** The HA conversation framework already supports this via `extra_system_prompt`. Document how users can leverage it with your integration's prompt field.

**Effort:** Low (mostly docs — HA's ChatLog already handles template rendering)

---

## 🥉 Tier 3: Cool But Complex

### 11. Code Interpreter Support

**What:** Pass through the OpenAI Responses API `code_interpreter` tool for models that support it.

**Why:** Let the LLM run Python code to analyze data, create charts, process CSV files from HA.

**How:** Add `CONF_CODE_INTERPRETER` option. The official `openai_conversation` already does this.

**Effort:** Medium (need to handle the tool type and file outputs)

---

### 12. Multi-Agent Routing

**What:** Allow users to configure multiple conversation subentries and route based on intent or topic.

**Why:** Use a cheap/fast model for simple commands, expensive model for complex reasoning.

**How:** Create a "router" conversation entity that first classifies the request, then forwards to the appropriate sub-agent.

**Effort:** High

---

### 13. Guardrails Integration

**What:** Surface LiteLLM's guardrail features (PII masking, content filtering) as HA config options.

**Why:** Privacy-conscious users (especially with kids) want content filtering.

**How:** Pass guardrail configuration in headers that LiteLLM's proxy respects. Config option to enable/disable.

**Reference:** [LiteLLM Guardrails](https://docs.litellm.ai/docs/proxy/guardrails/quick_start)

**Effort:** Low (header passthrough) to Medium (config UI)

---

### 14. Streaming TTS (OpenAI Realtime-like)

**What:** Stream audio responses as they're generated, reducing perceived latency.

**Why:** HA 2026 supports streaming TTS for conversation agents. The official blog showed 10x speed improvements.

**How:** Use the responses API streaming + pipe partial text into TTS. Requires implementing `_attr_supports_streaming = True` on the conversation entity (already done) and potentially a realtime audio pipe.

**Effort:** High (depends on LiteLLM realtime support maturity)

---

## 📋 Priority Recommendation

| Priority | Feature | Impact | Effort |
|----------|---------|--------|--------|
| 🟢 Now | MCP docs (already works!) | High | Zero |
| 🟢 Now | Web search tool option | High | Low |
| 🟡 Next | Extended tools (service/history/url) | Very High | Medium |
| 🟡 Next | STT platform | High | Medium |
| 🟡 Next | TTS platform | High | Medium |
| 🔵 Later | Cost tracking sensor | Medium | Medium |
| 🔵 Later | Code interpreter | Medium | Medium |
| 🔵 Later | Guardrails config | Medium | Low |

---

## References

- [HA LLM API Developer Docs](https://developers.home-assistant.io/docs/core/llm/) — how to register custom tools
- [HA MCP Integration](https://www.home-assistant.io/integrations/mcp/) — MCP server tool support
- [HA AI Task Docs](https://www.home-assistant.io/integrations/ai_task/) — generate_data, generate_image actions
- [HA AI Blog Post (Sept 2025)](https://www.home-assistant.io/blog/2025/09/11/ai-in-home-assistant/) — streaming TTS, MCP, AI suggestions
- [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses) — web_search, code_interpreter, tools
- [LiteLLM Proxy Docs](https://docs.litellm.ai/docs/proxy/quick_start) — caching, guardrails, callbacks
- [extended_openai_conversation v2](https://github.com/damiannos/ha-extended-openai-conversation-v2) — reference for extended tools pattern
- [HA OpenAI Conversation source](https://github.com/home-assistant/core/tree/dev/homeassistant/components/openai_conversation) — reference implementation
- [HA STT Platform docs](https://www.home-assistant.io/integrations/stt/) — building block for voice pipelines
- [ha-openai-whisper-stt-api](https://github.com/fabio-garavini/ha-openai-whisper-stt-api) — community STT reference
