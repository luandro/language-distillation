from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Protocol

from langpipe.domain.enums import Operation, PolicyDecision, PolicyMode
from langpipe.domain.errors import PolicyConflict


class PolicyLike(Protocol):
    @property
    def mode(self) -> PolicyMode: ...

    @property
    def allow(self) -> tuple[Operation, ...]: ...

    @property
    def deny(self) -> tuple[Operation, ...]: ...


class Baseline(StrEnum):
    ALLOW = "allow"
    DEFAULT_DENY = "default_deny"
    REVIEW = "review"
    HARD_DENY = "hard_deny"


_A = Baseline.ALLOW
_D = Baseline.DEFAULT_DENY
_R = Baseline.REVIEW
_H = Baseline.HARD_DENY

# ADR-0007 baseline matrix, amended by ADR-0025 (presence-based authorization).
# Column order matches _COLUMN_MODES.
_COLUMN_MODES: tuple[PolicyMode, ...] = (
    PolicyMode.DIRECT,
    PolicyMode.DISTILL_ONLY,
    PolicyMode.REVIEW_REQUIRED,
    PolicyMode.RESTRICTED,
    PolicyMode.ARCHIVE_ONLY,
    PolicyMode.EXCLUDE,
)

_ROWS: Mapping[Operation, tuple[Baseline, ...]] = {
    Operation.INGEST: (_A, _A, _A, _A, _A, _H),
    Operation.READ_RAW: (_A, _A, _R, _D, _D, _H),
    Operation.EXTRACT: (_A, _A, _R, _D, _H, _H),
    Operation.NORMALIZE: (_A, _A, _R, _D, _H, _H),
    Operation.ALIGN: (_A, _A, _R, _D, _H, _H),
    Operation.DISTILL_LEXICON: (_A, _A, _R, _D, _H, _H),
    Operation.DISTILL_MORPHOLOGY: (_A, _A, _R, _D, _H, _H),
    Operation.DISTILL_GRAMMAR: (_A, _A, _R, _D, _H, _H),
    Operation.AUDIO_ALIGN: (_A, _A, _R, _D, _H, _H),
    Operation.HUMAN_REVIEW: (_A, _A, _A, _D, _D, _H),
    Operation.EVALUATION: (_A, _A, _R, _D, _H, _H),
    Operation.DIRECT_TRAINING: (_A, _A, _R, _D, _H, _H),
    Operation.SYNTHETIC_GENERATION_SUPPORT: (_A, _A, _R, _D, _H, _H),
    Operation.THIRD_PARTY_API: (_D, _D, _D, _D, _H, _H),
    Operation.CLOUD_PROCESSING: (_D, _D, _D, _D, _H, _H),
    Operation.REDISTRIBUTE_DERIVED: (_D, _D, _D, _D, _H, _H),
    Operation.REDISTRIBUTE_RAW: (_D, _H, _D, _D, _H, _H),
}

BASELINE: Mapping[PolicyMode, Mapping[Operation, Baseline]] = {
    mode: {op: row[index] for op, row in _ROWS.items()} for index, mode in enumerate(_COLUMN_MODES)
}

# Most restrictive first; used by resolve_many.
_PERMISSION_RANK: Mapping[PolicyDecision, int] = {
    PolicyDecision.DENY: 0,
    PolicyDecision.REVIEW_REQUIRED: 1,
    PolicyDecision.ALLOW: 2,
}


def baseline(mode: PolicyMode, op: Operation) -> Baseline:
    return BASELINE[mode][op]


def validate_policy_lists(
    mode: PolicyMode, allow: Iterable[Operation], deny: Iterable[Operation]
) -> None:
    del deny  # deny lists never conflict with the baseline matrix
    for op in allow:
        if baseline(mode, op) is Baseline.HARD_DENY:
            raise PolicyConflict()


def resolve(policy: PolicyLike, op: Operation) -> PolicyDecision:
    if op in policy.deny:
        return PolicyDecision.DENY
    level = baseline(policy.mode, op)
    if level is Baseline.HARD_DENY:
        return PolicyDecision.DENY
    if op in policy.allow:
        return PolicyDecision.ALLOW
    if level is Baseline.ALLOW:
        return PolicyDecision.ALLOW
    if level is Baseline.DEFAULT_DENY:
        return PolicyDecision.DENY
    return PolicyDecision.REVIEW_REQUIRED


def resolve_many(policies: Iterable[PolicyLike], op: Operation) -> PolicyDecision:
    decisions: Sequence[PolicyDecision] = [resolve(policy, op) for policy in policies]
    if not decisions:
        return PolicyDecision.DENY
    return min(decisions, key=_PERMISSION_RANK.__getitem__)
