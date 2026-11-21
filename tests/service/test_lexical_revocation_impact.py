"""Revocation impact over lexical lineage (WP4.9, M4-PLAN Gate 25, ADR-0015).

Revoking an ancestor source must make every downstream lexical object ineligible while
mutating no stored state: "affected" means present in `revocation_impact`, "ineligible"
means `lineage_eligibility` returns DENY, and both are computed from the lineage graph.

Each test builds one realistic pipeline world:

- `Sp` (pivot, por) x `St` (target, qaa): ingest -> extract -> normalize -> tokenize ->
  segment align -> token align -> lexical induction (with its report artifact) ->
  review task -> authorized `accept` decision (which validates the Sense).
- `Sb` (bystander): a wordlist source with its own induction chain.
- A shared lexeme backed by the parallel chain *and* by evidence from `Sb`.

Test data is synthetic placeholder text; reports carry identifiers only.
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from langpipe.alignment.base import AlignmentConfig, AlignmentSide
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    LifecycleStatus,
    LineageKind,
    Operation,
    PolicyDecision,
    ReviewDecisionKind,
    ReviewTaskType,
    RunIoRole,
    RunStage,
    SourceStatus,
    SourceType,
)
from langpipe.domain.errors import InvalidLineage, NotFound
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.extraction.service import extract_source
from langpipe.governance.lineage_policy import (
    ancestor_source_ids,
    effective_decision,
    lineage_eligibility,
)
from langpipe.ingest.wordlist import WordlistExtractor
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.lexicon.service import LexicalService
from langpipe.lineage import RevocationImpact, revocation_impact
from langpipe.normalization.service import normalize_extraction
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.service import ReviewService
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import manifest_data, state_counts, write_manifest, write_origin_file
from tests.service.test_token_alignment_service import _Links

TSV = "text/tab-separated-values"
OPS = (Operation.DIRECT_TRAINING, Operation.REDISTRIBUTE_DERIVED)
REVIEWER = "linguist_1"
ROLE = "community_linguist"
LANGUAGE = "qaa"

# Synthetic placeholder content that must never leak into an impact report (M2 E10).
PIVOT_TEXT = "O homem vê."
TARGET_TEXT = "kanu mabi."
BYSTANDER_WORDLIST = b"qaa\tpor\tnote\ntapi\tcoisa\n"
CONTENT_STRINGS = (
    "kanu",
    "mabi",
    "homem",
    "vê",
    "tapi",
    "coisa",
    '"gloss"',
    '"source_form"',
)
AFFECTED_TYPES = (
    EntityType.LEXEME,
    EntityType.SENSE,
    EntityType.REVIEW_DECISION,
    EntityType.ARTIFACT,
)


@dataclass(frozen=True)
class _World:
    pivot_source: str
    target_source: str
    bystander_source: str
    lexeme: str
    sense: str
    report: str
    task: str
    decision: str
    bystander_lexeme: str
    bystander_sense: str
    bystander_report: str
    # object_id -> {operation: decision}, captured before any revocation.
    pre_eligibility: dict[str, dict[Operation, PolicyDecision]]
    pre_effective: dict[str, dict[Operation, PolicyDecision]]


def _outputs(ctx: AppContext, run_id: str, entity_type: EntityType) -> list[str]:
    return sorted(
        object_id
        for object_id, role in ctx.repo.list_run_io(run_id)
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is entity_type
    )


def _only(ctx: AppContext, run_id: str, entity_type: EntityType) -> str:
    ids = _outputs(ctx, run_id, entity_type)
    assert len(ids) == 1, f"expected one {entity_type} output, found {len(ids)}"
    return ids[0]


def _parallel_side(
    ctx: AppContext, tmp_path: Path, key: str, language: str, text: str
) -> tuple[AlignmentSide, str]:
    """One pipeline side (ingest..tokenize) whose policy allows redistribution overrides.

    The baseline matrix denies `REDISTRIBUTE_DERIVED` in every mode, so the fixture
    sources carry an explicit allow entry: the pre-revocation state is then ALLOW for
    both fixture operations and a revocation flip is observable for each of them.
    """
    relative = f"texts/{key}.tsv"
    write_origin_file(tmp_path, relative, f"ref\t{language}\nT.1\t{text}\n".encode())
    data = manifest_data(
        key=key,
        objects=[{"path": relative, "media_type": TSV}],
        allow=["redistribute_derived"],
    )
    data["source_type"] = SourceType.WORDLIST.value
    data["languages"] = [language]
    source = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml")).source
    ingest_source(ctx, source.id)
    extraction = extract_source(ctx, source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    return AlignmentSide(source.id, language, normalization.run.id), tokenization.run.id


def _build_world(ctx: AppContext, tmp_path: Path) -> _World:
    target_side, target_tokenization = _parallel_side(
        ctx, tmp_path, "wp49-target", LANGUAGE, TARGET_TEXT
    )
    pivot_side, pivot_tokenization = _parallel_side(ctx, tmp_path, "wp49-pivot", "por", PIVOT_TEXT)

    segment_alignment = SegmentAlignmentService(ctx).align(
        target_side, pivot_side, config=AlignmentConfig(namespace="refs")
    )
    token_alignment = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment_alignment.run.id,
        source_tokenization_run_id=target_tokenization,
        target_tokenization_run_id=pivot_tokenization,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    induction = LexicalService(ctx).induce_lexicon(token_alignment.run.id)
    lexeme = _only(ctx, induction.run.id, EntityType.LEXEME)
    sense = _only(ctx, induction.run.id, EntityType.SENSE)
    report = induction.report.id

    # Bystander source with its own separate induction chain.
    relative = "bystander/wordlist.tsv"
    write_origin_file(tmp_path, relative, BYSTANDER_WORDLIST)
    data = manifest_data(
        key="wp49-bystander",
        objects=[{"path": relative, "media_type": TSV}],
        allow=["redistribute_derived"],
    )
    data["source_type"] = SourceType.WORDLIST.value
    data["languages"] = [LANGUAGE, "por"]
    registered = register_source(ctx, write_manifest(tmp_path, data, name="wp49-bystander.yaml"))
    bystander_source = registered.source.id
    wordlist_extraction = WordlistExtractor(ctx).extract(registered.source.key)
    bystander_induction = LexicalService(ctx).induce_lexicon(
        wordlist_extraction.run.id, method="wordlist_tabular@0.1.0"
    )
    bystander_lexeme = _only(ctx, bystander_induction.run.id, EntityType.LEXEME)
    bystander_sense = _only(ctx, bystander_induction.run.id, EntityType.SENSE)
    bystander_report = bystander_induction.report.id

    # The shared lexeme also draws evidence from the bystander source: one observation
    # whose lineage names Sb, wired like the induction adapter wires evidence support.
    run_id = (
        RunRecorder(ctx)
        .start(RunStage.LEXICAL_INDUCTION, "langpipe.test", {}, [bystander_source])
        .id
    )
    now = ctx.clock()
    extra_evidence = EvidenceItem(
        id=ctx.new_id(IdPrefix.EVIDENCE),
        kind=EvidenceKind.DICTIONARY_ASSERTION,
        polarity=EvidencePolarity.SUPPORTS,
        target_id=lexeme,
        source_id=bystander_source,
        run_id=run_id,
        created_at=now,
    )
    with ctx.repo.transaction():
        ctx.repo.add_evidence(extra_evidence)
        for from_id, to_id in ((lexeme, extra_evidence.id), (extra_evidence.id, bystander_source)):
            ctx.repo.add_lineage_edge(
                LineageEdge(
                    id=ctx.new_id(IdPrefix.LINEAGE),
                    from_id=from_id,
                    to_id=to_id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=run_id,
                    created_at=now,
                )
            )

    # Authorized human review validates the sense (invariant 3: the only path to
    # `validated`), leaving the lexeme at its machine-promoted status.
    authority = ReviewAuthorityRegistry()
    authority.register(REVIEWER, ROLE, [LANGUAGE])
    review = ReviewService(
        ctx.repo,
        authority,
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )
    task = review.create_task(
        sense,
        task_type=ReviewTaskType.LEXICAL_SENSE,
        required_role=ROLE,
    )
    result = review.record_decision(task.id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE)
    assert ctx.repo.get_sense(sense).status is LifecycleStatus.VALIDATED

    observed = (lexeme, sense, report, task.id, result.decision.id, bystander_lexeme)
    pre_eligibility = {
        o: {op: lineage_eligibility(ctx.repo, o, op) for op in OPS} for o in observed
    }
    pre_effective = {o: {op: effective_decision(ctx.repo, o, op) for op in OPS} for o in observed}

    return _World(
        pivot_source=pivot_side.source_id,
        target_source=target_side.source_id,
        bystander_source=bystander_source,
        lexeme=lexeme,
        sense=sense,
        report=report,
        task=task.id,
        decision=result.decision.id,
        bystander_lexeme=bystander_lexeme,
        bystander_sense=bystander_sense,
        bystander_report=bystander_report,
        pre_eligibility=pre_eligibility,
        pre_effective=pre_effective,
    )


def _revoke(ctx: AppContext, source_id: str) -> None:
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())


def _state(ctx: AppContext) -> dict[str, int]:
    counts = state_counts(ctx)
    counts["runs"] = ctx.repo.count_runs()
    return counts


def _statuses(ctx: AppContext, world: _World) -> dict[str, object]:
    repo = ctx.repo
    return {
        "lexeme": repo.get_lexeme(world.lexeme).status,
        "sense": repo.get_sense(world.sense).status,
        "bystander_lexeme": repo.get_lexeme(world.bystander_lexeme).status,
        "task": repo.get_review_task(world.task).status,
        "pivot": repo.get_source(world.pivot_source).status,
        "bystander": repo.get_source(world.bystander_source).status,
    }


def _normalized(impact: RevocationImpact) -> dict[str, object]:
    """Backend-neutral shape: counts and depths only, no generated identifiers."""
    return {
        "source_status": impact.source_status.value,
        "revoked": impact.revoked,
        "total": impact.total,
        "validated_affected": len(impact.validated_affected),
        "by_type": {entity.value: len(ids) for entity, ids in impact.by_type.items()},
        "entries": dict(
            sorted(Counter((e.entity_type.value, e.depth) for e in impact.entries).items())
        ),
    }


# Captured per backend by test_backend_parity; the `repo` fixture parametrization runs
# memory before postgres, so the second backend finds the first one's snapshot.
_PARITY: dict[str, dict[str, object]] = {}


# --- 1. transitive reach ---------------------------------------------------------------------


def test_impact_reaches_every_lexical_layer_after_revocation(
    ctx: AppContext, tmp_path: Path
) -> None:
    world = _build_world(ctx, tmp_path)
    _revoke(ctx, world.pivot_source)

    impact = revocation_impact(ctx.repo, world.pivot_source)

    assert impact.revoked is True
    for entity_type in (
        EntityType.SEGMENT,
        EntityType.SEGMENT_ALIGNMENT,
        EntityType.TOKEN_ALIGNMENT_EDGE,
        EntityType.EVIDENCE_ITEM,
        EntityType.LEXEME,
        EntityType.SENSE,
        EntityType.REVIEW_TASK,
        EntityType.REVIEW_DECISION,
        EntityType.ARTIFACT,
    ):
        assert impact.by_type[entity_type], f"no {entity_type.value} in impact"
    entries = {entry.object_id for entry in impact.entries}
    assert all(entry.depth >= 1 for entry in impact.entries)
    # The revoked source and its co-ancestor are ancestors, never descendants.
    assert world.pivot_source not in entries
    assert world.target_source not in entries
    assert not impact.by_type[EntityType.SOURCE]


# --- 2. eligibility flips to DENY ------------------------------------------------------------


def test_affected_objects_become_ineligible_after_revocation(
    ctx: AppContext, tmp_path: Path
) -> None:
    world = _build_world(ctx, tmp_path)
    for object_id in (world.lexeme, world.sense, world.decision, world.report):
        for op in OPS:
            assert world.pre_eligibility[object_id][op] is PolicyDecision.ALLOW

    _revoke(ctx, world.pivot_source)
    impact = revocation_impact(ctx.repo, world.pivot_source)

    affected = {entry.object_id for entry in impact.entries if entry.entity_type in AFFECTED_TYPES}
    assert {world.lexeme, world.sense, world.decision, world.report} <= affected
    for object_id in affected:
        for op in OPS:
            assert lineage_eligibility(ctx.repo, object_id, op) is PolicyDecision.DENY


# --- 3. effective_decision is untouched ------------------------------------------------------


def test_effective_decision_is_unchanged_by_revocation(ctx: AppContext, tmp_path: Path) -> None:
    world = _build_world(ctx, tmp_path)
    _revoke(ctx, world.pivot_source)

    for object_id, expected in world.pre_effective.items():
        for op in OPS:
            assert effective_decision(ctx.repo, object_id, op) is expected[op]


# --- 4. the shared lexeme --------------------------------------------------------------------


def test_shared_lexeme_is_impacted_and_denied(ctx: AppContext, tmp_path: Path) -> None:
    world = _build_world(ctx, tmp_path)
    assert set(ancestor_source_ids(ctx.repo, world.lexeme)) == {
        world.pivot_source,
        world.target_source,
        world.bystander_source,
    }

    _revoke(ctx, world.pivot_source)
    impact = revocation_impact(ctx.repo, world.pivot_source)

    assert world.lexeme in impact.lexemes
    for op in OPS:
        assert lineage_eligibility(ctx.repo, world.lexeme, op) is PolicyDecision.DENY


# --- 5. bystander isolation ------------------------------------------------------------------


def test_bystander_descendants_are_isolated_from_impact(ctx: AppContext, tmp_path: Path) -> None:
    world = _build_world(ctx, tmp_path)

    _revoke(ctx, world.pivot_source)
    impact = revocation_impact(ctx.repo, world.pivot_source)

    reachable = {entry.object_id for entry in impact.entries}
    assert world.bystander_lexeme not in reachable
    assert world.bystander_sense not in reachable
    assert world.bystander_report not in reachable
    for op in OPS:
        assert (
            lineage_eligibility(ctx.repo, world.bystander_lexeme, op)
            is world.pre_eligibility[world.bystander_lexeme][op]
        )


# --- 6. revocation_impact writes nothing -----------------------------------------------------


def test_revocation_impact_writes_nothing(ctx: AppContext, tmp_path: Path) -> None:
    world = _build_world(ctx, tmp_path)
    _revoke(ctx, world.pivot_source)
    state_before = _state(ctx)
    statuses_before = _statuses(ctx, world)

    first = revocation_impact(ctx.repo, world.pivot_source)
    second = revocation_impact(ctx.repo, world.pivot_source)

    assert first == second
    assert _state(ctx) == state_before
    assert _statuses(ctx, world) == statuses_before


# --- 7. validated_affected -------------------------------------------------------------------


def test_validated_affected_names_only_the_validated_sense(ctx: AppContext, tmp_path: Path) -> None:
    world = _build_world(ctx, tmp_path)
    assert ctx.repo.get_lexeme(world.lexeme).status is not LifecycleStatus.VALIDATED

    _revoke(ctx, world.pivot_source)
    impact = revocation_impact(ctx.repo, world.pivot_source)

    assert impact.validated_affected == (world.sense,)


# --- 8. what-if on an unrevoked source -------------------------------------------------------


def test_what_if_report_on_an_unrevoked_source(ctx: AppContext, tmp_path: Path) -> None:
    world = _build_world(ctx, tmp_path)

    impact = revocation_impact(ctx.repo, world.pivot_source)

    assert impact.revoked is False
    assert impact.source_status is SourceStatus.INGESTED
    assert world.lexeme in impact.lexemes
    assert world.sense in impact.senses
    assert world.report in impact.artifacts


# --- 9. error cases --------------------------------------------------------------------------


def test_unknown_id_raises_not_found_and_non_source_raises_invalid_lineage(
    ctx: AppContext, tmp_path: Path
) -> None:
    world = _build_world(ctx, tmp_path)

    with pytest.raises(NotFound):
        revocation_impact(ctx.repo, ctx.new_id(IdPrefix.SOURCE))
    with pytest.raises(InvalidLineage):
        revocation_impact(ctx.repo, world.lexeme)


# --- 10. no content leak ---------------------------------------------------------------------


def test_report_dict_carries_no_source_content(ctx: AppContext, tmp_path: Path) -> None:
    world = _build_world(ctx, tmp_path)
    _revoke(ctx, world.pivot_source)

    rendered = json.dumps(revocation_impact(ctx.repo, world.pivot_source).to_dict())

    for needle in CONTENT_STRINGS:
        assert needle not in rendered, f"content leaked into report: {needle}"


# --- 11. backend parity ----------------------------------------------------------------------


def test_backend_parity(ctx: AppContext, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    world = _build_world(ctx, tmp_path)
    _revoke(ctx, world.pivot_source)

    normalized = _normalized(revocation_impact(ctx.repo, world.pivot_source))
    backend = request.node.callspec.params["repo"]
    other = "postgres" if backend == "memory" else "memory"
    _PARITY[backend] = normalized
    if _PARITY.get(other) is not None:
        assert normalized == _PARITY[other]
