# ha-litellm-conversation — Implementation Plan

## Executive Summary

A Home Assistant custom integration that connects to any **LiteLLM proxy** and registers as both a **Conversation agent** and **AI Task provider**. Uses the OpenAI Python SDK's **Responses API** (`/v1/responses`) — which LiteLLM v1.82.6+ fully supports — making it a configurable-`base_url` fork of HA's built-in `openai_conversation`.

---

## Reference Links

### Source Code to Study

| Resource | URL | Why |
|----------|-----|-----|
| HA OpenAI Conversation (dev) | https://github.com/home-assistant/core/tree/dev/homeassistant/components/openai_conversation | **Primary reference** — we fork this |
| HA Anthropic (dev) | https://github.com/home-assistant/core/tree/dev/homeassistant/components/anthropic | AI Task + subentry pattern |
| Extended OpenAI Conversation (HACS) | https://github.com/jekalmin/extended_openai_conversation | Custom component + HACS example |
| HA Core `const.py` | https://github.com/home-assistant/core/blob/dev/homeassistant/const.py | Shared constants (CONF_LLM_HASS_API, etc.) |
| HA `helpers/llm.py` | https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/llm.py | LLM API helper internals |
| HA `components/conversation/__init__.py` | https://github.com/home-assistant/core/blob/dev/homeassistant/components/conversation/__init__.py | ChatLog, ConversationEntity |

### LiteLLM Docs

| Resource | URL | Why |
|----------|-----|-----|
| LiteLLM Responses API | https://docs.litellm.ai/docs/response_api | Confirms /v1/responses support |
| LiteLLM Provider Params | https://docs.litellm.ai/docs/completion/provider_specific_params | Provider-specific passthrough |
| LiteLLM OpenAI Agents SDK | https://docs.litellm.ai/docs/tutorials/openai_agents_sdk | SDK compatibility proof |
| LiteLLM Proxy Quick Start | https://docs.litellm.ai/docs/proxy/quick_start | Proxy setup reference |
| LiteLLM OpenAPI Spec (live) | https://litellm-api.up.railway.app/openapi.json | Your live proxy's full API |

### HA Developer Docs

| Resource | URL | Why |
|----------|-----|-----|
| LLM API for Integrations | https://developers.home-assistant.io/docs/core/llm/ | How to integrate with ChatLog + tools |
| Development Checklist | https://developers.home-assistant.io/docs/development_checklist | Code standards |
| Component Code Review | https://developers.home-assistant.io/docs/creating_component_code_review | Review requirements |
| Core Architecture | https://developers.home-assistant.io/docs/architecture/core | Event bus, state, services |
| Config Flow | https://developers.home-assistant.io/docs/config_entries_config_flow_handler | Config entry pattern |
| Conversation Platform | https://www.home-assistant.io/integrations/conversation/ | User-facing docs |
| AI Task Platform | https://www.home-assistant.io/integrations/ai_task/ | User-facing docs |
| Integration Manifest | https://developers.home-assistant.io/docs/creating_integration_manifest | manifest.json spec |
| HACS Integration | https://hacs.xyz/docs/publish/integration | Publishing to HACS |

### Tools & Standards

| Resource | URL | Why |
|----------|-----|-----|
| OpenAI Python SDK | https://github.com/openai/openai-python | Client library we use |
| Ruff (formatter/linter) | https://docs.astral.sh/ruff/ | Required by HA for formatting |
| Voluptuous (validation) | https://github.com/alecthomas/voluptuous | Config schema validation |
| HACS (custom components) | https://hacs.xyz/ | Distribution platform |

---

## Why Not Just Use the Built-in OpenAI Component?

The built-in `openai_conversation` hardcodes OpenAI auth and doesn't expose `base_url`. Our component:

1. **Configurable `base_url`** → point at any LiteLLM proxy
2. **Configurable API key** → use LiteLLM virtual keys
3. **Dynamic model list** from proxy's `/v1/models` endpoint
4. **All providers** LiteLLM supports (Bedrock, Vertex, Azure, Anthropic, Ollama, etc.)
5. **Both platforms**: `conversation` + `ai_task`

---

## Architecture

```
┌─────────────────────────────────────────────┐
│         Home Assistant                       │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │  litellm_conversation component      │   │
│  │  (OpenAI Python SDK w/ base_url)     │   │
│  └──────────────┬───────────────────────┘   │
│                 │                             │
└─────────────────┼─────────────────────────────┘
                  │ HTTPS (OpenAI Responses API)
                  ▼
┌─────────────────────────────────────────────┐
│  LiteLLM Proxy                               │
│  /v1/responses  /v1/models  /v1/chat/...    │
│                                              │
│  Routes to: Bedrock, OpenAI, Anthropic,     │
│  Vertex AI, Azure, Ollama, etc.             │
└─────────────────────────────────────────────┘
```

**SDK usage**: `openai.AsyncOpenAI(base_url="https://your-litellm", api_key="sk-...")` → `client.responses.create(stream=True, ...)`

---

## File Structure

```
custom_components/litellm_conversation/
├── __init__.py              # Entry setup, client creation, platform forwarding
├── manifest.json            # Integration metadata + dependencies
├── config_flow.py           # ConfigFlow + SubentryFlow
├── const.py                 # Constants, defaults, domain
├── entity.py                # LiteLLMBaseLLMEntity + _transform_stream + _convert_content
├── conversation.py          # LiteLLMConversationEntity
├── ai_task.py               # LiteLLMAITaskEntity
├── strings.json             # UI strings for config flow
└── translations/
    └── en.json              # English translations
```

---

## What to Copy from `openai_conversation`

Since LiteLLM implements the full Responses API, we copy nearly everything:

| Our File | Copy from | Changes |
|----------|-----------|---------|
| `entity.py` | [`openai_conversation/entity.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/openai_conversation/entity.py) | None — same API, same stream |
| `conversation.py` | [`openai_conversation/conversation.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/openai_conversation/conversation.py) | Rename class + domain |
| `ai_task.py` | [`openai_conversation/ai_task.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/openai_conversation/ai_task.py) | Rename class + domain |
| `__init__.py` | [`openai_conversation/__init__.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/openai_conversation/__init__.py) | Add `base_url`, remove OpenAI org auth |
| `config_flow.py` | [`openai_conversation/config_flow.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/openai_conversation/config_flow.py) | Add `base_url` field, dynamic model list |
| `const.py` | [`openai_conversation/const.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/openai_conversation/const.py) | Change domain + defaults |

---

## Config Flow Design

### Step 1: User Setup (`async_step_user`)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `base_url` | str | _(required)_ | LiteLLM proxy URL (e.g. `https://litellm-api.up.railway.app`) |
| `api_key` | str | _(required)_ | Proxy API key |

**Validation**: `client.models.list()` with 10s timeout. Success → entry created.

### Step 2: Auto-create subentries

On success, create two subentries (per [HA's subentry pattern](https://github.com/home-assistant/core/blob/dev/homeassistant/components/openai_conversation/__init__.py)):
- `conversation` subentry
- `ai_task_data` subentry

### Conversation Subentry Options

| Option | Type | Default | Reference |
|--------|------|---------|-----------|
| `model` | select (from `/v1/models`) | First available | Dynamic from proxy |
| `prompt` | template | HA default | [`llm.DEFAULT_INSTRUCTIONS_PROMPT`](https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/llm.py) |
| `temperature` | float (0–2) | `1.0` | |
| `max_tokens` | int | `4096` | |
| `top_p` | float (0–1) | `1.0` | |
| `llm_hass_api` | LLM API selector | `None` | Per [LLM dev docs](https://developers.home-assistant.io/docs/core/llm/) |

### AI Task Subentry Options

| Option | Type | Default |
|--------|------|---------|
| `model` | select | First available |
| `temperature` | float (0–2) | `1.0` |
| `max_tokens` | int | `4096` |
| `top_p` | float (0–1) | `1.0` |

---

## Key Implementation Details

### 1. Client Creation

```python
# __init__.py
async def async_setup_entry(hass, entry: LiteLLMConfigEntry) -> bool:
    client = openai.AsyncOpenAI(
        api_key=entry.data[CONF_API_KEY],
        base_url=entry.data[CONF_BASE_URL],       # ← THE key difference
        http_client=get_async_client(hass),
    )
    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
```

### 2. Conversation Entity (per [LLM dev docs](https://developers.home-assistant.io/docs/core/llm/))

```python
# conversation.py — follows the pattern exactly
async def _async_handle_message(self, user_input, chat_log):
    await chat_log.async_provide_llm_data(
        user_input.as_llm_context(DOMAIN),
        self.subentry.data.get(CONF_LLM_HASS_API),
        self.subentry.data.get(CONF_PROMPT),
        user_input.extra_system_prompt,
    )
    # Delegates to entity.py's _async_handle_chat_log
    await self._async_handle_chat_log(chat_log)
```

### 3. Core Loop (`entity.py` — copied from openai_conversation)

```python
async def _async_handle_chat_log(self, chat_log, ...):
    for _iteration in range(MAX_TOOL_ITERATIONS):
        response = await client.responses.create(
            model=model,
            input=_convert_content_to_param(chat_log),
            tools=tools,
            stream=True,
        )
        async for _ in chat_log.async_add_delta_content_stream(
            self.entity_id, _transform_stream(chat_log, response)
        ):
            pass
        if not chat_log.unresponded_tool_results:
            break
```

### 4. `ConversationEntityFeature.CONTROL`

Only set when `CONF_LLM_HASS_API` is configured (per [LLM docs](https://developers.home-assistant.io/docs/core/llm/)):

```python
@property
def supported_features(self):
    if self.subentry.data.get(CONF_LLM_HASS_API):
        return ConversationEntityFeature.CONTROL
    return ConversationEntityFeature(0)
```

### 5. AI Task Entity

```python
# ai_task.py — follows anthropic component's pattern
async def _async_generate_data(self, chat_log, task, ...):
    await self._async_handle_chat_log(
        chat_log,
        structure_name=task.structure_name,
        structure=task.structure,
    )
```

---

## Developer Requirements (per [HA checklist](https://developers.home-assistant.io/docs/development_checklist))

- [ ] External lib on PyPI: `openai>=1.58.1` ✅ (already published)
- [ ] Requirements pinned in `manifest.json`
- [ ] Code formatted with [`ruff format`](https://docs.astral.sh/ruff/)
- [ ] Use constants from `homeassistant.const` (`CONF_LLM_HASS_API`, `CONF_API_KEY`)
- [ ] No direct HTTP calls — use `openai` SDK
- [ ] Documentation for home-assistant.io (if submitting to core)
- [ ] `.strict-typing` updated if fully typed

---

## Implementation Phases

### Phase 1: Skeleton + Config Flow (2–3 hours)
- [ ] Create repo: `edgar971/ha-litellm-conversation`
- [ ] `manifest.json` — domain `litellm_conversation`, deps `openai>=1.58.1`
- [ ] `const.py` — domain, defaults, config keys
- [ ] `config_flow.py` — user step (URL + key), validation via `models.list()`, subentry flows
- [ ] `__init__.py` — entry setup, client creation with `base_url`
- [ ] `strings.json` + `translations/en.json`
- [ ] Verify: integration loads in HA, config flow works

### Phase 2: Conversation Agent (1–2 hours)
- [ ] `entity.py` — copy from `openai_conversation/entity.py` (stream transform, content conversion)
- [ ] `conversation.py` — register as conversation agent
- [ ] Test: "Hello" → streamed text response via LiteLLM → Bedrock Claude

### Phase 3: Tool Calling (1–2 hours)
- [ ] Enable `CONF_LLM_HASS_API` in subentry options
- [ ] Verify tools passed to Responses API
- [ ] Test: "Turn on the living room lights" → tool call → light turns on

### Phase 4: AI Task (1 hour)
- [ ] `ai_task.py` — register as AI Task entity
- [ ] Test structured + unstructured generation
- [ ] Verify subentry auto-creation

### Phase 5: Polish (1–2 hours)
- [ ] Error handling (auth, timeout, rate limit)
- [ ] Reauth flow
- [ ] README with setup instructions
- [ ] `hacs.json` for HACS distribution
- [ ] `ruff format` all files
- [ ] Test with multiple LiteLLM models

**Total: ~1 day**

---

## Risks & Gotchas

### 🔴 Critical

1. **Responses API stream event fidelity** — LiteLLM must emit identical SSE events as OpenAI (`response.output_item.added`, `response.content_part.delta`, `response.function_call_arguments.delta`, etc.). If any event differs, `_transform_stream` breaks silently.
   - **Mitigation**: Test with your live proxy early. Check [LiteLLM Responses API docs](https://docs.litellm.ai/docs/response_api).

2. **Tool calling through Responses API bridge** — Non-OpenAI models (Bedrock Claude) going through LiteLLM's Responses API may have edge cases.
   - **Mitigation**: Test function calling with Bedrock specifically. Check [LiteLLM provider-specific params](https://docs.litellm.ai/docs/completion/provider_specific_params).

### 🟡 Important

3. **Base URL normalization** — OpenAI SDK behavior with trailing `/v1`. Some users will enter `https://proxy.example.com/v1`, others just `https://proxy.example.com`. Normalize in config flow.

4. **Model names from proxy** — LiteLLM returns model IDs like `bedrock-claude-4-6-sonnet`. Config UI needs to handle these gracefully.

5. **`CONF_LLM_HASS_API` must be omitted (not empty)** — Per [LLM docs](https://developers.home-assistant.io/docs/core/llm/), if no API is selected the key must be absent from config, not set to `None` or `[]`.

### 🟢 Nice to Have

6. **Provider-specific params** — LiteLLM supports `extra_body` for passthrough. Future enhancement.

7. **Cost tracking** — LiteLLM returns usage data. Could expose as entity attributes.

8. **WebSocket streaming** — LiteLLM supports `/responses` via WebSocket for lower latency. Future enhancement.

---

## `manifest.json`

```json
{
  "domain": "litellm_conversation",
  "name": "LiteLLM Conversation",
  "codeowners": ["@edgar971"],
  "config_flow": true,
  "dependencies": ["conversation", "ai_task"],
  "documentation": "https://github.com/edgar971/ha-litellm-conversation",
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "requirements": ["openai>=1.58.1"],
  "version": "1.0.0"
}
```

---

## Testing Checklist

- [ ] Config flow: valid URL + key → entry created with 2 subentries
- [ ] Config flow: invalid key → auth error shown
- [ ] Config flow: unreachable URL → connection error shown
- [ ] Config flow: model dropdown populated from proxy `/v1/models`
- [ ] Conversation: text Q&A streams response
- [ ] Conversation: tool call executes HA service (light toggle)
- [ ] Conversation: multi-turn tool loop resolves correctly
- [ ] Conversation: `CONTROL` feature only set when LLM API configured
- [ ] AI Task: unstructured text generation
- [ ] AI Task: structured JSON output with schema
- [ ] Error: proxy down → graceful "service unavailable"
- [ ] Error: 429 rate limit → retry with backoff
- [ ] Multiple proxies: two entries with different URLs work independently
- [ ] HACS: installs cleanly from custom repository
- [ ] Formatting: `ruff format` passes with zero changes

---

## Summary

LiteLLM v1.82.6 implements the full OpenAI Responses API. This makes the integration a **thin fork of `openai_conversation`** — same stream transform, same tool calling, same ChatLog integration. The only real work is:

1. Add `base_url` to config flow + client creation
2. Remove OpenAI-specific auth (org_id, OAuth)
3. Dynamic model list from proxy's `/v1/models`
4. Rename domain + classes

Everything else — the hard parts (streaming, tool calling, AI task, ChatLog integration) — is proven code from HA core that we copy unchanged.
