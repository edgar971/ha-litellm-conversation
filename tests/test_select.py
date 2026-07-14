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


async def test_setup_entry_reuses_cached_model_list(hass: HomeAssistant) -> None:
    """async_setup_entry caches the model list; select platform skips a second live fetch."""
    from custom_components.litellm_conversation import select as select_module

    entry = _entry()
    hass.data[DOMAIN] = {f"{entry.entry_id}_models": ["gpt-4o-mini", "claude-x"]}

    with patch(
        "custom_components.litellm_conversation.config_flow._get_models",
        AsyncMock(side_effect=AssertionError("should not call _get_models when cached")),
    ):
        added: list = []
        await select_module.async_setup_entry(
            hass,
            MagicMock(entry_id=entry.entry_id, data={"base_url": "x", "api_key": "y"}),
            lambda entities: added.extend(entities),
        )

    assert added[0].options[1:] == ["gpt-4o-mini", "claude-x"]


async def test_async_refresh_models_updates_options(hass: HomeAssistant) -> None:
    """async_refresh_models replaces the option list and keeps a valid selection."""
    from custom_components.litellm_conversation.select import LiteLLMDreamModelSelect

    select = LiteLLMDreamModelSelect(_entry(), ["gpt-4o-mini"])
    select.hass = hass
    select.entity_id = "select.test_dream_model"
    select.async_write_ha_state = MagicMock()
    with patch.object(select, "async_get_last_state", AsyncMock(return_value=None)):
        await select.async_added_to_hass()
    await select.async_select_option("gpt-4o-mini")

    await select.async_refresh_models(["gpt-4o-mini", "new-model"])

    assert select.options == [USE_DEFAULT_OPTION, "gpt-4o-mini", "new-model"]
    assert select.current_option == "gpt-4o-mini"  # still valid, kept


async def test_async_refresh_models_falls_back_when_selection_vanishes(
    hass: HomeAssistant,
) -> None:
    """If the previously selected model disappears from the proxy, fall back to default."""
    from custom_components.litellm_conversation.select import LiteLLMDreamModelSelect

    select = LiteLLMDreamModelSelect(_entry(), ["old-model"])
    select.hass = hass
    select.entity_id = "select.test_dream_model"
    select.async_write_ha_state = MagicMock()
    with patch.object(select, "async_get_last_state", AsyncMock(return_value=None)):
        await select.async_added_to_hass()
    await select.async_select_option("old-model")

    await select.async_refresh_models(["new-model"])

    assert select.current_option == USE_DEFAULT_OPTION
    assert select.selected_model is None


async def test_refresh_dream_model_options_no_entity_returns_false(hass: HomeAssistant) -> None:
    """async_refresh_dream_model_options returns False when no select entity exists yet."""
    from custom_components.litellm_conversation.select import (
        async_refresh_dream_model_options,
    )

    hass.data.pop(DOMAIN, None)
    entry = _entry()
    entry.data = {"base_url": "x", "api_key": "y"}
    assert await async_refresh_dream_model_options(hass, entry) is False
