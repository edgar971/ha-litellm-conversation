"""Config flow for LiteLLM Conversation integration."""

from __future__ import annotations

import asyncio
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
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_REASONING_EFFORT,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    DOMAIN,
    REASONING_EFFORT_OPTIONS,
)


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
                self._base_url = base_url
                self._api_key = api_key
                self._models = await _get_models(self.hass, base_url, api_key)
                return await self.async_step_models()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL): str,
                    vol.Required(CONF_API_KEY): str,
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
                return self.async_update_reload_and_abort(
                    entry,
                    data={CONF_BASE_URL: base_url, CONF_API_KEY: api_key},
                )

        current_base_url = entry.data.get(CONF_BASE_URL, "") if entry else ""
        current_api_key = entry.data.get(CONF_API_KEY, "") if entry else ""

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_URL, default=current_base_url): str,
                    vol.Required(CONF_API_KEY, default=current_api_key): str,
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
        }


def _build_conversation_schema(models: list[str], defaults: dict[str, Any]) -> vol.Schema:
    """Build the conversation subentry schema with optional defaults."""
    return vol.Schema(
        {
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
            vol.Optional(CONF_LLM_HASS_API): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value="", label="No control")],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _build_ai_task_schema(models: list[str], defaults: dict[str, Any]) -> vol.Schema:
    """Build the AI task subentry schema with optional defaults."""
    return vol.Schema(
        {
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


class LiteLLMConversationSubentryFlowHandler(ConfigSubentryFlow):
    """Conversation subentry flow."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle subentry configuration."""
        if user_input is not None:
            data = dict(user_input)
            # Remove empty optional fields
            if not data.get(CONF_LLM_HASS_API):
                data.pop(CONF_LLM_HASS_API, None)
            if not data.get(CONF_PROMPT):
                data.pop(CONF_PROMPT, None)
            if data.get(CONF_REASONING_EFFORT) == "none":
                data.pop(CONF_REASONING_EFFORT, None)
            return self.async_create_entry(
                title=data.get(CONF_CHAT_MODEL, "LiteLLM Conversation"),
                data=data,
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        llm_apis = [SelectOptionDict(value="", label="No control")] + [
            SelectOptionDict(value=api.id, label=api.name) for api in llm.async_get_apis(self.hass)
        ]

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CHAT_MODEL,
                    default=models[0] if models else DEFAULT_CHAT_MODEL,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=m, label=m) for m in models],
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_PROMPT): TemplateSelector(),
                vol.Optional(CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE): NumberSelector(
                    NumberSelectorConfig(min=0, max=2, step=0.05, mode=NumberSelectorMode.SLIDER)
                ),
                vol.Optional(CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): NumberSelector(
                    NumberSelectorConfig(min=1, max=32768, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_TOP_P, default=DEFAULT_TOP_P): NumberSelector(
                    NumberSelectorConfig(min=0, max=1, step=0.05, mode=NumberSelectorMode.SLIDER)
                ),
                vol.Optional(CONF_REASONING_EFFORT, default="none"): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=v, label=v.capitalize())
                            for v in REASONING_EFFORT_OPTIONS
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_LLM_HASS_API): SelectSelector(
                    SelectSelectorConfig(
                        options=llm_apis,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an existing conversation subentry."""
        subentry = self._get_reconfigure_subentry()
        current = dict(subentry.data)

        if user_input is not None:
            data = dict(user_input)
            if not data.get(CONF_LLM_HASS_API):
                data.pop(CONF_LLM_HASS_API, None)
            if not data.get(CONF_PROMPT):
                data.pop(CONF_PROMPT, None)
            if data.get(CONF_REASONING_EFFORT) == "none":
                data.pop(CONF_REASONING_EFFORT, None)
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=data.get(CONF_CHAT_MODEL, subentry.title),
                data=data,
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        llm_apis = [SelectOptionDict(value="", label="No control")] + [
            SelectOptionDict(value=api.id, label=api.name) for api in llm.async_get_apis(self.hass)
        ]

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CHAT_MODEL,
                    default=current.get(
                        CONF_CHAT_MODEL, models[0] if models else DEFAULT_CHAT_MODEL
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=m, label=m) for m in models],
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_PROMPT, default=current.get(CONF_PROMPT, "")): TemplateSelector(),
                vol.Optional(
                    CONF_TEMPERATURE,
                    default=current.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=2, step=0.05, mode=NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_MAX_TOKENS,
                    default=current.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=32768, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_TOP_P, default=current.get(CONF_TOP_P, DEFAULT_TOP_P)
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1, step=0.05, mode=NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_REASONING_EFFORT,
                    default=current.get(CONF_REASONING_EFFORT, "none"),
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
                    CONF_LLM_HASS_API,
                    default=current.get(CONF_LLM_HASS_API, ""),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=llm_apis,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="reconfigure", data_schema=schema)


class LiteLLMAITaskSubentryFlowHandler(ConfigSubentryFlow):
    """AI Task subentry flow."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle subentry configuration."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get(CONF_CHAT_MODEL, "LiteLLM AI Tasks"),
                data=user_input,
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHAT_MODEL, default=models[0] if models else DEFAULT_CHAT_MODEL
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[SelectOptionDict(value=m, label=m) for m in models],
                            custom_value=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_TEMPERATURE, default=DEFAULT_TEMPERATURE): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=2, step=0.05, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                    vol.Optional(CONF_MAX_TOKENS, default=DEFAULT_MAX_TOKENS): NumberSelector(
                        NumberSelectorConfig(min=1, max=32768, step=1, mode=NumberSelectorMode.BOX)
                    ),
                    vol.Optional(CONF_TOP_P, default=DEFAULT_TOP_P): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=1, step=0.05, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an existing AI task subentry."""
        subentry = self._get_reconfigure_subentry()
        current = dict(subentry.data)

        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=user_input.get(CONF_CHAT_MODEL, subentry.title),
                data=user_input,
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHAT_MODEL,
                        default=current.get(
                            CONF_CHAT_MODEL, models[0] if models else DEFAULT_CHAT_MODEL
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[SelectOptionDict(value=m, label=m) for m in models],
                            custom_value=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE,
                        default=current.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=2, step=0.05, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                    vol.Optional(
                        CONF_MAX_TOKENS,
                        default=current.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS),
                    ): NumberSelector(
                        NumberSelectorConfig(min=1, max=32768, step=1, mode=NumberSelectorMode.BOX)
                    ),
                    vol.Optional(
                        CONF_TOP_P, default=current.get(CONF_TOP_P, DEFAULT_TOP_P)
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=1, step=0.05, mode=NumberSelectorMode.SLIDER
                        )
                    ),
                }
            ),
        )
