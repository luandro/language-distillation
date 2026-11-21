"""WP4.1 unit tests: review domain models (ReviewTask, ReviewDecision).

Contracts under test (ADR-0013 §4-5, docs/REVIEW-WORKFLOW.md, M4-PLAN §6 WP4.1):
- `ReviewTaskType` covers every task type the review workflow document names;
- `ReviewDecisionKind` is exactly `accept/reject/modify/uncertain/defer`;
- both target references must be opaque prefixed ids;
- decisions are immutable records (frozen, `extra="forbid"`);
- `status` is an operational queue state, never a `LifecycleStatus`.
"""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from langpipe.domain.enums import LifecycleStatus, ReviewDecisionKind, ReviewTaskType
from langpipe.domain.ids import ID_PATTERN, IdPrefix, new_id
from langpipe.domain.models import ReviewDecision, ReviewTask
from langpipe.domain.models.base import DomainModel

NOW = datetime(2026, 1, 1, tzinfo=UTC)

EXPECTED_TASK_TYPES = [
    "lexical_sense",
    "lemma",
    "morphology_segmentation",
    "morpheme_function",
    "grammar_construction",
    "register_domain",
    "alignment_spotcheck",
    "governance_export",
    "pronunciation",
]

EXPECTED_DECISION_KINDS = ["accept", "reject", "modify", "uncertain", "defer"]


def _task(**overrides: object) -> ReviewTask:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.REVIEW_TASK),
        "task_type": ReviewTaskType.LEXICAL_SENSE,
        "target_id": new_id(IdPrefix.SENSE),
        "required_role": "community_linguist",
        "priority": 0.75,
        "reason": "competing_glosses",
        "creator_run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return ReviewTask(**values)  # type: ignore[arg-type]


def _decision(**overrides: object) -> ReviewDecision:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.REVIEW_DECISION),
        "task_id": new_id(IdPrefix.REVIEW_TASK),
        "target_id": new_id(IdPrefix.SENSE),
        "decision": ReviewDecisionKind.ACCEPT,
        "reviewer_id": "reviewer-maria",
        "reviewer_role": "community_linguist",
        "created_at": NOW,
    }
    values.update(overrides)
    return ReviewDecision(**values)  # type: ignore[arg-type]


def test_review_task_type_enum_values() -> None:
    assert [member.value for member in ReviewTaskType] == EXPECTED_TASK_TYPES


def test_review_decision_kind_enum_values() -> None:
    assert [member.value for member in ReviewDecisionKind] == EXPECTED_DECISION_KINDS


def test_enum_members_are_string_enums() -> None:
    assert all(isinstance(member.value, str) for member in ReviewTaskType)
    assert all(isinstance(member.value, str) for member in ReviewDecisionKind)


def test_task_ids_carry_plan_prefixes() -> None:
    task = _task()
    decision = _decision()
    assert ID_PATTERN.match(task.id) is not None
    assert task.id.startswith(f"{IdPrefix.REVIEW_TASK.value}_")
    assert decision.id.startswith(f"{IdPrefix.REVIEW_DECISION.value}_")
    assert decision.task_id.startswith(f"{IdPrefix.REVIEW_TASK.value}_")
    assert task.creator_run_id.startswith(f"{IdPrefix.RUN.value}_")


@pytest.mark.parametrize(
    ("factory", "field", "prefix"),
    [
        (_task, "id", IdPrefix.REVIEW_TASK),
        (_task, "creator_run_id", IdPrefix.RUN),
        (_decision, "id", IdPrefix.REVIEW_DECISION),
        (_decision, "task_id", IdPrefix.REVIEW_TASK),
    ],
)
def test_plain_ids_are_rejected(factory, field: str, prefix: IdPrefix) -> None:
    wrong = new_id(IdPrefix.SEGMENT)
    with pytest.raises(ValidationError):
        factory(**{field: wrong})


@pytest.mark.parametrize("factory", [_task, _decision])
def test_models_are_frozen_domain_models(factory) -> None:
    model = factory()
    assert isinstance(model, DomainModel)
    with pytest.raises(ValidationError):
        model.created_at = NOW  # type: ignore[misc]


@pytest.mark.parametrize("factory", [_task, _decision])
def test_extra_fields_are_forbidden(factory) -> None:
    with pytest.raises(ValidationError):
        factory(unexpected_field=1)


@pytest.mark.parametrize("factory", [_task, _decision])
def test_naive_and_non_utc_datetimes_are_rejected(factory) -> None:
    with pytest.raises(ValidationError):
        factory(created_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        factory(created_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))))


def test_task_defaults() -> None:
    task = _task()
    assert task.task_type is ReviewTaskType.LEXICAL_SENSE
    assert task.target_version is None
    assert task.evidence_item_ids == []
    assert task.status == "open"
    assert task.priority == 0.75


def test_task_status_string_is_not_a_lifecycle_status() -> None:
    task = _task()
    assert isinstance(task.status, str)
    assert not hasattr(type(task), "status") or not isinstance(task.status, object.__class__)
    # An operational queue state, not `candidate/supported/validated/...`.
    for status in ("open", "in_review", "resolved", "cancelled"):
        assert _task(status=status).status == status
    with pytest.raises(ValidationError):
        _task(status="validated")
    with pytest.raises(ValidationError):
        _task(status=LifecycleStatus.CANDIDATE)  # not the lifecycle enum


@pytest.mark.parametrize("task_type", list(ReviewTaskType))
def test_every_task_type_is_accepted(task_type: ReviewTaskType) -> None:
    assert _task(task_type=task_type).task_type is task_type


@pytest.mark.parametrize("kind", list(ReviewDecisionKind))
def test_every_decision_kind_is_accepted(kind: ReviewDecisionKind) -> None:
    assert _decision(decision=kind).decision is kind


def test_target_ids_must_be_prefixed_ids() -> None:
    with pytest.raises(ValidationError):
        _task(target_id="not-an-id")
    with pytest.raises(ValidationError):
        _decision(target_id="not-an-id")
    with pytest.raises(ValidationError):
        _decision(target_id="")


def test_target_id_accepts_any_known_prefix() -> None:
    for prefix in (IdPrefix.SENSE, IdPrefix.LEXEME, IdPrefix.CONCEPT, IdPrefix.FORM_LEXEME):
        value = new_id(prefix)
        assert _task(target_id=value).target_id == value
        assert _decision(target_id=value).target_id == value


def test_evidence_item_ids_are_prefixed_ids() -> None:
    evidence = (new_id(IdPrefix.EVIDENCE), new_id(IdPrefix.EVIDENCE))
    task = _task(evidence_item_ids=list(evidence))
    assert task.evidence_item_ids == list(evidence)

    with pytest.raises(ValidationError):
        _task(evidence_item_ids=["not-an-id"])
    with pytest.raises(ValidationError):
        _task(evidence_item_ids=[new_id(IdPrefix.SEGMENT)])


def test_task_required_role_and_reason_and_priority() -> None:
    task = _task(
        required_role="native_speaker_elder",
        reason="restricted_term",
        priority=1.0,
        target_version="1",
    )
    assert task.required_role == "native_speaker_elder"
    assert task.reason == "restricted_term"
    assert task.priority == 1.0
    assert task.target_version == "1"

    with pytest.raises(ValidationError):
        _task(required_role="")
    with pytest.raises(ValidationError):
        _task(reason="")
    with pytest.raises(ValidationError):
        _task(priority="high")
    with pytest.raises(ValidationError):
        _task(priority=None)
    for non_finite in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            _task(priority=non_finite)
    for boolean in (True, False):
        with pytest.raises(ValidationError):
            _task(priority=boolean)
    assert _task(priority=-0.5).priority == -0.5
    assert _task(priority=0.0).priority == 0.0


def test_decision_optional_fields_default_none() -> None:
    decision = _decision()
    assert decision.superseding_object_id is None
    assert decision.notes is None
    assert decision.reviewer_role == "community_linguist"
    assert decision.reviewer_id == "reviewer-maria"


def test_decision_records_superseding_object_and_notes() -> None:
    superseding = new_id(IdPrefix.LEXEME)
    decision = _decision(
        decision=ReviewDecisionKind.MODIFY,
        superseding_object_id=superseding,
        notes="corrected gloss",
    )
    assert decision.decision is ReviewDecisionKind.MODIFY
    assert decision.superseding_object_id == superseding
    assert decision.notes == "corrected gloss"

    with pytest.raises(ValidationError):
        _decision(superseding_object_id="not-an-id")
    with pytest.raises(ValidationError):
        _decision(reviewer_id="")
    with pytest.raises(ValidationError):
        _decision(reviewer_role="")


@pytest.mark.parametrize(
    ("model", "factory"),
    [(ReviewTask, _task), (ReviewDecision, _decision)],
)
def test_json_roundtrip(model, factory) -> None:
    if model is ReviewTask:
        original = _task(
            target_version="3",
            evidence_item_ids=[new_id(IdPrefix.EVIDENCE)],
            status="in_review",
        )
    else:
        original = _decision(
            decision=ReviewDecisionKind.DEFER,
            superseding_object_id=new_id(IdPrefix.SENSE),
            notes="needs a second speaker",
        )
    dumped = original.model_dump(mode="json")
    assert model.model_validate(dumped) == original
    assert model.model_validate_json(json.dumps(dumped)) == original
    payload = original.model_dump_json()
    assert json.loads(payload)["id"] == original.id
    assert json.loads(payload)["created_at"] == "2026-01-01T00:00:00Z"


def test_schema_names() -> None:
    assert ReviewTask.SCHEMA_NAME == "review-task"
    assert ReviewDecision.SCHEMA_NAME == "review-decision"
    assert _task().SCHEMA_VERSION == 1
    assert _decision().SCHEMA_VERSION == 1


def test_decisions_are_immutable_records_not_edited_in_place() -> None:
    decision = _decision()
    with pytest.raises(ValidationError):
        decision.decision = ReviewDecisionKind.REJECT  # type: ignore[misc]
    # A changed opinion records a NEW decision (docs/REVIEW-WORKFLOW.md immutability).
    revised = _decision(
        task_id=decision.task_id,
        target_id=decision.target_id,
        decision=ReviewDecisionKind.REJECT,
    )
    assert revised.id != decision.id
    assert revised.decision is ReviewDecisionKind.REJECT
    assert decision.decision is ReviewDecisionKind.ACCEPT
