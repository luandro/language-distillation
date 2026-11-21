import copy
import threading
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import ValidationError

from langpipe.domain.enums import (
    EntityType,
    LifecycleStatus,
    LineageKind,
    ReviewTaskType,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import (
    AlignmentFailed,
    ImmutableViolation,
    InvalidLineage,
    NotFound,
    SchemaViolation,
    SourceConflict,
)
from langpipe.domain.models.alignment import SegmentAlignment, TokenAlignmentEdge
from langpipe.domain.models.approval import SourceUseApproval
from langpipe.domain.models.base import DomainModel
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
from langpipe.morphology.spans import check_analysis
from langpipe.storage.repository import (
    AlignmentSideDescriptor,
    alignment_side_descriptors,
    checked_min_priority,
    queue_status_filter,
    token_surface_for,
)


def _revalidate[M: DomainModel](model: M, **changes: Any) -> M:
    """Build a changed copy through validation; `model_copy` would bypass it."""
    data = model.model_dump()
    data.update(changes)
    try:
        return type(model).model_validate(data)
    except ValidationError as exc:
        raise SchemaViolation() from exc


@dataclass
class _State:
    registry: dict[str, EntityType] = field(default_factory=dict)
    policies: dict[str, SourcePolicy] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    source_objects: dict[str, SourceObject] = field(default_factory=dict)
    raw_blobs: dict[str, RawBlob] = field(default_factory=dict)
    runs: dict[str, ProcessingRun] = field(default_factory=dict)
    run_io: set[tuple[str, str, RunIoRole]] = field(default_factory=set)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    segments: dict[str, Segment] = field(default_factory=dict)
    tokens: dict[str, TokenOccurrence] = field(default_factory=dict)
    forms: dict[str, Form] = field(default_factory=dict)
    evidence: dict[str, EvidenceItem] = field(default_factory=dict)
    lineage: dict[str, LineageEdge] = field(default_factory=dict)
    audit_events: dict[str, AuditEvent] = field(default_factory=dict)
    # Fast internal indexes for O(1) lookups and O(deg) graph traversals (WP2.17)
    forms_by_key: dict[tuple[str, str, str], Form] = field(default_factory=dict)
    segments_by_ordinal: dict[tuple[str, str, int], str] = field(default_factory=dict)
    tokens_by_ordinal: dict[tuple[str, str, int], str] = field(default_factory=dict)
    lineage_by_triple: dict[tuple[str, str, LineageKind], LineageEdge] = field(default_factory=dict)
    lineage_out: dict[str, list[str]] = field(default_factory=dict)
    lineage_in: dict[str, list[str]] = field(default_factory=dict)
    lineage_edges_out: dict[str, list[LineageEdge]] = field(default_factory=dict)
    lineage_edges_in: dict[str, list[LineageEdge]] = field(default_factory=dict)
    tokens_by_segment: dict[str, list[TokenOccurrence]] = field(default_factory=dict)
    # M3 alignment evidence (WP3.3): per-run lists for O(1) reads plus the natural-key
    # uniqueness mirrors of the database constraints; membership itself lives in the
    # model's ordered side tuples, so endpoint checks never scan whole state.
    segment_alignments: dict[str, SegmentAlignment] = field(default_factory=dict)
    segment_alignment_ids_by_run: dict[str, list[str]] = field(default_factory=dict)
    segment_alignment_natural: dict[tuple[str, str], str] = field(default_factory=dict)
    token_edges: dict[str, TokenAlignmentEdge] = field(default_factory=dict)
    token_edge_ids_by_run: dict[str, list[str]] = field(default_factory=dict)
    token_edge_natural: dict[tuple[str, str, str, str, str, str], str] = field(default_factory=dict)
    # M4 lexical evidence and review queue (ADR-0013): orders are (created_at, id), the
    # review queue keeps open tasks only, and form_lexeme / review_decision are append-only.
    concepts: dict[str, Concept] = field(default_factory=dict)
    lexemes: dict[str, Lexeme] = field(default_factory=dict)
    lexeme_ids_by_language: dict[str, list[str]] = field(default_factory=dict)
    form_lexeme_links: dict[str, FormLexemeLink] = field(default_factory=dict)
    form_lexeme_ids_by_form: dict[str, list[str]] = field(default_factory=dict)
    form_lexeme_ids_by_lexeme: dict[str, list[str]] = field(default_factory=dict)
    form_lexeme_natural: dict[tuple[str, str], str] = field(default_factory=dict)
    senses: dict[str, Sense] = field(default_factory=dict)
    sense_ids_by_lexeme: dict[str, list[str]] = field(default_factory=dict)
    review_tasks: dict[str, ReviewTask] = field(default_factory=dict)
    review_decisions: dict[str, ReviewDecision] = field(default_factory=dict)
    review_decision_ids_by_target: dict[str, list[str]] = field(default_factory=dict)
    # M5 IGT observations and morphology graph (ADR-0017): the `*_natural` / `*_records`
    # members mirror the database unique constraints; morph_segment_feature is the
    # append-only join keyed (segment_id, feature_id) and never enters the registry.
    igt_observations: dict[str, IGTObservation] = field(default_factory=dict)
    igt_observation_records: set[tuple[str, str, int]] = field(default_factory=set)
    features: dict[str, Feature] = field(default_factory=dict)
    feature_natural: dict[tuple[str, str], str] = field(default_factory=dict)
    morphemes: dict[str, Morpheme] = field(default_factory=dict)
    morpheme_identity: set[tuple[str, str]] = field(default_factory=set)
    allomorphs: dict[str, Allomorph] = field(default_factory=dict)
    allomorph_natural: set[tuple[str, str]] = field(default_factory=set)
    morph_analyses: dict[str, MorphAnalysis] = field(default_factory=dict)
    morph_analysis_natural: set[tuple[str, str, str]] = field(default_factory=set)
    morph_segments: dict[str, MorphSegment] = field(default_factory=dict)
    morph_segment_ordinals: set[tuple[str, int]] = field(default_factory=set)
    morph_segment_features: list[MorphSegmentFeature] = field(default_factory=list)
    # M5 source-use approvals (ADR-0018): append-only governance records.
    source_use_approvals: dict[str, SourceUseApproval] = field(default_factory=dict)


class InMemoryRepository:
    """Repository backed by plain dicts. Every stored and returned model is a deep copy."""

    def __init__(self) -> None:
        self._state = _State()
        self._in_transaction = False
        # Request locks outlive transactions and rollbacks, so they live outside _State
        # (which is snapshotted per transaction and cannot be deep-copied with locks).
        self._request_locks: dict[str, threading.Lock] = {}

    # --- transactions -------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._in_transaction:
            raise RuntimeError("nested transactions are not supported")
        snapshot = copy.deepcopy(self._state)
        self._in_transaction = True
        try:
            yield
        except BaseException:
            self._state = snapshot
            raise
        finally:
            self._in_transaction = False

    def _writable(self) -> _State:
        if not self._in_transaction:
            raise RuntimeError("write outside transaction")
        return self._state

    # --- helpers --------------------------------------------------------------------------

    @staticmethod
    def _insert[M: DomainModel](
        table: dict[str, M],
        key: str,
        value: M,
        registry: dict[str, EntityType] | None = None,
        entity_type: EntityType | None = None,
    ) -> None:
        if key in table:
            raise ImmutableViolation()
        table[key] = copy.deepcopy(value)
        if registry is not None and entity_type is not None:
            registry[key] = entity_type

    @staticmethod
    def _fetch[M: DomainModel](table: dict[str, M], entity: str, key: str) -> M:
        if key not in table:
            raise NotFound(entity, key)
        return copy.deepcopy(table[key])

    def _require_registered(self, object_id: str) -> None:
        if object_id not in self._state.registry:
            raise InvalidLineage()

    def _out_neighbours(self, object_id: str) -> list[str]:
        return self._state.lineage_out.get(object_id, [])

    def _in_neighbours(self, object_id: str) -> list[str]:
        return self._state.lineage_in.get(object_id, [])

    @staticmethod
    def _walk(start: str, neighbours: Callable[[str], list[str]]) -> list[tuple[str, int]]:
        """Breadth-first walk; the first visit to a node is its minimum depth."""
        depth: dict[str, int] = {}
        seen = {start}
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        while queue:
            node, level = queue.popleft()
            for nxt in neighbours(node):
                if nxt not in seen:
                    seen.add(nxt)
                    depth[nxt] = level + 1
                    queue.append((nxt, level + 1))
        return sorted(depth.items(), key=lambda item: (item[1], item[0]))

    # --- policies and sources -------------------------------------------------------------

    def add_policy(self, p: SourcePolicy) -> None:
        self._insert(self._writable().policies, p.id, p)

    def get_policy(self, policy_id: str) -> SourcePolicy:
        return self._fetch(self._state.policies, "source_policy", policy_id)

    def add_source(self, s: Source) -> None:
        state = self._writable()
        if any(existing.key == s.key for existing in state.sources.values()):
            raise SourceConflict(s.key)
        self._insert(state.sources, s.id, s, state.registry, EntityType.SOURCE)

    def get_source(self, source_id: str) -> Source:
        return self._fetch(self._state.sources, EntityType.SOURCE.value, source_id)

    def find_source_by_key(self, key: str) -> Source | None:
        for source in self._state.sources.values():
            if source.key == key:
                return copy.deepcopy(source)
        return None

    def set_source_status(self, source_id: str, status: SourceStatus, at: datetime) -> Source:
        state = self._writable()
        current = self._fetch(state.sources, EntityType.SOURCE.value, source_id)
        updated = _revalidate(current, status=status, updated_at=at)
        state.sources[source_id] = copy.deepcopy(updated)
        return updated

    def add_source_object(self, o: SourceObject) -> None:
        state = self._writable()
        source = self._fetch(state.sources, EntityType.SOURCE.value, o.source_id)
        for existing in state.source_objects.values():
            if existing.source_id == o.source_id and existing.original_path == o.original_path:
                # Name the source by its key; the path is a file name and stays out of errors.
                raise SourceConflict(source.key)
        self._insert(state.source_objects, o.id, o, state.registry, EntityType.SOURCE_OBJECT)

    def get_source_object(self, object_id: str) -> SourceObject:
        return self._fetch(self._state.source_objects, EntityType.SOURCE_OBJECT.value, object_id)

    def list_source_objects(self, source_id: str) -> list[SourceObject]:
        found = [o for o in self._state.source_objects.values() if o.source_id == source_id]
        return [copy.deepcopy(o) for o in sorted(found, key=lambda o: o.original_path)]

    # --- raw blobs ------------------------------------------------------------------------

    def add_raw_blob(self, b: RawBlob) -> RawBlob:
        blobs = self._writable().raw_blobs
        if b.sha256 in blobs:
            return copy.deepcopy(blobs[b.sha256])
        blobs[b.sha256] = copy.deepcopy(b)
        return copy.deepcopy(b)

    def get_raw_blob(self, sha256: str) -> RawBlob | None:
        blob = self._state.raw_blobs.get(sha256)
        return None if blob is None else copy.deepcopy(blob)

    # --- runs -----------------------------------------------------------------------------

    def add_run(self, r: ProcessingRun) -> None:
        state = self._writable()
        self._insert(state.runs, r.id, r, state.registry, EntityType.PROCESSING_RUN)

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        finished_at: datetime,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> ProcessingRun:
        state = self._writable()
        current = self._fetch(state.runs, EntityType.PROCESSING_RUN.value, run_id)
        if current.status is not RunStatus.RUNNING or status is RunStatus.RUNNING:
            raise ImmutableViolation()
        updated = _revalidate(
            current,
            status=status,
            finished_at=finished_at,
            error_type=error_type,
            error_message=error_message,
        )
        state.runs[run_id] = copy.deepcopy(updated)
        return updated

    def get_run(self, run_id: str) -> ProcessingRun:
        return self._fetch(self._state.runs, EntityType.PROCESSING_RUN.value, run_id)

    def find_succeeded_run(self, run_key: str) -> ProcessingRun | None:
        matches = [
            r
            for r in self._state.runs.values()
            if r.run_key == run_key and r.status is RunStatus.SUCCEEDED
        ]
        if not matches:
            return None
        earliest = min(matches, key=lambda r: (r.started_at, r.id))
        return copy.deepcopy(earliest)

    def list_runs_with_input(
        self, object_id: str, stage: RunStage, status: RunStatus | None = None
    ) -> list[ProcessingRun]:
        input_run_ids = {
            rid
            for rid, obj, role in self._state.run_io
            if obj == object_id and role is RunIoRole.INPUT
        }
        matches = [
            r
            for r in self._state.runs.values()
            if r.id in input_run_ids and r.stage is stage and (status is None or r.status is status)
        ]
        ordered = sorted(matches, key=lambda r: (r.started_at, r.id))
        return [copy.deepcopy(r) for r in ordered]

    def add_run_io(self, run_id: str, object_id: str, role: RunIoRole) -> None:
        state = self._writable()
        self._require_registered(object_id)
        state.run_io.add((run_id, object_id, role))

    def list_run_io(self, run_id: str) -> list[tuple[str, RunIoRole]]:
        pairs = [(obj, role) for rid, obj, role in self._state.run_io if rid == run_id]
        return sorted(pairs, key=lambda pair: (pair[0], pair[1].value))

    def add_artifact(self, a: Artifact) -> None:
        state = self._writable()
        self._insert(state.artifacts, a.id, a, state.registry, EntityType.ARTIFACT)

    def get_artifact(self, artifact_id: str) -> Artifact:
        return self._fetch(self._state.artifacts, EntityType.ARTIFACT.value, artifact_id)

    # --- observations (insert-only) -------------------------------------------------------

    def add_segment(self, s: Segment) -> None:
        state = self._writable()
        seg_key = (s.run_id, s.source_object_id, s.ordinal)
        if seg_key in state.segments_by_ordinal:
            raise ImmutableViolation()
        self._insert(state.segments, s.id, s, state.registry, EntityType.SEGMENT)
        state.segments_by_ordinal[seg_key] = s.id

    def get_segment(self, segment_id: str) -> Segment:
        return self._fetch(self._state.segments, EntityType.SEGMENT.value, segment_id)

    def list_segments(self, source_object_id: str) -> list[Segment]:
        found = [s for s in self._state.segments.values() if s.source_object_id == source_object_id]
        return [copy.deepcopy(s) for s in sorted(found, key=lambda s: s.ordinal)]

    def list_segments_for_run(self, run_id: str) -> list[Segment]:
        found = [s for s in self._state.segments.values() if s.run_id == run_id]
        ordered = sorted(found, key=lambda s: (s.source_object_id, s.ordinal))
        return [copy.deepcopy(s) for s in ordered]

    def add_token(self, t: TokenOccurrence) -> None:
        state = self._writable()
        tok_key = (t.run_id, t.segment_id, t.ordinal)
        if tok_key in state.tokens_by_ordinal:
            raise ImmutableViolation()
        self._insert(state.tokens, t.id, t, state.registry, EntityType.TOKEN_OCCURRENCE)
        state.tokens_by_ordinal[tok_key] = t.id
        state.tokens_by_segment.setdefault(t.segment_id, []).append(copy.deepcopy(t))

    def get_token(self, token_id: str) -> TokenOccurrence:
        return self._fetch(self._state.tokens, EntityType.TOKEN_OCCURRENCE.value, token_id)

    def list_tokens(self, segment_id: str) -> list[TokenOccurrence]:
        found = self._state.tokens_by_segment.get(segment_id, [])
        return [copy.deepcopy(t) for t in sorted(found, key=lambda t: t.ordinal)]

    def get_or_create_form(self, f: Form) -> Form:
        state = self._writable()
        form_key = (f.language, f.orthography_profile, f.text)
        existing = state.forms_by_key.get(form_key)
        if existing is not None:
            return copy.deepcopy(existing)
        self._insert(state.forms, f.id, f, state.registry, EntityType.FORM)
        saved = copy.deepcopy(f)
        state.forms_by_key[form_key] = saved
        return saved

    def get_form(self, form_id: str) -> Form:
        return self._fetch(self._state.forms, EntityType.FORM.value, form_id)

    def add_evidence(self, e: EvidenceItem) -> None:
        state = self._writable()
        self._require_registered(e.target_id)
        self._insert(state.evidence, e.id, e, state.registry, EntityType.EVIDENCE_ITEM)

    def get_evidence(self, evidence_id: str) -> EvidenceItem:
        return self._fetch(self._state.evidence, EntityType.EVIDENCE_ITEM.value, evidence_id)

    def list_evidence_for_target(self, target_id: str) -> list[EvidenceItem]:
        found = [e for e in self._state.evidence.values() if e.target_id == target_id]
        return [copy.deepcopy(e) for e in sorted(found, key=lambda e: (e.created_at, e.id))]

    # --- lineage --------------------------------------------------------------------------

    def add_lineage_edge(self, e: LineageEdge) -> LineageEdge:
        state = self._writable()
        triple = (e.from_id, e.to_id, e.kind)
        existing = state.lineage_by_triple.get(triple)
        if existing is not None:
            return copy.deepcopy(existing)
        self._require_registered(e.from_id)
        self._require_registered(e.to_id)
        # `from` depends on `to`; a cycle exists when `from` is `to` or one of its ancestors.
        if e.from_id == e.to_id or e.from_id in {node for node, _ in self.ancestors(e.to_id)}:
            raise InvalidLineage()
        saved = copy.deepcopy(e)
        state.lineage[e.id] = saved
        state.lineage_by_triple[triple] = saved
        state.lineage_out.setdefault(e.from_id, []).append(e.to_id)
        state.lineage_in.setdefault(e.to_id, []).append(e.from_id)
        state.lineage_edges_out.setdefault(e.from_id, []).append(saved)
        state.lineage_edges_in.setdefault(e.to_id, []).append(saved)
        return copy.deepcopy(e)

    def list_lineage_edges(
        self, object_id: str, direction: Literal["out", "in"]
    ) -> list[LineageEdge]:
        if direction == "out":
            found = self._state.lineage_edges_out.get(object_id, [])
        else:
            found = self._state.lineage_edges_in.get(object_id, [])
        return [copy.deepcopy(e) for e in sorted(found, key=lambda e: e.id)]

    def list_lineage_edges_by_kind(self, kind: LineageKind) -> list[LineageEdge]:
        edges = [
            e
            for edge_list in self._state.lineage_edges_out.values()
            for e in edge_list
            if e.kind is kind
        ]
        return [copy.deepcopy(e) for e in sorted(edges, key=lambda e: e.id)]

    def ancestors(self, object_id: str) -> list[tuple[str, int]]:
        return self._walk(object_id, self._out_neighbours)

    def descendants(self, object_id: str) -> list[tuple[str, int]]:
        return self._walk(object_id, self._in_neighbours)

    def entity_type_of(self, object_id: str) -> EntityType | None:
        return self._state.registry.get(object_id)

    # --- alignments (M3, ADR-0011) -------------------------------------------------------

    def _alignment_sides(
        self, state: _State, run: ProcessingRun, *, require_tokenization: bool
    ) -> tuple[AlignmentSideDescriptor, AlignmentSideDescriptor]:
        """Eager §5.4 selection validation: config shape plus registered source and pinned runs."""
        sides = alignment_side_descriptors(run.config, require_tokenization=require_tokenization)
        for side in sides:
            if side.source_id not in state.sources:
                raise InvalidLineage()
            normalization = state.runs.get(side.normalization_run_id)
            if (
                normalization is None
                or normalization.stage is not RunStage.NORMALIZATION
                or normalization.status is not RunStatus.SUCCEEDED
            ):
                raise InvalidLineage()
            if require_tokenization or side.tokenization_run_id is not None:
                tokenization = state.runs.get(side.tokenization_run_id or "")
                if (
                    tokenization is None
                    or tokenization.stage is not RunStage.TOKENIZATION
                    or tokenization.status is not RunStatus.SUCCEEDED
                ):
                    raise InvalidLineage()
        return sides

    def add_segment_alignment(self, alignment: SegmentAlignment) -> None:
        state = self._writable()
        run = state.runs.get(alignment.run_id)
        if run is None or run.stage is not RunStage.SEGMENT_ALIGNMENT:
            raise InvalidLineage()
        sides = self._alignment_sides(state, run, require_tokenization=False)
        for side, member_ids in (
            (sides[0], alignment.source_segment_ids),
            (sides[1], alignment.target_segment_ids),
        ):
            for member_id in member_ids:
                segment = state.segments.get(member_id)
                if (
                    segment is None
                    or segment.run_id != side.normalization_run_id
                    or segment.language != side.language
                ):
                    raise InvalidLineage()
        # Disposition references are referential integrity only: the authorization basis
        # artifact and the superseded alignment must exist. Importer trust, actor match
        # and HUMAN_REVIEW policy are WP3.7 service scope, not checked here.
        basis_id = alignment.authorization_basis_id
        if basis_id is not None and basis_id not in state.artifacts:
            raise InvalidLineage()
        supersedes_id = alignment.supersedes_id
        if supersedes_id is not None and supersedes_id not in state.segment_alignments:
            raise InvalidLineage()
        if (alignment.run_id, alignment.group_key) in state.segment_alignment_natural:
            raise ImmutableViolation()
        self._insert(
            state.segment_alignments,
            alignment.id,
            alignment,
            state.registry,
            EntityType.SEGMENT_ALIGNMENT,
        )
        state.segment_alignment_natural[(alignment.run_id, alignment.group_key)] = alignment.id
        state.segment_alignment_ids_by_run.setdefault(alignment.run_id, []).append(alignment.id)

    def get_segment_alignment(self, alignment_id: str) -> SegmentAlignment:
        return self._fetch(
            self._state.segment_alignments, EntityType.SEGMENT_ALIGNMENT.value, alignment_id
        )

    def list_segment_alignments_for_run(self, run_id: str) -> list[SegmentAlignment]:
        ids = self._state.segment_alignment_ids_by_run.get(run_id, [])
        found = [self._state.segment_alignments[alignment_id] for alignment_id in ids]
        ordered = sorted(found, key=lambda alignment: (alignment.group_key, alignment.id))
        return [copy.deepcopy(alignment) for alignment in ordered]

    def add_token_alignment_edge(self, edge: TokenAlignmentEdge) -> None:
        state = self._writable()
        run = state.runs.get(edge.run_id)
        if run is None or run.stage is not RunStage.TOKEN_ALIGNMENT:
            raise InvalidLineage()
        sides = self._alignment_sides(state, run, require_tokenization=True)
        alignment = state.segment_alignments.get(edge.segment_alignment_id)
        if alignment is None:
            raise InvalidLineage()
        for token_id, side, member_ids in (
            (edge.source_token_id, sides[0], alignment.source_segment_ids),
            (edge.target_token_id, sides[1], alignment.target_segment_ids),
        ):
            token = state.tokens.get(token_id)
            if token is None or token.run_id != side.tokenization_run_id:
                raise InvalidLineage()
            if token.segment_id not in member_ids:
                raise InvalidLineage()
        natural = (
            edge.run_id,
            edge.segment_alignment_id,
            edge.source_token_id,
            edge.target_token_id,
            edge.direction.value,
            edge.symmetrization.value,
        )
        if natural in state.token_edge_natural:
            raise ImmutableViolation()
        self._insert(
            state.token_edges, edge.id, edge, state.registry, EntityType.TOKEN_ALIGNMENT_EDGE
        )
        state.token_edge_natural[natural] = edge.id
        state.token_edge_ids_by_run.setdefault(edge.run_id, []).append(edge.id)

    def get_token_alignment_edge(self, edge_id: str) -> TokenAlignmentEdge:
        return self._fetch(self._state.token_edges, EntityType.TOKEN_ALIGNMENT_EDGE.value, edge_id)

    def list_token_alignment_edges_for_run(self, run_id: str) -> list[TokenAlignmentEdge]:
        ids = self._state.token_edge_ids_by_run.get(run_id, [])
        found = [self._state.token_edges[edge_id] for edge_id in ids]
        ordered = sorted(
            found,
            key=lambda edge: (
                edge.source_token_id,
                edge.target_token_id,
                edge.direction.value,
                edge.symmetrization.value,
                edge.id,
            ),
        )
        return [copy.deepcopy(edge) for edge in ordered]

    # --- lexical evidence (M4, ADR-0013) ---------------------------------------------------

    @staticmethod
    def _require_runs[T: DomainModel](state: _State, model: T, *run_ids: str) -> T:
        for run_id in run_ids:
            if run_id not in state.runs:
                raise InvalidLineage()
        return model

    def add_concept(self, c: Concept) -> None:
        state = self._writable()
        self._require_runs(state, c, c.run_id)
        self._insert(state.concepts, c.id, c, state.registry, EntityType.CONCEPT)

    def get_concept(self, concept_id: str) -> Concept:
        return self._fetch(self._state.concepts, EntityType.CONCEPT.value, concept_id)

    def list_concepts(self) -> list[Concept]:
        found = sorted(self._state.concepts.values(), key=lambda c: (c.created_at, c.id))
        return [copy.deepcopy(c) for c in found]

    def add_lexeme(self, lexeme: Lexeme) -> None:
        state = self._writable()
        self._require_runs(state, lexeme, lexeme.run_id)
        if lexeme.lemma_form_id is not None and lexeme.lemma_form_id not in state.forms:
            raise InvalidLineage()
        self._insert(state.lexemes, lexeme.id, lexeme, state.registry, EntityType.LEXEME)
        state.lexeme_ids_by_language.setdefault(lexeme.language, []).append(lexeme.id)

    def get_lexeme(self, lexeme_id: str) -> Lexeme:
        return self._fetch(self._state.lexemes, EntityType.LEXEME.value, lexeme_id)

    def list_lexemes_by_language(self, language: str) -> list[Lexeme]:
        ids = self._state.lexeme_ids_by_language.get(language, [])
        found = [self._state.lexemes[lexeme_id] for lexeme_id in ids]
        ordered = sorted(found, key=lambda item: (item.created_at, item.id))
        return [copy.deepcopy(item) for item in ordered]

    def list_lexemes_by_form(self, form_id: str) -> list[Lexeme]:
        # The relation, not `lemma_form_id`, decides: a form may back zero, one or many
        # lexemes and a non-lemma link still resolves (ADR-0013 §1).
        link_ids = self._state.form_lexeme_ids_by_form.get(form_id, [])
        links = [self._state.form_lexeme_links[link_id] for link_id in link_ids]
        found = [self._state.lexemes[link.lexeme_id] for link in links]
        ordered = sorted(found, key=lambda item: (item.created_at, item.id))
        return [copy.deepcopy(item) for item in ordered]

    def set_lexeme_status(
        self,
        lexeme_id: str,
        status: LifecycleStatus,
        score_breakdown: LexicalScoreBreakdown | None = None,
    ) -> Lexeme:
        state = self._writable()
        current = self._fetch(state.lexemes, EntityType.LEXEME.value, lexeme_id)
        updated = _revalidate(current, status=status, score_breakdown=score_breakdown)
        state.lexemes[lexeme_id] = copy.deepcopy(updated)
        return updated

    def add_form_lexeme_link(self, link: FormLexemeLink) -> None:
        state = self._writable()
        self._require_runs(state, link, link.run_id)
        if link.form_id not in state.forms:
            raise InvalidLineage()
        if link.lexeme_id not in state.lexemes:
            raise InvalidLineage()
        if (link.form_id, link.lexeme_id) in state.form_lexeme_natural:
            raise ImmutableViolation()
        self._insert(
            state.form_lexeme_links,
            link.id,
            link,
            state.registry,
            EntityType.FORM_LEXEME,
        )
        state.form_lexeme_natural[(link.form_id, link.lexeme_id)] = link.id
        state.form_lexeme_ids_by_form.setdefault(link.form_id, []).append(link.id)
        state.form_lexeme_ids_by_lexeme.setdefault(link.lexeme_id, []).append(link.id)

    def list_form_lexeme_links_for_form(self, form_id: str) -> list[FormLexemeLink]:
        ids = self._state.form_lexeme_ids_by_form.get(form_id, [])
        found = [self._state.form_lexeme_links[link_id] for link_id in ids]
        ordered = sorted(found, key=lambda link: (link.created_at, link.id))
        return [copy.deepcopy(link) for link in ordered]

    def list_form_lexeme_links_for_lexeme(self, lexeme_id: str) -> list[FormLexemeLink]:
        ids = self._state.form_lexeme_ids_by_lexeme.get(lexeme_id, [])
        found = [self._state.form_lexeme_links[link_id] for link_id in ids]
        ordered = sorted(found, key=lambda link: (link.created_at, link.id))
        return [copy.deepcopy(link) for link in ordered]

    def add_sense(self, s: Sense) -> None:
        state = self._writable()
        self._require_runs(state, s, s.run_id)
        if s.lexeme_id not in state.lexemes:
            raise InvalidLineage()
        if s.concept_id is not None and s.concept_id not in state.concepts:
            raise InvalidLineage()
        self._insert(state.senses, s.id, s, state.registry, EntityType.SENSE)
        state.sense_ids_by_lexeme.setdefault(s.lexeme_id, []).append(s.id)

    def get_sense(self, sense_id: str) -> Sense:
        return self._fetch(self._state.senses, EntityType.SENSE.value, sense_id)

    def list_senses_for_lexeme(self, lexeme_id: str) -> list[Sense]:
        ids = self._state.sense_ids_by_lexeme.get(lexeme_id, [])
        found = [self._state.senses[sense_id] for sense_id in ids]
        ordered = sorted(found, key=lambda s: (s.created_at, s.id))
        return [copy.deepcopy(s) for s in ordered]

    def set_sense_status(
        self,
        sense_id: str,
        status: LifecycleStatus,
        score_breakdown: LexicalScoreBreakdown | None = None,
    ) -> Sense:
        state = self._writable()
        current = self._fetch(state.senses, EntityType.SENSE.value, sense_id)
        updated = _revalidate(current, status=status, score_breakdown=score_breakdown)
        state.senses[sense_id] = copy.deepcopy(updated)
        return updated

    # --- human review queue (M4, ADR-0013) ------------------------------------------------

    def add_review_task(self, task: ReviewTask) -> None:
        state = self._writable()
        self._require_runs(state, task, task.creator_run_id)
        # target_id references the object registry, exactly as evidence_item does.
        if task.target_id not in state.registry:
            raise InvalidLineage()
        self._insert(state.review_tasks, task.id, task, state.registry, EntityType.REVIEW_TASK)

    def get_review_task(self, task_id: str) -> ReviewTask:
        return self._fetch(self._state.review_tasks, EntityType.REVIEW_TASK.value, task_id)

    def get_review_task_for_update(self, task_id: str) -> ReviewTask:
        # Memory holds no row locks: the in-transaction fetch plus the transaction
        # snapshot stand in for PostgreSQL's locked reread.
        state = self._writable()
        return self._fetch(state.review_tasks, EntityType.REVIEW_TASK.value, task_id)

    def list_review_tasks(
        self,
        *,
        task_type: ReviewTaskType | None = None,
        required_role: str | None = None,
        status: str | None = "open",
        min_priority: float | None = None,
    ) -> list[ReviewTask]:
        wanted_status = queue_status_filter(status)
        wanted_type = None if task_type is None else ReviewTaskType(task_type)
        floor = checked_min_priority(min_priority)
        found = [
            task
            for task in self._state.review_tasks.values()
            if (wanted_status is None or task.status == wanted_status)
            and (wanted_type is None or task.task_type is wanted_type)
            and (required_role is None or task.required_role == required_role)
            and (floor is None or task.priority >= floor)
        ]
        ordered = sorted(found, key=lambda t: (-t.priority, t.created_at, t.id))
        return [copy.deepcopy(task) for task in ordered]

    def set_review_task_status(self, task_id: str, status: str) -> ReviewTask:
        if status not in REVIEW_TASK_STATUSES:
            # A queue entry carries an operational state, never a LifecycleStatus.
            raise SchemaViolation()
        state = self._writable()
        current = self._fetch(state.review_tasks, EntityType.REVIEW_TASK.value, task_id)
        updated = _revalidate(current, status=status)
        state.review_tasks[task_id] = copy.deepcopy(updated)
        return updated

    def add_review_decision(self, decision: ReviewDecision) -> None:
        state = self._writable()
        if decision.task_id not in state.review_tasks:
            raise InvalidLineage()
        if decision.target_id not in state.registry:
            raise InvalidLineage()
        if (
            decision.superseding_object_id is not None
            and decision.superseding_object_id not in state.registry
        ):
            raise InvalidLineage()
        self._insert(
            state.review_decisions,
            decision.id,
            decision,
            state.registry,
            EntityType.REVIEW_DECISION,
        )
        state.review_decision_ids_by_target.setdefault(decision.target_id, []).append(decision.id)

    def get_review_decision(self, decision_id: str) -> ReviewDecision:
        return self._fetch(
            self._state.review_decisions, EntityType.REVIEW_DECISION.value, decision_id
        )

    def list_review_decisions_for_target(self, target_id: str) -> list[ReviewDecision]:
        ids = self._state.review_decision_ids_by_target.get(target_id, [])
        found = [self._state.review_decisions[decision_id] for decision_id in ids]
        ordered = sorted(found, key=lambda d: (d.created_at, d.id))
        return [copy.deepcopy(decision) for decision in ordered]

    # --- IGT observations and the morphology graph (M5, ADR-0017) -------------------------

    def add_igt_observation(self, observation: IGTObservation) -> None:
        state = self._writable()
        if observation.source_id not in state.sources:
            raise InvalidLineage()
        if observation.source_object_id not in state.source_objects:
            raise InvalidLineage()
        if observation.run_id not in state.runs:
            raise InvalidLineage()
        if observation.segment_id is not None and observation.segment_id not in state.segments:
            raise InvalidLineage()
        record = (
            observation.run_id,
            observation.source_object_id,
            observation.record_ordinal,
        )
        if record in state.igt_observation_records:
            raise ImmutableViolation()
        self._insert(
            state.igt_observations,
            observation.id,
            observation,
            state.registry,
            EntityType.IGT_OBSERVATION,
        )
        state.igt_observation_records.add(record)

    def get_igt_observation(self, observation_id: str) -> IGTObservation:
        return self._fetch(
            self._state.igt_observations, EntityType.IGT_OBSERVATION.value, observation_id
        )

    def list_igt_observations_for_run(self, run_id: str) -> list[IGTObservation]:
        found = [o for o in self._state.igt_observations.values() if o.run_id == run_id]
        return [copy.deepcopy(o) for o in sorted(found, key=lambda o: (o.record_ordinal, o.id))]

    def list_igt_observations_for_object(self, source_object_id: str) -> list[IGTObservation]:
        found = [
            o
            for o in self._state.igt_observations.values()
            if o.source_object_id == source_object_id
        ]
        return [copy.deepcopy(o) for o in sorted(found, key=lambda o: (o.record_ordinal, o.id))]

    def add_feature(self, feature: Feature) -> Feature:
        state = self._writable()
        existing_id = state.feature_natural.get((feature.namespace, feature.label))
        if existing_id is not None:
            return copy.deepcopy(state.features[existing_id])
        self._require_runs(state, feature, feature.run_id)
        self._insert(state.features, feature.id, feature, state.registry, EntityType.FEATURE)
        state.feature_natural[(feature.namespace, feature.label)] = feature.id
        return copy.deepcopy(feature)

    def get_feature(self, feature_id: str) -> Feature:
        return self._fetch(self._state.features, EntityType.FEATURE.value, feature_id)

    def get_feature_by_label(self, namespace: str, label: str) -> Feature | None:
        feature_id = self._state.feature_natural.get((namespace, label))
        return None if feature_id is None else copy.deepcopy(self._state.features[feature_id])

    def list_features(self, namespace: str | None = None) -> list[Feature]:
        found = [
            f
            for f in self._state.features.values()
            if namespace is None or f.namespace == namespace
        ]
        return [copy.deepcopy(f) for f in sorted(found, key=lambda f: (f.namespace, f.label, f.id))]

    def add_morpheme(self, morpheme: Morpheme) -> None:
        state = self._writable()
        self._require_runs(state, morpheme, morpheme.run_id)
        if (morpheme.run_id, morpheme.identity_key) in state.morpheme_identity:
            raise ImmutableViolation()
        self._insert(state.morphemes, morpheme.id, morpheme, state.registry, EntityType.MORPHEME)
        state.morpheme_identity.add((morpheme.run_id, morpheme.identity_key))

    def get_morpheme(self, morpheme_id: str) -> Morpheme:
        return self._fetch(self._state.morphemes, EntityType.MORPHEME.value, morpheme_id)

    def get_morpheme_for_update(self, morpheme_id: str) -> Morpheme:
        # Memory holds no row locks: the in-transaction fetch plus the transaction
        # snapshot stand in for PostgreSQL's locked reread.
        state = self._writable()
        return self._fetch(state.morphemes, EntityType.MORPHEME.value, morpheme_id)

    def list_morphemes_for_run(self, run_id: str) -> list[Morpheme]:
        found = [m for m in self._state.morphemes.values() if m.run_id == run_id]
        return [copy.deepcopy(m) for m in sorted(found, key=lambda m: (m.created_at, m.id))]

    def set_morpheme_status(
        self,
        morpheme_id: str,
        status: LifecycleStatus,
        score_breakdown: ScoreBreakdown | None = None,
    ) -> Morpheme:
        state = self._writable()
        current = self._fetch(state.morphemes, EntityType.MORPHEME.value, morpheme_id)
        updated = _revalidate(current, status=status, score_breakdown=score_breakdown)
        state.morphemes[morpheme_id] = copy.deepcopy(updated)
        return updated

    def add_allomorph(self, allomorph: Allomorph) -> None:
        state = self._writable()
        if allomorph.morpheme_id not in state.morphemes:
            raise InvalidLineage()
        self._require_runs(state, allomorph, allomorph.run_id)
        if (allomorph.morpheme_id, allomorph.form) in state.allomorph_natural:
            raise ImmutableViolation()
        self._insert(
            state.allomorphs, allomorph.id, allomorph, state.registry, EntityType.ALLOMORPH
        )
        state.allomorph_natural.add((allomorph.morpheme_id, allomorph.form))

    def list_allomorphs_for_morpheme(self, morpheme_id: str) -> list[Allomorph]:
        found = [a for a in self._state.allomorphs.values() if a.morpheme_id == morpheme_id]
        return [copy.deepcopy(a) for a in sorted(found, key=lambda a: (a.created_at, a.id))]

    def set_allomorph_status(self, allomorph_id: str, status: LifecycleStatus) -> Allomorph:
        state = self._writable()
        current = self._fetch(state.allomorphs, EntityType.ALLOMORPH.value, allomorph_id)
        updated = _revalidate(current, status=status)
        state.allomorphs[allomorph_id] = copy.deepcopy(updated)
        return updated

    def add_morph_analysis(
        self,
        analysis: MorphAnalysis,
        segments: Sequence[MorphSegment],
        segment_features: Sequence[MorphSegmentFeature] = (),
        boundary_marks: tuple[str, ...] = ("-", "="),
    ) -> None:
        state = self._writable()
        # Every check runs before any insert: the write below is all-or-nothing.
        if analysis.run_id not in state.runs:
            raise InvalidLineage()
        token = state.tokens.get(analysis.target_token_id)
        if token is None:
            raise InvalidLineage()
        if token_surface_for(token, analysis.span_representation) != analysis.surface:
            raise SchemaViolation()
        for segment in segments:
            if segment.morpheme_id is not None and segment.morpheme_id not in state.morphemes:
                raise InvalidLineage()
            if segment.allomorph_id is not None:
                # An allomorph of a different morpheme would leave the graph self-
                # contradictory: the allomorph listing and the analyses listing for the
                # segment's morpheme would disagree about the same analysis.
                allomorph = state.allomorphs.get(segment.allomorph_id)
                if allomorph is None or allomorph.morpheme_id != segment.morpheme_id:
                    raise InvalidLineage()
        segment_ids = {segment.id for segment in segments}
        seen_assignments: set[tuple[str, str]] = set()
        for assignment in segment_features:
            if assignment.feature_id not in state.features:
                raise InvalidLineage()
            if assignment.segment_id not in segment_ids:
                raise InvalidLineage()
            # A repeated (segment, feature) pair would collide with the PostgreSQL
            # composite primary key; refuse it here so both backends fail identically.
            if (assignment.segment_id, assignment.feature_id) in seen_assignments:
                raise ImmutableViolation()
            seen_assignments.add((assignment.segment_id, assignment.feature_id))
        try:
            check_analysis(analysis, list(segments), boundary_marks)
        except ValueError:
            # Mirrors the PostgreSQL backend: the cause is dropped like every input echo.
            raise SchemaViolation() from None
        if (analysis.target_token_id, analysis.run_id, analysis.signature) in (
            state.morph_analysis_natural
        ):
            raise ImmutableViolation()
        seen_ids = {analysis.id}
        seen_ordinals: set[tuple[str, int]] = set()
        for segment in segments:
            if segment.id in seen_ids:
                raise ImmutableViolation()
            if (segment.analysis_id, segment.ordinal) in seen_ordinals or (
                segment.analysis_id,
                segment.ordinal,
            ) in state.morph_segment_ordinals:
                raise ImmutableViolation()
            seen_ids.add(segment.id)
            seen_ordinals.add((segment.analysis_id, segment.ordinal))
        self._insert(
            state.morph_analyses,
            analysis.id,
            analysis,
            state.registry,
            EntityType.MORPH_ANALYSIS,
        )
        for segment in segments:
            self._insert(
                state.morph_segments,
                segment.id,
                segment,
                state.registry,
                EntityType.MORPH_SEGMENT,
            )
            state.morph_segment_ordinals.add((segment.analysis_id, segment.ordinal))
        state.morph_segment_features.extend(copy.deepcopy(sf) for sf in segment_features)
        state.morph_analysis_natural.add(
            (analysis.target_token_id, analysis.run_id, analysis.signature)
        )

    def get_morph_analysis(self, analysis_id: str) -> MorphAnalysis:
        return self._fetch(self._state.morph_analyses, EntityType.MORPH_ANALYSIS.value, analysis_id)

    def get_morph_analysis_for_update(self, analysis_id: str) -> MorphAnalysis:
        # Memory holds no row locks: the in-transaction fetch plus the transaction
        # snapshot stand in for PostgreSQL's locked reread.
        state = self._writable()
        return self._fetch(state.morph_analyses, EntityType.MORPH_ANALYSIS.value, analysis_id)

    def list_morph_analyses_for_token(self, token_id: str) -> list[MorphAnalysis]:
        found = [a for a in self._state.morph_analyses.values() if a.target_token_id == token_id]
        return [copy.deepcopy(a) for a in sorted(found, key=lambda a: (a.created_at, a.id))]

    def list_morph_analyses_for_run(self, run_id: str) -> list[MorphAnalysis]:
        found = [a for a in self._state.morph_analyses.values() if a.run_id == run_id]
        return [copy.deepcopy(a) for a in sorted(found, key=lambda a: (a.created_at, a.id))]

    def list_analyses_linking_morpheme(self, morpheme_id: str) -> list[MorphAnalysis]:
        # Resolved through the segments, so one linked segment is enough and unlinked
        # competing analyses stay excluded (ADR-0017: no winner column).
        linked = {
            segment.analysis_id
            for segment in self._state.morph_segments.values()
            if segment.morpheme_id == morpheme_id
        }
        found = [a for a in self._state.morph_analyses.values() if a.id in linked]
        return [copy.deepcopy(a) for a in sorted(found, key=lambda a: (a.created_at, a.id))]

    def list_morph_segments(self, analysis_id: str) -> list[MorphSegment]:
        found = [s for s in self._state.morph_segments.values() if s.analysis_id == analysis_id]
        return [copy.deepcopy(s) for s in sorted(found, key=lambda s: s.ordinal)]

    def get_morph_segment(self, segment_id: str) -> MorphSegment:
        segment = self._state.morph_segments.get(segment_id)
        if segment is None:
            raise NotFound(EntityType.MORPH_SEGMENT.value, segment_id)
        return copy.deepcopy(segment)

    def list_segment_features(self, segment_id: str) -> list[MorphSegmentFeature]:
        found = [sf for sf in self._state.morph_segment_features if sf.segment_id == segment_id]
        return [copy.deepcopy(sf) for sf in sorted(found, key=lambda sf: sf.feature_id)]

    def set_morph_analysis_status(
        self,
        analysis_id: str,
        status: LifecycleStatus,
        score_breakdown: ScoreBreakdown | None = None,
    ) -> MorphAnalysis:
        state = self._writable()
        current = self._fetch(state.morph_analyses, EntityType.MORPH_ANALYSIS.value, analysis_id)
        updated = _revalidate(current, status=status, score_breakdown=score_breakdown)
        state.morph_analyses[analysis_id] = copy.deepcopy(updated)
        return updated

    # --- source use approvals (M5, ADR-0018) ----------------------------------------------

    def add_source_use_approval(self, approval: SourceUseApproval) -> None:
        state = self._writable()
        if approval.source_id not in state.sources:
            raise InvalidLineage()
        self._require_runs(state, approval, approval.run_id)
        self._insert(
            state.source_use_approvals,
            approval.id,
            approval,
            state.registry,
            EntityType.SOURCE_USE_APPROVAL,
        )

    def list_source_use_approvals(self, source_id: str) -> list[SourceUseApproval]:
        found = [a for a in self._state.source_use_approvals.values() if a.source_id == source_id]
        return [copy.deepcopy(a) for a in sorted(found, key=lambda a: (a.created_at, a.id))]

    def lock_sources(self, source_ids: Sequence[str], *, timeout_seconds: float = 300.0) -> None:
        # Memory holds no row locks: the transaction snapshot plus existence checks stand
        # in for PostgreSQL's sorted SELECT FOR UPDATE. Acquisition never blocks, so the
        # shared bound only needs validation, not enforcement.
        state = self._writable()
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        for source_id in sorted(set(source_ids)):
            if source_id not in state.sources:
                raise NotFound(EntityType.SOURCE.value, source_id)

    @contextmanager
    def alignment_lock(self, request_key: str, *, timeout_seconds: float = 300.0) -> Iterator[None]:
        if self._in_transaction:
            raise RuntimeError("alignment_lock must not be nested in repository.transaction")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        lock = self._request_locks.setdefault(request_key, threading.Lock())
        if not lock.acquire(timeout=timeout_seconds):
            raise AlignmentFailed("backend_timeout")
        try:
            yield
        finally:
            lock.release()

    # --- audit and counts -----------------------------------------------------------------

    def add_audit_event(self, e: AuditEvent) -> None:
        self._insert(self._writable().audit_events, e.id, e)

    def list_audit_events(self) -> list[AuditEvent]:
        events = sorted(self._state.audit_events.values(), key=lambda e: (e.occurred_at, e.id))
        return [copy.deepcopy(e) for e in events]

    def count(self, entity_type: EntityType) -> int:
        return sum(1 for kind in self._state.registry.values() if kind is entity_type)

    def count_lineage_edges(self) -> int:
        return len(self._state.lineage)

    def count_raw_blobs(self) -> int:
        return len(self._state.raw_blobs)

    def count_runs(self, status: RunStatus | None = None) -> int:
        if status is None:
            return len(self._state.runs)
        return sum(1 for r in self._state.runs.values() if r.status is status)
