"""Tests for the remember/forget services."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.litellm_conversation.const import DOMAIN
from custom_components.litellm_conversation.memory import async_get_memory_store
from custom_components.litellm_conversation.services import async_register_services
from custom_components.litellm_conversation.transcripts import (
    async_get_transcript_buffer,
)
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


# --- dream + clear_transcripts services (v1.6.0) ---


def _dream_entry(ops: list[dict] | None = None) -> MagicMock:
    from homeassistant.config_entries import ConfigEntryState

    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.state = ConfigEntryState.LOADED
    sub = MagicMock()
    sub.subentry_type = "ai_task_data"
    sub.data = {"chat_model": "cheap-model"}
    entry.subentries = {"s1": sub}
    completion = MagicMock()
    completion.choices = [
        MagicMock(message=MagicMock(content=json.dumps({"operations": ops or []})))
    ]
    completion.usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    entry.runtime_data.chat.completions.create = AsyncMock(return_value=completion)
    return entry


async def test_dream_service(hass: HomeAssistant) -> None:
    """The dream service runs a dream against the loaded entry."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    buffer.add_exchange("the mailbox key is in the junk drawer", "Noted!", "c")

    entry = _dream_entry(
        [{"op": "add", "text": "Mailbox key is in the junk drawer", "reason": "stated"}]
    )
    with patch.object(hass.config_entries, "async_entries", return_value=[entry]):
        response = await hass.services.async_call(
            DOMAIN, "dream", {}, blocking=True, return_response=True
        )

    assert response["added"] == 1
    assert response["exchanges_analyzed"] == 1

    store = async_get_memory_store(hass)
    assert store.memories[0].text == "Mailbox key is in the junk drawer"


async def test_dream_service_dry_run(hass: HomeAssistant) -> None:
    """dry_run returns ops without applying."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    buffer.add_exchange("q", "a", "c")

    entry = _dream_entry([{"op": "add", "text": "proposal", "reason": "r"}])
    with patch.object(hass.config_entries, "async_entries", return_value=[entry]):
        response = await hass.services.async_call(
            DOMAIN, "dream", {"dry_run": True}, blocking=True, return_response=True
        )

    assert response["dry_run"] is True
    assert response["operations"] == [{"op": "add", "text": "proposal", "reason": "r"}]
    store = async_get_memory_store(hass)
    assert store.memories == []


async def test_dream_service_no_entry(hass: HomeAssistant) -> None:
    """No loaded entry -> clear validation error."""
    with (
        patch.object(hass.config_entries, "async_entries", return_value=[]),
        pytest.raises(ServiceValidationError, match="No loaded"),
    ):
        await hass.services.async_call(DOMAIN, "dream", {}, blocking=True, return_response=True)


async def test_clear_transcripts_service(hass: HomeAssistant) -> None:
    """clear_transcripts wipes the buffer and reports the count."""
    buffer = async_get_transcript_buffer(hass)
    await buffer.async_load()
    buffer.add_exchange("a", "b", "c")
    buffer.add_exchange("d", "e", "f")

    response = await hass.services.async_call(
        DOMAIN, "clear_transcripts", {}, blocking=True, return_response=True
    )
    assert response == {"removed": 2}
    assert buffer.exchange_count == 0


# --- refresh_models service ---


async def test_refresh_models_service_no_select_entity(hass: HomeAssistant) -> None:
    """refresh_models raises a clear validation error when the select entity isn't loaded."""
    entry = _dream_entry()
    with (
        patch.object(hass.config_entries, "async_entries", return_value=[entry]),
        pytest.raises(ServiceValidationError, match="dream model select entity"),
    ):
        await hass.services.async_call(
            DOMAIN, "refresh_models", {}, blocking=True, return_response=True
        )


async def test_refresh_models_service_updates_entity(hass: HomeAssistant) -> None:
    """refresh_models fetches fresh models and updates the select entity."""
    from custom_components.litellm_conversation.select import LiteLLMDreamModelSelect

    entry = _dream_entry()
    entry.data = {"base_url": "http://localhost:4000", "api_key": "sk-test"}

    select = LiteLLMDreamModelSelect(entry, ["old-model"])
    select.hass = hass
    select.entity_id = "select.test_dream_model"
    select.async_write_ha_state = MagicMock()
    with patch.object(select, "async_get_last_state", AsyncMock(return_value=None)):
        await select.async_added_to_hass()

    with (
        patch.object(hass.config_entries, "async_entries", return_value=[entry]),
        patch(
            "custom_components.litellm_conversation.config_flow._get_models",
            AsyncMock(return_value=["fresh-model"]),
        ),
    ):
        response = await hass.services.async_call(
            DOMAIN, "refresh_models", {}, blocking=True, return_response=True
        )

    assert response == {"refreshed": True}
    assert select.options == ["Use AI Task default", "fresh-model"]
