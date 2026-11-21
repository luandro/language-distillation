import math
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Literal, NamedTuple, Protocol

from langpipe.domain.enums import (
    EntityType,
    LifecycleStatus,
    LineageKind,
    ReviewTaskType,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    SpanRepresentation,
)
from langpipe.domain.errors import SchemaViolation
from langpipe.domain.models.alignment import SegmentAlignment, TokenAlignmentEdge
from langpipe.domain.models.approval import SourceUseApproval
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.igt import IGTObservation
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
from langpipe.domain.models.observation import Form, Segment, TokenOccurrence
from langpipe.domain.models.review import REVIEW_TASK_STATUSES, ReviewDecision, ReviewTask
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.domain.models.source import RawBlob, Source, SourceObject, SourcePolicy


class AlignmentSideDescriptor(NamedTuple):
    """One ordered side of an alignment run config (M3-PLAN §5.4, ADR-0011 §4)."""

    role: str
    source_id: str
    language: str
    normalization_run_id: str
    tokenization_run_id: str | None


def _required_text(side: Mapping[str, Any], key: str) -> str:
    value = side.get(key)
    if not isinstance(value, str):
        raise SchemaViolation()
    return value


def _optional_text(side: Mapping[str, Any], key: str) -> str | None:
    """Absent or explicitly null stays an omitted pin; any present value must be a string.

    Silently coercing a present malformed value (int, bool, array, object) to an omitted
    pin made the backends disagree with the deferred database guard, so it is a
    SchemaViolation instead.
    """
    value = side.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaViolation()
    return value


def alignment_side_descriptors(
    config: Mapping[str, Any] | None, *, require_tokenization: bool
) -> tuple[AlignmentSideDescriptor, AlignmentSideDescriptor]:
    """Parse and shape-check the ordered source/target side descriptors of a run config.

    The pure mirror of the deferred `langpipe_alignment_selected_sides` contract: both
    repository backends call this eagerly so repository-mediated writes never depend on
    the database guards. Reference checks (registered source, succeeded pinned runs) stay
    with the backends, which own the lookups. Raises SchemaViolation on any malformed
    shape; the malformed config itself is never echoed.
    """
    sides = None if config is None else config.get("sides")
    if not isinstance(sides, Sequence) or isinstance(sides, (str, bytes)) or len(sides) != 2:
        raise SchemaViolation()
    parsed: list[AlignmentSideDescriptor] = []
    for expected_role, side in zip(("source", "target"), sides, strict=True):
        if not isinstance(side, Mapping):
            raise SchemaViolation()
        role = _required_text(side, "role")
        source_id = _required_text(side, "source_id")
        language = _required_text(side, "language")
        normalization_run_id = _required_text(side, "normalization_run_id")
        tokenization_run_id = _optional_text(side, "tokenization_run_id")
        if role != expected_role:
            raise SchemaViolation()
        if not source_id or not language or not language.strip():
            raise SchemaViolation()
        if normalization_run_id is None:
            raise SchemaViolation()
        if (require_tokenization or tokenization_run_id is not None) and not tokenization_run_id:
            raise SchemaViolation()
        parsed.append(
            AlignmentSideDescriptor(
                role=role,
                source_id=source_id,
                language=language,
                normalization_run_id=normalization_run_id,
                tokenization_run_id=tokenization_run_id,
            )
        )
    if parsed[0].language == parsed[1].language:
        raise SchemaViolation()
    return parsed[0], parsed[1]


def queue_status_filter(status: str | None) -> str | None:
    """Validate a queue status filter: `None` selects every operational state.

    A lifecycle status is not an operational queue state, and anything unknown is a
    malformed filter: both are refused instead of silently matching nothing.
    """
    if status is None:
        return None
    if status not in REVIEW_TASK_STATUSES:
        raise SchemaViolation()
    return status


def checked_min_priority(min_priority: float | None) -> float | None:
    """Validate a queue priority threshold. A boolean or non-finite value is refused."""
    if min_priority is None:
        return None
    if isinstance(min_priority, bool) or not math.isfinite(min_priority):
        raise ValueError("min_priority must be a finite number")
    return min_priority


def token_surface_for(token: TokenOccurrence, representation: SpanRepresentation) -> str:
    """The token surface a `MorphAnalysis`'s spans refer to, per ADR-0017 §3.

    The representation is derived from the token, not chosen by the caller: spans
    index the `normalized_surface` when the token carries one, else the `raw_surface`.
    `MorphAnalysis.surface` must equal that surface and `span_representation` must
    name it — a RAW analysis over a normalized token, or a NORMALIZED analysis over
    a token that never carried a normalized surface, has nothing to match and is a
    SchemaViolation. The check lives with both repository backends.
    """
    if token.normalized_surface is not None:
        expected = SpanRepresentation.NORMALIZED
        surface = token.normalized_surface
    else:
        expected = SpanRepresentation.RAW
        surface = token.raw_surface
    if representation is not expected:
        raise SchemaViolation()
    return surface


class Repository(Protocol):
    """Persistence port. Observation rows are insert-only: no update or delete methods exist."""

    # nesting not supported: RuntimeError
    def transaction(self) -> AbstractContextManager[None]: ...

    # every add_*/set_*/finish_* MUST be called inside transaction();
    # else RuntimeError("write outside transaction")

    def add_policy(self, p: SourcePolicy) -> None: ...
    def get_policy(self, policy_id: str) -> SourcePolicy: ...  # NotFound
    def add_source(self, s: Source) -> None: ...  # registers EntityType.source
    def get_source(self, source_id: str) -> Source: ...
    def find_source_by_key(self, key: str) -> Source | None: ...
    def set_source_status(self, source_id: str, status: SourceStatus, at: datetime) -> Source: ...
    def add_source_object(self, o: SourceObject) -> None: ...  # unique (source_id, original_path)
    def get_source_object(self, object_id: str) -> SourceObject: ...
    def list_source_objects(self, source_id: str) -> list[SourceObject]: ...  # by original_path
    def add_raw_blob(self, b: RawBlob) -> RawBlob: ...  # idempotent: returns existing row
    def get_raw_blob(self, sha256: str) -> RawBlob | None: ...
    def add_run(self, r: ProcessingRun) -> None: ...
    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        finished_at: datetime,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> ProcessingRun: ...
    # ImmutableViolation if run not running or status == running
    def get_run(self, run_id: str) -> ProcessingRun: ...
    def find_succeeded_run(self, run_key: str) -> ProcessingRun | None: ...
    def list_runs_with_input(
        self, object_id: str, stage: RunStage, status: RunStatus | None = None
    ) -> list[ProcessingRun]: ...  # role=input; by (started_at, id)
    def add_run_io(self, run_id: str, object_id: str, role: RunIoRole) -> None: ...
    # object must exist in registry else InvalidLineage; duplicate ignored
    def list_run_io(self, run_id: str) -> list[tuple[str, RunIoRole]]: ...  # sorted
    def add_artifact(self, a: Artifact) -> None: ...
    def get_artifact(self, artifact_id: str) -> Artifact: ...
    def add_segment(self, s: Segment) -> None: ...  # unique (run_id, source_object_id, ordinal)
    def get_segment(self, segment_id: str) -> Segment: ...
    def list_segments(self, source_object_id: str) -> list[Segment]: ...
    def list_segments_for_run(self, run_id: str) -> list[Segment]: ...  # by (object, ordinal)
    def add_token(self, t: TokenOccurrence) -> None: ...  # unique (run_id, segment_id, ordinal)
    def get_token(self, token_id: str) -> TokenOccurrence: ...
    def list_tokens(self, segment_id: str) -> list[TokenOccurrence]: ...
    def get_or_create_form(self, f: Form) -> Form: ...  # natural key (language, profile, text)
    def get_form(self, form_id: str) -> Form: ...  # NotFound (WP4.10 §3.4)
    def add_evidence(self, e: EvidenceItem) -> None: ...  # target_id must exist else InvalidLineage
    def get_evidence(self, evidence_id: str) -> EvidenceItem: ...
    def list_evidence_for_target(self, target_id: str) -> list[EvidenceItem]: ...
    def add_lineage_edge(self, e: LineageEdge) -> LineageEdge: ...
    # endpoints must exist; idempotent on (from, to, kind) → returns existing;
    # cycle → InvalidLineage
    def list_lineage_edges(
        self, object_id: str, direction: Literal["out", "in"]
    ) -> list[LineageEdge]: ...
    def list_lineage_edges_by_kind(self, kind: LineageKind) -> list[LineageEdge]: ...
    def ancestors(self, object_id: str) -> list[tuple[str, int]]: ...  # (id, min depth ≥1)
    def descendants(self, object_id: str) -> list[tuple[str, int]]: ...  # reverse edges
    def entity_type_of(self, object_id: str) -> EntityType | None: ...
    # --- alignments (M3, ADR-0011) -------------------------------------------------------
    # add_segment_alignment inserts the ordered relational members internally; members
    # are not independently valid entities and no status setter exists. Both backends
    # validate the §5.4 selection contract eagerly, mirroring the deferred DB guards.
    def add_segment_alignment(self, alignment: SegmentAlignment) -> None: ...
    def get_segment_alignment(self, alignment_id: str) -> SegmentAlignment: ...  # NotFound
    def list_segment_alignments_for_run(self, run_id: str) -> list[SegmentAlignment]: ...
    # ordered by (group_key, id)
    def add_token_alignment_edge(self, edge: TokenAlignmentEdge) -> None: ...
    def get_token_alignment_edge(self, edge_id: str) -> TokenAlignmentEdge: ...  # NotFound
    def list_token_alignment_edges_for_run(self, run_id: str) -> list[TokenAlignmentEdge]: ...
    # ordered by (source_token_id, target_token_id, direction, symmetrization, id)
    # --- lexical evidence and the review queue (M4, ADR-0013) --------------------------------
    # Hypotheses never truth: these methods only persist candidates and record what a
    # reviewer decided. Nothing here promotes an object to `validated` on its own.
    def add_concept(self, c: Concept) -> None: ...  # registers EntityType.CONCEPT
    def get_concept(self, concept_id: str) -> Concept: ...  # NotFound
    def list_concepts(self) -> list[Concept]: ...  # ordered by (created_at, id)
    def add_lexeme(self, lexeme: Lexeme) -> None: ...  # registers EntityType.LEXEME
    def get_lexeme(self, lexeme_id: str) -> Lexeme: ...  # NotFound
    def list_lexemes_by_language(self, language: str) -> list[Lexeme]: ...  # (created_at, id)
    # Resolved through the explicit form_lexeme relation, so ambiguity is preserved and
    # non-lemma links count; a missing or unlinked form returns [].
    def list_lexemes_by_form(self, form_id: str) -> list[Lexeme]: ...  # (created_at, id)
    def set_lexeme_status(
        self,
        lexeme_id: str,
        status: LifecycleStatus,
        score_breakdown: LexicalScoreBreakdown | None = None,
    ) -> Lexeme: ...  # NotFound; atomic
    def add_form_lexeme_link(self, link: FormLexemeLink) -> None: ...  # EntityType.FORM_LEXEME
    # unique (form_id, lexeme_id) → ImmutableViolation; append-only
    def list_form_lexeme_links_for_form(self, form_id: str) -> list[FormLexemeLink]: ...
    # ordered by (created_at, id)
    def list_form_lexeme_links_for_lexeme(self, lexeme_id: str) -> list[FormLexemeLink]: ...
    # ordered by (created_at, id)
    def add_sense(self, s: Sense) -> None: ...  # registers EntityType.SENSE
    def get_sense(self, sense_id: str) -> Sense: ...  # NotFound
    def list_senses_for_lexeme(self, lexeme_id: str) -> list[Sense]: ...  # (created_at, id)
    def set_sense_status(
        self,
        sense_id: str,
        status: LifecycleStatus,
        score_breakdown: LexicalScoreBreakdown | None = None,
    ) -> Sense: ...  # NotFound; atomic
    def add_review_task(self, task: ReviewTask) -> None: ...  # registers EntityType.REVIEW_TASK
    def get_review_task(self, task_id: str) -> ReviewTask: ...  # NotFound
    def get_review_task_for_update(self, task_id: str) -> ReviewTask: ...
    # requires transaction(); PostgreSQL SELECT FOR UPDATE with a post-lock reread,
    # memory validates existence inside the transaction; held until the caller's
    # transaction ends; NotFound
    def list_review_tasks(
        self,
        *,
        task_type: ReviewTaskType | None = None,
        required_role: str | None = None,
        status: str | None = "open",
        min_priority: float | None = None,
    ) -> list[ReviewTask]: ...
    # status None = every operational queue state; a LifecycleStatus or unknown status
    # is a SchemaViolation; ordered by (-priority, created_at, id)
    def set_review_task_status(self, task_id: str, status: str) -> ReviewTask: ...  # NotFound
    # operational queue state only; a LifecycleStatus value is a SchemaViolation
    def add_review_decision(self, decision: ReviewDecision) -> None: ...
    # registers EntityType.REVIEW_DECISION; append-only, no update or delete path
    def get_review_decision(self, decision_id: str) -> ReviewDecision: ...  # NotFound
    def list_review_decisions_for_target(self, target_id: str) -> list[ReviewDecision]: ...
    # ordered by (created_at, id)
    # --- IGT observations (M5, ADR-0017 §1-3) --------------------------------------------
    # Observation ≠ inference: an observation row is immutable source evidence, append-only.
    def add_igt_observation(self, observation: IGTObservation) -> None: ...
    # registers EntityType.IGT_OBSERVATION; unique (run_id, source_object_id, record_ordinal)
    # → ImmutableViolation; append-only
    def get_igt_observation(self, observation_id: str) -> IGTObservation: ...  # NotFound
    def list_igt_observations_for_run(self, run_id: str) -> list[IGTObservation]: ...
    # ordered by (record_ordinal, id)
    def list_igt_observations_for_object(self, source_object_id: str) -> list[IGTObservation]: ...
    # ordered by (record_ordinal, id)
    # --- Feature definitions (M5, ADR-0017 §4) -------------------------------------------
    def add_feature(self, feature: Feature) -> Feature: ...
    # registers EntityType.FEATURE; idempotent on (namespace, label): a natural-key hit
    # returns the stored row (with its own valid run_id) without error; the caller's
    # run_id is not checked on an idempotent hit
    def get_feature(self, feature_id: str) -> Feature: ...  # NotFound
    def get_feature_by_label(self, namespace: str, label: str) -> Feature | None: ...
    def list_features(self, namespace: str | None = None) -> list[Feature]: ...
    # ordered by (namespace, label, id)
    # --- Morphemes & Allomorphs (M5, ADR-0017 §5) ----------------------------------------
    def add_morpheme(self, morpheme: Morpheme) -> None: ...
    # registers EntityType.MORPHEME; unique (run_id, identity_key) → ImmutableViolation
    def get_morpheme(self, morpheme_id: str) -> Morpheme: ...  # NotFound
    def get_morpheme_for_update(self, morpheme_id: str) -> Morpheme: ...
    # requires transaction(); SELECT FOR UPDATE on PostgreSQL; memory validates existence;
    # held until the caller's transaction ends; NotFound
    def list_morphemes_for_run(self, run_id: str) -> list[Morpheme]: ...
    # ordered by (created_at, id)
    def set_morpheme_status(
        self,
        morpheme_id: str,
        status: LifecycleStatus,
        score_breakdown: ScoreBreakdown | None = None,
    ) -> Morpheme: ...  # NotFound; atomic; hypothesis guard
    def add_allomorph(self, allomorph: Allomorph) -> None: ...
    # registers EntityType.ALLOMORPH; unique (morpheme_id, form) → ImmutableViolation
    def list_allomorphs_for_morpheme(self, morpheme_id: str) -> list[Allomorph]: ...
    # ordered by (created_at, id)
    def set_allomorph_status(self, allomorph_id: str, status: LifecycleStatus) -> Allomorph: ...
    # NotFound; atomic; hypothesis guard
    # --- Morph Analyses, Segments & Features (M5, ADR-0017 §6) ---------------------------
    # Lock order is task → target → dependents (matching WP4.3): lock the target token's
    # analysis rows before the morpheme/allomorph rows they link to. `add_morph_analysis`
    # validates the segmentation against the target token's surface (via `check_analysis`)
    # and inserts analysis, segments and segment features atomically.
    def add_morph_analysis(
        self,
        analysis: MorphAnalysis,
        segments: Sequence[MorphSegment],
        segment_features: Sequence[MorphSegmentFeature] = (),
        boundary_marks: tuple[str, ...] = ("-", "="),
    ) -> None: ...
    # registers EntityType.MORPH_ANALYSIS and EntityType.MORPH_SEGMENT; validates the target
    # token exists and `token_surface_for(token, analysis.span_representation) == analysis.surface`;
    # a segment's allomorph must belong to the segment's morpheme → InvalidLineage;
    # validates check_analysis(analysis, list(segments), boundary_marks) before write;
    # unique (target_token_id, run_id, signature) → ImmutableViolation
    def get_morph_analysis(self, analysis_id: str) -> MorphAnalysis: ...  # NotFound
    def get_morph_analysis_for_update(self, analysis_id: str) -> MorphAnalysis: ...
    # requires transaction(); SELECT FOR UPDATE on PostgreSQL; memory validates existence;
    # held until the caller's transaction ends; NotFound
    def list_morph_analyses_for_token(self, token_id: str) -> list[MorphAnalysis]: ...
    # ordered by (created_at, id)
    def list_morph_analyses_for_run(self, run_id: str) -> list[MorphAnalysis]: ...
    # ordered by (created_at, id)
    def list_analyses_linking_morpheme(self, morpheme_id: str) -> list[MorphAnalysis]: ...
    # ordered by (created_at, id); resolved through morph_segment, so ambiguity is preserved
    def list_morph_segments(self, analysis_id: str) -> list[MorphSegment]: ...
    # ordered by ordinal
    def get_morph_segment(self, segment_id: str) -> MorphSegment: ...  # NotFound
    def list_segment_features(self, segment_id: str) -> list[MorphSegmentFeature]: ...
    # ordered by feature_id
    def set_morph_analysis_status(
        self,
        analysis_id: str,
        status: LifecycleStatus,
        score_breakdown: ScoreBreakdown | None = None,
    ) -> MorphAnalysis: ...  # NotFound; atomic; hypothesis guard
    # --- Source Use Approvals (M5, ADR-0018) ----------------------------------------------
    def add_source_use_approval(self, approval: SourceUseApproval) -> None: ...
    # registers EntityType.SOURCE_USE_APPROVAL; append-only, no update or delete path
    def list_source_use_approvals(self, source_id: str) -> list[SourceUseApproval]: ...
    # ordered by (created_at, id)
    def lock_sources(
        self, source_ids: Sequence[str], *, timeout_seconds: float = 300.0
    ) -> None: ...
    # requires transaction(); PostgreSQL SELECT FOR UPDATE in sorted order under a
    # transaction-local lock timeout (bounded acquisition raises backend_timeout),
    # memory validates existence; locks held until the caller's transaction ends
    def alignment_lock(
        self, request_key: str, *, timeout_seconds: float = 300.0
    ) -> AbstractContextManager[None]: ...
    # serializes one request over preflight/reuse/start/compute/commit on a dedicated
    # session advisory lock (PostgreSQL) or per-key lock (memory); must not be entered
    # inside repository.transaction(); bounded acquisition raises backend_timeout
    def add_audit_event(self, e: AuditEvent) -> None: ...
    def list_audit_events(self) -> list[AuditEvent]: ...  # ordered by occurred_at, id
    def count(self, entity_type: EntityType) -> int: ...
    def count_lineage_edges(self) -> int: ...
    def count_raw_blobs(self) -> int: ...
    def count_runs(self, status: RunStatus | None = None) -> int: ...
