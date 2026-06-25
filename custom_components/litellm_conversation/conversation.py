"""LiteLLM Conversation agent."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.components.conversation import (
    ChatLog,
    ConversationEntityFeature,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_PROMPT, DOMAIN
from .entity import LiteLLMBaseLLMEntity

import openai
from homeassistant.const import CONF_LLM_HASS_API


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up conversation entities from a config entry."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "conversation":
            continue
        async_add_entities(
            [LiteLLMConversationEntity(config_entry, subentry)]
        )


class LiteLLMConversationEntity(LiteLLMBaseLLMEntity):
    """LiteLLM conversation agent entity."""

    _attr_supports_streaming = True

    @property
    def supported_features(self) -> ConversationEntityFeature:
        """Return supported features."""
        if self.subentry.data.get(CONF_LLM_HASS_API):
            return ConversationEntityFeature.CONTROL
        return ConversationEntityFeature(0)

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Handle a message."""
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context(DOMAIN),
            self.subentry.data.get(CONF_LLM_HASS_API),
            self.subentry.data.get(CONF_PROMPT),
            user_input.extra_system_prompt,
        )
        await self._async_handle_chat_log(chat_log)
        return chat_log.as_conversation_result()
