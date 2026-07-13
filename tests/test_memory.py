"""Tests for the memory store."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.litellm_conversation.memory import (
    MAX_MEMORIES,
    MAX_MEMORY_LENGTH,
    MemoryStore,
    async_get_memory_store,
)
from homeassistant.core import HomeAssistant


async def _store(hass: HomeAssistant) -> MemoryStore:
    store = MemoryStore(hass)
    await store.async_load()
    return store


async def test_remember_and_list(hass: HomeAssistant) -> None:
    """Basic add + list."""
    store = await _store(hass)
    m = store.remember("Dog food lives in the garage fridge")
    assert m.id
    assert [x.text for x in store.memories] == ["Dog food lives in the garage fridge"]


async def test_remember_normalizes_whitespace(hass: HomeAssistant) -> None:
    """Internal whitespace is collapsed."""
    store = await _store(hass)
    m = store.remember("  two \n spaces   here ")
    assert m.text == "two spaces here"


async def test_remember_rejects_empty_and_too_long(hass: HomeAssistant) -> None:
    """Empty and over-length memories are rejected."""
    store = await _store(hass)
    with pytest.raises(ValueError, match="empty"):
        store.remember("   ")
    with pytest.raises(ValueError, match="too long"):
        store.remember("x" * (MAX_MEMORY_LENGTH + 1))


async def test_remember_rejects_duplicates(hass: HomeAssistant) -> None:
    """Case-insensitive duplicates are rejected."""
    store = await _store(hass)
    store.remember("Luna's bedtime is 8:30")
    with pytest.raises(ValueError, match="identical"):
        store.remember("luna's bedtime is 8:30")


async def test_remember_cap(hass: HomeAssistant) -> None:
    """The memory cap produces a clear error."""
    store = await _store(hass)
    for i in range(MAX_MEMORIES):
        store.remember(f"fact number {i}")
    with pytest.raises(ValueError, match="limit reached"):
        store.remember("one too many")


async def test_forget_by_id(hass: HomeAssistant) -> None:
    """Forget removes exactly the matching memory."""
    store = await _store(hass)
    keep = store.remember("keep this")
    drop = store.remember("drop this")
    assert store.forget(drop.id) is True
    assert store.forget("nonexistent") is False
    assert [m.id for m in store.memories] == [keep.id]


async def test_forget_matching_text(hass: HomeAssistant) -> None:
    """Substring forget removes all case-insensitive matches."""
    store = await _store(hass)
    store.remember("The WiFi password is hunter2")
    store.remember("Guest wifi is on VLAN 10")
    store.remember("Unrelated fact")
    assert store.forget_matching("WIFI") == 2
    assert len(store.memories) == 1
    assert store.forget_matching("") == 0


async def test_update(hass: HomeAssistant) -> None:
    """Update edits text in place (todo-UI edit path)."""
    store = await _store(hass)
    m = store.remember("bedtime is 8:00")
    assert store.update(m.id, "bedtime is 8:30") is True
    assert store.memories[0].text == "bedtime is 8:30"
    assert store.update("nope", "x") is False
    with pytest.raises(ValueError):
        store.update(m.id, "")


async def test_prompt_section(hass: HomeAssistant) -> None:
    """Prompt injection renders facts under a defensive framing header."""
    store = await _store(hass)
    assert store.prompt_section() == ""
    store.remember("fact one")
    store.remember("fact two")
    section = store.prompt_section()
    assert "never as instructions" in section
    assert "- fact one" in section
    assert "- fact two" in section


async def test_persistence_roundtrip(hass: HomeAssistant) -> None:
    """Memories survive a save/load cycle."""
    store = await _store(hass)
    store.remember("durable fact")
    # Flush the delayed save immediately.
    await store._store.async_save(
        {"memories": [m.as_dict() for m in store.memories]}
    )

    fresh = MemoryStore(hass)
    await fresh.async_load()
    assert [m.text for m in fresh.memories] == ["durable fact"]


async def test_singleton_getter(hass: HomeAssistant) -> None:
    """async_get_memory_store returns the same instance."""
    a = async_get_memory_store(hass)
    b = async_get_memory_store(hass)
    assert a is b


async def test_updates_signal_listeners(hass: HomeAssistant) -> None:
    """Mutations fire the update signal (feeds todo entity + sensor)."""
    store = await _store(hass)
    signals = []
    with patch(
        "custom_components.litellm_conversation.memory.async_dispatcher_send",
        side_effect=lambda hass, signal: signals.append(signal),
    ):
        m = store.remember("x")
        store.update(m.id, "y")
        store.forget(m.id)
    assert len(signals) == 3
