"""Constants for the LiteLLM Conversation integration."""

from datetime import timedelta
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
CONF_IMAGE_MODEL = "image_model"
CONF_IMAGE_SIZE = "image_size"
CONF_IMAGE_QUALITY = "image_quality"
CONF_STT_MODEL = "stt_model"
CONF_DECISION_MODEL = "decision_model"
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

# Poll interval for the proxy-side spend/budget sensors (GET /key/info is a
# cheap self-info call; 15 min keeps budget tracking fresh without spamming
# the proxy).
KEY_INFO_UPDATE_INTERVAL = timedelta(minutes=15)

# Per-request timeout for AI Task image generation. Diffusion backends
# (Bedrock Stable Diffusion, DALL-E class models) routinely need far longer
# than the chat path's first-token latency; 120 s is generous without
# hanging an automation forever.
IMAGE_GENERATION_TIMEOUT = 120.0

# Per-request timeout for decision-model evaluations (POST /v1/systemone).
# Decision models are small fast classifiers, so this is deliberately much
# tighter than the diffusion path: a hung evaluation should fail the
# automation quickly rather than sit on it for minutes.
DECISION_EVALUATION_TIMEOUT = 60.0

# Tags stamped on every Chat Completions request via the LiteLLM body field
# `metadata.tags` so the proxy's spend logs (request_tags) can be sliced by
# Home Assistant traffic in Grafana.
REQUEST_METADATA_TAGS = ["home-assistant", "ha-litellm-conversation"]
