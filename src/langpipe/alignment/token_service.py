"""Atomic Stage 5 token alignment service (WP3.9, ADR-0011 §5/§7)."""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from pydantic import JsonValue

from langpipe import __version__
from langpipe.alignment.base import AlignmentConfig, IndexLink, TokenAligner, TokenGroup
from langpipe.alignment.governance import ensure_alignment_allowed
from langpipe.alignment.registry import TOKEN_ALIGNERS, resolve_aligner
from langpipe.alignment.report import link_token_report, store_token_report, token_report_payload
from langpipe.alignment.segment_service import active_segment_alignments
from langpipe.alignment.symmetrization import symmetrize
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AlignmentDirection,
    AlignmentStatus,
    AuditEventType,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    Symmetrization,
    most_restrictive,
)
from langpipe.domain.errors import AlignmentFailed, InvalidLineage, PolicyDenied
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.alignment import TokenAlignmentEdge
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import TokenOccurrence
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.governance import effective_policy
from langpipe.governance.lineage_policy import effective_decision
from langpipe.ingestion.runs import RunRecorder
from langpipe.text.registry import VersionedRegistry

logger = logging.getLogger(__name__)
_TOOL = "langpipe.token-align"


@dataclass(frozen=True)
class TokenAlignmentSummary:
    run: ProcessingRun
    edges: int
    unaligned_source: int
    unaligned_target: int
    skipped_groups: int
    report: Artifact
    reused: bool


class TokenAlignmentService:
    def __init__(
        self, ctx: AppContext, *, aligners: VersionedRegistry[TokenAligner] | None = None
    ) -> None:
        self.ctx = ctx
        self.aligners = aligners if aligners is not None else TOKEN_ALIGNERS
        self.recorder = RunRecorder(ctx)

    def align(
        self,
        segment_run_id: str,
        *,
        source_tokenization_run_id: str,
        target_tokenization_run_id: str,
        method: str = "eflomal@0.1.0",
        config: AlignmentConfig,
    ) -> TokenAlignmentSummary:
        adapter = resolve_aligner(self.aligners, method)
        method_id = f"{adapter.name}@{adapter.version}"
        segment_run = self.ctx.repo.get_run(segment_run_id)
        if (
            segment_run.stage is not RunStage.SEGMENT_ALIGNMENT
            or segment_run.status is not RunStatus.SUCCEEDED
        ):
            raise InvalidLineage()
        alignments = self.ctx.repo.list_segment_alignments_for_run(segment_run_id)
        active = active_segment_alignments(self.ctx.repo, alignments)
        excluded = [
            row
            for row in active
            if row.status not in (AlignmentStatus.STRUCTURAL, AlignmentStatus.APPROVED)
        ]
        active = [
            row
            for row in active
            if row.status in (AlignmentStatus.STRUCTURAL, AlignmentStatus.APPROVED)
        ]
        sides_raw = segment_run.config.get("sides")
        if not isinstance(sides_raw, list) or len(sides_raw) != 2:
            raise InvalidLineage()
        sides: list[dict[str, JsonValue]] = []
        for side in sides_raw:
            if not isinstance(side, dict):
                raise InvalidLineage()
            sides.append(side)
        norm_0 = sides[0].get("normalization_run_id")
        norm_1 = sides[1].get("normalization_run_id")
        if not isinstance(norm_0, str) or not isinstance(norm_1, str):
            raise InvalidLineage()
        token_runs = [
            self._token_run(source_tokenization_run_id, norm_0),
            self._token_run(target_tokenization_run_id, norm_1),
        ]
        for side_index, member_ids in enumerate(
            (
                {i for row in active for i in row.source_segment_ids},
                {i for row in active for i in row.target_segment_ids},
            )
        ):
            selected_inputs = {
                object_id
                for object_id, role in self.ctx.repo.list_run_io(token_runs[side_index].id)
                if role is RunIoRole.INPUT
                and self.ctx.repo.entity_type_of(object_id) is EntityType.SEGMENT
            }
            if not member_ids <= selected_inputs:
                raise InvalidLineage()
        segment_ids = sorted(
            {i for row in active for i in (*row.source_segment_ids, *row.target_segment_ids)}
        )
        if segment_ids:
            governed_ids = segment_ids
        else:
            raw_source_ids = [side.get("source_id") for side in sides]
            if any(not isinstance(s_id, str) for s_id in raw_source_ids):
                raise InvalidLineage()
            governed_ids = [str(s_id) for s_id in raw_source_ids]
        sources = ensure_alignment_allowed(self.ctx, governed_ids)
        tokens_by_segment: dict[str, list[TokenOccurrence]] = {}
        all_tokens: list[TokenOccurrence] = []
        selected_ids: list[str] = []
        for side_dict, token_run in zip(sides, token_runs, strict=True):
            s_id = side_dict.get("source_id")
            n_id = side_dict.get("normalization_run_id")
            if not isinstance(s_id, str) or not isinstance(n_id, str):
                raise InvalidLineage()
            selected_ids.extend((s_id, n_id, token_run.id))
        for segment_id in segment_ids:
            token_run = (
                token_runs[0]
                if segment_id in {i for a in active for i in a.source_segment_ids}
                else token_runs[1]
            )
            tokens = [t for t in self.ctx.repo.list_tokens(segment_id) if t.run_id == token_run.id]
            tokens.sort(key=lambda item: item.ordinal)
            tokens_by_segment[segment_id] = tokens
            all_tokens.extend(tokens)
        sources = ensure_alignment_allowed(
            self.ctx, [*sources, *segment_ids, *(t.id for t in all_tokens)]
        )
        config_data: dict[str, JsonValue] = {
            "sides": [
                {**sides[0], "tokenization_run_id": source_tokenization_run_id},
                {**sides[1], "tokenization_run_id": target_tokenization_run_id},
            ],
            "segment_run_id": segment_run_id,
            "source_tokenization_run_id": source_tokenization_run_id,
            "target_tokenization_run_id": target_tokenization_run_id,
            "method": method_id,
            "symmetrization": config.symmetrization.value,
            "model": config.model,
            "threads": config.threads,
            "timeout_seconds": config.timeout_seconds,
            "random_seed": config.random_seed,
        }
        inputs = sorted(
            set(selected_ids)
            | {segment_run_id}
            | {r.id for r in active}
            | set(segment_ids)
            | {t.id for t in all_tokens}
        )
        # The existing recorder owns exact run identity; its key is also the concurrency key.
        digest = config_hash(config_data)
        request_key = ProcessingRun.compute_run_key(
            RunStage.TOKEN_ALIGNMENT, _TOOL, __version__, digest, inputs
        )
        with self.ctx.repo.alignment_lock(request_key):
            sources = ensure_alignment_allowed(
                self.ctx, [*sources, *segment_ids, *(t.id for t in all_tokens)]
            )
            reusable = self.recorder.find_reusable(
                RunStage.TOKEN_ALIGNMENT, _TOOL, config_data, inputs
            )
            if reusable is not None:
                try:
                    with self.ctx.repo.transaction():
                        self.ctx.repo.lock_sources(sources)
                        self._check_locked_sources(sources)
                except PolicyDenied as exc:
                    self._record_denial(exc)
                    raise
                return self._summary(reusable, True)
            run = self.recorder.start(RunStage.TOKEN_ALIGNMENT, _TOOL, config_data, inputs)
            token_groups: list[TokenGroup] = []
            source_maps: dict[str, tuple[TokenOccurrence, ...]] = {}
            target_maps: dict[str, tuple[TokenOccurrence, ...]] = {}
            report_groups: list[dict[str, object]] = []
            try:
                for alignment in active:
                    source_tokens = tuple(
                        t for sid in alignment.source_segment_ids for t in tokens_by_segment[sid]
                    )
                    target_tokens = tuple(
                        t for sid in alignment.target_segment_ids for t in tokens_by_segment[sid]
                    )
                    source_maps[alignment.id], target_maps[alignment.id] = (
                        source_tokens,
                        target_tokens,
                    )
                    token_groups.append(TokenGroup(alignment.id, source_tokens, target_tokens))
                nonempty = [g for g in token_groups if g.source_tokens and g.target_tokens]
                empty_ids = {
                    g.alignment_id
                    for g in token_groups
                    if not g.source_tokens or not g.target_tokens
                }
                output = adapter.align(nonempty, config)
                if len({g.alignment_id for g in output.groups}) != len(output.groups) or {
                    g.alignment_id for g in output.groups
                } != {g.alignment_id for g in nonempty}:
                    raise AlignmentFailed("invalid_adapter_output")
                edge_rows: list[TokenAlignmentEdge] = []
                edges_by_group: dict[str, list[TokenAlignmentEdge]] = {}
                out_by_id = {g.alignment_id: g for g in output.groups}
                for group in nonempty:
                    links = out_by_id[group.alignment_id]
                    src, tgt = source_maps[group.alignment_id], target_maps[group.alignment_id]
                    self._validate_links(links.forward, len(src), len(tgt))
                    self._validate_links(links.reverse, len(src), len(tgt))
                    sym = symmetrize(links.forward, links.reverse, config.symmetrization)
                    rows: list[TokenAlignmentEdge] = []
                    for direction, items, mode in (
                        (AlignmentDirection.FORWARD, links.forward, Symmetrization.NONE),
                        (AlignmentDirection.REVERSE, links.reverse, Symmetrization.NONE),
                        (AlignmentDirection.SYMMETRIZED, sym, config.symmetrization),
                    ):
                        for link in items:
                            rows.append(
                                TokenAlignmentEdge(
                                    id=self.ctx.new_id(IdPrefix.TOKEN_ALIGNMENT),
                                    segment_alignment_id=group.alignment_id,
                                    source_token_id=src[link.source_index].id,
                                    target_token_id=tgt[link.target_index].id,
                                    direction=direction,
                                    algorithm=method_id,
                                    score=link.score,
                                    raw_scores=dict(link.raw_scores),
                                    symmetrization=mode,
                                    run_id=run.id,
                                    created_at=self.ctx.clock(),
                                )
                            )
                    edges_by_group[group.alignment_id] = rows
                    edge_rows.extend(rows)
                backend = {
                    "version": output.backend.version,
                    "archive_sha256": output.backend.archive_sha256,
                    "options": dict(output.backend.options),
                    "seed_supported": output.backend.seed_supported,
                }
                # Adapter metadata is recursively constrained to scalar values and allowlisted keys.
                self._validate_metadata(backend)
                for group in token_groups:
                    rows = edges_by_group.get(group.alignment_id, [])
                    sym_pairs = {
                        (e.source_token_id, e.target_token_id)
                        for e in rows
                        if e.direction is AlignmentDirection.SYMMETRIZED
                    }
                    fwd = {
                        e.source_token_id for e in rows if e.direction is AlignmentDirection.FORWARD
                    }
                    rev = {
                        e.target_token_id for e in rows if e.direction is AlignmentDirection.REVERSE
                    }
                    linked_src = {sid for sid, _ in sym_pairs}
                    linked_tgt = {tid for _, tid in sym_pairs}
                    reason = "empty_token_side" if group.alignment_id in empty_ids else None
                    report_groups.append(
                        {
                            "alignment_id": group.alignment_id,
                            "source_segment_ids": list(
                                next(
                                    a.source_segment_ids
                                    for a in active
                                    if a.id == group.alignment_id
                                )
                            ),
                            "target_segment_ids": list(
                                next(
                                    a.target_segment_ids
                                    for a in active
                                    if a.id == group.alignment_id
                                )
                            ),
                            "status": next(
                                a.status.value for a in active if a.id == group.alignment_id
                            ),
                            "source_token_ids": [t.id for t in group.source_tokens],
                            "target_token_ids": [t.id for t in group.target_tokens],
                            "index_pairs": {
                                "forward": [
                                    [i.source_index, i.target_index]
                                    for i in out_by_id[group.alignment_id].forward
                                ]
                                if reason is None
                                else [],
                                "reverse": [
                                    [i.source_index, i.target_index]
                                    for i in out_by_id[group.alignment_id].reverse
                                ]
                                if reason is None
                                else [],
                                "symmetrized": [list(pair) for pair in sorted(sym_pairs)],
                            },
                            "links": {
                                "forward": [
                                    {
                                        "source_index": item.source_index,
                                        "target_index": item.target_index,
                                        "score": item.score,
                                    }
                                    for item in out_by_id[group.alignment_id].forward
                                ]
                                if reason is None
                                else [],
                                "reverse": [
                                    {
                                        "source_index": item.source_index,
                                        "target_index": item.target_index,
                                        "score": item.score,
                                    }
                                    for item in out_by_id[group.alignment_id].reverse
                                ]
                                if reason is None
                                else [],
                            },
                            "counts": {
                                "forward": sum(
                                    e.direction is AlignmentDirection.FORWARD for e in rows
                                ),
                                "reverse": sum(
                                    e.direction is AlignmentDirection.REVERSE for e in rows
                                ),
                                "symmetrized": len(sym_pairs),
                            },
                            "score_reason": "score_unavailable",
                            "reason": reason,
                            "unaligned_source_ids": [
                                t.id
                                for t in group.source_tokens
                                if t.id
                                not in (
                                    fwd
                                    if config.symmetrization is Symmetrization.NONE
                                    else linked_src
                                )
                            ],
                            "unaligned_target_ids": [
                                t.id
                                for t in group.target_tokens
                                if t.id
                                not in (
                                    rev
                                    if config.symmetrization is Symmetrization.NONE
                                    else linked_tgt
                                )
                            ],
                            "unaligned_by_direction": {
                                "forward": {
                                    "source": [
                                        t.id
                                        for t in group.source_tokens
                                        if t.id
                                        not in {
                                            e.source_token_id
                                            for e in rows
                                            if e.direction is AlignmentDirection.FORWARD
                                        }
                                    ],
                                    "target": [
                                        t.id
                                        for t in group.target_tokens
                                        if t.id
                                        not in {
                                            e.target_token_id
                                            for e in rows
                                            if e.direction is AlignmentDirection.FORWARD
                                        }
                                    ],
                                },
                                "reverse": {
                                    "source": [
                                        t.id
                                        for t in group.source_tokens
                                        if t.id
                                        not in {
                                            e.source_token_id
                                            for e in rows
                                            if e.direction is AlignmentDirection.REVERSE
                                        }
                                    ],
                                    "target": [
                                        t.id
                                        for t in group.target_tokens
                                        if t.id
                                        not in {
                                            e.target_token_id
                                            for e in rows
                                            if e.direction is AlignmentDirection.REVERSE
                                        }
                                    ],
                                },
                                "symmetrized": {
                                    "source": [
                                        t.id for t in group.source_tokens if t.id not in linked_src
                                    ],
                                    "target": [
                                        t.id for t in group.target_tokens if t.id not in linked_tgt
                                    ],
                                },
                            },
                        }
                    )
                access = most_restrictive(
                    effective_policy(self.ctx.repo, s).access_class for s in sources
                )
                with self.ctx.repo.transaction():
                    self.ctx.repo.lock_sources(sources)
                    self._check_locked_sources(sources)
                    for edge in edge_rows:
                        self.ctx.repo.add_token_alignment_edge(edge)
                        for parent in (
                            edge.source_token_id,
                            edge.target_token_id,
                            edge.segment_alignment_id,
                        ):
                            self.ctx.repo.add_lineage_edge(
                                LineageEdge(
                                    id=self.ctx.new_id(IdPrefix.LINEAGE),
                                    from_id=edge.id,
                                    to_id=parent,
                                    kind=LineageKind.DERIVED_FROM,
                                    run_id=run.id,
                                    created_at=self.ctx.clock(),
                                )
                            )
                        self.ctx.repo.add_run_io(run.id, edge.id, RunIoRole.OUTPUT)
                    payload = token_report_payload(
                        run_id=run.id,
                        segment_run_id=segment_run_id,
                        source_tokenization_run_id=source_tokenization_run_id,
                        target_tokenization_run_id=target_tokenization_run_id,
                        method=method_id,
                        backend=backend,
                        groups=report_groups,
                        excluded_groups=[
                            {"alignment_id": row.id, "reason": "ineligible_status"}
                            for row in excluded
                        ],
                    )
                    report = store_token_report(
                        self.ctx, run=run, payload=payload, access_class=access
                    )
                    link_token_report(
                        self.ctx,
                        run=run,
                        report=report,
                        inputs=[
                            i
                            for i in inputs
                            if self.ctx.repo.entity_type_of(i) not in (EntityType.PROCESSING_RUN,)
                        ],
                        edges=edge_rows,
                    )
                    for object_id in inputs:
                        self.ctx.repo.add_run_io(run.id, object_id, RunIoRole.INPUT)
                    succeeded = self.recorder.succeed(run.id)
                return TokenAlignmentSummary(
                    succeeded,
                    len(edge_rows),
                    sum(
                        len(cast(list[str], item["unaligned_source_ids"])) for item in report_groups
                    ),
                    sum(
                        len(cast(list[str], item["unaligned_target_ids"])) for item in report_groups
                    ),
                    len(empty_ids),
                    report,
                    False,
                )
            except BaseException as exc:
                if isinstance(exc, PolicyDenied):
                    self._record_denial(exc)
                self.recorder.fail(run.id, exc)
                raise

    def _token_run(self, run_id: str, normalization_id: str) -> ProcessingRun:
        run = self.ctx.repo.get_run(run_id)
        if run.stage is not RunStage.TOKENIZATION or run.status is not RunStatus.SUCCEEDED:
            raise InvalidLineage()
        selected = [
            self.ctx.repo.get_segment(i)
            for i, role in self.ctx.repo.list_run_io(run.id)
            if role is RunIoRole.INPUT and self.ctx.repo.entity_type_of(i) is EntityType.SEGMENT
        ]
        if not selected or any(item.run_id != normalization_id for item in selected):
            raise InvalidLineage()
        return run

    @staticmethod
    def _validate_links(links: Sequence[IndexLink], source_count: int, target_count: int) -> None:
        seen = set()
        for link in links:
            pair = (link.source_index, link.target_index)
            if (
                isinstance(link.source_index, bool)
                or isinstance(link.target_index, bool)
                or not 0 <= link.source_index < source_count
                or not 0 <= link.target_index < target_count
                or pair in seen
            ):
                raise AlignmentFailed("invalid_adapter_output")
            seen.add(pair)

    @staticmethod
    def _validate_metadata(value: Mapping[str, object]) -> None:
        allowed = {"version", "archive_sha256", "options", "seed_supported"}
        if set(value) - allowed or not isinstance(value.get("options"), Mapping):
            raise AlignmentFailed("invalid_adapter_output")
        version = value.get("version")
        archive = value.get("archive_sha256")
        if (
            not isinstance(version, str)
            or re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.]+)?", version) is None
        ):
            raise AlignmentFailed("invalid_adapter_output")
        if archive is not None and (
            not isinstance(archive, str) or re.fullmatch(r"[0-9a-f]{64}", archive) is None
        ):
            raise AlignmentFailed("invalid_adapter_output")
        if not isinstance(value.get("seed_supported"), bool):
            raise AlignmentFailed("invalid_adapter_output")
        allowed_options = {
            "model",
            "n_samplers",
            "threads",
            "omp_dynamic",
            "omp_max_active_levels",
            "timeout_seconds",
            "score_model",
            "random_seed",
            "randomness",
            "native_preprocessing",
            "scores",
        }
        options_val = value.get("options")
        if not isinstance(options_val, Mapping):
            raise AlignmentFailed("invalid_adapter_output")
        options: Mapping[str, object] = options_val
        if set(options) - allowed_options:
            raise AlignmentFailed("invalid_adapter_output")
        if options.get("randomness") not in (None, "stochastic_unseeded"):
            raise AlignmentFailed("invalid_adapter_output")
        if options.get("native_preprocessing") not in (None, "lowercase"):
            raise AlignmentFailed("invalid_adapter_output")
        if options.get("scores") not in (None, "score_unavailable"):
            raise AlignmentFailed("invalid_adapter_output")
        integer_options = {"model", "n_samplers", "threads", "omp_max_active_levels", "score_model"}
        bool_options = {"omp_dynamic"}
        numeric_options = {"timeout_seconds"}
        nullable_integer_options = {"random_seed"}
        for key, item in options.items():
            if key in {"randomness", "native_preprocessing", "scores"}:
                continue
            if key in integer_options and (not isinstance(item, int) or isinstance(item, bool)):
                raise AlignmentFailed("invalid_adapter_output")
            if key in bool_options and not isinstance(item, bool):
                raise AlignmentFailed("invalid_adapter_output")
            if key in numeric_options and (
                not isinstance(item, (int, float))
                or isinstance(item, bool)
                or not math.isfinite(item)
            ):
                raise AlignmentFailed("invalid_adapter_output")
            if (
                key in nullable_integer_options
                and item is not None
                and (not isinstance(item, int) or isinstance(item, bool))
            ):
                raise AlignmentFailed("invalid_adapter_output")

    def _check_locked_sources(self, sources: Sequence[str]) -> None:
        for source_id in sources:
            source = self.ctx.repo.get_source(source_id)
            decision = effective_decision(self.ctx.repo, source_id, Operation.ALIGN)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                if source.status is SourceStatus.REVOKED and decision is PolicyDecision.ALLOW:
                    decision = PolicyDecision.DENY
                raise PolicyDenied(source_id, Operation.ALIGN, decision)

    def _record_denial(self, exc: PolicyDenied) -> None:
        with self.ctx.repo.transaction():
            self.ctx.repo.add_audit_event(
                AuditEvent(
                    id=self.ctx.new_id(IdPrefix.AUDIT),
                    event_type=AuditEventType.POLICY_DENIED,
                    actor=self.ctx.actor,
                    subject_id=exc.source_id,
                    run_id=None,
                    details={"operation": exc.operation.value, "decision": exc.decision.value},
                    occurred_at=self.ctx.clock(),
                )
            )

    def _summary(self, run: ProcessingRun, reused: bool) -> TokenAlignmentSummary:
        edges = self.ctx.repo.list_token_alignment_edges_for_run(run.id)
        report = next(
            (
                self.ctx.repo.get_artifact(i)
                for i, role in self.ctx.repo.list_run_io(run.id)
                if role is RunIoRole.OUTPUT
                and self.ctx.repo.entity_type_of(i) is EntityType.ARTIFACT
            ),
            None,
        )
        if report is None:
            raise InvalidLineage()
        payload = json.loads(self.ctx.artifact_store.read_bytes(report.sha256))
        groups = payload["groups"]
        return TokenAlignmentSummary(
            run=run,
            edges=len(edges),
            unaligned_source=sum(len(group["unaligned_source_ids"]) for group in groups),
            unaligned_target=sum(len(group["unaligned_target_ids"]) for group in groups),
            skipped_groups=int(payload["totals"].get("skipped_groups", 0)),
            report=report,
            reused=reused,
        )
