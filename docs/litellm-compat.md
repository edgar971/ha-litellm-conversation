# LiteLLM / Bedrock Compatibility Notes

Research conducted 2026-06-26. Sources: [drop_params docs](https://docs.litellm.ai/docs/completion/drop_params), [Bedrock provider docs](https://docs.litellm.ai/docs/providers/bedrock), [input params reference](https://docs.litellm.ai/docs/completion/input).

---

## 1. `drop_params` — auto-strip unsupported params

LiteLLM raises by default when a param isn't supported by the target provider. `drop_params=True` silences that and drops the offending param instead.

### Proxy-side (recommended — not in our control)
```yaml
# config.yaml
litellm_settings:
  drop_params: true
```

### Per-model in proxy config
```yaml
model_list:
  - model_name: bedrock-claude
    litellm_params:
      model: bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
      additional_drop_params: ["response_format"]
```

### Per-request from OpenAI client (our approach)
Pass via `extra_body` — LiteLLM proxy forwards this to the underlying litellm call:
```python
extra_body={"drop_params": True}
```
`additional_drop_params` is also accepted per-request:
```python
extra_body={"additional_drop_params": ["response_format"]}
```

### Python SDK (direct litellm, not proxy)
```python
litellm.completion(..., drop_params=True)
litellm.completion(..., additional_drop_params=["response_format"])
```

---

## 2. Known Bedrock / Bedrock-Claude restrictions via LiteLLM

| Param | Behavior | Fix |
|---|---|---|
| `temperature` + `top_p` together | Bedrock rejects if both sent | Send only one |
| `tool_choice` without `tools` | Bedrock rejects | Only send `tool_choice` when `tools` is also present |
| `response_format.json_schema.strict: true` | Not supported by Bedrock | Omit `strict` field entirely |
| `logprobs` / `top_logprobs` | Not supported | Drop before sending |
| `presence_penalty` / `frequency_penalty` | Bedrock-model-dependent | Use `drop_params` or omit |
| `seed` | Limited support | Use `drop_params` or omit |

Bedrock supports JSON mode via `response_format: {type: "json_object"}` or a json_schema **without** `strict: true`.

---

## 3. Provider-agnostic model detection

LiteLLM does NOT return provider metadata in the Chat Completions response. The model field in the response echoes back whatever model string was requested.

To detect Bedrock at request time, inspect the model string:
- Bedrock native: `bedrock/anthropic.claude-*`, `bedrock/amazon.titan-*`
- Bedrock via LiteLLM alias: any configured alias — not detectable from client

**Conclusion**: don't rely on client-side detection. Use `drop_params` as the defense layer.

---

## 4. Structured output on Bedrock

Bedrock Claude supports `response_format` in two forms:
- `{"type": "json_object"}` — JSON mode, no schema enforcement
- `{"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}` — schema-guided output (**without** `strict: true`)

`strict: true` is an OpenAI-specific extension that Bedrock does not support. Omit it.

---

## 5. Best practices for a provider-agnostic LiteLLM client

**Always do:**
- Pass `extra_body={"drop_params": True}` on every request as a safety net
- Only send `temperature` OR `top_p`, not both
- Only send `tool_choice` when `tools` is also in the payload
- Omit `strict: true` from `json_schema` response_format
- Catch `openai.APIStatusError` and surface the status code for debugging

**Never hardcode:**
- Provider-specific params (e.g., `thinking`, `anthropic_version`)
- Assumption that all OpenAI params are supported
- Assumption that the proxy has `drop_params` globally enabled

**Recommended headers:**
```python
extra_headers = {
    "x-litellm-reasoning-effort": reasoning_effort,  # for models that support it
}
extra_body = {
    "drop_params": True,  # ask proxy to silently drop unsupported params
}
```
