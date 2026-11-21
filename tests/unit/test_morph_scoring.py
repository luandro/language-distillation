"""Unit tests for morph-v1 scoring policy (WP5.8, M5-PLAN §7.8, Gate 37)."""

from datetime import UTC, datetime

import pytest

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LifecycleStatus
from langpipe.domain.errors import InvalidTransition
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem
from langpipe.domain.models.morphology import MorphSegment
from langpipe.morphology.scoring import (
    AMBIGUITY,
    BOUNDARY_MARK_SUPPORT,
    CONTRADICTION,
    CROSS_METHOD_AGREEMENT,
    FORM_DIVERSITY,
    IGT_INDEPENDENCE,
    IGT_SUPPORT,
    POLICY_VERSION,
    PROJECTION_SUPPORT,
    UNKNOWN_SEGMENT,
    score_allomorph,
    score_analysis,
    score_morpheme,
)


def _evidence(
    kind: EvidenceKind = EvidenceKind.IGT_ASSERTION,
    polarity: EvidencePolarity = EvidencePolarity.SUPPORTS,
    obs_id: str | None = None,
    source_id: str | None = None,
    independence_group: str | None = None,
    word_form: str | None = None,
) -> EvidenceItem:
    claim: dict[str, object] = {}
    if obs_id:
        claim["igt_observation_id"] = obs_id
    if word_form:
        claim["word_form"] = word_form
    src = source_id or new_id(IdPrefix.SOURCE)
    return EvidenceItem(
        id=new_id(IdPrefix.EVIDENCE),
        kind=kind,
        polarity=polarity,
        target_id=new_id(IdPrefix.MORPHEME),
        source_id=src,
        independence_group=independence_group,
        claim=claim,
        run_id=new_id(IdPrefix.RUN),
        created_at=datetime.now(UTC),
    )


def test_score_morpheme_raw_components_and_penalties_retained() -> None:
    status, breakdown = score_morpheme(
        igt_support=3,
        igt_independence=2,
        form_diversity=4,
        projection_support=1,
        boundary_mark_support=2,
        cross_method_agreement=1,
        contradiction=0,
    )
    assert breakdown.policy_version == POLICY_VERSION
    assert breakdown.components[IGT_SUPPORT] == 3.0
    assert breakdown.components[IGT_INDEPENDENCE] == 2.0
    assert breakdown.components[FORM_DIVERSITY] == 4.0
    assert breakdown.components[PROJECTION_SUPPORT] == 1.0
    assert breakdown.components[BOUNDARY_MARK_SUPPORT] == 2.0
    assert breakdown.components[CROSS_METHOD_AGREEMENT] == 1.0
    assert breakdown.penalties[CONTRADICTION] == 0.0
    assert breakdown.penalties[UNKNOWN_SEGMENT] == 0.0
    assert breakdown.penalties[AMBIGUITY] == 0.0
    assert 0.0 <= breakdown.overall <= 1.0
    assert status is LifecycleStatus.SUPPORTED


def test_score_morpheme_promotion_rules() -> None:
    # igt_support >= 2 and igt_independence >= 2 -> supported
    status, _ = score_morpheme(igt_support=2, igt_independence=2, form_diversity=1, contradiction=0)
    assert status is LifecycleStatus.SUPPORTED

    # igt_support >= 2 and form_diversity >= 2 -> supported
    status, _ = score_morpheme(igt_support=2, igt_independence=1, form_diversity=2, contradiction=0)
    assert status is LifecycleStatus.SUPPORTED

    # igt_support < 2 -> candidate
    status, _ = score_morpheme(igt_support=1, igt_independence=5, form_diversity=5, contradiction=0)
    assert status is LifecycleStatus.CANDIDATE

    # neither independence >= 2 nor form_diversity >= 2 -> candidate
    status, _ = score_morpheme(igt_support=2, igt_independence=1, form_diversity=1, contradiction=0)
    assert status is LifecycleStatus.CANDIDATE

    # contradiction > 0 -> candidate (blocked)
    status, breakdown = score_morpheme(
        igt_support=10, igt_independence=10, form_diversity=10, contradiction=1
    )
    assert status is LifecycleStatus.CANDIDATE
    assert breakdown.overall == 0.0


def test_score_morpheme_from_evidence_items() -> None:
    src = new_id(IdPrefix.SOURCE)
    items = [
        _evidence(obs_id="obs_1", source_id=src, independence_group="grp_a", word_form="wesa"),
        _evidence(obs_id="obs_2", source_id=src, independence_group="grp_b", word_form="wesara"),
    ]
    status, breakdown = score_morpheme(evidence_items=items)
    assert status is LifecycleStatus.SUPPORTED
    assert breakdown.components[IGT_SUPPORT] == 2.0
    assert breakdown.components[IGT_INDEPENDENCE] == 2.0
    assert breakdown.components[FORM_DIVERSITY] == 2.0
    assert breakdown.penalties[CONTRADICTION] == 0.0
    assert breakdown.independence_groups == ["grp_a", "grp_b"]


def test_score_morpheme_re_evaluating_validated_raises_invalid_transition() -> None:
    with pytest.raises(InvalidTransition):
        score_morpheme(current_status=LifecycleStatus.VALIDATED)


def test_score_allomorph_matches_morpheme_criteria() -> None:
    status, breakdown = score_allomorph(
        igt_support=2, igt_independence=2, form_diversity=2, contradiction=0
    )
    assert status is LifecycleStatus.SUPPORTED
    assert breakdown.policy_version == POLICY_VERSION


def test_fixture_consequences_m5_plan_section_7_8() -> None:
    """Fixture consequence from M5-PLAN §7.8:

    `wesa` -> supported; `ki`, `ra`, `mabi`, `nawa`, unknown -> candidate;
    IGT-1 analysis of `wesa` -> supported;
    IGT-1 `mabi-ki`, IGT-2 `wesa-ra` -> candidate.
    """
    now = datetime.now(UTC)
    # wesa is attested in IGT-1 and IGT-2 (distinct records and distinct groups)
    wesa_status, _ = score_morpheme(
        igt_support=2, igt_independence=2, form_diversity=2, contradiction=0
    )
    assert wesa_status is LifecycleStatus.SUPPORTED

    # ki, ra, mabi, nawa are each attested in only 1 IGT record
    for name in ("ki", "ra", "mabi", "nawa", "unknown"):
        m_status, _ = score_morpheme(
            igt_support=1, igt_independence=1, form_diversity=1, contradiction=0
        )
        assert m_status is LifecycleStatus.CANDIDATE, f"{name} must stay candidate"

    # IGT-1 analysis of `wesa`: method is igt_assertion, single morpheme is wesa (supported)
    seg_wesa = MorphSegment(
        id=new_id(IdPrefix.MORPH_SEGMENT),
        analysis_id=new_id(IdPrefix.MORPH_ANALYSIS),
        ordinal=0,
        start=0,
        end=4,
        is_zero=False,
        surface="wesa",
        morpheme_id=new_id(IdPrefix.MORPHEME),
        created_at=now,
    )
    ana_wesa_status, breakdown = score_analysis(
        method="igt_assertion@0.1.0",
        linked_morpheme_statuses=[wesa_status],
        segments=[seg_wesa],
        contradiction=0,
    )
    assert ana_wesa_status is LifecycleStatus.SUPPORTED
    assert breakdown.overall >= 0.75

    # IGT-1 analysis of `mabi-ki`: mabi and ki are candidates
    ana_mabi_ki_status, _ = score_analysis(
        method="igt_assertion@0.1.0",
        linked_morpheme_statuses=[LifecycleStatus.CANDIDATE, LifecycleStatus.CANDIDATE],
        segments=[],
        contradiction=0,
    )
    assert ana_mabi_ki_status is LifecycleStatus.CANDIDATE

    # IGT-2 analysis of `wesa-ra`: ra is candidate
    ana_wesa_ra_status, _ = score_analysis(
        method="igt_assertion@0.1.0",
        linked_morpheme_statuses=[LifecycleStatus.SUPPORTED, LifecycleStatus.CANDIDATE],
        segments=[],
        contradiction=0,
    )
    assert ana_wesa_ra_status is LifecycleStatus.CANDIDATE


def test_score_analysis_method_gate() -> None:
    # A method not in allowlist (e.g. unsegmented or morfessor) stays candidate
    status, _ = score_analysis(
        method="unsegmented@0.1.0",
        linked_morpheme_statuses=[LifecycleStatus.SUPPORTED],
        contradiction=0,
    )
    assert status is LifecycleStatus.CANDIDATE

    status, _ = score_analysis(
        method="morfessor@0.1.0",
        linked_morpheme_statuses=[LifecycleStatus.SUPPORTED],
        contradiction=0,
    )
    assert status is LifecycleStatus.CANDIDATE


def test_score_analysis_unknown_segment_and_contradiction_penalties() -> None:
    now = datetime.now(UTC)
    # Unknown segment blocks promotion
    seg_unknown = MorphSegment(
        id=new_id(IdPrefix.MORPH_SEGMENT),
        analysis_id=new_id(IdPrefix.MORPH_ANALYSIS),
        ordinal=0,
        start=0,
        end=3,
        is_zero=False,
        surface="foo",
        morpheme_id=None,
        created_at=now,
    )
    status, breakdown = score_analysis(
        method="igt_assertion",
        linked_morpheme_statuses=[LifecycleStatus.SUPPORTED],
        segments=[seg_unknown],
        contradiction=0,
    )
    assert status is LifecycleStatus.CANDIDATE
    assert breakdown.penalties[UNKNOWN_SEGMENT] == 1.0

    # Contradiction blocks promotion and zeroes overall
    status, breakdown = score_analysis(
        method="igt_assertion",
        linked_morpheme_statuses=[LifecycleStatus.SUPPORTED],
        segments=[],
        contradiction=1,
    )
    assert status is LifecycleStatus.CANDIDATE
    assert breakdown.penalties[CONTRADICTION] == 1.0
    assert breakdown.overall == 0.0


def test_score_analysis_ambiguity_calculation() -> None:
    _, breakdown = score_analysis(
        method="igt_assertion",
        linked_morpheme_statuses=[LifecycleStatus.SUPPORTED],
        distinct_signatures_on_token=3,
    )
    assert breakdown.penalties[AMBIGUITY] == 2.0


def test_score_analysis_re_evaluating_validated_raises_invalid_transition() -> None:
    with pytest.raises(InvalidTransition):
        score_analysis(method="igt_assertion", current_status=LifecycleStatus.VALIDATED)
