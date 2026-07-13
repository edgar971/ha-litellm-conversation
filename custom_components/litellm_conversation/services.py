"""Services for the LiteLLM Conversation integration.

litellm_conversation.remember / .forget — automation-driven memory writes,
e.g. saving a contractor quote when a calendar event completes.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .memory import async_get_memory_store

SERVICE_REMEMBER = "remember"
SERVICE_FORGET = "forget"
SERVICE_DREAM = "dream"
SERVICE_CLEAR_TRANSCRIPTS = "clear_transcripts"

_TEXT_SCHEMA = vol.Schema({vol.Required("text"): str})
_DREAM_SCHEMA = vol.Schema(
    {
        vol.Optional("model"): str,
        vol.Optional("include_activity", default=False): bool,
        vol.Optional("dry_run", default=False): bool,
    }
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_REMEMBER):
        return

    async def _remember(call: ServiceCall) -> ServiceResponse:
        store = async_get_memory_store(hass)
        await store.async_load()
        try:
            memory = store.remember(call.data["text"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        return {"id": memory.id, "remembered": memory.text}

    async def _forget(call: ServiceCall) -> ServiceResponse:
        store = async_get_memory_store(hass)
        await store.async_load()
        removed = store.forget_matching(call.data["text"])
        if not removed:
            raise ServiceValidationError("No memories matched that text")
        return {"removed": removed}

    async def _dream(call: ServiceCall) -> ServiceResponse:
        from datetime import timedelta

        from homeassistant.util import dt as dt_util

        from .activity import async_build_activity_digest
        from .dreaming import async_dream
        from .transcripts import async_get_transcript_buffer

        entry = _get_loaded_entry(hass)

        activity_digest = None
        if call.data["include_activity"]:
            buffer = async_get_transcript_buffer(hass)
            await buffer.async_load()
            start = (
                dt_util.parse_datetime(buffer.last_dream_at)
                if buffer.last_dream_at
                else dt_util.now() - timedelta(days=1)
            ) or dt_util.now() - timedelta(days=1)
            activity_digest = await async_build_activity_digest(hass, start, dt_util.now())

        result = await async_dream(
            hass,
            entry,
            model=call.data.get("model"),
            activity_digest=activity_digest,
            dry_run=call.data["dry_run"],
        )
        return result.as_dict()

    async def _clear_transcripts(call: ServiceCall) -> ServiceResponse:
        from .transcripts import async_get_transcript_buffer

        buffer = async_get_transcript_buffer(hass)
        await buffer.async_load()
        return {"removed": buffer.clear()}

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMEMBER,
        _remember,
        schema=_TEXT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORGET,
        _forget,
        schema=_TEXT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DREAM,
        _dream,
        schema=_DREAM_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_TRANSCRIPTS,
        _clear_transcripts,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.OPTIONAL,
    )


def _get_loaded_entry(hass: HomeAssistant):
    """Return the loaded LiteLLM config entry (dream needs the client)."""
    from homeassistant.config_entries import ConfigEntryState

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise ServiceValidationError("No loaded LiteLLM Conversation config entry")
