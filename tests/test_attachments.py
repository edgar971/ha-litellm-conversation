"""Tests for attachment handling (vision support)."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.litellm_conversation.entity import (
    _convert_content_to_messages,
    async_prepare_attachment_parts,
)
from homeassistant.exceptions import HomeAssistantError

PNG_BYTES = b"\x89PNG\r\n\x1a\nfakepngdata"


class _FakeHass:
    """Minimal hass stand-in: run executor jobs inline."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _attachment(path: Path, mime_type: str) -> SimpleNamespace:
    return SimpleNamespace(media_content_id="media-source://test", mime_type=mime_type, path=path)


@pytest.fixture
def png_file(tmp_path: Path) -> Path:
    p = tmp_path / "snap.png"
    p.write_bytes(PNG_BYTES)
    return p


async def test_single_image_encoded(png_file: Path) -> None:
    """A single image attachment becomes one image_url part."""
    parts = await async_prepare_attachment_parts(_FakeHass(), [_attachment(png_file, "image/png")])
    assert len(parts) == 1
    assert parts[0]["type"] == "image_url"
    url = parts[0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG_BYTES


async def test_multiple_images_order_preserved(tmp_path: Path) -> None:
    """Multiple attachments produce parts in order."""
    p1 = tmp_path / "a.jpg"
    p1.write_bytes(b"jpegdata1")
    p2 = tmp_path / "b.png"
    p2.write_bytes(b"pngdata2")
    parts = await async_prepare_attachment_parts(
        _FakeHass(),
        [_attachment(p1, "image/jpeg"), _attachment(p2, "image/png")],
    )
    assert len(parts) == 2
    assert parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_non_image_rejected(tmp_path: Path) -> None:
    """Non-image attachments raise a clear error."""
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4")
    with pytest.raises(HomeAssistantError, match="Only image attachments"):
        await async_prepare_attachment_parts(_FakeHass(), [_attachment(p, "application/pdf")])


def _user_content(text: str, attachments=None) -> SimpleNamespace:
    return SimpleNamespace(role="user", content=text, attachments=attachments)


IMAGE_PART = {
    "type": "image_url",
    "image_url": {"url": "data:image/png;base64,QUJD"},
}


def test_messages_attach_parts_to_last_user_message() -> None:
    """Attachment parts ride on the last user message as multi-part content."""
    content = [
        SimpleNamespace(role="system", content="sys prompt", attachments=None),
        _user_content("earlier question"),
        SimpleNamespace(role="assistant", content="earlier answer", attachments=None),
        _user_content("what is in this image?"),
    ]
    messages = _convert_content_to_messages(content, [IMAGE_PART])
    assert messages[1]["content"] == "earlier question"  # untouched
    last = messages[-1]
    assert last["role"] == "user"
    assert last["content"] == [
        {"type": "text", "text": "what is in this image?"},
        IMAGE_PART,
    ]


def test_messages_without_parts_unchanged() -> None:
    """No attachment parts -> plain string content everywhere."""
    content = [_user_content("hello")]
    messages = _convert_content_to_messages(content)
    assert messages == [{"role": "user", "content": "hello"}]


def test_parts_attach_to_last_user_message_even_with_trailing_assistant() -> None:
    """Parts attach to the last USER message so they survive tool-loop rebuilds."""
    content = [
        _user_content("question about image"),
        SimpleNamespace(role="assistant", content="answer", attachments=None),
    ]
    messages = _convert_content_to_messages(content, [IMAGE_PART])
    assert messages[-1]["content"] == "answer"
    assert messages[0]["content"] == [
        {"type": "text", "text": "question about image"},
        IMAGE_PART,
    ]
