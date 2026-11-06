# 0001 — Chat Completions, not the Responses API

- **Status:** Accepted
- **Date:** 2026-06-26 (compatibility research; re-affirmed when code interpreter was rejected)
- **Context:** [`docs/litellm-compat.md`](../litellm-compat.md); `conversation.py`, `ai_task.py`

## Context

Every generation path in this integration goes through a LiteLLM proxy to
whatever provider the operator configured — including Amazon Bedrock. The
compatibility research (2026-06-26) found that providers reachable through
LiteLLM diverge sharply on request params: Bedrock rejects `temperature` and
`top_p` together, rejects `tool_choice` without `tools`, does not support
`response_format.json_schema.strict: true`, `logprobs`, or `seed`; and LiteLLM
returns no provider metadata in responses (the model field just echoes the
request), so the client cannot detect the provider reliably.

The OpenAI Responses API is the newer surface, with capabilities like built-in
web search and code interpreter. But those capabilities are Responses-API-only
and largely OpenAI-platform-only: Bedrock deployments do not have them, and a
provider-agnostic bridge cannot assume them. Chat Completions is the lowest
common denominator every LiteLLM provider implements.

## Decision

All generation uses `/v1/chat/completions` via the OpenAI Python client. Per-request
hardening from the research doc applies everywhere:

- `extra_body={"drop_params": True}` as a safety net (never assume proxy-global `drop_params`);
- send `temperature` **or** `top_p`, never both; `tool_choice` only alongside `tools`;
- structured output via `json_schema` response_format with `strict` omitted entirely.

Features that require the Responses API are rejected rather than half-supported —
code interpreter is explicitly out (see roadmap "Decided / historical").

## Consequences

- One request shape works across Bedrock, Anthropic, OpenAI and anything else
  LiteLLM fronts; provider quirks degrade by dropping params, not by crashing.
- No server-side Responses tools: web search is a LiteLLM passthrough body
  param instead, and code interpreter stays out unless the repo ever drops
  Bedrock compatibility.
- `drop_params` silently drops what it drops — debugging unsupported behavior
  means checking what the provider actually received, not just what we sent.
- If the ecosystem eventually deprecates Chat Completions, every call site here
  migrates at once; that is the accepted future cost.
