"""Unit tests for `igt_projection@0.1.0` morphology inducer (M5-PLAN §6 WP5.10, Gate 39)."""

from datetime import UTC, datetime

from langpipe.domain.enums import (
    Abstention,
    AllomorphConditioning,
    AnalysisKind,
    EvidenceKind,
    EvidencePolarity,
    FormBasis,
    LifecycleStatus,
    LineageKind,
    MorphRole,
    SpanRepresentation,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.morphology import (
    Allomorph,
    Morpheme,
)
from langpipe.domain.models.observation import Span, TokenOccurrence
from langpipe.languages.base import MorphologyProfile
from langpipe.morphology.adapters.igt_projection import IgtProjectionInducer
from langpipe.morphology.base import (
    MorphologyInductionInput,
    MorphologyInventory,
)
from langpipe.morphology.identity import morpheme_identity_key
from langpipe.morphology.registry import get_morphology_inducer


def _make_morpheme(
    run_id: str,
    form: str,
    role: MorphRole,
    language: str = "und",
    glosses: dict[str, list[str]] | None = None,
    gloss_labels: list[str] | None = None,
    status: LifecycleStatus = LifecycleStatus.CANDIDATE,
) -> Morpheme:
    now = datetime.now(UTC)
    g_labels = gloss_labels or []
    g_dict = glosses or {}
    key = morpheme_identity_key(
        language=language,
        role=role,
        canonical_form=form,
        glosses=g_dict if g_dict else None,
        gloss_labels=g_labels,
    )
    return Morpheme(
        id=new_id(IdPrefix.MORPHEME),
        language=language,
        role=role,
        canonical_form=form,
        form_basis=FormBasis.SURFACE,
        glosses=g_dict,
        gloss_labels=g_labels,
        identity_key=key,
        status=status,
        run_id=run_id,
        created_at=now,
    )


def _make_allomorph(
    run_id: str,
    morpheme_id: str,
    form: str,
    is_zero: bool = False,
    status: LifecycleStatus = LifecycleStatus.CANDIDATE,
) -> Allomorph:
    now = datetime.now(UTC)
    return Allomorph(
        id=new_id(IdPrefix.ALLOMORPH),
        morpheme_id=morpheme_id,
        form=form,
        is_zero=is_zero,
        form_basis=FormBasis.SURFACE,
        conditioning=AllomorphConditioning.UNKNOWN,
        status=status,
        run_id=run_id,
        created_at=now,
    )


def _make_token(
    run_id: str,
    surface: str,
    segment_id: str | None = None,
    ordinal: int = 0,
) -> TokenOccurrence:
    now = datetime.now(UTC)
    seg_id = segment_id or new_id(IdPrefix.SEGMENT)
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id=seg_id,
        ordinal=ordinal,
        raw_surface=surface,
        normalized_surface=surface,
        raw_span=Span(representation=SpanRepresentation.RAW, start=0, end=len(surface)),
        normalized_span=Span(
            representation=SpanRepresentation.NORMALIZED, start=0, end=len(surface)
        ),
        tokenizer="whitespace_punct@0.1.0",
        run_id=run_id,
        created_at=now,
    )


def test_registry_resolves_igt_projection() -> None:
    inducer = get_morphology_inducer("igt_projection")
    assert inducer.name == "igt_projection"
    assert inducer.version == "0.1.0"
    assert inducer.method_id == "igt_projection@0.1.0"


def test_igt_projection_honest_abstention_without_inventory() -> None:
    inducer = IgtProjectionInducer()
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)
    token = _make_token(tok_run, "wesara")
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=None,
    )
    output = inducer.induce(inp)
    assert len(output.analyses) == 0
    assert token.id in output.abstentions
    assert output.abstentions[token.id] is Abstention.INSUFFICIENT_EVIDENCE


def test_igt_projection_split_at_boundary_marks() -> None:
    inducer = IgtProjectionInducer()
    inv_run = new_id(IdPrefix.RUN)
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)

    m_root = _make_morpheme(inv_run, "mabi", MorphRole.ROOT)
    a_root = _make_allomorph(inv_run, m_root.id, "mabi")

    m_bound = _make_morpheme(inv_run, "ki", MorphRole.UNKNOWN_BOUND)
    a_bound = _make_allomorph(inv_run, m_bound.id, "ki")

    inventory = MorphologyInventory(
        run_id=inv_run,
        morphemes=[m_root, m_bound],
        allomorphs=[a_root, a_bound],
    )

    token = _make_token(tok_run, "mabi-ki")
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=inventory,
    )
    output = inducer.induce(inp)

    assert len(output.analyses) == 1
    cand = output.analyses[0]
    assert cand.analysis.analysis_kind is AnalysisKind.SEGMENTED
    assert cand.analysis.status is LifecycleStatus.CANDIDATE
    assert len(cand.segments) == 2

    # Segments match spans
    seg0 = cand.segments[0]
    assert seg0.surface == "mabi"
    assert seg0.start == 0
    assert seg0.end == 4
    assert seg0.morpheme_id == m_root.id
    assert seg0.allomorph_id == a_root.id
    assert seg0.role is MorphRole.ROOT

    seg1 = cand.segments[1]
    assert seg1.surface == "ki"
    assert seg1.start == 5
    assert seg1.end == 7
    assert seg1.morpheme_id == m_bound.id
    assert seg1.allomorph_id == a_bound.id
    assert seg1.role is MorphRole.UNKNOWN_BOUND

    # Invariants: no morphemes or features created
    assert len(output.morphemes) == 0
    assert len(output.allomorphs) == 0
    assert len(output.features) == 0

    # Evidence: morphology_induction supports
    assert len(output.evidence_items) == 1
    evi = output.evidence_items[0]
    assert evi.kind is EvidenceKind.MORPHOLOGY_INDUCTION
    assert evi.polarity is EvidencePolarity.SUPPORTS
    assert evi.independence_group == f"inventory:{inv_run}"
    assert evi.target_id == cand.analysis.id


def test_igt_projection_suffix_stripping_known_stem() -> None:
    inducer = IgtProjectionInducer()
    inv_run = new_id(IdPrefix.RUN)
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)

    m_wesa = _make_morpheme(inv_run, "wesa", MorphRole.ROOT)
    a_wesa = _make_allomorph(inv_run, m_wesa.id, "wesa")

    m_ra = _make_morpheme(inv_run, "ra", MorphRole.UNKNOWN_BOUND)
    a_ra = _make_allomorph(inv_run, m_ra.id, "ra")

    inventory = MorphologyInventory(
        run_id=inv_run,
        morphemes=[m_wesa, m_ra],
        allomorphs=[a_wesa, a_ra],
    )

    token = _make_token(tok_run, "wesara")
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=inventory,
    )
    output = inducer.induce(inp)

    assert len(output.analyses) == 1
    cand = output.analyses[0]
    assert len(cand.segments) == 2
    assert cand.segments[0].surface == "wesa"
    assert cand.segments[0].morpheme_id == m_wesa.id
    assert cand.segments[1].surface == "ra"
    assert cand.segments[1].morpheme_id == m_ra.id


def test_igt_projection_suffix_stripping_unknown_stem() -> None:
    inducer = IgtProjectionInducer()
    inv_run = new_id(IdPrefix.RUN)
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)

    # Only suffix 'ra' is known; stem 'nawa' is NOT in inventory
    m_ra = _make_morpheme(inv_run, "ra", MorphRole.UNKNOWN_BOUND)
    a_ra = _make_allomorph(inv_run, m_ra.id, "ra")

    inventory = MorphologyInventory(
        run_id=inv_run,
        morphemes=[m_ra],
        allomorphs=[a_ra],
    )

    token = _make_token(tok_run, "nawara")
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=inventory,
    )
    output = inducer.induce(inp)

    assert len(output.analyses) == 1
    cand = output.analyses[0]
    assert len(cand.segments) == 2

    # Stem is unknown piece: morpheme_id=None, role=unknown
    stem_seg = cand.segments[0]
    assert stem_seg.surface == "nawa"
    assert stem_seg.morpheme_id is None
    assert stem_seg.allomorph_id is None
    assert stem_seg.role is MorphRole.UNKNOWN

    suf_seg = cand.segments[1]
    assert suf_seg.surface == "ra"
    assert suf_seg.morpheme_id == m_ra.id
    assert suf_seg.role is MorphRole.UNKNOWN_BOUND


def test_igt_projection_prefix_stripping() -> None:
    inducer = IgtProjectionInducer()
    inv_run = new_id(IdPrefix.RUN)
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)

    m_pref = _make_morpheme(inv_run, "ki", MorphRole.CLITIC)
    a_pref = _make_allomorph(inv_run, m_pref.id, "ki")

    inventory = MorphologyInventory(
        run_id=inv_run,
        morphemes=[m_pref],
        allomorphs=[a_pref],
    )

    token = _make_token(tok_run, "kiwesa")
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=inventory,
    )
    output = inducer.induce(inp)

    assert len(output.analyses) == 1
    cand = output.analyses[0]
    assert len(cand.segments) == 2
    assert cand.segments[0].surface == "ki"
    assert cand.segments[0].morpheme_id == m_pref.id
    assert cand.segments[1].surface == "wesa"
    assert cand.segments[1].morpheme_id is None


def test_igt_projection_refuses_stripping_below_min_stem_length() -> None:
    inducer = IgtProjectionInducer()
    inv_run = new_id(IdPrefix.RUN)
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)

    m_ra = _make_morpheme(inv_run, "ra", MorphRole.UNKNOWN_BOUND)
    a_ra = _make_allomorph(inv_run, m_ra.id, "ra")

    inventory = MorphologyInventory(
        run_id=inv_run,
        morphemes=[m_ra],
        allomorphs=[a_ra],
    )

    # Surface 'ara': stripping 'ra' leaves remainder 'a' of length 1 < min_stem_length (2)
    token = _make_token(tok_run, "ara")
    profile = MorphologyProfile(min_stem_length=2)
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        profile=profile,
        inventory=inventory,
    )
    output = inducer.induce(inp)

    # Honest abstention because remainder < min_stem_length
    assert len(output.analyses) == 0
    assert token.id in output.abstentions
    assert output.abstentions[token.id] is Abstention.INSUFFICIENT_EVIDENCE


def test_igt_projection_competing_segmentations_and_cap() -> None:
    inducer = IgtProjectionInducer()
    inv_run = new_id(IdPrefix.RUN)
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)

    # Surface 'wesara' can be stripped with suffix 'ra' (stem 'wesa')
    # and suffix 'a' (stem 'wesar')
    m_ra = _make_morpheme(inv_run, "ra", MorphRole.UNKNOWN_BOUND)
    a_ra = _make_allomorph(inv_run, m_ra.id, "ra")

    m_a = _make_morpheme(inv_run, "a", MorphRole.CLITIC)
    a_a = _make_allomorph(inv_run, m_a.id, "a")

    inventory = MorphologyInventory(
        run_id=inv_run,
        morphemes=[m_ra, m_a],
        allomorphs=[a_ra, a_a],
    )

    token = _make_token(tok_run, "wesara")
    # Cap at 1
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=inventory,
        policy={"cap": 1},
    )
    output = inducer.induce(inp)

    # Exactly capped at 1 analysis
    assert len(output.analyses) == 1

    # Now with default cap (8), competing segmentations are emitted:
    # 1. wesa + ra
    # 2. wesar + a
    # 3. wes + a + ra
    inp_uncapped = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=inventory,
    )
    output_uncapped = inducer.induce(inp_uncapped)
    assert len(output_uncapped.analyses) == 3
    sigs = {c.analysis.signature for c in output_uncapped.analyses}
    assert len(sigs) == 3


def test_igt_projection_contradiction_evidence_on_signature_mismatch() -> None:
    inducer = IgtProjectionInducer()
    inv_run = new_id(IdPrefix.RUN)
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)

    m_ra = _make_morpheme(inv_run, "ra", MorphRole.UNKNOWN_BOUND)
    a_ra = _make_allomorph(inv_run, m_ra.id, "ra")

    # Inventory holds an IGT assertion for "wesara" with a different signature
    inventory = MorphologyInventory(
        run_id=inv_run,
        morphemes=[m_ra],
        allomorphs=[a_ra],
        surface_signatures={"wesara": ["asserted_different_sig_001"]},
    )

    token = _make_token(tok_run, "wesara")
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=inventory,
    )
    output = inducer.induce(inp)

    assert len(output.analyses) == 1
    cand = output.analyses[0]

    # Contradiction evidence is present
    contra_items = [e for e in output.evidence_items if e.polarity is EvidencePolarity.CONTRADICTS]
    assert len(contra_items) == 1
    contra = contra_items[0]
    assert contra.target_id == cand.analysis.id
    assert contra.kind is EvidenceKind.MORPHOLOGY_INDUCTION
    assert contra.independence_group == f"inventory:{inv_run}"

    # Score breakdown records contradiction penalty
    assert cand.analysis.score_breakdown is not None
    assert cand.analysis.score_breakdown.penalties.get("contradiction") == 1.0


def test_igt_projection_lineage_edges() -> None:
    inducer = IgtProjectionInducer()
    inv_run = new_id(IdPrefix.RUN)
    tok_run = new_id(IdPrefix.RUN)
    proj_run = new_id(IdPrefix.RUN)

    m_root = _make_morpheme(inv_run, "mabi", MorphRole.ROOT)
    a_root = _make_allomorph(inv_run, m_root.id, "mabi")

    m_bound = _make_morpheme(inv_run, "ki", MorphRole.UNKNOWN_BOUND)
    a_bound = _make_allomorph(inv_run, m_bound.id, "ki")

    inventory = MorphologyInventory(
        run_id=inv_run,
        morphemes=[m_root, m_bound],
        allomorphs=[a_root, a_bound],
    )

    token = _make_token(tok_run, "mabi-ki")
    inp = MorphologyInductionInput(
        run_id=proj_run,
        language="und",
        tokens=[token],
        inventory=inventory,
    )
    output = inducer.induce(inp)

    assert len(output.analyses) == 1
    ana_id = output.analyses[0].analysis.id

    # Lineage edges exist to token and to linked morphemes
    token_edge = [
        e
        for e in output.lineage_edges
        if e.from_id == ana_id and e.to_id == token.id and e.kind is LineageKind.DERIVED_FROM
    ]
    assert len(token_edge) == 1

    m_edges = [
        e
        for e in output.lineage_edges
        if e.from_id == ana_id and e.to_id in (m_root.id, m_bound.id)
    ]
    assert len(m_edges) == 2
