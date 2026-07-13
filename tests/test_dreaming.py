"""Tests for the dreaming layer (prompt builder, op application, dream flow)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.litellm_conversation.dreaming import (
    EVENT_DREAM_COMPLETED,
    apply_operations,
    async_dream,
    build_dream_prompt,
)
from custom_components.litellm_conversation.memory import (
    MemoryStore,
    async_get_memory_store,
)
from custom_components.litellm_conversation.transcripts import (
    Exchange,
    async_get_transcript_buffer,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

# --- build_dream_prompt ---


def _exchange(user: str, assistant: str) -> Exchange:
    return Exchange(user_text=user, assistant_text=assistant, conversation_id="c")


async def test_prompt_includes_memories_and_transcripts(hass: HomeAssistant) -> None:
    """Prompt carries memory ids, transcripts, and instructions."""
    store = MemoryStore(hass)
    await store.async_load()
    m = store.remember("Existing fact")

    prompt = build_dream_prompt(
        store.memories, [_exchange("remember the gate code is broken", "Noted")]
    )
    assert f"- {m.id}: Existing fact" in prompt
    assert "User: remember the gate code is broken" in prompt
    assert "operations" in prompt


def test_prompt_empty_memories_and_activity() -> None:
    """No memories -> explicit 'none'; activity digest included when given."""
    prompt = build_dream_prompt([], [_exchange("q", "a")], "Activity: door opened 3x")
    assert "Current memories: none." in prompt
    assert "Activity: door opened 3x" in prompt


# --- apply_operations ---


async def test_apply_add_update_delete(hass: HomeAssistant) -> None:
    """All three op kinds apply against the store."""
    store = MemoryStore(hass)
    await store.async_load()
    old = store.remember("Bedtime is 8:00")
    stale = store.remember("Old contractor is Bob")

    added, updated, deleted, skipped = apply_operations(
        store,
        [
            {"op": "add", "text": "Dog food is in the garage fridge", "reason": "stated"},
            {"op": "update", "id": old.id, "text": "Bedtime is 8:30", "reason": "corrected"},
            {"op": "delete", "id": stale.id, "reason": "contradicted"},
        ],
    )
    assert (added, updated, deleted, skipped) == (1, 1, 1, 0)
    texts = {m.text for m in store.memories}
    assert texts == {"Dog food is in the garage fridge", "Bedtime is 8:30"}


async def test_apply_bad_ops_skipped_not_fatal(hass: HomeAssistant) -> None:
    """Malformed/unknown ops are skipped; the rest still apply."""
    store = MemoryStore(hass)
    await store.async_load()

    added, updated, deleted, skipped = apply_operations(
        store,
        [
            {"op": "update", "id": "ghost", "text": "x", "reason": "r"},  # unknown id
            {"op": "explode", "reason": "r"},  # unknown op
            {"op": "add", "reason": "r"},  # missing text
            {"op": "add", "text": "good fact", "reason": "r"},
        ],
    )
    assert (added, updated, deleted, skipped) == (1, 0, 0, 3)
    assert store.memories[0].text == "good fact"


async def test_apply_respects_store_caps(hass: HomeAssistant) -> None:
    """A dream cannot blow past the memory cap — overflow ops are skipped."""
    store = MemoryStore(hass)
    await store.async_load()
    from custom_components.litellm_conversation.memory import MAX_MEMORIES

    for i in range(MAX_MEMORIES):
        store.remember(f"fact {i}")
    added, _, _, skipped = apply_operations(
        store, [{"op": "add", "text": "one too many", "reason": "r"}]
    )
    assert added == 0 and skipped == 1


# --- async_dream ---


def _entry(response_ops: list[dict] | None = None, usage_total: int = 500) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry1"
    sub = MagicMock()
    sub.subentry_type = "ai_task_data"
    sub.data = {"chat_model": "cheap-model"}
    entry.subentries = {"s1": sub}
    completion = MagicMock()
    completion.choices = [
        MagicMock(message=MagicMock(content=json.dumps({"operations": response_ops or []})))
    ]
    completion.usage = SimpleNamespace(
        prompt_tokens=400, completion_tokens=100, total_tokens=usage_total
    )
    entry.runtime_data.chat.completions.create = AsyncMock(return_value=completion)
    return entry


async def test_dream_noop_without_material(hass: HomeAssistant) -> None:
    """No new transcripts + no activity -> no LLM call, zero result."""
    entry = _entry()
    result = await async_dream(hass, entry)
    assert result.added == 0
    entry.runtime_data.chat.completions.create.assert_not_awaited()


async def test_dream_applies_ops_and_advances_watermark(hass: HomeAssistant) -> None:
    """A dream analyzes new exchanges, applies ops, advances the watermark."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    buffer.add_exchange("the gate code panel is broken", "I'll note that", "c1")

    entry = _entry([{"op": "add", "text": "The gate code panel is broken", "reason": "stated"}])
    events = []
    hass.bus.async_listen(EVENT_DREAM_COMPLETED, lambda e: events.append(e))

    result = await async_dream(hass, entry)
    await hass.async_block_till_done()

    assert result.added == 1
    assert result.exchanges_analyzed == 1
    assert result.tokens == 500

    store = async_get_memory_store(hass)
    assert store.memories[0].text == "The gate code panel is broken"
    # Watermark advanced: next dream sees nothing.
    assert buffer.exchanges_since_last_dream() == []
    # Event fired with summary payload.
    assert events and events[0].data["added"] == 1

    # Model came from the ai_task subentry.
    kwargs = entry.runtime_data.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "cheap-model"
    assert kwargs["response_format"]["type"] == "json_schema"


async def test_dream_dry_run_applies_nothing(hass: HomeAssistant) -> None:
    """dry_run returns proposed ops without touching store or watermark."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    buffer.add_exchange("q", "a", "c")

    entry = _entry([{"op": "add", "text": "proposed fact", "reason": "r"}])
    result = await async_dream(hass, entry, dry_run=True)

    assert result.dry_run is True
    assert result.operations == [{"op": "add", "text": "proposed fact", "reason": "r"}]
    assert result.added == 0
    store = async_get_memory_store(hass)
    assert store.memories == []
    assert buffer.exchanges_since_last_dream() != []  # watermark NOT advanced


async def test_dream_model_override(hass: HomeAssistant) -> None:
    """An explicit model overrides the subentry default."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    buffer.add_exchange("q", "a", "c")

    entry = _entry()
    await async_dream(hass, entry, model="haiku-override")
    kwargs = entry.runtime_data.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "haiku-override"


async def test_dream_llm_failure_keeps_watermark(hass: HomeAssistant) -> None:
    """LLM failure raises and does NOT advance the watermark (retry window)."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    buffer.add_exchange("q", "a", "c")

    entry = _entry()
    entry.runtime_data.chat.completions.create = AsyncMock(side_effect=Exception("proxy down"))

    with pytest.raises(HomeAssistantError, match="Dream LLM call failed"):
        await async_dream(hass, entry)
    assert len(buffer.exchanges_since_last_dream()) == 1


async def test_dream_invalid_json_raises(hass: HomeAssistant) -> None:
    """Garbage model output raises a clear error."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    buffer.add_exchange("q", "a", "c")

    entry = _entry()
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content="not json {{{"))]
    completion.usage = None
    entry.runtime_data.chat.completions.create = AsyncMock(return_value=completion)

    with pytest.raises(HomeAssistantError, match="invalid JSON"):
        await async_dream(hass, entry)
