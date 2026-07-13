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

_TEXT_SCHEMA = vol.Schema({vol.Required("text"): str})


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
