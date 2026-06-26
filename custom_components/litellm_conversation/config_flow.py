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
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    DOMAIN,
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


class LiteLLMConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LiteLLM Conversation."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            api_key = user_input[CONF_API_KEY]

            normalized = base_url
            if not normalized.endswith("/v1"):
                normalized = f"{normalized}/v1"

            client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url=normalized,
                http_client=get_async_client(self.hass),
            )
            try:
                async with asyncio.timeout(10):
                    await client.models.list()
            except openai.AuthenticationError:
                errors["base"] = "invalid_auth"
            except TimeoutError, openai.APIConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=base_url,
                    data={CONF_BASE_URL: base_url, CONF_API_KEY: api_key},
                    subentries=[
                        {
                            "subentry_type": "conversation",
                            "title": "LiteLLM Conversation",
                            "data": {},
                        },
                        {
                            "subentry_type": "ai_task_data",
                            "title": "LiteLLM AI Tasks",
                            "data": {},
                        },
                    ],
                )

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

    @classmethod
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported subentry types."""
        return {
            "conversation": LiteLLMConversationSubentryFlowHandler,
            "ai_task_data": LiteLLMAITaskSubentryFlowHandler,
        }


class LiteLLMConversationSubentryFlowHandler(ConfigSubentryFlow):
    """Conversation subentry flow."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle subentry configuration."""
        if user_input is not None:
            # Remove llm_hass_api key if empty so it's omitted rather than None
            data = dict(user_input)
            if not data.get(CONF_LLM_HASS_API):
                data.pop(CONF_LLM_HASS_API, None)
            return self.async_create_entry(
                title=user_input.get(CONF_CHAT_MODEL, "LiteLLM Conversation"),
                data=data,
            )

        entry = self._get_entry()
        models = await _get_models(self.hass, entry.data[CONF_BASE_URL], entry.data[CONF_API_KEY])

        llm_apis = [
            SelectOptionDict(value="", label="No control"),
        ] + [
            SelectOptionDict(value=api.id, label=api.name) for api in llm.async_get_apis(self.hass)
        ]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CHAT_MODEL, default=models[0] if models else DEFAULT_CHAT_MODEL
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[SelectOptionDict(value=m, label=m) for m in models],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_PROMPT): TemplateSelector(),
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
                    vol.Optional(CONF_LLM_HASS_API): SelectSelector(
                        SelectSelectorConfig(
                            options=llm_apis,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )


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
