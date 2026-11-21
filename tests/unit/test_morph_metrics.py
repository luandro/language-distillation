"""Unit tests for morphology evaluation metrics (WP5.11 / Gate 40)."""

from datetime import UTC, datetime

from langpipe.domain.enums import (
    AnalysisKind,
    LifecycleStatus,
    SpanRepresentation,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.morphology import (
    MorphAnalysis,
    MorphSegment,
    ScoreBreakdown,
)
from langpipe.evaluation.morphology import evaluate_morphology
from langpipe.morphology.spans import segmentation_signature


def _make_analysis(
    token_id: str,
    segments: list[tuple[int, int, str]],
    method: str = "test@0.1.0",
    score_overall: float = 0.5,
    sig: str | None = None,
) -> tuple[MorphAnalysis, list[MorphSegment]]:
    ana_id = new_id(IdPrefix.MORPH_ANALYSIS)
    now = datetime.now(UTC)
    seg_models: list[MorphSegment] = []
    for idx, (st, en, surf) in enumerate(segments):
        seg_models.append(
            MorphSegment(
                id=new_id(IdPrefix.MORPH_SEGMENT),
                analysis_id=ana_id,
                ordinal=idx,
                start=st,
                end=en,
                is_zero=False,
                surface=surf,
                created_at=now,
            )
        )
    bd = ScoreBreakdown(
        policy_version="morph-v1",
        overall=score_overall,
        components={},
        penalties={},
        independence_groups=[],
    )
    kind = AnalysisKind.SEGMENTED if len(segments) > 1 else AnalysisKind.UNSEGMENTED
    computed_sig = sig if (sig and len(sig) == 64) else segmentation_signature(kind, seg_models)
    ana = MorphAnalysis(
        id=ana_id,
        target_token_id=token_id,
        analysis_kind=kind,
        method=method,
        span_representation=SpanRepresentation.NORMALIZED,
        surface="".join(s[2] for s in segments),
        signature=computed_sig,
        status=LifecycleStatus.CANDIDATE,
        score_breakdown=bd,
        run_id=new_id(IdPrefix.RUN),
        created_at=now,
    )
    return ana, seg_models


def test_morphology_metrics_perfect_match() -> None:
    # 2 tokens: "ab" -> "a" + "b", "cde" -> "cd" + "e"
    gold_items = [
        {
            "selector": {"word_ordinal": 0},
            "surface": "ab",
            "segments": [[0, 1], [1, 2]],
            "affix_spans": [[1, 2]],
            "root_span": [0, 1],
        },
        {
            "selector": {"word_ordinal": 1},
            "surface": "cde",
            "segments": [[0, 2], [2, 3]],
            "affix_spans": [[2, 3]],
            "root_span": [0, 2],
        },
    ]

    tok1 = new_id(IdPrefix.TOKEN)
    tok2 = new_id(IdPrefix.TOKEN)
    a1, s1 = _make_analysis(tok1, [(0, 1, "a"), (1, 2, "b")], score_overall=0.8)
    a2, s2 = _make_analysis(tok2, [(0, 2, "cd"), (2, 3, "e")], score_overall=0.9)

    analyses_by_token = {tok1: [a1], tok2: [a2]}
    segs_by_analysis = {a1.id: s1, a2.id: s2}
    token_id_map = {0: tok1, 1: tok2}
    surfaces = {tok1: "ab", tok2: "cde"}

    metrics = evaluate_morphology(
        gold_items=gold_items,
        analyses_by_token=analyses_by_token,
        segments_by_analysis=segs_by_analysis,
        token_id_map=token_id_map,
        token_surfaces=surfaces,
    )

    assert metrics.boundary_precision == 1.0
    assert metrics.boundary_recall == 1.0
    assert metrics.boundary_f1 == 1.0
    assert metrics.exact_accuracy == 1.0
    assert metrics.known_affix_preservation == 1.0
    assert metrics.stem_preservation == 1.0
    assert metrics.over_segmentation_rate == 0.0
    assert metrics.under_segmentation_rate == 0.0
    assert metrics.coverage == 1.0
    assert metrics.abstention_rate == 0.0
    assert metrics.mean_distinct_signatures_per_token == 1.0
    assert metrics.downstream_chrf == "not_applicable"
    assert metrics.downstream_feature_error == "not_applicable"


def test_morphology_metrics_over_segmentation() -> None:
    # Gold: "abc" -> [0, 3] (no cut).
    # Pred: "a" + "b" + "c" -> cuts at 1 and 2.
    gold_items = [
        {
            "selector": {"word_ordinal": 0},
            "surface": "abc",
            "segments": [[0, 3]],
            "affix_spans": [],
            "root_span": [0, 3],
        }
    ]
    tok = new_id(IdPrefix.TOKEN)
    a, s = _make_analysis(tok, [(0, 1, "a"), (1, 2, "b"), (2, 3, "c")])

    metrics = evaluate_morphology(
        gold_items=gold_items,
        analyses_by_token={tok: [a]},
        segments_by_analysis={a.id: s},
        token_id_map={0: tok},
        token_surfaces={tok: "abc"},
    )

    assert metrics.boundary_precision == 0.0
    assert metrics.boundary_recall == 0.0
    assert metrics.boundary_f1 == 0.0
    assert metrics.exact_accuracy == 0.0
    assert metrics.over_segmentation_rate == 1.0
    assert metrics.under_segmentation_rate == 0.0


def test_morphology_metrics_under_segmentation() -> None:
    # Gold: "abc" -> "a" + "b" + "c" (cuts at 1 and 2).
    # Pred: "abc" -> [0, 3] (cuts: none).
    gold_items = [
        {
            "selector": {"word_ordinal": 0},
            "surface": "abc",
            "segments": [[0, 1], [1, 2], [2, 3]],
            "affix_spans": [[1, 2], [2, 3]],
            "root_span": [0, 1],
        }
    ]
    tok = new_id(IdPrefix.TOKEN)
    a, s = _make_analysis(tok, [(0, 3, "abc")])

    metrics = evaluate_morphology(
        gold_items=gold_items,
        analyses_by_token={tok: [a]},
        segments_by_analysis={a.id: s},
        token_id_map={0: tok},
        token_surfaces={tok: "abc"},
    )

    assert metrics.boundary_precision == 0.0
    assert metrics.boundary_recall == 0.0
    assert metrics.boundary_f1 == 0.0
    assert metrics.exact_accuracy == 0.0
    assert metrics.over_segmentation_rate == 0.0
    assert metrics.under_segmentation_rate == 1.0
    assert metrics.known_affix_preservation == 0.0
    assert metrics.stem_preservation == 0.0


def test_morphology_metrics_oracle_selection() -> None:
    # Gold: "abcd" -> "ab" + "cd" (cut at 2).
    # Token has two candidate analyses:
    # 1. "a" + "bcd" (score 0.9 - Top 1, cut at 1 - wrong).
    # 2. "ab" + "cd" (score 0.4 - Lower score, cut at 2 - oracle match!).
    gold_items = [
        {
            "selector": {"word_ordinal": 0},
            "surface": "abcd",
            "segments": [[0, 2], [2, 4]],
            "affix_spans": [[2, 4]],
            "root_span": [0, 2],
        }
    ]
    tok = new_id(IdPrefix.TOKEN)
    a1, s1 = _make_analysis(tok, [(0, 1, "a"), (1, 4, "bcd")], score_overall=0.9)
    a2, s2 = _make_analysis(tok, [(0, 2, "ab"), (2, 4, "cd")], score_overall=0.4)

    metrics = evaluate_morphology(
        gold_items=gold_items,
        analyses_by_token={tok: [a1, a2]},
        segments_by_analysis={a1.id: s1, a2.id: s2},
        token_id_map={0: tok},
        token_surfaces={tok: "abcd"},
    )

    assert metrics.top1_boundary_f1 == 0.0
    assert metrics.oracle_boundary_f1 == 1.0
    assert metrics.mean_distinct_signatures_per_token == 2.0


def test_morphology_metrics_missing_analysis_abstention() -> None:
    gold_items = [
        {
            "selector": {"word_ordinal": 0},
            "surface": "word",
            "segments": [[0, 2], [2, 4]],
        }
    ]
    # No prediction for token
    metrics = evaluate_morphology(
        gold_items=gold_items,
        analyses_by_token={},
        segments_by_analysis={},
        token_id_map={},
        token_surfaces={},
    )
    assert metrics.coverage == 0.0
    assert metrics.abstention_rate == 1.0
    assert metrics.top1_boundary_f1 == 0.0


def test_gold_from_igt_alignment_failure_strict_and_excluded() -> None:
    """Gate 40 finding 2: gold derivation must not invent unsegmented answers on mismatch."""
    import pytest

    from langpipe.domain.enums import IgtFormat, IgtParseStatus, RunStage, RunStatus
    from langpipe.domain.errors import GoldAlignmentError
    from langpipe.domain.models.igt import IgtMorph, IGTObservation, IgtTierLine, IgtWord
    from langpipe.evaluation.morphology import gold_from_igt
    from langpipe.storage.memory import InMemoryRepository
    from tests.contract.builders import make_policy, make_run, make_source, make_source_object

    repo = InMemoryRepository()
    now = datetime.now(UTC)

    policy = make_policy()
    igt_run = make_run(
        stage=RunStage.IGT_IMPORT,
        tool_name="langpipe.igt-import",
        status=RunStatus.SUCCEEDED,
        finished_at=now,
        config={"language": "qaa"},
    )
    source = make_source(policy, igt_run.id, key="src-test-igt")
    sobj = make_source_object(source, igt_run.id)
    obs = IGTObservation(
        id=new_id(IdPrefix.IGT_OBSERVATION),
        source_id=source.id,
        source_object_id=sobj.id,
        run_id=igt_run.id,
        record_ordinal=1,
        record_ref="IGT-FAIL-1",
        format=IgtFormat.TOOLBOX,
        locator={"line": 1},
        tiers=[IgtTierLine(marker="\\tx", line_number=1, raw="tx line")],
        words=[
            # Word 0: Morphemes DO NOT align to surface ("xyz" not in "kano")
            IgtWord(
                ordinal=0,
                text="kano",
                morphs=[
                    IgtMorph(ordinal=0, text="xyz", gloss="MISMATCH"),
                ],
            ),
            # Word 1: Genuinely unanalyzed word in IGT (empty morphs)
            IgtWord(
                ordinal=1,
                text="mano",
                morphs=[],
            ),
            # Word 2: Correctly aligns
            IgtWord(
                ordinal=2,
                text="tano-bo",
                morphs=[
                    IgtMorph(ordinal=0, text="tano", gloss="canoe"),
                    IgtMorph(ordinal=1, text="bo", boundary_before="-", gloss="PL"),
                ],
            ),
        ],
        translations={},
        parse_status=IgtParseStatus.OK,
        diagnostics=[],
        created_at=now,
    )

    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(igt_run)
        repo.add_source(source)
        repo.add_source_object(sobj)
        repo.add_igt_observation(obs)

    # 1. When strict=True, must raise GoldAlignmentError
    with pytest.raises(GoldAlignmentError) as exc_info:
        gold_from_igt(repo, igt_run.id, ["IGT-FAIL-1"], "qaa", strict=True)
    assert "xyz" in str(exc_info.value)
    assert "kano" in str(exc_info.value)

    # 2. When strict=False (default), must explicitly exclude the mismatched word
    gold = gold_from_igt(repo, igt_run.id, ["IGT-FAIL-1"], "qaa", strict=False)

    surfaces = [it["surface"] for it in gold.items]
    # Mismatched "kano" must NOT be in gold items (neither as segmented nor as unsegmented!)
    assert "kano" not in surfaces
    # Genuinely unanalyzed word "mano" IS in gold items as unsegmented
    assert "mano" in surfaces
    mano_item = next(it for it in gold.items if it["surface"] == "mano")
    assert mano_item["segments"] == [[0, 4]]
    # Correctly aligned "tano-bo" IS in gold items
    assert "tano-bo" in surfaces

    # Unresolved record must be preserved in provenance
    assert "unresolved" in gold.provenance
    assert len(gold.provenance["unresolved"]) == 1
    unres = gold.provenance["unresolved"][0]
    assert unres["surface"] == "kano"
    assert unres["morphs"] == ["xyz"]
