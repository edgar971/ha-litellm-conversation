"""Tests for the memories todo entity."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.litellm_conversation.memory import MemoryStore
from custom_components.litellm_conversation.todo import LiteLLMMemoriesTodoEntity
from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


async def _entity(hass: HomeAssistant) -> LiteLLMMemoriesTodoEntity:
    store = MemoryStore(hass)
    await store.async_load()
    entry = MagicMock()
    entry.entry_id = "entry1"
    entity = LiteLLMMemoriesTodoEntity(entry, store)
    entity.hass = hass
    entity.entity_id = "todo.litellm_memories"
    return entity


async def test_memories_render_as_items(hass: HomeAssistant) -> None:
    """Stored memories appear as needs_action todo items."""
    entity = await _entity(hass)
    m = entity._store.remember("fact one")

    items = entity.todo_items
    assert len(items) == 1
    assert items[0].summary == "fact one"
    assert items[0].uid == m.id
    assert items[0].status is TodoItemStatus.NEEDS_ACTION


async def test_create_item_remembers(hass: HomeAssistant) -> None:
    """Adding an item through the UI stores a memory."""
    entity = await _entity(hass)
    await entity.async_create_todo_item(TodoItem(summary="new fact"))
    assert [m.text for m in entity._store.memories] == ["new fact"]


async def test_create_invalid_raises_ha_error(hass: HomeAssistant) -> None:
    """Store validation errors surface as HomeAssistantError (UI toast)."""
    entity = await _entity(hass)
    with pytest.raises(HomeAssistantError):
        await entity.async_create_todo_item(TodoItem(summary="   "))


async def test_update_item_edits_memory(hass: HomeAssistant) -> None:
    """Editing an item updates the memory text."""
    entity = await _entity(hass)
    m = entity._store.remember("bedtime 8:00")
    await entity.async_update_todo_item(
        TodoItem(summary="bedtime 8:30", uid=m.id, status=TodoItemStatus.NEEDS_ACTION)
    )
    assert entity._store.memories[0].text == "bedtime 8:30"


async def test_completing_item_forgets(hass: HomeAssistant) -> None:
    """Checking an item off deletes the memory (done == forgotten)."""
    entity = await _entity(hass)
    m = entity._store.remember("obsolete fact")
    await entity.async_update_todo_item(
        TodoItem(summary="obsolete fact", uid=m.id, status=TodoItemStatus.COMPLETED)
    )
    assert entity._store.memories == []


async def test_delete_items_forgets(hass: HomeAssistant) -> None:
    """Deleting items removes the memories."""
    entity = await _entity(hass)
    a = entity._store.remember("a")
    b = entity._store.remember("b")
    entity._store.remember("c")
    await entity.async_delete_todo_items([a.id, b.id])
    assert [m.text for m in entity._store.memories] == ["c"]


async def test_update_unknown_uid_raises(hass: HomeAssistant) -> None:
    """Editing a vanished memory errors cleanly."""
    entity = await _entity(hass)
    with pytest.raises(HomeAssistantError, match="not found"):
        await entity.async_update_todo_item(
            TodoItem(summary="x", uid="ghost", status=TodoItemStatus.NEEDS_ACTION)
        )
