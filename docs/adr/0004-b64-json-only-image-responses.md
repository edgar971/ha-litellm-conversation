# 0004 — `b64_json` only for image generation responses

- **Status:** Accepted
- **Date:** 2026-11-06 (shipped with issue #4, commit `b3f89f0`)
- **Context:** `ai_task.py` (`generate_image`); [`SECURITY.md`](../../SECURITY.md) mitigations list

## Context

`ai_task.generate_image` calls the LiteLLM proxy's `/v1/images/generations`.
That endpoint can answer in two shapes: `b64_json` (the image bytes, base64, in
the response body) or `url` (a link to fetch the image from somewhere — often
provider object storage with a presigned URL).

Accepting the `url` shape would mean Home Assistant issuing an outbound HTTP
GET to a URL chosen by the proxy/provider stack, not by the user. That is a
classic SSRF surface: a compromised or misconfigured proxy (or anything able to
influence its response) could point HA at internal addresses — exactly the
class this repo already refuses on the other side of the fence, in the
`fetch_url` extended tool, which rejects URLs resolving to private/loopback
ranges. It also leaks the generated image's location: presigned links expire
unexpectedly for downstream consumers and are usable by anyone holding them.

## Decision

The integration requests `response_format: "b64_json"` and **rejects URL-only
responses with a clean error** — it never fetches a remote image URL, even one
that looks harmless. Providers that report token/usage data in the response
feed the daily usage sensors via `SIGNAL_USAGE_UPDATED`; providers without
usage (e.g. Bedrock SD) simply skip the signal.

## Consequences

- The SSRF posture stays closed: no code path in this integration fetches a
  URL it did not get from the user, with the sole guarded exception of
  `fetch_url` itself.
- A provider that can only return URLs is unsupported through this path and
  fails with an actionable error rather than silently working — accepted cost.
- Image bytes live in HA's own attachment/handling flow: no expiring presigned
  links surfacing in dashboards, nothing usable by whoever happens to hold a
  link.
- Base64 bodies are larger on the wire than a URL would be; irrelevant at
  single-image generation sizes over a LAN.
