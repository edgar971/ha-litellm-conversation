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
    """Mock AsyncOpenAI models.list(). Pass [] explicitly for an empty proxy."""
    models = MagicMock()
    models.data = [
        MagicMock(id=m) for m in (["gpt-4o-mini", "claude-x"] if model_ids is None else model_ids)
    ]
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


async def test_user_flow_validate_connection_reused_for_models(
    hass: HomeAssistant, setup_ha, mock_openai_ok
) -> None:
    """Model list comes from the same call that validates the connection (no 2nd fetch)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["step_id"] == "models"
    # models.list was called exactly once by _validate_connection; _get_models
    # is never invoked in this path.
    assert mock_openai_ok.return_value.models.list.call_count == 1


async def test_user_flow_empty_model_list_shows_placeholder_not_fake_default(
    hass: HomeAssistant, setup_ha
) -> None:
    """A proxy with zero configured models gets a visible warning, not a silent fake default."""
    with patch(
        "custom_components.litellm_conversation.config_flow.openai.AsyncOpenAI"
    ) as mock_client:
        mock_client.return_value.models.list = _mock_models_list([])
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "models"
    assert result["description_placeholders"]["model_count"].startswith("0")
    assert "model_list" in result["description_placeholders"]["model_count"]


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


async def test_get_models_returns_empty_on_failure(hass: HomeAssistant) -> None:
    """_get_models returns [] (not a fake default model) when the fetch fails."""
    from custom_components.litellm_conversation.config_flow import _get_models

    with patch(
        "custom_components.litellm_conversation.config_flow.openai.AsyncOpenAI"
    ) as mock_client:
        mock_client.return_value.models.list = AsyncMock(side_effect=RuntimeError("boom"))
        models = await _get_models(hass, BASE_URL, API_KEY)

    assert models == []


async def test_schemas_model_options_placeholder_on_empty() -> None:
    """schemas._model_options falls back to a placeholder, never an empty dropdown."""
    from custom_components.litellm_conversation.schemas import _model_options

    assert len(_model_options([])) == 1
    assert _model_options(["a", "b"]) == [
        {"value": "a", "label": "a"},
        {"value": "b", "label": "b"},
    ]
    assert _model_options([], fallback="whisper-1")[0]["value"] == "whisper-1"
