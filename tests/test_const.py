"""Basic tests for litellm_conversation constants and imports."""

from custom_components.litellm_conversation.const import (
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    DOMAIN,
    MAX_TOOL_ITERATIONS,
)


def test_domain():
    """Test domain constant is set."""
    assert DOMAIN == "litellm_conversation"


def test_constants_exist():
    """Test required constants are defined."""
    assert CONF_BASE_URL == "base_url"
    assert CONF_CHAT_MODEL == "chat_model"
    assert MAX_TOOL_ITERATIONS == 10
