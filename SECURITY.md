# Security policy

This integration sends your Home Assistant conversations, device history and
camera snapshots to a LiteLLM proxy you configure, and lets the model call
Home Assistant services back. Reports about either direction are welcome and
taken seriously.

## Supported versions

Fixes land on `main` and ship in a patch release of the latest minor version.
Older minor lines (the 1.x series) are not patched: upgrade instead.

| Version | Supported |
|---|---|
| The latest 2.x release | ✅ |
| 1.x and older | ❌ |
| `main` | ✅ (unreleased) |

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: **Security → Report a
vulnerability** on
<https://github.com/edgar971/ha-litellm-conversation/security/advisories/new>.
Please do not open a public issue, and do not test against someone else's
deployment.

A useful report includes:

- what an attacker gains, and from where (a prompt, the proxy, a HA service
  call, the network path to the proxy);
- the smallest reproduction you have, against which version or commit;
- your Home Assistant and integration versions.

Expect an acknowledgement within a few days. Please give us a reasonable
window to ship a fix before writing it up publicly.

## Existing mitigations

These are deliberate design choices, not exhaustive — a bypass of one is still
a reportable vulnerability:

- **SSRF guard** on the `fetch_url` extended tool: URLs resolving to
  private/loopback ranges are refused (`extended_tools.py`).
- **Exposed-entity gating**: entity-scoped tools (camera analysis, history)
  only reach entities marked exposed to Assist.
- **No fetching of remote image URLs**: `ai_task.generate_image` accepts
  `b64_json` responses only and rejects URL-only responses, so the integration
  never fetches an arbitrary URL handed back by the proxy (`ai_task.py`).
- **Service-call blocklist** for `call_service`, plus prompt-injection
  hardening passes on the extended tools (`fix(security)` commits in history).
- **API key hygiene**: key inputs are masked, never pre-filled on
  reconfigure; diagnostics exports redact the key.

## Out of scope

- A malicious or compromised LiteLLM proxy: you chose it, and it already sees
  everything the integration sends. Abuse *beyond* what the proxy could do
  with its own data (e.g. pivoting into HA) is in scope.
- Prompt injection that only makes the model say rude things to the user.
  Injection that reaches a privileged surface (a blocked service call, a
  non-exposed entity, an SSR'd internal URL) is in scope.
- Denial of service through sheer volume against your own proxy.
- Reports from a scanner without a demonstrated impact on this integration.
