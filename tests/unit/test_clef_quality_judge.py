"""Unit tests for Clef Semantic Quality Judge & Quarantining Pipeline."""

import pytest

from langpipe.synthesis.clef import HeuristicClefJudge, MockClefJudge, get_clef_judge
from langpipe.synthesis.grounding import GroundingValidator
from langpipe.synthesis.quality import FailureReason, QualityStatus
from langpipe.synthesis.structural import check_structural_alignment
from tests.fixtures.artifacts import requires_built_lexicon


@pytest.fixture
def validator():
    return GroundingValidator(lang_code="mzr")


@pytest.fixture
def heuristic_judge():
    return HeuristicClefJudge(lang_code="mzr")


@requires_built_lexicon
def test_plausible_marubo_phrase_passes(validator, heuristic_judge):
    """Plausible phrase: 'vaki-n nami pi-ai' (child-ERG meat eat-PRES -> A criança come carne)."""
    raw_phrase = "vaki-n nami pi-ai."
    igt = "vaki-n nami pi-ai\ncriança-ERG carne comer-PRES\nA criança come carne."
    pt = "A criança come carne."

    # 1. Grounding check
    grounding = validator.validate(raw_phrase)
    assert grounding.valid is True

    # 2. Structural L1 check
    l1 = check_structural_alignment(raw_phrase, igt, pt, lang_code="mzr")
    assert l1["tam_consistent"] is True

    # 3. Clef L2 Judge
    judgment = heuristic_judge.judge_phrase(
        target_phrase=raw_phrase,
        igt_gloss=igt,
        portuguese_translation=pt,
        grounding_report=grounding,
        l1_checks=l1,
    )

    assert judgment.status == QualityStatus.PASSED_AUTOMATED
    assert FailureReason.SEMANTIC_IMPLAUSIBILITY not in judgment.reasons
    assert FailureReason.SELECTIONAL_VIOLATION not in judgment.reasons
    assert judgment.score >= 0.8


@requires_built_lexicon
def test_nonsensical_phrase_quarantined_by_clef(validator, heuristic_judge):
    """Absurd phrase: fish killing/burning a child (severe selectional violation).

    Even though stems are grounded in LKB, Clef MUST quarantine it!
    """
    raw_phrase = "yapa-n vaki yamama-katsai."
    igt = "yapa-n vaki yamama-katsai\npeixe-ERG criança matar-FUT\nO peixe matará o menino."
    pt = "O peixe matará o menino."

    grounding = validator.validate(raw_phrase)
    assert grounding.valid is True  # Lexically grounded

    l1 = check_structural_alignment(raw_phrase, igt, pt, lang_code="mzr")
    judgment = heuristic_judge.judge_phrase(
        target_phrase=raw_phrase,
        igt_gloss=igt,
        portuguese_translation=pt,
        grounding_report=grounding,
        l1_checks=l1,
    )

    # Must be quarantined due to selectional restriction / semantic implausibility
    assert judgment.status == QualityStatus.QUARANTINED
    has_violation = (
        FailureReason.SELECTIONAL_VIOLATION in judgment.reasons
        or FailureReason.SEMANTIC_IMPLAUSIBILITY in judgment.reasons
    )
    assert has_violation
    assert "peixe" in judgment.critique.lower()
    assert judgment.score < 0.4


@requires_built_lexicon
def test_tam_mismatch_quarantined_or_rejected(validator, heuristic_judge):
    """TAM mismatch: '-ma' (NEG) in Marúbo, but affirmative Portuguese sentence."""
    raw_phrase = "vaki-n nami pi-ma-ai."
    igt = "vaki-n nami pi-ma-ai\ncriança-ERG carne comer-NEG-PRES\nA criança come carne todo dia."
    pt = "A criança come carne todo dia."

    grounding = validator.validate(raw_phrase)
    l1 = check_structural_alignment(raw_phrase, igt, pt, lang_code="mzr")
    assert l1["tam_consistent"] is False

    judgment = heuristic_judge.judge_phrase(
        target_phrase=raw_phrase,
        igt_gloss=igt,
        portuguese_translation=pt,
        grounding_report=grounding,
        l1_checks=l1,
    )

    assert FailureReason.TAM_MISMATCH in judgment.reasons
    assert judgment.status in (QualityStatus.QUARANTINED, QualityStatus.REJECTED)


def test_hallucination_hard_rejection(validator, heuristic_judge):
    """Hallucinated word is rejected at L0 without reaching automated pass."""
    raw_phrase = "vaki-n computador yamama."
    igt = "vaki-n computador yamama\ncriança computador matar\nO menino mata computador."
    pt = "O menino mata computador."

    grounding = validator.validate(raw_phrase)
    assert grounding.valid is False

    l1 = check_structural_alignment(raw_phrase, igt, pt, lang_code="mzr")
    judgment = heuristic_judge.judge_phrase(
        target_phrase=raw_phrase,
        igt_gloss=igt,
        portuguese_translation=pt,
        grounding_report=grounding,
        l1_checks=l1,
    )

    assert judgment.status == QualityStatus.REJECTED
    assert FailureReason.HALLUCINATION in judgment.reasons


def test_mock_judge_factory():
    judge = get_clef_judge("mock")
    assert isinstance(judge, MockClefJudge)
