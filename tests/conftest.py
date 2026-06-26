"""Pytest configuration for ha-litellm-conversation tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def mock_config_entry_data():
    """Return minimal config entry data for tests."""
    return {
        "api_key": "test-api-key",
        "base_url": "http://localhost:11434",
    }
