"""Constants for the LiteLLM Conversation integration."""

DOMAIN = "litellm_conversation"

CONF_BASE_URL = "base_url"
CONF_PROMPT = "prompt"
CONF_TEMPERATURE = "temperature"
CONF_TOP_P = "top_p"
CONF_MAX_TOKENS = "max_tokens"
CONF_CHAT_MODEL = "chat_model"

DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_CHAT_MODEL = "gpt-4o-mini"

RECOMMENDED_TEMPERATURE = 1.0
RECOMMENDED_TOP_P = 1.0
RECOMMENDED_MAX_TOKENS = 4096

MAX_TOOL_ITERATIONS = 10
