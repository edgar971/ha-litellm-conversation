# 0002 — v2.0.0 removes dreaming and long-term memory

- **Status:** Accepted
- **Date:** 2026-11-05 (v2.0.0 tag)
- **Context:** commits `3fc55aa` / `4172b94`; CHANGELOG v2.0.0 "Removed" notes

## Context

v1.5.0 shipped a long-term memory layer (a Store-backed `MemoryStore`, a
`todo.*_memories` management UI, `remember`/`forget`/`list_memories` tools and
per-turn prompt injection). v1.6.x shipped "dreaming" on top of it: a
transcript buffer, a nightly consolidation pass driven by one structured LLM
call, a capture switch, a dream-model select, a `last_dream` sensor and a
nightly blueprint.

Two signals killed them:

- **The dogfooding signal.** While running the maintainer's own instance, the
  proxy key sat at 401 unnoticed — background subsystems that fire on their own
  schedule fail silently in exactly the way nobody sees until much later. Every
  autonomous layer adds a failure surface with no user in the loop to notice.
- **Scope discipline.** The integration's actual job is being a good LiteLLM
  proxy bridge: conversation, AI Task, STT/TTS, sensors, extended tools. The
  memory subsystems were a second product living inside it — extra platforms,
  services, storage files, blueprints and translations to maintain, with their
  own quality surface (serialization, device grouping, diagnostics) that the
  v1.6.2 release existed purely to patch.

Meanwhile Home Assistant gained a native seam for exactly this: the MCP
integration can attach any memory/RAG MCP server to these agents through the
LLM API selector, with no code in this repo.

## Decision

v2.0.0 (breaking) removes both subsystems outright — modules, platforms,
entities, services, blueprint and injection — rather than deprecating them in
place. Orphaned entities are cleaned up automatically on the first restart;
automations calling `dream`/`clear_transcripts`/`remember`/`forget` fail loudly
until edited (documented upgrade guidance). The recommended replacement is HA's
MCP integration plus a memory MCP server of the user's choice.

## Consequences

- Much smaller surface: four platforms' worth of entities, two services files'
  worth of actions and the nightly LLM spend are gone; the proxy bridge stays
  sharp.
- Breaking for users who built on it. Accepted as a v2.0.0 cost; guidance is in
  the changelog and release notes.
- The silent-failure lesson generalizes: anything here that runs without a user
  in the loop (the spend-sensor coordinator, entity availability flips) must be
  observable — sensors go `unavailable`, errors log once per transition.
- Precedent for future capability requests: if HA has or grows a native seam
  (MCP, Assist), prefer wiring to it over building a layer inside the
  integration.
