"""Milestone 5 morphology graph domain logic, protocol, and scoring (ADR-0017).

Provides canonical segmentation signatures, span validation, morphology inducer protocol,
identity key hashing and morph-v1 scoring policy.
"""

from langpipe.morphology.base import (
    MorphAnalysisCandidate,
    MorphologyInducer,
    MorphologyInductionInput,
    MorphologyInductionOutput,
    MorphologyInventory,
)
from langpipe.morphology.identity import morpheme_identity_key
from langpipe.morphology.scoring import (
    AMBIGUITY,
    BOUNDARY_MARK_SUPPORT,
    COMPONENTS,
    CONTRADICTION,
    CROSS_METHOD_AGREEMENT,
    DEFAULT_POLICY,
    FORM_DIVERSITY,
    IGT_INDEPENDENCE,
    IGT_SUPPORT,
    PENALTIES,
    POLICY_VERSION,
    PROJECTION_SUPPORT,
    UNKNOWN_SEGMENT,
    MorphScoringPolicy,
    score_allomorph,
    score_analysis,
    score_morpheme,
)
from langpipe.morphology.spans import (
    check_analysis,
    check_segments,
    segmentation_signature,
)
from langpipe.morphology.word_mapping import (
    WordMappingResult,
    is_pure_punctuation,
    map_words,
)

__all__ = [
    "AMBIGUITY",
    "BOUNDARY_MARK_SUPPORT",
    "COMPONENTS",
    "CONTRADICTION",
    "CROSS_METHOD_AGREEMENT",
    "DEFAULT_POLICY",
    "FORM_DIVERSITY",
    "IGT_INDEPENDENCE",
    "IGT_SUPPORT",
    "MorphAnalysisCandidate",
    "MorphScoringPolicy",
    "MorphologyInducer",
    "MorphologyInductionInput",
    "MorphologyInductionOutput",
    "MorphologyInventory",
    "PENALTIES",
    "POLICY_VERSION",
    "PROJECTION_SUPPORT",
    "UNKNOWN_SEGMENT",
    "WordMappingResult",
    "check_analysis",
    "check_segments",
    "is_pure_punctuation",
    "map_words",
    "morpheme_identity_key",
    "score_allomorph",
    "score_analysis",
    "score_morpheme",
    "segmentation_signature",
]
