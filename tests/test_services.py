"""Tests for the remember/forget services."""

from __future__ import annotations

import pytest

from custom_components.litellm_conversation.const import DOMAIN
from custom_components.litellm_conversation.memory import async_get_memory_store
from custom_components.litellm_conversation.services import async_register_services
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture(autouse=True)
def _register(hass: HomeAssistant) -> None:
    async_register_services(hass)
    # Idempotent — second call must not raise.
    async_register_services(hass)


async def test_remember_service(hass: HomeAssistant) -> None:
    """The remember service stores a memory and returns it."""
    response = await hass.services.async_call(
        DOMAIN,
        "remember",
        {"text": "Contractor quote: $10,196"},
        blocking=True,
        return_response=True,
    )
    assert response["remembered"] == "Contractor quote: $10,196"

    store = async_get_memory_store(hass)
    assert [m.text for m in store.memories] == ["Contractor quote: $10,196"]


async def test_forget_service(hass: HomeAssistant) -> None:
    """The forget service removes matching memories."""
    store = async_get_memory_store(hass)
    await store.async_load()
    store.remember("WiFi password is hunter2")

    response = await hass.services.async_call(
        DOMAIN,
        "forget",
        {"text": "wifi"},
        blocking=True,
        return_response=True,
    )
    assert response == {"removed": 1}
    assert store.memories == []


async def test_remember_service_validation_error(hass: HomeAssistant) -> None:
    """Invalid memory text raises ServiceValidationError."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "remember", {"text": "   "}, blocking=True, return_response=True
        )


async def test_forget_service_no_match(hass: HomeAssistant) -> None:
    """Forgetting an unknown fragment raises ServiceValidationError."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "forget", {"text": "never stored"}, blocking=True, return_response=True
        )
