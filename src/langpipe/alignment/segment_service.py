"""Atomic Stage 4 alignment and governed disposition import (WP3.7)."""

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from pydantic import JsonValue

from langpipe import __version__
from langpipe.alignment.base import (
    AlignmentConfig,
    AlignmentSide,
    SegmentAligner,
    SegmentMatchOutput,
)
from langpipe.alignment.canonical import PARTIAL_COVERAGE, UNMATCHED_REASONS
from langpipe.alignment.governance import ensure_alignment_allowed
from langpipe.alignment.registry import SEGMENT_ALIGNERS, resolve_aligner
from langpipe.alignment.report import (
    link_segment_report,
    segment_report_payload,
    store_segment_report,
)
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AlignmentMode,
    AlignmentStatus,
    ArtifactKind,
    AuditEventType,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    most_restrictive,
)
from langpipe.domain.errors import AlignmentFailed, AmbiguousInput, InvalidLineage, PolicyDenied
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.alignment import SegmentAlignment
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import Segment
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.governance import effective_policy
from langpipe.governance.lineage_policy import effective_decision
from langpipe.ingestion.runs import RunRecorder
from langpipe.storage.repository import Repository
from langpipe.text.registry import VersionedRegistry

logger = logging.getLogger(__name__)
_TOOL = "langpipe.segment-align"
_AUTH_SCHEMA = "alignment-authorization"


@dataclass(frozen=True)
class SegmentAlignmentSummary:
    run: ProcessingRun
    alignments: int
    unmatched_source: int
    unmatched_target: int
    report: Artifact | None
    reused: bool


class SegmentAlignmentService:
    def __init__(
        self,
        ctx: AppContext,
        *,
        aligners: VersionedRegistry[SegmentAligner] | None = None,
        trusted_importers: Sequence[str] | None = None,
    ) -> None:
        self.ctx = ctx
        self.aligners = aligners if aligners is not None else SEGMENT_ALIGNERS
        if trusted_importers is None:
            trusted_importers = tuple(
                item.strip()
                for item in os.environ.get("LANGPIPE_TRUSTED_IMPORTERS", "").split(",")
                if item.strip()
            )
        self.trusted_importers = frozenset(trusted_importers)
        self.recorder = RunRecorder(ctx)

    def align(
        self,
        source: AlignmentSide,
        target: AlignmentSide,
        *,
        method: str = "canonical_locator@0.1.0",
        config: AlignmentConfig,
    ) -> SegmentAlignmentSummary:
        adapter = resolve_aligner(self.aligners, method)
        method_id = f"{adapter.name}@{adapter.version}"
        sides = [source, target]
        sources = ensure_alignment_allowed(self.ctx, [source.source_id, target.source_id])
        source_segments = self._selected_segments(source)
        target_segments = self._selected_segments(target)
        segment_ids = [s.id for s in (*source_segments, *target_segments)]
        sources = ensure_alignment_allowed(self.ctx, [*sources, *segment_ids])
        if source.source_id == target.source_id:
            self._check_bilingual_same_source(source, target)
        run_config: dict[str, JsonValue] = {
            "method": method_id,
            "namespace": config.namespace,
            "versification_id": config.versification_id,
            "symmetrization": config.symmetrization.value,
            "model": config.model,
            "threads": config.threads,
            "timeout_seconds": config.timeout_seconds,
            "random_seed": config.random_seed,
            "sides": [
                self._side_config(side, role)
                for side, role in zip(sides, ("source", "target"), strict=True)
            ],
        }
        inputs = self._run_inputs(sides, source_segments, target_segments)
        digest = config_hash(run_config)
        request_key = ProcessingRun.compute_run_key(
            RunStage.SEGMENT_ALIGNMENT, _TOOL, __version__, digest, inputs
        )
        with self.ctx.repo.alignment_lock(request_key):
            # Policy is deliberately rechecked before looking up reusable evidence.
            ensure_alignment_allowed(self.ctx, [source.source_id, target.source_id, *segment_ids])
            reusable = self.recorder.find_reusable(
                RunStage.SEGMENT_ALIGNMENT, _TOOL, run_config, inputs
            )
            if reusable is not None:
                try:
                    with self.ctx.repo.transaction():
                        self.ctx.repo.lock_sources(sources)
                        self._check_locked_sources(sources)
                except PolicyDenied as exc:
                    self._record_denial(exc.source_id, exc.operation, exc.decision)
                    raise
                return self._summary(reusable, True)
            run = self.recorder.start(RunStage.SEGMENT_ALIGNMENT, _TOOL, run_config, inputs)
            try:
                output = adapter.align(source_segments, target_segments, config)
                self._validate_match_output(output, source_segments, target_segments)
                created = [
                    SegmentAlignment(
                        id=self.ctx.new_id(IdPrefix.SEGMENT_ALIGNMENT),
                        source_segment_ids=tuple(s.id for s in group.source_segments),
                        target_segment_ids=tuple(s.id for s in group.target_segments),
                        method=method_id,
                        mode=(
                            AlignmentMode.CANONICAL
                            if method_id.startswith("canonical_")
                            else AlignmentMode.HEURISTIC
                        ),
                        status=group.status,
                        score=None,
                        raw_scores={},
                        group_key=group.group_key,
                        run_id=run.id,
                        created_at=self.ctx.clock(),
                    )
                    for group in output.groups
                ]
                access = most_restrictive(
                    effective_policy(self.ctx.repo, s).access_class for s in sources
                )
                with self.ctx.repo.transaction():
                    self.ctx.repo.lock_sources(sources)
                    self._check_locked_sources(sources)
                    for row in created:
                        self.ctx.repo.add_segment_alignment(row)
                        for member_id in (*row.source_segment_ids, *row.target_segment_ids):
                            self._lineage(row.id, member_id, LineageKind.DERIVED_FROM, run.id)
                        self.ctx.repo.add_run_io(run.id, row.id, RunIoRole.OUTPUT)
                    unmatched_source = [
                        item
                        for item in output.unmatched
                        if item[0] in {s.id for s in source_segments}
                    ]
                    unmatched_target = [
                        item
                        for item in output.unmatched
                        if item[0] in {s.id for s in target_segments}
                    ]
                    report = store_segment_report(
                        self.ctx,
                        run=run,
                        payload=segment_report_payload(
                            run_id=run.id,
                            method=method_id,
                            mode=created[0].mode.value
                            if created
                            else AlignmentMode.CANONICAL.value,
                            sides=[self._report_side(side) for side in sides],
                            namespace=config.namespace,
                            versification_id=config.versification_id,
                            groups=created,
                            group_reasons={
                                row.id: group.reason
                                for row, group in zip(created, output.groups, strict=True)
                            },
                            unmatched_source=unmatched_source,
                            unmatched_target=unmatched_target,
                        ),
                        access_class=access,
                    )
                    link_segment_report(
                        self.ctx, run=run, report=report, alignments=created, segments=segment_ids
                    )
                    for object_id in inputs:
                        self.ctx.repo.add_run_io(run.id, object_id, RunIoRole.INPUT)
                    succeeded = self.recorder.succeed(run.id)
                return SegmentAlignmentSummary(
                    succeeded,
                    len(created),
                    len(unmatched_source),
                    len(unmatched_target),
                    report,
                    False,
                )
            except BaseException as exc:
                if isinstance(exc, PolicyDenied):
                    self._record_denial(exc.source_id, exc.operation, exc.decision)
                self.recorder.fail(run.id, exc)
                raise

    def import_disposition(
        self,
        predecessor_id: str,
        basis_artifact_id: str,
        status: Literal["approved", "rejected"],
    ) -> SegmentAlignmentSummary:
        if status not in ("approved", "rejected"):
            raise AlignmentFailed("authorization_invalid")
        predecessor = self.ctx.repo.get_segment_alignment(predecessor_id)
        artifact, basis_run, data = self._validate_authorization(
            predecessor, basis_artifact_id, status
        )
        segment_ids = (*predecessor.source_segment_ids, *predecessor.target_segment_ids)
        source_ids = ensure_alignment_allowed(self.ctx, segment_ids)
        self._require_human_review(source_ids)
        run_config = {
            "disposition": status,
            "predecessor_id": predecessor.id,
            "basis_artifact_id": artifact.id,
            "actor": data["actor"],
            "sides": self.ctx.repo.get_run(predecessor.run_id).config["sides"],
        }
        inputs = [predecessor.id, artifact.id]
        digest = config_hash(run_config)
        run_key = ProcessingRun.compute_run_key(
            RunStage.SEGMENT_ALIGNMENT, _TOOL, __version__, digest, inputs
        )
        with self.ctx.repo.alignment_lock(run_key):
            ensure_alignment_allowed(self.ctx, segment_ids)
            self._require_human_review(source_ids)
            reusable = self.recorder.find_reusable(
                RunStage.SEGMENT_ALIGNMENT, _TOOL, run_config, inputs
            )
            if reusable is not None:
                try:
                    with self.ctx.repo.transaction():
                        self.ctx.repo.lock_sources(source_ids)
                        self._check_locked_sources(source_ids)
                        self._check_locked_review(source_ids)
                except PolicyDenied as exc:
                    self._record_denial(exc.source_id, exc.operation, exc.decision)
                    raise
                return self._summary(reusable, True)
            # Catch conflicting successors inserted since preflight, before creating a run.
            if any(
                edge.kind is LineageKind.SUPERSEDES
                for edge in self.ctx.repo.list_lineage_edges(predecessor.id, "in")
            ):
                raise AlignmentFailed("authorization_invalid")
            run = self.recorder.start(RunStage.SEGMENT_ALIGNMENT, _TOOL, run_config, inputs)
            successor = SegmentAlignment(
                id=self.ctx.new_id(IdPrefix.SEGMENT_ALIGNMENT),
                source_segment_ids=predecessor.source_segment_ids,
                target_segment_ids=predecessor.target_segment_ids,
                method=predecessor.method,
                mode=predecessor.mode,
                status=AlignmentStatus(status),
                score=predecessor.score,
                raw_scores=predecessor.raw_scores,
                group_key=predecessor.group_key,
                run_id=run.id,
                created_at=self.ctx.clock(),
                authorization_basis_id=artifact.id,
                supersedes_id=predecessor.id,
            )
            try:
                access = most_restrictive(
                    effective_policy(self.ctx.repo, s).access_class for s in source_ids
                )
                with self.ctx.repo.transaction():
                    self.ctx.repo.lock_sources(source_ids)
                    if any(
                        edge.kind is LineageKind.SUPERSEDES
                        for edge in self.ctx.repo.list_lineage_edges(predecessor.id, "in")
                    ):
                        raise AlignmentFailed("authorization_invalid")
                    self._check_locked_sources(source_ids)
                    self._check_locked_review(source_ids)
                    self.ctx.repo.add_segment_alignment(successor)
                    self._lineage(successor.id, predecessor.id, LineageKind.SUPERSEDES, run.id)
                    self._lineage(successor.id, artifact.id, LineageKind.IMPORTED_FROM, run.id)
                    for member_id in segment_ids:
                        self._lineage(successor.id, member_id, LineageKind.DERIVED_FROM, run.id)
                    self.ctx.repo.add_run_io(run.id, predecessor.id, RunIoRole.INPUT)
                    self.ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.INPUT)
                    self.ctx.repo.add_run_io(run.id, successor.id, RunIoRole.OUTPUT)
                    report = store_segment_report(
                        self.ctx,
                        run=run,
                        payload=segment_report_payload(
                            run_id=run.id,
                            method=successor.method,
                            mode=successor.mode.value,
                            sides=[],
                            namespace="disposition",
                            versification_id=None,
                            groups=[successor],
                            group_reasons={successor.id: None},
                            unmatched_source=[],
                            unmatched_target=[],
                            disposition={
                                "predecessor_id": predecessor.id,
                                "status": status,
                                "basis_artifact_id": artifact.id,
                            },
                        ),
                        access_class=access,
                    )
                    link_segment_report(
                        self.ctx,
                        run=run,
                        report=report,
                        alignments=[successor],
                        segments=segment_ids,
                    )
                    succeeded = self.recorder.succeed(run.id)
                return SegmentAlignmentSummary(succeeded, 1, 0, 0, report, False)
            except BaseException as exc:
                if isinstance(exc, PolicyDenied):
                    self._record_denial(exc.source_id, exc.operation, exc.decision)
                self.recorder.fail(run.id, exc)
                raise

    def _selected_segments(self, side: AlignmentSide) -> list[Segment]:
        run = self.ctx.repo.get_run(side.normalization_run_id)
        if run.stage is not RunStage.NORMALIZATION or run.status is not RunStatus.SUCCEEDED:
            raise InvalidLineage()
        segments = self.ctx.repo.list_segments_for_run(run.id)
        selected = [
            s for s in segments if s.source_id == side.source_id and s.language == side.language
        ]
        if not selected or any(s.source_id != side.source_id for s in segments):
            raise InvalidLineage()
        return selected

    @staticmethod
    def _side_config(side: AlignmentSide, role: str) -> dict[str, JsonValue]:
        return {
            "role": role,
            "source_id": side.source_id,
            "language": side.language,
            "normalization_run_id": side.normalization_run_id,
            "tokenization_run_id": None,
        }

    @staticmethod
    def _report_side(side: AlignmentSide) -> dict[str, str | None]:
        return {
            "source_id": side.source_id,
            "language": side.language,
            "normalization_run_id": side.normalization_run_id,
        }

    @staticmethod
    def _run_inputs(
        sides: Sequence[AlignmentSide],
        source_segments: Sequence[Segment],
        target_segments: Sequence[Segment],
    ) -> list[str]:
        return sorted(
            {side.source_id for side in sides}
            | {side.normalization_run_id for side in sides}
            | {s.id for s in (*source_segments, *target_segments)}
        )

    def _check_bilingual_same_source(self, left: AlignmentSide, right: AlignmentSide) -> None:
        if left.language == right.language:
            raise AlignmentFailed("invalid_coordinates")
        langs = self.ctx.repo.get_source(left.source_id).languages
        if left.language not in langs or right.language not in langs:
            raise InvalidLineage()

    @staticmethod
    def _validate_match_output(
        output: SegmentMatchOutput,
        source_segments: Sequence[Segment],
        target_segments: Sequence[Segment],
    ) -> None:
        source_by_id = {s.id: s for s in source_segments}
        target_by_id = {s.id: s for s in target_segments}
        used_source: set[str] = set()
        used_target: set[str] = set()
        group_keys: set[str] = set()
        for group in output.groups:
            src = [s.id for s in group.source_segments]
            tgt = [s.id for s in group.target_segments]
            if (
                not src
                or not tgt
                or group.group_key in group_keys
                or any(i not in source_by_id for i in src)
                or any(i not in target_by_id for i in tgt)
            ):
                raise AlignmentFailed("invalid_adapter_output")
            if (
                len(set(src)) != len(src)
                or len(set(tgt)) != len(tgt)
                or set(src) & used_source
                or set(tgt) & used_target
            ):
                raise AlignmentFailed("invalid_adapter_output")
            if any(
                source_by_id[i] != s for i, s in zip(src, group.source_segments, strict=True)
            ) or any(target_by_id[i] != s for i, s in zip(tgt, group.target_segments, strict=True)):
                raise AlignmentFailed("invalid_adapter_output")
            if len(group.group_key) != 64 or any(
                c not in "0123456789abcdef" for c in group.group_key
            ):
                raise AlignmentFailed("invalid_adapter_output")
            if group.reason is not None and group.reason != PARTIAL_COVERAGE:
                raise AlignmentFailed("invalid_adapter_output")
            group_keys.add(group.group_key)
            used_source.update(src)
            used_target.update(tgt)
        unmatched_ids: set[str] = set()
        for segment_id, reason in output.unmatched:
            if (
                (segment_id not in source_by_id and segment_id not in target_by_id)
                or segment_id in unmatched_ids
                or reason not in UNMATCHED_REASONS
            ):
                raise AlignmentFailed("invalid_adapter_output")
            unmatched_ids.add(segment_id)
        if used_source & unmatched_ids or used_target & unmatched_ids:
            raise AlignmentFailed("invalid_adapter_output")
        if (set(source_by_id) - used_source) != (unmatched_ids & set(source_by_id)) or (
            set(target_by_id) - used_target
        ) != (unmatched_ids & set(target_by_id)):
            raise AlignmentFailed("invalid_adapter_output")

    def _summary(self, run: ProcessingRun, reused: bool) -> SegmentAlignmentSummary:
        rows = self.ctx.repo.list_segment_alignments_for_run(run.id)
        report = next(
            (
                self.ctx.repo.get_artifact(oid)
                for oid, role in self.ctx.repo.list_run_io(run.id)
                if role is RunIoRole.OUTPUT
                and self.ctx.repo.entity_type_of(oid) is EntityType.ARTIFACT
            ),
            None,
        )
        counts = {"unmatched_source": 0, "unmatched_target": 0}
        if report is not None:
            payload = json.loads(self.ctx.artifact_store.read_bytes(report.sha256))
            counts = payload["totals"]
        return SegmentAlignmentSummary(
            run,
            len(rows),
            int(counts["unmatched_source"]),
            int(counts["unmatched_target"]),
            report,
            reused,
        )

    def _validate_authorization(
        self, predecessor: SegmentAlignment, artifact_id: str, status: str
    ) -> tuple[Artifact, ProcessingRun, dict[str, object]]:
        try:
            artifact = self.ctx.repo.get_artifact(artifact_id)
            run = self.ctx.repo.get_run(artifact.run_id)
            payload = json.loads(self.ctx.artifact_store.read_bytes(artifact.sha256))
            members = payload["member_ids"]
            expected = sorted((*predecessor.source_segment_ids, *predecessor.target_segment_ids))
            occurred = datetime.fromisoformat(payload["occurred_at"])
            valid = (
                artifact.kind is ArtifactKind.OTHER
                and artifact.media_type == "application/json"
                and artifact.schema_name == _AUTH_SCHEMA
                and artifact.schema_version == 1
                and run.status is RunStatus.SUCCEEDED
                and run.tool_name in self.trusted_importers
                and payload["schema"] == _AUTH_SCHEMA
                and payload["schema_version"] == 1
                and payload["predecessor_id"] == predecessor.id
                and isinstance(members, list)
                and members == expected
                and payload["actor"] == self.ctx.actor
                and payload["disposition"] == status
                and payload["basis_kind"] in {"authorized_reviewer", "editorial_decision"}
                and isinstance(payload["issuer_authority"], str)
                and bool(payload["issuer_authority"])
                and occurred.utcoffset() == timedelta(0)
                and (artifact.id, RunIoRole.OUTPUT) in self.ctx.repo.list_run_io(run.id)
                and (predecessor.id, RunIoRole.INPUT) in self.ctx.repo.list_run_io(run.id)
                and any(
                    edge.to_id == predecessor.id
                    and edge.kind is LineageKind.DERIVED_FROM
                    and edge.run_id == run.id
                    for edge in self.ctx.repo.list_lineage_edges(artifact.id, "out")
                )
            )
            if not valid:
                raise ValueError
            return artifact, run, payload
        except Exception:
            raise AlignmentFailed("authorization_invalid") from None

    def _require_human_review(self, source_ids: Sequence[str]) -> None:
        for source_id in source_ids:
            source = self.ctx.repo.get_source(source_id)
            decision = effective_decision(self.ctx.repo, source_id, Operation.HUMAN_REVIEW)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                if decision is PolicyDecision.ALLOW:
                    decision = PolicyDecision.DENY
                with self.ctx.repo.transaction():
                    self.ctx.repo.add_audit_event(
                        AuditEvent(
                            id=self.ctx.new_id(IdPrefix.AUDIT),
                            event_type=AuditEventType.POLICY_DENIED,
                            actor=self.ctx.actor,
                            subject_id=source_id,
                            run_id=None,
                            details={
                                "operation": Operation.HUMAN_REVIEW.value,
                                "decision": decision.value,
                            },
                            occurred_at=self.ctx.clock(),
                        )
                    )
                raise PolicyDenied(source_id, Operation.HUMAN_REVIEW, decision)

    def _check_locked_sources(self, source_ids: Sequence[str]) -> None:
        """Repeat ALIGN checks while source rows are locked through publication."""
        for source_id in source_ids:
            source = self.ctx.repo.get_source(source_id)
            decision = effective_decision(self.ctx.repo, source_id, Operation.ALIGN)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                if source.status is SourceStatus.REVOKED and decision is PolicyDecision.ALLOW:
                    decision = PolicyDecision.DENY
                raise PolicyDenied(source_id, Operation.ALIGN, decision)

    def _check_locked_review(self, source_ids: Sequence[str]) -> None:
        for source_id in source_ids:
            source = self.ctx.repo.get_source(source_id)
            decision = effective_decision(self.ctx.repo, source_id, Operation.HUMAN_REVIEW)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                if source.status is SourceStatus.REVOKED and decision is PolicyDecision.ALLOW:
                    decision = PolicyDecision.DENY
                raise PolicyDenied(source_id, Operation.HUMAN_REVIEW, decision)

    def _record_denial(
        self, source_id: str, operation: Operation, decision: PolicyDecision
    ) -> None:
        with self.ctx.repo.transaction():
            self.ctx.repo.add_audit_event(
                AuditEvent(
                    id=self.ctx.new_id(IdPrefix.AUDIT),
                    event_type=AuditEventType.POLICY_DENIED,
                    actor=self.ctx.actor,
                    subject_id=source_id,
                    run_id=None,
                    details={"operation": operation.value, "decision": decision.value},
                    occurred_at=self.ctx.clock(),
                )
            )

    def _lineage(self, from_id: str, to_id: str, kind: LineageKind, run_id: str) -> None:
        self.ctx.repo.add_lineage_edge(
            LineageEdge(
                id=self.ctx.new_id(IdPrefix.LINEAGE),
                from_id=from_id,
                to_id=to_id,
                kind=kind,
                run_id=run_id,
                created_at=self.ctx.clock(),
            )
        )


def active_segment_alignments(
    repo: Repository, alignments: Sequence[SegmentAlignment]
) -> list[SegmentAlignment]:
    """Follow immutable supersedes edges, rejecting multiple active successors."""
    active: list[SegmentAlignment] = []
    for row in alignments:
        children = [
            repo.get_segment_alignment(edge.from_id)
            for edge in repo.list_lineage_edges(row.id, "in")
            if edge.kind is LineageKind.SUPERSEDES
        ]
        if len(children) > 1:
            raise AmbiguousInput(RunStage.SEGMENT_ALIGNMENT, len(children))
        if children:
            active.extend(active_segment_alignments(repo, children))
        else:
            active.append(row)
    # If the caller supplied both a predecessor and successor, keep only terminal evidence.
    superseded = {
        row.id
        for row in alignments
        if any(
            edge.kind is LineageKind.SUPERSEDES for edge in repo.list_lineage_edges(row.id, "in")
        )
    }
    unique = {row.id: row for row in active if row.id not in superseded}
    return sorted(unique.values(), key=lambda row: (row.group_key, row.id))
