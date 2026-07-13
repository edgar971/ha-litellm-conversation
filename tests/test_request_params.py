"""Tests for request param assembly and API error mapping (entity.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import openai
import pytest
import voluptuous as vol

from custom_components.litellm_conversation.entity import (
    _build_request_params,
    _raise_for_api_error,
)
from homeassistant.exceptions import HomeAssistantError


def test_defaults_minimal_params() -> None:
    """Empty subentry data produces minimal params with drop_params safety net."""
    create_params, extra_body = _build_request_params({}, None)
    assert create_params["model"]
    assert create_params["stream"] is True
    assert create_params["stream_options"] == {"include_usage": True}
    assert "temperature" not in create_params
    assert "top_p" not in create_params
    assert "tools" not in create_params
    assert "response_format" not in create_params
    assert extra_body == {"drop_params": True}


def test_temperature_wins_over_top_p() -> None:
    """Bedrock quirk: never send temperature AND top_p together."""
    create_params, _ = _build_request_params({"temperature": 0.5, "top_p": 0.9}, None)
    assert create_params["temperature"] == 0.5
    assert "top_p" not in create_params


def test_top_p_sent_when_temperature_default() -> None:
    """top_p alone is passed through."""
    create_params, _ = _build_request_params({"top_p": 0.9}, None)
    assert create_params["top_p"] == 0.9
    assert "temperature" not in create_params


def test_default_values_omitted() -> None:
    """Provider defaults apply when sliders are left at their defaults."""
    create_params, _ = _build_request_params({"temperature": 1.0, "top_p": 1.0}, None)
    assert "temperature" not in create_params
    assert "top_p" not in create_params


def test_tools_included() -> None:
    """Tool specs are forwarded."""
    tools = [{"type": "function", "function": {"name": "x"}}]
    create_params, _ = _build_request_params({}, tools)
    assert create_params["tools"] is tools


def test_structure_builds_response_format_without_strict() -> None:
    """Structured output uses json_schema WITHOUT strict (Bedrock quirk)."""
    schema = vol.Schema({vol.Required("name"): str})
    create_params, _ = _build_request_params({}, None, "person", schema)
    rf = create_params["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "person"
    assert "strict" not in rf["json_schema"]


def test_structure_with_ha_selectors() -> None:
    """Selector-based structures (what ai_task.generate_data actually sends) convert.

    Regression: without llm.selector_serializer, voluptuous_openapi crashes with
    'cannot use BooleanSelector as a dict key (unhashable type)'.
    """
    from homeassistant.helpers import selector

    schema = vol.Schema(
        {
            vol.Required("vehicles_visible"): selector.BooleanSelector(),
            vol.Required("description"): selector.TextSelector(),
        }
    )
    create_params, _ = _build_request_params({}, None, "driveway_check", schema)
    props = create_params["response_format"]["json_schema"]["schema"]["properties"]
    assert props["vehicles_visible"]["type"] == "boolean"
    assert props["description"]["type"] == "string"


def test_reasoning_effort_in_extra_body() -> None:
    """reasoning_effort goes in the body (header is silently ignored by proxy)."""
    _, extra_body = _build_request_params({"reasoning_effort": "low"}, None)
    assert extra_body["reasoning_effort"] == "low"

    _, extra_body = _build_request_params({"reasoning_effort": "none"}, None)
    assert "reasoning_effort" not in extra_body


def test_web_search_options() -> None:
    """Web search toggle adds web_search_options with context size."""
    _, extra_body = _build_request_params(
        {"web_search": True, "web_search_context_size": "high"}, None
    )
    assert extra_body["web_search_options"] == {"search_context_size": "high"}

    _, extra_body = _build_request_params({"web_search": False}, None)
    assert "web_search_options" not in extra_body


def test_guardrails_parsed_to_list() -> None:
    """Comma-separated guardrail names become a list, whitespace stripped."""
    _, extra_body = _build_request_params({"guardrails": "pii-mask, toxicity ,"}, None)
    assert extra_body["guardrails"] == ["pii-mask", "toxicity"]


@pytest.mark.parametrize(
    ("exc", "translation_key"),
    [
        (
            openai.AuthenticationError("bad key", response=MagicMock(status_code=401), body=None),
            "authentication_error",
        ),
        (
            openai.RateLimitError("slow down", response=MagicMock(status_code=429), body=None),
            "rate_limit_error",
        ),
        (openai.APIConnectionError(request=MagicMock()), "connection_error"),
        (
            openai.APIStatusError("boom", response=MagicMock(status_code=502), body=None),
            "api_error",
        ),
    ],
)
def test_raise_for_api_error_mapping(exc: openai.OpenAIError, translation_key: str) -> None:
    """Each openai error type maps to the right translated HomeAssistantError."""
    with pytest.raises(HomeAssistantError) as exc_info:
        _raise_for_api_error(exc, "test-model")
    assert exc_info.value.translation_key == translation_key
    assert exc_info.value.__cause__ is exc


def test_raise_for_api_error_reraises_unknown() -> None:
    """openai errors outside the map are re-raised unchanged."""
    err = openai.OpenAIError("weird")
    with pytest.raises(openai.OpenAIError) as exc_info:
        _raise_for_api_error(err, "test-model")
    assert exc_info.value is err
