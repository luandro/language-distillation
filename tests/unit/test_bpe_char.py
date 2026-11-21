"""Unit tests for bpe_char@0.1.0 baseline adapter (WP5.11 / Gate 40)."""

from datetime import UTC, datetime

from langpipe.domain.enums import (
    Abstention,
    LifecycleStatus,
    LineageKind,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.observation import TokenOccurrence
from langpipe.morphology.adapters.bpe_char import BpeCharInducer
from langpipe.morphology.base import MorphologyInductionInput
from langpipe.morphology.registry import get_morphology_inducer


def _tok(surface: str, seg_id: str | None = None, ord_idx: int = 0) -> TokenOccurrence:
    actual_seg_id = seg_id if seg_id is not None else new_id(IdPrefix.SEGMENT)
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id=actual_seg_id,
        ordinal=ord_idx,
        raw_surface=surface or " ",
        normalized_surface=surface,
        tokenizer="whitespace@0.1.0",
        run_id=new_id(IdPrefix.RUN),
        created_at=datetime.now(UTC),
    )


def test_bpe_char_registered() -> None:
    inducer = get_morphology_inducer("bpe_char@0.1.0")
    assert isinstance(inducer, BpeCharInducer)
    assert inducer.method_id == "bpe_char@0.1.0"


def test_bpe_char_deterministic_merges() -> None:
    inducer = BpeCharInducer()
    # "low low low lower lowest" -> 'l','o','w' frequent
    tokens = [
        _tok("low", ord_idx=0),
        _tok("low", ord_idx=1),
        _tok("low", ord_idx=2),
        _tok("lower", ord_idx=3),
        _tok("lowest", ord_idx=4),
    ]
    run_id = new_id(IdPrefix.RUN)
    inp = MorphologyInductionInput(
        run_id=run_id,
        language="qaa",
        tokens=tokens,
        policy={"merges": 10},
    )
    out = inducer.induce(inp)
    assert len(out.analyses) == 5

    # Check analyses are candidates, never validated or supported
    for cand in out.analyses:
        assert cand.analysis.status is LifecycleStatus.CANDIDATE
        for seg in cand.segments:
            assert seg.morpheme_id is None
            assert seg.allomorph_id is None
            assert seg.role is None


def test_bpe_char_lexicographical_tie_breaking() -> None:
    inducer = BpeCharInducer()
    # 'ab' and 'cd' appear exactly once.
    # Lexicographically 'a'+'b' < 'c'+'d', so ('a', 'b') merges before ('c', 'd').
    tokens = [_tok("abcd", ord_idx=0)]
    inp = MorphologyInductionInput(
        run_id=new_id(IdPrefix.RUN),
        language="qaa",
        tokens=tokens,
        policy={"merges": 1},
    )
    out = inducer.induce(inp)
    assert len(out.analyses) == 1
    segs = out.analyses[0].segments
    surfaces = [s.surface for s in segs]
    # 'ab' merged, 'c' and 'd' remain separate
    assert surfaces == ["ab", "c", "d"]


def test_bpe_char_merges_cap() -> None:
    inducer = BpeCharInducer()
    tokens = [_tok("abcdefgh", ord_idx=0)]
    # merges=0 -> all individual characters
    inp0 = MorphologyInductionInput(
        run_id=new_id(IdPrefix.RUN),
        language="qaa",
        tokens=tokens,
        policy={"merges": 0},
    )
    out0 = inducer.induce(inp0)
    segs0 = [s.surface for s in out0.analyses[0].segments]
    assert segs0 == ["a", "b", "c", "d", "e", "f", "g", "h"]


def test_bpe_char_empty_surface_abstention() -> None:
    inducer = BpeCharInducer()
    tok_empty = _tok("", ord_idx=0)
    inp = MorphologyInductionInput(
        run_id=new_id(IdPrefix.RUN),
        language="qaa",
        tokens=[tok_empty],
        policy={"merges": 5},
    )
    out = inducer.induce(inp)
    assert len(out.analyses) == 0
    assert tok_empty.id in out.abstentions
    assert out.abstentions[tok_empty.id] is Abstention.INSUFFICIENT_EVIDENCE


def test_bpe_char_lineage_edges() -> None:
    inducer = BpeCharInducer()
    tok = _tok("testing", ord_idx=0)
    inp = MorphologyInductionInput(
        run_id=new_id(IdPrefix.RUN),
        language="qaa",
        tokens=[tok],
        policy={"merges": 3},
    )
    out = inducer.induce(inp)
    assert len(out.analyses) == 1
    ana_id = out.analyses[0].analysis.id

    # Lineage from analysis to token (analysis is derived from token)
    tok_edge = [e for e in out.lineage_edges if e.from_id == ana_id and e.to_id == tok.id]
    assert len(tok_edge) == 1
    assert tok_edge[0].kind is LineageKind.DERIVED_FROM

    # Lineage from analysis to segments
    for seg in out.analyses[0].segments:
        seg_edge = [e for e in out.lineage_edges if e.from_id == ana_id and e.to_id == seg.id]
        assert len(seg_edge) == 1
        assert seg_edge[0].kind is LineageKind.DERIVED_FROM


def test_bpe_char_learns_from_token_types_invariant_to_token_counts() -> None:
    """WP5.11: bpe_char learns from unique token types; varying token occurrences
    does not change merges.
    """
    inducer = BpeCharInducer()
    # Vocabulary has types: "ab", "bc", "cd"
    # In run 1: equal occurrences
    tokens1 = [_tok("ab", ord_idx=0), _tok("bc", ord_idx=1), _tok("cd", ord_idx=2)]
    # In run 2: heavily skewed occurrences (e.g. 100 repetitions of "ab")
    tokens2 = [_tok("ab", ord_idx=i) for i in range(100)] + [
        _tok("bc", ord_idx=100),
        _tok("cd", ord_idx=101),
    ]

    inp1 = MorphologyInductionInput(
        run_id=new_id(IdPrefix.RUN),
        language="qaa",
        tokens=tokens1,
        policy={"merges": 2},
    )
    inp2 = MorphologyInductionInput(
        run_id=new_id(IdPrefix.RUN),
        language="qaa",
        tokens=tokens2,
        policy={"merges": 2},
    )

    out1 = inducer.induce(inp1)
    out2 = inducer.induce(inp2)

    # Segmentations of the common unique types must be identical
    ab1 = [s.surface for s in out1.analyses[0].segments]
    ab2 = [s.surface for s in out2.analyses[0].segments]
    assert ab1 == ab2
    bc1 = [s.surface for s in out1.analyses[1].segments]
    bc2 = [s.surface for s in out2.analyses[100].segments]
    assert bc1 == bc2
