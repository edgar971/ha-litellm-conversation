"""Tests for AI Task image generation via /v1/images/generations (issue #4).

Pure parsing/params functions get direct tests; entity paths use
SimpleNamespace/MagicMock fakes (no network), mirroring test_sensor.py style.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from custom_components.litellm_conversation.ai_task import (
    LiteLLMAITaskEntity,
    build_image_request,
    parse_image_response,
    parse_size,
)
from homeassistant.components import ai_task
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

# ---------------------------------------------------------------------------
# Pure builders / parsers
# ---------------------------------------------------------------------------


def test_build_image_request_defaults() -> None:
    """Model, prompt, n=1 and b64_json are always sent; LiteLLM body fields ride along."""
    body = build_image_request({"image_model": "sd-model"}, "a red fox")
    assert body["model"] == "sd-model"
    assert body["prompt"] == "a red fox"
    assert body["n"] == 1
    assert body["response_format"] == "b64_json"
    assert body["drop_params"] is True
    assert body["metadata"]["tags"]  # spend-log request tags, same as chat path
    assert "size" not in body
    assert "quality" not in body


def test_build_image_request_size_quality_passthrough() -> None:
    """Configured size/quality are forwarded (trimmed); blanks stay omitted."""
    body = build_image_request(
        {"image_model": "m", "image_size": " 1024x512 ", "image_quality": "hd"},
        "prompt",
    )
    assert body["size"] == "1024x512"
    assert body["quality"] == "hd"

    body = build_image_request({"image_model": "m", "image_size": "", "image_quality": None}, "p")
    assert "size" not in body
    assert "quality" not in body


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1024x1024", (1024, 1024)),
        ("512X256", (512, 256)),
        (" 800 x 600 ", (800, 600)),
        ("square", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_parse_size(value: object, expected: tuple[int, int] | None) -> None:
    """WxH strings map to dimensions; anything else degrades to None."""
    assert parse_size(value) == expected


def test_parse_image_response_b64_happy_path() -> None:
    """b64_json decodes to bytes; revised_prompt exposed; no usage -> None."""
    payload = {
        "data": [{"b64_json": base64.b64encode(b"PNGDATA").decode(), "revised_prompt": "rev"}]
    }
    parsed = parse_image_response(payload)
    assert parsed.image_data == b"PNGDATA"
    assert parsed.mime_type == "image/png"
    assert parsed.revised_prompt == "rev"
    assert parsed.usage is None


def test_parse_image_response_usage_prompt_completion_spelling() -> None:
    """LiteLLM-normalized usage passes through to the sensor-facing keys."""
    payload = {
        "data": [{"b64_json": base64.b64encode(b"X").decode()}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 0, "total_tokens": 7},
    }
    parsed = parse_image_response(payload)
    assert parsed.usage == {"prompt_tokens": 7, "completion_tokens": 0, "total_tokens": 7}


def test_parse_image_response_usage_input_output_spelling() -> None:
    """OpenAI images spelling (input/output_tokens) is normalized; total derived."""
    payload = {
        "data": [{"b64_json": base64.b64encode(b"X").decode()}],
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }
    parsed = parse_image_response(payload)
    assert parsed.usage == {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}


def test_parse_image_response_zero_usage_is_none() -> None:
    """An all-zero/empty usage dict is treated as no usable usage."""
    payload = {"data": [{"b64_json": base64.b64encode(b"X").decode()}], "usage": {}}
    assert parse_image_response(payload).usage is None


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "JSON object"),
        ({}, "'data' list missing"),
        ({"data": []}, "'data' list missing"),
        ({"data": "nope"}, "'data' list missing"),
        ({"data": ["scalar"]}, "shape in /images/generations"),
    ],
)
def test_parse_image_response_structural_errors(payload: object, message: str) -> None:
    """Malformed payloads raise ValueError (surfaced as HomeAssistantError upstream)."""
    with pytest.raises(ValueError, match=message):
        parse_image_response(payload)


def test_parse_image_response_url_only_raises() -> None:
    """URL-only responses error cleanly — we intentionally never fetch them."""
    payload = {"data": [{"url": "https://cdn.example.com/img.png"}]}
    with pytest.raises(ValueError, match="only an image URL"):
        parse_image_response(payload)


def test_parse_image_response_no_payload_at_all_raises() -> None:
    """A data item with neither b64_json nor url still fails cleanly."""
    with pytest.raises(ValueError, match="no 'b64_json'"):
        parse_image_response({"data": [{}]})


def test_parse_image_response_invalid_base64_raises() -> None:
    """Garbage base64 is a ValueError, not a crash deep in decoding."""
    with pytest.raises(ValueError, match="invalid base64"):
        parse_image_response({"data": [{"b64_json": "!!!not-base64!!!"}]})


def test_parse_image_response_empty_after_decode_raises() -> None:
    """Zero-byte b64 payload is rejected (HA media upload needs real bytes)."""
    with pytest.raises(ValueError, match="no 'b64_json'"):
        parse_image_response({"data": [{"b64_json": ""}]})


# ---------------------------------------------------------------------------
# Entity path (faked client, no network)
# ---------------------------------------------------------------------------

_IMAGE_SUBENTRY = {"chat_model": "chat-m", "image_model": "sd-model"}


def _entity(
    hass: HomeAssistant,
    subentry_data: dict[str, object],
    post: AsyncMock,
) -> LiteLLMAITaskEntity:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    client = MagicMock()
    client.with_options.return_value = client  # timeout override returns same fake
    client.post = post
    entry.runtime_data = client
    subentry = SimpleNamespace(subentry_id="sub1", title="Tasks", data=subentry_data)
    entity = LiteLLMAITaskEntity(entry, subentry)
    entity.hass = hass
    entity.entity_id = "ai_task.test_tasks"
    return entity


def _chat_log() -> SimpleNamespace:
    return SimpleNamespace(conversation_id="conv-1")


def _task() -> ai_task.GenImageTask:
    return ai_task.GenImageTask(name="pic", instructions="a cat in a hat")


async def test_features_advertise_generate_image_unconditionally(
    hass: HomeAssistant,
) -> None:
    """GENERATE_IMAGE is static (can't be re-declared per subentry on target HA)."""
    entity = _entity(hass, {}, AsyncMock())
    features = entity.supported_features
    assert features & ai_task.AITaskEntityFeature.GENERATE_IMAGE
    assert features & ai_task.AITaskEntityFeature.GENERATE_DATA


async def test_generate_image_without_model_raises_cleanly(hass: HomeAssistant) -> None:
    """No image_model configured -> clear HomeAssistantError, zero HTTP calls."""
    post = AsyncMock()
    entity = _entity(hass, {"chat_model": "chat-m"}, post)
    with pytest.raises(HomeAssistantError, match="No image model configured"):
        await entity._async_generate_image(_task(), _chat_log())
    post.assert_not_awaited()


async def test_generate_image_happy_path_dispatches_usage(hass: HomeAssistant) -> None:
    """b64 result becomes GenImageTaskResult and usage hits the sensor signal."""
    payload = {
        "data": [{"b64_json": base64.b64encode(b"PNG!").decode(), "revised_prompt": "rev"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 0, "total_tokens": 4},
    }
    entity = _entity(
        hass, {**_IMAGE_SUBENTRY, "image_size": "1024x1024"}, AsyncMock(return_value=payload)
    )
    with patch("custom_components.litellm_conversation.ai_task.async_dispatcher_send") as send:
        result = await entity._async_generate_image(_task(), _chat_log())

    assert isinstance(result, ai_task.GenImageTaskResult)
    assert result.image_data == b"PNG!"
    assert result.conversation_id == "conv-1"
    assert result.mime_type == "image/png"
    assert result.model == "sd-model"
    assert result.revised_prompt == "rev"
    assert (result.width, result.height) == (1024, 1024)
    send.assert_called_once_with(
        hass,
        "litellm_conversation_usage_updated_test_entry",
        {"model": "sd-model", "prompt_tokens": 4, "completion_tokens": 0, "total_tokens": 4},
    )


async def test_generate_image_no_usage_skips_dispatch(hass: HomeAssistant) -> None:
    """Providers without usage (e.g. Bedrock SD) still succeed; no fake signal."""
    payload = {"data": [{"b64_json": base64.b64encode(b"PNG!").decode()}]}
    entity = _entity(hass, dict(_IMAGE_SUBENTRY), AsyncMock(return_value=payload))
    with patch("custom_components.litellm_conversation.ai_task.async_dispatcher_send") as send:
        result = await entity._async_generate_image(_task(), _chat_log())
    assert result.image_data == b"PNG!"
    assert (result.width, result.height) == (None, None)
    send.assert_not_called()


async def test_generate_image_sends_b64_and_tags_body(hass: HomeAssistant) -> None:
    """The raw post targets /images/generations with the pure-builder body."""
    payload = {"data": [{"b64_json": base64.b64encode(b"X").decode()}]}
    post = AsyncMock(return_value=payload)
    entity = _entity(hass, {**_IMAGE_SUBENTRY, "image_quality": "hd"}, post)
    await entity._async_generate_image(_task(), _chat_log())

    args, kwargs = post.await_args
    assert args == ("/images/generations",)
    body = kwargs["body"]
    assert kwargs["cast_to"] is dict
    assert body["response_format"] == "b64_json"
    assert body["quality"] == "hd"
    assert body["drop_params"] is True


async def test_generate_image_no_image_models_on_proxy_maps_error(
    hass: HomeAssistant,
) -> None:
    """A proxy with no image deployments (4xx) -> translated HomeAssistantError, no crash."""
    err = openai.NotFoundError(
        "No deployments available", response=MagicMock(status_code=404), body=None
    )
    entity = _entity(hass, dict(_IMAGE_SUBENTRY), AsyncMock(side_effect=err))
    with pytest.raises(HomeAssistantError) as exc_info:
        await entity._async_generate_image(_task(), _chat_log())
    assert exc_info.value.translation_domain == "litellm_conversation"
    assert exc_info.value.translation_key == "api_error"


async def test_generate_image_connection_error_marks_unavailable(
    hass: HomeAssistant,
) -> None:
    """Proxy unreachable follows the chat path: entity flips unavailable."""
    err = openai.APIConnectionError(request=MagicMock())
    entity = _entity(hass, dict(_IMAGE_SUBENTRY), AsyncMock(side_effect=err))
    with pytest.raises(HomeAssistantError):
        await entity._async_generate_image(_task(), _chat_log())
    assert entity.available is False


async def test_generate_image_malformed_payload_maps_error(hass: HomeAssistant) -> None:
    """HTTP 200 with junk body -> clean HomeAssistantError, not a KeyError."""
    entity = _entity(hass, dict(_IMAGE_SUBENTRY), AsyncMock(return_value={"unexpected": True}))
    with pytest.raises(HomeAssistantError, match="Unexpected LiteLLM image response"):
        await entity._async_generate_image(_task(), _chat_log())
