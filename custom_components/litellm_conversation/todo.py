"""Todo platform exposing long-term memories as a manageable list.

HA's built-in To-do panel becomes the memory management UI for free:
add item = remember, edit = correct, delete = forget. The entity reads and
writes the same MemoryStore the LLM tools and services use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .memory import SIGNAL_MEMORIES_UPDATED, MemoryStore, async_get_memory_store

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the memories todo entity."""
    store = async_get_memory_store(hass)
    await store.async_load()
    async_add_entities([LiteLLMMemoriesTodoEntity(config_entry, store)])


class LiteLLMMemoriesTodoEntity(TodoListEntity):
    """Long-term memories, manageable through HA's native To-do UI."""

    _attr_has_entity_name = True
    _attr_name = "Memories"
    _attr_icon = "mdi:brain"
    _attr_should_poll = False
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(self, entry: LiteLLMConfigEntry, store: MemoryStore) -> None:
        """Initialize the entity."""
        self._store = store
        self._attr_unique_id = f"{entry.entry_id}_memories"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "LiteLLM Proxy",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to memory updates (LLM tools / services mutate the store)."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_MEMORIES_UPDATED, self.async_write_ha_state)
        )

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return memories as todo items."""
        return [
            TodoItem(
                summary=memory.text,
                uid=memory.id,
                status=TodoItemStatus.NEEDS_ACTION,
            )
            for memory in self._store.memories
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add a memory from the UI."""
        try:
            self._store.remember(item.summary or "")
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Edit a memory from the UI.

        Marking an item completed deletes it — a 'done' memory is a
        forgotten one; keeping completed ghosts in the list has no meaning.
        """
        if item.uid is None:
            raise HomeAssistantError("Memory id missing")
        if item.status == TodoItemStatus.COMPLETED:
            self._store.forget(item.uid)
            return
        try:
            if not self._store.update(item.uid, item.summary or ""):
                raise HomeAssistantError("Memory not found")
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete memories from the UI."""
        for uid in uids:
            self._store.forget(uid)
