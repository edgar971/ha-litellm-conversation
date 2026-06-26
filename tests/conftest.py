"""Pytest configuration for ha-litellm-conversation tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield


@pytest.fixture
def mock_config_entry_data():
    """Return minimal config entry data for tests."""
    return {
        "api_key": "test-api-key",
        "base_url": "http://localhost:11434",
    }


@pytest.fixture
def mock_openai_client():
    """Return a mocked AsyncOpenAI client."""
    with patch(
        "custom_components.litellm_conversation.openai.AsyncOpenAI"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        yield mock_client
