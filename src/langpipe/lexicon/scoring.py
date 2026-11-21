"""Lexical evidence scoring policy (WP4.4: M4-PLAN §6, ADR-0013 §3, EVIDENCE-AND-CONFIDENCE).

Pure domain logic: no storage, no network, no source text. The policy turns a set of
`EvidenceItem`s about one lexical hypothesis into a versioned `LexicalScoreBreakdown`
and decides the automated `candidate` -> `supported` transition. Machine confidence
never creates `validated`: this module returns `SUPPORTED` at most, and refuses to
adjudicate an object that a human already validated (Invariant 3).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LifecycleStatus
from langpipe.domain.errors import InvalidTransition
from langpipe.domain.models.evidence import EvidenceItem
from langpipe.domain.models.lexical import LexicalScoreBreakdown

POLICY_VERSION: Final = "lexical-v1"

# Raw score components, in breakdown order (EVIDENCE-AND-CONFIDENCE.md §Score breakdown).
ALIGNMENT_SUPPORT: Final = "alignment_support"
SOURCE_DIVERSITY: Final = "source_diversity"
DICTIONARY_SUPPORT: Final = "dictionary_support"
IGT_SUPPORT: Final = "igt_support"
MONOLINGUAL_SUPPORT: Final = "monolingual_support"
DOMAIN_STABILITY: Final = "domain_stability"
COMPONENTS: Final = (
    ALIGNMENT_SUPPORT,
    SOURCE_DIVERSITY,
    DICTIONARY_SUPPORT,
    IGT_SUPPORT,
    MONOLINGUAL_SUPPORT,
    DOMAIN_STABILITY,
)

# Raw penalty components, in breakdown order.
FORMULAIC_SOURCE: Final = "formulaic_source"
SINGLE_REGISTER_CONCENTRATION: Final = "single_register_concentration"
RELATED_LANGUAGE_ONLY: Final = "related_language_only"
PENALTIES: Final = (FORMULAIC_SOURCE, SINGLE_REGISTER_CONCENTRATION, RELATED_LANGUAGE_ONLY)

# The component each evidence kind may feed. Kinds absent here (grammar descriptions,
# morphology inductions, speaker review, manual annotation, related-language comparison)
# corroborate only through source diversity: they are not direct evidence about one
# target-language lexical hypothesis.
COMPONENT_KINDS: Final[dict[EvidenceKind, str]] = {
    EvidenceKind.DICTIONARY_ASSERTION: DICTIONARY_SUPPORT,
    EvidenceKind.TOKEN_ALIGNMENT: ALIGNMENT_SUPPORT,
    EvidenceKind.SEGMENT_COOCCURRENCE: ALIGNMENT_SUPPORT,
    EvidenceKind.IGT_ASSERTION: IGT_SUPPORT,
    EvidenceKind.MONOLINGUAL_DISTRIBUTION: MONOLINGUAL_SUPPORT,
}

# Extension marker an adapter may set on evidence that describes another language
# (e.g. a Portuguese gloss recorded as an external hypothesis).
_RELATED_NAMESPACE: Final = "langpipe.scoring"
_RELATED_FLAG: Final = "related_language"

# Strength default when an item records no value for its component: a recorded,
# governed, supporting assertion is support at full weight. Recorded non-finite or
# out-of-range values are clamped, never credited beyond the [0, 1] range.
_DEFAULT_STRENGTH: Final = 1.0


def _clamp(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return min(1.0, max(0.0, value))


def _recorded_strength(item: EvidenceItem, component: str) -> float:
    if component not in item.strength:
        return _DEFAULT_STRENGTH
    value = item.strength[component]
    if isinstance(value, bool) or not math.isfinite(value):
        return 0.0
    return _clamp(value)


def _independence_axis(item: EvidenceItem) -> str | None:
    # Independence markers, most to least specific (EVIDENCE-AND-CONFIDENCE.md
    # §Evidence independence): an explicit group, else the source.
    if item.independence_group:
        return item.independence_group
    source: str | None = item.source_id
    return source or None


def _established_axes(evidence_items: Sequence[EvidenceItem]) -> set[str]:
    # Only an established axis corroborates: an item with neither `independence_group`
    # nor `source_id` supplies no independence marker, so it never counts as a source
    # (EVIDENCE-AND-CONFIDENCE.md §Evidence independence). The observation itself is
    # preserved everywhere else: `independence_groups` and `compute_score` record it.
    return {axis for axis in map(_independence_axis, evidence_items) if axis is not None}


def _axis_counts(evidence_items: Sequence[EvidenceItem]) -> Counter[str]:
    # Items per established axis: two items of one group are not independent
    # corroboration. An item with no established axis joins none, so unknown provenance
    # is neither an axis of its own nor a repeat of an established one.
    return Counter(axis for axis in map(_independence_axis, evidence_items) if axis is not None)


@dataclass(frozen=True)
class LexicalScorePolicy:
    """Versioned weights, penalties and gates for lexical evidence scoring.

    Component weights must be positive and sum to 1.0; penalties and the promotion
    threshold live in [0.0, 1.0]. No field carries text, paths or credentials.
    """

    alignment_support_weight: float = 0.30
    source_diversity_weight: float = 0.20
    dictionary_support_weight: float = 0.20
    igt_support_weight: float = 0.10
    monolingual_support_weight: float = 0.10
    domain_stability_weight: float = 0.10
    formulaic_source_penalty: float = 0.10
    single_register_concentration_penalty: float = 0.05
    promotion_threshold: float = 0.75
    min_independent_sources: int = 2
    # When true, evidence whose `claim["language"]` names a language other than the
    # target counts as related-language evidence. Off by default: no adapter in this
    # milestone records claim languages, so the policy stays literal to WP4.4.
    claim_language_is_related: bool = False

    def __post_init__(self) -> None:
        weights = self._weights()
        for name in COMPONENTS:
            if not weights[name] > 0.0:
                raise ValueError(f"component weight {name} must be positive")
        total = math.fsum(weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError("component weights must sum to 1.0")
        for name in PENALTIES[:2]:
            penalty = getattr(self, f"{name}_penalty")
            if not 0.0 <= penalty <= 1.0:
                raise ValueError(f"penalty {name} must be between 0.0 and 1.0")
        if not 0.0 <= self.promotion_threshold <= 1.0:
            raise ValueError("promotion_threshold must be between 0.0 and 1.0")
        if self.min_independent_sources < 1:
            raise ValueError("min_independent_sources must be at least 1")

    def _weights(self) -> dict[str, float]:
        return {name: getattr(self, f"{name}_weight") for name in COMPONENTS}

    def _is_related(self, item: EvidenceItem, target_language: str | None) -> bool:
        # Invariant 8: related-language evidence never promotes target-language knowledge.
        if item.kind is EvidenceKind.RELATED_LANGUAGE_COMPARISON:
            return True
        if item.extensions.get(_RELATED_NAMESPACE, {}).get(_RELATED_FLAG):
            return True
        if not self.claim_language_is_related:
            return False
        claim = item.claim or {}
        language = claim.get("language")
        if not isinstance(language, str) or not language:
            return False
        return target_language is None or language != target_language

    def compute_score(
        self,
        evidence_items: Sequence[EvidenceItem],
        target_language: str | None = None,
    ) -> LexicalScoreBreakdown:
        """Aggregate `evidence_items` into a versioned breakdown. Order-independent.

        `independence_groups` lists every independence axis observed on the evidence,
        resolved as the explicit `independence_group`, else the `source_id`: contradictions
        and related-language evidence are recorded but never add support. Diversity counts
        only these established axes: an item with no axis is a distinct observation, not an
        independent source, and never supplies the second axis a promotion gate needs.
        """
        supporting = [i for i in evidence_items if i.polarity is EvidencePolarity.SUPPORTS]
        target_evidence = [
            item for item in supporting if not self._is_related(item, target_language)
        ]

        components = {name: 0.0 for name in COMPONENTS}
        for item in target_evidence:
            component = COMPONENT_KINDS.get(item.kind)
            if component is None:
                continue
            components[component] = max(components[component], _recorded_strength(item, component))
        axes = _established_axes(target_evidence)
        components[SOURCE_DIVERSITY] = _clamp(len(axes) / self.min_independent_sources)
        components[DOMAIN_STABILITY] = self._domain_stability(target_evidence)

        duplicated = sum(count for count in _axis_counts(target_evidence).values() if count > 1)
        penalties = {
            FORMULAIC_SOURCE: self.formulaic_source_penalty * (duplicated / len(target_evidence))
            if target_evidence
            else 0.0,
            SINGLE_REGISTER_CONCENTRATION: self.single_register_concentration_penalty
            if len({item.register for item in target_evidence if item.register}) == 1
            else 0.0,
            RELATED_LANGUAGE_ONLY: 1.0 if supporting and not target_evidence else 0.0,
        }

        weighted = math.fsum(weight * components[name] for name, weight in self._weights().items())
        overall = _clamp(weighted - math.fsum(penalties.values()))
        axes = _established_axes(evidence_items)
        return LexicalScoreBreakdown(
            policy_version=POLICY_VERSION,
            overall=overall,
            components=components,
            penalties=penalties,
            independence_groups=sorted(axes),
        )

    @staticmethod
    def _domain_stability(target_evidence: Sequence[EvidenceItem]) -> float:
        if not target_evidence:
            return 0.0
        domains = {item.domain for item in target_evidence if item.domain}
        if not domains:
            return 1.0
        # One agreed domain is stable; every additional distinct domain is disagreement.
        return _clamp(1.0 / len(domains))

    def evaluate_promotion(
        self,
        current_status: LifecycleStatus,
        breakdown: LexicalScoreBreakdown,
        evidence_items: Sequence[EvidenceItem],
        target_language: str,
    ) -> LifecycleStatus:
        """Return the status an automated scoring policy may set for this hypothesis.

        Only `candidate` -> `supported` is ever produced (Invariant 3). A validated
        object is never machine-adjudicated: an already-validated hypothesis may only
        be retired by a human decision, so this refuses it instead of demoting it.
        """
        if current_status is LifecycleStatus.VALIDATED:
            raise InvalidTransition()
        if current_status is not LifecycleStatus.CANDIDATE:
            return current_status
        return (
            LifecycleStatus.SUPPORTED
            if self._promotable(breakdown, evidence_items, target_language)
            else LifecycleStatus.CANDIDATE
        )

    def _promotable(
        self,
        breakdown: LexicalScoreBreakdown,
        evidence_items: Sequence[EvidenceItem],
        target_language: str,
    ) -> bool:
        if breakdown.policy_version != POLICY_VERSION:
            return False
        if breakdown.overall < self.promotion_threshold:
            return False
        supporting = [i for i in evidence_items if i.polarity is EvidencePolarity.SUPPORTS]
        target_evidence = [
            item for item in supporting if not self._is_related(item, target_language)
        ]
        if not supporting or not target_evidence:
            return False
        axes = _established_axes(target_evidence)
        if len(axes) < self.min_independent_sources:
            return False
        contradicting = [
            item for item in evidence_items if item.polarity is EvidencePolarity.CONTRADICTS
        ]
        # Contradiction is preserved, never averaged away (EVIDENCE-AND-CONFIDENCE.md).
        return self._mass(contradicting) <= self._mass(target_evidence)

    def _mass(self, evidence_items: Sequence[EvidenceItem]) -> float:
        total = 0.0
        for item in evidence_items:
            component = COMPONENT_KINDS.get(item.kind)
            if component is not None:
                total += _recorded_strength(item, component)
        return total


DEFAULT_POLICY: Final = LexicalScorePolicy()


def compute_score(
    evidence_items: Sequence[EvidenceItem],
    target_language: str | None = None,
) -> LexicalScoreBreakdown:
    """Score `evidence_items` under `DEFAULT_POLICY` (`lexical-v1`)."""
    return DEFAULT_POLICY.compute_score(evidence_items, target_language)


def evaluate_promotion(
    current_status: LifecycleStatus,
    breakdown: LexicalScoreBreakdown,
    evidence_items: Sequence[EvidenceItem],
    target_language: str,
) -> LifecycleStatus:
    """Evaluate the candidate -> supported transition under `DEFAULT_POLICY`."""
    return DEFAULT_POLICY.evaluate_promotion(
        current_status, breakdown, evidence_items, target_language
    )


__all__ = [
    "COMPONENTS",
    "COMPONENT_KINDS",
    "DEFAULT_POLICY",
    "PENALTIES",
    "POLICY_VERSION",
    "LexicalScorePolicy",
    "compute_score",
    "evaluate_promotion",
]
