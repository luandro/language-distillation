"""Stage 6 lexical evidence: evidence scoring and candidate promotion gates (M4)."""

from langpipe.lexicon.scoring import (
    COMPONENTS,
    DEFAULT_POLICY,
    PENALTIES,
    POLICY_VERSION,
    LexicalScorePolicy,
    compute_score,
    evaluate_promotion,
)

__all__ = [
    "COMPONENTS",
    "DEFAULT_POLICY",
    "PENALTIES",
    "POLICY_VERSION",
    "LexicalScorePolicy",
    "compute_score",
    "evaluate_promotion",
]
