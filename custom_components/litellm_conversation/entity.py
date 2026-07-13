"""LiteLLM Conversation entity base."""

from __future__ import annotations

import base64
from collections.abc import AsyncGenerator, Callable
import json
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, NoReturn

import openai
import voluptuous as vol
from voluptuous_openapi import convert

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps

from .const import (
    CONF_CHAT_MODEL,
    CONF_GUARDRAILS,
    CONF_MAX_TOKENS,
    CONF_REASONING_EFFORT,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    CONF_WEB_SEARCH,
    CONF_WEB_SEARCH_CONTEXT_SIZE,
    DEFAULT_CHAT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    DEFAULT_WEB_SEARCH_CONTEXT_SIZE,
    DOMAIN,
    LOGGER,
    MAX_TOOL_ITERATIONS,
    SIGNAL_USAGE_UPDATED,
)

if TYPE_CHECKING:
    from . import LiteLLMConfigEntry


def _build_request_params(
    subentry_data: dict[str, Any] | Any,
    tools: list[dict[str, Any]] | None,
    structure_name: str | None = None,
    structure: vol.Schema | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build (create_params, extra_body) for a Chat Completions request.

    Pure function: encapsulates all provider-quirk handling (Bedrock
    temperature/top_p exclusivity, drop_params, body-param reasoning_effort,
    web_search_options, guardrails) so it can be unit-tested directly.
    """
    model = subentry_data.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)
    temperature = subentry_data.get(CONF_TEMPERATURE)
    top_p = subentry_data.get(CONF_TOP_P)
    max_tokens = subentry_data.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)
    reasoning_effort = subentry_data.get(CONF_REASONING_EFFORT)
    web_search = subentry_data.get(CONF_WEB_SEARCH, False)
    guardrails = subentry_data.get(CONF_GUARDRAILS, "")

    create_params: dict[str, Any] = {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": max_tokens,
    }

    # Only send temperature OR top_p (not both) — Bedrock rejects requests
    # containing both. Prefer temperature; omit both when unset so the
    # provider default applies.
    if temperature is not None and temperature != DEFAULT_TEMPERATURE:
        create_params["temperature"] = temperature
        if top_p is not None and top_p != DEFAULT_TOP_P:
            LOGGER.warning(
                "Both temperature and top_p are set; sending only temperature "
                "(some providers reject both)"
            )
    elif top_p is not None and top_p != DEFAULT_TOP_P:
        create_params["top_p"] = top_p

    if tools:
        create_params["tools"] = tools

    if structure is not None and structure_name is not None:
        output_schema = convert(structure)
        # Omit `strict` — not supported by Bedrock and many non-OpenAI providers.
        create_params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": structure_name,
                "schema": output_schema,
            },
        }

    # Ask the proxy to silently drop any params unsupported by the target provider.
    extra_body: dict[str, Any] = {"drop_params": True}
    # reasoning_effort is a LiteLLM body param (not a header); drop_params
    # strips it for models that don't support reasoning.
    if reasoning_effort and reasoning_effort != "none":
        extra_body["reasoning_effort"] = reasoning_effort

    # Native web search (Chat Completions web_search_options — LiteLLM
    # translates per provider; drop_params strips it when unsupported).
    if web_search:
        context_size = subentry_data.get(
            CONF_WEB_SEARCH_CONTEXT_SIZE, DEFAULT_WEB_SEARCH_CONTEXT_SIZE
        )
        extra_body["web_search_options"] = {"search_context_size": context_size}

    # LiteLLM proxy guardrails (comma-separated names -> list body param).
    if guardrails:
        extra_body["guardrails"] = [g.strip() for g in guardrails.split(",") if g.strip()]

    return create_params, extra_body


# openai exception type -> (log label, translation key) for user-facing errors.
_API_ERROR_MAP: tuple[tuple[type[openai.OpenAIError], str, str], ...] = (
    (openai.AuthenticationError, "Authentication error", "authentication_error"),
    (openai.RateLimitError, "Rate limit error", "rate_limit_error"),
    (openai.APIConnectionError, "Connection error", "connection_error"),
)


def _raise_for_api_error(err: openai.OpenAIError, model: str) -> NoReturn:
    """Map an openai exception to a translated HomeAssistantError and raise it."""
    for exc_type, label, translation_key in _API_ERROR_MAP:
        if isinstance(err, exc_type):
            LOGGER.error("%s (model=%s): %s", label, model, err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
            ) from err
    if isinstance(err, openai.APIStatusError):
        LOGGER.error("API status error (model=%s, status=%s): %s", model, err.status_code, err)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"status_code": str(err.status_code)},
        ) from err
    raise err


def _format_tool(tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None) -> dict[str, Any]:
    """Format tool specification for Chat Completions API."""
    schema = convert(tool.parameters, custom_serializer=custom_serializer)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
        },
    }


async def async_prepare_attachment_parts(
    hass: HomeAssistant,
    attachments: list[conversation.Attachment],
) -> list[dict[str, Any]]:
    """Encode image attachments as Chat Completions image_url content parts.

    Only images are supported: Bedrock (and several other providers) do not
    reliably accept PDFs on the Chat Completions path.
    """

    def _encode(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("utf-8")

    parts: list[dict[str, Any]] = []
    for attachment in attachments:
        if not attachment.mime_type.startswith("image/"):
            raise HomeAssistantError(
                "Only image attachments are supported; "
                f"{attachment.path.name} is {attachment.mime_type}"
            )
        b64 = await hass.async_add_executor_job(_encode, attachment.path)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{attachment.mime_type};base64,{b64}"},
            }
        )
    return parts


def _convert_content_to_messages(
    chat_content: list[conversation.Content],
    last_user_attachment_parts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert chat log content to Chat Completions API messages.

    If last_user_attachment_parts is provided, the attachment parts are
    appended to the last user message as multi-part content (text part
    first) — matching the pattern used by core's openai_conversation
    integration. The last *user* message is targeted (not simply the last
    message) so attachments survive tool-loop iterations, where tool results
    are appended after the user message.
    """
    messages: list[dict[str, Any]] = []
    attach_index = -1
    if last_user_attachment_parts:
        for index in range(len(chat_content) - 1, -1, -1):
            content = chat_content[index]
            if (
                not isinstance(
                    content,
                    (conversation.ToolResultContent, conversation.AssistantContent),
                )
                and content.role == "user"
            ):
                attach_index = index
                break

    for index, content in enumerate(chat_content):
        if isinstance(content, conversation.ToolResultContent):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": content.tool_call_id,
                    "content": json_dumps(content.tool_result),
                }
            )
            continue

        if isinstance(content, conversation.AssistantContent):
            msg: dict[str, Any] = {"role": "assistant"}
            if content.content:
                msg["content"] = content.content
            if content.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json_dumps(tc.tool_args),
                        },
                    }
                    for tc in content.tool_calls
                ]
            messages.append(msg)
        elif content.content:
            if last_user_attachment_parts and index == attach_index:
                messages.append(
                    {
                        "role": content.role,
                        "content": [
                            {"type": "text", "text": content.content},
                            *last_user_attachment_parts,
                        ],
                    }
                )
            else:
                messages.append(
                    {
                        "role": content.role,
                        "content": content.content,
                    }
                )

    return messages


async def _transform_stream(
    result: openai.AsyncStream,
    usage_out: dict[str, Any] | None = None,
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform a Chat Completions stream into HA chat log delta dicts.

    If usage_out is provided, token usage from the final stream chunk
    (requires stream_options include_usage) is written into it.
    """
    current_tool_calls: dict[int, dict[str, Any]] = {}

    def _flush_tool_calls() -> list[llm.ToolInput]:
        """Build ToolInput list from accumulated tool calls and clear the buffer."""
        tool_inputs: list[llm.ToolInput] = []
        for tc in current_tool_calls.values():
            if tc["tool_call_id"] and tc["tool_name"]:
                LOGGER.debug(
                    "Tool call completed: %s (call_id=%s)",
                    tc["tool_name"],
                    tc["tool_call_id"],
                )
                args_json = tc["tool_args_json"] or "{}"
                try:
                    tool_args = json.loads(args_json)
                except (ValueError, TypeError) as err:
                    LOGGER.warning(
                        "Failed to parse tool arguments for %s (call_id=%s): %s -- raw=%s",
                        tc["tool_name"],
                        tc["tool_call_id"],
                        err,
                        repr(args_json),
                    )
                    tool_args = {}
                tool_inputs.append(
                    llm.ToolInput(
                        id=tc["tool_call_id"],
                        tool_name=tc["tool_name"],
                        tool_args=tool_args,
                    )
                )
        current_tool_calls.clear()
        return tool_inputs

    async for chunk in result:
        # Capture usage from the final chunk (include_usage stream option).
        if usage_out is not None and getattr(chunk, "usage", None):
            usage_out["prompt_tokens"] = chunk.usage.prompt_tokens
            usage_out["completion_tokens"] = chunk.usage.completion_tokens
            usage_out["total_tokens"] = chunk.usage.total_tokens

        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            continue

        delta = choice.delta

        if delta is not None:
            # Reasoning/thinking content (LiteLLM surfaces this for reasoning models)
            if reasoning := getattr(delta, "reasoning_content", None):
                yield {"thinking_content": reasoning}

            # Text content
            if delta.content:
                yield {"content": delta.content}

            # Tool calls
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in current_tool_calls:
                        current_tool_calls[idx] = {
                            "tool_call_id": tc_delta.id or "",
                            "tool_name": "",
                            "tool_args_json": "",
                        }
                    tc = current_tool_calls[idx]
                    if tc_delta.id:
                        tc["tool_call_id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc["tool_name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc["tool_args_json"] += tc_delta.function.arguments

        # On any terminal finish_reason, emit accumulated tool calls (we already
        # have them buffered, regardless of the specific reason reported).
        if choice.finish_reason:
            tool_inputs = _flush_tool_calls()
            if tool_inputs:
                yield {"tool_calls": tool_inputs}

    # Safety net: flush any leftover tool calls if the stream ended without a
    # terminal finish_reason being observed.
    tool_inputs = _flush_tool_calls()
    if tool_inputs:
        yield {"tool_calls": tool_inputs}


class LiteLLMBaseLLMEntity(Entity):
    """Base class for LiteLLM LLM entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry: LiteLLMConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_name = subentry.title

    @property
    def client(self) -> openai.AsyncOpenAI:
        """Return the OpenAI client."""
        return self.entry.runtime_data

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        structure_name: str | None = None,
        structure: vol.Schema | None = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ) -> None:
        """Handle a chat log using the Chat Completions API."""
        tools: list[dict[str, Any]] | None = None
        if chat_log.llm_api is not None:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        create_params, extra_body = _build_request_params(
            self.subentry.data, tools, structure_name, structure
        )
        model = create_params["model"]

        # Encode image attachments (AI Task SUPPORT_ATTACHMENTS) from the
        # last user message; they must be re-attached on every loop iteration
        # since messages are rebuilt from the chat log each time.
        attachment_parts: list[dict[str, Any]] | None = None
        last_content = chat_log.content[-1] if chat_log.content else None
        if isinstance(last_content, conversation.UserContent) and last_content.attachments:
            attachment_parts = await async_prepare_attachment_parts(
                self.hass, last_content.attachments
            )

        create_params["messages"] = _convert_content_to_messages(chat_log.content, attachment_parts)

        for _iteration in range(max_iterations):
            LOGGER.debug(
                "LiteLLM request: model=%s temperature=%s top_p=%s max_tokens=%s tools=%d",
                model,
                create_params.get("temperature", "unset"),
                create_params.get("top_p", "unset"),
                create_params["max_tokens"],
                len(tools) if tools else 0,
            )
            t0 = time.monotonic()
            try:
                response = await self.client.chat.completions.create(
                    **create_params,
                    extra_body=extra_body,
                )
            except openai.OpenAIError as err:
                _raise_for_api_error(err, model)

            content_len_before = len(chat_log.content)

            usage: dict[str, Any] = {}
            async for _ in chat_log.async_add_delta_content_stream(
                self.entity_id, _transform_stream(response, usage)
            ):
                pass

            latency_ms = (time.monotonic() - t0) * 1000
            LOGGER.info(
                "LiteLLM response: model=%s latency=%.0fms iteration=%d tokens=%s",
                model,
                latency_ms,
                _iteration + 1,
                usage.get("total_tokens", "n/a"),
            )

            # Notify usage sensors (if the sensor platform is loaded).
            if usage:
                async_dispatcher_send(
                    self.hass,
                    f"{SIGNAL_USAGE_UPDATED}_{self.entry.entry_id}",
                    {"model": model, **usage},
                )

            # Verify the stream actually added something to the chat log.
            if len(chat_log.content) == content_len_before:
                LOGGER.error(
                    "Model returned no content (model=%s). Check proxy logs.",
                    model,
                )
                raise HomeAssistantError(
                    f"LiteLLM model '{model}' returned no response. Check your LiteLLM proxy logs."
                )

            if not chat_log.unresponded_tool_results:
                break

            # Update messages for next iteration (attachments must survive
            # the rebuild or the image vanishes after the first tool call).
            create_params["messages"] = _convert_content_to_messages(
                chat_log.content, attachment_parts
            )
        else:
            # Loop exhausted without the model finishing its tool workflow.
            LOGGER.error(
                "Tool iteration limit (%d) reached without completion (model=%s)",
                max_iterations,
                model,
            )
            raise HomeAssistantError(
                f"LiteLLM model '{model}' did not finish after {max_iterations} tool "
                "iterations. The conversation may be stuck in a tool-calling loop."
            )
