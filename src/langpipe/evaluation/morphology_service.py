"""Governed morphology benchmark service (M5-PLAN §6 WP5.11, §7.10, ADR-0019).

Evaluates one or more morphology induction runs against frozen or derived MorphGold v1.
Refuses with `BenchmarkLeakage` if gold observations are lineage ancestors of the evaluated
inventory. Enforces `Operation.EVALUATION` on all ancestor sources.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    Abstention,
    AccessClass,
    ArtifactKind,
    AuditEventType,
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
    BenchmarkLeakage,
    InvalidLineage,
    NotFound,
    PolicyDenied,
)
from langpipe.domain.hashing import canonical_json, config_hash, sha256_bytes
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.igt import IGTObservation
from langpipe.domain.models.morphology import (
    MorphAnalysis,
    MorphGold,
    MorphSegment,
)
from langpipe.domain.models.observation import Segment
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.evaluation.morphology import (
    MorphologyMethodMetrics,
    evaluate_morphology,
    gold_from_igt,
)
from langpipe.governance import effective_policy
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.ingestion.runs import TOOL_VERSION, RunRecorder
from langpipe.morphology.word_mapping import map_words

REPORT_SCHEMA = "morphology-benchmark-report"
TOOL_NAME = "langpipe.morphology-benchmark"


def _matches_locator(seg_locator: Any, query_locator: Any) -> bool:
    if not seg_locator or not query_locator:
        return False
    if seg_locator == query_locator or str(seg_locator) == str(query_locator):
        return True
    if isinstance(seg_locator, dict) and isinstance(query_locator, dict):
        return bool(query_locator) and all(
            k in seg_locator and (seg_locator[k] == v or str(seg_locator[k]) == str(v))
            for k, v in query_locator.items()
        )
    return False


@dataclass(frozen=True)
class MorphologyBenchmarkSummary:
    run: ProcessingRun
    report: Artifact
    metrics: dict[str, MorphologyMethodMetrics]
    reused: bool


class MorphologyBenchmarkService:
    """Service evaluating morphology induction runs against gold fixtures."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.recorder = RunRecorder(ctx)

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

    def evaluate(
        self,
        evaluated_run_ids: Sequence[str],
        gold: MorphGold | str,
        refs: Sequence[str] = (),
        language: str | None = None,
    ) -> MorphologyBenchmarkSummary:
        repo = self.ctx.repo
        if not evaluated_run_ids:
            raise InvalidLineage()

        eval_runs: list[ProcessingRun] = []
        seen_methods: set[str] = set()
        for r_id in evaluated_run_ids:
            try:
                r = repo.get_run(r_id)
            except NotFound:
                raise InvalidLineage() from None
            if r.status is not RunStatus.SUCCEEDED:
                raise InvalidLineage()
            if r.stage not in (RunStage.MORPHOLOGY_INDUCTION, RunStage.IGT_IMPORT):
                raise InvalidLineage()
            method_name = str(r.config.get("method", r.tool_name))
            if method_name in seen_methods:
                raise InvalidLineage()
            seen_methods.add(method_name)
            eval_runs.append(r)

        # Deterministic evaluation and report ordering regardless of input order
        eval_runs.sort(key=lambda r: str(r.config.get("method", r.tool_name)))

        # Pre-flight candidate ancestor sources across eval_runs and gold
        candidate_sources: set[str] = set()
        for r_id in evaluated_run_ids:
            candidate_sources.update(ancestor_source_ids(repo, r_id))
            r_run = repo.get_run(r_id)
            t_run_id = r_run.config.get("tokenization_run_id")
            if t_run_id:
                for inp_id, role in repo.list_run_io(str(t_run_id)):
                    if role is RunIoRole.INPUT:
                        candidate_sources.update(ancestor_source_ids(repo, inp_id))
                        try:
                            seg = repo.get_segment(inp_id)
                            candidate_sources.add(seg.source_id)
                        except NotFound:
                            pass
            i_run_id = r_run.config.get("inventory_run_id")
            if i_run_id:
                candidate_sources.update(ancestor_source_ids(repo, str(i_run_id)))

        gold_model_pre: MorphGold | None = None
        if isinstance(gold, MorphGold):
            gold_model_pre = gold
        elif isinstance(gold, str) and (gold.endswith(".json") or Path(gold).is_file()):
            content = Path(gold).read_text(encoding="utf-8")
            gold_model_pre = MorphGold.model_validate(json.loads(content))
        else:
            # gold is igt_extract_run_id
            candidate_sources.update(ancestor_source_ids(repo, gold))
            for candidate_obs in repo.list_igt_observations_for_run(gold):
                candidate_sources.add(candidate_obs.source_id)

        if gold_model_pre is not None:
            prov_igt_run = gold_model_pre.provenance.get("igt_extract_run_id")
            if isinstance(prov_igt_run, str) and prov_igt_run:
                candidate_sources.update(ancestor_source_ids(repo, prov_igt_run))
                for candidate_obs in repo.list_igt_observations_for_run(prov_igt_run):
                    candidate_sources.add(candidate_obs.source_id)

            for it in gold_model_pre.items:
                sel = it.get("selector", {})
                if sel.get("source_key"):
                    src = repo.find_source_by_key(str(sel["source_key"]))
                    if src:
                        candidate_sources.add(src.id)
                obs_id = sel.get("observation_id")
                if obs_id:
                    try:
                        obs = repo.get_igt_observation(str(obs_id))
                        candidate_sources.add(obs.source_id)
                    except NotFound:
                        pass
                tgt_ref = sel.get("igt_ref")
                if tgt_ref:
                    tgt_ref_str = str(tgt_ref)
                    raw_id = (
                        tgt_ref_str[3:]
                        if tgt_ref_str.startswith("id:")
                        else (tgt_ref_str if not tgt_ref_str.startswith(("ref:", "ord:")) else None)
                    )
                    if raw_id:
                        try:
                            obs = repo.get_igt_observation(raw_id)
                            candidate_sources.add(obs.source_id)
                        except NotFound:
                            pass
                if isinstance(prov_igt_run, str) and prov_igt_run and tgt_ref:
                    run_obs = repo.list_igt_observations_for_run(prov_igt_run)
                    for candidate_obs in run_obs:
                        if candidate_obs.record_ref == tgt_ref or str(
                            candidate_obs.record_ordinal
                        ) == str(tgt_ref):
                            candidate_sources.add(candidate_obs.source_id)
                            break
                if "segment_locator" in sel:
                    seg_loc = sel["segment_locator"]
                    for r_id in evaluated_run_ids:
                        t_run_id = repo.get_run(r_id).config.get("tokenization_run_id")
                        if t_run_id:
                            for inp_id, role in repo.list_run_io(str(t_run_id)):
                                if role is RunIoRole.INPUT:
                                    try:
                                        s_candidate = repo.get_segment(inp_id)
                                        if _matches_locator(s_candidate.locator, seg_loc):
                                            candidate_sources.add(s_candidate.source_id)
                                    except NotFound:
                                        pass

        source_ids = sorted(candidate_sources)

        try:
            with repo.transaction():
                if source_ids:
                    repo.lock_sources(source_ids)
                    for s_id in source_ids:
                        curr_s = repo.get_source(s_id)
                        dec = effective_decision(repo, curr_s.id, Operation.EVALUATION)
                        if curr_s.status is SourceStatus.REVOKED or dec is not PolicyDecision.ALLOW:
                            if (
                                curr_s.status is SourceStatus.REVOKED
                                and dec is PolicyDecision.ALLOW
                            ):
                                dec = PolicyDecision.DENY
                            raise PolicyDenied(
                                source_id=curr_s.id, operation=Operation.EVALUATION, decision=dec
                            )

                # 1. Resolve gold under locked governance
                if gold_model_pre is not None:
                    gold_model = gold_model_pre
                else:
                    assert isinstance(gold, str)
                    gold_model = gold_from_igt(
                        repo, igt_extract_run_id=gold, refs=refs, language=language
                    )

                gold_digest = sha256_bytes(
                    canonical_json(
                        {
                            "gold_id": gold_model.gold_id,
                            "language": str(gold_model.language),
                            "items": [
                                it.model_dump() if hasattr(it, "model_dump") else it
                                for it in gold_model.items
                            ],
                            "provenance": gold_model.provenance,
                        }
                    ).encode("utf-8")
                )

                # 2. Leakage Guard (ADR-0019 Decision 2)
                # Check if any gold observation leaked into the evaluated run's inventory or inputs
                gold_obs_ids: set[str] = set()
                gold_source_refs: set[tuple[str, str | None, str, str]] = set()
                resolved_gold_obs_ids: dict[int, str] = {}
                for idx, it in enumerate(gold_model.items):
                    sel = it.selector if hasattr(it, "selector") else it.get("selector", {})
                    obs_id = None
                    igt_run_id = gold_model.provenance.get("igt_extract_run_id")
                    candidates: list[IGTObservation] = []
                    matching_loc_segs_by_id: dict[str, Segment] = {}

                    # 1. Deduplicate locator-matched segments across evaluated runs
                    if "segment_locator" in sel:
                        seg_loc = sel["segment_locator"]
                        for r in eval_runs:
                            t_run_id = r.config.get("tokenization_run_id")
                            if not t_run_id:
                                continue
                            for inp_id, role in repo.list_run_io(str(t_run_id)):
                                if role is RunIoRole.INPUT:
                                    try:
                                        s_candidate = repo.get_segment(inp_id)
                                    except NotFound:
                                        continue
                                    if _matches_locator(s_candidate.locator, seg_loc):
                                        matching_loc_segs_by_id[s_candidate.id] = s_candidate
                                        if s_candidate.source_id and isinstance(seg_loc, dict):
                                            raw_ref = (
                                                seg_loc.get("igt_ref")
                                                or seg_loc.get("record_ref")
                                                or seg_loc.get("ref")
                                            )
                                            if raw_ref is not None:
                                                gold_source_refs.add(
                                                    (
                                                        s_candidate.source_id,
                                                        s_candidate.source_object_id,
                                                        "ref",
                                                        str(raw_ref),
                                                    )
                                                )
                                            if seg_loc.get("record_ordinal") is not None:
                                                gold_source_refs.add(
                                                    (
                                                        s_candidate.source_id,
                                                        s_candidate.source_object_id,
                                                        "ord",
                                                        str(seg_loc["record_ordinal"]),
                                                    )
                                                )

                    # 1b. Collect potential locator-matched observations independently
                    # for leakage guard
                    if "segment_locator" in sel and matching_loc_segs_by_id:
                        for s in matching_loc_segs_by_id.values():
                            if s.source_object_id:
                                for c in repo.list_igt_observations_for_object(s.source_object_id):
                                    loc = s.locator
                                    if (
                                        c.segment_id == s.id
                                        or (
                                            isinstance(loc, dict)
                                            and c.record_ref
                                            and c.record_ref == loc.get("igt_ref")
                                        )
                                        or (
                                            isinstance(loc, dict)
                                            and str(c.record_ordinal)
                                            == str(loc.get("record_ordinal"))
                                        )
                                    ):
                                        gold_obs_ids.add(c.id)

                    # 1c. Collect candidate source IDs referenced by selector or evaluated runs
                    candidate_sids: set[str] = set()
                    for r in eval_runs:
                        t_run_id = r.config.get("tokenization_run_id")
                        if t_run_id:
                            for inp_id, role in repo.list_run_io(str(t_run_id)):
                                if role is RunIoRole.INPUT:
                                    try:
                                        seg = repo.get_segment(inp_id)
                                        candidate_sids.add(seg.source_id)
                                    except NotFound:
                                        pass
                        i_run_id = r.config.get("inventory_run_id")
                        if i_run_id:
                            for s_id in ancestor_source_ids(repo, str(i_run_id)):
                                candidate_sids.add(s_id)
                    if sel.get("source_key"):
                        src = repo.find_source_by_key(str(sel["source_key"]))
                        if src:
                            candidate_sids.add(src.id)
                    if isinstance(igt_run_id, str) and igt_run_id:
                        for s_id in ancestor_source_ids(repo, igt_run_id):
                            candidate_sids.add(s_id)
                    for s in matching_loc_segs_by_id.values():
                        if s.source_id:
                            candidate_sids.add(s.source_id)

                    obs_id_raw = sel.get("observation_id")
                    cand_single: IGTObservation | None = None
                    cand_id_obs: IGTObservation | None = None
                    if obs_id_raw:
                        gold_obs_ids.add(str(obs_id_raw))
                        try:
                            cand_single = repo.get_igt_observation(str(obs_id_raw))
                            candidate_sids.add(cand_single.source_id)
                            s_id = cand_single.source_id
                            o_id = cand_single.source_object_id
                            if cand_single.record_ref:
                                gold_source_refs.add(
                                    (s_id, o_id, "ref", str(cand_single.record_ref))
                                )
                            gold_source_refs.add(
                                (s_id, o_id, "ord", str(cand_single.record_ordinal))
                            )
                            gold_source_refs.add((s_id, o_id, "id", str(cand_single.id)))
                        except NotFound:
                            pass

                    igt_ref_raw = sel.get("igt_ref")
                    if igt_ref_raw:
                        tgt_ref_str = str(igt_ref_raw)
                        raw_id = (
                            tgt_ref_str[3:]
                            if tgt_ref_str.startswith("id:")
                            else (
                                tgt_ref_str
                                if not tgt_ref_str.startswith(("ref:", "ord:"))
                                else None
                            )
                        )
                        if raw_id:
                            try:
                                cand_id_obs = repo.get_igt_observation(raw_id)
                                gold_obs_ids.add(cand_id_obs.id)
                                candidate_sids.add(cand_id_obs.source_id)
                                s_id = cand_id_obs.source_id
                                o_id = cand_id_obs.source_object_id
                                if cand_id_obs.record_ref:
                                    gold_source_refs.add(
                                        (s_id, o_id, "ref", str(cand_id_obs.record_ref))
                                    )
                                gold_source_refs.add(
                                    (s_id, o_id, "ord", str(cand_id_obs.record_ordinal))
                                )
                                gold_source_refs.add((s_id, o_id, "id", str(cand_id_obs.id)))
                            except NotFound:
                                pass

                    identified_obj_id = (
                        cand_single.source_object_id
                        if cand_single is not None
                        else (cand_id_obs.source_object_id if cand_id_obs is not None else None)
                    )

                    # 1d. Independently collect all observations matching record constraints
                    # for leakage guard
                    for s_id in candidate_sids:
                        for obj in repo.list_source_objects(s_id):
                            if identified_obj_id is not None and obj.id != identified_obj_id:
                                continue
                            matching_obs = repo.list_igt_observations_for_object(obj.id)
                            if sel.get("record_ref"):
                                raw_val = str(sel["record_ref"])
                                for c in matching_obs:
                                    if c.record_ref == raw_val:
                                        gold_obs_ids.add(c.id)
                                        gold_source_refs.add((s_id, obj.id, "ref", raw_val))
                                if not matching_obs:
                                    gold_source_refs.add((s_id, obj.id, "ref", raw_val))
                            if sel.get("record_ordinal") is not None:
                                raw_ord = int(sel["record_ordinal"])
                                for c in matching_obs:
                                    if c.record_ordinal == raw_ord:
                                        gold_obs_ids.add(c.id)
                                        gold_source_refs.add((s_id, obj.id, "ord", str(raw_ord)))
                            if sel.get("igt_ref"):
                                raw_ref = str(sel["igt_ref"])
                                val = raw_ref
                                kind = "ref"
                                if raw_ref.startswith("ref:"):
                                    val = raw_ref[4:]
                                    kind = "ref"
                                elif raw_ref.startswith("ord:"):
                                    val = raw_ref[4:]
                                    kind = "ord"
                                elif raw_ref.startswith("id:"):
                                    val = raw_ref[3:]
                                    kind = "id"
                                elif (
                                    not sel.get("record_ref") and sel.get("record_ordinal") is None
                                ):
                                    if raw_ref.isdigit():
                                        raise ValueError(
                                            f"Ambiguous selector igt_ref='{raw_ref}' without "
                                            f"explicit kind cannot be resolved. "
                                            f"Specify 'ref:{raw_ref}' or 'ord:{raw_ref}'."
                                        )
                                for c in matching_obs:
                                    is_match = (
                                        (kind == "ref" and c.record_ref == val)
                                        or (kind == "ord" and str(c.record_ordinal) == val)
                                        or (kind == "id" and c.id == val)
                                    )
                                    if is_match:
                                        gold_obs_ids.add(c.id)
                                        gold_source_refs.add((s_id, obj.id, kind, val))

                    # 2. Establish initial observation pool for scoring intersection
                    tgt_ref_str = str(sel.get("igt_ref")) if sel.get("igt_ref") else ""
                    is_unprefixed_ref = bool(tgt_ref_str) and not tgt_ref_str.startswith(
                        ("ref:", "ord:", "id:")
                    )
                    if obs_id_raw:
                        candidates = [cand_single] if cand_single is not None else []
                    elif tgt_ref_str.startswith("id:"):
                        candidates = [cand_id_obs] if cand_id_obs is not None else []
                    elif is_unprefixed_ref:
                        # Unprefixed reference: populate candidate pool from all candidate
                        # sources (including evaluated runs, provenance run, observation source)
                        # so cross-namespace collision (ID vs record_ref vs ordinal) is checked
                        # across all applicable evaluated sources even when provenance is present.
                        pool_sids = set(candidate_sids)
                        if cand_id_obs is not None:
                            pool_sids.add(cand_id_obs.source_id)
                        if isinstance(igt_run_id, str) and igt_run_id:
                            candidates = list(repo.list_igt_observations_for_run(igt_run_id))
                        else:
                            candidates = []
                        seen_c_ids = {c.id for c in candidates}
                        for s_id in pool_sids:
                            for obj in repo.list_source_objects(s_id):
                                for c in repo.list_igt_observations_for_object(obj.id):
                                    if c.id not in seen_c_ids:
                                        seen_c_ids.add(c.id)
                                        candidates.append(c)
                    elif isinstance(igt_run_id, str) and igt_run_id:
                        candidates = repo.list_igt_observations_for_run(igt_run_id)
                    elif sel.get("source_key"):
                        src = repo.find_source_by_key(str(sel["source_key"]))
                        if src:
                            for obj in repo.list_source_objects(src.id):
                                candidates.extend(repo.list_igt_observations_for_object(obj.id))
                    elif cand_id_obs is not None:
                        # Unprefixed ID: populate pool from candidate and observation sources
                        # to enable cross-namespace collision check against record_ref and ordinal
                        for s_id in candidate_sids | {cand_id_obs.source_id}:
                            for obj in repo.list_source_objects(s_id):
                                candidates.extend(repo.list_igt_observations_for_object(obj.id))
                    elif "segment_locator" in sel and matching_loc_segs_by_id:
                        seen_loc_c_ids: set[str] = set()
                        for s in matching_loc_segs_by_id.values():
                            if s.source_object_id:
                                for c in repo.list_igt_observations_for_object(s.source_object_id):
                                    if c.id not in seen_loc_c_ids:
                                        seen_loc_c_ids.add(c.id)
                                        candidates.append(c)

                    # 3. Apply constraints sequentially (only narrowing, NEVER broadening!)
                    if sel.get("source_key"):
                        src = repo.find_source_by_key(str(sel["source_key"]))
                        candidates = [c for c in candidates if c.source_id == src.id] if src else []

                    if sel.get("record_ref"):
                        tgt_val = str(sel["record_ref"])
                        candidates = [c for c in candidates if c.record_ref == tgt_val]

                    if sel.get("record_ordinal") is not None:
                        tgt_ord = int(sel["record_ordinal"])
                        candidates = [c for c in candidates if c.record_ordinal == tgt_ord]

                    if sel.get("igt_ref"):
                        tgt_ref = str(sel["igt_ref"])
                        if tgt_ref.startswith("ref:"):
                            val = tgt_ref[4:]
                            candidates = [c for c in candidates if c.record_ref == val]
                        elif tgt_ref.startswith("ord:"):
                            val = tgt_ref[4:]
                            candidates = [c for c in candidates if str(c.record_ordinal) == val]
                        elif tgt_ref.startswith("id:"):
                            val = tgt_ref[3:]
                            candidates = [c for c in candidates if c.id == val]
                        else:
                            val = tgt_ref
                            ref_m = [c for c in candidates if c.record_ref == val]
                            ord_m = [c for c in candidates if str(c.record_ordinal) == val]
                            id_m = [c for c in candidates if c.id == val]
                            non_empty = [{c.id for c in m} for m in (ref_m, ord_m, id_m) if m]
                            if len(non_empty) > 1 and not all(
                                s == non_empty[0] for s in non_empty[1:]
                            ):
                                raise ValueError(
                                    f"Ambiguous selector igt_ref='{val}' matches multiple "
                                    f"record namespaces across different observations. "
                                    f"Disambiguate with 'ref:{val}' or 'ord:{val}'."
                                )
                            candidates = ref_m or ord_m or id_m

                    if "segment_locator" in sel:
                        seg_loc = sel["segment_locator"]
                        candidates = [
                            c
                            for c in candidates
                            if c.segment_id in matching_loc_segs_by_id
                            or (
                                c.record_ref
                                and isinstance(seg_loc, dict)
                                and c.record_ref == seg_loc.get("igt_ref")
                            )
                            or (
                                isinstance(seg_loc, dict)
                                and str(c.record_ordinal) == str(seg_loc.get("record_ordinal"))
                            )
                        ]

                    for c in candidates:
                        gold_obs_ids.add(c.id)

                    # If segment_locator had multiple matches, locator is ambiguous
                    is_ambiguous_locator = (
                        "segment_locator" in sel and len(matching_loc_segs_by_id) != 1
                    )

                    # 4. Require uniqueness for scoring resolution
                    if len(candidates) == 1 and not is_ambiguous_locator:
                        obs_id = candidates[0].id
                        resolved_gold_obs_ids[idx] = str(obs_id)

                for r in eval_runs:
                    # Check general lineage ancestry for gold observations
                    anc_ids = {a_id for a_id, _ in repo.ancestors(r.id)}
                    lineage_leaked = gold_obs_ids & anc_ids
                    if lineage_leaked:
                        leak_list = sorted(lineage_leaked)
                        raise BenchmarkLeakage(
                            f"gold observations {leak_list} in lineage ancestors "
                            f"of evaluated run {r.id}"
                        )

                    inv_run_id = r.config.get("inventory_run_id")
                    if isinstance(inv_run_id, str) and inv_run_id:
                        inv_anc_ids = {a_id for a_id, _ in repo.ancestors(inv_run_id)}
                        inv_lineage_leaked = gold_obs_ids & inv_anc_ids
                        if inv_lineage_leaked:
                            leak_list = sorted(inv_lineage_leaked)
                            raise BenchmarkLeakage(
                                f"gold observations {leak_list} in lineage ancestors "
                                f"of inventory run {inv_run_id}"
                            )
                        inv_run = repo.get_run(inv_run_id)
                        inv_igt_run = inv_run.config.get("igt_extract_run_id")
                        inv_excluded_raw = inv_run.config.get("exclude_refs")
                        inv_excluded = (
                            set(inv_excluded_raw)
                            if isinstance(inv_excluded_raw, (list, tuple))
                            else set()
                        )
                        if inv_igt_run:
                            inv_obs = repo.list_igt_observations_for_run(str(inv_igt_run))
                            active_inv_obs = [
                                o
                                for o in inv_obs
                                if not (
                                    (o.record_ref and o.record_ref in inv_excluded)
                                    or str(o.record_ordinal) in inv_excluded
                                    or o.id in inv_excluded
                                )
                            ]
                            used_inv_obs_ids = {o.id for o in active_inv_obs}
                            leaked_obs = gold_obs_ids & used_inv_obs_ids
                            if leaked_obs:
                                leak_list = sorted(leaked_obs)
                                raise BenchmarkLeakage(
                                    f"gold observations {leak_list} leaked into "
                                    f"inventory run {inv_run_id}"
                                )
                            active_inv_refs = (
                                {
                                    (o.source_id, o.source_object_id, "ref", o.record_ref)
                                    for o in active_inv_obs
                                    if o.record_ref
                                }
                                | {
                                    (o.source_id, o.source_object_id, "ord", str(o.record_ordinal))
                                    for o in active_inv_obs
                                }
                                | {
                                    (o.source_id, o.source_object_id, "id", o.id)
                                    for o in active_inv_obs
                                }
                            )
                            leaked_refs = {
                                (s, obj, k, v)
                                for s, obj, k, v in gold_source_refs
                                if any(
                                    s == inv_s
                                    and (obj is None or inv_obj is None or obj == inv_obj)
                                    and k == inv_k
                                    and v == inv_v
                                    for inv_s, inv_obj, inv_k, inv_v in active_inv_refs
                                )
                            }
                            if leaked_refs:
                                leak_list = sorted(
                                    f"{s}:{obj or '*'}:{k}:{v}" for s, obj, k, v in leaked_refs
                                )
                                raise BenchmarkLeakage(
                                    f"gold records {leak_list} leaked into "
                                    f"inventory run {inv_run_id}"
                                )
                        elif gold_source_refs:
                            inv_sources = ancestor_source_ids(repo, inv_run_id)
                            matching_gold_refs = {
                                val
                                for s_id, _obj_id, _k, val in gold_source_refs
                                if s_id in inv_sources
                            }
                            if matching_gold_refs and not matching_gold_refs.issubset(inv_excluded):
                                diff = sorted(matching_gold_refs - inv_excluded)
                                raise BenchmarkLeakage(
                                    f"gold records {diff} leaked into inventory run {inv_run_id}"
                                )
                    # If the evaluated run itself is an IGT assertion run
                    if r.stage is RunStage.IGT_IMPORT or r.tool_name == "langpipe.igt-assert":
                        eval_igt_run = r.config.get("igt_extract_run_id")
                        eval_excluded_raw = r.config.get("exclude_refs")
                        eval_excluded = (
                            set(eval_excluded_raw)
                            if isinstance(eval_excluded_raw, (list, tuple))
                            else set()
                        )
                        if eval_igt_run:
                            eval_obs = repo.list_igt_observations_for_run(str(eval_igt_run))
                            active_eval_obs = [
                                o
                                for o in eval_obs
                                if not (
                                    (o.record_ref and o.record_ref in eval_excluded)
                                    or str(o.record_ordinal) in eval_excluded
                                    or o.id in eval_excluded
                                )
                            ]
                            used_eval_obs_ids = {o.id for o in active_eval_obs}
                            leaked_eval_obs = gold_obs_ids & used_eval_obs_ids
                            if leaked_eval_obs:
                                eval_leak_list = sorted(leaked_eval_obs)
                                raise BenchmarkLeakage(
                                    f"gold observations {eval_leak_list} evaluated in assertion run"
                                )
                            active_eval_refs = (
                                {
                                    (o.source_id, o.source_object_id, "ref", o.record_ref)
                                    for o in active_eval_obs
                                    if o.record_ref
                                }
                                | {
                                    (o.source_id, o.source_object_id, "ord", str(o.record_ordinal))
                                    for o in active_eval_obs
                                }
                                | {
                                    (o.source_id, o.source_object_id, "id", o.id)
                                    for o in active_eval_obs
                                }
                            )
                            leaked_eval_refs = {
                                (s, obj, k, v)
                                for s, obj, k, v in gold_source_refs
                                if any(
                                    s == eval_s
                                    and (obj is None or eval_obj is None or obj == eval_obj)
                                    and k == eval_k
                                    and v == eval_v
                                    for eval_s, eval_obj, eval_k, eval_v in active_eval_refs
                                )
                            }
                            if leaked_eval_refs:
                                eval_leak_list = sorted(
                                    f"{s}:{obj or '*'}:{k}:{v}" for s, obj, k, v in leaked_eval_refs
                                )
                                raise BenchmarkLeakage(
                                    f"gold records {eval_leak_list} evaluated in "
                                    f"their own assertion run"
                                )
                        elif gold_source_refs:
                            eval_sources = ancestor_source_ids(repo, r.id)
                            matching_eval_refs = {
                                val
                                for s_id, _obj_id, _k, val in gold_source_refs
                                if s_id in eval_sources
                            }
                            if matching_eval_refs and not matching_eval_refs.issubset(
                                eval_excluded
                            ):
                                diff = sorted(matching_eval_refs - eval_excluded)
                                raise BenchmarkLeakage(
                                    f"gold records {diff} evaluated in their own assertion run"
                                )

                # 3. Map gold items to tokens and compute metrics
                method_metrics: dict[str, MorphologyMethodMetrics] = {}
                for r in eval_runs:
                    method_name = str(r.config.get("method", r.tool_name))
                    token_run_id = r.config.get("tokenization_run_id")
                    if not token_run_id:
                        raise InvalidLineage()

                    token_id_map: dict[int, str] = {}
                    token_surfaces: dict[str, str] = {}
                    analyses_by_token: dict[str, list[MorphAnalysis]] = {}
                    segs_by_analysis: dict[str, list[MorphSegment]] = {}

                    # Map gold items to tokens
                    for idx, it in enumerate(gold_model.items):
                        sel = it.selector if hasattr(it, "selector") else it.get("selector", {})
                        obs_id = resolved_gold_obs_ids.get(idx)
                        word_ord = sel.get("word_ordinal", 0)
                        seg_loc = sel.get("segment_locator")
                        tok_ord = sel.get("token_ordinal")
                        if seg_loc is not None:
                            # Look up segment by locator in tokenization run inputs (segment IDs)
                            input_loc_segs: list[Segment] = []
                            for seg_id, role in repo.list_run_io(str(token_run_id)):
                                if role is RunIoRole.INPUT:
                                    try:
                                        seg = repo.get_segment(seg_id)
                                    except NotFound:
                                        continue
                                    src_key = sel.get("source_key")
                                    if src_key:
                                        try:
                                            src_obj = repo.get_source(seg.source_id)
                                            if src_obj.key != src_key:
                                                continue
                                        except NotFound:
                                            continue
                                    if _matches_locator(seg.locator, seg_loc):
                                        input_loc_segs.append(seg)
                            # Reject ambiguous or missing locator matches: require unique match
                            # Do NOT fall through to observation matching on ambiguity or miss
                            has_obs_constraints = bool(
                                sel.get("record_ref")
                                or sel.get("record_ordinal") is not None
                                or sel.get("igt_ref")
                                or sel.get("observation_id")
                            )
                            if has_obs_constraints and not obs_id:
                                continue

                            if len(input_loc_segs) == 1:
                                matched_seg = input_loc_segs[0]
                                if obs_id:
                                    try:
                                        obs_obj = repo.get_igt_observation(obs_id)
                                        if obs_obj.source_id != matched_seg.source_id:
                                            continue
                                        if (
                                            obs_obj.source_object_id
                                            and matched_seg.source_object_id
                                            != obs_obj.source_object_id
                                        ):
                                            continue
                                        is_lineage_match = bool(
                                            obs_obj.segment_id
                                            and (
                                                obs_obj.segment_id == matched_seg.id
                                                or obs_obj.segment_id
                                                in {
                                                    a_id
                                                    for a_id, _ in repo.ancestors(matched_seg.id)
                                                }
                                            )
                                        )
                                        loc = matched_seg.locator
                                        is_record_match = isinstance(loc, dict) and (
                                            (
                                                obs_obj.record_ref
                                                and loc.get("igt_ref") == obs_obj.record_ref
                                            )
                                            or loc.get("record_ordinal") == obs_obj.record_ordinal
                                        )
                                        if not (is_lineage_match or is_record_match):
                                            continue
                                    except NotFound:
                                        continue
                                seg_tokens = [
                                    t
                                    for t in repo.list_tokens(matched_seg.id)
                                    if t.run_id == token_run_id
                                ]
                                seg_tokens.sort(key=lambda t: t.ordinal)
                                target_ord = int(tok_ord) if tok_ord is not None else 0
                                matched_tok = next(
                                    (t for t in seg_tokens if t.ordinal == target_ord), None
                                )
                                if matched_tok is not None:
                                    token_id_map[idx] = matched_tok.id
                                    surf = (
                                        matched_tok.normalized_surface
                                        if matched_tok.normalized_surface is not None
                                        else matched_tok.raw_surface
                                    )
                                    token_surfaces[matched_tok.id] = surf
                            continue

                        if obs_id:
                            obs = repo.get_igt_observation(obs_id)
                            matching_seg_ids: set[str] = set()
                            for inp_id, role in repo.list_run_io(str(token_run_id)):
                                if role is not RunIoRole.INPUT:
                                    continue
                                if inp_id == obs.segment_id:
                                    matching_seg_ids.add(inp_id)
                                    continue
                                try:
                                    cand_seg = repo.get_segment(inp_id)
                                except NotFound:
                                    continue
                                # Scope strictly to observation's source and object
                                if cand_seg.source_id != obs.source_id:
                                    continue
                                if (
                                    obs.source_object_id
                                    and cand_seg.source_object_id != obs.source_object_id
                                ):
                                    continue
                                # Lineage check: candidate descends from obs.segment_id
                                if obs.segment_id and obs.segment_id in {
                                    a_id for a_id, _ in repo.ancestors(cand_seg.id)
                                }:
                                    matching_seg_ids.add(cand_seg.id)
                                    continue
                                loc = cand_seg.locator
                                if isinstance(loc, dict) and (
                                    loc.get("record_ordinal") == obs.record_ordinal
                                    or (obs.record_ref and loc.get("igt_ref") == obs.record_ref)
                                ):
                                    matching_seg_ids.add(cand_seg.id)

                            # Reject ambiguous matches; require exactly one unique match
                            target_seg_id: str | None = None
                            if len(matching_seg_ids) == 1:
                                target_seg_id = next(iter(matching_seg_ids))
                            elif not matching_seg_ids and obs.segment_id:
                                target_seg_id = obs.segment_id

                            active_seg_id = target_seg_id
                            if active_seg_id:
                                seg_tokens = [
                                    t
                                    for t in repo.list_tokens(active_seg_id)
                                    if t.run_id == token_run_id
                                ]
                                seg_tokens.sort(key=lambda t: t.ordinal)
                                mapping = map_words(obs.words, seg_tokens)
                                matched_tok = next(
                                    (tok for w, tok in mapping.mapped if w.ordinal == word_ord),
                                    None,
                                )
                                if matched_tok is not None:
                                    token_id_map[idx] = matched_tok.id
                                    surf = (
                                        matched_tok.normalized_surface
                                        if matched_tok.normalized_surface is not None
                                        else matched_tok.raw_surface
                                    )
                                    token_surfaces[matched_tok.id] = surf

                    # Query candidate analyses for mapped tokens
                    abstentions_by_token: dict[str, Abstention] = {}
                    for tok_id in token_id_map.values():
                        cands = [
                            a
                            for a in repo.list_morph_analyses_for_token(tok_id)
                            if a.run_id == r.id
                        ]
                        analyses_by_token[tok_id] = cands
                        for a in cands:
                            segs = repo.list_morph_segments(a.id)
                            segs_by_analysis[a.id] = list(segs)
                            if a.abstention is not None:
                                abstentions_by_token[tok_id] = a.abstention

                    metrics = evaluate_morphology(
                        gold_items=gold_model.items,
                        analyses_by_token=analyses_by_token,
                        segments_by_analysis=segs_by_analysis,
                        token_id_map=token_id_map,
                        token_surfaces=token_surfaces,
                        token_abstentions=abstentions_by_token,
                    )
                    method_metrics[method_name] = metrics

                # 4. Check Idempotent Rerun Reuse
                bench_config: dict[str, Any] = {
                    "evaluated_run_ids": sorted(evaluated_run_ids),
                    "gold_digest": gold_digest,
                }
                bench_inputs = sorted({*evaluated_run_ids, *source_ids})
                reusable = self.recorder.find_reusable(
                    RunStage.EVALUATION, TOOL_NAME, bench_config, bench_inputs
                )
                if reusable is not None:
                    out_artifacts = [
                        repo.get_artifact(art_id)
                        for art_id, role in repo.list_run_io(reusable.id)
                        if role is RunIoRole.OUTPUT
                    ]
                    if out_artifacts:
                        return MorphologyBenchmarkSummary(
                            run=reusable,
                            report=out_artifacts[0],
                            metrics=method_metrics,
                            reused=True,
                        )

                # 5. Record New Run & Report
                digest = config_hash(bench_config)
                run_key = ProcessingRun.compute_run_key(
                    RunStage.EVALUATION, TOOL_NAME, TOOL_VERSION, digest, bench_inputs
                )
                bench_run = ProcessingRun(
                    id=self.ctx.new_id(IdPrefix.RUN),
                    stage=RunStage.EVALUATION,
                    tool_name=TOOL_NAME,
                    tool_version=TOOL_VERSION,
                    config=dict(bench_config),
                    config_hash=digest,
                    code_revision=self.ctx.code_revision,
                    run_key=run_key,
                    status=RunStatus.RUNNING,
                    started_at=self.ctx.clock(),
                )
                repo.add_run(bench_run)

                source_models = [repo.get_source(s_id) for s_id in source_ids]
                access = (
                    most_restrictive(effective_policy(repo, s).access_class for s in source_models)
                    if source_models
                    else AccessClass.PUBLIC
                )
                methods_list = [r.config.get("method", r.tool_name) for r in eval_runs]
                not_run = {
                    "flatcat": "not_available",
                }
                if not any(str(m).startswith("morfessor") for m in methods_list):
                    not_run["morfessor_baseline"] = "optional_extra_absent"

                report_payload = {
                    "schema": REPORT_SCHEMA,
                    "schema_version": 1,
                    "run_id": bench_run.id,
                    "evaluated_run_ids": sorted(evaluated_run_ids),
                    "methods": methods_list,
                    "gold_digest": gold_digest,
                    "gold_items": len(gold_model.items),
                    "metrics": {m: met.to_dict() for m, met in method_metrics.items()},
                    "not_run": not_run,
                }

                stored = self.ctx.artifact_store.put_bytes(
                    canonical_json(report_payload).encode("utf-8")
                )
                report_artifact = Artifact(
                    id=self.ctx.new_id(IdPrefix.ARTIFACT),
                    run_id=bench_run.id,
                    kind=ArtifactKind.BENCHMARK_REPORT,
                    media_type="application/json",
                    sha256=stored.sha256,
                    size_bytes=stored.size_bytes,
                    access_class=access,
                    schema_name=REPORT_SCHEMA,
                    schema_version=1,
                    created_at=self.ctx.clock(),
                )

                repo.add_artifact(report_artifact)
                repo.add_run_io(bench_run.id, report_artifact.id, RunIoRole.OUTPUT)
                for inp_id in bench_inputs:
                    repo.add_run_io(bench_run.id, inp_id, RunIoRole.INPUT)
                    repo.add_lineage_edge(
                        LineageEdge(
                            id=self.ctx.new_id(IdPrefix.LINEAGE),
                            from_id=report_artifact.id,
                            to_id=inp_id,
                            kind=LineageKind.DERIVED_FROM,
                            run_id=bench_run.id,
                            created_at=self.ctx.clock(),
                        )
                    )
                succeeded_run = self.recorder.succeed(bench_run.id)

                return MorphologyBenchmarkSummary(
                    run=succeeded_run,
                    report=report_artifact,
                    metrics=method_metrics,
                    reused=False,
                )
        except PolicyDenied as exc:
            self._record_denial(exc.source_id, exc.decision)
            raise


def evaluate_morphology_benchmark(
    ctx: AppContext,
    evaluated_run_ids: Sequence[str],
    gold: MorphGold | str,
    refs: Sequence[str] = (),
    language: str | None = None,
) -> MorphologyBenchmarkSummary:
    """Helper entry point for morphology benchmarking."""
    service = MorphologyBenchmarkService(ctx)
    return service.evaluate(
        evaluated_run_ids=evaluated_run_ids,
        gold=gold,
        refs=refs,
        language=language,
    )
