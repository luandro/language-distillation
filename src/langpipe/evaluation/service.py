"""Governed benchmark evaluation over frozen gold and persisted token edges."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from pydantic import ValidationError

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AlignmentDirection,
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
from langpipe.domain.errors import AlignmentFailed, InvalidLineage, PolicyDenied
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.alignment import SegmentAlignment
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import TokenOccurrence
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.evaluation.alignment import (
    AlignmentMetrics,
    GoldAlignment,
    GoldGroupLocatorSelector,
    GoldTokenSelector,
    evaluate_links,
)
from langpipe.governance import effective_policy
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.ingestion.runs import RunRecorder
from langpipe.storage.repository import Repository

REPORT_SCHEMA = "benchmark-report"


@dataclass(frozen=True)
class BenchmarkSummary:
    run: ProcessingRun
    metrics: AlignmentMetrics
    report: Artifact
    reused: bool


class BenchmarkService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.recorder = RunRecorder(ctx)

    def evaluate(
        self,
        token_run_id: str,
        gold_artifact_id: str,
        *,
        direction: AlignmentDirection = AlignmentDirection.SYMMETRIZED,
    ) -> BenchmarkSummary:
        repo = self.ctx.repo
        token_run = repo.get_run(token_run_id)
        gold_artifact = repo.get_artifact(gold_artifact_id)
        if (
            token_run.stage is not RunStage.TOKEN_ALIGNMENT
            or token_run.status is not RunStatus.SUCCEEDED
        ):
            raise InvalidLineage()
        if (
            gold_artifact.kind is not ArtifactKind.ALIGNMENT_FILE
            or gold_artifact.schema_name != GoldAlignment.SCHEMA_NAME
            or gold_artifact.schema_version != GoldAlignment.SCHEMA_VERSION
        ):
            raise AlignmentFailed("invalid_gold")
        token_inputs = [i for i, role in repo.list_run_io(token_run_id) if role is RunIoRole.INPUT]
        sources = self._ensure_evaluation_allowed([*token_inputs, gold_artifact_id])
        try:
            gold = GoldAlignment.model_validate_json(
                self.ctx.artifact_store.read_bytes(gold_artifact.sha256)
            )
        except (ValidationError, ValueError, UnicodeDecodeError):
            raise AlignmentFailed("invalid_gold") from None
        predicted_edges = repo.list_token_alignment_edges_for_run(token_run_id)
        governed = [*token_inputs, gold_artifact_id, *(e.id for e in predicted_edges)]
        sources = self._ensure_evaluation_allowed(governed)
        run_config = token_run.config
        source_tokenization_id = run_config.get("source_tokenization_run_id")
        target_tokenization_id = run_config.get("target_tokenization_run_id")
        if not isinstance(source_tokenization_id, str) or not isinstance(
            target_tokenization_id, str
        ):
            raise InvalidLineage()
        segment_run_id = run_config.get("segment_run_id")
        if not isinstance(segment_run_id, str):
            raise InvalidLineage()
        groups_by_id = {g.id: g for g in repo.list_segment_alignments_for_run(segment_run_id)}
        chosen = [e for e in predicted_edges if e.direction is direction]
        pred_pairs = {
            (e.segment_alignment_id, e.source_token_id, e.target_token_id) for e in chosen
        }
        flattened: set[tuple[int, int]] = set()
        src_offset = tgt_offset = 0
        for gold_group in gold.groups:
            alignment_id = gold_group.group_id
            if gold_group.locator_selector is not None:
                matches = [
                    row
                    for row in groups_by_id.values()
                    if self._locator_selector_matches(gold_group.locator_selector, row, repo)
                ]
                if len(matches) != 1:
                    raise AlignmentFailed("invalid_gold")
                alignment_id = matches[0].id
            elif alignment_id is None and gold_group.group_key is not None:
                matches = [
                    row for row in groups_by_id.values() if row.group_key == gold_group.group_key
                ]
                if len(matches) != 1:
                    raise AlignmentFailed("invalid_gold")
                alignment_id = matches[0].id
            alignment = groups_by_id.get(alignment_id or "")
            if alignment is None:
                raise AlignmentFailed("invalid_gold")
            src_tokens = [
                t
                for sid in alignment.source_segment_ids
                for t in repo.list_tokens(sid)
                if t.run_id == source_tokenization_id
            ]
            tgt_tokens = [
                t
                for sid in alignment.target_segment_ids
                for t in repo.list_tokens(sid)
                if t.run_id == target_tokenization_id
            ]
            src_tokens.sort(
                key=lambda t: (alignment.source_segment_ids.index(t.segment_id), t.ordinal)
            )
            tgt_tokens.sort(
                key=lambda t: (alignment.target_segment_ids.index(t.segment_id), t.ordinal)
            )
            if not self._selectors_match(
                gold_group.source_tokens, src_tokens, alignment.source_segment_ids
            ) or not self._selectors_match(
                gold_group.target_tokens, tgt_tokens, alignment.target_segment_ids
            ):
                raise AlignmentFailed("invalid_gold")
            src_segments = [repo.get_segment(sid) for sid in alignment.source_segment_ids]
            tgt_segments = [repo.get_segment(sid) for sid in alignment.target_segment_ids]
            if any(
                s.normalization_profile != gold_group.source_normalization_version
                for s in src_segments
            ) or any(
                s.normalization_profile != gold_group.target_normalization_version
                for s in tgt_segments
            ):
                raise AlignmentFailed("invalid_gold")
            if any(t.tokenizer != gold_group.source_tokenizer_version for t in src_tokens) or any(
                t.tokenizer != gold_group.target_tokenizer_version for t in tgt_tokens
            ):
                raise AlignmentFailed("invalid_gold")
            src_index = {t.id: i for i, t in enumerate(src_tokens)}
            tgt_index = {t.id: i for i, t in enumerate(tgt_tokens)}
            for edge_group, source_id, target_id in pred_pairs:
                if edge_group == alignment.id:
                    if source_id not in src_index or target_id not in tgt_index:
                        raise AlignmentFailed("invalid_gold")
                    flattened.add(
                        (src_offset + src_index[source_id], tgt_offset + tgt_index[target_id])
                    )
            src_offset += len(src_tokens)
            tgt_offset += len(tgt_tokens)
        metrics = evaluate_links(flattened, gold)
        config = {
            "token_run_id": token_run_id,
            "gold_artifact_id": gold_artifact_id,
            "direction": direction.value,
            "protocol": "transductive_unsupervised",
        }
        # Run I/O is not traversed by ancestor_source_ids. Keep the selected source-bearing
        # token-run inputs as direct report dependencies so empty edge sets retain prediction
        # ancestry. Use the same inputs for identity and persisted run I/O.
        inputs = sorted({token_run_id, gold_artifact_id, *(e.id for e in chosen), *token_inputs})
        reusable = self.recorder.find_reusable(
            RunStage.EVALUATION, "langpipe.benchmark", config, inputs
        )
        if reusable is not None:
            try:
                with repo.transaction():
                    repo.lock_sources(sources)
                    self._check_evaluation_sources(sources)
            except PolicyDenied as exc:
                self._record_denial(exc.source_id, exc.decision)
                raise
            report = self._report_for(reusable)
            return BenchmarkSummary(reusable, metrics, report, True)
        run = self.recorder.start(RunStage.EVALUATION, "langpipe.benchmark", config, inputs)
        try:
            access = most_restrictive(effective_policy(repo, s).access_class for s in sources)
            payload = {
                "schema": REPORT_SCHEMA,
                "schema_version": 1,
                "run_id": run.id,
                "protocol": "transductive_unsupervised",
                "direction": direction.value,
                "gold_split": sorted({g.split for g in gold.groups}),
                "metrics": asdict(metrics),
                "reasons": list(metrics.reasons),
            }
            stored = self.ctx.artifact_store.put_bytes(canonical_json(payload).encode())
            report = Artifact(
                id=self.ctx.new_id(IdPrefix.ARTIFACT),
                run_id=run.id,
                kind=ArtifactKind.BENCHMARK_REPORT,
                media_type="application/json",
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                access_class=access,
                schema_name=REPORT_SCHEMA,
                schema_version=1,
                created_at=self.ctx.clock(),
            )
            with repo.transaction():
                repo.lock_sources(sources)
                self._check_evaluation_sources(sources)
                repo.add_artifact(report)
                repo.add_run_io(run.id, report.id, RunIoRole.OUTPUT)
                for input_id in inputs:
                    repo.add_run_io(run.id, input_id, RunIoRole.INPUT)
                    repo.add_lineage_edge(
                        LineageEdge(
                            id=self.ctx.new_id(IdPrefix.LINEAGE),
                            from_id=report.id,
                            to_id=input_id,
                            kind=LineageKind.DERIVED_FROM,
                            run_id=run.id,
                            created_at=self.ctx.clock(),
                        )
                    )
                succeeded = self.recorder.succeed(run.id)
            return BenchmarkSummary(succeeded, metrics, report, False)
        except PolicyDenied as exc:
            self._record_denial(exc.source_id, exc.decision)
            self.recorder.fail(run.id, exc)
            raise
        except BaseException as exc:
            self.recorder.fail(run.id, exc)
            raise

    @staticmethod
    def _locator_selector_matches(
        selector: GoldGroupLocatorSelector, alignment: SegmentAlignment, repo: Repository
    ) -> bool:
        segment_run = repo.get_run(alignment.run_id)
        if segment_run.config.get("namespace") != selector.namespace:
            return False
        for segment_ids, expected_members in (
            (alignment.source_segment_ids, selector.source_members),
            (alignment.target_segment_ids, selector.target_members),
        ):
            if len(segment_ids) != len(expected_members):
                return False
            for segment_id, expected in zip(segment_ids, expected_members, strict=True):
                segment = repo.get_segment(segment_id)
                source_object = repo.get_source_object(segment.source_object_id)
                if (
                    source_object.original_path != expected.source_object_path
                    or segment.locator != expected.locator
                ):
                    return False
        return True

    @staticmethod
    def _selectors_match(
        selectors: tuple[GoldTokenSelector, ...],
        tokens: list[TokenOccurrence],
        member_ids: tuple[str, ...],
    ) -> bool:
        if len(selectors) != len(tokens):
            return False
        for selector, token in zip(selectors, tokens, strict=True):
            expected = (selector.member, selector.ordinal)
            actual = (member_ids.index(token.segment_id), token.ordinal)
            token_id = selector.token_id
            if expected != actual or (token_id is not None and token_id != token.id):
                return False
        return True

    def _ensure_evaluation_allowed(self, input_ids: list[str]) -> tuple[str, ...]:
        repo = self.ctx.repo
        sources: set[str] = set()
        for object_id in sorted(set(input_ids)):
            ancestors = set(ancestor_source_ids(repo, object_id))
            if repo.entity_type_of(object_id) is EntityType.SOURCE:
                ancestors.add(object_id)
            if not ancestors and repo.entity_type_of(object_id) is not EntityType.PROCESSING_RUN:
                raise InvalidLineage()
            sources.update(ancestors)
        for source_id in sorted(sources):
            source = repo.get_source(source_id)
            decision = effective_decision(repo, source_id, Operation.EVALUATION)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                if source.status is SourceStatus.REVOKED and decision is PolicyDecision.ALLOW:
                    decision = PolicyDecision.DENY
                self._record_denial(source_id, decision)
                raise PolicyDenied(source_id, Operation.EVALUATION, decision)
        return tuple(sorted(sources))

    def _record_denial(self, source_id: str, decision: PolicyDecision) -> None:
        with self.ctx.repo.transaction():
            self.ctx.repo.add_audit_event(
                AuditEvent(
                    id=self.ctx.new_id(IdPrefix.AUDIT),
                    event_type=AuditEventType.POLICY_DENIED,
                    actor=self.ctx.actor,
                    subject_id=source_id,
                    run_id=None,
                    details={
                        "operation": Operation.EVALUATION.value,
                        "decision": decision.value,
                    },
                    occurred_at=self.ctx.clock(),
                )
            )

    def _report_for(self, run: ProcessingRun) -> Artifact:
        for object_id, role in self.ctx.repo.list_run_io(run.id):
            if (
                role is RunIoRole.OUTPUT
                and self.ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT
            ):
                return self.ctx.repo.get_artifact(object_id)
        raise InvalidLineage()

    def _check_evaluation_sources(self, sources: tuple[str, ...]) -> None:
        for source_id in sources:
            source = self.ctx.repo.get_source(source_id)
            decision = effective_decision(self.ctx.repo, source_id, Operation.EVALUATION)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                if source.status is SourceStatus.REVOKED and decision is PolicyDecision.ALLOW:
                    decision = PolicyDecision.DENY
                raise PolicyDenied(source_id, Operation.EVALUATION, decision)
