"""M3 golden exact graph and null evidence contracts.

Source 01 (``01-parallel-distill``) is the unchanged registered bilingual fixture: extraction with
``tsv_sentences@0.1.0`` produces the real 1:2 membership on TXT.1.4 and preserves ``wesa-ra`` as
one occurrence on TXT.1.3. The standalone null challenge uses the synthetic permission-safe
``tests/golden/fixture/alignment`` source with ``direct`` policy, so it alone can be benchmarked
under ``Operation.EVALUATION``. Token links come only from the test-injected
``MockTokenAligner`` with explicit matrices; no statistical output is asserted.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from langpipe.alignment.base import AlignmentConfig, AlignmentSide
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    AlignmentDirection,
    AlignmentMode,
    ArtifactKind,
    LineageKind,
    Operation,
    RunIoRole,
    RunStage,
    SourceStatus,
)
from langpipe.domain.errors import AlignmentFailed, PolicyDenied
from langpipe.domain.hashing import canonical_json, sha256_bytes
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import Artifact
from langpipe.evaluation.alignment import GoldAlignment
from langpipe.evaluation.service import BenchmarkService
from langpipe.extraction.service import extract_source
from langpipe.governance.guard import require_all
from langpipe.governance.lineage_policy import ancestor_source_ids
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.lineage.impact import impact_of
from langpipe.normalization.service import normalize_extraction
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.service import tokenize_normalization
from tests.fixtures.alignment import MockTokenAligner
from tests.golden.normalize_m3 import normalize_m3_snapshot
from tests.service.manifests import state_counts

GOLDEN = Path(__file__).parent
FIXTURE = GOLDEN / "fixture"
EXPECTED = GOLDEN / "expected" / "m3"
PARALLEL_DIR = FIXTURE / "sources" / "01-parallel-distill"
NULL_DIR = FIXTURE / "alignment"
GOLD_PATH = NULL_DIR / "gold.v1.json"
UPDATE_ENV = "LANGPIPE_UPDATE_GOLDEN"
UPDATE_MESSAGE = "golden files rewritten; review the diff and commit intentionally"
DEFAULT_TOKENIZER = "whitespace_punct@0.1.0"
NULL_REF = "NULL.1"
TSV_EXTRACTOR = "tsv@0.1.0"
SENTENCES_EXTRACTOR = "tsv_sentences@0.1.0"

# One forward/reverse pair of zero-based index pairs per segment alignment group id.
_LinksMap = dict[str, tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]]


class _M3Flow:
    """One registered bilingual source with its pinned normalization and tokenization runs."""

    def __init__(self, registration: RegistrationResult, normalization, tokenization) -> None:
        self.registration = registration
        self.normalization = normalization
        self.tokenization = tokenization

    @property
    def source_id(self) -> str:
        return self.registration.source.id

    @property
    def normalization_run_id(self) -> str:
        return self.normalization.run.id

    @property
    def tokenization_run_id(self) -> str:
        return self.tokenization.run.id

    def side(self, language: str) -> AlignmentSide:
        return AlignmentSide(self.source_id, language, self.normalization_run_id)

    def segments(self, repo, language: str) -> list[Any]:
        return [
            item
            for item in repo.list_segments_for_run(self.normalization_run_id)
            if item.language == language
        ]

    def segment_by_ref(self, repo, language: str, ref: str) -> Any:
        return next(
            item for item in self.segments(repo, language) if item.locator.get("ref") == ref
        )

    def tokens(self, repo, segment_id: str) -> list[Any]:
        """Occurrences of one segment restricted to the pinned tokenization run."""
        return [
            token
            for token in repo.list_tokens(segment_id)
            if token.run_id == self.tokenization_run_id
        ]

    def groups(self, repo, segment_run_id: str) -> list[Any]:
        return repo.list_segment_alignments_for_run(segment_run_id)


class _Aligned:
    """Stage 4 and Stage 5 summaries of one flow plus the persisted segment groups."""

    def __init__(self, segment, token, alignments) -> None:
        self.segment = segment
        self.token = token
        self.alignments = alignments

    @property
    def segment_run_id(self) -> str:
        return self.segment.run.id

    @property
    def token_run_id(self) -> str:
        return self.token.run.id


def _build_bilingual(ctx: AppContext, manifest_path: Path, *, extractor: str) -> _M3Flow:
    """Register, ingest, extract, normalize and tokenize one bilingual source."""
    registration = register_source(ctx, manifest_path)
    ingest_source(ctx, registration.source.id)
    extraction = extract_source(ctx, registration.source.id, extractor=extractor)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    return _M3Flow(registration, normalization, tokenization)


def _parallel_flow(ctx: AppContext) -> _M3Flow:
    """The unchanged fixture source 01 through the opt-in sentence TSV extractor."""
    return _build_bilingual(ctx, PARALLEL_DIR / "manifest.yaml", extractor=SENTENCES_EXTRACTOR)


def _null_flow(ctx: AppContext) -> _M3Flow:
    """The synthetic permission-safe null challenge through the default TSV extractor."""
    return _build_bilingual(ctx, NULL_DIR / "null-token-manifest.yaml", extractor=TSV_EXTRACTOR)


def _stage4(ctx: AppContext, flow: _M3Flow):
    return SegmentAlignmentService(ctx).align(
        flow.side("qaa"), flow.side("por"), config=AlignmentConfig(namespace="tsv")
    )


def _links_only_first(alignment_ids: Sequence[str]) -> _LinksMap:
    """Explicit mock matrix linking index 0 to index 0 in both directions."""
    return {alignment_id: (((0, 0),), ((0, 0),)) for alignment_id in alignment_ids}


def _parallel_links(ctx: AppContext, flow: _M3Flow) -> _LinksMap:
    """Explicit mock matrix: 0 -> 0 everywhere except the TXT.1.3 whole-token null."""
    links: _LinksMap = {}
    for alignment in _groups(ctx, _stage4(ctx, flow).run.id):
        surfaces = [
            token.raw_surface
            for segment_id in alignment.source_segment_ids
            for token in flow.tokens(ctx.repo, segment_id)
        ]
        links[alignment.id] = ((), ()) if "wesa-ra" in surfaces else (((0, 0),), ((0, 0),))
    return links


def _groups(ctx: AppContext, segment_run_id: str) -> list[Any]:
    return ctx.repo.list_segment_alignments_for_run(segment_run_id)


def _flow_tokens(ctx: AppContext, flow: _M3Flow, segment_ids: set[str]) -> set[str]:
    """Every occurrence of one flow under its pinned tokenization run for the given segments."""
    return {token.id for segment_id in segment_ids for token in flow.tokens(ctx.repo, segment_id)}


def _align(ctx: AppContext, flow: _M3Flow, links: _LinksMap) -> _Aligned:
    """Run Stage 4 then Stage 5 with the explicit test-injected mock token aligner."""
    segment = _stage4(ctx, flow)
    alignments = _groups(ctx, segment.run.id)
    token = TokenAlignmentService(
        ctx, aligners=VersionedRegistry((MockTokenAligner(links),))
    ).align(
        segment.run.id,
        source_tokenization_run_id=flow.tokenization_run_id,
        target_tokenization_run_id=flow.tokenization_run_id,
        method="mock@0.1.0",
        config=AlignmentConfig(namespace="tsv"),
    )
    return _Aligned(segment, token, alignments)


def _register_gold(ctx: AppContext, gold: GoldAlignment, source_id: str) -> Artifact:
    """Persist a frozen gold artifact as a governed evaluation input for one source."""
    stored = ctx.artifact_store.put_bytes(canonical_json(gold.model_dump(mode="json")).encode())
    recorder = RunRecorder(ctx)
    run = recorder.start(
        RunStage.EVALUATION,
        "golden.m3.gold",
        {"fixture": "m3", "sha256": stored.sha256},
        [source_id],
    )
    artifact = Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.ALIGNMENT_FILE,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=AccessClass.PUBLIC,
        schema_name=GoldAlignment.SCHEMA_NAME,
        schema_version=GoldAlignment.SCHEMA_VERSION,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_artifact(artifact)
        ctx.repo.add_run_io(run.id, source_id, RunIoRole.INPUT)
        ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=artifact.id,
                to_id=source_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )
        recorder.succeed(run.id)
    return artifact


def _frozen_gold() -> GoldAlignment:
    """The committed frozen gold; its selectors stay ID-free and portable."""
    return GoldAlignment.model_validate_json(GOLD_PATH.read_bytes())


def _benchmark(ctx: AppContext, flow: _M3Flow, token_run_id: str):
    """Benchmark one token run against the frozen gold registered for this source."""
    gold = _register_gold(ctx, _frozen_gold(), flow.source_id)
    return BenchmarkService(ctx).evaluate(token_run_id, gold.id), gold


def _write_expected(snapshot: dict[str, Any]) -> None:
    EXPECTED.mkdir(parents=True, exist_ok=True)
    for name, value in snapshot.items():
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (EXPECTED / f"{name}.json").write_text(text, encoding="utf-8")


def test_golden_m3_snapshot(ctx: AppContext) -> None:
    """Four fixture rows become four structural groups, including the real 1:2 TXT.1.4."""
    parallel = _parallel_flow(ctx)
    aligned = _align(ctx, parallel, _parallel_links(ctx, parallel))
    # Source 01 is distill_only and its policy allows no evaluation; only the synthetic direct
    # null source produces the benchmark report.
    null_flow = _null_flow(ctx)
    null_aligned = _align(
        ctx,
        null_flow,
        _links_only_first([group.id for group in _groups(ctx, _stage4(ctx, null_flow).run.id)]),
    )
    benchmark, _gold = _benchmark(ctx, null_flow, null_aligned.token_run_id)
    snapshot = normalize_m3_snapshot(
        ctx,
        [parallel.source_id],
        aligned.segment_run_id,
        aligned.token_run_id,
        benchmark.run.id,
        auxiliary_flows=((null_aligned.segment_run_id, null_aligned.token_run_id),),
    )
    if os.environ.get(UPDATE_ENV) == "1":
        _write_expected(snapshot)
        pytest.fail(UPDATE_MESSAGE)
    for name, value in snapshot.items():
        expected = json.loads((EXPECTED / f"{name}.json").read_text(encoding="utf-8"))
        assert value == expected, name


def test_txt14_is_actual_one_to_two_members(ctx: AppContext) -> None:
    """TXT.1.4 is exactly one qaa segment and two ordered por segments in one group."""
    flow = _parallel_flow(ctx)
    alignments = _groups(ctx, _stage4(ctx, flow).run.id)
    members = [
        group
        for group in alignments
        if len(group.source_segment_ids) == 1 and len(group.target_segment_ids) == 2
    ]
    assert len(members) == 1
    source_members = [ctx.repo.get_segment(item) for item in members[0].source_segment_ids]
    target_members = [ctx.repo.get_segment(item) for item in members[0].target_segment_ids]
    assert [item.language for item in source_members] == ["qaa"]
    assert [item.language for item in target_members] == ["por", "por"]
    assert [item.locator.get("ref") for item in source_members] == ["TXT.1.4"]
    assert [item.locator.get("ref") for item in target_members] == ["TXT.1.4", "TXT.1.4"]
    assert [item.locator.get("sentence_part") for item in target_members] == [0, 1]
    assert members[0].status.value == "structural"


def test_txt13_no_suffix_token_fabricated(ctx: AppContext) -> None:
    """`wesa-ra` stays one occurrence and remains unaligned without any NULL edge."""
    flow = _parallel_flow(ctx)
    aligned = _align(ctx, flow, _parallel_links(ctx, flow))
    txt13 = flow.segment_by_ref(ctx.repo, "qaa", "TXT.1.3")
    occurrences = flow.tokens(ctx.repo, txt13.id)
    target_segment = flow.segment_by_ref(ctx.repo, "por", "TXT.1.3")
    target_tokens = flow.tokens(ctx.repo, target_segment.id)
    assert len(target_tokens) == 7
    wesa = [item for item in occurrences if item.raw_surface == "wesa-ra"]
    assert len(wesa) == 1
    assert not any(item.raw_surface == "-ra" for item in occurrences)
    assert wesa[0].tokenizer == DEFAULT_TOKENIZER
    edges = ctx.repo.list_token_alignment_edges_for_run(aligned.token_run_id)
    assert not any(item.source_token_id == wesa[0].id for item in edges)
    assert all(edge.target_token_id is not None for edge in edges)
    report = json.loads(ctx.artifact_store.read_bytes(aligned.token.report.sha256))
    group = next(item for item in report["groups"] if wesa[0].id in item["source_token_ids"])
    assert group["unaligned_source_ids"] == [item.id for item in occurrences]
    assert group["unaligned_target_ids"] == [item.id for item in target_tokens]


def test_standalone_ra_spelling_preserves_two_unaligned_occurrences(ctx: AppContext) -> None:
    """`foo` aligns to `bar`; `-` and `ra` keep separate occurrence IDs in the null complement."""
    flow = _null_flow(ctx)
    source_segment = flow.segment_by_ref(ctx.repo, "qaa", NULL_REF)
    target_segment = flow.segment_by_ref(ctx.repo, "por", NULL_REF)
    source_tokens = flow.tokens(ctx.repo, source_segment.id)
    target_tokens = flow.tokens(ctx.repo, target_segment.id)
    assert [item.raw_surface for item in source_tokens] == ["foo", "-", "ra"]
    assert [item.raw_surface for item in target_tokens] == ["bar"]
    aligned = _align(
        ctx,
        flow,
        _links_only_first([group.id for group in _groups(ctx, _stage4(ctx, flow).run.id)]),
    )
    edges = [
        edge
        for edge in ctx.repo.list_token_alignment_edges_for_run(aligned.token_run_id)
        if edge.direction is AlignmentDirection.SYMMETRIZED
    ]
    assert {(edge.source_token_id, edge.target_token_id) for edge in edges} == {
        (source_tokens[0].id, target_tokens[0].id)
    }
    payload = json.loads(ctx.artifact_store.read_bytes(aligned.token.report.sha256))
    report_group = next(
        item for item in payload["groups"] if source_tokens[0].id in item["source_token_ids"]
    )
    assert report_group["unaligned_source_ids"] == [source_tokens[1].id, source_tokens[2].id]
    assert report_group["index_pairs"]["symmetrized"] == [
        [source_tokens[0].id, target_tokens[0].id]
    ]
    assert report_group["unaligned_target_ids"] == []
    assert all(
        edge.source_token_id is not None and edge.target_token_id is not None for edge in edges
    )
    assert source_tokens[1].id != source_tokens[2].id


def test_distill_only_alignment_outputs_are_trainable(ctx: AppContext) -> None:
    """M3 outputs of a distill_only source train under ADR-0025; egress stays closed."""
    flow = _parallel_flow(ctx)
    aligned = _align(ctx, flow, _parallel_links(ctx, flow))
    outputs = [
        *ctx.repo.list_segment_alignments_for_run(aligned.segment_run_id),
        *ctx.repo.list_token_alignment_edges_for_run(aligned.token_run_id),
        aligned.segment.report,
        aligned.token.report,
    ]
    assert aligned.segment.report is not None and aligned.token.report is not None
    for value in outputs:
        ancestors = set(ancestor_source_ids(ctx.repo, value.id))
        assert ancestors == {flow.source_id}
        policies = {
            source_id: ctx.repo.get_policy(ctx.repo.get_source(source_id).policy_id)
            for source_id in ancestors
        }
        require_all(policies, Operation.DIRECT_TRAINING)
        with pytest.raises(PolicyDenied):
            require_all(policies, Operation.THIRD_PARTY_API)


def test_evaluation_allowed_on_distill_only_parallel_source(ctx: AppContext) -> None:
    """A distill_only label no longer blocks evaluation (ADR-0025)."""
    flow = _parallel_flow(ctx)
    policies = {flow.source_id: flow.registration.policy}
    # Evaluation and training are allowed at baseline; outward egress stays denied.
    require_all(policies, Operation.EVALUATION)
    require_all(policies, Operation.DIRECT_TRAINING)
    with pytest.raises(PolicyDenied):
        require_all(policies, Operation.THIRD_PARTY_API)


def test_standalone_null_benchmark_uses_frozen_gold(ctx: AppContext) -> None:
    """The synthetic null challenge permits evaluation and measures predicted vs gold links."""
    flow = _null_flow(ctx)
    aligned = _align(
        ctx,
        flow,
        _links_only_first([group.id for group in _groups(ctx, _stage4(ctx, flow).run.id)]),
    )
    gold_group = _frozen_gold().groups[0]
    assert gold_group.group_id is None and gold_group.locator_selector is not None
    assert gold_group.locator_selector.namespace == "tsv"
    assert len(gold_group.source_tokens) == 3
    assert len(gold_group.target_tokens) == 1
    benchmark, gold = _benchmark(ctx, flow, aligned.token_run_id)
    metrics = benchmark.metrics
    # Predicted {(0,0)} against sure {(0,0)} and possible {(0,0)}; annotated nulls are 1,2.
    assert metrics.total_predicted == 1
    assert metrics.total_sure == 1
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0
    assert metrics.aer == 0.0
    assert metrics.null_source_annotated == 3
    assert metrics.null_source_tp == 2
    assert metrics.null_source_fp == 0
    assert metrics.null_source_fn == 0
    assert metrics.null_source_precision == 1.0
    assert metrics.null_source_recall == 1.0
    assert "null_source_coverage_incomplete" not in metrics.reasons
    assert metrics.reasons == ("null_target_coverage_incomplete",)
    report = json.loads(ctx.artifact_store.read_bytes(benchmark.report.sha256))
    assert report["protocol"] == "transductive_unsupervised"
    assert report["direction"] == "symmetrized"


def test_gold_rejects_missing_trailing_and_drifted_tokens(
    ctx: AppContext, monkeypatch: Any
) -> None:
    """Exact selector cardinality and component versions are validated before ID binding."""
    flow = _null_flow(ctx)
    aligned = _align(
        ctx,
        flow,
        _links_only_first([group.id for group in _groups(ctx, _stage4(ctx, flow).run.id)]),
    )
    gold = _frozen_gold()
    base = gold.groups[0]
    assert len(base.source_tokens) == 3 and len(base.target_tokens) == 1

    # The production binding check, spied: every golden variant below must reach it and be
    # rejected there, rather than by gold-document schema validation.
    selector_lengths: list[int] = []
    original_match = BenchmarkService._selectors_match

    def spy(
        selectors: tuple[Any, ...],
        tokens: list[Any],
        member_ids: tuple[str, ...],
    ) -> bool:
        selector_lengths.append(len(selectors))
        return original_match(selectors, tokens, member_ids)

    monkeypatch.setattr(BenchmarkService, "_selectors_match", staticmethod(spy))

    def reject(gold_variant: GoldAlignment, expected_lengths: list[int]) -> None:
        """A schema-valid gold document is rejected by the binding check, reaching the spy."""
        GoldAlignment.model_validate_json(gold_variant.model_dump_json())
        selector_lengths.clear()
        with pytest.raises(AlignmentFailed, match="invalid_gold"):
            BenchmarkService(ctx).evaluate(
                aligned.token_run_id,
                _register_gold(ctx, gold_variant, flow.source_id).id,
            )
        # The variant must actually reach the production binding check and be rejected there,
        # with the spy observing the variant's own selector cardinality.
        assert selector_lengths == expected_lengths

    trailing = gold.model_copy(
        update={
            "groups": (
                base.model_copy(
                    update={
                        "source_tokens": (
                            *base.source_tokens,
                            base.source_tokens[0].model_copy(update={"ordinal": 9}),
                        ),
                    }
                ),
            )
        }
    )
    # Both variants must be schema-valid documents on their own: the failure under test is the
    # production selector binding check in BenchmarkService, not a Pydantic model validator.
    GoldAlignment.model_validate_json(trailing.model_dump_json())
    reject(trailing, [4])

    missing = gold.model_copy(
        update={
            "groups": (
                base.model_copy(
                    update={
                        "source_tokens": tuple(base.source_tokens[:1]),
                        # Cardinality shrink first: the retained null indices 1, 2 and the
                        # links must stay in bounds for the one remaining token.
                        "sure_links": ((0, 0),),
                        "possible_links": ((0, 0),),
                        "annotated_null_source": (),
                    }
                ),
            )
        }
    )
    GoldAlignment.model_validate_json(missing.model_dump_json())
    reject(missing, [1])

    drifted = gold.model_copy(
        update={
            "groups": (
                base.model_copy(update={"source_tokenizer_version": "whitespace_punct@9.9.9"}),
            )
        }
    )
    reject(drifted, [3, 1])

    drifted_norm = gold.model_copy(
        update={
            "groups": (
                base.model_copy(update={"source_normalization_version": "default_text@9.9.9"}),
            )
        }
    )
    reject(drifted_norm, [3, 1])


def test_revocation_blocks_alignment_reuse_and_evaluation(ctx: AppContext) -> None:
    """Revocation after publication blocks a reused alignment run and a reused benchmark."""
    flow = _null_flow(ctx)
    aligned = _align(
        ctx,
        flow,
        _links_only_first([group.id for group in _groups(ctx, _stage4(ctx, flow).run.id)]),
    )
    benchmark, gold = _benchmark(ctx, flow, aligned.token_run_id)
    assert benchmark.reused is False

    with ctx.repo.transaction():
        ctx.repo.set_source_status(flow.source_id, SourceStatus.REVOKED, ctx.clock())
    service = SegmentAlignmentService(ctx)
    with pytest.raises(PolicyDenied):
        service.align(flow.side("qaa"), flow.side("por"), config=AlignmentConfig(namespace="tsv"))
    with pytest.raises(PolicyDenied):
        BenchmarkService(ctx).evaluate(aligned.token_run_id, gold.id)


def _expected_group_key(
    method: str, namespace: str, source_ids: Sequence[str], target_ids: Sequence[str]
) -> str:
    """Independently recompute the canonical group key from ADR-0011 / DOMAIN-MODEL inputs.

    The key is the SHA-256 of the canonical JSON of method, mode, namespace, versification and
    the ordered member id lists; it is derived here rather than imported so a change in the
    aligner's own hashing cannot pass unnoticed.
    """
    return sha256_bytes(
        canonical_json(
            {
                "method": method,
                "mode": AlignmentMode.CANONICAL.value,
                "namespace": namespace,
                "versification_id": None,
                "source_segment_ids": list(source_ids),
                "target_segment_ids": list(target_ids),
            }
        ).encode("utf-8")
    )


def test_persisted_group_keys_match_independent_canonical_hash(ctx: AppContext) -> None:
    """Every fixture group key equals an independently computed canonical hash of its members."""
    flow = _parallel_flow(ctx)
    aligned = _align(ctx, flow, _parallel_links(ctx, flow))
    groups = aligned.alignments
    expected_by_ref: dict[str, str] = {}
    for group in groups:
        expected = _expected_group_key(
            group.method, "tsv", group.source_segment_ids, group.target_segment_ids
        )
        assert group.group_key == expected
        source_refs = [
            ctx.repo.get_segment(item).locator.get("ref") for item in group.source_segment_ids
        ]
        expected_by_ref[",".join(source_refs)] = expected
    # TXT.1.4 is the real 1:2 group, so its key must cover one qaa and two ordered por members.
    assert "TXT.1.4" in expected_by_ref

    # Reused runs keep the same keys, so a rerun is detectable as the same evidence.
    again = _parallel_flow(ctx)
    again_aligned = _align(ctx, again, _parallel_links(ctx, again))
    assert again_aligned.segment.reused
    for group in again_aligned.alignments:
        source_refs = [
            ctx.repo.get_segment(item).locator.get("ref") for item in group.source_segment_ids
        ]
        assert group.group_key == expected_by_ref[",".join(source_refs)]

    # A different coordinate set must produce a different key, and the fixture really has
    # distinct coordinate groups, not one key reused across all of them.
    assert len({group.group_key for group in groups}) == len(groups)
    null_flow = _null_flow(ctx)
    null_aligned = _align(
        ctx,
        null_flow,
        _links_only_first([group.id for group in _groups(ctx, _stage4(ctx, null_flow).run.id)]),
    )
    for group in null_aligned.alignments:
        assert group.group_key == _expected_group_key(
            group.method, "tsv", group.source_segment_ids, group.target_segment_ids
        )
    assert {group.group_key for group in null_aligned.alignments}.isdisjoint(
        {group.group_key for group in groups}
    )


def test_group_key_rejects_substituted_members_and_orientations(ctx: AppContext) -> None:
    """Altered member identity or orientation fails the independently recomputed key."""
    flow = _parallel_flow(ctx)
    aligned = _align(ctx, flow, _parallel_links(ctx, flow))
    for group in aligned.alignments:
        expected = _expected_group_key(
            group.method, "tsv", group.source_segment_ids, group.target_segment_ids
        )
        assert group.group_key == expected
        # Reversed orientation is a different correspondence, not the same group.
        reversed_key = _expected_group_key(
            group.method, "tsv", group.target_segment_ids, group.source_segment_ids
        )
        if group.source_segment_ids != group.target_segment_ids:
            assert reversed_key != group.group_key
        # Any altered member id, including a member from another group, fails the check.
        other_ids = [
            member_id
            for candidate in aligned.alignments
            if candidate.id != group.id
            for member_id in (candidate.source_segment_ids + candidate.target_segment_ids)
        ]
        for substitute in other_ids:
            substituted = tuple(
                substitute if index == 0 else member
                for index, member in enumerate(group.source_segment_ids)
            )
            altered = _expected_group_key(
                group.method, "tsv", substituted, group.target_segment_ids
            )
            assert altered != group.group_key


def test_rerun_reuses_m3_ids_and_source_lineage_is_bidirectional(ctx: AppContext) -> None:
    """A repeated pipeline reuses run IDs, and reversed lineage edges never exist."""
    flow = _parallel_flow(ctx)
    aligned = _align(ctx, flow, _parallel_links(ctx, flow))
    edges = ctx.repo.list_token_alignment_edges_for_run(aligned.token_run_id)

    impact = {entry.object_id: entry.entity_type for entry in impact_of(ctx.repo, flow.source_id)}
    for alignment in aligned.alignments:
        assert impact.get(alignment.id) is not None
    for edge in edges:
        assert impact.get(edge.id) is not None
    for artifact in (aligned.segment.report, aligned.token.report):
        assert artifact is not None and impact.get(artifact.id) is not None

    derived_ids = {alignment.id for alignment in aligned.alignments} | {row.id for row in edges}
    for edge in ctx.repo.list_lineage_edges(flow.source_id, "out"):
        assert edge.to_id not in derived_ids
    for source_id in ancestor_source_ids(ctx.repo, aligned.alignments[0].id):
        for edge in ctx.repo.list_lineage_edges(source_id, "out"):
            assert edge.to_id not in derived_ids

    again = _parallel_flow(ctx)
    before_counts = state_counts(ctx)
    again_aligned = _align(ctx, again, _parallel_links(ctx, again))
    assert again_aligned.segment.reused and again_aligned.token.reused
    assert again_aligned.segment_run_id == aligned.segment_run_id
    assert again_aligned.token_run_id == aligned.token_run_id
    assert [row.id for row in again_aligned.alignments] == [row.id for row in aligned.alignments]
    again_edges = ctx.repo.list_token_alignment_edges_for_run(again_aligned.token_run_id)
    assert [row.id for row in again_edges] == [row.id for row in edges]

    # A reused rerun publishes nothing new: every semantic entity, run and lineage edge count
    # stays exactly as it was, so no duplicate group, edge, artifact or lineage row is created.
    after_counts = state_counts(ctx)
    assert after_counts == before_counts
    assert after_counts["segment_alignment"] == len(aligned.alignments)
    assert after_counts["token_alignment_edge"] == len(edges)
    assert after_counts["processing_run"] == before_counts["processing_run"]


def test_no_raw_surface_in_reports(ctx: AppContext) -> None:
    """Allowlisted reports carry identifiers and fixed codes, never source text."""
    flow = _parallel_flow(ctx)
    aligned = _align(ctx, flow, _parallel_links(ctx, flow))
    for artifact in (aligned.segment.report, aligned.token.report):
        assert artifact is not None
        payload = ctx.artifact_store.read_bytes(artifact.sha256)
        for surface in (b"kanu", b"homem", b"wesa-ra", b"Ele sorri"):
            assert surface not in payload


def _parents(ctx: AppContext, object_id: str) -> set[tuple[str, LineageKind]]:
    """Exact outgoing lineage parents as ``(id, kind)`` pairs."""
    return {(edge.to_id, edge.kind) for edge in ctx.repo.list_lineage_edges(object_id, "out")}


def test_lineage_parents_are_exact_for_groups_edges_and_reports(ctx: AppContext) -> None:
    """Every persisted M3 object points derived_from at exactly its own real inputs."""
    flow = _parallel_flow(ctx)
    aligned = _align(ctx, flow, _parallel_links(ctx, flow))
    groups = aligned.alignments
    edges = ctx.repo.list_token_alignment_edges_for_run(aligned.token_run_id)
    segment_members = {
        segment_id for group in groups for segment_id in group.source_segment_ids
    } | {segment_id for group in groups for segment_id in group.target_segment_ids}

    # sal -> exactly its own member segments, one edge per member, never sal -> sal.
    for group in groups:
        expected = {
            (segment_id, LineageKind.DERIVED_FROM)
            for segment_id in (*group.source_segment_ids, *group.target_segment_ids)
        }
        assert _parents(ctx, group.id) == expected

    # tal -> its sal plus both endpoint tokens; a token of a foreign group is never a parent.
    tokens = _flow_tokens(ctx, flow, segment_members)
    for edge in edges:
        assert _parents(ctx, edge.id) == {
            (edge.segment_alignment_id, LineageKind.DERIVED_FROM),
            (edge.source_token_id, LineageKind.DERIVED_FROM),
            (edge.target_token_id, LineageKind.DERIVED_FROM),
        }
        assert edge.source_token_id in tokens
        assert edge.target_token_id in tokens

    # Stage 4 report -> the groups it published and the segments they cover.
    assert aligned.segment.report is not None
    assert _parents(ctx, aligned.segment.report.id) == {
        (group.id, LineageKind.DERIVED_FROM) for group in groups
    } | {(segment_id, LineageKind.DERIVED_FROM) for segment_id in segment_members}

    # Stage 5 report -> the selected groups, their segments/tokens, both published sides and
    # the published edges.
    assert aligned.token.report is not None
    assert _parents(ctx, aligned.token.report.id) == {
        (group.id, LineageKind.DERIVED_FROM) for group in groups
    } | {(segment_id, LineageKind.DERIVED_FROM) for segment_id in segment_members} | {
        (token_id, LineageKind.DERIVED_FROM) for token_id in tokens
    } | {(edge.id, LineageKind.DERIVED_FROM) for edge in edges} | {
        (source_id, LineageKind.DERIVED_FROM)
        for source_id in (flow.side("qaa").source_id, flow.side("por").source_id)
    }


def test_benchmark_report_derives_from_gold_artifact_and_exact_inputs(ctx: AppContext) -> None:
    """The benchmark report points derived_from at exactly the gold artifact and its inputs.

    The expected parent set is constructed independently from the benchmark input contract in
    M3-PLAN §5.4: the gold artifact, the auxiliary (benchmarked) source, the token-alignment run
    that produced the predictions, the segment-alignment run that produced the selected groups,
    the pinned normalization/tokenization runs behind those tokens, the selected groups with
    their member segments and member tokens, and the selected symmetrized edges.
    """
    flow = _null_flow(ctx)
    aligned = _align(
        ctx,
        flow,
        _links_only_first([group.id for group in _groups(ctx, _stage4(ctx, flow).run.id)]),
    )
    benchmark, gold = _benchmark(ctx, flow, aligned.token_run_id)
    groups = _groups(ctx, aligned.segment_run_id)
    symmetrized = [
        edge
        for edge in ctx.repo.list_token_alignment_edges_for_run(aligned.token_run_id)
        if edge.direction is AlignmentDirection.SYMMETRIZED
    ]
    member_segments = {
        segment_id
        for group in groups
        for segment_id in (*group.source_segment_ids, *group.target_segment_ids)
    }
    member_tokens = {
        token.id for segment_id in member_segments for token in flow.tokens(ctx.repo, segment_id)
    }
    segment_run = ctx.repo.get_run(aligned.segment_run_id)
    side_runs = {
        side["normalization_run_id"]
        for side in segment_run.config["sides"]
        if isinstance(side, dict)
    }
    assert side_runs == {flow.normalization_run_id}
    # The benchmark's own input set: the gold artifact, the auxiliary source, the tokenization
    # run that produced the predicted tokens, the segment-alignment run, the side normalization
    # run, the selected groups/segments/tokens and the selected symmetrized edges.
    assert aligned.token_run_id == benchmark.run.config["token_run_id"]
    expected: set[tuple[str, LineageKind]] = {
        (gold.id, LineageKind.DERIVED_FROM),
        (flow.source_id, LineageKind.DERIVED_FROM),
        (flow.tokenization_run_id, LineageKind.DERIVED_FROM),
        (flow.normalization_run_id, LineageKind.DERIVED_FROM),
        (aligned.segment_run_id, LineageKind.DERIVED_FROM),
        (aligned.token_run_id, LineageKind.DERIVED_FROM),
    }
    expected |= {(group.id, LineageKind.DERIVED_FROM) for group in groups}
    expected |= {(segment_id, LineageKind.DERIVED_FROM) for segment_id in member_segments}
    expected |= {(token_id, LineageKind.DERIVED_FROM) for token_id in member_tokens}
    expected |= {(edge.id, LineageKind.DERIVED_FROM) for edge in symmetrized}
    assert _parents(ctx, benchmark.report.id) == expected


def test_lineage_parent_substitution_is_detected(ctx: AppContext, monkeypatch: Any) -> None:
    """A substituted lineage parent is detected by the exact-parent lineage check.

    This detector runs the real comparison used by the benchmark contract against tampered
    parents: ``list_lineage_edges`` for the benchmark report omits the gold artifact, or reports
    a foreign id in its place. The exact-parent equality must fail (AssertionError), and the
    tampered repository read must actually have been exercised.
    """
    flow = _null_flow(ctx)
    aligned = _align(
        ctx,
        flow,
        _links_only_first([group.id for group in _groups(ctx, _stage4(ctx, flow).run.id)]),
    )
    benchmark, gold = _benchmark(ctx, flow, aligned.token_run_id)
    report_id = benchmark.report.id
    original = _parents(ctx, report_id)
    assert (gold.id, LineageKind.DERIVED_FROM) in original

    foreign = _parallel_flow(ctx)
    assert foreign.source_id != flow.source_id
    pristine = ctx.repo.list_lineage_edges
    calls: list[str] = []
    tampered_substitutes: list[str] = []
    substitute = gold.id

    def tampered(object_id: str, direction: str) -> list[LineageEdge]:
        calls.append(object_id)
        edges = list(pristine(object_id, direction))
        if object_id == report_id:
            if substitute == gold.id:
                # Drop the gold artifact parent entirely.
                edges = [
                    edge
                    for edge in edges
                    if not (edge.to_id == gold.id and edge.kind is LineageKind.DERIVED_FROM)
                ]
            else:
                edges = [
                    LineageEdge(
                        id=ctx.new_id(IdPrefix.LINEAGE),
                        from_id=edge.from_id,
                        to_id=substitute,
                        kind=edge.kind,
                        run_id=edge.run_id,
                        created_at=edge.created_at,
                    )
                    if (edge.to_id == gold.id and edge.kind is LineageKind.DERIVED_FROM)
                    else edge
                    for edge in edges
                ]
        return edges

    # Omitting the gold parent and replacing it with a real foreign id must both be detected.
    for substitute in (gold.id, foreign.source_id):
        tampered_substitutes.append(substitute)
        calls.clear()
        monkeypatch.setattr(ctx.repo, "list_lineage_edges", tampered)
        try:
            with pytest.raises(AssertionError):
                assert _parents(ctx, report_id) == original
        finally:
            monkeypatch.undo()
        assert report_id in calls
    assert tampered_substitutes == [gold.id, foreign.source_id]
    assert foreign.source_id not in {parent_id for parent_id, _kind in original}
