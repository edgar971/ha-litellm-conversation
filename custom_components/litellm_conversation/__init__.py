"""The LiteLLM Conversation integration."""

from __future__ import annotations

import openai
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .const import CONF_BASE_URL, DOMAIN

PLATFORMS = [Platform.CONVERSATION]
_SUBENTRY_PLATFORMS: dict[str, list[Platform]] = {
    "conversation": [Platform.CONVERSATION],
    "ai_task_data": [Platform.AI_TASK],
}

type LiteLLMConfigEntry = ConfigEntry[openai.AsyncOpenAI]


async def async_setup_entry(hass: HomeAssistant, entry: LiteLLMConfigEntry) -> bool:
    """Set up LiteLLM Conversation from a config entry."""
    base_url = entry.data[CONF_BASE_URL]
    # Normalize: strip trailing slash, ensure /v1 suffix
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"

    client = openai.AsyncOpenAI(
        api_key=entry.data[CONF_API_KEY],
        base_url=base_url,
        http_client=get_async_client(hass),
    )
    entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.CONVERSATION, Platform.AI_TASK]
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LiteLLMConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, [Platform.CONVERSATION, Platform.AI_TASK]
    )
