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
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    DEFAULT_CHAT_MODEL,
    DOMAIN,
    LOGGER,
)
from .schemas import (
    _build_ai_task_schema,
    _build_conversation_schema,
    _build_stt_schema,
    _build_tts_schema,
    _clean_conversation_data,
    _llm_api_options,
)
from .util import normalize_base_url

API_KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _build_client(hass, base_url: str, api_key: str) -> openai.AsyncOpenAI:
    """Create an OpenAI client for the given proxy credentials."""
    return openai.AsyncOpenAI(
        api_key=api_key,
        base_url=normalize_base_url(base_url),
        http_client=get_async_client(hass),
    )


async def _get_models(hass, base_url: str, api_key: str) -> list[str]:
    """Fetch model list from the LiteLLM proxy.

    Returns an empty list on any failure or empty response — callers must
    handle that explicitly (fall back to a placeholder AND warn the user),
    rather than this function silently manufacturing a fake default that
    doesn't exist on the proxy.
    """
    client = _build_client(hass, base_url, api_key)
    try:
        async with asyncio.timeout(10):
            models = await client.models.list()
        return sorted(m.id for m in models.data)
    except Exception as err:
        LOGGER.warning("Could not fetch model list from %s: %s", base_url, err)
        return []


async def _validate_connection(
    hass, base_url: str, api_key: str
) -> tuple[dict[str, str], list[str]]:
    """Validate LiteLLM proxy connection and fetch models in one round-trip.

    Returns (errors, models). Combining validation + model listing avoids a
    second live /v1/models call immediately after the first.
    """
    errors: dict[str, str] = {}
    client = _build_client(hass, base_url, api_key)
    try:
        async with asyncio.timeout(10):
            response = await client.models.list()
        return errors, sorted(m.id for m in response.data)
    except openai.AuthenticationError:
        errors["base"] = "invalid_auth"
    except (TimeoutError, openai.APIConnectionError):
        errors["base"] = "cannot_connect"
    except Exception as err:
        LOGGER.exception("Unexpected error validating LiteLLM proxy %s: %s", base_url, err)
        errors["base"] = "unknown"
    return errors, []


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

            errors, models = await _validate_connection(self.hass, base_url, api_key)
            if not errors:
                await self.async_set_unique_id(base_url)
                self._abort_if_unique_id_configured()
                self._base_url = base_url
                self._api_key = api_key
                self._models = models
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
        # The proxy connected fine but returned zero models — likely a proxy
        # config gap (no model_list entries) rather than a network/auth
        # problem, so it wasn't caught by _validate_connection. Surface it
        # instead of silently seeding a fake "gpt-4o-mini" that doesn't
        # exist on the proxy and will fail on first use.
        model_count_text = (
            str(len(models))
            if models
            else "0 — check your LiteLLM proxy's model_list config; a placeholder is shown below but it will not work until you add a real model"
        )
        return self.async_show_form(
            step_id="models",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CHAT_MODEL,
                        default=models[0] if models else DEFAULT_CHAT_MODEL,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=m, label=m)
                                for m in (models or [DEFAULT_CHAT_MODEL])
                            ],
                            custom_value=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            description_placeholders={"model_count": model_count_text},
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
            errors, _models = await _validate_connection(
                self.hass, entry.data[CONF_BASE_URL], api_key
            )
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

            errors, _models = await _validate_connection(self.hass, base_url, api_key)
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
