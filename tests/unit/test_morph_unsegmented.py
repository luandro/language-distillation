"""Unit tests for unsegmented baseline morphology inducer (WP5.8, M5-PLAN §6, Gate 37)."""

from datetime import UTC, datetime

from langpipe.domain.enums import (
    Abstention,
    AnalysisKind,
    LifecycleStatus,
    LineageKind,
    SpanRepresentation,
)
from langpipe.domain.models.observation import Span, TokenOccurrence
from langpipe.morphology.adapters.unsegmented import UnsegmentedInducer
from langpipe.morphology.base import MorphologyInductionInput
from langpipe.morphology.spans import check_analysis


def _token(
    token_id: str,
    raw_surface: str,
    normalized_surface: str | None = None,
    ordinal: int = 0,
) -> TokenOccurrence:
    raw_span = Span(start=0, end=len(raw_surface), representation=SpanRepresentation.RAW)
    norm_span = None
    if normalized_surface is not None:
        norm_span = Span(
            start=0, end=len(normalized_surface), representation=SpanRepresentation.NORMALIZED
        )
    return TokenOccurrence(
        id=token_id,
        segment_id="seg_01JGZZZZZZZZZZZZZZZZZZZZ01",
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ01",
        ordinal=ordinal,
        raw_surface=raw_surface,
        normalized_surface=normalized_surface,
        raw_span=raw_span,
        normalized_span=norm_span,
        tokenizer="regex_whitespace@0.1.0",
        created_at=datetime.now(UTC),
    )


def test_unsegmented_inducer_single_token() -> None:
    inducer = UnsegmentedInducer()
    tok = _token("tok_01JGZZZZZZZZZZZZZZZZZZZZ01", "wesa", "wesa")

    req = MorphologyInductionInput(
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ99",
        language="qaa",
        tokens=[tok],
    )

    output = inducer.induce(req)

    assert len(output.analyses) == 1
    candidate = output.analyses[0]
    analysis = candidate.analysis
    assert analysis.target_token_id == tok.id
    assert analysis.analysis_kind is AnalysisKind.UNSEGMENTED
    assert analysis.method == "unsegmented@0.1.0"
    assert analysis.abstention is Abstention.INSUFFICIENT_EVIDENCE
    assert analysis.status is LifecycleStatus.CANDIDATE
    assert analysis.surface == "wesa"
    assert analysis.score_breakdown is not None
    assert analysis.score_breakdown.overall == 0.0

    # Exactly one segment
    assert len(candidate.segments) == 1
    segment = candidate.segments[0]
    assert segment.ordinal == 0
    assert segment.start == 0
    assert segment.end == 4
    assert not segment.is_zero
    assert segment.surface == "wesa"
    assert segment.morpheme_id is None
    assert segment.role is None
    assert segment.analysis_id == analysis.id

    # No features or morphemes
    assert len(candidate.features) == 0
    assert len(output.morphemes) == 0
    assert len(output.allomorphs) == 0
    assert len(output.features) == 0
    assert len(output.evidence_items) == 0

    # Lineage edge: analysis -> token
    assert len(output.lineage_edges) == 1
    edge = output.lineage_edges[0]
    assert edge.from_id == analysis.id
    assert edge.to_id == tok.id
    assert edge.kind is LineageKind.DERIVED_FROM
    assert edge.run_id == req.run_id

    # Abstention map
    assert output.abstentions == {tok.id: Abstention.INSUFFICIENT_EVIDENCE}

    # Invariant verification
    check_analysis(analysis, list(candidate.segments), ())


def test_unsegmented_inducer_fallback_to_raw_surface() -> None:
    inducer = UnsegmentedInducer()
    tok = _token("tok_01JGZZZZZZZZZZZZZZZZZZZZ02", "canoa", normalized_surface=None)

    req = MorphologyInductionInput(
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ99",
        language="por",
        tokens=[tok],
    )

    output = inducer.induce(req)
    assert len(output.analyses) == 1
    candidate = output.analyses[0]
    assert candidate.analysis.surface == "canoa"
    assert candidate.analysis.span_representation is SpanRepresentation.RAW
    assert candidate.segments[0].surface == "canoa"
    assert candidate.segments[0].start == 0
    assert candidate.segments[0].end == 5
    check_analysis(candidate.analysis, list(candidate.segments), ())


def test_unsegmented_inducer_multiple_tokens_preserves_order_and_lineage() -> None:
    inducer = UnsegmentedInducer()
    toks = [
        _token(f"tok_01JGZZZZZZZZZZZZZZZZZZZZ{i:02d}", f"word{i}", f"word{i}", ordinal=i)
        for i in range(5)
    ]
    req = MorphologyInductionInput(
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ99",
        language="qaa",
        tokens=toks,
    )
    output = inducer.induce(req)

    assert len(output.analyses) == 5
    assert len(output.lineage_edges) == 5
    assert len(output.abstentions) == 5

    for tok, candidate, edge in zip(toks, output.analyses, output.lineage_edges, strict=True):
        assert candidate.analysis.target_token_id == tok.id
        assert edge.from_id == candidate.analysis.id
        assert edge.to_id == tok.id
        assert output.abstentions[tok.id] is Abstention.INSUFFICIENT_EVIDENCE
