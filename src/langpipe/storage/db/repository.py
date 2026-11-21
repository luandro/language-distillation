"""PostgreSQL implementation of the Repository port (ADR-0002, ADR-0009).

Rows are mapped explicitly: `_to_<entity>` builds an ORM row from a domain model and
`_from_<entity>` builds a domain model from an ORM row. JSON columns hold the nested
structures; the append-only triggers and lineage rules live in the migration.
"""

import copy
import hashlib
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from langpipe.domain.enums import (
    Abstention,
    AccessClass,
    AlignmentDirection,
    AlignmentMode,
    AlignmentStatus,
    AllomorphConditioning,
    AnalysisKind,
    ApprovalAction,
    ArtifactKind,
    AuditEventType,
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    FeatureAssignmentBasis,
    FormBasis,
    IgtFormat,
    IgtParseStatus,
    LifecycleStatus,
    LineageKind,
    MorphRole,
    Operation,
    PolicyMode,
    ReviewDecisionKind,
    ReviewTaskType,
    RunIoRole,
    RunStage,
    RunStatus,
    SegmentStatus,
    SourceStatus,
    SourceType,
    SpanRepresentation,
    Symmetrization,
)
from langpipe.domain.errors import (
    AlignmentFailed,
    ImmutableViolation,
    InvalidLineage,
    LangpipeError,
    NotFound,
    SchemaViolation,
    SourceConflict,
)
from langpipe.domain.models.alignment import SegmentAlignment, TokenAlignmentEdge
from langpipe.domain.models.approval import SourceUseApproval
from langpipe.domain.models.base import DomainModel
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.igt import IGTObservation, IgtTierLine, IgtWord
from langpipe.domain.models.lexical import (
    Concept,
    FormLexemeLink,
    Lexeme,
    LexicalScoreBreakdown,
    Sense,
)
from langpipe.domain.models.morphology import (
    Allomorph,
    Feature,
    MorphAnalysis,
    Morpheme,
    MorphSegment,
    MorphSegmentFeature,
    ScoreBreakdown,
)
from langpipe.domain.models.observation import Form, Segment, Span, TokenOccurrence
from langpipe.domain.models.review import REVIEW_TASK_STATUSES, ReviewDecision, ReviewTask
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.domain.models.source import (
    Provenance,
    RawBlob,
    Source,
    SourceObject,
    SourcePolicy,
)
from langpipe.morphology.spans import check_analysis
from langpipe.storage.db import tables
from langpipe.storage.repository import (
    AlignmentSideDescriptor,
    Repository,
    alignment_side_descriptors,
    checked_min_priority,
    queue_status_filter,
    token_surface_for,
)

_RESTRICT_VIOLATION = "23001"
_UNIQUE_VIOLATION = "23505"
_LOCK_NOT_AVAILABLE = "55P03"

# Session advisory locks poll with a short bounded backoff until the caller's deadline.
_ADVISORY_POLL_SECONDS = 0.05
_ADVISORY_MAX_POLL_SECONDS = 0.25


def _advisory_key(request_key: str) -> int:
    """Deterministic signed 64-bit session advisory lock key from the request identity."""
    digest = hashlib.sha256(request_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


# Recursive walks over the DAG. Each (id, depth) pair is kept once, so the query terminates
# (lineage cycles are refused at insert time). `COLLATE "C"` keeps id order identical to Python.
_ANCESTORS_SQL = sql_text(
    """
    WITH RECURSIVE walk(id, depth) AS (
        SELECT e.to_id, 1 FROM lineage_edge e WHERE e.from_id = :start
        UNION
        SELECT e.to_id, w.depth + 1 FROM walk w JOIN lineage_edge e ON e.from_id = w.id
    )
    SELECT id, MIN(depth) AS depth FROM walk
    GROUP BY id ORDER BY depth, id COLLATE "C"
    """
)
_DESCENDANTS_SQL = sql_text(
    """
    WITH RECURSIVE walk(id, depth) AS (
        SELECT e.from_id, 1 FROM lineage_edge e WHERE e.to_id = :start
        UNION
        SELECT e.from_id, w.depth + 1 FROM walk w JOIN lineage_edge e ON e.to_id = w.id
    )
    SELECT id, MIN(depth) AS depth FROM walk
    GROUP BY id ORDER BY depth, id COLLATE "C"
    """
)


class StorageIntegrityError(LangpipeError):
    """An unmapped database integrity violation; carries only safe diagnostics."""

    def __init__(self, sqlstate: str | None, constraint: str | None) -> None:
        self.sqlstate = sqlstate
        self.constraint = constraint
        super().__init__(
            f"storage integrity violation: sqlstate={sqlstate} constraint={constraint}"
        )


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _utc_or_none(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


def _revalidate[M: DomainModel](model: M, **changes: Any) -> M:
    """Build a changed copy through validation; `model_copy` would bypass it."""
    data = model.model_dump()
    data.update(changes)
    try:
        return type(model).model_validate(data)
    except ValidationError:
        # The Pydantic cause echoes input values (titles, text); keep it out of the chain.
        raise SchemaViolation() from None


def _translate(
    exc: IntegrityError, mapping: Mapping[str, Callable[[], LangpipeError]]
) -> LangpipeError | None:
    """Map a known constraint or trigger violation; unknown violations return None."""
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None)
    constraint: str | None = getattr(getattr(orig, "diag", None), "constraint_name", None)
    if sqlstate == _RESTRICT_VIOLATION:
        return ImmutableViolation()
    if sqlstate == _UNIQUE_VIOLATION and constraint is not None and constraint.endswith("_pkey"):
        # A duplicate identifier is an attempt to rewrite an existing object.
        return ImmutableViolation()
    if constraint is not None and constraint in mapping:
        return mapping[constraint]()
    return None


@contextmanager
def _constraints(mapping: Mapping[str, Callable[[], LangpipeError]]) -> Iterator[None]:
    """Translate database integrity errors into domain errors; re-raise everything else."""
    try:
        yield
    except IntegrityError as exc:
        mapped = _translate(exc, mapping)
        if mapped is None:
            # Unknown violations keep only SQLSTATE and constraint name: the database message
            # and SQL parameters can carry row values, so they are not retained.
            orig = exc.orig
            sqlstate = getattr(orig, "sqlstate", None)
            constraint: str | None = getattr(getattr(orig, "diag", None), "constraint_name", None)
            raise StorageIntegrityError(sqlstate, constraint) from None
        # The database error carries SQL parameters (raw text); it must not be chained.
        raise mapped from None


def _insert(
    session: Session,
    row: object,
    mapping: Mapping[str, Callable[[], LangpipeError]] | None = None,
) -> None:
    with _constraints(mapping or {}):
        session.add(row)
        session.flush()


def _register(
    session: Session, object_id: str, entity_type: EntityType, created_at: datetime
) -> None:
    _insert(
        session,
        tables.ObjectRegistry(id=object_id, entity_type=entity_type.value, created_at=created_at),
    )


def _require_registered(session: Session, object_id: str) -> None:
    if session.get(tables.ObjectRegistry, object_id) is None:
        raise InvalidLineage()


def _require[T](session: Session, model: type[T], entity: str, key: str) -> T:
    row = session.get(model, key)
    if row is None:
        raise NotFound(entity, key)
    return row


def _require_for_update[T: tables.Base](
    session: Session, model: type[T], entity: str, key: str
) -> T:
    """Read a row for mutation under a `FOR UPDATE` lock held until the caller commits.

    Always re-reads under the lock: an identity-map `session.get` would return the
    pre-lock snapshot of an already loaded row, so the state used to build the returned
    model could predate a concurrent writer's commit. `populate_existing` overwrites the
    mapped attributes in place, so the locked row and the session agree afterwards.
    """
    statement = select(model).filter_by(id=key).with_for_update()
    locked = session.scalars(statement.execution_options(populate_existing=True)).one_or_none()
    if locked is None:
        raise NotFound(entity, key)
    return locked


def _require_run(session: Session, run_id: str) -> None:
    """Lineage parents are validated eagerly, mirroring the deferred foreign keys."""
    if session.get(tables.ProcessingRun, run_id) is None:
        raise InvalidLineage()


# --- domain model -> ORM row --------------------------------------------------------------


def _to_policy(p: SourcePolicy) -> tables.SourcePolicy:
    return tables.SourcePolicy(
        id=p.id,
        mode=p.mode.value,
        access_class=p.access_class.value,
        authority=p.authority,
        allow=[operation.value for operation in p.allow],
        deny=[operation.value for operation in p.deny],
        restrictions=copy.deepcopy(p.restrictions),
        policy_version=p.policy_version,
        created_at=p.created_at,
    )


def _to_source(s: Source) -> tables.Source:
    return tables.Source(
        id=s.id,
        key=s.key,
        title=s.title,
        source_type=s.source_type.value,
        languages=list(s.languages),
        provenance=s.provenance.model_dump(mode="json"),
        policy_id=s.policy_id,
        acquired_at=s.acquired_at,
        status=s.status.value,
        domains=list(s.domains),
        registers=list(s.registers),
        manifest_sha256=s.manifest_sha256,
        registration_run_id=s.registration_run_id,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _to_source_object(o: SourceObject) -> tables.SourceObject:
    return tables.SourceObject(
        id=o.id,
        source_id=o.source_id,
        original_path=o.original_path,
        origin_uri=o.origin_uri,
        sha256=o.sha256,
        size_bytes=o.size_bytes,
        media_type=o.media_type,
        access_class=o.access_class.value,
        registration_run_id=o.registration_run_id,
        created_at=o.created_at,
    )


def _to_raw_blob_values(b: RawBlob) -> dict[str, Any]:
    return {
        "sha256": b.sha256,
        "size_bytes": b.size_bytes,
        "storage_backend": b.storage_backend,
        "stored_at": b.stored_at,
        "ingestion_run_id": b.ingestion_run_id,
    }


def _to_run(r: ProcessingRun) -> tables.ProcessingRun:
    return tables.ProcessingRun(
        id=r.id,
        stage=r.stage.value,
        tool_name=r.tool_name,
        tool_version=r.tool_version,
        config=copy.deepcopy(r.config),
        config_hash=r.config_hash,
        code_revision=r.code_revision,
        run_key=r.run_key,
        random_seed=r.random_seed,
        status=r.status.value,
        started_at=r.started_at,
        finished_at=r.finished_at,
        error_type=r.error_type,
        error_message=r.error_message,
    )


def _to_artifact(a: Artifact) -> tables.Artifact:
    return tables.Artifact(
        id=a.id,
        run_id=a.run_id,
        kind=a.kind.value,
        media_type=a.media_type,
        sha256=a.sha256,
        size_bytes=a.size_bytes,
        access_class=a.access_class.value,
        schema_name=a.schema_name,
        schema_version=a.schema_version,
        created_at=a.created_at,
    )


def _to_segment(s: Segment) -> tables.Segment:
    return tables.Segment(
        id=s.id,
        source_id=s.source_id,
        source_object_id=s.source_object_id,
        run_id=s.run_id,
        ordinal=s.ordinal,
        language=s.language,
        locator=copy.deepcopy(s.locator),
        raw_text=s.raw_text,
        normalized_text=s.normalized_text,
        normalization_profile=s.normalization_profile,
        status=s.status.value,
        created_at=s.created_at,
    )


def _to_token(t: TokenOccurrence) -> tables.TokenOccurrence:
    raw, norm = t.raw_span, t.normalized_span
    return tables.TokenOccurrence(
        id=t.id,
        segment_id=t.segment_id,
        run_id=t.run_id,
        ordinal=t.ordinal,
        raw_surface=t.raw_surface,
        normalized_surface=t.normalized_surface,
        raw_start=None if raw is None else raw.start,
        raw_end=None if raw is None else raw.end,
        norm_start=None if norm is None else norm.start,
        norm_end=None if norm is None else norm.end,
        tokenizer=t.tokenizer,
        form_id=t.form_id,
        created_at=t.created_at,
    )


def _to_form_values(f: Form) -> dict[str, Any]:
    return {
        "id": f.id,
        "language": f.language,
        "orthography_profile": f.orthography_profile,
        "text": f.text,
        "run_id": f.run_id,
        "created_at": f.created_at,
    }


def _to_evidence(e: EvidenceItem) -> tables.EvidenceItem:
    return tables.EvidenceItem(
        id=e.id,
        kind=e.kind.value,
        polarity=e.polarity.value,
        target_id=e.target_id,
        claim=copy.deepcopy(e.claim),
        source_id=e.source_id,
        run_id=e.run_id,
        strength=copy.deepcopy(e.strength),
        policy_version=e.policy_version,
        independence_group=e.independence_group,
        domain=e.domain,
        register=e.register,
        extensions=copy.deepcopy(e.extensions),
        created_at=e.created_at,
    )


def _to_lineage_values(e: LineageEdge) -> dict[str, Any]:
    return {
        "id": e.id,
        "from_id": e.from_id,
        "to_id": e.to_id,
        "kind": e.kind.value,
        "run_id": e.run_id,
        "created_at": e.created_at,
    }


def _to_audit(e: AuditEvent) -> tables.AuditEvent:
    return tables.AuditEvent(
        id=e.id,
        event_type=e.event_type.value,
        actor=e.actor,
        subject_id=e.subject_id,
        run_id=e.run_id,
        details=copy.deepcopy(e.details),
        occurred_at=e.occurred_at,
    )


def _to_segment_alignment(a: SegmentAlignment) -> tables.SegmentAlignment:
    # creating_txid is database-owned: trg_segment_alignment_stamp_creation stamps it.
    return tables.SegmentAlignment(
        id=a.id,
        method=a.method,
        mode=a.mode.value,
        status=a.status.value,
        score=a.score,
        raw_scores=copy.deepcopy(a.raw_scores),
        group_key=a.group_key,
        run_id=a.run_id,
        authorization_basis_id=a.authorization_basis_id,
        supersedes_id=a.supersedes_id,
        created_at=a.created_at,
    )


def _to_token_alignment_edge(e: TokenAlignmentEdge) -> tables.TokenAlignmentEdge:
    return tables.TokenAlignmentEdge(
        id=e.id,
        segment_alignment_id=e.segment_alignment_id,
        source_token_id=e.source_token_id,
        target_token_id=e.target_token_id,
        direction=e.direction.value,
        algorithm=e.algorithm,
        score=e.score,
        raw_scores=copy.deepcopy(e.raw_scores),
        symmetrization=e.symmetrization.value,
        run_id=e.run_id,
        created_at=e.created_at,
    )


def _to_concept(c: Concept) -> tables.Concept:
    return tables.Concept(
        id=c.id,
        concept_type=c.concept_type,
        canonical_label=c.canonical_label,
        concepticon_id=c.concepticon_id,
        external_urn=c.external_urn,
        run_id=c.run_id,
        created_at=c.created_at,
    )


def _to_lexeme(lexeme: Lexeme) -> tables.Lexeme:
    return tables.Lexeme(
        id=lexeme.id,
        language=lexeme.language,
        lemma_form_id=lexeme.lemma_form_id,
        pos=lexeme.pos,
        status=lexeme.status.value,
        register=lexeme.register,
        domain=lexeme.domain,
        score_breakdown=(
            None if lexeme.score_breakdown is None else lexeme.score_breakdown.model_dump()
        ),
        run_id=lexeme.run_id,
        created_at=lexeme.created_at,
    )


def _to_form_lexeme_values(link: FormLexemeLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "form_id": link.form_id,
        "lexeme_id": link.lexeme_id,
        "role": link.role,
        "run_id": link.run_id,
        "created_at": link.created_at,
    }


def _to_sense(s: Sense) -> tables.Sense:
    return tables.Sense(
        id=s.id,
        lexeme_id=s.lexeme_id,
        glosses=copy.deepcopy(s.glosses),
        concept_id=s.concept_id,
        status=s.status.value,
        domain=s.domain,
        register=s.register,
        score_breakdown=None if s.score_breakdown is None else s.score_breakdown.model_dump(),
        run_id=s.run_id,
        created_at=s.created_at,
    )


def _to_review_task(task: ReviewTask) -> tables.ReviewTask:
    return tables.ReviewTask(
        id=task.id,
        task_type=task.task_type.value,
        target_id=task.target_id,
        target_version=task.target_version,
        evidence_item_ids=list(task.evidence_item_ids),
        required_role=task.required_role,
        priority=task.priority,
        reason=task.reason,
        creator_run_id=task.creator_run_id,
        status=task.status,
        created_at=task.created_at,
    )


def _to_review_decision(d: ReviewDecision) -> tables.ReviewDecision:
    return tables.ReviewDecision(
        id=d.id,
        task_id=d.task_id,
        target_id=d.target_id,
        decision=d.decision.value,
        reviewer_id=d.reviewer_id,
        reviewer_role=d.reviewer_role,
        superseding_object_id=d.superseding_object_id,
        notes=d.notes,
        created_at=d.created_at,
    )


# --- ORM row -> domain model --------------------------------------------------------------


def _from_policy(row: tables.SourcePolicy) -> SourcePolicy:
    return SourcePolicy(
        id=row.id,
        mode=PolicyMode(row.mode),
        access_class=AccessClass(row.access_class),
        authority=row.authority,
        allow=tuple(Operation(value) for value in row.allow),
        deny=tuple(Operation(value) for value in row.deny),
        restrictions=copy.deepcopy(row.restrictions),
        policy_version=row.policy_version,
        created_at=_utc(row.created_at),
    )


def _from_source(row: tables.Source) -> Source:
    return Source(
        id=row.id,
        key=row.key,
        title=row.title,
        source_type=SourceType(row.source_type),
        languages=tuple(row.languages),
        provenance=Provenance.model_validate(row.provenance),
        policy_id=row.policy_id,
        acquired_at=_utc(row.acquired_at),
        status=SourceStatus(row.status),
        domains=tuple(row.domains),
        registers=tuple(row.registers),
        manifest_sha256=row.manifest_sha256,
        registration_run_id=row.registration_run_id,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _from_source_object(row: tables.SourceObject) -> SourceObject:
    return SourceObject(
        id=row.id,
        source_id=row.source_id,
        original_path=row.original_path,
        origin_uri=row.origin_uri,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        media_type=row.media_type,
        access_class=AccessClass(row.access_class),
        registration_run_id=row.registration_run_id,
        created_at=_utc(row.created_at),
    )


def _from_raw_blob(row: tables.RawBlob) -> RawBlob:
    return RawBlob(
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        storage_backend=row.storage_backend,
        stored_at=_utc(row.stored_at),
        ingestion_run_id=row.ingestion_run_id,
    )


def _from_run(row: tables.ProcessingRun) -> ProcessingRun:
    return ProcessingRun(
        id=row.id,
        stage=RunStage(row.stage),
        tool_name=row.tool_name,
        tool_version=row.tool_version,
        config=copy.deepcopy(row.config),
        config_hash=row.config_hash,
        code_revision=row.code_revision,
        run_key=row.run_key,
        random_seed=row.random_seed,
        status=RunStatus(row.status),
        started_at=_utc(row.started_at),
        finished_at=_utc_or_none(row.finished_at),
        error_type=row.error_type,
        error_message=row.error_message,
    )


def _from_artifact(row: tables.Artifact) -> Artifact:
    return Artifact(
        id=row.id,
        run_id=row.run_id,
        kind=ArtifactKind(row.kind),
        media_type=row.media_type,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        access_class=AccessClass(row.access_class),
        schema_name=row.schema_name,
        schema_version=row.schema_version,
        created_at=_utc(row.created_at),
    )


def _from_segment(row: tables.Segment) -> Segment:
    return Segment(
        id=row.id,
        source_id=row.source_id,
        source_object_id=row.source_object_id,
        run_id=row.run_id,
        ordinal=row.ordinal,
        language=row.language,
        locator=copy.deepcopy(row.locator),
        raw_text=row.raw_text,
        normalized_text=row.normalized_text,
        normalization_profile=row.normalization_profile,
        status=SegmentStatus(row.status),
        created_at=_utc(row.created_at),
    )


def _span(representation: SpanRepresentation, start: int | None, end: int | None) -> Span | None:
    if start is None or end is None:
        return None
    return Span(representation=representation, start=start, end=end)


def _from_token(row: tables.TokenOccurrence) -> TokenOccurrence:
    return TokenOccurrence(
        id=row.id,
        segment_id=row.segment_id,
        run_id=row.run_id,
        ordinal=row.ordinal,
        raw_surface=row.raw_surface,
        normalized_surface=row.normalized_surface,
        raw_span=_span(SpanRepresentation.RAW, row.raw_start, row.raw_end),
        normalized_span=_span(SpanRepresentation.NORMALIZED, row.norm_start, row.norm_end),
        tokenizer=row.tokenizer,
        form_id=row.form_id,
        created_at=_utc(row.created_at),
    )


def _from_form(row: tables.Form) -> Form:
    return Form(
        id=row.id,
        language=row.language,
        orthography_profile=row.orthography_profile,
        text=row.text,
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _from_evidence(row: tables.EvidenceItem) -> EvidenceItem:
    return EvidenceItem(
        id=row.id,
        kind=EvidenceKind(row.kind),
        polarity=EvidencePolarity(row.polarity),
        target_id=row.target_id,
        claim=copy.deepcopy(row.claim),
        source_id=row.source_id,
        run_id=row.run_id,
        strength=copy.deepcopy(row.strength),
        policy_version=row.policy_version,
        independence_group=row.independence_group,
        domain=row.domain,
        register=row.register,
        extensions=copy.deepcopy(row.extensions),
        created_at=_utc(row.created_at),
    )


def _from_lineage(row: tables.LineageEdge) -> LineageEdge:
    return LineageEdge(
        id=row.id,
        from_id=row.from_id,
        to_id=row.to_id,
        kind=LineageKind(row.kind),
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _from_audit(row: tables.AuditEvent) -> AuditEvent:
    return AuditEvent(
        id=row.id,
        event_type=AuditEventType(row.event_type),
        actor=row.actor,
        subject_id=row.subject_id,
        run_id=row.run_id,
        details=copy.deepcopy(row.details),
        occurred_at=_utc(row.occurred_at),
    )


def _side_member_ids(
    members: Sequence[tables.SegmentAlignmentMember], side: str
) -> tuple[str, ...]:
    found = [member for member in members if member.side == side]
    return tuple(member.segment_id for member in sorted(found, key=lambda member: member.position))


def _member_ids(session: Session, alignment_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    members = session.scalars(
        select(tables.SegmentAlignmentMember).where(
            tables.SegmentAlignmentMember.alignment_id == alignment_id
        )
    ).all()
    return _side_member_ids(members, "source"), _side_member_ids(members, "target")


def _from_segment_alignment(
    row: tables.SegmentAlignment,
    source_segment_ids: tuple[str, ...],
    target_segment_ids: tuple[str, ...],
) -> SegmentAlignment:
    return SegmentAlignment(
        id=row.id,
        source_segment_ids=source_segment_ids,
        target_segment_ids=target_segment_ids,
        method=row.method,
        mode=AlignmentMode(row.mode),
        status=AlignmentStatus(row.status),
        score=row.score,
        raw_scores=copy.deepcopy(row.raw_scores),
        group_key=row.group_key,
        run_id=row.run_id,
        authorization_basis_id=row.authorization_basis_id,
        supersedes_id=row.supersedes_id,
        created_at=_utc(row.created_at),
    )


def _from_token_alignment_edge(row: tables.TokenAlignmentEdge) -> TokenAlignmentEdge:
    return TokenAlignmentEdge(
        id=row.id,
        segment_alignment_id=row.segment_alignment_id,
        source_token_id=row.source_token_id,
        target_token_id=row.target_token_id,
        direction=AlignmentDirection(row.direction),
        algorithm=row.algorithm,
        score=row.score,
        raw_scores=copy.deepcopy(row.raw_scores),
        symmetrization=Symmetrization(row.symmetrization),
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _score_breakdown(stored: dict[str, object] | None) -> LexicalScoreBreakdown | None:
    return None if stored is None else LexicalScoreBreakdown.model_validate(copy.deepcopy(stored))


def _from_concept(row: tables.Concept) -> Concept:
    return Concept(
        id=row.id,
        concept_type=row.concept_type,
        canonical_label=row.canonical_label,
        concepticon_id=row.concepticon_id,
        external_urn=row.external_urn,
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _from_lexeme(row: tables.Lexeme) -> Lexeme:
    return Lexeme(
        id=row.id,
        language=row.language,
        lemma_form_id=row.lemma_form_id,
        pos=row.pos,
        status=LifecycleStatus(row.status),
        register=row.register,
        domain=row.domain,
        score_breakdown=_score_breakdown(row.score_breakdown),
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _from_form_lexeme(row: tables.FormLexeme) -> FormLexemeLink:
    return FormLexemeLink(
        id=row.id,
        form_id=row.form_id,
        lexeme_id=row.lexeme_id,
        role=row.role,
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _from_sense(row: tables.Sense) -> Sense:
    return Sense(
        id=row.id,
        lexeme_id=row.lexeme_id,
        glosses=copy.deepcopy(row.glosses),
        concept_id=row.concept_id,
        status=LifecycleStatus(row.status),
        domain=row.domain,
        register=row.register,
        score_breakdown=_score_breakdown(row.score_breakdown),
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _from_review_task(row: tables.ReviewTask) -> ReviewTask:
    return ReviewTask(
        id=row.id,
        task_type=ReviewTaskType(row.task_type),
        target_id=row.target_id,
        target_version=row.target_version,
        evidence_item_ids=list(row.evidence_item_ids),
        required_role=row.required_role,
        priority=row.priority,
        reason=row.reason,
        creator_run_id=row.creator_run_id,
        status=row.status,
        created_at=_utc(row.created_at),
    )


def _from_review_decision(row: tables.ReviewDecision) -> ReviewDecision:
    return ReviewDecision(
        id=row.id,
        task_id=row.task_id,
        target_id=row.target_id,
        decision=ReviewDecisionKind(row.decision),
        reviewer_id=row.reviewer_id,
        reviewer_role=row.reviewer_role,
        superseding_object_id=row.superseding_object_id,
        notes=row.notes,
        created_at=_utc(row.created_at),
    )


def _to_igt_observation(o: IGTObservation) -> tables.IGTObservation:
    return tables.IGTObservation(
        id=o.id,
        source_id=o.source_id,
        source_object_id=o.source_object_id,
        run_id=o.run_id,
        segment_id=o.segment_id,
        record_ordinal=o.record_ordinal,
        record_ref=o.record_ref,
        format=o.format.value,
        locator=copy.deepcopy(o.locator),
        tiers=[tier.model_dump(mode="json") for tier in o.tiers],
        words=[word.model_dump(mode="json") for word in o.words],
        translations=copy.deepcopy(o.translations),
        parse_status=o.parse_status.value,
        diagnostics=list(o.diagnostics),
        created_at=o.created_at,
    )


def _from_igt_observation(row: tables.IGTObservation) -> IGTObservation:
    return IGTObservation(
        id=row.id,
        source_id=row.source_id,
        source_object_id=row.source_object_id,
        run_id=row.run_id,
        segment_id=row.segment_id,
        record_ordinal=row.record_ordinal,
        record_ref=row.record_ref,
        format=IgtFormat(row.format),
        locator=copy.deepcopy(row.locator),
        tiers=[IgtTierLine.model_validate(copy.deepcopy(tier)) for tier in row.tiers],
        words=[IgtWord.model_validate(copy.deepcopy(word)) for word in row.words],
        translations=copy.deepcopy(row.translations),
        parse_status=IgtParseStatus(row.parse_status),
        diagnostics=list(row.diagnostics),
        created_at=_utc(row.created_at),
    )


def _to_feature(f: Feature) -> tables.Feature:
    return tables.Feature(
        id=f.id,
        namespace=f.namespace,
        label=f.label,
        definition=f.definition,
        defined_by=f.defined_by,
        run_id=f.run_id,
        created_at=f.created_at,
    )


def _from_feature(row: tables.Feature) -> Feature:
    return Feature(
        id=row.id,
        namespace=row.namespace,
        label=row.label,
        definition=row.definition,
        defined_by=row.defined_by,
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _to_morpheme(m: Morpheme) -> tables.Morpheme:
    return tables.Morpheme(
        id=m.id,
        language=m.language,
        role=m.role.value,
        canonical_form=m.canonical_form,
        form_basis=m.form_basis.value,
        glosses=copy.deepcopy(m.glosses),
        gloss_labels=list(m.gloss_labels),
        identity_key=m.identity_key,
        status=m.status.value,
        score_breakdown=(None if m.score_breakdown is None else m.score_breakdown.model_dump()),
        run_id=m.run_id,
        created_at=m.created_at,
    )


def _from_morpheme(row: tables.Morpheme) -> Morpheme:
    return Morpheme(
        id=row.id,
        language=row.language,
        role=MorphRole(row.role),
        canonical_form=row.canonical_form,
        form_basis=FormBasis(row.form_basis),
        glosses=copy.deepcopy(row.glosses),
        gloss_labels=list(row.gloss_labels),
        identity_key=row.identity_key,
        status=LifecycleStatus(row.status),
        score_breakdown=_score_breakdown(row.score_breakdown),
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _to_allomorph(a: Allomorph) -> tables.Allomorph:
    return tables.Allomorph(
        id=a.id,
        morpheme_id=a.morpheme_id,
        form=a.form,
        is_zero=a.is_zero,
        form_basis=a.form_basis.value,
        conditioning=a.conditioning.value,
        conditioning_note=a.conditioning_note,
        status=a.status.value,
        run_id=a.run_id,
        created_at=a.created_at,
    )


def _from_allomorph(row: tables.Allomorph) -> Allomorph:
    return Allomorph(
        id=row.id,
        morpheme_id=row.morpheme_id,
        form=row.form,
        is_zero=row.is_zero,
        form_basis=FormBasis(row.form_basis),
        conditioning=AllomorphConditioning(row.conditioning),
        conditioning_note=row.conditioning_note,
        status=LifecycleStatus(row.status),
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _to_morph_analysis(a: MorphAnalysis) -> tables.MorphAnalysis:
    return tables.MorphAnalysis(
        id=a.id,
        target_token_id=a.target_token_id,
        analysis_kind=a.analysis_kind.value,
        method=a.method,
        span_representation=a.span_representation.value,
        surface=a.surface,
        signature=a.signature,
        abstention=None if a.abstention is None else a.abstention.value,
        status=a.status.value,
        score_breakdown=(None if a.score_breakdown is None else a.score_breakdown.model_dump()),
        run_id=a.run_id,
        created_at=a.created_at,
    )


def _from_morph_analysis(row: tables.MorphAnalysis) -> MorphAnalysis:
    return MorphAnalysis(
        id=row.id,
        target_token_id=row.target_token_id,
        analysis_kind=AnalysisKind(row.analysis_kind),
        method=row.method,
        span_representation=SpanRepresentation(row.span_representation),
        surface=row.surface,
        signature=row.signature,
        abstention=None if row.abstention is None else Abstention(row.abstention),
        status=LifecycleStatus(row.status),
        score_breakdown=_score_breakdown(row.score_breakdown),
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


def _to_morph_segment(s: MorphSegment) -> tables.MorphSegment:
    return tables.MorphSegment(
        id=s.id,
        analysis_id=s.analysis_id,
        ordinal=s.ordinal,
        start=s.start,
        end=s.end,
        is_zero=s.is_zero,
        surface=s.surface,
        morpheme_id=s.morpheme_id,
        allomorph_id=s.allomorph_id,
        role=None if s.role is None else s.role.value,
        source_gloss=s.source_gloss,
        created_at=s.created_at,
    )


def _from_morph_segment(row: tables.MorphSegment) -> MorphSegment:
    return MorphSegment(
        id=row.id,
        analysis_id=row.analysis_id,
        ordinal=row.ordinal,
        start=row.start,
        end=row.end,
        is_zero=row.is_zero,
        surface=row.surface,
        morpheme_id=row.morpheme_id,
        allomorph_id=row.allomorph_id,
        role=None if row.role is None else MorphRole(row.role),
        source_gloss=row.source_gloss,
        created_at=_utc(row.created_at),
    )


def _to_morph_segment_feature(sf: MorphSegmentFeature) -> tables.MorphSegmentFeature:
    return tables.MorphSegmentFeature(
        segment_id=sf.segment_id,
        feature_id=sf.feature_id,
        basis=sf.basis.value,
        created_at=sf.created_at,
    )


def _from_morph_segment_feature(row: tables.MorphSegmentFeature) -> MorphSegmentFeature:
    return MorphSegmentFeature(
        segment_id=row.segment_id,
        feature_id=row.feature_id,
        basis=FeatureAssignmentBasis(row.basis),
        created_at=_utc(row.created_at),
    )


def _to_source_use_approval(a: SourceUseApproval) -> tables.SourceUseApproval:
    return tables.SourceUseApproval(
        id=a.id,
        source_id=a.source_id,
        operation=a.operation.value,
        action=a.action.value,
        approver_id=a.approver_id,
        approver_role=a.approver_role,
        basis=a.basis,
        run_id=a.run_id,
        created_at=a.created_at,
    )


def _from_source_use_approval(row: tables.SourceUseApproval) -> SourceUseApproval:
    return SourceUseApproval(
        id=row.id,
        source_id=row.source_id,
        operation=Operation(row.operation),
        action=ApprovalAction(row.action),
        approver_id=row.approver_id,
        approver_role=row.approver_role,
        basis=row.basis,
        run_id=row.run_id,
        created_at=_utc(row.created_at),
    )


class PostgresRepository(Repository):
    """Repository backed by PostgreSQL. Writes need `transaction()`; reads work without one."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session: Session | None = None

    # --- transactions and session access --------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._session is not None:
            raise RuntimeError("nested transactions are not supported")
        with Session(self._engine) as session, _constraints({}), session.begin():
            self._session = session
            try:
                yield
            finally:
                self._session = None

    def _writer(self) -> Session:
        if self._session is None:
            raise RuntimeError("write outside transaction")
        return self._session

    @contextmanager
    def _reader(self) -> Iterator[Session]:
        if self._session is not None:
            yield self._session
            return
        with Session(self._engine) as session:
            yield session

    # --- policies and sources -------------------------------------------------------------

    def add_policy(self, p: SourcePolicy) -> None:
        _insert(self._writer(), _to_policy(p))

    def get_policy(self, policy_id: str) -> SourcePolicy:
        with self._reader() as session:
            return _from_policy(_require(session, tables.SourcePolicy, "source_policy", policy_id))

    def add_source(self, s: Source) -> None:
        session = self._writer()
        _register(session, s.id, EntityType.SOURCE, s.created_at)
        _insert(session, _to_source(s), {"uq_source_key": lambda: SourceConflict(s.key)})

    def get_source(self, source_id: str) -> Source:
        with self._reader() as session:
            row = _require(session, tables.Source, EntityType.SOURCE.value, source_id)
            return _from_source(row)

    def find_source_by_key(self, key: str) -> Source | None:
        with self._reader() as session:
            row = session.scalars(select(tables.Source).where(tables.Source.key == key)).first()
            return None if row is None else _from_source(row)

    def set_source_status(self, source_id: str, status: SourceStatus, at: datetime) -> Source:
        session = self._writer()
        row = _require(session, tables.Source, EntityType.SOURCE.value, source_id)
        updated = _revalidate(_from_source(row), status=status, updated_at=at)
        row.status = status.value
        row.updated_at = at
        with _constraints({}):
            session.flush()
        return updated

    def add_source_object(self, o: SourceObject) -> None:
        session = self._writer()
        # Name the source by its key; the path is a file name and stays out of errors.
        source_key = _require(session, tables.Source, EntityType.SOURCE.value, o.source_id).key
        _register(session, o.id, EntityType.SOURCE_OBJECT, o.created_at)
        _insert(
            session,
            _to_source_object(o),
            {"uq_source_object_source_path": lambda: SourceConflict(source_key)},
        )

    def get_source_object(self, object_id: str) -> SourceObject:
        with self._reader() as session:
            row = _require(session, tables.SourceObject, EntityType.SOURCE_OBJECT.value, object_id)
            return _from_source_object(row)

    def list_source_objects(self, source_id: str) -> list[SourceObject]:
        with self._reader() as session:
            rows = session.scalars(
                select(tables.SourceObject).where(tables.SourceObject.source_id == source_id)
            ).all()
        return [_from_source_object(row) for row in sorted(rows, key=lambda r: r.original_path)]

    # --- raw blobs ------------------------------------------------------------------------

    def add_raw_blob(self, b: RawBlob) -> RawBlob:
        session = self._writer()
        statement = (
            pg_insert(tables.RawBlob)
            .values(_to_raw_blob_values(b))
            .on_conflict_do_nothing(index_elements=["sha256"])
            .returning(tables.RawBlob)
        )
        with _constraints({}):
            inserted = session.scalars(statement).first()
            if inserted is not None:
                return _from_raw_blob(inserted)
            existing = _require(session, tables.RawBlob, "raw_blob", b.sha256)
        return _from_raw_blob(existing)

    def get_raw_blob(self, sha256: str) -> RawBlob | None:
        with self._reader() as session:
            row = session.get(tables.RawBlob, sha256)
            return None if row is None else _from_raw_blob(row)

    # --- runs -----------------------------------------------------------------------------

    def add_run(self, r: ProcessingRun) -> None:
        session = self._writer()
        _register(session, r.id, EntityType.PROCESSING_RUN, r.started_at)
        _insert(session, _to_run(r))

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        finished_at: datetime,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> ProcessingRun:
        session = self._writer()
        row = _require(session, tables.ProcessingRun, EntityType.PROCESSING_RUN.value, run_id)
        if row.status != RunStatus.RUNNING.value or status is RunStatus.RUNNING:
            raise ImmutableViolation()
        updated = _revalidate(
            _from_run(row),
            status=status,
            finished_at=finished_at,
            error_type=error_type,
            error_message=error_message,
        )
        row.status = status.value
        row.finished_at = finished_at
        row.error_type = error_type
        row.error_message = error_message
        with _constraints({}):
            session.flush()
        return updated

    def get_run(self, run_id: str) -> ProcessingRun:
        with self._reader() as session:
            row = _require(session, tables.ProcessingRun, EntityType.PROCESSING_RUN.value, run_id)
            return _from_run(row)

    def find_succeeded_run(self, run_key: str) -> ProcessingRun | None:
        statement = (
            select(tables.ProcessingRun)
            .where(
                tables.ProcessingRun.run_key == run_key,
                tables.ProcessingRun.status == RunStatus.SUCCEEDED.value,
            )
            .order_by(tables.ProcessingRun.started_at, tables.ProcessingRun.id)
            .limit(1)
        )
        with self._reader() as session:
            row = session.scalars(statement).first()
            return None if row is None else _from_run(row)

    def list_runs_with_input(
        self, object_id: str, stage: RunStage, status: RunStatus | None = None
    ) -> list[ProcessingRun]:
        statement = (
            select(tables.ProcessingRun)
            .join(
                tables.ProcessingRunIo,
                tables.ProcessingRunIo.run_id == tables.ProcessingRun.id,
            )
            .where(
                tables.ProcessingRunIo.object_id == object_id,
                tables.ProcessingRunIo.role == RunIoRole.INPUT.value,
                tables.ProcessingRun.stage == stage.value,
            )
        )
        if status is not None:
            statement = statement.where(tables.ProcessingRun.status == status.value)
        statement = statement.order_by(tables.ProcessingRun.started_at, tables.ProcessingRun.id)
        with self._reader() as session:
            return [_from_run(row) for row in session.scalars(statement).all()]

    def add_run_io(self, run_id: str, object_id: str, role: RunIoRole) -> None:
        session = self._writer()
        _require_registered(session, object_id)
        statement = (
            pg_insert(tables.ProcessingRunIo)
            .values(run_id=run_id, object_id=object_id, role=role.value)
            .on_conflict_do_nothing(index_elements=["run_id", "object_id", "role"])
        )
        with _constraints({}):
            session.execute(statement)

    def list_run_io(self, run_id: str) -> list[tuple[str, RunIoRole]]:
        with self._reader() as session:
            rows = session.scalars(
                select(tables.ProcessingRunIo).where(tables.ProcessingRunIo.run_id == run_id)
            ).all()
        pairs = [(row.object_id, RunIoRole(row.role)) for row in rows]
        return sorted(pairs, key=lambda pair: (pair[0], pair[1].value))

    def add_artifact(self, a: Artifact) -> None:
        session = self._writer()
        _register(session, a.id, EntityType.ARTIFACT, a.created_at)
        _insert(session, _to_artifact(a))

    def get_artifact(self, artifact_id: str) -> Artifact:
        with self._reader() as session:
            row = _require(session, tables.Artifact, EntityType.ARTIFACT.value, artifact_id)
            return _from_artifact(row)

    # --- observations (insert-only) -------------------------------------------------------

    def add_segment(self, s: Segment) -> None:
        session = self._writer()
        _register(session, s.id, EntityType.SEGMENT, s.created_at)
        _insert(
            session,
            _to_segment(s),
            {"uq_segment_run_object_ordinal": ImmutableViolation},
        )

    def get_segment(self, segment_id: str) -> Segment:
        with self._reader() as session:
            row = _require(session, tables.Segment, EntityType.SEGMENT.value, segment_id)
            return _from_segment(row)

    def list_segments(self, source_object_id: str) -> list[Segment]:
        statement = (
            select(tables.Segment)
            .where(tables.Segment.source_object_id == source_object_id)
            .order_by(tables.Segment.ordinal)
        )
        with self._reader() as session:
            return [_from_segment(row) for row in session.scalars(statement).all()]

    def list_segments_for_run(self, run_id: str) -> list[Segment]:
        statement = (
            select(tables.Segment)
            .where(tables.Segment.run_id == run_id)
            .order_by(tables.Segment.source_object_id, tables.Segment.ordinal)
        )
        with self._reader() as session:
            return [_from_segment(row) for row in session.scalars(statement).all()]

    def add_token(self, t: TokenOccurrence) -> None:
        session = self._writer()
        _register(session, t.id, EntityType.TOKEN_OCCURRENCE, t.created_at)
        _insert(
            session,
            _to_token(t),
            {"uq_token_run_segment_ordinal": ImmutableViolation},
        )

    def get_token(self, token_id: str) -> TokenOccurrence:
        with self._reader() as session:
            row = _require(
                session, tables.TokenOccurrence, EntityType.TOKEN_OCCURRENCE.value, token_id
            )
            return _from_token(row)

    def list_tokens(self, segment_id: str) -> list[TokenOccurrence]:
        statement = (
            select(tables.TokenOccurrence)
            .where(tables.TokenOccurrence.segment_id == segment_id)
            .order_by(tables.TokenOccurrence.ordinal)
        )
        with self._reader() as session:
            return [_from_token(row) for row in session.scalars(statement).all()]

    def _select_form(self, session: Session, f: Form) -> tables.Form | None:
        return session.scalars(
            select(tables.Form).where(
                tables.Form.language == f.language,
                tables.Form.orthography_profile == f.orthography_profile,
                tables.Form.text == f.text,
            )
        ).first()

    def _insert_form(self, session: Session, f: Form) -> tables.Form | None:
        """Insert the form and its registry row in a savepoint; None if the key was taken."""
        statement = (
            pg_insert(tables.Form)
            .values(_to_form_values(f))
            .on_conflict_do_nothing(index_elements=["language", "orthography_profile", "text"])
            .returning(tables.Form)
        )
        savepoint = session.begin_nested()
        try:
            _register(session, f.id, EntityType.FORM, f.created_at)
            with _constraints({}):
                inserted = session.scalars(statement).first()
        except BaseException:
            savepoint.rollback()
            raise
        # Rolling back also removes the unused registry row, which append-only tables cannot
        # delete later; the form and its registry entry are kept together or not at all.
        if inserted is None:
            savepoint.rollback()
        else:
            savepoint.commit()
        return inserted

    def get_or_create_form(self, f: Form) -> Form:
        session = self._writer()
        existing = self._select_form(session, f)
        if existing is not None:
            return _from_form(existing)
        inserted = self._insert_form(session, f)
        if inserted is not None:
            return _from_form(inserted)
        # Another writer committed the same natural key after our lookup; return its form.
        winner = self._select_form(session, f)
        if winner is None:
            raise NotFound(EntityType.FORM.value, f.id)
        return _from_form(winner)

    def get_form(self, form_id: str) -> Form:
        with self._reader() as session:
            row = _require(session, tables.Form, EntityType.FORM.value, form_id)
            return _from_form(row)

    def add_evidence(self, e: EvidenceItem) -> None:
        session = self._writer()
        _require_registered(session, e.target_id)
        _register(session, e.id, EntityType.EVIDENCE_ITEM, e.created_at)
        _insert(session, _to_evidence(e))

    def get_evidence(self, evidence_id: str) -> EvidenceItem:
        with self._reader() as session:
            row = _require(
                session, tables.EvidenceItem, EntityType.EVIDENCE_ITEM.value, evidence_id
            )
            return _from_evidence(row)

    def list_evidence_for_target(self, target_id: str) -> list[EvidenceItem]:
        statement = (
            select(tables.EvidenceItem)
            .where(tables.EvidenceItem.target_id == target_id)
            .order_by(tables.EvidenceItem.created_at, tables.EvidenceItem.id)
        )
        with self._reader() as session:
            return [_from_evidence(row) for row in session.scalars(statement).all()]

    # --- lineage --------------------------------------------------------------------------

    def _find_edge(self, session: Session, e: LineageEdge) -> LineageEdge | None:
        row = session.scalars(
            select(tables.LineageEdge).where(
                tables.LineageEdge.from_id == e.from_id,
                tables.LineageEdge.to_id == e.to_id,
                tables.LineageEdge.kind == e.kind.value,
            )
        ).first()
        return None if row is None else _from_lineage(row)

    def add_lineage_edge(self, e: LineageEdge) -> LineageEdge:
        session = self._writer()
        existing = self._find_edge(session, e)
        if existing is not None:
            return existing
        _require_registered(session, e.from_id)
        _require_registered(session, e.to_id)
        # `from` depends on `to`; a cycle exists when `from` is `to` or one of its ancestors.
        if e.from_id == e.to_id or e.from_id in {node for node, _ in self.ancestors(e.to_id)}:
            raise InvalidLineage()
        statement = (
            pg_insert(tables.LineageEdge)
            .values(_to_lineage_values(e))
            .on_conflict_do_nothing(index_elements=["from_id", "to_id", "kind"])
            .returning(tables.LineageEdge)
        )
        with _constraints({}):
            inserted = session.scalars(statement).first()
        if inserted is not None:
            return _from_lineage(inserted)
        # A concurrent writer stored the same (from, to, kind) first; return that edge.
        stored = self._find_edge(session, e)
        if stored is None:
            raise NotFound("lineage_edge", e.id)
        return stored

    def list_lineage_edges(
        self, object_id: str, direction: Literal["out", "in"]
    ) -> list[LineageEdge]:
        column = tables.LineageEdge.from_id if direction == "out" else tables.LineageEdge.to_id
        statement = select(tables.LineageEdge).where(column == object_id)
        with self._reader() as session:
            rows = session.scalars(statement).all()
        return [_from_lineage(row) for row in sorted(rows, key=lambda row: row.id)]

    def list_lineage_edges_by_kind(self, kind: LineageKind) -> list[LineageEdge]:
        statement = select(tables.LineageEdge).where(tables.LineageEdge.kind == kind.value)
        with self._reader() as session:
            rows = session.scalars(statement).all()
        return [_from_lineage(row) for row in sorted(rows, key=lambda row: row.id)]

    def _walk(self, statement: Any, object_id: str) -> list[tuple[str, int]]:
        with self._reader() as session:
            rows = session.execute(statement, {"start": object_id}).all()
        return [(row.id, row.depth) for row in rows]

    def ancestors(self, object_id: str) -> list[tuple[str, int]]:
        return self._walk(_ANCESTORS_SQL, object_id)

    def descendants(self, object_id: str) -> list[tuple[str, int]]:
        return self._walk(_DESCENDANTS_SQL, object_id)

    def entity_type_of(self, object_id: str) -> EntityType | None:
        with self._reader() as session:
            row = session.get(tables.ObjectRegistry, object_id)
            return None if row is None else EntityType(row.entity_type)

    # --- alignments (M3, ADR-0011) -------------------------------------------------------

    def _alignment_side_runs(
        self, session: Session, run: tables.ProcessingRun, *, require_tokenization: bool
    ) -> tuple[AlignmentSideDescriptor, AlignmentSideDescriptor]:
        """Eager §5.4 selection validation: config shape plus registered source and pinned runs."""
        sides = alignment_side_descriptors(run.config, require_tokenization=require_tokenization)
        for side in sides:
            if session.get(tables.Source, side.source_id) is None:
                raise InvalidLineage()
            normalization = session.get(tables.ProcessingRun, side.normalization_run_id)
            if (
                normalization is None
                or normalization.stage != RunStage.NORMALIZATION.value
                or normalization.status != RunStatus.SUCCEEDED.value
            ):
                raise InvalidLineage()
            if require_tokenization or side.tokenization_run_id is not None:
                tokenization = session.get(tables.ProcessingRun, side.tokenization_run_id or "")
                if (
                    tokenization is None
                    or tokenization.stage != RunStage.TOKENIZATION.value
                    or tokenization.status != RunStatus.SUCCEEDED.value
                ):
                    raise InvalidLineage()
        return sides

    def add_segment_alignment(self, alignment: SegmentAlignment) -> None:
        session = self._writer()
        run = session.get(tables.ProcessingRun, alignment.run_id)
        if run is None or run.stage != RunStage.SEGMENT_ALIGNMENT.value:
            raise InvalidLineage()
        sides = self._alignment_side_runs(session, run, require_tokenization=False)
        member_sides = (
            (sides[0], alignment.source_segment_ids),
            (sides[1], alignment.target_segment_ids),
        )
        for side, member_ids in member_sides:
            for member_id in member_ids:
                segment = session.get(tables.Segment, member_id)
                if (
                    segment is None
                    or segment.run_id != side.normalization_run_id
                    or segment.language != side.language
                ):
                    raise InvalidLineage()
        # Disposition references are referential integrity only: the authorization basis
        # artifact and the superseded alignment must exist before any row is written,
        # mirroring the foreign keys eagerly instead of surfacing them as an unmapped
        # integrity error at commit. Importer trust, actor match and HUMAN_REVIEW policy
        # are WP3.7 service scope, not checked here.
        if alignment.authorization_basis_id is not None and (
            session.get(tables.Artifact, alignment.authorization_basis_id) is None
        ):
            raise InvalidLineage()
        if alignment.supersedes_id is not None and (
            session.get(tables.SegmentAlignment, alignment.supersedes_id) is None
        ):
            raise InvalidLineage()
        _register(session, alignment.id, EntityType.SEGMENT_ALIGNMENT, alignment.created_at)
        _insert(
            session,
            _to_segment_alignment(alignment),
            {"uq_segment_alignment_run_group_key": ImmutableViolation},
        )
        # Members are part of the parent write, never independently valid entities; the
        # deferred group guard validates the complete membership at commit.
        for side, member_ids in member_sides:
            for position, member_id in enumerate(member_ids):
                _insert(
                    session,
                    tables.SegmentAlignmentMember(
                        alignment_id=alignment.id,
                        side=side.role,
                        position=position,
                        segment_id=member_id,
                    ),
                )

    def get_segment_alignment(self, alignment_id: str) -> SegmentAlignment:
        with self._reader() as session:
            row = _require(
                session, tables.SegmentAlignment, EntityType.SEGMENT_ALIGNMENT.value, alignment_id
            )
            source_ids, target_ids = _member_ids(session, alignment_id)
        return _from_segment_alignment(row, source_ids, target_ids)

    def list_segment_alignments_for_run(self, run_id: str) -> list[SegmentAlignment]:
        statement = select(tables.SegmentAlignment).where(tables.SegmentAlignment.run_id == run_id)
        with self._reader() as session:
            rows = session.scalars(statement).all()
            if not rows:
                return []
            members = session.scalars(
                select(tables.SegmentAlignmentMember).where(
                    tables.SegmentAlignmentMember.alignment_id.in_([row.id for row in rows])
                )
            ).all()
        grouped: dict[str, list[tables.SegmentAlignmentMember]] = {}
        for member in members:
            grouped.setdefault(member.alignment_id, []).append(member)
        return [
            _from_segment_alignment(
                row,
                _side_member_ids(grouped.get(row.id, []), "source"),
                _side_member_ids(grouped.get(row.id, []), "target"),
            )
            for row in sorted(rows, key=lambda row: (row.group_key, row.id))
        ]

    def add_token_alignment_edge(self, edge: TokenAlignmentEdge) -> None:
        session = self._writer()
        run = session.get(tables.ProcessingRun, edge.run_id)
        if run is None or run.stage != RunStage.TOKEN_ALIGNMENT.value:
            raise InvalidLineage()
        sides = self._alignment_side_runs(session, run, require_tokenization=True)
        if session.get(tables.SegmentAlignment, edge.segment_alignment_id) is None:
            raise InvalidLineage()
        for token_id, side in (
            (edge.source_token_id, sides[0]),
            (edge.target_token_id, sides[1]),
        ):
            token = session.get(tables.TokenOccurrence, token_id)
            if token is None or token.run_id != side.tokenization_run_id:
                raise InvalidLineage()
            member = session.scalars(
                select(tables.SegmentAlignmentMember)
                .where(
                    tables.SegmentAlignmentMember.alignment_id == edge.segment_alignment_id,
                    tables.SegmentAlignmentMember.side == side.role,
                    tables.SegmentAlignmentMember.segment_id == token.segment_id,
                )
                .limit(1)
            ).first()
            if member is None:
                raise InvalidLineage()
        _register(session, edge.id, EntityType.TOKEN_ALIGNMENT_EDGE, edge.created_at)
        _insert(
            session,
            _to_token_alignment_edge(edge),
            {"uq_token_alignment_edge_natural_key": ImmutableViolation},
        )

    def get_token_alignment_edge(self, edge_id: str) -> TokenAlignmentEdge:
        with self._reader() as session:
            row = _require(
                session, tables.TokenAlignmentEdge, EntityType.TOKEN_ALIGNMENT_EDGE.value, edge_id
            )
            return _from_token_alignment_edge(row)

    def list_token_alignment_edges_for_run(self, run_id: str) -> list[TokenAlignmentEdge]:
        statement = select(tables.TokenAlignmentEdge).where(
            tables.TokenAlignmentEdge.run_id == run_id
        )
        with self._reader() as session:
            rows = session.scalars(statement).all()
        ordered = sorted(
            rows,
            key=lambda row: (
                row.source_token_id,
                row.target_token_id,
                row.direction,
                row.symmetrization,
                row.id,
            ),
        )
        return [_from_token_alignment_edge(row) for row in ordered]

    # --- lexical evidence (M4, ADR-0013) -----------------------------------------------------

    def add_concept(self, c: Concept) -> None:
        session = self._writer()
        _require_run(session, c.run_id)
        _register(session, c.id, EntityType.CONCEPT, c.created_at)
        _insert(session, _to_concept(c))

    def get_concept(self, concept_id: str) -> Concept:
        with self._reader() as session:
            row = _require(session, tables.Concept, EntityType.CONCEPT.value, concept_id)
            return _from_concept(row)

    def list_concepts(self) -> list[Concept]:
        statement = select(tables.Concept).order_by(tables.Concept.created_at, tables.Concept.id)
        with self._reader() as session:
            return [_from_concept(row) for row in session.scalars(statement).all()]

    def add_lexeme(self, lexeme: Lexeme) -> None:
        session = self._writer()
        _require_run(session, lexeme.run_id)
        if lexeme.lemma_form_id is not None and (
            session.get(tables.Form, lexeme.lemma_form_id) is None
        ):
            raise InvalidLineage()
        _register(session, lexeme.id, EntityType.LEXEME, lexeme.created_at)
        _insert(session, _to_lexeme(lexeme))

    def get_lexeme(self, lexeme_id: str) -> Lexeme:
        with self._reader() as session:
            row = _require(session, tables.Lexeme, EntityType.LEXEME.value, lexeme_id)
            return _from_lexeme(row)

    def list_lexemes_by_language(self, language: str) -> list[Lexeme]:
        statement = (
            select(tables.Lexeme)
            .where(tables.Lexeme.language == language)
            .order_by(tables.Lexeme.created_at, tables.Lexeme.id)
        )
        with self._reader() as session:
            return [_from_lexeme(row) for row in session.scalars(statement).all()]

    def list_lexemes_by_form(self, form_id: str) -> list[Lexeme]:
        # Resolved through the explicit form_lexeme join: ambiguity is preserved and
        # non-lemma links count, so `lemma_form_id` alone cannot answer this (ADR-0013 §1).
        statement = (
            select(tables.Lexeme)
            .join(tables.FormLexeme, tables.FormLexeme.lexeme_id == tables.Lexeme.id)
            .where(tables.FormLexeme.form_id == form_id)
            .order_by(tables.Lexeme.created_at, tables.Lexeme.id)
        )
        with self._reader() as session:
            return [_from_lexeme(row) for row in session.scalars(statement).all()]

    def set_lexeme_status(
        self,
        lexeme_id: str,
        status: LifecycleStatus,
        score_breakdown: LexicalScoreBreakdown | None = None,
    ) -> Lexeme:
        session = self._writer()
        row = _require_for_update(session, tables.Lexeme, EntityType.LEXEME.value, lexeme_id)
        updated = _revalidate(_from_lexeme(row), status=status, score_breakdown=score_breakdown)
        row.status = updated.status.value
        row.score_breakdown = (
            None if updated.score_breakdown is None else updated.score_breakdown.model_dump()
        )
        with _constraints({}):
            session.flush()
        return updated

    def add_form_lexeme_link(self, link: FormLexemeLink) -> None:
        session = self._writer()
        _require_run(session, link.run_id)
        if session.get(tables.Form, link.form_id) is None:
            raise InvalidLineage()
        if session.get(tables.Lexeme, link.lexeme_id) is None:
            raise InvalidLineage()
        _register(session, link.id, EntityType.FORM_LEXEME, link.created_at)
        _insert(
            session,
            tables.FormLexeme(**{**_to_form_lexeme_values(link)}),
            {"ux_form_lexeme_pair": ImmutableViolation},
        )

    def list_form_lexeme_links_for_form(self, form_id: str) -> list[FormLexemeLink]:
        statement = (
            select(tables.FormLexeme)
            .where(tables.FormLexeme.form_id == form_id)
            .order_by(tables.FormLexeme.created_at, tables.FormLexeme.id)
        )
        with self._reader() as session:
            return [_from_form_lexeme(row) for row in session.scalars(statement).all()]

    def list_form_lexeme_links_for_lexeme(self, lexeme_id: str) -> list[FormLexemeLink]:
        statement = (
            select(tables.FormLexeme)
            .where(tables.FormLexeme.lexeme_id == lexeme_id)
            .order_by(tables.FormLexeme.created_at, tables.FormLexeme.id)
        )
        with self._reader() as session:
            return [_from_form_lexeme(row) for row in session.scalars(statement).all()]

    def add_sense(self, s: Sense) -> None:
        session = self._writer()
        _require_run(session, s.run_id)
        if session.get(tables.Lexeme, s.lexeme_id) is None:
            raise InvalidLineage()
        if s.concept_id is not None and session.get(tables.Concept, s.concept_id) is None:
            raise InvalidLineage()
        _register(session, s.id, EntityType.SENSE, s.created_at)
        _insert(session, _to_sense(s))

    def get_sense(self, sense_id: str) -> Sense:
        with self._reader() as session:
            row = _require(session, tables.Sense, EntityType.SENSE.value, sense_id)
            return _from_sense(row)

    def list_senses_for_lexeme(self, lexeme_id: str) -> list[Sense]:
        statement = (
            select(tables.Sense)
            .where(tables.Sense.lexeme_id == lexeme_id)
            .order_by(tables.Sense.created_at, tables.Sense.id)
        )
        with self._reader() as session:
            return [_from_sense(row) for row in session.scalars(statement).all()]

    def set_sense_status(
        self,
        sense_id: str,
        status: LifecycleStatus,
        score_breakdown: LexicalScoreBreakdown | None = None,
    ) -> Sense:
        session = self._writer()
        row = _require_for_update(session, tables.Sense, EntityType.SENSE.value, sense_id)
        updated = _revalidate(_from_sense(row), status=status, score_breakdown=score_breakdown)
        row.status = updated.status.value
        row.score_breakdown = (
            None if updated.score_breakdown is None else updated.score_breakdown.model_dump()
        )
        with _constraints({}):
            session.flush()
        return updated

    # --- human review queue (M4, ADR-0013) ---------------------------------------------------

    def add_review_task(self, task: ReviewTask) -> None:
        session = self._writer()
        _require_run(session, task.creator_run_id)
        _require_registered(session, task.target_id)
        _register(session, task.id, EntityType.REVIEW_TASK, task.created_at)
        _insert(session, _to_review_task(task))

    def get_review_task(self, task_id: str) -> ReviewTask:
        with self._reader() as session:
            row = _require(session, tables.ReviewTask, EntityType.REVIEW_TASK.value, task_id)
            return _from_review_task(row)

    def get_review_task_for_update(self, task_id: str) -> ReviewTask:
        session = self._writer()
        row = _require_for_update(session, tables.ReviewTask, EntityType.REVIEW_TASK.value, task_id)
        return _from_review_task(row)

    def list_review_tasks(
        self,
        *,
        task_type: ReviewTaskType | None = None,
        required_role: str | None = None,
        status: str | None = "open",
        min_priority: float | None = None,
    ) -> list[ReviewTask]:
        wanted_status = queue_status_filter(status)
        statement = select(tables.ReviewTask)
        if wanted_status is not None:
            statement = statement.where(tables.ReviewTask.status == wanted_status)
        if task_type is not None:
            statement = statement.where(
                tables.ReviewTask.task_type == ReviewTaskType(task_type).value
            )
        if required_role is not None:
            statement = statement.where(tables.ReviewTask.required_role == required_role)
        floor = checked_min_priority(min_priority)
        if floor is not None:
            statement = statement.where(tables.ReviewTask.priority >= floor)
        statement = statement.order_by(
            tables.ReviewTask.priority.desc(),
            tables.ReviewTask.created_at,
            tables.ReviewTask.id,
        )
        with self._reader() as session:
            return [_from_review_task(row) for row in session.scalars(statement).all()]

    def set_review_task_status(self, task_id: str, status: str) -> ReviewTask:
        if status not in REVIEW_TASK_STATUSES:
            # A queue entry carries an operational state, never a LifecycleStatus.
            raise SchemaViolation()
        session = self._writer()
        row = _require_for_update(session, tables.ReviewTask, EntityType.REVIEW_TASK.value, task_id)
        updated = _revalidate(_from_review_task(row), status=status)
        row.status = updated.status
        with _constraints({}):
            session.flush()
        return updated

    def add_review_decision(self, decision: ReviewDecision) -> None:
        session = self._writer()
        if session.get(tables.ReviewTask, decision.task_id) is None:
            raise InvalidLineage()
        _require_registered(session, decision.target_id)
        if decision.superseding_object_id is not None:
            _require_registered(session, decision.superseding_object_id)
        _register(session, decision.id, EntityType.REVIEW_DECISION, decision.created_at)
        _insert(session, _to_review_decision(decision))

    def get_review_decision(self, decision_id: str) -> ReviewDecision:
        with self._reader() as session:
            row = _require(
                session, tables.ReviewDecision, EntityType.REVIEW_DECISION.value, decision_id
            )
            return _from_review_decision(row)

    def list_review_decisions_for_target(self, target_id: str) -> list[ReviewDecision]:
        statement = (
            select(tables.ReviewDecision)
            .where(tables.ReviewDecision.target_id == target_id)
            .order_by(tables.ReviewDecision.created_at, tables.ReviewDecision.id)
        )
        with self._reader() as session:
            return [_from_review_decision(row) for row in session.scalars(statement).all()]

    # --- IGT observations and the morphology graph (M5, ADR-0017) -------------------------

    def add_igt_observation(self, observation: IGTObservation) -> None:
        session = self._writer()
        # Lineage parents are validated eagerly, mirroring the deferred foreign keys.
        if session.get(tables.Source, observation.source_id) is None:
            raise InvalidLineage()
        if session.get(tables.SourceObject, observation.source_object_id) is None:
            raise InvalidLineage()
        _require_run(session, observation.run_id)
        if observation.segment_id is not None and (
            session.get(tables.Segment, observation.segment_id) is None
        ):
            raise InvalidLineage()
        _register(session, observation.id, EntityType.IGT_OBSERVATION, observation.created_at)
        _insert(
            session,
            _to_igt_observation(observation),
            {"uq_igt_observation_record": ImmutableViolation},
        )

    def get_igt_observation(self, observation_id: str) -> IGTObservation:
        with self._reader() as session:
            row = _require(
                session, tables.IGTObservation, EntityType.IGT_OBSERVATION.value, observation_id
            )
            return _from_igt_observation(row)

    def list_igt_observations_for_run(self, run_id: str) -> list[IGTObservation]:
        statement = (
            select(tables.IGTObservation)
            .where(tables.IGTObservation.run_id == run_id)
            .order_by(tables.IGTObservation.record_ordinal, tables.IGTObservation.id)
        )
        with self._reader() as session:
            return [_from_igt_observation(row) for row in session.scalars(statement).all()]

    def list_igt_observations_for_object(self, source_object_id: str) -> list[IGTObservation]:
        statement = (
            select(tables.IGTObservation)
            .where(tables.IGTObservation.source_object_id == source_object_id)
            .order_by(tables.IGTObservation.record_ordinal, tables.IGTObservation.id)
        )
        with self._reader() as session:
            return [_from_igt_observation(row) for row in session.scalars(statement).all()]

    def add_feature(self, feature: Feature) -> Feature:
        session = self._writer()
        existing = session.scalars(
            select(tables.Feature).where(
                tables.Feature.namespace == feature.namespace,
                tables.Feature.label == feature.label,
            )
        ).first()
        if existing is not None:
            return _from_feature(existing)
        _require_run(session, feature.run_id)
        _register(session, feature.id, EntityType.FEATURE, feature.created_at)
        row = _to_feature(feature)
        _insert(session, row, {"uq_feature_namespace_label": ImmutableViolation})
        return _from_feature(row)

    def get_feature(self, feature_id: str) -> Feature:
        with self._reader() as session:
            row = _require(session, tables.Feature, EntityType.FEATURE.value, feature_id)
            return _from_feature(row)

    def get_feature_by_label(self, namespace: str, label: str) -> Feature | None:
        with self._reader() as session:
            row = session.scalars(
                select(tables.Feature).where(
                    tables.Feature.namespace == namespace,
                    tables.Feature.label == label,
                )
            ).first()
            return None if row is None else _from_feature(row)

    def list_features(self, namespace: str | None = None) -> list[Feature]:
        statement = select(tables.Feature)
        if namespace is not None:
            statement = statement.where(tables.Feature.namespace == namespace)
        statement = statement.order_by(
            tables.Feature.namespace, tables.Feature.label, tables.Feature.id
        )
        with self._reader() as session:
            return [_from_feature(row) for row in session.scalars(statement).all()]

    def add_morpheme(self, morpheme: Morpheme) -> None:
        session = self._writer()
        _require_run(session, morpheme.run_id)
        _register(session, morpheme.id, EntityType.MORPHEME, morpheme.created_at)
        _insert(
            session,
            _to_morpheme(morpheme),
            {"uq_morpheme_run_identity_key": ImmutableViolation},
        )

    def get_morpheme(self, morpheme_id: str) -> Morpheme:
        with self._reader() as session:
            row = _require(session, tables.Morpheme, EntityType.MORPHEME.value, morpheme_id)
            return _from_morpheme(row)

    def get_morpheme_for_update(self, morpheme_id: str) -> Morpheme:
        session = self._writer()
        row = _require_for_update(session, tables.Morpheme, EntityType.MORPHEME.value, morpheme_id)
        return _from_morpheme(row)

    def list_morphemes_for_run(self, run_id: str) -> list[Morpheme]:
        statement = (
            select(tables.Morpheme)
            .where(tables.Morpheme.run_id == run_id)
            .order_by(tables.Morpheme.created_at, tables.Morpheme.id)
        )
        with self._reader() as session:
            return [_from_morpheme(row) for row in session.scalars(statement).all()]

    def set_morpheme_status(
        self,
        morpheme_id: str,
        status: LifecycleStatus,
        score_breakdown: ScoreBreakdown | None = None,
    ) -> Morpheme:
        session = self._writer()
        row = _require_for_update(session, tables.Morpheme, EntityType.MORPHEME.value, morpheme_id)
        updated = _revalidate(_from_morpheme(row), status=status, score_breakdown=score_breakdown)
        row.status = updated.status.value
        row.score_breakdown = (
            None if updated.score_breakdown is None else updated.score_breakdown.model_dump()
        )
        with _constraints({}):
            session.flush()
        return updated

    def add_allomorph(self, allomorph: Allomorph) -> None:
        session = self._writer()
        if session.get(tables.Morpheme, allomorph.morpheme_id) is None:
            raise InvalidLineage()
        _require_run(session, allomorph.run_id)
        _register(session, allomorph.id, EntityType.ALLOMORPH, allomorph.created_at)
        _insert(
            session,
            _to_allomorph(allomorph),
            {"uq_allomorph_morpheme_form": ImmutableViolation},
        )

    def list_allomorphs_for_morpheme(self, morpheme_id: str) -> list[Allomorph]:
        statement = (
            select(tables.Allomorph)
            .where(tables.Allomorph.morpheme_id == morpheme_id)
            .order_by(tables.Allomorph.created_at, tables.Allomorph.id)
        )
        with self._reader() as session:
            return [_from_allomorph(row) for row in session.scalars(statement).all()]

    def set_allomorph_status(self, allomorph_id: str, status: LifecycleStatus) -> Allomorph:
        session = self._writer()
        row = _require_for_update(
            session, tables.Allomorph, EntityType.ALLOMORPH.value, allomorph_id
        )
        updated = _revalidate(_from_allomorph(row), status=status)
        row.status = updated.status.value
        with _constraints({}):
            session.flush()
        return updated

    def add_morph_analysis(
        self,
        analysis: MorphAnalysis,
        segments: Sequence[MorphSegment],
        segment_features: Sequence[MorphSegmentFeature] = (),
        boundary_marks: tuple[str, ...] = ("-", "="),
    ) -> None:
        session = self._writer()
        token = session.get(tables.TokenOccurrence, analysis.target_token_id)
        if token is None:
            raise InvalidLineage()
        if token_surface_for(_from_token(token), analysis.span_representation) != analysis.surface:
            raise SchemaViolation()
        _require_run(session, analysis.run_id)
        for segment in segments:
            if segment.morpheme_id is not None and (
                session.get(tables.Morpheme, segment.morpheme_id) is None
            ):
                raise InvalidLineage()
            if segment.allomorph_id is not None:
                # An allomorph of a different morpheme would leave the graph self-
                # contradictory: the allomorph listing and the analyses listing for the
                # segment's morpheme would disagree about the same analysis.
                allomorph = session.get(tables.Allomorph, segment.allomorph_id)
                if allomorph is None or allomorph.morpheme_id != segment.morpheme_id:
                    raise InvalidLineage()
        seen_assignments: set[tuple[str, str]] = set()
        for assignment in segment_features:
            if session.get(tables.Feature, assignment.feature_id) is None:
                raise InvalidLineage()
            if assignment.segment_id not in {segment.id for segment in segments}:
                raise InvalidLineage()
            # A repeated (segment, feature) pair would collide on the composite primary
            # key at flush; refuse it here so both backends fail identically.
            if (assignment.segment_id, assignment.feature_id) in seen_assignments:
                raise ImmutableViolation()
            seen_assignments.add((assignment.segment_id, assignment.feature_id))
        try:
            check_analysis(analysis, list(segments), boundary_marks)
        except ValueError:
            # The ValueError carries ordinals and lengths only; callers branch on the
            # schema violation, so the cause is dropped like every other input echo.
            raise SchemaViolation() from None
        # Registry rows are flushed before any content row is added: `_register` flushes
        # the whole session, and a pending analysis row would otherwise surface its unique
        # violation inside an unmapped registry flush.
        _register(session, analysis.id, EntityType.MORPH_ANALYSIS, analysis.created_at)
        for segment in segments:
            _register(session, segment.id, EntityType.MORPH_SEGMENT, segment.created_at)
        session.add(_to_morph_analysis(analysis))
        for segment in segments:
            session.add(_to_morph_segment(segment))
        for assignment in segment_features:
            session.add(_to_morph_segment_feature(assignment))
        # One flush writes analysis, segments and assignments together: the unique natural
        # key and the per-analysis ordinal pair refuse the whole write (a `*_pkey` collision
        # on a duplicated identifier already translates to ImmutableViolation).
        with _constraints(
            {
                "uq_morph_analysis_signature": ImmutableViolation,
                "uq_morph_segment_analysis_ordinal": ImmutableViolation,
            }
        ):
            session.flush()

    def get_morph_analysis(self, analysis_id: str) -> MorphAnalysis:
        with self._reader() as session:
            row = _require(
                session, tables.MorphAnalysis, EntityType.MORPH_ANALYSIS.value, analysis_id
            )
            return _from_morph_analysis(row)

    def get_morph_analysis_for_update(self, analysis_id: str) -> MorphAnalysis:
        session = self._writer()
        row = _require_for_update(
            session, tables.MorphAnalysis, EntityType.MORPH_ANALYSIS.value, analysis_id
        )
        return _from_morph_analysis(row)

    def list_morph_analyses_for_token(self, token_id: str) -> list[MorphAnalysis]:
        statement = (
            select(tables.MorphAnalysis)
            .where(tables.MorphAnalysis.target_token_id == token_id)
            .order_by(tables.MorphAnalysis.created_at, tables.MorphAnalysis.id)
        )
        with self._reader() as session:
            return [_from_morph_analysis(row) for row in session.scalars(statement).all()]

    def list_morph_analyses_for_run(self, run_id: str) -> list[MorphAnalysis]:
        statement = (
            select(tables.MorphAnalysis)
            .where(tables.MorphAnalysis.run_id == run_id)
            .order_by(tables.MorphAnalysis.created_at, tables.MorphAnalysis.id)
        )
        with self._reader() as session:
            return [_from_morph_analysis(row) for row in session.scalars(statement).all()]

    def list_analyses_linking_morpheme(self, morpheme_id: str) -> list[MorphAnalysis]:
        # Resolved through the segments: one linked segment is enough, and `distinct`
        # keeps a multi-segment analysis from appearing twice (ADR-0017: no winner column).
        statement = (
            select(tables.MorphAnalysis)
            .join(
                tables.MorphSegment,
                tables.MorphSegment.analysis_id == tables.MorphAnalysis.id,
            )
            .where(tables.MorphSegment.morpheme_id == morpheme_id)
            .distinct()
            .order_by(tables.MorphAnalysis.created_at, tables.MorphAnalysis.id)
        )
        with self._reader() as session:
            return [_from_morph_analysis(row) for row in session.scalars(statement).all()]

    def list_morph_segments(self, analysis_id: str) -> list[MorphSegment]:
        statement = (
            select(tables.MorphSegment)
            .where(tables.MorphSegment.analysis_id == analysis_id)
            .order_by(tables.MorphSegment.ordinal)
        )
        with self._reader() as session:
            return [_from_morph_segment(row) for row in session.scalars(statement).all()]

    def get_morph_segment(self, segment_id: str) -> MorphSegment:
        with self._reader() as session:
            row = _require(session, tables.MorphSegment, EntityType.MORPH_SEGMENT.value, segment_id)
            return _from_morph_segment(row)

    def list_segment_features(self, segment_id: str) -> list[MorphSegmentFeature]:
        statement = (
            select(tables.MorphSegmentFeature)
            .where(tables.MorphSegmentFeature.segment_id == segment_id)
            .order_by(tables.MorphSegmentFeature.feature_id)
        )
        with self._reader() as session:
            return [_from_morph_segment_feature(row) for row in session.scalars(statement).all()]

    def set_morph_analysis_status(
        self,
        analysis_id: str,
        status: LifecycleStatus,
        score_breakdown: ScoreBreakdown | None = None,
    ) -> MorphAnalysis:
        session = self._writer()
        row = _require_for_update(
            session, tables.MorphAnalysis, EntityType.MORPH_ANALYSIS.value, analysis_id
        )
        updated = _revalidate(
            _from_morph_analysis(row), status=status, score_breakdown=score_breakdown
        )
        row.status = updated.status.value
        row.score_breakdown = (
            None if updated.score_breakdown is None else updated.score_breakdown.model_dump()
        )
        with _constraints({}):
            session.flush()
        return updated

    # --- source use approvals (M5, ADR-0018) ----------------------------------------------

    def add_source_use_approval(self, approval: SourceUseApproval) -> None:
        session = self._writer()
        if session.get(tables.Source, approval.source_id) is None:
            raise InvalidLineage()
        _require_run(session, approval.run_id)
        _register(session, approval.id, EntityType.SOURCE_USE_APPROVAL, approval.created_at)
        _insert(session, _to_source_use_approval(approval))

    def list_source_use_approvals(self, source_id: str) -> list[SourceUseApproval]:
        statement = (
            select(tables.SourceUseApproval)
            .where(tables.SourceUseApproval.source_id == source_id)
            .order_by(tables.SourceUseApproval.created_at, tables.SourceUseApproval.id)
        )
        with self._reader() as session:
            return [_from_source_use_approval(row) for row in session.scalars(statement).all()]

    def lock_sources(self, source_ids: Sequence[str], *, timeout_seconds: float = 300.0) -> None:
        session = self._writer()
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        ids = sorted(set(source_ids))
        if not ids:
            return
        # Bounded acquisition: a transaction-local lock timeout (SET LOCAL scope, so it
        # cannot outlive this transaction even on the failure path) turns an indefinite
        # row-lock wait into SQLSTATE 55P03, translated to a fixed backend_timeout below.
        previous = session.execute(sql_text("SELECT current_setting('lock_timeout')")).scalar_one()
        bounded_ms = max(1, round(timeout_seconds * 1000))
        session.execute(
            sql_text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": f"{bounded_ms}ms"},
        )
        try:
            with _constraints({}):
                rows = session.scalars(
                    select(tables.Source)
                    .where(tables.Source.id.in_(ids))
                    .order_by(tables.Source.id)
                    .with_for_update()
                ).all()
        except DBAPIError as exc:
            if getattr(getattr(exc, "orig", None), "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                raise
            # The timed-out statement aborted the transaction: roll it back so no
            # partial outputs survive. The driver exception carries SQL text and
            # parameters, so it is neither chained nor logged.
            session.rollback()
            raise AlignmentFailed("backend_timeout") from None
        # Later statements in the still-live transaction keep the caller's own setting.
        session.execute(
            sql_text("SELECT set_config('lock_timeout', :value, true)"), {"value": previous}
        )
        found = {row.id for row in rows}
        for source_id in ids:
            if source_id not in found:
                raise NotFound(EntityType.SOURCE.value, source_id)

    @contextmanager
    def alignment_lock(self, request_key: str, *, timeout_seconds: float = 300.0) -> Iterator[None]:
        if self._session is not None:
            raise RuntimeError("alignment_lock must not be nested in repository.transaction")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        key = _advisory_key(request_key)
        # A dedicated session carries the advisory lock so it survives the semantic
        # transactions begun and committed inside the lock scope; released in finally,
        # never by an intermediate COMMIT (M3-PLAN §5.3).
        connection = self._engine.connect()
        try:
            deadline = time.monotonic() + timeout_seconds
            delay = _ADVISORY_POLL_SECONDS
            while True:
                acquired = connection.execute(
                    sql_text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                ).scalar_one()
                if acquired:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AlignmentFailed("backend_timeout")
                time.sleep(min(delay, remaining))
                delay = min(delay * 2, _ADVISORY_MAX_POLL_SECONDS)
            try:
                yield
            finally:
                connection.execute(
                    sql_text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                ).scalar_one()
        finally:
            connection.close()

    # --- audit and counts -----------------------------------------------------------------

    def add_audit_event(self, e: AuditEvent) -> None:
        _insert(self._writer(), _to_audit(e))

    def list_audit_events(self) -> list[AuditEvent]:
        statement = select(tables.AuditEvent).order_by(
            tables.AuditEvent.occurred_at, tables.AuditEvent.id
        )
        with self._reader() as session:
            return [_from_audit(row) for row in session.scalars(statement).all()]

    def _count(self, statement: Any) -> int:
        with self._reader() as session:
            return int(session.scalar(statement) or 0)

    def count(self, entity_type: EntityType) -> int:
        return self._count(
            select(func.count())
            .select_from(tables.ObjectRegistry)
            .where(tables.ObjectRegistry.entity_type == entity_type.value)
        )

    def count_lineage_edges(self) -> int:
        return self._count(select(func.count()).select_from(tables.LineageEdge))

    def count_raw_blobs(self) -> int:
        return self._count(select(func.count()).select_from(tables.RawBlob))

    def count_runs(self, status: RunStatus | None = None) -> int:
        statement = select(func.count()).select_from(tables.ProcessingRun)
        if status is not None:
            statement = statement.where(tables.ProcessingRun.status == status.value)
        return self._count(statement)
