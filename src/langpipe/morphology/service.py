"""Stage 7b/8 morphology service (WP5.9: M5-PLAN §6, Gate 38, ADR-0017).

Orchestrates Stage 7b IGT morphology assertion and Stage 8 morphology induction over
governed predecessor runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    AuditEventType,
    EntityType,
    LifecycleStatus,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    most_restrictive,
)
from langpipe.domain.errors import (
    AmbiguousInput,
    InvalidLineage,
    NotFound,
    PolicyDenied,
)
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.igt import IGTObservation
from langpipe.domain.models.morphology import (
    Allomorph,
    MorphAnalysis,
)
from langpipe.domain.models.observation import TokenOccurrence
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.governance import effective_policy
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.ingestion.runs import RunRecorder
from langpipe.languages.base import profile_identity
from langpipe.morphology.adapters.igt_assertion import IgtAssertionInducer
from langpipe.morphology.base import (
    MorphologyInductionInput,
    MorphologyInductionOutput,
    MorphologyInventory,
)
from langpipe.morphology.registry import get_morphology_inducer

logger = logging.getLogger(__name__)

REPORT_SCHEMA = "morphology-induction-report"
REPORT_SCHEMA_VERSION = 1

_ACCESS_RANK: dict[AccessClass, int] = {
    AccessClass.PUBLIC: 0,
    AccessClass.COMMUNITY: 1,
    AccessClass.RESTRICTED: 2,
    AccessClass.HIGHLY_RESTRICTED: 3,
}


@dataclass(frozen=True)
class MorphologyInductionResult:
    """One Stage 7b/8 morphology run result and report."""

    run: ProcessingRun
    reused: bool
    report: Artifact
    totals: dict[str, int]
    analysis_kind_counts: dict[str, int]
    abstention_counts: dict[str, int]
    status_counts: dict[str, int]
    words_mapped: int
    words_unmapped: dict[str, int]
    excluded_refs_count: int


def _most_restrictive_access(ctx: AppContext, sources: Sequence[str]) -> AccessClass:
    if not sources:
        return AccessClass.RESTRICTED
    return most_restrictive(effective_policy(ctx.repo, s).access_class for s in sources)


def _record_denial(ctx: AppContext, subject_id: str, decision: PolicyDecision) -> None:
    with ctx.repo.transaction():
        ctx.repo.add_audit_event(
            AuditEvent(
                id=ctx.new_id(IdPrefix.AUDIT),
                event_type=AuditEventType.POLICY_DENIED,
                actor=ctx.actor,
                subject_id=subject_id,
                run_id=None,
                details={
                    "operation": Operation.DISTILL_MORPHOLOGY.value,
                    "decision": decision.value,
                },
                occurred_at=ctx.clock(),
            )
        )


def _find_run_source_ids(ctx: AppContext, run_id: str, visited: set[str] | None = None) -> set[str]:
    """Recover the ancestor source IDs for a processing run."""
    if visited is None:
        visited = set()
    if run_id in visited:
        return set()
    visited.add(run_id)

    repo = ctx.repo
    sources: set[str] = set()

    # 1. Check IGT observations if stage is EXTRACTION
    if hasattr(repo, "list_igt_observations_for_run"):
        obs_list = repo.list_igt_observations_for_run(run_id)
        for obs in obs_list:
            if obs.source_id:
                sources.add(obs.source_id)
    if sources:
        return sources

    # 2. Check segments for run
    if hasattr(repo, "list_segments_for_run"):
        segs = repo.list_segments_for_run(run_id)
        for seg in segs:
            if seg.source_id:
                sources.add(seg.source_id)
    if sources:
        return sources

    # 3. Check run_io
    run = repo.get_run(run_id)
    for object_id, role in repo.list_run_io(run_id):
        etype = repo.entity_type_of(object_id)
        if etype is EntityType.SOURCE:
            sources.add(object_id)
        elif etype is EntityType.SOURCE_OBJECT:
            sources.add(repo.get_source_object(object_id).source_id)
        elif etype is EntityType.SEGMENT:
            sources.add(repo.get_segment(object_id).source_id)
        elif etype is EntityType.PROCESSING_RUN and role is RunIoRole.INPUT:
            sources.update(_find_run_source_ids(ctx, object_id, visited))

    if sources:
        return sources

    # 4. Check config references
    for key in (
        "extraction_run_id",
        "normalization_run_id",
        "tokenization_run_id",
        "igt_extract_run_id",
        "inventory_run_id",
    ):
        parent_run_id = run.config.get(key)
        if isinstance(parent_run_id, str):
            sources.update(_find_run_source_ids(ctx, parent_run_id, visited))

    return sources


def _ensure_morphology_allowed(ctx: AppContext, input_ids: Sequence[str]) -> tuple[str, ...]:
    """Check Operation.DISTILL_MORPHOLOGY over the full ancestry of inputs."""
    if not input_ids:
        raise InvalidLineage()
    repo = ctx.repo
    sources: set[str] = set()
    missing: list[str] = []
    for input_id in sorted(set(input_ids)):
        etype = repo.entity_type_of(input_id)
        if etype is EntityType.SOURCE:
            sources.add(input_id)
            continue
        if etype is EntityType.PROCESSING_RUN:
            run_sources = _find_run_source_ids(ctx, input_id)
            if not run_sources:
                missing.append(input_id)
            else:
                sources.update(run_sources)
            continue
        ancestors = set(ancestor_source_ids(repo, input_id))
        if not ancestors:
            missing.append(input_id)
        sources.update(ancestors)

    for input_id in missing:
        decision = PolicyDecision.DENY
        _record_denial(ctx, input_id, decision)
        raise PolicyDenied(input_id, Operation.DISTILL_MORPHOLOGY, decision)

    for source_id in sorted(sources):
        source = repo.get_source(source_id)
        decision = effective_decision(repo, source_id, Operation.DISTILL_MORPHOLOGY)
        if source.status is SourceStatus.REVOKED and decision is PolicyDecision.ALLOW:
            decision = PolicyDecision.DENY
        if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
            _record_denial(ctx, source_id, decision)
            raise PolicyDenied(source_id, Operation.DISTILL_MORPHOLOGY, decision)

    return tuple(sorted(sources))


def _verify_sources_allowed_locked(repo: Any, governing_sources: Sequence[str]) -> None:
    """Lock sources and verify DISTILL_MORPHOLOGY permission inside a transaction."""
    repo.lock_sources(governing_sources)
    for s_id in governing_sources:
        src = repo.get_source(s_id)
        dec = effective_decision(repo, s_id, Operation.DISTILL_MORPHOLOGY)
        if src.status is SourceStatus.REVOKED and dec is PolicyDecision.ALLOW:
            dec = PolicyDecision.DENY
        if src.status is SourceStatus.REVOKED or dec is not PolicyDecision.ALLOW:
            raise PolicyDenied(s_id, Operation.DISTILL_MORPHOLOGY, dec)


def _is_ancestor_run(
    repo: Any,
    descendant_run_id: str,
    ancestor_run_id: str,
    visited: set[str] | None = None,
) -> bool:
    """Traverse run lineage/config/run_io to check whether descendant descends from ancestor."""
    if descendant_run_id == ancestor_run_id:
        return True
    if visited is None:
        visited = set()
    if descendant_run_id in visited:
        return False
    visited.add(descendant_run_id)

    run = repo.get_run(descendant_run_id)
    if run is None:
        return False

    # 1. Config references
    for key in (
        "extraction_run_id",
        "normalization_run_id",
        "tokenization_run_id",
        "igt_extract_run_id",
        "inventory_run_id",
    ):
        parent_id = run.config.get(key)
        if isinstance(parent_id, str) and (
            parent_id == ancestor_run_id
            or _is_ancestor_run(repo, parent_id, ancestor_run_id, visited)
        ):
            return True
    input_run_ids = run.config.get("input_run_ids")
    if isinstance(input_run_ids, list):
        for parent_id in input_run_ids:
            if isinstance(parent_id, str) and (
                parent_id == ancestor_run_id
                or _is_ancestor_run(repo, parent_id, ancestor_run_id, visited)
            ):
                return True

    # 2. Lineage edges
    for edge in repo.list_lineage_edges(descendant_run_id, direction="out"):
        if edge.to_id == ancestor_run_id:
            return True
        if (
            edge.kind in (LineageKind.DERIVED_FROM, LineageKind.NORMALIZED_FROM)
            and repo.entity_type_of(edge.to_id) is EntityType.PROCESSING_RUN
            and _is_ancestor_run(repo, edge.to_id, ancestor_run_id, visited)
        ):
            return True

    # 3. Run IO inputs
    for obj_id, role in repo.list_run_io(descendant_run_id):
        if role is RunIoRole.INPUT:
            if obj_id == ancestor_run_id:
                return True
            etype = repo.entity_type_of(obj_id)
            if etype is EntityType.PROCESSING_RUN:
                if _is_ancestor_run(repo, obj_id, ancestor_run_id, visited):
                    return True
            elif etype is EntityType.SEGMENT:
                seg = repo.get_segment(obj_id)
                if seg and (
                    seg.run_id == ancestor_run_id
                    or _is_ancestor_run(repo, seg.run_id, ancestor_run_id, visited)
                ):
                    return True

    return False


class MorphologyService:
    """Orchestrates Stage 7b and Stage 8 morphology operations."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.recorder = RunRecorder(ctx)

    def assert_igt(
        self,
        tokenization_run_id: str,
        igt_extract_run_id: str,
        *,
        exclude_refs: Sequence[str] = (),
        language: str | None = None,
        contact_language: str | None = None,
        profile: Any | None = None,
    ) -> MorphologyInductionResult:
        """Stage 7b: Assert morphology hypotheses from IGT observations on mapped tokens."""
        repo = self.ctx.repo

        tok_run = repo.get_run(tokenization_run_id)
        igt_run = repo.get_run(igt_extract_run_id)
        if tok_run.status is not RunStatus.SUCCEEDED or igt_run.status is not RunStatus.SUCCEEDED:
            raise InvalidLineage()

        if not _is_ancestor_run(repo, tokenization_run_id, igt_extract_run_id):
            raise InvalidLineage()

        # Governance gate: Operation.DISTILL_MORPHOLOGY
        input_ids = [igt_extract_run_id, tokenization_run_id]
        governing_sources = _ensure_morphology_allowed(self.ctx, input_ids)

        all_obs = repo.list_igt_observations_for_run(igt_extract_run_id)
        raw_seg_ids = {obs.segment_id for obs in all_obs if obs.segment_id is not None}

        # Check line of ancestry from tokens or run lineage
        tokens_by_raw_seg: dict[str, list[TokenOccurrence]] = defaultdict(list)
        norm_to_raw: dict[str, str] = {}

        for raw_id in raw_seg_ids:
            # Normalized segments derived from this raw segment
            in_edges = repo.list_lineage_edges(raw_id, direction="in")
            for edge in in_edges:
                if edge.kind is LineageKind.NORMALIZED_FROM:
                    norm_to_raw[edge.from_id] = raw_id

        # Also find tokens
        found_any_tokens = False
        for norm_id, raw_id in norm_to_raw.items():
            toks = [t for t in repo.list_tokens(norm_id) if t.run_id == tokenization_run_id]
            if toks:
                tokens_by_raw_seg[raw_id].extend(toks)
                found_any_tokens = True

        # Check direct tokens on raw_seg_id as well
        if not found_any_tokens:
            for raw_id in raw_seg_ids:
                toks = [t for t in repo.list_tokens(raw_id) if t.run_id == tokenization_run_id]
                if toks:
                    tokens_by_raw_seg[raw_id].extend(toks)
                    found_any_tokens = True

        if not found_any_tokens and raw_seg_ids:
            raise InvalidLineage()

        # Flatten tokens for input
        input_tokens: list[TokenOccurrence] = []
        for _raw_id, toks in tokens_by_raw_seg.items():
            input_tokens.extend(toks)

        # Precondition / language resolution before run creation
        lang = language or tok_run.config.get("language") or igt_run.config.get("language")
        if not lang:
            token_languages = {repo.get_segment(t.segment_id).language for t in input_tokens}
            if len(token_languages) == 1:
                lang = next(iter(token_languages))
            elif len(token_languages) > 1:
                raise AmbiguousInput(RunStage.IGT_IMPORT, len(token_languages))
            else:
                src = repo.get_source(governing_sources[0])
                if len(src.languages) > 1:
                    raise AmbiguousInput(RunStage.IGT_IMPORT, len(src.languages))
                lang = src.languages[0]

        profile_ref = profile_identity(profile, str(lang))

        # Idempotence check with pinned language and profile
        sorted_excludes = tuple(sorted(set(exclude_refs)))
        config: dict[str, Any] = {
            "method": "igt_assertion@0.1.0",
            "tokenization_run_id": tokenization_run_id,
            "igt_extract_run_id": igt_extract_run_id,
            "exclude_refs": list(sorted_excludes),
            "language": str(lang),
            "contact_language": contact_language,
            "profile": profile_ref,
        }

        reusable = self.recorder.find_reusable(
            RunStage.IGT_IMPORT, "langpipe.igt-assert", config, input_ids
        )
        if reusable is not None:
            try:
                with repo.transaction():
                    _verify_sources_allowed_locked(repo, governing_sources)
            except PolicyDenied as error:
                _record_denial(self.ctx, error.source_id, error.decision)
                raise
            return self._build_result_from_reusable(reusable)

        # Start execution
        run = self.recorder.start(RunStage.IGT_IMPORT, "langpipe.igt-assert", config, input_ids)
        run_committed = False

        try:
            active_obs: list[IGTObservation] = []
            excluded_count = 0
            for obs in all_obs:
                if (
                    (obs.record_ref is not None and obs.record_ref in sorted_excludes)
                    or str(obs.record_ordinal) in sorted_excludes
                    or obs.id in sorted_excludes
                ):
                    excluded_count += 1
                else:
                    active_obs.append(obs)

            adapter_input = MorphologyInductionInput(
                run_id=run.id,
                language=str(lang),
                tokens=input_tokens,
                profile=profile,
                observations=active_obs,
                contact_language=contact_language,
                segment_ancestors=norm_to_raw,
            )

            inducer = IgtAssertionInducer(self.ctx.new_id)
            output = inducer.induce(adapter_input)

            # Persist everything in one transaction
            with repo.transaction():
                _verify_sources_allowed_locked(repo, governing_sources)

                # Persist features with deduplication
                feat_id_map: dict[str, str] = {}
                features_created = 0
                features_reused = 0
                for feat in output.features:
                    existing = repo.get_feature_by_label(feat.namespace, feat.label)
                    if existing is not None:
                        feat_id_map[feat.id] = existing.id
                        features_reused += 1
                    else:
                        repo.add_feature(feat)
                        feat_id_map[feat.id] = feat.id
                        features_created += 1

                # Persist morphemes
                for m in output.morphemes:
                    repo.add_morpheme(m)
                    repo.add_run_io(run.id, m.id, RunIoRole.OUTPUT)

                # Persist allomorphs
                for a in output.allomorphs:
                    repo.add_allomorph(a)
                    repo.add_run_io(run.id, a.id, RunIoRole.OUTPUT)

                # Persist analyses and segments
                boundary_marks = (
                    tuple(profile.boundary_marks)
                    if profile and hasattr(profile, "boundary_marks")
                    else ("-", "=")
                )
                for cand in output.analyses:
                    updated_features = [
                        f.model_copy(
                            update={"feature_id": feat_id_map.get(f.feature_id, f.feature_id)}
                        )
                        for f in cand.features
                    ]
                    repo.add_morph_analysis(
                        cand.analysis,
                        cand.segments,
                        updated_features,
                        boundary_marks=boundary_marks,
                    )
                    repo.add_run_io(run.id, cand.analysis.id, RunIoRole.OUTPUT)

                # Persist evidence
                for evi in output.evidence_items:
                    repo.add_evidence(evi)

                # Persist lineage
                now = self.ctx.clock()
                for edge in output.lineage_edges:
                    repo.add_lineage_edge(edge)

                for parent_run_id in input_ids:
                    repo.add_lineage_edge(
                        LineageEdge(
                            id=self.ctx.new_id(IdPrefix.LINEAGE),
                            from_id=run.id,
                            to_id=parent_run_id,
                            kind=LineageKind.DERIVED_FROM,
                            run_id=run.id,
                            created_at=now,
                        )
                    )
                    repo.add_run_io(run.id, parent_run_id, RunIoRole.INPUT)

                # Report artifact
                access_class = _most_restrictive_access(self.ctx, governing_sources)
                report = self._create_report(
                    run=run,
                    method="igt_assertion@0.1.0",
                    input_run_ids=input_ids,
                    inventory_run_id=None,
                    language=str(lang),
                    output=output,
                    features_created=features_created,
                    features_reused=features_reused,
                    excluded_refs_count=excluded_count,
                    access_class=access_class,
                )

                run = self.recorder.succeed(run.id)
                result = self._result_from_output(
                    run=run,
                    reused=False,
                    report=report,
                    output=output,
                    input_run_ids=input_ids,
                    features_created=features_created,
                    features_reused=features_reused,
                    excluded_refs_count=excluded_count,
                )
            run_committed = True
            return result
        except PolicyDenied as error:
            if not run_committed:
                try:
                    persisted = self.ctx.repo.get_run(run.id)
                    if persisted.status is RunStatus.RUNNING:
                        self.recorder.fail(run.id, error)
                except Exception:
                    pass
            _record_denial(self.ctx, error.source_id, error.decision)
            raise
        except BaseException as error:
            if not run_committed:
                try:
                    persisted = self.ctx.repo.get_run(run.id)
                    if persisted.status is RunStatus.RUNNING:
                        self.recorder.fail(run.id, error)
                except Exception:
                    pass
            raise

    def induce(
        self,
        tokenization_run_id: str,
        method: str,
        *,
        inventory_run_id: str | None = None,
        language: str | None = None,
        profile: Any | None = None,
    ) -> MorphologyInductionResult:
        """Stage 8: Induce morphology candidate segmentations from token occurrences."""
        repo = self.ctx.repo

        tok_run = repo.get_run(tokenization_run_id)
        if tok_run.status is not RunStatus.SUCCEEDED:
            raise InvalidLineage()

        inducer = get_morphology_inducer(method)
        method_ref = f"{inducer.name}@{inducer.version}"

        input_ids = [tokenization_run_id]
        if inventory_run_id is not None:
            try:
                inv_run = repo.get_run(inventory_run_id)
            except NotFound:
                raise InvalidLineage() from None
            if inv_run.status is not RunStatus.SUCCEEDED:
                raise InvalidLineage()
            input_ids.append(inventory_run_id)

        governing_sources = _ensure_morphology_allowed(self.ctx, input_ids)

        # Retrieve all tokens from tokenization_run
        tokens: list[TokenOccurrence] = []
        for object_id, role in repo.list_run_io(tokenization_run_id):
            if role is RunIoRole.INPUT:
                toks = [t for t in repo.list_tokens(object_id) if t.run_id == tokenization_run_id]
                tokens.extend(toks)

        tokens.sort(key=lambda t: (t.segment_id, t.ordinal))

        # Retrieve inventory if provided
        inventory = None
        inventory_digest = None
        if inventory_run_id is not None:
            inv_morphemes = [
                m
                for m in repo.list_morphemes_for_run(inventory_run_id)
                if m.status not in (LifecycleStatus.REJECTED, LifecycleStatus.DEPRECATED)
            ]
            inv_allomorphs: list[Allomorph] = []
            inv_evidence: list[EvidenceItem] = []
            for m in inv_morphemes:
                inv_allomorphs.extend(
                    a
                    for a in repo.list_allomorphs_for_morpheme(m.id)
                    if a.run_id == inventory_run_id
                    and a.status not in (LifecycleStatus.REJECTED, LifecycleStatus.DEPRECATED)
                )
                inv_evidence.extend(
                    e for e in repo.list_evidence_for_target(m.id) if e.run_id == inventory_run_id
                )
            inv_analyses = repo.list_morph_analyses_for_run(inventory_run_id)
            surface_signatures: dict[str, list[str]] = defaultdict(list)
            for ana in inv_analyses:
                if ana.status in (LifecycleStatus.REJECTED, LifecycleStatus.DEPRECATED):
                    continue
                if ana.signature not in surface_signatures[ana.surface]:
                    surface_signatures[ana.surface].append(ana.signature)
            inventory = MorphologyInventory(
                run_id=inventory_run_id,
                morphemes=inv_morphemes,
                allomorphs=inv_allomorphs,
                evidence_items=inv_evidence,
                analyses=inv_analyses,
                surface_signatures=surface_signatures,
            )
            # Pin snapshot digest so mutable status changes invalidate rerun reuse
            inv_snapshot_str = "\n".join(
                [f"m:{m.id}:{m.status.value}" for m in sorted(inv_morphemes, key=lambda x: x.id)]
                + [f"a:{a.id}:{a.status.value}" for a in sorted(inv_allomorphs, key=lambda x: x.id)]
                + [
                    f"ana:{ana.id}:{ana.status.value}:{ana.signature}"
                    for ana in sorted(inv_analyses, key=lambda x: x.id)
                ]
            )
            inventory_digest = hashlib.sha256(inv_snapshot_str.encode("utf-8")).hexdigest()

        # Precondition / language resolution before run creation
        lang = language or tok_run.config.get("language")
        if not lang:
            token_languages = {repo.get_segment(t.segment_id).language for t in tokens}
            if len(token_languages) == 1:
                lang = next(iter(token_languages))
            elif len(token_languages) > 1:
                raise AmbiguousInput(RunStage.MORPHOLOGY_INDUCTION, len(token_languages))
            else:
                src = repo.get_source(governing_sources[0])
                if len(src.languages) > 1:
                    raise AmbiguousInput(RunStage.MORPHOLOGY_INDUCTION, len(src.languages))
                lang = src.languages[0]

        profile_ref = profile_identity(profile, str(lang))

        config: dict[str, Any] = {
            "method": method_ref,
            "tokenization_run_id": tokenization_run_id,
            "inventory_run_id": inventory_run_id,
            "inventory_digest": inventory_digest,
            "language": str(lang),
            "profile": profile_ref,
        }

        reusable = self.recorder.find_reusable(
            RunStage.MORPHOLOGY_INDUCTION, "langpipe.morph-induce", config, input_ids
        )
        if reusable is not None:
            try:
                with repo.transaction():
                    _verify_sources_allowed_locked(repo, governing_sources)
            except PolicyDenied as error:
                _record_denial(self.ctx, error.source_id, error.decision)
                raise
            return self._build_result_from_reusable(reusable)

        run = self.recorder.start(
            RunStage.MORPHOLOGY_INDUCTION, "langpipe.morph-induce", config, input_ids
        )
        run_committed = False

        try:
            adapter_input = MorphologyInductionInput(
                run_id=run.id,
                language=str(lang),
                tokens=tokens,
                profile=profile,
                inventory=inventory,
            )

            output = inducer.induce(adapter_input)

            with repo.transaction():
                _verify_sources_allowed_locked(repo, governing_sources)

                feat_id_map: dict[str, str] = {}
                features_created = 0
                features_reused = 0
                for feat in output.features:
                    existing = repo.get_feature_by_label(feat.namespace, feat.label)
                    if existing is not None:
                        feat_id_map[feat.id] = existing.id
                        features_reused += 1
                    else:
                        repo.add_feature(feat)
                        feat_id_map[feat.id] = feat.id
                        features_created += 1

                for m in output.morphemes:
                    repo.add_morpheme(m)
                    repo.add_run_io(run.id, m.id, RunIoRole.OUTPUT)

                for a in output.allomorphs:
                    repo.add_allomorph(a)
                    repo.add_run_io(run.id, a.id, RunIoRole.OUTPUT)

                boundary_marks = (
                    tuple(profile.boundary_marks)
                    if profile and hasattr(profile, "boundary_marks")
                    else ("-", "=")
                )
                for cand in output.analyses:
                    updated_features = [
                        f.model_copy(
                            update={"feature_id": feat_id_map.get(f.feature_id, f.feature_id)}
                        )
                        for f in cand.features
                    ]
                    repo.add_morph_analysis(
                        cand.analysis,
                        cand.segments,
                        updated_features,
                        boundary_marks=boundary_marks,
                    )
                    repo.add_run_io(run.id, cand.analysis.id, RunIoRole.OUTPUT)

                for evi in output.evidence_items:
                    repo.add_evidence(evi)

                now = self.ctx.clock()
                for edge in output.lineage_edges:
                    repo.add_lineage_edge(edge)

                for parent_run_id in input_ids:
                    repo.add_lineage_edge(
                        LineageEdge(
                            id=self.ctx.new_id(IdPrefix.LINEAGE),
                            from_id=run.id,
                            to_id=parent_run_id,
                            kind=LineageKind.DERIVED_FROM,
                            run_id=run.id,
                            created_at=now,
                        )
                    )
                    repo.add_run_io(run.id, parent_run_id, RunIoRole.INPUT)

                access_class = _most_restrictive_access(self.ctx, governing_sources)
                report = self._create_report(
                    run=run,
                    method=method_ref,
                    input_run_ids=input_ids,
                    inventory_run_id=inventory_run_id,
                    language=str(lang),
                    output=output,
                    features_created=features_created,
                    features_reused=features_reused,
                    excluded_refs_count=0,
                    access_class=access_class,
                )

                run = self.recorder.succeed(run.id)
                result = self._result_from_output(
                    run=run,
                    reused=False,
                    report=report,
                    output=output,
                    input_run_ids=input_ids,
                    features_created=features_created,
                    features_reused=features_reused,
                    excluded_refs_count=0,
                )
            run_committed = True
            return result
        except PolicyDenied as error:
            if not run_committed:
                try:
                    persisted = self.ctx.repo.get_run(run.id)
                    if persisted.status is RunStatus.RUNNING:
                        self.recorder.fail(run.id, error)
                except Exception:
                    pass
            _record_denial(self.ctx, error.source_id, error.decision)
            raise
        except BaseException as error:
            if not run_committed:
                try:
                    persisted = self.ctx.repo.get_run(run.id)
                    if persisted.status is RunStatus.RUNNING:
                        self.recorder.fail(run.id, error)
                except Exception:
                    pass
            raise

    def list_analyses_for_token(self, token_id: str) -> list[MorphAnalysis]:
        """List all candidate analyses for one token occurrence."""
        return self.ctx.repo.list_morph_analyses_for_token(token_id)

    def _create_report(
        self,
        *,
        run: ProcessingRun,
        method: str,
        input_run_ids: Sequence[str],
        inventory_run_id: str | None,
        language: str,
        output: MorphologyInductionOutput,
        features_created: int,
        features_reused: int,
        excluded_refs_count: int,
        access_class: AccessClass,
    ) -> Artifact:
        status_counts = Counter(c.analysis.status.value for c in output.analyses)
        # Invariant 3: machine scoring never creates validated
        assert "validated" not in status_counts, "Invariant 3 violation: validated status in report"

        analysis_kind_counts = Counter(c.analysis.analysis_kind.value for c in output.analyses)
        abstention_counts = Counter(a.value for a in output.abstentions.values())

        payload = {
            "schema": REPORT_SCHEMA,
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": run.id,
            "method": method,
            "input_run_ids": list(input_run_ids),
            "inventory_run_id": inventory_run_id,
            "language": language,
            "totals": {
                "analyses": len(output.analyses),
                "segments": sum(len(c.segments) for c in output.analyses),
                "morphemes": len(output.morphemes),
                "allomorphs": len(output.allomorphs),
                "features_created": features_created,
                "features_reused": features_reused,
                "evidence_items": len(output.evidence_items),
                "lineage_edges": len(output.lineage_edges) + len(input_run_ids),
            },
            "analysis_kind_counts": dict(analysis_kind_counts),
            "abstention_counts": dict(abstention_counts),
            "status_counts": dict(status_counts),
            "words_mapped": output.words_mapped,
            "words_unmapped": dict(output.words_unmapped),
            "excluded_refs_count": excluded_refs_count,
        }

        stored = self.ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
        artifact = Artifact(
            id=self.ctx.new_id(IdPrefix.ARTIFACT),
            run_id=run.id,
            kind=ArtifactKind.OTHER,
            media_type="application/json",
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            access_class=access_class,
            schema_name=REPORT_SCHEMA,
            schema_version=REPORT_SCHEMA_VERSION,
            created_at=self.ctx.clock(),
        )
        self.ctx.repo.add_artifact(artifact)
        self.ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)

        now = self.ctx.clock()
        for parent_id in input_run_ids:
            self.ctx.repo.add_lineage_edge(
                LineageEdge(
                    id=self.ctx.new_id(IdPrefix.LINEAGE),
                    from_id=artifact.id,
                    to_id=parent_id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=run.id,
                    created_at=now,
                )
            )
        return artifact

    def _result_from_output(
        self,
        *,
        run: ProcessingRun,
        reused: bool,
        report: Artifact,
        output: MorphologyInductionOutput,
        input_run_ids: Sequence[str] = (),
        features_created: int,
        features_reused: int,
        excluded_refs_count: int,
    ) -> MorphologyInductionResult:
        totals = {
            "analyses": len(output.analyses),
            "segments": sum(len(c.segments) for c in output.analyses),
            "morphemes": len(output.morphemes),
            "allomorphs": len(output.allomorphs),
            "features_created": features_created,
            "features_reused": features_reused,
            "evidence_items": len(output.evidence_items),
            "lineage_edges": len(output.lineage_edges) + len(input_run_ids),
        }
        return MorphologyInductionResult(
            run=run,
            reused=reused,
            report=report,
            totals=totals,
            analysis_kind_counts=dict(
                Counter(c.analysis.analysis_kind.value for c in output.analyses)
            ),
            abstention_counts=dict(Counter(a.value for a in output.abstentions.values())),
            status_counts=dict(Counter(c.analysis.status.value for c in output.analyses)),
            words_mapped=output.words_mapped,
            words_unmapped=dict(output.words_unmapped),
            excluded_refs_count=excluded_refs_count,
        )

    def _build_result_from_reusable(self, run: ProcessingRun) -> MorphologyInductionResult:
        repo = self.ctx.repo
        report: Artifact | None = None
        for object_id, role in repo.list_run_io(run.id):
            if role is RunIoRole.OUTPUT and repo.entity_type_of(object_id) is EntityType.ARTIFACT:
                art = repo.get_artifact(object_id)
                if art.schema_name == REPORT_SCHEMA:
                    report = art
                    break
        if report is None:
            raise InvalidLineage()

        report_bytes = self.ctx.artifact_store.read_bytes(report.sha256)
        data = json.loads(report_bytes.decode("utf-8"))

        return MorphologyInductionResult(
            run=run,
            reused=True,
            report=report,
            totals=data.get("totals", {}),
            analysis_kind_counts=data.get("analysis_kind_counts", {}),
            abstention_counts=data.get("abstention_counts", {}),
            status_counts=data.get("status_counts", {}),
            words_mapped=data.get("words_mapped", 0),
            words_unmapped=data.get("words_unmapped", {}),
            excluded_refs_count=data.get("excluded_refs_count", 0),
        )


def assert_igt(
    ctx: AppContext,
    tokenization_run_id: str,
    igt_extract_run_id: str,
    *,
    exclude_refs: Sequence[str] = (),
    language: str | None = None,
    contact_language: str | None = None,
    profile: Any | None = None,
) -> MorphologyInductionResult:
    """Convenience helper for assert_igt."""
    return MorphologyService(ctx).assert_igt(
        tokenization_run_id=tokenization_run_id,
        igt_extract_run_id=igt_extract_run_id,
        exclude_refs=exclude_refs,
        language=language,
        contact_language=contact_language,
        profile=profile,
    )


def induce_morphology(
    ctx: AppContext,
    tokenization_run_id: str,
    method: str,
    *,
    inventory_run_id: str | None = None,
    language: str | None = None,
    profile: Any | None = None,
) -> MorphologyInductionResult:
    """Convenience helper for induce."""
    return MorphologyService(ctx).induce(
        tokenization_run_id=tokenization_run_id,
        method=method,
        inventory_run_id=inventory_run_id,
        language=language,
        profile=profile,
    )


__all__ = [
    "MorphologyInductionResult",
    "MorphologyService",
    "REPORT_SCHEMA",
    "REPORT_SCHEMA_VERSION",
    "assert_igt",
    "induce_morphology",
]
