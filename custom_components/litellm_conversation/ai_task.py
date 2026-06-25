"""LiteLLM AI Task entity."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.ai_task import (
    AITaskEntity,
    AITaskEntityFeature,
    GenerateDataTask,
)
from homeassistant.components.conversation import ChatLog
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import LiteLLMBaseLLMEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities from a config entry."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "ai_task_data":
            continue
        async_add_entities(
            [LiteLLMAITaskEntity(config_entry, subentry)]
        )


class LiteLLMAITaskEntity(LiteLLMBaseLLMEntity, AITaskEntity):
    """LiteLLM AI Task entity."""

    _attr_supported_features = AITaskEntityFeature.GENERATE_DATA

    async def _async_generate_data(
        self,
        task: GenerateDataTask,
        chat_log: ChatLog,
    ) -> None:
        """Generate data for an AI task."""
        await self._async_handle_chat_log(
            chat_log,
            structure_name=task.structure_name,
            structure=task.structure,
        )
