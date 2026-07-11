"""Pytest configuration for ha-litellm-conversation tests."""

from __future__ import annotations

import pytest
import pytest_asyncio

from homeassistant.setup import async_setup_component


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest_asyncio.fixture
async def setup_ha(hass):
    """Set up core homeassistant component (required by conversation/ai_task deps)."""
    assert await async_setup_component(hass, "homeassistant", {})
    return hass


@pytest.fixture
def mock_config_entry_data():
    """Return minimal config entry data for tests."""
    return {
        "api_key": "test-api-key",
        "base_url": "http://localhost:4000",
    }
