from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import agentmesh.deepsearch.contracts as deepsearch_contracts
from agentmesh.deepsearch.contracts import (
    MAX_NORMALIZED_ANSWERS_BYTES,
    ClarificationAnswerKind,
    ClarificationHistoryRoundV1,
    ClarificationQuestionDraftV1,
    ClarificationQuestionV1,
    DeepSearchClarifyRequestV1,
    DeepSearchStateResponse,
    RequirementAmbiguityV1,
    RequirementPayloadV1,
    RequirementRefinementDraftV1,
    RequirementScopeV1,
    RequirementSuccessCriterionV1,
    RequirementVersionV1,
    clarification_question_id,
    clarification_request_hash,
    materialize_clarification_questions,
    materialize_requirement_payload,
    normalize_clarification_answers,
    normalize_clarification_request_answers,
    requirement_content_hash,
)


def _question_draft(
    prompt: str = "Which market?",
    *,
    answer_kind: ClarificationAnswerKind = ClarificationAnswerKind.TEXT,
    options: list[str] | None = None,
) -> ClarificationQuestionDraftV1:
    return ClarificationQuestionDraftV1(
        prompt=prompt,
        required=True,
        answer_kind=answer_kind,
        options=options or [],
        max_length=2_000,
        default_value=None,
    )


def _payload(*, questions: list[ClarificationQuestionV1], round_number: int) -> RequirementPayloadV1:
    return RequirementPayloadV1(
        goal="Compare collaboration software",
        scope=RequirementScopeV1(objects=["collaboration software"]),
        constraints=[],
        success_criteria=[RequirementSuccessCriterionV1(id="criterion_market", statement="Compare the market")],
        deliverables=["Research report"],
        assumptions=[],
        ambiguities=(
            [RequirementAmbiguityV1(id="ambiguity_market", statement="Market is unknown", blocking=True)]
            if questions
            else []
        ),
        clarification_questions=questions,
        clarification_history=[],
        clarification_round=round_number,
    )


def _refinement_draft(*, blocking: bool, prompt: str = "Which market?") -> RequirementRefinementDraftV1:
    return RequirementRefinementDraftV1(
        goal="Compare collaboration software",
        scope=RequirementScopeV1(objects=["collaboration software"]),
        constraints=[],
        success_criteria=[RequirementSuccessCriterionV1(id="criterion_market", statement="Compare the market")],
        deliverables=["Research report"],
        assumptions=[],
        ambiguities=(
            [RequirementAmbiguityV1(id="ambiguity_market", statement="Market is unknown", blocking=True)]
            if blocking
            else []
        ),
        clarification_questions=[_question_draft(prompt)] if blocking else [],
    )


def _version(*, version: int, payload: RequirementPayloadV1) -> RequirementVersionV1:
    return RequirementVersionV1(
        id=f"requirement_{version}",
        run_id="run_1",
        version=version,
        request_key=f"turn_{version}",
        request_hash=str(version) * 64,
        content_hash=requirement_content_hash(payload),
        payload=payload,
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
    )


def test_question_ids_are_server_owned_stable_and_version_scoped() -> None:
    composed = " Café? "
    decomposed = "Cafe\u0301?"

    assert clarification_question_id(version=2, ordinal=1, prompt=composed) == clarification_question_id(
        version=2,
        ordinal=1,
        prompt=decomposed,
    )
    assert clarification_question_id(version=2, ordinal=1, prompt=composed).startswith("q_2_1_")
    assert clarification_question_id(version=2, ordinal=1, prompt=composed) != clarification_question_id(
        version=3,
        ordinal=1,
        prompt=composed,
    )


def test_materialize_questions_rejects_more_than_five_and_never_accepts_model_ids() -> None:
    drafts = [_question_draft(f"Question {index}") for index in range(1, 6)]

    questions = materialize_clarification_questions(version=4, drafts=drafts)

    assert [item.id.split("_")[:3] for item in questions] == [
        ["q", "4", str(index)] for index in range(1, 6)
    ]
    with pytest.raises(ValueError, match="more than five"):
        materialize_clarification_questions(version=4, drafts=[*drafts, _question_draft("Six")])
    with pytest.raises(ValidationError):
        ClarificationQuestionDraftV1.model_validate(
            {
                **drafts[0].model_dump(mode="json"),
                "id": "model-controlled-id",
            }
        )


def test_materialize_requirement_payload_owns_round_history_and_question_ids() -> None:
    initial = materialize_requirement_payload(
        previous=None,
        draft=_refinement_draft(blocking=True),
        answers={},
        target_version=1,
    )
    first = _version(version=1, payload=initial)
    second_payload = materialize_requirement_payload(
        previous=first,
        draft=_refinement_draft(blocking=True, prompt="Which time range?"),
        answers={initial.clarification_questions[0].id: "China"},
        target_version=2,
    )

    assert second_payload.clarification_round == 2
    assert second_payload.clarification_questions[0].id.startswith("q_2_1_")
    assert second_payload.clarification_history[0].questions == initial.clarification_questions
    assert second_payload.clarification_history[0].answers == {initial.clarification_questions[0].id: "China"}

    with pytest.raises(ValidationError):
        RequirementRefinementDraftV1.model_validate(
            {
                **_refinement_draft(blocking=True).model_dump(mode="python"),
                "clarification_round": 3,
            }
        )


def test_materialize_requirement_payload_stops_after_three_rounds() -> None:
    first_payload = materialize_requirement_payload(
        previous=None,
        draft=_refinement_draft(blocking=True, prompt="Round one?"),
        answers={},
        target_version=1,
    )
    first = _version(version=1, payload=first_payload)
    second_payload = materialize_requirement_payload(
        previous=first,
        draft=_refinement_draft(blocking=True, prompt="Round two?"),
        answers={first_payload.clarification_questions[0].id: "Answer one"},
        target_version=2,
    )
    second = _version(version=2, payload=second_payload)
    third_payload = materialize_requirement_payload(
        previous=second,
        draft=_refinement_draft(blocking=True, prompt="Round three?"),
        answers={second_payload.clarification_questions[0].id: "Answer two"},
        target_version=3,
    )
    third = _version(version=3, payload=third_payload)

    exhausted = materialize_requirement_payload(
        previous=third,
        draft=_refinement_draft(blocking=True, prompt="Forbidden round four?"),
        answers={third_payload.clarification_questions[0].id: "Answer three"},
        target_version=4,
    )

    assert exhausted.clarification_round == 3
    assert len(exhausted.clarification_history) == 3
    assert exhausted.clarification_questions == []


@pytest.mark.parametrize(
    "payload",
    [
        {
            "prompt": "Text",
            "required": True,
            "answer_kind": "text",
            "options": ["invalid"],
            "max_length": 2_000,
            "default_value": None,
        },
        {
            "prompt": "Choice",
            "required": True,
            "answer_kind": "single_choice",
            "options": [],
            "max_length": 2_000,
            "default_value": None,
        },
        {
            "prompt": "Text",
            "required": True,
            "answer_kind": "text",
            "options": [],
            "max_length": 2_001,
            "default_value": None,
        },
        {
            "prompt": "Text",
            "required": True,
            "answer_kind": "text",
            "options": [],
            "max_length": 2_000,
            "default_value": False,
        },
    ],
)
def test_question_contract_rejects_kind_mismatches_and_out_of_bounds(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ClarificationQuestionDraftV1.model_validate(payload)


def test_requirement_payload_is_strict_and_limits_rounds_and_questions() -> None:
    questions = materialize_clarification_questions(
        version=1,
        drafts=[_question_draft(f"Question {index}") for index in range(1, 6)],
    )
    payload = _payload(questions=questions, round_number=1)

    assert len(payload.clarification_questions) == 5
    with pytest.raises(ValidationError):
        RequirementPayloadV1.model_validate({**payload.model_dump(mode="python"), "unexpected": True})
    with pytest.raises(ValidationError):
        RequirementPayloadV1.model_validate(
            {
                **payload.model_dump(mode="python"),
                "clarification_questions": [*questions, questions[0]],
            }
        )
    with pytest.raises(ValidationError):
        RequirementPayloadV1.model_validate(
            {
                **payload.model_dump(mode="python"),
                "clarification_questions": [],
                "clarification_round": 4,
            }
        )


def test_answer_normalization_is_question_typed_and_canonical() -> None:
    drafts = [
        _question_draft("Region"),
        _question_draft(
            "Products",
            answer_kind=ClarificationAnswerKind.MULTI_CHOICE,
            options=["Alpha", "Beta"],
        ),
    ]
    questions = materialize_clarification_questions(version=2, drafts=drafts)

    normalized = normalize_clarification_answers(
        questions=questions,
        answers={questions[0].id: "  Cafe\u0301  ", questions[1].id: ["Beta", "Alpha"]},
    )

    assert normalized == {questions[0].id: "Café", questions[1].id: ["Alpha", "Beta"]}
    with pytest.raises(ValueError, match="unknown"):
        normalize_clarification_answers(questions=questions, answers={"q_9_1_deadbeef": "value"})
    with pytest.raises(ValueError, match="missing"):
        normalize_clarification_answers(questions=questions, answers={questions[0].id: "value"})
    with pytest.raises(ValueError, match="must be a string or a list"):
        normalize_clarification_answers(
            questions=questions,
            answers={questions[0].id: True, questions[1].id: ["Alpha"]},
        )


def test_normalized_answers_enforce_utf8_byte_limit() -> None:
    questions = materialize_clarification_questions(
        version=1,
        drafts=[_question_draft(f"Question {index}") for index in range(1, 4)],
    )
    answers = {question.id: "界" * 1_000 for question in questions}

    with pytest.raises(ValueError, match="8000 bytes"):
        normalize_clarification_answers(questions=questions, answers=answers)
    assert len(str(MAX_NORMALIZED_ANSWERS_BYTES)) > 0


def test_clarify_wire_request_defers_answer_semantics_until_after_version_fence() -> None:
    request = DeepSearchClarifyRequestV1.model_validate(
        {
            "client_turn_id": "clarify_002",
            "expected_requirement_version": 2,
            "answers": {"q_2_1_deadbeef": False},
        }
    )

    assert request.answers == {"q_2_1_deadbeef": False}
    question = materialize_clarification_questions(version=2, drafts=[_question_draft()])[0]
    with pytest.raises(ValueError, match="string or a list"):
        normalize_clarification_answers(questions=[question], answers={question.id: False})
    with pytest.raises(ValidationError):
        DeepSearchClarifyRequestV1.model_validate(
            {
                **request.model_dump(mode="python"),
                "unexpected": True,
            }
        )


def test_requirement_version_checks_canonical_content_hash_and_question_version() -> None:
    questions = materialize_clarification_questions(version=2, drafts=[_question_draft()])
    payload = _payload(questions=questions, round_number=1)
    content_hash = requirement_content_hash(payload)
    version = RequirementVersionV1(
        id="requirement_2",
        run_id="run_1",
        version=2,
        request_key="clarify_001",
        request_hash="1" * 64,
        content_hash=content_hash,
        payload=payload,
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
    )

    assert version.content_hash == requirement_content_hash(version.payload)
    with pytest.raises(ValidationError, match="content_hash"):
        RequirementVersionV1.model_validate({**version.model_dump(mode="python"), "content_hash": "0" * 64})
    wrong_questions = materialize_clarification_questions(version=3, drafts=[_question_draft()])
    wrong_payload = _payload(questions=wrong_questions, round_number=1)
    with pytest.raises(ValidationError, match="question ID"):
        RequirementVersionV1.model_validate(
            {
                **version.model_dump(mode="python"),
                "payload": wrong_payload,
                "content_hash": requirement_content_hash(wrong_payload),
            }
        )


def test_requirement_content_hash_is_locked_to_schema_and_payload_only() -> None:
    payload = _payload(questions=[], round_number=0)

    assert requirement_content_hash(payload) == "3a22c6747094e60127bfcf5553131dd38ec7dfc9345ddb58954eb1d474af1b2a"


def test_clarification_request_hash_uses_only_documented_projection() -> None:
    left = clarification_request_hash(
        run_id="run_1",
        expected_requirement_version=2,
        normalized_answers={"q_2_2_deadbeef": ["Beta", "Alpha"], "q_2_1_deadbeef": " China "},
    )
    right = clarification_request_hash(
        run_id="run_1",
        expected_requirement_version=2,
        normalized_answers={"q_2_1_deadbeef": "China", "q_2_2_deadbeef": ["Alpha", "Beta"]},
    )

    assert left == right
    assert left == "fcbdec94aaa591b6a407bf3674903b8d22bb7a3000bc53d8d1a614539596a743"


def test_request_identity_hashes_invalid_json_answers_without_accepting_them_semantically() -> None:
    raw = {"q_2_1_deadbeef": {"nested": True}, "q_2_2_deadbeef": 42}

    assert normalize_clarification_request_answers(raw) == raw
    assert clarification_request_hash(
        run_id="run_1",
        expected_requirement_version=2,
        normalized_answers=raw,
    )
    question = materialize_clarification_questions(version=2, drafts=[_question_draft()])[0]
    with pytest.raises(ValueError, match="unknown"):
        normalize_clarification_answers(questions=[question], answers=raw)


def test_request_identity_normalization_bounds_untrusted_json(monkeypatch) -> None:
    with pytest.raises(ValueError, match="five answers"):
        normalize_clarification_request_answers({f"question_{index}": "value" for index in range(6)})

    normalize = deepsearch_contracts.unicodedata.normalize

    def reject_normalizing_oversized_text(form: str, value: str) -> str:
        if len(value) > MAX_NORMALIZED_ANSWERS_BYTES:
            raise AssertionError("oversized text reached Unicode normalization")
        return normalize(form, value)

    monkeypatch.setattr(deepsearch_contracts.unicodedata, "normalize", reject_normalizing_oversized_text)
    with pytest.raises(ValueError, match="8000 bytes"):
        normalize_clarification_request_answers({"question": "x" * 8_001})
    with pytest.raises(ValueError, match="too complex"):
        normalize_clarification_request_answers({"question": [0] * 10_000})

    nested: object = "value"
    for _index in range(10):
        nested = {"child": nested}
    with pytest.raises(ValueError, match="nested too deeply"):
        normalize_clarification_request_answers({"question": nested})


def test_blocking_ambiguity_and_current_questions_remain_consistent() -> None:
    question = materialize_clarification_questions(version=1, drafts=[_question_draft()])[0]
    with pytest.raises(ValidationError, match="blocking ambiguity"):
        RequirementPayloadV1.model_validate(
            {
                **_payload(questions=[question], round_number=1).model_dump(mode="python"),
                "ambiguities": [],
            }
        )

def test_history_requires_normalized_answers_and_ordered_rounds() -> None:
    question = materialize_clarification_questions(version=1, drafts=[_question_draft()])[0]
    history = ClarificationHistoryRoundV1(round=1, questions=[question], answers={question.id: "China"})
    payload = RequirementPayloadV1.model_validate(
        {
            **_payload(questions=[], round_number=0).model_dump(mode="python"),
            "clarification_round": 1,
            "clarification_history": [history],
        }
    )

    assert payload.clarification_history == [history]
    normalized_history = ClarificationHistoryRoundV1(round=1, questions=[question], answers={question.id: " China "})
    assert normalized_history.answers == {question.id: "China"}

    with pytest.raises(ValidationError, match="ordered"):
        RequirementPayloadV1.model_validate(
            {
                **payload.model_dump(mode="python"),
                "clarification_round": 2,
                "clarification_history": [
                    {"round": 2, "questions": [question], "answers": {question.id: "China"}},
                    history,
                ],
            }
        )


def test_deepsearch_state_response_is_a_strict_slice_two_projection() -> None:
    payload = {
        "run": {
            "id": "run_1",
            "thread_id": "thread_1",
            "user_id": "user_1",
            "workspace_id": "workspace_1",
            "project_id": "project_1",
            "input_text": "Compare collaboration software",
            "planning_mode": "deepsearch",
        },
        "active_requirement": None,
        "problem_graph": None,
        "plan": None,
        "evidence_coverage": None,
        "report_review": None,
        "retry_disposition": "none",
    }

    assert DeepSearchStateResponse.model_validate(payload).retry_disposition == "none"
    with pytest.raises(ValidationError):
        DeepSearchStateResponse.model_validate({**payload, "unexpected": True})
