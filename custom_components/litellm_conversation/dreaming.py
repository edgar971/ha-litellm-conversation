"""The dreaming layer: background memory consolidation.

One LLM call analyzes recent conversation transcripts (plus optionally a
household-activity digest) against the current memory list and returns
add/update/delete operations, which are applied to the MemoryStore. Named
after the consolidation phase of sleep — and ChatGPT's memory architecture,
which pairs a hot-path memory tool with background consolidation.

Scheduling is deliberately NOT built in: the litellm_conversation.dream
service is called from user automations (HA is the scheduler).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL, LOGGER, SIGNAL_USAGE_UPDATED
from .memory import MemoryStore
from .transcripts import Exchange

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry

DREAM_MAX_TOKENS = 2000
EVENT_DREAM_COMPLETED = "litellm_conversation_dream_completed"

DREAM_SYSTEM_PROMPT = """\
You are the memory-consolidation process for a household voice assistant.
Analyze the conversation transcripts (and household activity, if provided)
and maintain the long-term memory list.

Rules:
- Only durable facts: stable preferences, corrections, recurring patterns,
  household facts (locations of things, schedules, names, decisions).
- NEVER store transient state ("the lights are on"), one-off requests,
  secrets, codes, or passwords.
- Prefer UPDATE over ADD when an existing memory covers the same subject.
- CONSOLIDATE: if several memories cover one subject, merge them (update
  one, delete the others).
- DELETE memories contradicted by newer information or clearly stale.
- Each memory must be a single short sentence, max 300 characters.
- An empty operations list is a normal outcome — most conversations
  contain nothing worth remembering. Do not invent facts.
"""

# Structured-output schema for the dream response.
DREAM_OPS_SCHEMA = vol.Schema(
    {
        vol.Required("operations"): [
            vol.Schema(
                {
                    vol.Required("op"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=["add", "update", "delete"])
                    ),
                    vol.Optional("id"): str,
                    vol.Optional("text"): str,
                    vol.Required("reason"): str,
                }
            )
        ]
    }
)


@dataclass
class DreamResult:
    """Outcome of one dream."""

    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    operations: list[dict[str, Any]] | None = None
    exchanges_analyzed: int = 0
    tokens: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable summary."""
        return {
            "added": self.added,
            "updated": self.updated,
            "deleted": self.deleted,
            "skipped": self.skipped,
            "exchanges_analyzed": self.exchanges_analyzed,
            "tokens": self.tokens,
            "dry_run": self.dry_run,
            "operations": self.operations or [],
        }


def build_dream_prompt(
    memories: list[Any],
    exchanges: list[Exchange],
    activity_digest: str | None = None,
) -> str:
    """Assemble the dream user prompt (pure function, unit-testable)."""
    parts: list[str] = []

    if memories:
        parts.append("Current memories (id: text):")
        parts.extend(f"- {m.id}: {m.text}" for m in memories)
    else:
        parts.append("Current memories: none.")

    parts.append("\nConversation transcripts since the last dream:")
    for e in exchanges:
        parts.append(f"[{e.when}]\nUser: {e.user_text}\nAssistant: {e.assistant_text}")

    if activity_digest:
        parts.append("\nHousehold activity during this period:")
        parts.append(activity_digest)

    parts.append(
        "\nReturn the operations needed to keep the memory list accurate "
        "and concise. Reference existing memory ids for update/delete."
    )
    return "\n".join(parts)


def apply_operations(
    store: MemoryStore, operations: list[dict[str, Any]]
) -> tuple[int, int, int, int]:
    """Apply dream ops to the store. Returns (added, updated, deleted, skipped).

    Per-op failures are logged and skipped, never fatal — one malformed op
    must not lose the rest of the dream.
    """
    added = updated = deleted = skipped = 0
    valid_ids = {m.id for m in store.memories}

    for op in operations:
        kind = op.get("op")
        try:
            if kind == "add":
                store.remember(op["text"])
                added += 1
            elif kind == "update":
                if op.get("id") in valid_ids and store.update(op["id"], op["text"]):
                    updated += 1
                else:
                    raise ValueError(f"unknown memory id {op.get('id')!r}")
            elif kind == "delete":
                if op.get("id") in valid_ids and store.forget(op["id"]):
                    deleted += 1
                else:
                    raise ValueError(f"unknown memory id {op.get('id')!r}")
            else:
                raise ValueError(f"unknown op {kind!r}")
        except (ValueError, KeyError, TypeError) as err:
            LOGGER.warning("Dream operation skipped (%s): %s", err, op)
            skipped += 1

    return added, updated, deleted, skipped


async def async_dream(
    hass: HomeAssistant,
    entry: LiteLLMConfigEntry,
    *,
    model: str | None = None,
    activity_digest: str | None = None,
    dry_run: bool = False,
) -> DreamResult:
    """Run one dream: analyze new transcripts, consolidate memories.

    Serialized per HA instance — concurrent calls (e.g. a dashboard button
    pressed during the nightly automation) queue rather than double-apply.
    """
    from .const import DOMAIN

    lock = hass.data.setdefault(DOMAIN, {}).setdefault("dream_lock", asyncio.Lock())
    async with lock:
        return await _async_dream_locked(
            hass, entry, model=model, activity_digest=activity_digest, dry_run=dry_run
        )


async def _async_dream_locked(
    hass: HomeAssistant,
    entry: LiteLLMConfigEntry,
    *,
    model: str | None = None,
    activity_digest: str | None = None,
    dry_run: bool = False,
) -> DreamResult:
    """Dream body (call via async_dream, which holds the lock)."""
    from json import JSONDecodeError

    from voluptuous_openapi import convert

    from homeassistant.helpers import llm as ha_llm
    from homeassistant.util.json import json_loads

    from .memory import async_get_memory_store
    from .transcripts import async_get_transcript_buffer

    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    store = async_get_memory_store(hass)
    await store.async_load()

    exchanges = buffer.exchanges_since_last_dream()
    if not exchanges and not activity_digest:
        LOGGER.debug("Dream skipped: nothing new to analyze")
        return DreamResult(dry_run=dry_run)

    if model is None:
        for subentry in entry.subentries.values():
            if subentry.subentry_type == "ai_task_data":
                model = subentry.data.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
                break
        else:
            model = DEFAULT_CHAT_MODEL

    prompt = build_dream_prompt(store.memories, exchanges, activity_digest)
    schema = convert(DREAM_OPS_SCHEMA, custom_serializer=ha_llm.selector_serializer)

    try:
        response = await entry.runtime_data.chat.completions.create(
            model=model,
            max_tokens=DREAM_MAX_TOKENS,
            messages=[
                {"role": "system", "content": DREAM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "memory_operations", "schema": schema},
            },
            extra_body={"drop_params": True},
        )
    except Exception as err:
        raise HomeAssistantError(f"Dream LLM call failed: {err}") from err

    try:
        parsed = json_loads(response.choices[0].message.content or "{}")
        operations = parsed.get("operations", [])
    except (JSONDecodeError, AttributeError) as err:
        raise HomeAssistantError(f"Dream returned invalid JSON: {err}") from err

    result = DreamResult(
        operations=operations,
        exchanges_analyzed=len(exchanges),
        dry_run=dry_run,
    )
    if usage := getattr(response, "usage", None):
        result.tokens = usage.total_tokens
        from homeassistant.helpers.dispatcher import async_dispatcher_send

        async_dispatcher_send(
            hass,
            f"{SIGNAL_USAGE_UPDATED}_{entry.entry_id}",
            {
                "model": model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            },
        )

    if not dry_run:
        result.added, result.updated, result.deleted, result.skipped = apply_operations(
            store, operations
        )
        buffer.mark_dreamed()

    LOGGER.info(
        "Dream complete: %d exchanges -> +%d ~%d -%d (skipped %d, dry_run=%s)",
        result.exchanges_analyzed,
        result.added,
        result.updated,
        result.deleted,
        result.skipped,
        dry_run,
    )
    hass.bus.async_fire(EVENT_DREAM_COMPLETED, result.as_dict())
    return result
