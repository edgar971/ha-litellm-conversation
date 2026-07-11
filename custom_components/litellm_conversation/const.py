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
CONF_WEB_SEARCH = "web_search"
CONF_WEB_SEARCH_CONTEXT_SIZE = "web_search_context_size"
CONF_GUARDRAILS = "guardrails"
CONF_STT_MODEL = "stt_model"
CONF_TTS_MODEL = "tts_model"
CONF_TTS_VOICE = "tts_voice"

REASONING_EFFORT_OPTIONS = ["none", "low", "medium", "high"]
WEB_SEARCH_CONTEXT_OPTIONS = ["low", "medium", "high"]

DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 1.0
DEFAULT_MAX_TOKENS = 4096
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_WEB_SEARCH_CONTEXT_SIZE = "medium"
DEFAULT_STT_MODEL = "whisper-1"
DEFAULT_TTS_MODEL = "tts-1"
DEFAULT_TTS_VOICE = "alloy"

TTS_VOICES = ["alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]

MAX_TOOL_ITERATIONS = 10

# Dispatcher signal for usage stats updates (sensor platform).
SIGNAL_USAGE_UPDATED = f"{DOMAIN}_usage_updated"
