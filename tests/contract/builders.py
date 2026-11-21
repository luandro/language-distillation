"""Valid model builders for repository contract tests. All datetimes are fixed UTC values."""

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from langpipe.domain.enums import (
    AccessClass,
    AlignmentDirection,
    AlignmentMode,
    AlignmentStatus,
    ArtifactKind,
    EvidenceKind,
    EvidencePolarity,
    PolicyMode,
    RunStage,
    RunStatus,
    SourceType,
    Symmetrization,
)
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.alignment import SegmentAlignment, TokenAlignmentEdge
from langpipe.domain.models.evidence import EvidenceItem
from langpipe.domain.models.observation import Form, Segment, TokenOccurrence
from langpipe.domain.models.run import Artifact, ProcessingRun
from langpipe.domain.models.source import Provenance, Source, SourceObject, SourcePolicy

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
LANGUAGE = "mzr"
TARGET_LANGUAGE = "por"
ALIGNMENT_METHOD = "canonical_locator@0.1.0"
TOKEN_ALGORITHM = "eflomal@0.1.0"
DEFAULT_CONFIG: dict[str, Any] = {"batch": 10, "profile": "default"}


def unique_run_key(label: str) -> str:
    """Distinct run_key per succeeded run (unique partial index ux_run_key_succeeded)."""
    return hashlib.sha256(f"wp33-{label}".encode()).hexdigest()


def make_policy(**overrides: Any) -> SourcePolicy:
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.POLICY),
        "mode": PolicyMode.DIRECT,
        "access_class": AccessClass.PUBLIC,
        "authority": "test-authority",
        "allow": (),
        "deny": (),
        "created_at": NOW,
    }
    data.update(overrides)
    return SourcePolicy.model_validate(data)


def make_source(
    policy: SourcePolicy, registration_run_id: str, key: str = "test-source", **overrides: Any
) -> Source:
    """`registration_run_id` must name a run the caller has already stored (foreign key)."""
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.SOURCE),
        "key": key,
        "title": "Test source",
        "source_type": SourceType.OTHER,
        "languages": (LANGUAGE,),
        "provenance": Provenance(acquired_from="test"),
        "policy_id": policy.id,
        "acquired_at": NOW,
        "domains": (),
        "registers": (),
        "manifest_sha256": SHA_A,
        "registration_run_id": registration_run_id,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return Source.model_validate(data)


def make_source_object(
    source: Source, registration_run_id: str, path: str = "texts/a.txt", **overrides: Any
) -> SourceObject:
    """`registration_run_id` must name a run the caller has already stored (foreign key)."""
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.SOURCE_OBJECT),
        "source_id": source.id,
        "original_path": path,
        "origin_uri": "file:///data/texts/a.txt",
        "sha256": SHA_B,
        "size_bytes": 11,
        "media_type": "text/plain",
        "access_class": AccessClass.PUBLIC,
        "registration_run_id": registration_run_id,
        "created_at": NOW,
    }
    data.update(overrides)
    return SourceObject.model_validate(data)


def make_run(
    stage: RunStage = RunStage.SOURCE_REGISTRATION,
    status: RunStatus = RunStatus.RUNNING,
    config: dict[str, Any] | None = None,
    run_key: str = SHA_C,
    **overrides: Any,
) -> ProcessingRun:
    run_config = dict(DEFAULT_CONFIG) if config is None else config
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.RUN),
        "stage": stage,
        "tool_name": "langpipe.test",
        "tool_version": "0.1.0",
        "config": run_config,
        "config_hash": config_hash(run_config),
        "code_revision": "abc1234",
        "run_key": run_key,
        "status": status,
        "started_at": NOW,
    }
    data.update(overrides)
    return ProcessingRun.model_validate(data)


def make_segment(
    source: Source,
    source_object: SourceObject,
    run: ProcessingRun,
    ordinal: int = 0,
    raw_text: str = "hello world",
    **overrides: Any,
) -> Segment:
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.SEGMENT),
        "source_id": source.id,
        "source_object_id": source_object.id,
        "run_id": run.id,
        "ordinal": ordinal,
        "language": LANGUAGE,
        "locator": {"line": ordinal + 1},
        "raw_text": raw_text,
        "created_at": NOW,
    }
    data.update(overrides)
    return Segment.model_validate(data)


def make_token(
    segment: Segment,
    run: ProcessingRun,
    ordinal: int = 0,
    surface: str = "hello",
    **overrides: Any,
) -> TokenOccurrence:
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.TOKEN),
        "segment_id": segment.id,
        "run_id": run.id,
        "ordinal": ordinal,
        "raw_surface": surface,
        "tokenizer": "whitespace@1",
        "created_at": NOW,
    }
    data.update(overrides)
    return TokenOccurrence.model_validate(data)


def make_form(run: ProcessingRun, text: str = "hello", **overrides: Any) -> Form:
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.FORM),
        "language": LANGUAGE,
        "orthography_profile": "practical@1",
        "text": text,
        "run_id": run.id,
        "created_at": NOW,
    }
    data.update(overrides)
    return Form.model_validate(data)


def make_evidence(target_id: str, run: ProcessingRun, **overrides: Any) -> EvidenceItem:
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.EVIDENCE),
        "kind": EvidenceKind.MANUAL_ANNOTATION,
        "polarity": EvidencePolarity.SUPPORTS,
        "target_id": target_id,
        "run_id": run.id,
        "created_at": NOW,
    }
    data.update(overrides)
    return EvidenceItem.model_validate(data)


def make_artifact(run: ProcessingRun, **overrides: Any) -> Artifact:
    """`run` must name a run the caller has already stored (foreign key)."""
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.ARTIFACT),
        "run_id": run.id,
        "kind": ArtifactKind.ALIGNMENT_FILE,
        "media_type": "application/json",
        "sha256": SHA_B,
        "size_bytes": 2,
        "access_class": AccessClass.PUBLIC,
        "created_at": NOW,
    }
    data.update(overrides)
    return Artifact.model_validate(data)


def alignment_sides_config(
    source_id: str,
    source_normalization_run_id: str,
    target_normalization_run_id: str,
    *,
    source_language: str = LANGUAGE,
    target_language: str = TARGET_LANGUAGE,
    source_tokenization_run_id: str | None = None,
    target_tokenization_run_id: str | None = None,
) -> dict[str, Any]:
    """Ordered side descriptors exactly as M3-PLAN §5.4 records them in the run config."""
    return {
        "sides": [
            {
                "role": "source",
                "source_id": source_id,
                "language": source_language,
                "normalization_run_id": source_normalization_run_id,
                "tokenization_run_id": source_tokenization_run_id,
            },
            {
                "role": "target",
                "source_id": source_id,
                "language": target_language,
                "normalization_run_id": target_normalization_run_id,
                "tokenization_run_id": target_tokenization_run_id,
            },
        ]
    }


def make_segment_alignment(
    run: ProcessingRun,
    source_segments: Sequence[Segment],
    target_segments: Sequence[Segment],
    **overrides: Any,
) -> SegmentAlignment:
    ordered_ids = [segment.id for segment in source_segments] + [
        segment.id for segment in target_segments
    ]
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.SEGMENT_ALIGNMENT),
        "source_segment_ids": tuple(segment.id for segment in source_segments),
        "target_segment_ids": tuple(segment.id for segment in target_segments),
        "method": ALIGNMENT_METHOD,
        "mode": AlignmentMode.CANONICAL,
        "status": AlignmentStatus.STRUCTURAL,
        "raw_scores": {},
        "group_key": hashlib.sha256("|".join(ordered_ids).encode("utf-8")).hexdigest(),
        "run_id": run.id,
        "created_at": NOW,
    }
    data.update(overrides)
    return SegmentAlignment.model_validate(data)


def make_token_alignment_edge(
    run: ProcessingRun,
    alignment: SegmentAlignment,
    source_token: TokenOccurrence,
    target_token: TokenOccurrence,
    *,
    direction: AlignmentDirection = AlignmentDirection.SYMMETRIZED,
    symmetrization: Symmetrization = Symmetrization.INTERSECTION,
    **overrides: Any,
) -> TokenAlignmentEdge:
    if direction is AlignmentDirection.SYMMETRIZED:
        if symmetrization not in (Symmetrization.INTERSECTION, Symmetrization.UNION):
            raise ValueError("symmetrized direction requires intersection or union")
    elif symmetrization is not Symmetrization.NONE:
        raise ValueError("forward/reverse direction requires symmetrization none")
    data: dict[str, Any] = {
        "id": new_id(IdPrefix.TOKEN_ALIGNMENT),
        "segment_alignment_id": alignment.id,
        "source_token_id": source_token.id,
        "target_token_id": target_token.id,
        "direction": direction,
        "algorithm": TOKEN_ALGORITHM,
        "raw_scores": {},
        "symmetrization": symmetrization,
        "run_id": run.id,
        "created_at": NOW,
    }
    data.update(overrides)
    return TokenAlignmentEdge.model_validate(data)
