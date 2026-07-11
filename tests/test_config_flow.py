"""Tests for the LiteLLM Conversation config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.litellm_conversation.const import CONF_BASE_URL, DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

BASE_URL = "http://localhost:4000"
API_KEY = "sk-test"
USER_INPUT = {CONF_BASE_URL: BASE_URL, "api_key": API_KEY}


def _mock_models_list(model_ids: list[str] | None = None) -> AsyncMock:
    """Mock AsyncOpenAI models.list()."""
    models = MagicMock()
    models.data = [MagicMock(id=m) for m in (model_ids or ["gpt-4o-mini", "claude-x"])]
    return AsyncMock(return_value=models)


@pytest.fixture
def mock_openai_ok():
    """Patch AsyncOpenAI so connection validation and model listing succeed."""
    with patch(
        "custom_components.litellm_conversation.config_flow.openai.AsyncOpenAI"
    ) as mock_client:
        mock_client.return_value.models.list = _mock_models_list()
        yield mock_client


async def test_user_flow_success(hass: HomeAssistant, setup_ha, mock_openai_ok) -> None:
    """Full happy path: user step -> models step -> entry created with subentries."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "models"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"chat_model": "claude-x"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data == {CONF_BASE_URL: BASE_URL, "api_key": API_KEY}
    assert entry.unique_id == BASE_URL
    subentry_types = sorted(s.subentry_type for s in entry.subentries.values())
    assert subentry_types == ["ai_task_data", "conversation"]


async def test_user_flow_duplicate_aborts(hass: HomeAssistant, setup_ha, mock_openai_ok) -> None:
    """Adding the same proxy URL twice aborts with already_configured."""
    MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        unique_id=BASE_URL,
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (
            openai.AuthenticationError("bad key", response=MagicMock(status_code=401), body=None),
            "invalid_auth",
        ),
        (openai.APIConnectionError(request=MagicMock()), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, setup_ha, side_effect, expected_error) -> None:
    """Connection validation errors map to the right form error."""
    with patch(
        "custom_components.litellm_conversation.config_flow.openai.AsyncOpenAI"
    ) as mock_client:
        mock_client.return_value.models.list = AsyncMock(side_effect=side_effect)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}


async def test_reauth_flow_updates_api_key(hass: HomeAssistant, setup_ha, mock_openai_ok) -> None:
    """Reauth flow validates and stores the new API key."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        unique_id=BASE_URL,
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch("homeassistant.config_entries.ConfigEntries.async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_key": "sk-new"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_key"] == "sk-new"
