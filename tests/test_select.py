"""Tests for the dream-model select entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.litellm_conversation.const import DOMAIN
from custom_components.litellm_conversation.select import (
    USE_DEFAULT_OPTION,
    LiteLLMDreamModelSelect,
    async_get_selected_dream_model,
)
from homeassistant.core import HomeAssistant


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry1"
    return entry


async def test_select_defaults_to_use_default_option(hass: HomeAssistant) -> None:
    """With no prior selection, the entity defaults to the AI Task default."""
    select = LiteLLMDreamModelSelect(_entry(), ["gpt-4o-mini", "claude-x"])
    select.hass = hass
    select.entity_id = "select.test_dream_model"
    with patch.object(select, "async_get_last_state", AsyncMock(return_value=None)):
        await select.async_added_to_hass()

    assert select.current_option == USE_DEFAULT_OPTION
    assert select.selected_model is None
    assert async_get_selected_dream_model(hass) is None


async def test_select_option_overrides_dream_model(hass: HomeAssistant) -> None:
    """Selecting a real model exposes it via the module-level lookup."""
    select = LiteLLMDreamModelSelect(_entry(), ["gpt-4o-mini", "claude-x"])
    select.hass = hass
    select.entity_id = "select.test_dream_model"
    select.async_write_ha_state = MagicMock()
    with patch.object(select, "async_get_last_state", AsyncMock(return_value=None)):
        await select.async_added_to_hass()

    await select.async_select_option("claude-x")

    assert select.current_option == "claude-x"
    assert select.selected_model == "claude-x"
    assert async_get_selected_dream_model(hass) == "claude-x"


async def test_select_restores_previous_choice(hass: HomeAssistant) -> None:
    """A previously selected model is restored across restarts."""
    from types import SimpleNamespace

    select = LiteLLMDreamModelSelect(_entry(), ["gpt-4o-mini", "claude-x"])
    select.hass = hass
    select.entity_id = "select.test_dream_model"
    last_state = SimpleNamespace(state="claude-x")
    with patch.object(select, "async_get_last_state", AsyncMock(return_value=last_state)):
        await select.async_added_to_hass()

    assert select.current_option == "claude-x"
    assert select.selected_model == "claude-x"


async def test_no_select_entity_registered_returns_none(hass: HomeAssistant) -> None:
    """When no select entity has been set up, the lookup returns None."""
    hass.data.pop(DOMAIN, None)
    assert async_get_selected_dream_model(hass) is None
