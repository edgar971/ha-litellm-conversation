"""Subentry form schemas for the LiteLLM Conversation config flow.

Pure schema builders + data cleaners, extracted from config_flow.py to keep
the flow handlers readable as subentry types grow.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.helpers import llm
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)

from .const import (
    CONF_CHAT_MODEL,
    CONF_GUARDRAILS,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_REASONING_EFFORT,
    CONF_STT_MODEL,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    CONF_TTS_MODEL,
    CONF_TTS_VOICE,
    CONF_WEB_SEARCH,
    CONF_WEB_SEARCH_CONTEXT_SIZE,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_STT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    DEFAULT_WEB_SEARCH_CONTEXT_SIZE,
    REASONING_EFFORT_OPTIONS,
    TTS_VOICES,
    WEB_SEARCH_CONTEXT_OPTIONS,
)


def _model_options(models: list[str], fallback: str = DEFAULT_CHAT_MODEL) -> list[SelectOptionDict]:
    """Build model dropdown options, with a placeholder when the proxy has none.

    An empty proxy model list (bad model_list config, or a transient fetch
    failure) must not produce an empty dropdown — custom_value=True lets the
    user type a model id manually either way, but a placeholder keeps the
    default-selection UX working instead of showing nothing to pick.
    """
    return [SelectOptionDict(value=m, label=m) for m in (models or [fallback])]


def _build_conversation_schema(
    models: list[str],
    llm_apis: list[SelectOptionDict],
    defaults: dict[str, Any],
    default_name: str,
) -> vol.Schema:
    """Build the conversation subentry schema (shared by user + reconfigure steps)."""
    return vol.Schema(
        {
            vol.Optional("name", default=default_name): str,
            vol.Optional(
                CONF_CHAT_MODEL,
                default=defaults.get(CONF_CHAT_MODEL, models[0] if models else DEFAULT_CHAT_MODEL),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_model_options(models),
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_PROMPT, default=defaults.get(CONF_PROMPT, "")): TemplateSelector(),
            vol.Optional(
                CONF_TEMPERATURE, default=defaults.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=2, step=0.05, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_MAX_TOKENS, default=defaults.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=32768, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_TOP_P, default=defaults.get(CONF_TOP_P, DEFAULT_TOP_P)
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=1, step=0.05, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_REASONING_EFFORT,
                default=defaults.get(CONF_REASONING_EFFORT, "none"),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=v, label=v.capitalize())
                        for v in REASONING_EFFORT_OPTIONS
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_WEB_SEARCH,
                default=defaults.get(CONF_WEB_SEARCH, False),
            ): BooleanSelector(),
            vol.Optional(
                CONF_WEB_SEARCH_CONTEXT_SIZE,
                default=defaults.get(CONF_WEB_SEARCH_CONTEXT_SIZE, DEFAULT_WEB_SEARCH_CONTEXT_SIZE),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=v, label=v.capitalize())
                        for v in WEB_SEARCH_CONTEXT_OPTIONS
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_GUARDRAILS, default=defaults.get(CONF_GUARDRAILS, "")): str,
            vol.Optional(
                CONF_LLM_HASS_API,
                default=defaults.get(CONF_LLM_HASS_API, ""),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=llm_apis,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _build_ai_task_schema(
    models: list[str],
    defaults: dict[str, Any],
    default_name: str,
) -> vol.Schema:
    """Build the AI task subentry schema (shared by user + reconfigure steps)."""
    return vol.Schema(
        {
            vol.Optional("name", default=default_name): str,
            vol.Optional(
                CONF_CHAT_MODEL,
                default=defaults.get(CONF_CHAT_MODEL, models[0] if models else DEFAULT_CHAT_MODEL),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_model_options(models),
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_TEMPERATURE, default=defaults.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=2, step=0.05, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_MAX_TOKENS, default=defaults.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=32768, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_TOP_P, default=defaults.get(CONF_TOP_P, DEFAULT_TOP_P)
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=1, step=0.05, mode=NumberSelectorMode.SLIDER)
            ),
        }
    )


def _llm_api_options(hass) -> list[SelectOptionDict]:
    """Return LLM API selector options with a 'No control' default."""
    return [SelectOptionDict(value="", label="No control")] + [
        SelectOptionDict(value=api.id, label=api.name) for api in llm.async_get_apis(hass)
    ]


def _clean_conversation_data(data: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional fields from conversation subentry data."""
    if not data.get(CONF_LLM_HASS_API):
        data.pop(CONF_LLM_HASS_API, None)
    if not data.get(CONF_PROMPT):
        data.pop(CONF_PROMPT, None)
    if data.get(CONF_REASONING_EFFORT) == "none":
        data.pop(CONF_REASONING_EFFORT, None)
    if not data.get(CONF_WEB_SEARCH):
        data.pop(CONF_WEB_SEARCH, None)
        data.pop(CONF_WEB_SEARCH_CONTEXT_SIZE, None)
    if not data.get(CONF_GUARDRAILS):
        data.pop(CONF_GUARDRAILS, None)
    return data


def _build_stt_schema(
    models: list[str],
    defaults: dict[str, Any],
    default_name: str,
) -> vol.Schema:
    """Build the STT subentry schema."""
    return vol.Schema(
        {
            vol.Optional("name", default=default_name): str,
            vol.Optional(
                CONF_STT_MODEL,
                default=defaults.get(CONF_STT_MODEL, DEFAULT_STT_MODEL),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_model_options(models, fallback=DEFAULT_STT_MODEL),
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _build_tts_schema(
    models: list[str],
    defaults: dict[str, Any],
    default_name: str,
) -> vol.Schema:
    """Build the TTS subentry schema."""
    return vol.Schema(
        {
            vol.Optional("name", default=default_name): str,
            vol.Optional(
                CONF_TTS_MODEL,
                default=defaults.get(CONF_TTS_MODEL, DEFAULT_TTS_MODEL),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_model_options(models, fallback=DEFAULT_TTS_MODEL),
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_TTS_VOICE,
                default=defaults.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=v, label=v.capitalize()) for v in TTS_VOICES],
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )
