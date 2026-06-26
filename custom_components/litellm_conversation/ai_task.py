"""LiteLLM AI Task entity."""

from __future__ import annotations

import base64
from json import JSONDecodeError
import logging
from typing import override

from openai.types.responses.response_output_item import ImageGenerationCall

from homeassistant.components import ai_task, conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.json import json_loads

from . import LiteLLMConfigEntry
from .entity import LiteLLMBaseLLMEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities from a config entry."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "ai_task_data":
            continue
        async_add_entities(
            [LiteLLMAITaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class LiteLLMAITaskEntity(
    ai_task.AITaskEntity,
    LiteLLMBaseLLMEntity,
):
    """LiteLLM AI Task entity."""

    _attr_supported_features = (
        ai_task.AITaskEntityFeature.GENERATE_DATA
        | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
        | ai_task.AITaskEntityFeature.GENERATE_IMAGE
    )

    def __init__(self, entry: LiteLLMConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        super().__init__(entry, subentry)

    @override
    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task."""
        await self._async_handle_chat_log(
            chat_log,
            structure_name=task.name,
            structure=task.structure,
            max_iterations=1000,
        )

        if not isinstance(chat_log.content[-1], conversation.AssistantContent):
            raise HomeAssistantError("Last content in chat log is not an AssistantContent")

        text = chat_log.content[-1].content or ""

        if not task.structure:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=text,
            )

        try:
            data = json_loads(text)
        except JSONDecodeError as err:
            raise HomeAssistantError("Error with LiteLLM structured response") from err

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=data,
        )

    @override
    async def _async_generate_image(
        self,
        task: ai_task.GenImageTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenImageTaskResult:
        """Handle a generate image task."""
        try:
            await self._async_handle_chat_log(chat_log, structure_name=task.name)
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(
                "LiteLLM image generation failed — check that the configured model supports image generation"
            ) from err

        if not isinstance(chat_log.content[-1], conversation.AssistantContent):
            raise HomeAssistantError("Last content in chat log is not an AssistantContent")

        # Look for an ImageGenerationCall in the response
        image_call: ImageGenerationCall | None = None
        for content in reversed(chat_log.content):
            if not isinstance(content, conversation.AssistantContent):
                break
            if isinstance(getattr(content, "native", None), ImageGenerationCall):
                native: ImageGenerationCall = content.native  # type: ignore[assignment]
                if image_call is None or image_call.result is None:
                    image_call = native
                else:
                    # Release earlier image data to save memory
                    native.result = None

        if image_call is None or image_call.result is None:
            raise HomeAssistantError(
                "No image returned from LiteLLM — the model may not support image generation"
            )

        image_data = base64.b64decode(image_call.result)
        image_call.result = None

        if hasattr(image_call, "output_format") and (output_format := image_call.output_format):
            mime_type = f"image/{output_format}"
        else:
            mime_type = "image/png"

        width: int | None = None
        height: int | None = None
        if hasattr(image_call, "size") and (size := image_call.size):
            parts = size.split("x")
            if len(parts) == 2:
                width = int(parts[0])
                height = int(parts[1])

        from .const import CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL

        return ai_task.GenImageTaskResult(
            image_data=image_data,
            conversation_id=chat_log.conversation_id,
            mime_type=mime_type,
            width=width,
            height=height,
            model=self.subentry.data.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL),
            revised_prompt=image_call.revised_prompt
            if hasattr(image_call, "revised_prompt")
            else None,
        )
