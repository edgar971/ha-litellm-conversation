"""Config flow for LiteLLM Conversation integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import openai
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
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
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BASE_URL,
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
    DOMAIN,
    REASONING_EFFORT_OPTIONS,
    TTS_VOICES,
    WEB_SEARCH_CONTEXT_OPTIONS,
)

API_KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _get_models(hass, base_url: str, api_key: str) -> list[str]:
    """Fetch model list from the LiteLLM proxy."""
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    client = openai.AsyncOpenAI(
        api_key=api_key,
        base_url=normalized,
        http_client=get_async_client(hass),
    )
    try:
        async with asyncio.timeout(10):
            models = await client.models.list()
        return sorted(m.id for m in models.data)
    except Exception:
        return [DEFAULT_CHAT_MODEL]


async def _validate_connection(hass, base_url: str, api_key: str) -> dict[str, str]:
    """Validate LiteLLM proxy connection and return errors dict."""
    errors: dict[str, str] = {}
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    client = openai.AsyncOpenAI(
        api_key=api_key,
        base_url=normalized,
        http_client=get_async_client(hass),
    )
    try:
        async with asyncio.timeout(10):
            await client.models.list()
    except openai.AuthenticationError:
        errors["base"] = "invalid_auth"
    except (TimeoutError, openai.APIConnectionError):
        errors["base"] = "cannot_connect"
    except Exception:
        errors["base"] = "unknown"
    return errors


class LiteLLMConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LiteLLM Conversation."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._base_url: str = ""
        self._api_key: str = ""
        self._models: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step — URL and API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            api_key = user_input[CONF_API_KEY]

            errors = await _validate_connection(self.hass, base_url, api_key)
            if not errors:
                await self.async_set_unique_id(base_url)
                self._abort_if_unique_id_configured()
                self._base_url = base_url
                self._api_key = api_key
                self._models = await _get_models(self.hass, base_url, api_key)
                return await self.async_step_models()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL): str,
                    vol.Required(CONF_API_KEY): API_KEY_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_models(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle model selection step."""
        if user_input is not None:
            chat_model = user_input.get(
                CONF_CHAT_MODEL, self._models[0] if self._models else DEFAULT_CHAT_MODEL
            )
            return self.async_create_entry(
                title=self._base_url,
                data={CONF_BASE_URL: self._base_url, CONF_API_KEY: self._api_key},
                subentries=[
                    {
                        "subentry_type": "conversation",
                        "title": "LiteLLM Conversation",
                        "data": {CONF_CHAT_MODEL: chat_model},
                    },
                    {
                        "subentry_type": "ai_task_data",
                        "title": "LiteLLM AI Tasks",
                        "data": {CONF_CHAT_MODEL: chat_model},
                    },
                ],
            )

        models = self._models
        return self.async_show_form(
            step_id="models",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CHAT_MODEL,
                        default=models[0] if models else DEFAULT_CHAT_MODEL,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[SelectOptionDict(value=m, label=m) for m in models],
                            custom_value=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            description_placeholders={"model_count": str(len(models))},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle reauthentication when the API key is rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key and validate it."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            errors = await _validate_connection(self.hass, entry.data[CONF_BASE_URL], api_key)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): API_KEY_SELECTOR}),
            description_placeholders={CONF_BASE_URL: entry.data[CONF_BASE_URL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of base_url and api_key."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            api_key = user_input[CONF_API_KEY]

            errors = await _validate_connection(self.hass, base_url, api_key)
            if not errors:
                # Abort only if a *different* entry already uses this proxy URL.
                existing = self.hass.config_entries.async_entry_for_domain_unique_id(
                    self.handler, base_url
                )
                if (
                    existing is not None
                    and entry is not None
                    and existing.entry_id != entry.entry_id
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=base_url,
                    data={CONF_BASE_URL: base_url, CONF_API_KEY: api_key},
                )

        current_base_url = entry.data.get(CONF_BASE_URL, "") if entry else ""

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL, default=current_base_url): str,
                    vol.Required(CONF_API_KEY): API_KEY_SELECTOR,
                }
            ),
            errors=errors,
        )

    @classmethod
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported subentry types."""
        return {
            "conversation": LiteLLMConversationSubentryFlowHandler,
            "ai_task_data": LiteLLMAITaskSubentryFlowHandler,
            "stt": LiteLLMSTTSubentryFlowHandler,
            "tts": LiteLLMTTSSubentryFlowHandler,
        }


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
                    options=[SelectOptionDict(value=m, label=m) for m in models],
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
                    options=[SelectOptionDict(value=m, label=m) for m in models],
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


class LiteLLMConversationSubentryFlowHandler(ConfigSubentryFlow):
    """Conversation subentry flow."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle subentry configuration."""
        if user_input is not None:
            data = dict(user_input)
            title = data.pop("name", "") or "LiteLLM Conversation"
            return self.async_create_entry(
                title=title,
                data=_clean_conversation_data(data),
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="user",
            data_schema=_build_conversation_schema(
                models, _llm_api_options(self.hass), {}, "LiteLLM Conversation"
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an existing conversation subentry."""
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            data = dict(user_input)
            title = data.pop("name", "") or subentry.title
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=title,
                data=_clean_conversation_data(data),
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_conversation_schema(
                models, _llm_api_options(self.hass), dict(subentry.data), subentry.title
            ),
        )


class LiteLLMAITaskSubentryFlowHandler(ConfigSubentryFlow):
    """AI Task subentry flow."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle subentry configuration."""
        if user_input is not None:
            data = dict(user_input)
            title = data.pop("name", "") or "LiteLLM AI Tasks"
            return self.async_create_entry(
                title=title,
                data=data,
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="user",
            data_schema=_build_ai_task_schema(models, {}, "LiteLLM AI Tasks"),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an existing AI task subentry."""
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            data = dict(user_input)
            title = data.pop("name", "") or subentry.title
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=title,
                data=data,
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_ai_task_schema(models, dict(subentry.data), subentry.title),
        )


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
                    options=[SelectOptionDict(value=m, label=m) for m in models],
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
                    options=[SelectOptionDict(value=m, label=m) for m in models],
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


class LiteLLMSTTSubentryFlowHandler(ConfigSubentryFlow):
    """Speech-to-text subentry flow."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle subentry configuration."""
        if user_input is not None:
            data = dict(user_input)
            title = data.pop("name", "") or "LiteLLM STT"
            return self.async_create_entry(title=title, data=data)

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="user",
            data_schema=_build_stt_schema(models, {}, "LiteLLM STT"),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an existing STT subentry."""
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            data = dict(user_input)
            title = data.pop("name", "") or subentry.title
            return self.async_update_and_abort(self._get_entry(), subentry, title=title, data=data)

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_stt_schema(models, dict(subentry.data), subentry.title),
        )


class LiteLLMTTSSubentryFlowHandler(ConfigSubentryFlow):
    """Text-to-speech subentry flow."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle subentry configuration."""
        if user_input is not None:
            data = dict(user_input)
            title = data.pop("name", "") or "LiteLLM TTS"
            return self.async_create_entry(title=title, data=data)

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="user",
            data_schema=_build_tts_schema(models, {}, "LiteLLM TTS"),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an existing TTS subentry."""
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            data = dict(user_input)
            title = data.pop("name", "") or subentry.title
            return self.async_update_and_abort(self._get_entry(), subentry, title=title, data=data)

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_tts_schema(models, dict(subentry.data), subentry.title),
        )
