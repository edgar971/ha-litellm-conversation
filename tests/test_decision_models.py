"""Tests for decision models via /v1/systemone (issue #13).

The HA builds CI installs for predate ai_task.evaluation, so entity/parsing
tests inject a minimal stand-in module (the real shapes are asserted against
core's evaluation.py contract: NoulAnswer.noul, ChoiceAnswer.choice/
probabilities, ScoreAnswer.score/probabilities list, EvaluationTaskResult.answers).
"""

from __future__ import annotations

import base64
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from custom_components.litellm_conversation import ai_task as ai_task_module
from custom_components.litellm_conversation.ai_task import (
    LiteLLMDecisionEntity,
    build_decision_request,
    parse_decision_response,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def eval_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Inject a stand-in ai_task.evaluation module with the core dataclass shapes."""
    fake = ModuleType("fake_evaluation")

    class NoulAnswer:
        def __init__(self, noul):
            self.noul = noul

    class ChoiceAnswer:
        def __init__(self, choice, probabilities=None):
            self.choice = choice
            self.probabilities = probabilities

    class ScoreAnswer:
        def __init__(self, score, probabilities=None):
            self.score = score
            self.probabilities = probabilities

    class EvaluationTaskResult:
        def __init__(self, answers):
            self.answers = answers

    fake.NoulAnswer = NoulAnswer  # pyright: ignore[reportAttributeAccessIssue]
    fake.ChoiceAnswer = ChoiceAnswer  # pyright: ignore[reportAttributeAccessIssue]
    fake.ScoreAnswer = ScoreAnswer  # pyright: ignore[reportAttributeAccessIssue]
    fake.EvaluationTaskResult = EvaluationTaskResult  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setattr(ai_task_module, "_evaluation_module", fake)
    # Entity-level tests exercise the evaluate path end to end; setup gating
    # is covered separately in its own tests.
    monkeypatch.setattr(ai_task_module, "_HAS_EVALUATION", True)
    return fake


# ---------------------------------------------------------------------------
# Pure builders / parsers
# ---------------------------------------------------------------------------

_QUESTIONS = {
    "is_refund": {"type": "noul", "instructions": "Is this a refund request?"},
    "urgency": {
        "type": "choice",
        "instructions": "How urgent?",
        "criteria": {"low": "can wait", "high": "today"},
    },
    "frustration": {
        "type": "score",
        "instructions": "How frustrated?",
        "criteria": ["calm", "angry"],
    },
}


def test_build_decision_request_minimal() -> None:
    """Model, state and questions are sent; LiteLLM body fields ride along."""
    body = build_decision_request({"decision_model": "clef"}, "ticket text", _QUESTIONS)
    assert body["model"] == "clef"
    assert body["state"] == "ticket text"
    assert body["questions"]["is_refund"] == {
        "type": "noul",
        "instructions": "Is this a refund request?",
    }
    assert body["questions"]["urgency"]["criteria"] == {"low": "can wait", "high": "today"}
    assert body["drop_params"] is True
    assert body["metadata"]["tags"]  # spend-log request tags, same as chat path
    assert "images" not in body


def test_build_decision_request_filters_unknown_question_fields() -> None:
    """Only type/instructions/criteria cross the wire; unknown fields are dropped."""
    questions = {"q": {"type": "noul", "instructions": "i", "secret": "x"}}
    body = build_decision_request({"decision_model": "m"}, "s", questions)
    assert body["questions"]["q"] == {"type": "noul", "instructions": "i"}


def test_build_decision_request_images_and_object_state() -> None:
    """Images attach as the `images` list; state may be any JSON value."""
    urls = ["data:image/png;base64,QUJD"]
    body = build_decision_request({"decision_model": "m"}, {"photo": "abc"}, {"q": {"type": "noul"}}, urls)
    assert body["images"] == urls
    assert body["state"] == {"photo": "abc"}


def test_build_decision_request_empty_questions_raises() -> None:
    with pytest.raises(ValueError, match="at least one question"):
        build_decision_request({"decision_model": "m"}, "s", {})


def test_parse_decision_response_all_types(eval_module: ModuleType) -> None:
    """noul/choice/score map onto the HA answer objects; score probs become a list."""
    payload = {
        "model": "jev-1.13.0",
        "answers": {
            "is_refund": {"type": "noul", "noul": 0.99},
            "urgency": {
                "type": "choice",
                "choice": "high",
                "confidence": 1.0,
                "probabilities": {"low": 0.0, "high": 1.0},
            },
            "frustration": {
                "type": "score",
                "score": 0.95,
                "confidence": 0.86,
                "legend": {"0": "calm", "1": "angry"},
                "probabilities": {"0": 0.07, "1": 0.91},
            },
        },
        "usage": {"input_tokens": 391, "output_tokens": 67},
    }
    answers = parse_decision_response(payload, _QUESTIONS)
    assert answers["is_refund"].noul == pytest.approx(0.99)
    assert answers["urgency"].choice == "high"
    assert answers["urgency"].probabilities == {"low": 0.0, "high": 1.0}
    assert answers["frustration"].score == pytest.approx(0.95)
    assert answers["frustration"].probabilities == [0.07, 0.91]


def test_parse_decision_response_score_probs_sorted_numerically(eval_module: ModuleType) -> None:
    """"10" must sort after "2", not before it."""
    payload = {
        "answers": {
            "frustration": {
                "type": "score",
                "score": 0.5,
                "probabilities": {"0": 0.1, "2": 0.2, "10": 0.3, "1": 0.4},
            }
        }
    }
    questions = {"frustration": {"type": "score", "instructions": "i"}}
    answers = parse_decision_response(payload, questions)
    assert answers["frustration"].probabilities == [0.1, 0.4, 0.2, 0.3]


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (["not", "a", "dict"], "expected a JSON object"),
        ({}, "missing 'answers'"),
        ({"answers": []}, "missing 'answers'"),
        ({"answers": {}}, "no answer for question 'is_refund'"),
        ({"answers": {"is_refund": {"type": "noul"}}}, "no numeric noul"),
        ({"answers": {"is_refund": {"type": "noul", "noul": True}}}, "no numeric noul"),
    ],
)
def test_parse_decision_response_malformed_raises(
    payload: object, match: str, eval_module: ModuleType
) -> None:
    questions = {"is_refund": {"type": "noul", "instructions": "i"}}
    with pytest.raises(ValueError, match=match):
        parse_decision_response(payload, questions)


def test_parse_decision_response_choice_without_probabilities(eval_module: ModuleType) -> None:
    """probabilities are optional in the wire format."""
    payload = {"answers": {"urgency": {"type": "choice", "choice": "low"}}}
    questions = {"urgency": {"type": "choice", "instructions": "i"}}
    answers = parse_decision_response(payload, questions)
    assert answers["urgency"].choice == "low"
    assert answers["urgency"].probabilities is None


# ---------------------------------------------------------------------------
# Entity path (faked client, no network)
# ---------------------------------------------------------------------------

_DECISION_SUBENTRY = {"decision_model": "clef"}


def _entity(
    hass: HomeAssistant,
    subentry_data: dict[str, object],
    post: AsyncMock,
) -> LiteLLMDecisionEntity:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    client = MagicMock()
    client.with_options.return_value = client  # timeout override returns same fake
    client.post = post
    entry.runtime_data = client
    subentry = SimpleNamespace(subentry_id="sub1", title="Decisions", data=subentry_data)
    entity = LiteLLMDecisionEntity(entry, subentry)
    entity.hass = hass
    entity.entity_id = "ai_task.test_decisions"
    return entity


def _task(
    state: object = "charged twice",
    questions: dict | None = None,
    attachments: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name="support-ticket", state=state, questions=questions or _QUESTIONS, attachments=attachments
    )


async def test_decision_entity_advertises_evaluate_and_attachments(
    hass: HomeAssistant,
) -> None:
    """EVALUATE (when the core has it) + SUPPORT_ATTACHMENTS are static."""
    entity = _entity(hass, dict(_DECISION_SUBENTRY), AsyncMock())
    features = entity.supported_features
    from homeassistant.components import ai_task as ha_ai_task

    assert features & ha_ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
    evaluate = getattr(ha_ai_task.AITaskEntityFeature, "EVALUATE", None)
    if evaluate is not None:
        assert features & evaluate


async def test_decision_evaluate_without_model_raises_cleanly(
    hass: HomeAssistant, eval_module: ModuleType
) -> None:
    """No decision_model configured -> clear HomeAssistantError, zero HTTP calls."""
    post = AsyncMock()
    entity = _entity(hass, {}, post)
    with pytest.raises(HomeAssistantError, match="No decision model configured"):
        await entity._async_evaluate(_task())
    post.assert_not_awaited()


async def test_decision_evaluate_happy_path(
    hass: HomeAssistant, eval_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Questions go to /systemone; answers come back as EvaluationTaskResult."""
    payload = {
        "answers": {
            "is_refund": {"type": "noul", "noul": 0.9},
            "urgency": {"type": "choice", "choice": "high"},
            "frustration": {"type": "score", "score": 0.4, "probabilities": {"0": 0.6, "1": 0.4}},
        }
    }
    post = AsyncMock(return_value=payload)
    entity = _entity(hass, dict(_DECISION_SUBENTRY), post)

    result = await entity._async_evaluate(_task())

    assert isinstance(result, eval_module.EvaluationTaskResult)
    assert result.answers["is_refund"].noul == pytest.approx(0.9)
    assert result.answers["frustration"].probabilities == [0.6, 0.4]

    args, kwargs = post.await_args
    assert args[0] == "/systemone"
    assert kwargs["body"]["model"] == "clef"
    assert kwargs["body"]["state"] == "charged twice"
    assert set(kwargs["body"]["questions"]) == {"is_refund", "urgency", "frustration"}


async def test_decision_evaluate_encodes_image_attachments(
    hass: HomeAssistant, eval_module: ModuleType, tmp_path: Path
) -> None:
    """Image attachments become data URLs in the `images` field."""
    img = tmp_path / "snapshot.png"
    img.write_bytes(b"PNGDATA")
    attachment = SimpleNamespace(path=img, mime_type="image/png")
    questions = {"has_person": {"type": "noul", "instructions": "Is a person visible?"}}
    post = AsyncMock(
        return_value={"answers": {q: {"type": "noul", "noul": 0.5} for q in questions}}
    )
    entity = _entity(hass, dict(_DECISION_SUBENTRY), post)

    await entity._async_evaluate(_task(questions=questions, attachments=[attachment]))

    sent_images = post.await_args.kwargs["body"]["images"]
    assert sent_images == [f"data:image/png;base64,{base64.b64encode(b'PNGDATA').decode()}"]


async def test_decision_evaluate_rejects_non_image_attachment(
    hass: HomeAssistant, eval_module: ModuleType, tmp_path: Path
) -> None:
    """A PDF attachment fails with a clear message instead of being dropped."""
    doc = tmp_path / "report.pdf"
    doc.write_bytes(b"%PDF")
    attachment = SimpleNamespace(path=doc, mime_type="application/pdf")
    post = AsyncMock()
    entity = _entity(hass, dict(_DECISION_SUBENTRY), post)

    with pytest.raises(HomeAssistantError, match="only image attachments"):
        await entity._async_evaluate(_task(attachments=[attachment]))
    post.assert_not_awaited()


async def test_decision_evaluate_connection_error_marks_unavailable(
    hass: HomeAssistant, eval_module: ModuleType
) -> None:
    """Connection failure flips availability (same contract as other paths)."""
    err = openai.APIConnectionError(request=MagicMock())
    entity = _entity(hass, dict(_DECISION_SUBENTRY), AsyncMock(side_effect=err))
    with pytest.raises(HomeAssistantError):
        await entity._async_evaluate(_task())
    assert entity.available is False


async def test_decision_evaluate_key_denied_raises_cleanly(
    hass: HomeAssistant, eval_module: ModuleType
) -> None:
    """A 403 (key not scoped to the decision model) surfaces as HomeAssistantError."""
    response = MagicMock()
    response.status_code = 403
    response.json.return_value = {"error": {"message": "key_model_access_denied"}}
    response.headers = {}
    err = openai.PermissionDeniedError(
        "denied", response=response, body={"error": {"message": "key_model_access_denied"}}
    )
    entity = _entity(hass, dict(_DECISION_SUBENTRY), AsyncMock(side_effect=err))
    with pytest.raises(HomeAssistantError):
        await entity._async_evaluate(_task())


async def test_decision_evaluate_malformed_payload_raises_cleanly(
    hass: HomeAssistant, eval_module: ModuleType
) -> None:
    """A response without answers becomes a HomeAssistantError, not a KeyError."""
    entity = _entity(hass, dict(_DECISION_SUBENTRY), AsyncMock(return_value={"foo": "bar"}))
    with pytest.raises(HomeAssistantError, match="Unexpected LiteLLM decision response"):
        await entity._async_evaluate(_task())


# ---------------------------------------------------------------------------
# Setup gating (graceful degradation)
# ---------------------------------------------------------------------------


def _config_entry(subentry_types: list[str]) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.subentries = {
        f"sub{i}": SimpleNamespace(
            subentry_id=f"sub{i}",
            subentry_type=t,
            title=f"S{i}",
            data={"decision_model": "clef"} if t == "ai_task_decision" else {"chat_model": "m"},
        )
        for i, t in enumerate(subentry_types)
    }
    return entry


async def test_setup_skips_decision_subentries_without_evaluation(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On HA < 2026.11 decision subentries are skipped with a warning, not crashed on."""
    monkeypatch.setattr(ai_task_module, "_HAS_EVALUATION", False)
    add_entities = MagicMock()
    entry = _config_entry(["ai_task_data", "ai_task_decision"])

    await ai_task_module.async_setup_entry(hass, entry, add_entities)

    added = [type(e[0][0]) for e in (call.args for call in add_entities.call_args_list)]
    assert LiteLLMDecisionEntity not in added
    assert len(added) == 1  # only the ai_task_data entity


async def test_setup_adds_decision_entity_with_evaluation(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On HA 2026.11+ a decision subentry yields exactly one LiteLLMDecisionEntity."""
    monkeypatch.setattr(ai_task_module, "_HAS_EVALUATION", True)
    add_entities = MagicMock()
    entry = _config_entry(["ai_task_decision"])

    await ai_task_module.async_setup_entry(hass, entry, add_entities)

    assert add_entities.call_count == 1
    assert isinstance(add_entities.call_args.args[0][0], LiteLLMDecisionEntity)
