"""Integration tests for the optional Morfessor baseline adapter (WP5.12).

Marked `optional_morphology`, deselected by default in CI (Gate 41).
Run explicitly with:
    uv run pytest -m optional_morphology
"""

from datetime import UTC, datetime

import pytest

from langpipe.domain.enums import Abstention, LifecycleStatus, LineageKind
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.observation import TokenOccurrence
from langpipe.morphology.adapters.morfessor import MorfessorInducer
from langpipe.morphology.base import MorphologyInductionInput
from langpipe.morphology.registry import get_morphology_inducer

pytestmark = pytest.mark.optional_morphology


def _make_token(surface: str, ordinal: int = 0) -> TokenOccurrence:
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id=new_id(IdPrefix.SEGMENT),
        run_id=new_id(IdPrefix.RUN),
        ordinal=ordinal,
        raw_surface=surface,
        normalized_surface=surface,
        token_type="word",
        tokenizer="whitespace@0.1.0",
        created_at=datetime.now(UTC),
    )


def test_morfessor_registry_resolution() -> None:
    inducer = get_morphology_inducer("morfessor_baseline@0.1.0")
    assert isinstance(inducer, MorfessorInducer)
    assert inducer.name == "morfessor_baseline"
    assert inducer.version == "0.1.0"


def test_morfessor_induction_end_to_end() -> None:
    pytest.importorskip("morfessor")

    inducer = MorfessorInducer(seed=42)
    words = [
        "wesa",
        "wesara",
        "wesano",
        "yora",
        "yorara",
        "inon",
        "inora",
    ]
    tokens = [_make_token(w, idx) for idx, w in enumerate(words)]
    tokens.append(_make_token("", len(words)))  # Empty token to test abstention

    req = MorphologyInductionInput(
        run_id=new_id(IdPrefix.RUN),
        tokens=tokens,
        inventory=None,
        language="qaa",
    )

    out = inducer.induce(req)

    assert len(out.analyses) == len(words)
    assert len(out.abstentions) == 1
    assert out.abstentions[tokens[-1].id] is Abstention.INSUFFICIENT_EVIDENCE

    # Check candidate lifecycle invariant: machine output never yields validated
    for cand in out.analyses:
        assert cand.analysis.status is LifecycleStatus.CANDIDATE
        for seg in cand.segments:
            assert seg.morpheme_id is None
            assert seg.allomorph_id is None

    # Lineage edges: analysis -> token and analysis -> segment
    assert len(out.lineage_edges) > len(words)
    ana_to_token = [
        e for e in out.lineage_edges if e.from_id.startswith("mana_") and e.to_id.startswith("tok_")
    ]
    assert len(ana_to_token) == len(words)
    for edge in out.lineage_edges:
        assert edge.kind is LineageKind.DERIVED_FROM


def test_morfessor_deterministic_with_fixed_seed() -> None:
    pytest.importorskip("morfessor")

    words = ["wesara", "wesano", "yorara", "inora"]
    tokens = [_make_token(w, idx) for idx, w in enumerate(words)]

    inducer1 = MorfessorInducer(seed=123)
    inducer2 = MorfessorInducer(seed=123)

    req = MorphologyInductionInput(
        run_id=new_id(IdPrefix.RUN),
        tokens=tokens,
        inventory=None,
        language="qaa",
    )

    out1 = inducer1.induce(req)
    out2 = inducer2.induce(req)

    sigs1 = [c.analysis.signature for c in out1.analyses]
    sigs2 = [c.analysis.signature for c in out2.analyses]
    assert sigs1 == sigs2
