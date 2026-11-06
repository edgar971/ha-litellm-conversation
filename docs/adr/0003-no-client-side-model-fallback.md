# 0003 — No client-side model fallback

- **Status:** Accepted
- **Date:** 2026-11-06 (formalized; decided earlier)
- **Context:** `conversation.py`, `entity.py`

## Context

Assist wants a reliable answer even when the primary model's provider errors or
rate-limits. The tempting client-side design: keep a fallback model list per
config entry, catch the failure, retry against the next model.

But the integration never talks to providers directly — it talks to a LiteLLM
proxy, and the proxy's router already implements exactly this: multiple
deployments under one model name, retries, and `fallbacks` config, applied
server-side with health checks. A second routing layer in the client would:

- duplicate policy that is visible and tunable in the proxy's `config.yaml`,
  splitting the source of truth across two places;
- hide provider health from the operator (the client quietly degrades while the
  proxy sees only partial traffic);
- distort the spend picture the new `/key/info` sensors and request tags exist
  to show, since which model actually answered would depend on client state.

## Decision

The integration sends exactly one model per request — the one selected in
config or on the subentry — with no fallback list, no retry-on-different-model,
and no client-side routing logic. Errors surface as-is: entities flip to
`unavailable` on proxy connection errors (logged once per transition) instead
of silently degrading.

## Consequences

- Reliability policy lives in one place the operator controls: the proxy's
  router config. Whatever fallbacks exist are visible in proxy logs and spend
  data, not buried in HA custom-component state.
- If the proxy is fully down, Assist fails visibly — which is the honest
  behavior, and matches the post-v2 rule that nothing degrades silently.
- Multi-model routing by context (cheap model for device control, big model
  for reasoning) stays out too unless it needs HA-specific context the proxy
  cannot see; then it would be a new decision, not an extension of this one.
- The client can't rescue a misconfigured proxy with no fallbacks — that is
  considered the operator's call to make, server-side.
