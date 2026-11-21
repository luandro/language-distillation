"""WP4.4 unit tests: lexical evidence scoring policy and promotion (M4-PLAN §6 WP4.4).

Contracts under test (`docs/implementation/M4-PLAN.md` WP4.4, ADR-0013 §3,
`docs/EVIDENCE-AND-CONFIDENCE.md`):
- the versioned `lexical-v1` breakdown preserves raw components and penalties instead of one
  opaque score, and records the independence groups it aggregated;
- repeated observations from one formulaic source are not independent corroboration: same
  `independence_group` duplicates are penalised and never satisfy source diversity;
- promotion is `candidate` -> `supported` only, gated on the threshold, independence,
  non-contradiction, and target-language (not related-language) evidence;
- machine confidence never produces `validated` (`EVIDENCE-AND-CONFIDENCE.md:61-63`).
"""

import math
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LifecycleStatus
from langpipe.domain.errors import InvalidTransition
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem
from langpipe.domain.models.lexical import LexicalScoreBreakdown
from langpipe.lexicon.scoring import (
    COMPONENTS,
    DEFAULT_POLICY,
    PENALTIES,
    POLICY_VERSION,
    LexicalScorePolicy,
    compute_score,
    evaluate_promotion,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
TARGET_LANGUAGE = "xxx"
SOURCE_A = new_id(IdPrefix.SOURCE)
SOURCE_B = new_id(IdPrefix.SOURCE)
_RELATED_EXTENSION = {"langpipe.scoring": {"related_language": True}}
_KINDS = tuple(EvidenceKind)


def _evidence(  # noqa: PLR0913
    *,
    kind: EvidenceKind = EvidenceKind.TOKEN_ALIGNMENT,
    polarity: EvidencePolarity = EvidencePolarity.SUPPORTS,
    strength: dict[str, float] | None = None,
    independence_group: str | None = None,
    source_id: str | None = None,
    domain: str | None = None,
    register: str | None = None,
    claim: dict[str, object] | None = None,
    extensions: dict[str, dict[str, object]] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        id=new_id(IdPrefix.EVIDENCE),
        kind=kind,
        polarity=polarity,
        target_id=new_id(IdPrefix.LEXEME),
        claim=claim,
        source_id=source_id,
        run_id=new_id(IdPrefix.RUN),
        strength=dict(strength or {}),
        independence_group=independence_group,
        domain=domain,
        register=register,
        extensions=extensions or {},
        created_at=NOW,
    )


def _breakdown(overall: float = 1.0, **kwargs: object) -> LexicalScoreBreakdown:
    values: dict[str, object] = {
        "policy_version": POLICY_VERSION,
        "overall": overall,
        "components": dict.fromkeys(COMPONENTS, 1.0),
        **kwargs,
    }
    return LexicalScoreBreakdown(**values)  # type: ignore[arg-type]


def _rich(target: str | None = TARGET_LANGUAGE) -> list[EvidenceItem]:
    """Target-language evidence across components, groups, domains and registers."""
    return [
        _evidence(
            independence_group="src/pilot-01",
            domain="food",
            register="informal",
        ),
        _evidence(
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            strength={"dictionary_support": 0.9},
            independence_group="src/wordlist-02",
            domain="food",
            register="formal",
        ),
        _evidence(
            kind=EvidenceKind.IGT_ASSERTION,
            strength={"igt_support": 0.8},
            independence_group="src/igt-03",
            domain="food",
            register="informal",
        ),
        _evidence(
            kind=EvidenceKind.MONOLINGUAL_DISTRIBUTION,
            strength={"monolingual_support": 0.7},
            independence_group="src/mono-04",
            domain="food",
            register="informal",
        ),
        _evidence(
            kind=EvidenceKind.SPEAKER_REVIEW,
            claim={"language": target} if target else None,
            independence_group="src/speaker-05",
            domain="food",
            register="informal",
        ),
    ]


def test_breakdown_is_versioned_and_reports_every_component() -> None:
    breakdown = DEFAULT_POLICY.compute_score(_rich(), target_language=TARGET_LANGUAGE)

    assert breakdown.policy_version == POLICY_VERSION == "lexical-v1"
    assert list(breakdown.components) == list(COMPONENTS)
    assert list(breakdown.penalties) == list(PENALTIES)
    assert breakdown.components["alignment_support"] == 1.0
    assert breakdown.components["dictionary_support"] == 0.9
    assert breakdown.components["igt_support"] == 0.8
    assert breakdown.components["monolingual_support"] == 0.7
    assert set(breakdown.penalties.values()) == {0.0}


def test_component_strengths_come_from_supporting_items_of_the_matching_kind() -> None:
    breakdown = DEFAULT_POLICY.compute_score(
        [
            _evidence(kind=EvidenceKind.TOKEN_ALIGNMENT, strength={"alignment_support": 0.9}),
            _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, strength={"dictionary_support": 0.6}),
            _evidence(kind=EvidenceKind.IGT_ASSERTION, strength={"igt_support": 0.4}),
            _evidence(
                kind=EvidenceKind.MONOLINGUAL_DISTRIBUTION, strength={"monolingual_support": 0.5}
            ),
            # Grammar descriptions describe a language, never one lexical hypothesis.
            _evidence(kind=EvidenceKind.GRAMMAR_DESCRIPTION, strength={"alignment_support": 1.0}),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert breakdown.components["alignment_support"] == 0.9
    assert breakdown.components["dictionary_support"] == 0.6
    assert breakdown.components["igt_support"] == 0.4
    assert breakdown.components["monolingual_support"] == 0.5
    assert breakdown.components["domain_stability"] == 1.0
    # None of these items records an independence axis, and a grammar description is
    # corroborated by no kind: no established source exists, so no diversity is earned.
    assert breakdown.components["source_diversity"] == 0.0
    assert breakdown.independence_groups == []


def test_strengths_are_clamped_into_the_unit_range() -> None:
    breakdown = DEFAULT_POLICY.compute_score(
        [
            _evidence(kind=EvidenceKind.TOKEN_ALIGNMENT, strength={"alignment_support": 4.0}),
            _evidence(
                kind=EvidenceKind.SEGMENT_COOCCURRENCE,
                strength={"alignment_support": -3.0},
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert breakdown.components["alignment_support"] == 1.0


def test_unrecorded_strength_defaults_to_full_support() -> None:
    # A governed, recorded assertion is support at full weight unless it says otherwise.
    breakdown = DEFAULT_POLICY.compute_score(
        [_evidence(independence_group="src/pilot-01")], target_language=TARGET_LANGUAGE
    )

    assert breakdown.components["alignment_support"] == 1.0
    assert breakdown.components["dictionary_support"] == 0.0
    assert breakdown.components["igt_support"] == 0.0


def test_nonfinite_strengths_are_not_credited() -> None:
    breakdown = DEFAULT_POLICY.compute_score(
        [
            _evidence(
                kind=EvidenceKind.DICTIONARY_ASSERTION,
                strength={"dictionary_support": float("nan")},
            )
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert breakdown.components["dictionary_support"] == 0.0


def test_empty_evidence_scores_zero() -> None:
    breakdown = DEFAULT_POLICY.compute_score([], target_language=TARGET_LANGUAGE)

    assert breakdown.overall == 0.0
    assert set(breakdown.components.values()) == {0.0}
    assert set(breakdown.penalties.values()) == {0.0}
    assert breakdown.independence_groups == []


def test_contradicting_evidence_is_preserved_not_averaged_away() -> None:
    contradicted = DEFAULT_POLICY.compute_score(
        [
            _evidence(
                kind=EvidenceKind.TOKEN_ALIGNMENT,
                strength={"alignment_support": 0.8},
                independence_group="src/pilot-01",
            ),
            _evidence(
                kind=EvidenceKind.TOKEN_ALIGNMENT,
                polarity=EvidencePolarity.CONTRADICTS,
                strength={"alignment_support": 1.0},
                independence_group="src/pilot-02",
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )

    # The contradiction is never credited as support, and never cancels the support.
    assert contradicted.components["alignment_support"] == 0.8
    # Only supporting evidence counts toward independence: a contradiction is an axis
    # of its own, not corroboration.
    assert contradicted.components["source_diversity"] == 0.5
    assert contradicted.overall > 0.0


def test_context_only_evidence_is_neither_support_nor_contradiction() -> None:
    context_only = DEFAULT_POLICY.compute_score(
        [
            _evidence(independence_group="src/pilot-01"),
            _evidence(
                kind=EvidenceKind.DICTIONARY_ASSERTION,
                polarity=EvidencePolarity.CONTEXT_ONLY,
                strength={"dictionary_support": 1.0},
                independence_group="src/pilot-02",
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert context_only.components["dictionary_support"] == 0.0
    # Context-only items are recorded axes, but never support, so they are not
    # independent corroboration.
    assert context_only.components["source_diversity"] == 0.5
    assert context_only.independence_groups == ["src/pilot-01", "src/pilot-02"]
    assert context_only.penalties["related_language_only"] == 0.0


def test_distinct_independence_groups_reward_independent_corroboration() -> None:
    one_group = DEFAULT_POLICY.compute_score(
        [
            _evidence(independence_group="src/pilot-01"),
            _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, independence_group="src/pilot-01"),
        ],
        target_language=TARGET_LANGUAGE,
    )
    two_groups = DEFAULT_POLICY.compute_score(
        [
            _evidence(independence_group="src/pilot-01"),
            _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, independence_group="src/pilot-02"),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert one_group.components["source_diversity"] == 0.5
    assert two_groups.components["source_diversity"] == 1.0
    assert two_groups.overall > one_group.overall


def test_independence_falls_back_to_source_then_stays_unknown() -> None:
    same_source = DEFAULT_POLICY.compute_score(
        [
            _evidence(source_id=SOURCE_A),
            _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, source_id=SOURCE_A),
        ],
        target_language=TARGET_LANGUAGE,
    )
    distinct_sources = DEFAULT_POLICY.compute_score(
        [
            _evidence(source_id=SOURCE_A),
            _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, source_id=SOURCE_B),
        ],
        target_language=TARGET_LANGUAGE,
    )
    unlabelled = DEFAULT_POLICY.compute_score(
        [
            _evidence(),
            _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert same_source.components["source_diversity"] == 0.5
    assert distinct_sources.components["source_diversity"] == 1.0
    # An item with neither `independence_group` nor `source_id` establishes no axis: it
    # is a distinct observation, never an independent source, and never appears as a
    # group. Distinct observations from identical unknown provenance cannot corroborate.
    assert unlabelled.components["source_diversity"] == 0.0
    assert unlabelled.independence_groups == []


def test_unknown_provenance_is_never_an_independent_source() -> None:
    # EVIDENCE-AND-CONFIDENCE.md §Evidence independence: an unknown axis cannot supply
    # the missing second source. Both paths resolve axes the same way, so the score and
    # the promotion gate can never disagree about how many sources exist.
    all_unlabelled = [
        _evidence(),
        _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, strength={"dictionary_support": 1.0}),
    ]
    one_known_plus_unlabelled = [
        _evidence(independence_group="src/pilot-01"),
        _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, strength={"dictionary_support": 1.0}),
    ]
    two_known = [
        _evidence(independence_group="src/pilot-01"),
        _evidence(
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            strength={"dictionary_support": 1.0},
            independence_group="src/pilot-02",
        ),
    ]

    for items, diversity, groups in (
        (all_unlabelled, 0.0, []),
        (one_known_plus_unlabelled, 0.5, ["src/pilot-01"]),
        (two_known, 1.0, ["src/pilot-01", "src/pilot-02"]),
    ):
        breakdown = DEFAULT_POLICY.compute_score(items, target_language=TARGET_LANGUAGE)
        # The score alone never clears the promotion threshold on only components, and
        # the gate independently refuses to promote on fewer than two established axes.
        assert breakdown.components["source_diversity"] == diversity
        assert breakdown.independence_groups == groups
        assert DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, breakdown, items, TARGET_LANGUAGE
        ) is (LifecycleStatus.SUPPORTED if items is two_known else LifecycleStatus.CANDIDATE)


def test_source_fallback_counts_two_known_sources() -> None:
    # The source is a legitimate axis when recorded: two distinct `source_id`s establish
    # the second axis that unlabelled evidence cannot.
    items = [
        _evidence(source_id=SOURCE_A),
        _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, source_id=SOURCE_B),
    ]

    breakdown = DEFAULT_POLICY.compute_score(items, target_language=TARGET_LANGUAGE)

    assert breakdown.components["source_diversity"] == 1.0
    assert sorted(breakdown.independence_groups) == sorted([SOURCE_A, SOURCE_B])
    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, breakdown, items, TARGET_LANGUAGE
        )
        is LifecycleStatus.SUPPORTED
    )


def test_explicit_groups_are_the_recorded_independence_axes() -> None:
    items = [
        _evidence(independence_group="src/pilot-01"),
        _evidence(
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            strength={"dictionary_support": 1.0},
            independence_group="src/wordlist-02",
        ),
    ]

    breakdown = DEFAULT_POLICY.compute_score(items, target_language=TARGET_LANGUAGE)

    assert breakdown.independence_groups == ["src/pilot-01", "src/wordlist-02"]
    assert breakdown.components["source_diversity"] == 1.0
    assert breakdown.penalties["formulaic_source"] == 0.0
    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, breakdown, items, TARGET_LANGUAGE
        )
        is LifecycleStatus.SUPPORTED
    )


def test_repeated_unlabelled_observations_penalised_not_rewarded() -> None:
    # The same unknown-provenance assertion recorded repeatedly is not corroboration:
    # the components are unchanged and the duplicated share penalises the repeat.
    repeated = DEFAULT_POLICY.compute_score(
        [
            _evidence(independence_group="src/pilot-01"),
            _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, independence_group="src/pilot-01"),
            _evidence(),
            _evidence(),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert repeated.components["alignment_support"] == 1.0
    assert repeated.components["dictionary_support"] == 1.0
    assert repeated.components["source_diversity"] == 0.5
    # Half of the supporting items repeat an established axis; the unlabelled items
    # establish no axis of their own and are not counted as duplicates either.
    assert repeated.penalties["formulaic_source"] == pytest.approx(0.1 * 2 / 4)
    assert repeated.independence_groups == ["src/pilot-01"]


def test_formulaic_source_penalty_grows_with_the_duplicated_share() -> None:
    independent = DEFAULT_POLICY.compute_score(
        [
            _evidence(
                kind=EvidenceKind.TOKEN_ALIGNMENT,
                strength={"alignment_support": 0.9},
                independence_group="src/pilot-01",
            ),
            _evidence(
                kind=EvidenceKind.DICTIONARY_ASSERTION,
                strength={"dictionary_support": 0.9},
                independence_group="src/pilot-02",
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )
    one_duplicated_item = DEFAULT_POLICY.compute_score(
        [
            _evidence(
                kind=EvidenceKind.TOKEN_ALIGNMENT,
                strength={"alignment_support": 0.9},
                independence_group="src/pilot-01",
            ),
            _evidence(
                kind=EvidenceKind.DICTIONARY_ASSERTION,
                strength={"dictionary_support": 0.9},
                independence_group="src/pilot-02",
            ),
            # A repeat of pilot-01's assertion: same axis, duplicated share grows.
            _evidence(
                kind=EvidenceKind.TOKEN_ALIGNMENT,
                strength={"alignment_support": 0.9},
                independence_group="src/pilot-01",
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )
    half_duplicated = DEFAULT_POLICY.compute_score(
        [
            _evidence(
                kind=EvidenceKind.TOKEN_ALIGNMENT,
                strength={"alignment_support": 0.9},
                independence_group="src/pilot-01",
            ),
            _evidence(
                kind=EvidenceKind.DICTIONARY_ASSERTION,
                strength={"dictionary_support": 0.9},
                independence_group="src/pilot-02",
            ),
            _evidence(
                kind=EvidenceKind.IGT_ASSERTION,
                strength={"igt_support": 0.9},
                independence_group="src/pilot-01",
            ),
            _evidence(
                kind=EvidenceKind.MONOLINGUAL_DISTRIBUTION,
                strength={"monolingual_support": 0.9},
                independence_group="src/pilot-02",
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert independent.penalties["formulaic_source"] == 0.0
    assert one_duplicated_item.penalties["formulaic_source"] == pytest.approx(0.1 * 2 / 3)
    assert half_duplicated.penalties["formulaic_source"] == pytest.approx(0.1)
    # Every case here spans the same two axes at full diversity, so the duplicated
    # share of supporting items is the only difference between them.
    assert (
        independent.independence_groups
        == one_duplicated_item.independence_groups
        == half_duplicated.independence_groups
        == ["src/pilot-01", "src/pilot-02"]
    )
    assert one_duplicated_item.overall < independent.overall
    # half_duplicated earns two more component supports (5 axes worth), so its net
    # score rises even though the duplicated share is larger.
    assert half_duplicated.components["igt_support"] == 0.9
    assert half_duplicated.overall > one_duplicated_item.overall


def test_single_register_concentration_penalty() -> None:
    concentrated = DEFAULT_POLICY.compute_score(
        [_evidence(independence_group="src/pilot-01", register="traditional")],
        target_language=TARGET_LANGUAGE,
    )
    untagged = DEFAULT_POLICY.compute_score(
        [_evidence(independence_group="src/pilot-01")],
        target_language=TARGET_LANGUAGE,
    )
    spread = DEFAULT_POLICY.compute_score(
        [
            _evidence(independence_group="src/pilot-01", register="traditional"),
            _evidence(
                kind=EvidenceKind.DICTIONARY_ASSERTION,
                independence_group="src/pilot-02",
                register="informal",
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert concentrated.penalties["single_register_concentration"] == 0.05
    assert untagged.penalties["single_register_concentration"] == 0.0
    assert spread.penalties["single_register_concentration"] == 0.0
    assert concentrated.overall < untagged.overall


def test_domain_conflict_lowers_domain_stability() -> None:
    one_domain = DEFAULT_POLICY.compute_score(
        [
            _evidence(independence_group="src/pilot-01", domain="ritual"),
            _evidence(
                kind=EvidenceKind.DICTIONARY_ASSERTION,
                independence_group="src/pilot-02",
                domain="ritual",
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )
    conflicted = DEFAULT_POLICY.compute_score(
        [
            _evidence(independence_group="src/pilot-01", domain="ritual"),
            _evidence(
                kind=EvidenceKind.DICTIONARY_ASSERTION,
                independence_group="src/pilot-02",
                domain="food",
            ),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert one_domain.components["domain_stability"] == 1.0
    assert conflicted.components["domain_stability"] == 0.5


def test_related_language_only_evidence_scores_zero() -> None:
    related = _evidence(
        kind=EvidenceKind.RELATED_LANGUAGE_COMPARISON, independence_group="ext/family"
    )
    flagged = _evidence(
        kind=EvidenceKind.TOKEN_ALIGNMENT,
        independence_group="ext/family",
        extensions=_RELATED_EXTENSION,
    )

    for item in (related, flagged):
        breakdown = DEFAULT_POLICY.compute_score([item], target_language=TARGET_LANGUAGE)
        assert breakdown.overall == 0.0
        assert set(breakdown.components.values()) == {0.0}
        assert breakdown.penalties["related_language_only"] == 1.0
        # The group is still recorded: preserved evidence, not discarded evidence.
        assert breakdown.independence_groups == ["ext/family"]

    mixed = DEFAULT_POLICY.compute_score(
        [related, _evidence(independence_group="src/pilot-01")], target_language=TARGET_LANGUAGE
    )
    assert mixed.penalties["related_language_only"] == 0.0
    assert mixed.overall > 0.0


def test_claim_language_rule_is_opt_in() -> None:
    # Default off: a Portuguese-contact dictionary assertion is still target-language
    # dictionary evidence until the policy is configured to read claim languages.
    literal = DEFAULT_POLICY.compute_score(
        [_evidence(claim={"language": "por"}, independence_group="src/wordlist-01")],
        target_language=TARGET_LANGUAGE,
    )
    aware = LexicalScorePolicy(claim_language_is_related=True).compute_score(
        [_evidence(claim={"language": "por"}, independence_group="src/wordlist-01")],
        target_language=TARGET_LANGUAGE,
    )
    native = LexicalScorePolicy(claim_language_is_related=True).compute_score(
        [_evidence(claim={"language": TARGET_LANGUAGE}, independence_group="src/wordlist-01")],
        target_language=TARGET_LANGUAGE,
    )

    assert literal.penalties["related_language_only"] == 0.0
    assert literal.overall > 0.0
    assert aware.penalties["related_language_only"] == 1.0
    assert aware.overall == 0.0
    assert native.penalties["related_language_only"] == 0.0


def test_independence_groups_are_unique_sorted_group_names() -> None:
    breakdown = DEFAULT_POLICY.compute_score(
        [
            _evidence(independence_group="src/pilot-02"),
            _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, independence_group="src/pilot-01"),
            _evidence(kind=EvidenceKind.IGT_ASSERTION, independence_group="src/pilot-02"),
        ],
        target_language=TARGET_LANGUAGE,
    )

    assert breakdown.independence_groups == ["src/pilot-01", "src/pilot-02"]


def test_candidate_is_promoted_when_every_gate_passes() -> None:
    items = _rich()

    breakdown = DEFAULT_POLICY.compute_score(items, target_language=TARGET_LANGUAGE)

    assert breakdown.overall >= DEFAULT_POLICY.promotion_threshold
    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, breakdown, items, TARGET_LANGUAGE
        )
        is LifecycleStatus.SUPPORTED
    )


def test_candidate_is_not_promoted_below_the_threshold() -> None:
    policy = LexicalScorePolicy(promotion_threshold=0.95)
    items = [
        _evidence(
            kind=EvidenceKind.TOKEN_ALIGNMENT,
            strength={"alignment_support": 0.4},
            independence_group="src/pilot-01",
        ),
        _evidence(
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            strength={"dictionary_support": 0.5},
            independence_group="src/pilot-02",
        ),
    ]

    breakdown = policy.compute_score(items, target_language=TARGET_LANGUAGE)

    assert 0.0 < breakdown.overall < policy.promotion_threshold
    assert (
        policy.evaluate_promotion(LifecycleStatus.CANDIDATE, breakdown, items, TARGET_LANGUAGE)
        is LifecycleStatus.CANDIDATE
    )


def test_candidate_is_not_promoted_from_one_formulaic_source() -> None:
    # Repeated observations of one formulaic source are not independent corroboration:
    # the score alone clears the threshold, the diversity gate does not.
    items = [
        _evidence(kind=EvidenceKind.TOKEN_ALIGNMENT, independence_group="src/formulaic"),
        _evidence(kind=EvidenceKind.DICTIONARY_ASSERTION, independence_group="src/formulaic"),
        _evidence(kind=EvidenceKind.IGT_ASSERTION, independence_group="src/formulaic"),
        _evidence(kind=EvidenceKind.MONOLINGUAL_DISTRIBUTION, independence_group="src/formulaic"),
    ]

    breakdown = DEFAULT_POLICY.compute_score(items, target_language=TARGET_LANGUAGE)

    assert breakdown.components["source_diversity"] == 0.5
    assert breakdown.penalties["formulaic_source"] == pytest.approx(0.1)
    # The threshold alone is met: only the diversity gate stops this promotion.
    assert breakdown.overall >= DEFAULT_POLICY.promotion_threshold
    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, breakdown, items, TARGET_LANGUAGE
        )
        is LifecycleStatus.CANDIDATE
    )


def test_candidate_is_not_promoted_from_related_language_evidence_alone() -> None:
    # EVIDENCE-AND-CONFIDENCE.md:62 — related-language evidence alone never promotes the target.
    items = [
        _evidence(kind=EvidenceKind.RELATED_LANGUAGE_COMPARISON, independence_group="ext/family"),
        _evidence(
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            strength={"dictionary_support": 1.0},
            independence_group="ext/family-2",
            extensions=_RELATED_EXTENSION,
        ),
    ]

    breakdown = DEFAULT_POLICY.compute_score(items, target_language=TARGET_LANGUAGE)

    assert breakdown.overall == 0.0
    assert breakdown.penalties["related_language_only"] == 1.0
    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, breakdown, items, TARGET_LANGUAGE
        )
        is LifecycleStatus.CANDIDATE
    )


def test_candidate_is_not_promoted_when_contradiction_outweighs_support() -> None:
    # Evidence that passes every other gate on its own: threshold, two established axes,
    # no related-language evidence. Only the contradiction gate can stop this promotion.
    support = [
        _evidence(
            kind=EvidenceKind.TOKEN_ALIGNMENT,
            strength={"alignment_support": 0.9},
            independence_group="src/pilot-01",
        ),
        _evidence(
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            strength={"dictionary_support": 0.9},
            independence_group="src/wordlist-02",
        ),
    ]

    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE,
            DEFAULT_POLICY.compute_score(support, target_language=TARGET_LANGUAGE),
            support,
            TARGET_LANGUAGE,
        )
        is LifecycleStatus.SUPPORTED
    )

    contradicted = support + [
        _evidence(
            kind=EvidenceKind.TOKEN_ALIGNMENT,
            polarity=EvidencePolarity.CONTRADICTS,
            strength={"alignment_support": 1.0},
            independence_group="src/contra-03",
        ),
        _evidence(
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            polarity=EvidencePolarity.CONTRADICTS,
            strength={"dictionary_support": 1.0},
            independence_group="src/contra-04",
        ),
    ]
    breakdown = DEFAULT_POLICY.compute_score(contradicted, target_language=TARGET_LANGUAGE)

    # Contradiction is preserved, never averaged away, and never credited as support.
    assert breakdown.components["alignment_support"] == 0.9
    assert breakdown.components["dictionary_support"] == 0.9
    # Both preconditions of the promotion gate are still satisfied: the score clears the
    # threshold on the supporting evidence and two established supporting axes exist.
    assert breakdown.overall >= DEFAULT_POLICY.promotion_threshold
    assert breakdown.components["source_diversity"] == 1.0
    assert breakdown.penalties["related_language_only"] == 0.0
    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, breakdown, contradicted, TARGET_LANGUAGE
        )
        is LifecycleStatus.CANDIDATE
    )


def test_candidate_is_not_promoted_without_any_supporting_evidence() -> None:
    items = [_evidence(polarity=EvidencePolarity.CONTEXT_ONLY, independence_group="src/pilot-01")]

    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, _breakdown(), items, TARGET_LANGUAGE
        )
        is LifecycleStatus.CANDIDATE
    )


def test_promotion_requires_the_current_policy_version() -> None:
    # Otherwise-promotable evidence, so only the recorded version differs between the
    # two evaluations: a breakdown from a superseded policy is never actioned.
    items = [
        _evidence(
            kind=EvidenceKind.TOKEN_ALIGNMENT,
            strength={"alignment_support": 0.9},
            independence_group="src/pilot-01",
        ),
        _evidence(
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            strength={"dictionary_support": 0.9},
            independence_group="src/wordlist-02",
        ),
    ]
    current = DEFAULT_POLICY.compute_score(items, target_language=TARGET_LANGUAGE)
    stale = current.model_copy(update={"policy_version": "lexical-v0"})

    assert current.overall >= DEFAULT_POLICY.promotion_threshold
    assert len(current.independence_groups) >= DEFAULT_POLICY.min_independent_sources
    assert (
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.CANDIDATE, current, items, TARGET_LANGUAGE
        )
        is LifecycleStatus.SUPPORTED
    )
    # Identical evidence, identical score: the stale version alone keeps it a candidate.
    assert stale.overall == current.overall
    assert stale.components == current.components
    assert (
        DEFAULT_POLICY.evaluate_promotion(LifecycleStatus.CANDIDATE, stale, items, TARGET_LANGUAGE)
        is LifecycleStatus.CANDIDATE
    )


def test_promotion_leaves_human_and_terminal_statuses_untouched() -> None:
    items = _rich()

    # Only an authorized review decision may move anything out of these states.
    for status in (
        LifecycleStatus.SUPPORTED,
        LifecycleStatus.REJECTED,
        LifecycleStatus.DEPRECATED,
    ):
        assert (
            DEFAULT_POLICY.evaluate_promotion(status, _breakdown(), items, TARGET_LANGUAGE)
            is status
        )


def test_promotion_refuses_to_adjudicate_a_validated_object() -> None:
    # Demoting a validated hypothesis would let machine scoring retract a human decision.
    items = [
        _evidence(kind=EvidenceKind.TOKEN_ALIGNMENT, independence_group="src/pilot-01"),
        _evidence(kind=EvidenceKind.RELATED_LANGUAGE_COMPARISON, independence_group="src/pilot-02"),
    ]

    with pytest.raises(InvalidTransition):
        DEFAULT_POLICY.evaluate_promotion(
            LifecycleStatus.VALIDATED, _breakdown(overall=0.0), items, TARGET_LANGUAGE
        )


def test_module_level_helpers_use_the_default_policy() -> None:
    items = _rich()
    breakdown = compute_score(items, target_language=TARGET_LANGUAGE)

    assert breakdown == DEFAULT_POLICY.compute_score(items, target_language=TARGET_LANGUAGE)
    assert (
        evaluate_promotion(
            LifecycleStatus.CANDIDATE, _breakdown(overall=0.0), items, TARGET_LANGUAGE
        )
        is LifecycleStatus.CANDIDATE
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"alignment_support_weight": -0.1},
        {"source_diversity_weight": 0.0},
        {"promotion_threshold": 1.5},
        {"promotion_threshold": float("nan")},
        {"formulaic_source_penalty": 1.5},
        {"single_register_concentration_penalty": -0.1},
        {"min_independent_sources": 0},
    ],
)
def test_policy_rejects_unusable_configuration(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        LexicalScorePolicy(**overrides)  # type: ignore[arg-type]


def test_policy_requires_weights_that_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to"):
        LexicalScorePolicy(igt_support_weight=0.5)


_strengths = st.dictionaries(
    st.sampled_from(list(COMPONENTS)),
    st.floats(min_value=-3.0, max_value=3.0, allow_nan=False),
    max_size=3,
)
_items = st.lists(
    st.builds(
        _evidence,
        kind=st.sampled_from(_KINDS),
        polarity=st.sampled_from(list(EvidencePolarity)),
        strength=_strengths,
        independence_group=st.one_of(
            st.none(), st.sampled_from(["src/a", "src/b", "ext/c"]), st.just("ext/c")
        ),
        source_id=st.one_of(st.none(), st.just(SOURCE_A), st.just(SOURCE_B)),
        domain=st.one_of(st.none(), st.sampled_from(["ritual", "food"])),
        register=st.one_of(st.none(), st.sampled_from(["traditional", "informal"])),
        extensions=st.one_of(st.none(), st.just(_RELATED_EXTENSION)),
    ),
    max_size=6,
)
_statuses = st.sampled_from(
    [status for status in LifecycleStatus if status is not LifecycleStatus.VALIDATED]
)
_breakdowns = st.builds(
    LexicalScoreBreakdown,
    policy_version=st.sampled_from([POLICY_VERSION, "lexical-v0"]),
    overall=st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    components=st.dictionaries(
        st.just("alignment_support"), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
    ),
    penalties=st.dictionaries(
        st.just("formulaic_source"), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
    ),
    independence_groups=st.lists(st.sampled_from(["src/a"]), max_size=2),
)


@given(items=_items, target=st.one_of(st.none(), st.just(TARGET_LANGUAGE)))
def test_scores_stay_in_range_and_are_order_independent(
    items: list[EvidenceItem], target: str | None
) -> None:
    forward = DEFAULT_POLICY.compute_score(items, target_language=target)
    backward = DEFAULT_POLICY.compute_score(list(reversed(items)), target_language=target)

    assert 0.0 <= forward.overall <= 1.0
    assert all(0.0 <= value <= 1.0 for value in forward.components.values())
    assert all(0.0 <= value <= 1.0 for value in forward.penalties.values())
    assert math.isfinite(forward.overall)
    assert forward.independence_groups == sorted(set(forward.independence_groups))
    assert forward == backward


@given(items=_items, status=_statuses, breakdown=_breakdowns)
def test_promotion_never_validates_by_return_value(
    items: list[EvidenceItem], status: LifecycleStatus, breakdown: LexicalScoreBreakdown
) -> None:
    # Machine confidence alone MUST NOT create VALIDATED, for any input combination
    # (EVIDENCE-AND-CONFIDENCE.md:61-63; AGENTS.md invariant 3).
    result = DEFAULT_POLICY.evaluate_promotion(status, breakdown, items, TARGET_LANGUAGE)

    assert result is not LifecycleStatus.VALIDATED


def test_no_scoring_path_produces_validated() -> None:
    # Every reachable status except VALIDATED (refused, never adjudicated), across every
    # evidence kind, with the strongest possible breakdown attached.
    strongest = _breakdown(overall=1.0)
    statuses = [status for status in LifecycleStatus if status is not LifecycleStatus.VALIDATED]
    for status in statuses:
        for kind in _KINDS:
            items = _rich() + [
                _evidence(
                    kind=kind,
                    polarity=EvidencePolarity.CONTRADICTS,
                    independence_group=f"ext/{index}",
                )
                for index, kind in enumerate(_KINDS)
            ]
            assert (
                DEFAULT_POLICY.evaluate_promotion(status, strongest, items, TARGET_LANGUAGE)
                is not LifecycleStatus.VALIDATED
            )


def test_maximum_evidence_still_never_validates() -> None:
    # Every component at 1.0, infinite diversity, both polarities of every kind present.
    items = _rich() + [
        _evidence(
            kind=kind,
            polarity=EvidencePolarity.CONTRADICTS,
            independence_group=f"ext/{index}",
            domain="food",
            register="informal",
        )
        for index, kind in enumerate(_KINDS)
    ]

    for status in list(LifecycleStatus):
        if status is LifecycleStatus.VALIDATED:
            continue  # refused, see test_promotion_refuses_to_adjudicate_a_validated_object
        assert (
            evaluate_promotion(status, _breakdown(overall=1.0), items, TARGET_LANGUAGE)
            is not LifecycleStatus.VALIDATED
        )
    # With every gate satisfying, the strongest available outcome is SUPPORTED.
    assert (
        evaluate_promotion(
            LifecycleStatus.CANDIDATE, _breakdown(overall=1.0), _rich(), TARGET_LANGUAGE
        )
        is LifecycleStatus.SUPPORTED
    )
