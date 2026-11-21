"""M4 golden lexical evidence, review authority, revocation and CLDF export contracts.

Source 01 (``01-parallel-distill``) drives the alignment path and source 03
(``03-wordlist``) the wordlist path, both unchanged from M1-M3; the synthetic
``golden-lexicon-export`` wordlist (``fixture/lexicon/``) is the only source whose
policy grants ``redistribute_derived``, so it alone can ever produce an export row.
Token links come from the test-injected ``MockTokenAligner`` with the M4 surface
dictionary; review authority is an explicit in-test registry with synthetic reviewer
ids, so no real data is ever validated (DELEGATED-DECISIONS §2).
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from langpipe.alignment.base import AlignmentConfig
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.app_context import AppContext
from langpipe.cldf.exporter import CLDFExporter, CLDFExportResult
from langpipe.domain.enums import (
    AuditEventType,
    EntityType,
    LifecycleStatus,
    LineageKind,
    Operation,
    PolicyDecision,
    ReviewDecisionKind,
    ReviewTaskType,
    RunIoRole,
    SourceStatus,
)
from langpipe.domain.errors import InvalidTransition, NoEligibleRecords, PolicyDenied
from langpipe.domain.hashing import canonical_json
from langpipe.domain.models.review import ReviewTask
from langpipe.governance.lineage_policy import (
    ancestor_source_ids,
    lineage_eligibility,
    revoked_ancestor_ids,
)
from langpipe.ingest.wordlist import WordlistExtractionResult, WordlistExtractor
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.lexicon.adapters.wordlist import PRIMARY_LEMMA_ROLE
from langpipe.lexicon.service import LexicalInductionResult, LexicalService
from langpipe.lineage import RevocationImpact, revocation_impact
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.base import UnauthorizedReviewer
from langpipe.review.recalc import RecalcService
from langpipe.review.service import ReviewDecisionResult, ReviewService
from tests.golden.normalize_m4 import lexeme_headword, normalize_m4_snapshot
from tests.golden.test_golden_m3 import (
    _align,
    _Aligned,
    _groups,
    _LinksMap,
    _M3Flow,
    _parallel_flow,
)
from tests.service.manifests import state_counts

GOLDEN = Path(__file__).parent
FIXTURE_SOURCES = GOLDEN / "fixture" / "sources"
LEXICON_DIR = GOLDEN / "fixture" / "lexicon"
EXPECTED = GOLDEN / "expected" / "m4"
UPDATE_ENV = "LANGPIPE_UPDATE_GOLDEN"
UPDATE_MESSAGE = "golden files rewritten; review the diff and commit intentionally"

ROLE = "golden_lexicographer"
REVIEWER = "golden-reviewer"
FAUNA_REVIEWER = "golden-fauna-only"
LANGUAGE = "qaa"
CONTACT = "por"
EXPORT_KEY = "golden-lexicon-export"

# Surface dictionary of the M4 mock matrix; never linked: `mabi-ki`, `wesa-ra` (M5 owns
# suffix-like material) and every other surface in the fixture.
_M4_LINKS = {"kanu": "homem", "mabi": "canoa", "rumi": "pajé"}

# Operations whose eligibility the snapshot pins per object.
OPS: tuple[Operation, ...] = (
    Operation.REDISTRIBUTE_DERIVED,
    Operation.HUMAN_REVIEW,
    Operation.DISTILL_LEXICON,
)


class Stage(IntEnum):
    """The latest pipeline step one world is built through (spec §2.1)."""

    S5 = 5
    S6 = 6
    S7 = 7
    S10 = 10


def _tokens_of(ctx: AppContext, flow: _M3Flow, segment_id: str) -> list[Any]:
    """Occurrences of one segment restricted to the flow's pinned tokenization run."""
    tokens: list[Any] = flow.tokens(ctx.repo, segment_id)
    return tokens


def _group_tokens(ctx: AppContext, flow: _M3Flow, alignment: Any) -> tuple[list[Any], list[Any]]:
    """One group's ordered sides: tokens of each member segment, in member then ordinal order."""
    source_tokens: list[Any] = []
    target_tokens: list[Any] = []
    for segment_id in alignment.source_segment_ids:
        source_tokens.extend(_tokens_of(ctx, flow, segment_id))
    for segment_id in alignment.target_segment_ids:
        target_tokens.extend(_tokens_of(ctx, flow, segment_id))
    return source_tokens, target_tokens


def _m4_links(ctx: AppContext, flow: _M3Flow) -> _LinksMap:
    """Explicit mock matrix built by surface lookup, symmetrized in both directions."""
    links: _LinksMap = {}
    matched: set[str] = set()
    segment = SegmentAlignmentService(ctx).align(
        flow.side("qaa"), flow.side("por"), config=AlignmentConfig(namespace="tsv")
    )
    for alignment in _groups(ctx, segment.run.id):
        source_tokens, target_tokens = _group_tokens(ctx, flow, alignment)
        pairs: list[tuple[int, int]] = []
        for key, value in _M4_LINKS.items():
            source_index = next(
                (i for i, token in enumerate(source_tokens) if token.raw_surface == key), None
            )
            target_index = next(
                (i for i, token in enumerate(target_tokens) if token.raw_surface == value), None
            )
            if source_index is not None and target_index is not None:
                pairs.append((source_index, target_index))
                matched.add(key)
        pairs.sort()
        symmetrized = tuple(pairs)
        links[alignment.id] = (symmetrized, symmetrized)
    # A tokenizer change must never pass by silently emitting no links.
    assert matched == set(_M4_LINKS), sorted(set(_M4_LINKS) - matched)
    return links


@dataclass
class _M4World:
    """Everything one M4 pipeline run persisted, plus the captures its tests read."""

    ctx: AppContext
    flow: _M3Flow
    aligned: _Aligned
    sources: dict[str, str]
    induce01: LexicalInductionResult
    extract03: WordlistExtractionResult
    induce03: LexicalInductionResult
    registration_export: RegistrationResult
    registration03: RegistrationResult
    extract_export: WordlistExtractionResult
    induce_export: LexicalInductionResult
    fingerprint_s5: dict[str, str]
    review: ReviewService | None = None
    tasks: dict[str, ReviewTask] = field(default_factory=dict)
    decisions: dict[str, ReviewDecisionResult] = field(default_factory=dict)
    pre_t3: dict[str, LifecycleStatus] = field(default_factory=dict)
    export_pre: CLDFExportResult | None = None
    pre_eligibility: dict[str, dict[Operation, PolicyDecision]] = field(default_factory=dict)
    pre_statuses: dict[str, LifecycleStatus] = field(default_factory=dict)
    impact: RevocationImpact | None = None
    export_post: CLDFExportResult | None = None
    fingerprint_s10: dict[str, str] | None = None
    p12b_denials: list[tuple[str, str]] = field(default_factory=list)

    def source(self, key: str) -> str:
        return self.sources[key]

    def export_pre_run(self) -> Any:
        assert self.export_pre is not None
        return self.export_pre.run

    def require_export_pre(self) -> CLDFExportResult:
        assert self.export_pre is not None
        return self.export_pre

    def require_export_post(self) -> CLDFExportResult:
        assert self.export_post is not None
        return self.export_post

    def require_impact(self) -> RevocationImpact:
        assert self.impact is not None
        return self.impact

    def evidence_ids(self, target_id: str) -> list[str]:
        return sorted(item.id for item in self.ctx.repo.list_evidence_for_target(target_id))

    def lex(self, source_key: str, headword: str) -> str:
        """The one lexeme of `source_key` whose lemma form or headword claim names `headword`."""
        repo = self.ctx.repo
        found: list[str] = [
            lexeme.id
            for lexeme in repo.list_lexemes_by_language(LANGUAGE)
            if ancestor_source_ids(repo, lexeme.id) == [self.sources[source_key]]
            and lexeme_headword(repo, lexeme.id) == headword
        ]
        assert len(found) == 1, (source_key, headword, len(found))
        return found[0]

    def sense(self, source_key: str, headword: str, gloss: str) -> str:
        repo = self.ctx.repo
        found: list[str] = [
            sense.id
            for sense in repo.list_senses_for_lexeme(self.lex(source_key, headword))
            if sense.glosses.get(CONTACT) == [gloss]
        ]
        assert len(found) == 1, (source_key, headword, gloss, len(found))
        return found[0]


def _review_service(ctx: AppContext) -> ReviewService:
    """The explicit in-test authority registry; LANGUAGE_PROFILES is never mutated."""
    registry = ReviewAuthorityRegistry()
    registry.register(REVIEWER, ROLE, [LANGUAGE])
    registry.register(FAUNA_REVIEWER, ROLE, [LANGUAGE], domains=["fauna"])
    return ReviewService(
        ctx.repo, registry, clock=ctx.clock, new_id=ctx.new_id, code_revision="golden-m4"
    )


def _revoke(ctx: AppContext, source_id: str) -> None:
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())


def _audit_denials(ctx: AppContext, before: int) -> list[Any]:
    return [
        event
        for event in ctx.repo.list_audit_events()[before:]
        if event.event_type is AuditEventType.POLICY_DENIED
    ]


def _run_outputs(ctx: AppContext, run_id: str, entity_type: EntityType) -> list[str]:
    return sorted(
        object_id
        for object_id, role in ctx.repo.list_run_io(run_id)
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is entity_type
    )


def _segment_key(segment: Any, layer: str) -> str:
    locator = segment.locator
    ref = str(locator.get("ref", locator.get("row", "")))
    base = f"{layer}:{segment.language}:{ref}"
    part = locator.get("sentence_part")
    return base if part is None else f"{base}:{part}"


def _flow_extraction_run(repo: Any, flow: _M3Flow) -> Any:
    """The extraction run that produced the raw segments one flow normalized."""
    for object_id, role in repo.list_run_io(flow.normalization.run.id):
        if role is not RunIoRole.INPUT:
            continue
        if repo.entity_type_of(object_id) is not EntityType.SEGMENT:
            continue
        raw = repo.get_segment(object_id)
        if raw.normalization_profile is None:
            return repo.get_run(raw.run_id)
    raise AssertionError("normalization without raw extraction inputs")


def _observation_fingerprint(
    ctx: AppContext,
    sources: dict[str, str],
    flow: _M3Flow,
    aligned: _Aligned,
    induction_run_ids: Sequence[str],
) -> dict[str, str]:
    """model_dump fingerprints of every observation-layer entity plus raw digests."""
    repo = ctx.repo
    entries: dict[str, str] = {}

    def put(key: str, model: Any) -> None:
        entries[key] = canonical_json(model.model_dump(mode="json"))

    for source_key, source_id in sources.items():
        for obj in repo.list_source_objects(source_id):
            put(f"sobj:{source_key}/{obj.original_path}", obj)
    for layer, raw_layer, normalization_flow in (("seg", "segraw", flow),):
        for segment in repo.list_segments_for_run(
            _flow_extraction_run(repo, normalization_flow).id
        ):
            put(_segment_key(segment, raw_layer), segment)
        for segment in repo.list_segments_for_run(normalization_flow.normalization.run.id):
            put(_segment_key(segment, layer), segment)
            for token in repo.list_tokens(segment.id):
                if token.run_id != normalization_flow.tokenization_run_id:
                    continue
                token_layer = "tok"
                put(
                    f"{token_layer}:{_segment_key(segment, layer)}:{token.ordinal}",
                    token,
                )
                if token.form_id is not None:
                    form = repo.get_form(token.form_id)
                    put(f"form:{form.language}/{form.orthography_profile}/{form.text}", form)
    alignments = {
        alignment.id: alignment
        for alignment in repo.list_segment_alignments_for_run(aligned.segment_run_id)
    }
    for alignment in alignments.values():
        first = repo.get_segment(alignment.source_segment_ids[0])
        put(f"sal:{_segment_key(first, 'seg')}", alignment)
    for edge in repo.list_token_alignment_edges_for_run(aligned.token_run_id):
        group = alignments[edge.segment_alignment_id]
        source_tokens, target_tokens = _group_tokens(ctx, flow, group)
        source_index = next(
            i for i, token in enumerate(source_tokens) if token.id == edge.source_token_id
        )
        target_index = next(
            i for i, token in enumerate(target_tokens) if token.id == edge.target_token_id
        )
        first = repo.get_segment(group.source_segment_ids[0])
        tal = f"tal:{_segment_key(first, 'seg')}:{source_index}->{target_index}"
        put(f"{tal}:{edge.direction.value}", edge)
    for run_id in induction_run_ids:
        for item_id in _run_outputs(ctx, run_id, EntityType.EVIDENCE_ITEM):
            item = repo.get_evidence(item_id)
            put(f"ev:{item.target_id}:{item.kind.value}:{canonical_json(item.claim or {})}", item)
    return entries


def _status_of(repo: Any, object_id: str) -> LifecycleStatus:
    entity = repo.entity_type_of(object_id)
    if entity is EntityType.LEXEME:
        status: LifecycleStatus = repo.get_lexeme(object_id).status
        return status
    assert entity is EntityType.SENSE
    sense_status: LifecycleStatus = repo.get_sense(object_id).status
    return sense_status


def _stage6(world: _M4World) -> None:
    """Review tasks T1-T8 and their decisions, in the fixed spec order (§3.2)."""
    ctx = world.ctx
    repo = ctx.repo
    review = _review_service(ctx)
    world.review = review
    targets = {
        "T1": world.sense("03-wordlist", "mabi", "canoa"),
        "T2": world.sense("03-wordlist", "mabi", "tronco"),
        "T3": world.lex("03-wordlist", "mabi"),
        "T4": world.lex(EXPORT_KEY, "nawa"),
        "T5": world.sense(EXPORT_KEY, "nawa", "rio"),
        "T6": world.lex("01-parallel-distill", "rumi"),
        "T7": world.sense("01-parallel-distill", "rumi", "pajé"),
        "T8": world.sense("03-wordlist", "rumi", "pajé"),
    }
    for name in sorted(targets):
        target_id = targets[name]
        world.tasks[name] = review.create_task(
            target_id,
            task_type=ReviewTaskType.LEXICAL_SENSE,
            required_role=ROLE,
            evidence_item_ids=world.evidence_ids(target_id),
        )
    for name, kind in (
        ("T1", ReviewDecisionKind.ACCEPT),
        ("T2", ReviewDecisionKind.REJECT),
    ):
        world.decisions[name] = review.record_decision(world.tasks[name].id, kind, REVIEWER, ROLE)
    # Statuses of record just before T3, for the P10 contained-side-effects check.
    world.pre_t3 = {
        "mabi03": repo.get_lexeme(targets["T3"]).status,
        "tronco03": repo.get_sense(targets["T2"]).status,
    }
    for name, kind in (
        ("T3", ReviewDecisionKind.ACCEPT),
        ("T4", ReviewDecisionKind.ACCEPT),
        ("T5", ReviewDecisionKind.ACCEPT),
        ("T6", ReviewDecisionKind.ACCEPT),
        ("T7", ReviewDecisionKind.ACCEPT),
    ):
        world.decisions[name] = review.record_decision(world.tasks[name].id, kind, REVIEWER, ROLE)
    # T8 is deliberately left open: its refused `golden-fauna-only` decision is the P9
    # negative, exercised by test_p9_rumi_domain_preserved on its own world.


def _capture_pre_revocation(world: _M4World) -> None:
    """Statuses and eligibility of every lexeme and sense, read back at S7."""
    repo = world.ctx.repo
    for lexeme in repo.list_lexemes_by_language(LANGUAGE):
        current = repo.get_lexeme(lexeme.id)
        world.pre_statuses[current.id] = current.status
        world.pre_eligibility[current.id] = {
            op: lineage_eligibility(repo, current.id, op) for op in OPS
        }
        for sense in repo.list_senses_for_lexeme(current.id):
            fresh = repo.get_sense(sense.id)
            world.pre_statuses[fresh.id] = fresh.status
            world.pre_eligibility[fresh.id] = {
                op: lineage_eligibility(repo, fresh.id, op) for op in OPS
            }


def _capture_p12b(world: _M4World, tmp_path: Path) -> None:
    """Revoke the export source and record the failing export's denial details."""
    ctx = world.ctx
    repo = ctx.repo
    before = len(repo.list_audit_events())
    _revoke(ctx, world.source(EXPORT_KEY))
    try:
        CLDFExporter(ctx).export(language=LANGUAGE, output_dir=tmp_path / "cldf-p12b")
    except NoEligibleRecords:
        pass
    else:
        raise AssertionError("post-revocation export must fail closed")
    world.p12b_denials = [
        (str(event.subject_id), str(event.details.get("decision")))
        for event in _audit_denials(ctx, before)
    ]


def _build_m4_world(ctx: AppContext, tmp_path: Path, *, until: Stage) -> _M4World:
    """S1-S10 in the fixed spec order, stopping at `until` (§2.1).

    S2 aligns both language sides from the single M3 flow and its pinned
    normalization/tokenization runs.
    """
    flow = _parallel_flow(ctx)  # S1
    aligned = _align(ctx, flow, _m4_links(ctx, flow))  # S2
    sources = {flow.registration.source.key: flow.source_id}
    induce01 = LexicalService(ctx).induce_lexicon(  # S3
        aligned.token_run_id,
        method="alignment_cooccurrence@0.1.0",
        target_language=LANGUAGE,
        contact_language=CONTACT,
    )
    registration03 = register_source(  # S4
        ctx, FIXTURE_SOURCES / "03-wordlist" / "manifest.yaml"
    )
    sources[registration03.source.key] = registration03.source.id
    extract03 = WordlistExtractor(ctx).extract("03-wordlist")
    induce03 = LexicalService(ctx).induce_lexicon(extract03.run.id, method="wordlist_tabular@0.1.0")
    registration = register_source(ctx, LEXICON_DIR / "export-manifest.yaml")  # S5
    sources[registration.source.key] = registration.source.id
    extract_export = WordlistExtractor(ctx).extract(EXPORT_KEY)
    induce_export = LexicalService(ctx).induce_lexicon(
        extract_export.run.id, method="wordlist_tabular@0.1.0"
    )
    fingerprint_s5 = _observation_fingerprint(
        ctx,
        sources,
        flow,
        aligned,
        [induce01.run.id, induce03.run.id, induce_export.run.id],
    )
    world = _M4World(
        ctx=ctx,
        flow=flow,
        aligned=aligned,
        sources=sources,
        induce01=induce01,
        extract03=extract03,
        induce03=induce03,
        registration_export=registration,
        registration03=registration03,
        extract_export=extract_export,
        induce_export=induce_export,
        fingerprint_s5=fingerprint_s5,
    )
    if until is Stage.S5:
        return world
    _stage6(world)  # S6
    if until is Stage.S6:
        return world
    RecalcService(ctx).recalculate(all_stale=True)
    world.export_pre = CLDFExporter(ctx).export(  # S7
        language=LANGUAGE, output_dir=tmp_path / "cldf-pre"
    )
    _capture_pre_revocation(world)
    if until is Stage.S7:
        return world
    _revoke(ctx, flow.source_id)  # S8
    world.impact = revocation_impact(ctx.repo, flow.source_id)  # S9
    world.export_post = CLDFExporter(ctx).export(  # S10
        language=LANGUAGE, output_dir=tmp_path / "cldf-post"
    )
    world.fingerprint_s10 = _observation_fingerprint(
        ctx,
        sources,
        flow,
        aligned,
        [induce01.run.id, induce03.run.id, induce_export.run.id],
    )
    return world


def _write_expected(snapshot: dict[str, Any]) -> None:
    EXPECTED.mkdir(parents=True, exist_ok=True)
    for name, value in snapshot.items():
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (EXPECTED / f"{name}.json").write_text(text, encoding="utf-8")


# --- snapshot ---------------------------------------------------------------------------


def test_golden_m4_snapshot(ctx: AppContext, tmp_path: Path) -> None:
    """Nine ID-free sections record the post-review, post-revocation world."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S10)
    # The P12b denial details are captured after S10 so the revocation-world bystander
    # checks in test_p12a see the export source still live.
    _capture_p12b(world, tmp_path)
    snapshot = normalize_m4_snapshot(ctx, world)
    if os.environ.get(UPDATE_ENV) == "1":
        _write_expected(snapshot)
        pytest.fail(UPDATE_MESSAGE)
    assert set(snapshot) == {path.stem for path in EXPECTED.glob("*.json")}
    for name, value in snapshot.items():
        expected = json.loads((EXPECTED / f"{name}.json").read_text(encoding="utf-8"))
        assert value == expected, name


# --- phenomena ---------------------------------------------------------------------------


def test_p2_mabi_one_lexeme_two_senses(ctx: AppContext, tmp_path: Path) -> None:
    """One wordlist headword keeps two sense hypotheses; sources never merge."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S5)
    repo = ctx.repo
    mabi03 = world.lex("03-wordlist", "mabi")
    run_lexemes = [
        repo.get_lexeme(item)
        for item in _run_outputs(ctx, world.induce03.run.id, EntityType.LEXEME)
    ]
    mabis = [item for item in run_lexemes if lexeme_headword(repo, item.id) == "mabi"]
    assert len(mabis) == 1 and mabis[0].id == mabi03

    senses = repo.list_senses_for_lexeme(mabi03)
    assert sorted(sense.glosses[CONTACT][0] for sense in senses) == ["canoa", "tronco"]
    assert all(sense.lexeme_id == mabi03 for sense in senses)
    run_id = world.induce03.run.id
    for sense in senses:
        gloss = sense.glosses[CONTACT][0]
        own = [
            item
            for item in repo.list_evidence_for_target(mabi03)
            if (item.claim or {}).get("gloss") == gloss
        ]
        assert len(own) == 1
        parents = {(edge.to_id, edge.kind) for edge in repo.list_lineage_edges(sense.id, "out")}
        assert (mabi03, LineageKind.DERIVED_FROM) in parents
        assert (run_id, LineageKind.DERIVED_FROM) in parents
        assert (own[0].id, LineageKind.DERIVED_FROM) in parents
    for sense in senses:
        # The snapshot pins which; the machine policy may grant supported at most.
        assert sense.status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)

    mabi01 = world.lex("01-parallel-distill", "mabi")
    assert mabi01 != mabi03
    senses01 = repo.list_senses_for_lexeme(mabi01)
    assert [sense.glosses[CONTACT] for sense in senses01] == [["canoa"]]
    assert repo.list_form_lexeme_links_for_lexeme(mabi03) == []
    links = repo.list_form_lexeme_links_for_lexeme(mabi01)
    assert len(links) == 1 and links[0].role == PRIMARY_LEMMA_ROLE
    form = repo.get_form(links[0].form_id)
    assert f"{form.language}/{form.orthography_profile}/{form.text}" == (
        "qaa/default_text@0.1.0/mabi"
    )


def test_p9_rumi_domain_preserved(ctx: AppContext, tmp_path: Path) -> None:
    """The wordlist domain tag stays on the 03 sense and gates review authority."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S6)
    repo = ctx.repo
    rumi03 = world.lex("03-wordlist", "rumi")
    assert repo.get_lexeme(rumi03).domain is None
    senses = repo.list_senses_for_lexeme(rumi03)
    assert len(senses) == 1
    sense = senses[0]
    assert sense.domain == "ritual/traditional"
    assert sense.glosses == {CONTACT: ["pajé"]}
    evidence = repo.list_evidence_for_target(rumi03)
    assert [item.domain for item in evidence] == ["ritual/traditional"]

    sense01 = repo.get_sense(world.sense("01-parallel-distill", "rumi", "pajé"))
    assert sense01.domain != "ritual/traditional"

    # The tag carries weight in review: a fauna-scoped reviewer is refused.
    before_counts = state_counts(ctx)
    status_before = repo.get_sense(sense.id).status
    decisions_before = repo.list_review_decisions_for_target(sense.id)
    assert world.review is not None
    with pytest.raises(UnauthorizedReviewer):
        world.review.record_decision(
            world.tasks["T8"].id, ReviewDecisionKind.ACCEPT, FAUNA_REVIEWER, ROLE
        )
    assert repo.get_review_task(world.tasks["T8"].id).status == "open"
    assert repo.get_sense(sense.id).status == status_before
    assert repo.list_review_decisions_for_target(sense.id) == decisions_before
    assert state_counts(ctx) == before_counts


def test_p10_review_accept_validates(ctx: AppContext, tmp_path: Path) -> None:
    """An authorized accept creates one immutable decision and validates its target."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S6)
    repo = ctx.repo
    canoa03 = world.sense("03-wordlist", "mabi", "canoa")
    result = world.decisions["T1"]
    decision = result.decision
    assert decision.task_id == world.tasks["T1"].id
    assert decision.target_id == canoa03
    assert decision.decision is ReviewDecisionKind.ACCEPT
    assert decision.reviewer_id == REVIEWER
    assert decision.reviewer_role == ROLE
    assert decision.superseding_object_id is None
    assert result.target_status is LifecycleStatus.VALIDATED
    assert repo.get_sense(canoa03).status is LifecycleStatus.VALIDATED
    assert repo.get_review_task(world.tasks["T1"].id).status == "resolved"

    stored = repo.get_review_decision(decision.id)
    with pytest.raises(ValidationError):
        stored.decision = ReviewDecisionKind.REJECT  # type: ignore[misc]
    with pytest.raises(InvalidTransition):
        assert world.review is not None
        world.review.record_decision(
            world.tasks["T1"].id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE
        )
    assert len(repo.list_review_decisions_for_target(canoa03)) == 1

    # Side effects are contained: T3 moved only the lexeme, not its decided siblings.
    tronco03 = world.sense("03-wordlist", "mabi", "tronco")
    mabi03 = world.lex("03-wordlist", "mabi")
    assert world.pre_t3["tronco03"] is LifecycleStatus.REJECTED
    assert world.pre_t3["mabi03"] in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
    assert repo.get_sense(tronco03).status is LifecycleStatus.REJECTED
    assert repo.get_sense(canoa03).status is LifecycleStatus.VALIDATED
    for sense in repo.list_senses_for_lexeme(mabi03):
        stale = [edge for edge in repo.list_lineage_edges(sense.id, "out")]
        assert any(
            edge.kind is LineageKind.STALE_DEPENDENT and edge.to_id == mabi03 for edge in stale
        )

    breakdown = repo.get_sense(canoa03).score_breakdown
    assert breakdown is not None and breakdown.policy_version == "lexical-v1"
    for induction in (world.induce01, world.induce03, world.induce_export):
        assert "validated" not in induction.status_counts


def test_p11_review_reject_rejects(ctx: AppContext, tmp_path: Path) -> None:
    """An authorized reject retires the sense and deletes nothing."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S6)
    repo = ctx.repo
    tronco03 = world.sense("03-wordlist", "mabi", "tronco")
    result = world.decisions["T2"]
    assert result.decision.decision is ReviewDecisionKind.REJECT
    assert result.target_status is LifecycleStatus.REJECTED
    sense = repo.get_sense(tronco03)
    assert sense.status is LifecycleStatus.REJECTED
    assert sense.glosses == {CONTACT: ["tronco"]}
    mabi03 = world.lex("03-wordlist", "mabi")
    parents = {(edge.to_id, edge.kind) for edge in repo.list_lineage_edges(tronco03, "out")}
    assert (mabi03, LineageKind.DERIVED_FROM) in parents
    claims = [
        (repo.get_evidence(object_id).claim or {}).get("gloss")
        for object_id, kind in parents
        if kind is LineageKind.DERIVED_FROM
        and repo.entity_type_of(object_id) is EntityType.EVIDENCE_ITEM
    ]
    assert "tronco" in claims
    canoa03 = world.sense("03-wordlist", "mabi", "canoa")
    assert repo.get_sense(canoa03).status is LifecycleStatus.VALIDATED
    assert repo.get_review_task(world.tasks["T2"].id).status == "resolved"
    with pytest.raises(InvalidTransition):
        assert world.review is not None
        world.review.record_decision(
            world.tasks["T2"].id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE
        )


def test_p12a_revoke_01_impact_and_eligibility(ctx: AppContext, tmp_path: Path) -> None:
    """Revoking 01 flips computed eligibility while every stored row stays as it was."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S10)
    repo = ctx.repo
    src01 = world.source("01-parallel-distill")
    kanu01 = world.lex("01-parallel-distill", "kanu")
    mabi01 = world.lex("01-parallel-distill", "mabi")
    rumi01 = world.lex("01-parallel-distill", "rumi")
    homem01 = world.sense("01-parallel-distill", "kanu", "homem")
    canoa01 = world.sense("01-parallel-distill", "mabi", "canoa")
    paje01 = world.sense("01-parallel-distill", "rumi", "pajé")
    nawa = world.lex(EXPORT_KEY, "nawa")
    rio = world.sense(EXPORT_KEY, "nawa", "rio")

    # 1. Pre-revocation export (S7): exactly the redistributable source's rows.
    pre = world.export_pre
    assert pre is not None and pre.reused is False
    assert pre.exported["entries"] == 1 and pre.exported["senses"] == 1
    payload = json.loads(ctx.artifact_store.read_bytes(pre.report.sha256))
    assert set(payload["entry_ids"]) == {nawa}
    assert set(payload["sense_ids"]) == {rio}
    assert payload["omitted"]["denied"] >= 2
    # The artifact keeps the counts of its own S7 run, before 01 was revoked. A reused
    # export that reads it must not re-report them as current (tsk #204).
    assert payload["omitted"]["revoked"] == 0

    # 2. Impact (S9): exactly the 01 descent, reaching its review queue entries.
    impact = world.impact
    assert impact is not None and impact.revoked is True
    assert set(impact.lexemes) == {kanu01, mabi01, rumi01}
    assert set(impact.senses) == {homem01, canoa01, paje01}
    assert set(impact.validated_affected) == {rumi01, paje01}
    assert {world.tasks["T6"].id, world.tasks["T7"].id} <= set(impact.review_tasks)
    assert {
        world.decisions["T6"].decision.id,
        world.decisions["T7"].decision.id,
    } <= set(impact.review_decisions)
    foreign: set[str] = set()
    if pre is not None:
        foreign.add(pre.report.id)
    for key in ("03-wordlist", EXPORT_KEY):
        foreign.add(world.source(key))
        for lexeme in repo.list_lexemes_by_language(LANGUAGE):
            if ancestor_source_ids(repo, lexeme.id) == [world.source(key)]:
                foreign.add(lexeme.id)
                foreign.update(sense.id for sense in repo.list_senses_for_lexeme(lexeme.id))
    assert {entry.object_id for entry in impact.entries}.isdisjoint(foreign)

    # 3. Eligibility flips; rows do not (ADR-0015: computed, never materialized).
    for object_id in (*impact.lexemes, *impact.senses):
        assert revoked_ancestor_ids(repo, object_id) == [src01]
        for op in (Operation.REDISTRIBUTE_DERIVED, Operation.HUMAN_REVIEW):
            assert lineage_eligibility(repo, object_id, op) is PolicyDecision.DENY
        assert world.pre_statuses[object_id] == _status_of(repo, object_id)
    assert repo.get_lexeme(rumi01).status is LifecycleStatus.VALIDATED
    assert repo.get_sense(paje01).status is LifecycleStatus.VALIDATED

    # 4. Bystanders are unaffected.
    for object_id, before_ops in world.pre_eligibility.items():
        if ancestor_source_ids(repo, object_id) in ([src01], []):
            continue
        assert _status_of(repo, object_id) == world.pre_statuses[object_id]
        for op, decision in before_ops.items():
            assert lineage_eligibility(repo, object_id, op) is decision

    # 5. Post-revocation export (S10): reused, byte-identical, still 01-free.
    post = world.export_post
    assert post is not None
    assert post.reused is True
    assert post.exported == pre.exported
    # The reused result reports the selection just made, not the S7 payload's counts:
    # source 01's lexeme is omitted as `revoked` now, not `denied` (tsk #204; ADR-0016
    # enumerates omissions so governance pressure stays visible), while the run's stored
    # report artifact still records what its own run counted.
    assert post.omitted["revoked"] == 1
    assert post.omitted["denied"] == pre.omitted["denied"] - 1
    replayed = json.loads(ctx.artifact_store.read_bytes(post.report.sha256))
    assert replayed["omitted"] == pre.omitted
    pre_files = {path.name: path.read_bytes() for path in sorted(pre.output_dir.iterdir())}
    post_files = {path.name: path.read_bytes() for path in sorted(post.output_dir.iterdir())}
    assert pre_files == post_files
    impacted_ids = {entry.object_id for entry in impact.entries} | {src01}
    for data in post_files.values():
        for object_id in impacted_ids:
            assert object_id.encode() not in data
        assert b"01-parallel-distill" not in data

    # 6. New work fails closed: no run, exactly one POLICY_DENIED audit event.
    audit_before = len(repo.list_audit_events())
    runs_before = repo.count_runs()
    with pytest.raises(PolicyDenied):
        LexicalService(ctx).induce_lexicon(
            world.aligned.token_run_id,
            method="alignment_cooccurrence@0.1.0",
            target_language=LANGUAGE,
            contact_language=CONTACT,
        )
    denials = _audit_denials(ctx, audit_before)
    assert len(denials) == 1
    assert denials[0].details == {"operation": "distill_lexicon", "decision": "deny"}
    assert repo.count_runs() == runs_before
    # Revoked targets cannot receive human decisions, with no persisted side effects.
    before_review = state_counts(ctx)
    with pytest.raises(PolicyDenied):
        task = _review_service(ctx).create_task(
            canoa01,
            task_type=ReviewTaskType.LEXICAL_SENSE,
            required_role=ROLE,
            evidence_item_ids=world.evidence_ids(canoa01),
        )
        _review_service(ctx).record_decision(task.id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE)
    assert state_counts(ctx) == before_review


def test_p12b_revoke_export_source(ctx: AppContext, tmp_path: Path) -> None:
    """Revoking the export source makes its artifacts ineligible; re-export fails closed."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S7)
    repo = ctx.repo
    src_export = world.source(EXPORT_KEY)
    pre = world.export_pre
    assert pre is not None
    report_payload = json.loads(ctx.artifact_store.read_bytes(pre.report.sha256))
    assert {entry["name"] for entry in report_payload["files"]} == {
        "entries.csv",
        "languages.csv",
        "senses.csv",
        "Dictionary-metadata.json",
        "sources.bib",
    }
    assert lineage_eligibility(repo, pre.report.id, Operation.REDISTRIBUTE_DERIVED) is (
        PolicyDecision.ALLOW
    )

    audit_before = len(repo.list_audit_events())
    _revoke(ctx, src_export)
    impact = revocation_impact(repo, src_export)
    for artifact in pre.files:
        assert artifact.id in set(impact.artifacts)
        assert lineage_eligibility(repo, artifact.id, Operation.REDISTRIBUTE_DERIVED) is (
            PolicyDecision.DENY
        )
    assert pre.report.id in set(impact.artifacts)
    assert lineage_eligibility(repo, pre.report.id, Operation.REDISTRIBUTE_DERIVED) is (
        PolicyDecision.DENY
    )

    runs_before = repo.count_runs()
    artifacts_before = repo.count(EntityType.ARTIFACT)
    with pytest.raises(NoEligibleRecords):
        CLDFExporter(ctx).export(language=LANGUAGE, output_dir=tmp_path / "cldf-after")
    assert not (tmp_path / "cldf-after").exists()
    assert repo.count_runs() == runs_before
    assert repo.count(EntityType.ARTIFACT) == artifacts_before
    denials = _audit_denials(ctx, audit_before)
    # One audit event per denying source: the export source is now revoked, and the
    # validated-but-unganted 03/01 rows were `denied` all along.
    assert {str(event.subject_id) for event in denials} == {
        world.source("01-parallel-distill"),
        world.source("03-wordlist"),
        src_export,
    }
    by_source = {str(event.subject_id): event for event in denials}
    assert by_source[src_export].details == {
        "operation": "redistribute_derived",
        "decision": "deny",
    }

    # The already-published bytes are untouched.
    for entry in report_payload["files"]:
        assert (pre.output_dir / str(entry["name"])).read_bytes() == ctx.artifact_store.read_bytes(
            str(entry["sha256"])
        )


# --- invariants ---------------------------------------------------------------------------


def test_observations_immutable_under_lexical_status_changes(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Review decisions, revocation and export change no observation-layer row (I1)."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S10)
    assert world.fingerprint_s5 == world.fingerprint_s10


def test_rerun_is_idempotent(ctx: AppContext, tmp_path: Path) -> None:
    """Rerunning S3-S5 reuses every run and writes nothing (I2)."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S5)
    before_counts = state_counts(ctx)
    before_runs = ctx.repo.count_runs()

    induce01 = LexicalService(ctx).induce_lexicon(
        world.aligned.token_run_id,
        method="alignment_cooccurrence@0.1.0",
        target_language=LANGUAGE,
        contact_language=CONTACT,
    )
    extract03 = WordlistExtractor(ctx).extract("03-wordlist")
    induce03 = LexicalService(ctx).induce_lexicon(extract03.run.id, method="wordlist_tabular@0.1.0")
    registration = register_source(ctx, LEXICON_DIR / "export-manifest.yaml")
    extract_export = WordlistExtractor(ctx).extract(EXPORT_KEY)
    induce_export = LexicalService(ctx).induce_lexicon(
        extract_export.run.id, method="wordlist_tabular@0.1.0"
    )
    assert induce01.reused and induce01.run.id == world.induce01.run.id
    assert extract03.reused and extract_export.reused
    assert induce03.reused and induce_export.reused
    assert registration.reused
    assert induce01.status_counts == world.induce01.status_counts
    assert induce03.status_counts == world.induce03.status_counts
    assert induce_export.status_counts == world.induce_export.status_counts
    assert state_counts(ctx) == before_counts
    assert ctx.repo.count_runs() == before_runs


def test_lineage_ancestry_is_exact(ctx: AppContext, tmp_path: Path) -> None:
    """Every lexical object descends from exactly its own source and Stage 6 run (I3)."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S7)
    repo = ctx.repo
    run_by_source = {
        "01-parallel-distill": world.induce01.run.id,
        "03-wordlist": world.induce03.run.id,
        EXPORT_KEY: world.induce_export.run.id,
    }
    seen = 0
    for source_key, stage6_run in run_by_source.items():
        source_id = world.source(source_key)
        for lexeme in repo.list_lexemes_by_language(LANGUAGE):
            if ancestor_source_ids(repo, lexeme.id) != [source_id]:
                continue
            seen += 1
            parents = {
                (edge.to_id, edge.kind) for edge in repo.list_lineage_edges(lexeme.id, "out")
            }
            assert (stage6_run, LineageKind.DERIVED_FROM) in parents
            for sense in repo.list_senses_for_lexeme(lexeme.id):
                sense_parents = {
                    (edge.to_id, edge.kind) for edge in repo.list_lineage_edges(sense.id, "out")
                }
                assert (stage6_run, LineageKind.DERIVED_FROM) in sense_parents
    assert seen == 7
    pre = world.export_pre
    assert pre is not None
    for artifact in pre.files:
        assert ancestor_source_ids(repo, artifact.id) == [world.source(EXPORT_KEY)]


def test_distill_only_never_exported(ctx: AppContext, tmp_path: Path) -> None:
    """The only content cells in an export are the redistributable row's (I4)."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S7)
    pre = world.export_pre
    assert pre is not None
    identifier = re.compile(r"^[a-z]+_[0-9A-HJKMNP-TV-Z]{26}$")
    cells: set[str] = set()
    for path in sorted(pre.output_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                cells.update(value for value in row.values() if value is not None)
    dropped = {
        cell
        for cell in cells
        if not cell
        or identifier.fullmatch(cell)
        or cell in {"qaa", CONTACT}
        or cell in world.sources
        or cell.lstrip().startswith("{")
    }
    assert cells - dropped == {"nawa", "rio"}
    forbidden = (
        "kanu",
        "homem",
        "mabi",
        "canoa",
        "tronco",
        "rumi",
        "pajé",
        "wesa-ra",
        "mabi-ki",
        "tesa",
        "Ele sorri",
        "O homem vê a canoa.",
    )
    for path in sorted(pre.output_dir.iterdir()):
        data = path.read_bytes()
        for needle in forbidden:
            assert needle.encode("utf-8") not in data, (path.name, needle)


def _validated_ids(repo: Any) -> set[str]:
    found: set[str] = set()
    for lexeme in repo.list_lexemes_by_language(LANGUAGE):
        if lexeme.status is LifecycleStatus.VALIDATED:
            found.add(lexeme.id)
        for sense in repo.list_senses_for_lexeme(lexeme.id):
            if sense.status is LifecycleStatus.VALIDATED:
                found.add(sense.id)
    return found


def test_no_machine_validation(ctx: AppContext, tmp_path: Path) -> None:
    """Only authorized accept decisions ever create `validated` objects (I5)."""
    world_s5 = _build_m4_world(ctx, tmp_path, until=Stage.S5)
    assert _validated_ids(ctx.repo) == set()
    for induction in (world_s5.induce01, world_s5.induce03, world_s5.induce_export):
        assert "validated" not in induction.status_counts

    world_s6 = _build_m4_world(ctx, tmp_path, until=Stage.S6)
    expected = {
        world_s6.sense("03-wordlist", "mabi", "canoa"),
        world_s6.lex("03-wordlist", "mabi"),
        world_s6.lex(EXPORT_KEY, "nawa"),
        world_s6.sense(EXPORT_KEY, "nawa", "rio"),
        world_s6.lex("01-parallel-distill", "rumi"),
        world_s6.sense("01-parallel-distill", "rumi", "pajé"),
    }
    assert _validated_ids(ctx.repo) == expected


def test_wordlist_lexemes_have_no_alignment_ancestry(ctx: AppContext, tmp_path: Path) -> None:
    """Wordlist path objects never inherit 01 lineage, so revocation cannot reach them (I6)."""
    world = _build_m4_world(ctx, tmp_path, until=Stage.S5)
    repo = ctx.repo
    src01 = world.source("01-parallel-distill")
    src03 = world.source("03-wordlist")
    checked = 0
    for lexeme in repo.list_lexemes_by_language(LANGUAGE):
        ancestors = ancestor_source_ids(repo, lexeme.id)
        if src03 not in ancestors:
            continue
        checked += 1
        assert src01 not in ancestors
        for sense in repo.list_senses_for_lexeme(lexeme.id):
            assert src01 not in ancestor_source_ids(repo, sense.id)
    assert checked == 3
