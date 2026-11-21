"""Milestone 5 morphology induction protocol and DTOs (M5-PLAN §6 WP5.8, ADR-0017).

Pure in-memory contracts between the morphology service (WP5.9) and its adapters.
Producers consume pinned input tokens/inventory and return analyses, segments, features,
evidence, lineage edges and abstentions. Nothing here touches storage or governance policy.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from langpipe.domain.enums import Abstention
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.igt import IGTObservation
from langpipe.domain.models.morphology import (
    Allomorph,
    Feature,
    MorphAnalysis,
    Morpheme,
    MorphSegment,
    MorphSegmentFeature,
)
from langpipe.domain.models.observation import TokenOccurrence
from langpipe.text.registry import Versioned


@dataclass(frozen=True)
class MorphAnalysisCandidate:
    """One candidate analysis with its constituent segments and feature assignments."""

    analysis: MorphAnalysis
    segments: Sequence[MorphSegment] = ()
    features: Sequence[MorphSegmentFeature] = ()


@dataclass(frozen=True)
class MorphologyInventory:
    """An inventory of morphemes, allomorphs and their evidence pinned by run id."""

    run_id: str
    morphemes: Sequence[Morpheme] = ()
    allomorphs: Sequence[Allomorph] = ()
    evidence_items: Sequence[EvidenceItem] = ()
    analyses: Sequence[MorphAnalysis] = ()
    surface_signatures: Mapping[str, Sequence[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class MorphologyInductionInput:
    """One pinned morphology induction request.

    `tokens` are pinned tokens with their `normalized_surface` (or raw if unnormalized).
    `profile` is the language morphology profile.
    `inventory` carries optional existing morphemes and allomorphs pinned by run id.
    `training_tokens` carries optional tokens for unsupervised induction baselines.
    `policy` carries optional scoring policy parameters.
    `observations` carries optional parsed IGT observation records.
    `contact_language` carries optional contact language code for glosses.
    """

    run_id: str
    language: str
    tokens: Sequence[TokenOccurrence]
    profile: Any | None = None
    inventory: MorphologyInventory | None = None
    training_tokens: Sequence[TokenOccurrence] | None = None
    policy: Any | None = None
    observations: Sequence[IGTObservation] = ()
    contact_language: str | None = None
    segment_ancestors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MorphologyInductionOutput:
    """Candidate morphology hypotheses, evidence, lineage and abstentions.

    Analyses, morphemes and allomorphs are hypotheses (candidate or supported; never validated).
    Abstentions record per-token reasons for unanalyzed tokens (ADR-0017 §5).
    """

    analyses: Sequence[MorphAnalysisCandidate] = field(default_factory=list)
    morphemes: Sequence[Morpheme] = field(default_factory=list)
    allomorphs: Sequence[Allomorph] = field(default_factory=list)
    features: Sequence[Feature] = field(default_factory=list)
    evidence_items: Sequence[EvidenceItem] = field(default_factory=list)
    lineage_edges: Sequence[LineageEdge] = field(default_factory=list)
    abstentions: Mapping[str, Abstention] = field(default_factory=dict)
    words_mapped: int = 0
    words_unmapped: Mapping[str, int] = field(default_factory=dict)


class MorphologyInducer(Versioned, Protocol):
    """Protocol for versioned morphology candidate inducers (name@version).

    An inducer MUST NOT create `validated` status (Invariant 3).
    """

    name: ClassVar[str]
    version: ClassVar[str]

    def induce(self, input: MorphologyInductionInput) -> MorphologyInductionOutput:
        """Induce candidate morphology analyses from pinned input."""
        ...


__all__ = [
    "MorphAnalysisCandidate",
    "MorphologyInducer",
    "MorphologyInductionInput",
    "MorphologyInductionOutput",
    "MorphologyInventory",
]
