"""LiteLLM AI Task entity."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from json import JSONDecodeError
import re
from typing import Any, cast, override

import openai

from homeassistant.components import ai_task, conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.json import json_loads

from . import LiteLLMConfigEntry
from .const import (
    CONF_DECISION_MODEL,
    CONF_IMAGE_MODEL,
    CONF_IMAGE_QUALITY,
    CONF_IMAGE_SIZE,
    DECISION_EVALUATION_TIMEOUT,
    IMAGE_GENERATION_TIMEOUT,
    LOGGER,
    REQUEST_METADATA_TAGS,
    SIGNAL_USAGE_UPDATED,
)
from .entity import LiteLLMBaseLLMEntity, _raise_for_api_error, async_attachment_data_urls
from .util import HAS_EVALUATION, evaluation_module

# EVALUATE exists only on HA 2026.11+; getattr keeps this module importable
# (and the flag simply absent from supported_features) on older cores.
_FEATURE_EVALUATE = getattr(ai_task.AITaskEntityFeature, "EVALUATE", ai_task.AITaskEntityFeature(0))

# "1024x1024" / "512X512" style size strings (the common OpenAI-shaped form).
_SIZE_RE = re.compile(r"^(\d+)\s*[xX]\s*(\d+)$")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LiteLLMConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities from a config entry."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type == "ai_task_decision":
            if not HAS_EVALUATION:
                LOGGER.warning(
                    "Skipping decision subentry '%s': decision models need Home"
                    " Assistant 2026.11 or newer",
                    subentry.title,
                )
                continue
            async_add_entities(
                [LiteLLMDecisionEntity(config_entry, subentry)],
                config_subentry_id=subentry.subentry_id,
            )
        elif subentry.subentry_type != "ai_task_data":
            continue
        else:
            async_add_entities(
                [LiteLLMAITaskEntity(config_entry, subentry)],
                config_subentry_id=subentry.subentry_id,
            )


def parse_size(value: Any) -> tuple[int, int] | None:
    """Parse a "WxH" size string into (width, height); anything else is None.

    Pure helper so the width/height metadata on GenImageTaskResult can be
    unit-tested without network. The value comes from user config, not the
    model response, so a non-numeric provider-specific size ("square") just
    yields no dimensions rather than an error.
    """
    if isinstance(value, str) and (match := _SIZE_RE.match(value.strip())):
        return int(match.group(1)), int(match.group(2))
    return None


def build_image_request(subentry_data: dict[str, Any], instructions: str) -> dict[str, Any]:
    """Build the /v1/images/generations request body.

    Pure function (mirrors _build_request_params for the chat path): all
    field mapping lives here so it is unit-testable without network. Assumes
    the caller already verified an image model is configured.
    """
    body: dict[str, Any] = {
        "model": subentry_data[CONF_IMAGE_MODEL],
        "prompt": instructions,
        "n": 1,
        # b64_json so the bytes come back in-band: HA's GenImageTaskResult
        # requires raw image_data and this integration deliberately does not
        # fetch URLs returned by the proxy (SSRF posture, AGENTS.md conv. 5).
        "response_format": "b64_json",
    }

    # Optional passthroughs; values are provider-specific free-text, so we
    # only forward what the user configured and let drop_params absorb the
    # rest (Bedrock SD ignores `quality`, e.g.).
    if size := str(subentry_data.get(CONF_IMAGE_SIZE) or "").strip():
        body["size"] = size
    if quality := str(subentry_data.get(CONF_IMAGE_QUALITY) or "").strip():
        body["quality"] = quality

    # LiteLLM-specific fields ride at the top level of the JSON body (this is
    # a raw client.post, so there is no SDK extra_body kwarg to merge them):
    # drop_params keeps provider quirks intact (AGENTS.md conv. 1) and
    # metadata.tags feeds the proxy's spend-log request_tags like chat requests.
    body["drop_params"] = True
    body["metadata"] = {"tags": list(REQUEST_METADATA_TAGS)}
    return body


def _normalize_usage(raw: Any) -> dict[str, int] | None:
    """Map a raw-post response `usage` onto the token keys the daily sensors read.

    OpenAI's images API and /v1/systemone report input_tokens/output_tokens
    while LiteLLM usually normalizes to prompt_tokens/completion_tokens; accept both and
    emit the sensor-facing spelling. Returns None when the response carries
    no usable usage (many diffusion providers don't).
    """
    if not isinstance(raw, dict) or not raw:
        return None

    def _num(*keys: str) -> int:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        return 0

    prompt = _num("prompt_tokens", "input_tokens")
    completion = _num("completion_tokens", "output_tokens")
    total = _num("total_tokens") or prompt + completion
    if not (prompt or completion or total):
        return None
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


@dataclass(frozen=True)
class ParsedImage:
    """Decoded single-image result from a /v1/images/generations response."""

    image_data: bytes
    mime_type: str
    revised_prompt: str | None
    usage: dict[str, int] | None


def parse_image_response(payload: Any) -> ParsedImage:
    """Parse an /images/generations response body into a ParsedImage.

    Pure function so the parsing contract is unit-testable without network.
    Raises ValueError on structurally malformed payloads or when no base64
    image is present (incl. URL-only responses — see error message for why
    we intentionally do not fetch those).
    """
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object from /images/generations")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("'data' list missing or empty in /images/generations response")
    first = data[0]
    if not isinstance(first, dict):
        raise ValueError("unexpected 'data[0]' shape in /images/generations response")

    b64 = first.get("b64_json")
    if not isinstance(b64, str) or not b64:
        if isinstance(first.get("url"), str) and first["url"]:
            # We explicitly request response_format=b64_json; a provider that
            # ignores it and returns only a URL would require us to fetch an
            # arbitrary remote address with the proxy's credentials context —
            # that is an SSRF surface (AGENTS.md conv. 5), so fail cleanly and
            # tell the user how to fix their model choice instead.
            raise ValueError(
                "provider returned only an image URL; this integration does not fetch "
                "remote URLs — configure an image model whose provider honors b64_json"
            )
        raise ValueError("no 'b64_json' image payload in /images/generations response")

    try:
        image_data = base64.b64decode(b64, validate=True)
    except ValueError as err:  # binascii.Error subclasses ValueError
        raise ValueError("invalid base64 image data in response") from err
    if not image_data:
        raise ValueError("empty image payload in /images/generations response")

    revised = first.get("revised_prompt")
    return ParsedImage(
        image_data=image_data,
        # OpenAI-compatible image endpoints return PNG by default and the
        # response carries no content-type field to negotiate otherwise.
        mime_type="image/png",
        revised_prompt=revised if isinstance(revised, str) else None,
        usage=_normalize_usage(payload.get("usage")),
    )


class LiteLLMAITaskEntity(
    ai_task.AITaskEntity,
    LiteLLMBaseLLMEntity,
):
    """LiteLLM AI Task entity."""

    _attr_supported_features = (
        ai_task.AITaskEntityFeature.GENERATE_DATA
        | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
        # Advertised unconditionally: supported_features is static on the HA
        # builds this integration installs for, so it cannot be toggled per
        # subentry. generate_image raises a clean error when no image model
        # is configured (see _async_generate_image).
        | ai_task.AITaskEntityFeature.GENERATE_IMAGE
    )

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
        """Handle a generate image task via the proxy's /v1/images/generations.

        Uses a raw client.post (same pattern as the /key/info coordinator)
        rather than client.images.generate so LiteLLM-specific body fields
        (drop_params, metadata.tags) sit at the top level and the response is
        parsed by our own pure function. The entry client's base_url already
        ends in /v1, hence the "/images/generations" path.
        """
        subentry_data = self.subentry.data
        model = subentry_data.get(CONF_IMAGE_MODEL)
        if not model:
            raise HomeAssistantError(
                "No image model configured for this LiteLLM AI Task entity. Set "
                "'Image model' in the AI task options to an image-capable model "
                "deployed on your LiteLLM proxy (the proxy's chat models cannot "
                "generate images)."
            )

        body = build_image_request(subentry_data, task.instructions)
        try:
            payload = await self.client.with_options(timeout=IMAGE_GENERATION_TIMEOUT).post(
                "/images/generations", body=body, cast_to=dict
            )
        except openai.APIConnectionError as err:
            self._set_available(False)
            _raise_for_api_error(err, model)
        except openai.OpenAIError as err:
            # A proxy with no image models deployed answers 4xx here (e.g.
            # "No deployments available"); _raise_for_api_error maps that to
            # a translated HomeAssistantError instead of crashing.
            _raise_for_api_error(err, model)
        self._set_available(True)

        try:
            parsed = parse_image_response(payload)
        except ValueError as err:
            raise HomeAssistantError(f"Unexpected LiteLLM image response: {err}") from err

        LOGGER.info(
            "LiteLLM image generated: model=%s bytes=%d usage=%s",
            model,
            len(parsed.image_data),
            parsed.usage or "n/a",
        )

        # AGENTS.md conv. 7: dispatch usage so the daily sensors stay honest.
        # Only when the response actually carries usage — image providers are
        # inconsistent about it (Bedrock SD reports none); we do not invent a
        # zero-token request row, matching the chat path's `if usage:` gate.
        if parsed.usage:
            async_dispatcher_send(
                self.hass,
                f"{SIGNAL_USAGE_UPDATED}_{self.entry.entry_id}",
                {"model": model, **parsed.usage},
            )

        dims = parse_size(subentry_data.get(CONF_IMAGE_SIZE))
        return ai_task.GenImageTaskResult(
            image_data=parsed.image_data,
            conversation_id=chat_log.conversation_id,
            mime_type=parsed.mime_type,
            width=dims[0] if dims else None,
            height=dims[1] if dims else None,
            model=model,
            revised_prompt=parsed.revised_prompt,
        )


# ---------------------------------------------------------------------------
# Decision models (issue #13): ai_task.evaluate via the proxy's
# POST /v1/systemone route (LiteLLM >= 1.104.2). HA's evaluation contract is
# deliberately System-One-shaped, so questions pass through nearly verbatim.
# ---------------------------------------------------------------------------


def build_decision_request(
    model: str,
    state: Any,
    questions: dict[str, Any],
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Build a /v1/systemone request body from an EvaluationTask's fields.

    Pure helper so the mapping contract is unit-testable without network.
    HA question dicts ({type, instructions, criteria}) are System-One-shaped
    already. Only those keys are copied, so anything else never reaches the
    proxy; core's schema allows no others today, and a field it adds later
    could change the question's meaning, so dropping one logs a warning.
    """
    if not questions:
        raise ValueError("at least one question is required")

    forwarded = ("type", "instructions", "criteria")
    for qid, question in questions.items():
        if dropped := set(question) - set(forwarded):
            LOGGER.warning("Dropping unknown fields from question '%s': %s", qid, sorted(dropped))

    body: dict[str, Any] = {
        "model": model,
        "state": state,
        "questions": {qid: {k: q[k] for k in forwarded if k in q} for qid, q in questions.items()},
    }
    if image_urls:
        body["images"] = list(image_urls)
    body["drop_params"] = True
    body["metadata"] = {"tags": list(REQUEST_METADATA_TAGS)}
    return body


def _probabilities(qid: str, raw: Any) -> dict[str, float]:
    """Return an answer's probabilities as floats; absent ones become empty.

    Core's answer types require probabilities but the wire format doesn't, so
    an absent distribution stays empty rather than being made up.
    """
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"answer for '{qid}' has malformed probabilities")
    try:
        return {key: float(value) for key, value in raw.items()}
    except (TypeError, ValueError) as err:
        raise ValueError(f"answer for '{qid}' has non-numeric probabilities") from err


def _score_probabilities(qid: str, raw: Any, levels: int) -> list[float]:
    """Order score probabilities by level, one entry per level of the scale.

    System One keys them by string index ("0", "1"). Any gap is an error:
    compacting one would move values onto the wrong level without notice.
    """
    probabilities = _probabilities(qid, raw)
    if not probabilities:
        return []
    try:
        by_level = {int(key): value for key, value in probabilities.items()}
    except ValueError as err:
        raise ValueError(f"answer for '{qid}' has non-index-keyed score probabilities") from err
    if sorted(by_level) != list(range(levels)):
        raise ValueError(
            f"answer for '{qid}' has probabilities that do not match its {levels} levels"
        )
    return [by_level[level] for level in range(levels)]


def parse_decision_response(payload: Any, questions: dict[str, Any]) -> dict[str, Any]:
    """Map a /v1/systemone response's answers onto HA answer objects.

    Pure helper so the mapping contract is unit-testable without network.
    Raises ValueError on malformed or incomplete payloads (a missing question
    id means the proxy answered fewer questions than we asked, which callers
    surface as a clean error).
    """
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object from /v1/systemone")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("missing 'answers' object in /v1/systemone response")

    result: dict[str, Any] = {}
    for qid, question in questions.items():
        answer = answers.get(qid)
        if not isinstance(answer, dict):
            raise ValueError(f"no answer for question '{qid}' in /v1/systemone response")
        q_type = question.get("type")
        if q_type == "noul":
            noul = answer.get("noul")
            if not isinstance(noul, (int, float)) or isinstance(noul, bool):
                raise ValueError(f"answer for '{qid}' has no numeric noul")
            result[qid] = evaluation_module.NoulAnswer(noul=float(noul))  # pyright: ignore[reportOptionalMemberAccess]
        elif q_type == "choice":
            choice = answer.get("choice")
            if not isinstance(choice, str):
                raise ValueError(f"answer for '{qid}' has no string choice")
            if choice not in question.get("criteria", ()):
                raise ValueError(f"answer for '{qid}' is not one of the question's options")
            result[qid] = evaluation_module.ChoiceAnswer(  # pyright: ignore[reportOptionalMemberAccess]
                choice=choice, probabilities=_probabilities(qid, answer.get("probabilities"))
            )
        elif q_type == "score":
            score = answer.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise ValueError(f"answer for '{qid}' has no numeric score")
            result[qid] = evaluation_module.ScoreAnswer(  # pyright: ignore[reportOptionalMemberAccess]
                score=float(score),
                probabilities=_score_probabilities(
                    qid, answer.get("probabilities"), len(question.get("criteria", ()))
                ),
            )
        else:
            raise ValueError(f"unsupported question type {q_type!r} for '{qid}'")
    return result


class LiteLLMDecisionEntity(
    ai_task.AITaskEntity,
    LiteLLMBaseLLMEntity,
):
    """LiteLLM decision-model entity (ai_task.evaluate via /v1/systemone)."""

    _attr_icon = "mdi:brain"
    _attr_supported_features = _FEATURE_EVALUATE | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS

    @property
    def _decision_model(self) -> str:
        model = self.subentry.data.get(CONF_DECISION_MODEL)
        if not isinstance(model, str) or not model.strip():
            raise HomeAssistantError(
                "No decision model configured on this subentry; reconfigure it "
                "and pick a decision-capable proxy model (e.g. cloudflare/clef)."
            )
        return model.strip()

    @override
    async def _async_evaluate(self, task) -> Any:  # EvaluationTaskResult on HA 2026.11+
        """Answer structured questions through the LiteLLM proxy."""
        if not HAS_EVALUATION:  # defensive; setup skips this entity otherwise
            raise HomeAssistantError("Decision models need Home Assistant 2026.11 or newer")

        model = self._decision_model
        image_urls = await async_attachment_data_urls(self.hass, task.attachments or [])
        body = build_decision_request(model, task.state, task.questions, image_urls)

        try:
            # max_retries=0: the SDK default would multiply the timeout budget
            # and could bill a retried evaluation again.
            payload = await self.client.with_options(
                timeout=DECISION_EVALUATION_TIMEOUT, max_retries=0
            ).post("/systemone", body=body, cast_to=dict)
        except openai.APITimeoutError as err:
            # A subclass of APIConnectionError, but a slow model doesn't mean
            # the proxy is unreachable, so the entity stays available.
            _raise_for_api_error(err, model)
        except openai.APIConnectionError as err:
            self._set_available(False)
            _raise_for_api_error(err, model)
        except openai.OpenAIError as err:
            # A key without the decision model scoped, or a proxy below
            # 1.104.2 without the route, answers 4xx here; map to a clean
            # HomeAssistantError like every other raw-post path.
            _raise_for_api_error(err, model)
        self._set_available(True)

        # AGENTS.md conv. 7: dispatch before parsing, since the proxy already
        # ran the model even if the answers turn out to be unusable.
        usage = _normalize_usage(payload.get("usage") if isinstance(payload, dict) else None)
        if usage:
            async_dispatcher_send(
                self.hass,
                f"{SIGNAL_USAGE_UPDATED}_{self.entry.entry_id}",
                {"model": model, **usage},
            )

        try:
            answers = parse_decision_response(payload, task.questions)
        except ValueError as err:
            raise HomeAssistantError(f"Unexpected LiteLLM decision response: {err}") from err

        LOGGER.debug(
            "Decision model %s answered task %r (%d questions, %d images)",
            model,
            task.name,
            len(answers),
            len(image_urls),
        )
        return evaluation_module.EvaluationTaskResult(  # pyright: ignore[reportOptionalMemberAccess]
            answers=cast("dict[str, Any]", answers)
        )
