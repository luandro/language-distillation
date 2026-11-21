import inspect
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    AuditEventType,
    RunStage,
    RunStatus,
)
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LATER = datetime(2026, 1, 2, tzinfo=UTC)
SHA = "b" * 64
CONFIG: dict[str, object] = {"batch": 10, "profile": "default"}


def _run(**overrides: object) -> ProcessingRun:
    data: dict[str, object] = {
        "id": new_id(IdPrefix.RUN),
        "stage": RunStage.SOURCE_REGISTRATION,
        "tool_name": "langpipe.register",
        "tool_version": "0.1.0",
        "config": CONFIG,
        "config_hash": config_hash(CONFIG),
        "code_revision": "abc1234",
        "run_key": SHA,
        "status": RunStatus.RUNNING,
        "started_at": NOW,
    }
    data.update(overrides)
    return ProcessingRun.model_validate(data)


def test_run_key_independent_of_input_order() -> None:
    first = ProcessingRun.compute_run_key(
        RunStage.RAW_INGESTION, "langpipe.ingest", "0.1.0", SHA, ["sobj_a", "sobj_b"]
    )
    second = ProcessingRun.compute_run_key(
        RunStage.RAW_INGESTION, "langpipe.ingest", "0.1.0", SHA, ["sobj_b", "sobj_a"]
    )
    assert first == second
    assert len(first) == 64


def test_run_key_ignores_code_revision() -> None:
    parameters = inspect.signature(ProcessingRun.compute_run_key).parameters
    assert "code_revision" not in parameters
    assert not any("revision" in name for name in parameters)


def test_config_hash_must_match_config() -> None:
    with pytest.raises(ValidationError):
        _run(config_hash=SHA)


def test_running_run_cannot_have_finished_at() -> None:
    with pytest.raises(ValidationError):
        _run(status=RunStatus.RUNNING, finished_at=LATER)


def test_failed_run_requires_error_type() -> None:
    with pytest.raises(ValidationError):
        _run(status=RunStatus.FAILED, finished_at=LATER, error_message="boom")


def test_failed_run_with_error_type_is_valid() -> None:
    run = _run(
        status=RunStatus.FAILED,
        finished_at=LATER,
        error_type="PolicyDenied",
    )
    assert run.status is RunStatus.FAILED


def test_succeeded_run_requires_finished_at_and_no_error() -> None:
    with pytest.raises(ValidationError):
        _run(status=RunStatus.SUCCEEDED)
    with pytest.raises(ValidationError):
        _run(status=RunStatus.SUCCEEDED, finished_at=LATER, error_type="X")


@pytest.mark.parametrize(
    ("status", "finished_at"),
    [(RunStatus.RUNNING, None), (RunStatus.SUCCEEDED, LATER)],
)
@pytest.mark.parametrize("field", ["error_type", "error_message"])
@pytest.mark.parametrize("value", ["", "boom"])
def test_running_and_succeeded_runs_reject_any_error_field(
    status: RunStatus, finished_at: datetime | None, field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        _run(status=status, finished_at=finished_at, **{field: value})


@pytest.mark.parametrize(
    ("status", "finished_at"),
    [(RunStatus.RUNNING, None), (RunStatus.SUCCEEDED, LATER)],
)
def test_running_and_succeeded_runs_accept_none_error_fields(
    status: RunStatus, finished_at: datetime | None
) -> None:
    run = _run(status=status, finished_at=finished_at, error_type=None, error_message=None)
    assert run.error_type is None
    assert run.error_message is None


def test_audit_details_reject_free_text() -> None:
    with pytest.raises(ValidationError):
        AuditEvent(
            id=new_id(IdPrefix.AUDIT),
            event_type=AuditEventType.POLICY_DENIED,
            actor="cli",
            subject_id=None,
            run_id=None,
            details={"some raw sentence": "x"},  # type: ignore[dict-item]
            occurred_at=NOW,
        )
    with pytest.raises(ValidationError):
        AuditEvent(
            id=new_id(IdPrefix.AUDIT),
            event_type=AuditEventType.POLICY_DENIED,
            actor="cli",
            subject_id=None,
            run_id=None,
            details={"mode": "some raw sentence"},
            occurred_at=NOW,
        )


def test_audit_details_accept_allowlisted_values() -> None:
    event = AuditEvent(
        id=new_id(IdPrefix.AUDIT),
        event_type=AuditEventType.POLICY_DENIED,
        actor="cli",
        subject_id=None,
        run_id=None,
        details={"mode": "distill_only", "operation": "read_raw", "decision": "deny", "objects": 2},
        occurred_at=NOW,
    )
    assert event.details["objects"] == 2


def test_run_schema_name_and_artifact_model() -> None:
    assert ProcessingRun.SCHEMA_NAME == "processing-run"
    assert Artifact.SCHEMA_NAME == "artifact"
    artifact = Artifact(
        id=new_id(IdPrefix.ARTIFACT),
        run_id=new_id(IdPrefix.RUN),
        kind=ArtifactKind.INGEST_REPORT,
        media_type="application/json",
        sha256=SHA,
        size_bytes=10,
        access_class=AccessClass.RESTRICTED,
        created_at=NOW,
    )
    assert artifact.schema_name is None
    assert artifact.schema_version is None
