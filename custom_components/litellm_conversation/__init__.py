"""The LiteLLM Conversation integration."""

from __future__ import annotations

import openai

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.httpx_client import get_async_client

from .const import CONF_BASE_URL, LOGGER
from .const import DOMAIN as DOMAIN
from .extended_tools import async_register_extended_api
from .util import normalize_base_url

# This integration is config-entry only — no YAML configuration is
# supported. Declaring this explicitly (instead of leaving it implicit)
# silences hassfest's CONFIG_SCHEMA warning, which otherwise fires on every
# integration that defines async_setup without a schema.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = (
    Platform.CONVERSATION,
    Platform.AI_TASK,
    Platform.SENSOR,
    Platform.STT,
    Platform.TTS,
)

type LiteLLMConfigEntry = ConfigEntry[openai.AsyncOpenAI]


async def async_setup_entry(hass: HomeAssistant, entry: LiteLLMConfigEntry) -> bool:
    """Set up LiteLLM Conversation from a config entry."""
    base_url = normalize_base_url(entry.data[CONF_BASE_URL])

    client = openai.AsyncOpenAI(
        api_key=entry.data[CONF_API_KEY],
        base_url=base_url,
        http_client=get_async_client(hass),
    )

    # Validate connection at setup so a bad key/URL surfaces as a reauth /
    # retry flow instead of a first-message failure.
    try:
        await client.with_options(timeout=10.0).models.list()
    except openai.AuthenticationError as err:
        raise ConfigEntryAuthFailed(err) from err
    except openai.OpenAIError as err:
        raise ConfigEntryNotReady(err) from err

    entry.runtime_data = client

    async_register_extended_api(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    LOGGER.info(
        "LiteLLM Conversation integration loaded successfully (entry_id=%s, base_url=%s)",
        entry.entry_id,
        base_url,
    )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: LiteLLMConfigEntry) -> None:
    """Handle options update — reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LiteLLMConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
