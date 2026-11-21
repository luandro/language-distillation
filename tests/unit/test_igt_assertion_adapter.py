"""Unit tests for igt_assertion@0.1.0 morphology adapter (M5-PLAN §7.7, Gate 38)."""

from datetime import UTC, datetime

from langpipe.domain.enums import (
    AnalysisKind,
    FeatureAssignmentBasis,
    FormBasis,
    IgtFormat,
    IgtParseStatus,
    LifecycleStatus,
    MorphRole,
    SpanRepresentation,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.igt import IgtMorph, IGTObservation, IgtTierLine, IgtWord
from langpipe.domain.models.observation import Span, TokenOccurrence
from langpipe.languages.base import MorphologyProfile
from langpipe.morphology.adapters.igt_assertion import IgtAssertionInducer
from langpipe.morphology.base import MorphologyInductionInput


def _token(seg_id: str, ordinal: int, surface: str) -> TokenOccurrence:
    raw_span = Span(start=0, end=len(surface), representation=SpanRepresentation.RAW)
    norm_span = Span(start=0, end=len(surface), representation=SpanRepresentation.NORMALIZED)
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id=seg_id,
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ99",
        ordinal=ordinal,
        raw_surface=surface,
        normalized_surface=surface,
        raw_span=raw_span,
        normalized_span=norm_span,
        tokenizer="regex_whitespace@0.1.0",
        created_at=datetime.now(UTC),
    )


def _obs(
    seg_id: str,
    record_ref: str,
    words: list[IgtWord],
    source_id: str | None = None,
) -> IGTObservation:
    src = source_id or new_id(IdPrefix.SOURCE)
    return IGTObservation(
        id=new_id(IdPrefix.IGT_OBSERVATION),
        source_id=src,
        source_object_id=new_id(IdPrefix.SOURCE_OBJECT),
        run_id=new_id(IdPrefix.RUN),
        segment_id=seg_id,
        record_ordinal=0,
        record_ref=record_ref,
        format=IgtFormat.TOOLBOX,
        locator={"line": 1},
        tiers=[IgtTierLine(marker="\\tx", line_number=1, raw="tx line")],
        words=words,
        translations={"por": ["traducao"]},
        parse_status=IgtParseStatus.OK,
        diagnostics=[],
        created_at=datetime.now(UTC),
    )


def test_igt_assertion_single_word_analysis_and_features() -> None:
    inducer = IgtAssertionInducer()
    seg_id = new_id(IdPrefix.SEGMENT)

    # Word: "mabi-ki" = "canoa-ERG"
    w = IgtWord(
        ordinal=0,
        text="mabi-ki",
        morphs=[
            IgtMorph(ordinal=0, text="mabi", boundary_before=None, gloss="canoa"),
            IgtMorph(ordinal=1, text="ki", boundary_before="-", gloss="ERG"),
        ],
    )
    obs = _obs(seg_id, "rec1", [w])
    tok = _token(seg_id, 0, "mabi-ki")

    req = MorphologyInductionInput(
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ99",
        language="qaa",
        tokens=[tok],
        observations=[obs],
        contact_language="por",
    )

    output = inducer.induce(req)
    assert output.words_mapped == 1
    assert len(output.analyses) == 1

    cand = output.analyses[0]
    analysis = cand.analysis
    assert analysis.target_token_id == tok.id
    assert analysis.analysis_kind is AnalysisKind.SEGMENTED
    assert analysis.method == "igt_assertion@0.1.0"
    assert analysis.status is LifecycleStatus.CANDIDATE  # Single observation -> stays candidate

    # 2 segments
    assert len(cand.segments) == 2
    seg0 = cand.segments[0]
    assert seg0.surface == "mabi"
    assert seg0.start == 0
    assert seg0.end == 4
    assert seg0.role is MorphRole.ROOT
    assert seg0.source_gloss == "canoa"

    seg1 = cand.segments[1]
    assert seg1.surface == "ki"
    assert seg1.start == 5
    assert seg1.end == 7
    assert seg1.role is MorphRole.UNKNOWN_BOUND
    assert seg1.source_gloss == "ERG"

    # Feature: local:qaa:ERG
    assert len(cand.features) == 1
    feat_assign = cand.features[0]
    assert feat_assign.segment_id == seg1.id
    assert feat_assign.basis is FeatureAssignmentBasis.IGT_GLOSS

    # Morphemes
    assert len(output.morphemes) == 2
    morpheme_roles = {m.canonical_form: m.role for m in output.morphemes}
    assert morpheme_roles["mabi"] is MorphRole.ROOT
    assert morpheme_roles["ki"] is MorphRole.UNKNOWN_BOUND

    # Lineage edges
    lineage_pairs = {(e.from_id, e.to_id) for e in output.lineage_edges}
    assert (analysis.id, obs.id) in lineage_pairs
    assert (analysis.id, tok.id) in lineage_pairs


def test_igt_assertion_multi_record_promotes_morpheme_and_analysis() -> None:
    """Fixture consequence from M5-PLAN §7.7 / §7.8:

    'wesa' attested in 2 distinct IGT observations promotes to supported,
    and an analysis containing only 'wesa' promotes to supported.
    """
    inducer = IgtAssertionInducer()
    seg1 = new_id(IdPrefix.SEGMENT)
    seg2 = new_id(IdPrefix.SEGMENT)

    w1 = IgtWord(
        ordinal=0,
        text="wesa",
        morphs=[IgtMorph(ordinal=0, text="wesa", boundary_before=None, gloss="ir")],
    )
    w2 = IgtWord(
        ordinal=0,
        text="wesa",
        morphs=[IgtMorph(ordinal=0, text="wesa", boundary_before=None, gloss="ir")],
    )

    obs1 = _obs(seg1, "rec1", [w1], source_id=new_id(IdPrefix.SOURCE))
    obs2 = _obs(seg2, "rec2", [w2], source_id=new_id(IdPrefix.SOURCE))
    tok1 = _token(seg1, 0, "wesa")
    tok2 = _token(seg2, 0, "wesa")

    req = MorphologyInductionInput(
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ99",
        language="qaa",
        tokens=[tok1, tok2],
        observations=[obs1, obs2],
        contact_language="por",
    )

    output = inducer.induce(req)
    assert output.words_mapped == 2

    # 'wesa' morpheme attested in 2 independent observations
    assert len(output.morphemes) == 1
    wesa_morpheme = output.morphemes[0]
    assert wesa_morpheme.canonical_form == "wesa"
    assert wesa_morpheme.status is LifecycleStatus.SUPPORTED

    # Analyses linking wesa promote to supported
    for cand in output.analyses:
        assert cand.analysis.status is LifecycleStatus.SUPPORTED


def test_igt_assertion_underlying_form_produces_no_analysis() -> None:
    inducer = IgtAssertionInducer()
    seg_id = new_id(IdPrefix.SEGMENT)

    # Word has morph "xyz" which cannot be located in token surface "canoa"
    w = IgtWord(
        ordinal=0,
        text="canoa",
        morphs=[IgtMorph(ordinal=0, text="xyz", boundary_before=None, gloss="barco")],
    )
    obs = _obs(seg_id, "rec1", [w])
    tok = _token(seg_id, 0, "canoa")

    req = MorphologyInductionInput(
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ99",
        language="qaa",
        tokens=[tok],
        observations=[obs],
        contact_language="por",
    )

    output = inducer.induce(req)
    assert output.words_mapped == 0
    assert output.words_unmapped["words_unmapped_underlying"] == 1
    assert len(output.analyses) == 0

    # Morpheme is still recorded with form_basis=underlying
    assert len(output.morphemes) == 1
    m = output.morphemes[0]
    assert m.canonical_form == "xyz"
    assert m.form_basis is FormBasis.UNDERLYING


def test_igt_assertion_unknown_gloss_produces_unknown_role() -> None:
    inducer = IgtAssertionInducer()
    seg_id = new_id(IdPrefix.SEGMENT)

    w = IgtWord(
        ordinal=0,
        text="poto",
        morphs=[IgtMorph(ordinal=0, text="poto", boundary_before=None, gloss="?")],
    )
    obs = _obs(seg_id, "rec1", [w])
    tok = _token(seg_id, 0, "poto")

    profile = MorphologyProfile(unknown_gloss_markers=("-", "--", "?", "???", "UNKNOWN"))

    req = MorphologyInductionInput(
        run_id="run_01JGZZZZZZZZZZZZZZZZZZZZ99",
        language="qaa",
        tokens=[tok],
        observations=[obs],
        profile=profile,
        contact_language="por",
    )

    output = inducer.induce(req)
    assert len(output.morphemes) == 1
    m = output.morphemes[0]
    assert m.role is MorphRole.UNKNOWN
    assert m.glosses == {}
