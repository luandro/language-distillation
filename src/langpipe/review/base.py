"""Shared human review contracts (M4-PLAN §6 WP4.8, ADR-0013 §4-5).

Small, stable types shared by the authority registry and the review service. The
review queue is the only writer of `validated`/`rejected` lifecycle status, so its
failure vocabulary is part of the invariant surface (AGENTS.md invariant 3).
"""

from langpipe.domain.enums import ReviewTaskType
from langpipe.domain.errors import LangpipeError

# ADR-0013 §5: the queue schema supports every ReviewTaskType, but M4 services and the
# CLI generate lexical task types only.
M4_TASK_TYPES: frozenset[ReviewTaskType] = frozenset(
    {
        ReviewTaskType.LEXICAL_SENSE,
        ReviewTaskType.LEMMA,
        ReviewTaskType.REGISTER_DOMAIN,
        ReviewTaskType.GOVERNANCE_EXPORT,
    }
)

# M5-PLAN §7.11, WP5.13: morphology review task types.
M5_TASK_TYPES: frozenset[ReviewTaskType] = M4_TASK_TYPES | frozenset(
    {
        ReviewTaskType.MORPHOLOGY_SEGMENTATION,
        ReviewTaskType.MORPHEME_FUNCTION,
    }
)


class UnauthorizedReviewer(LangpipeError, PermissionError):
    """A reviewer, role, language or domain combination the registry does not authorize.

    Also a `PermissionError`, so callers may catch either the typed error or the builtin.
    The service raises this before any write: an unauthorized decision changes nothing.
    """

    exit_code = 13

    def __init__(self, reviewer_id: str, reviewer_role: str, language: str) -> None:
        self.reviewer_id = reviewer_id
        self.reviewer_role = reviewer_role
        self.language = language
        super().__init__(
            f"unauthorized reviewer: reviewer={reviewer_id} role={reviewer_role} "
            f"language={language}"
        )


__all__ = ["M4_TASK_TYPES", "M5_TASK_TYPES", "UnauthorizedReviewer"]
