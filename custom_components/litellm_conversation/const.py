"""Constants for the LiteLLM Conversation integration."""

import logging

DOMAIN = "litellm_conversation"

LOGGER = logging.getLogger(__package__)

CONF_BASE_URL = "base_url"
CONF_PROMPT = "prompt"
CONF_TEMPERATURE = "temperature"
CONF_TOP_P = "top_p"
CONF_MAX_TOKENS = "max_tokens"
CONF_CHAT_MODEL = "chat_model"
CONF_REASONING_EFFORT = "reasoning_effort"

REASONING_EFFORT_OPTIONS = ["none", "low", "medium", "high"]

DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_CHAT_MODEL = "gpt-4o-mini"

RECOMMENDED_CHAT_MODEL = "gpt-4o-mini"
RECOMMENDED_TEMPERATURE = 1.0
RECOMMENDED_TOP_P = 1.0
RECOMMENDED_MAX_TOKENS = 4096

MAX_TOOL_ITERATIONS = 10
