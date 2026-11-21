from dataclasses import dataclass

import pytest

from langpipe.domain.enums import Operation, PolicyDecision, PolicyMode
from langpipe.domain.errors import PolicyConflict
from langpipe.governance.policy import (
    BASELINE,
    Baseline,
    baseline,
    resolve,
    validate_policy_lists,
)

# Column order: direct, distill_only, review_required, restricted, archive_only, exclude.
# Copied row by row from docs/adr/0007-source-policy-resolution.md, as amended by
# ADR-0025 (A=allow, D=default_deny, R=review, H=hard_deny).
# Do not edit to match the implementation.
ADR_0007_MATRIX: dict[Operation, str] = {
    Operation.INGEST: "AAAAAH",
    Operation.READ_RAW: "AARDDH",
    Operation.EXTRACT: "AARDHH",
    Operation.NORMALIZE: "AARDHH",
    Operation.ALIGN: "AARDHH",
    Operation.DISTILL_LEXICON: "AARDHH",
    Operation.DISTILL_MORPHOLOGY: "AARDHH",
    Operation.DISTILL_GRAMMAR: "AARDHH",
    Operation.AUDIO_ALIGN: "AARDHH",
    Operation.HUMAN_REVIEW: "AAADDH",
    Operation.EVALUATION: "AARDHH",
    Operation.DIRECT_TRAINING: "AARDHH",
    Operation.SYNTHETIC_GENERATION_SUPPORT: "AARDHH",
    Operation.THIRD_PARTY_API: "DDDDHH",
    Operation.CLOUD_PROCESSING: "DDDDHH",
    Operation.REDISTRIBUTE_DERIVED: "DDDDHH",
    Operation.REDISTRIBUTE_RAW: "DHDDHH",
}

_LETTER_TO_BASELINE = {
    "A": Baseline.ALLOW,
    "D": Baseline.DEFAULT_DENY,
    "R": Baseline.REVIEW,
    "H": Baseline.HARD_DENY,
}
_COLUMN_MODES = (
    PolicyMode.DIRECT,
    PolicyMode.DISTILL_ONLY,
    PolicyMode.REVIEW_REQUIRED,
    PolicyMode.RESTRICTED,
    PolicyMode.ARCHIVE_ONLY,
    PolicyMode.EXCLUDE,
)


@dataclass(frozen=True)
class _P:
    mode: PolicyMode
    allow: tuple[Operation, ...] = ()
    deny: tuple[Operation, ...] = ()


def test_matrix_is_total() -> None:
    assert set(ADR_0007_MATRIX) == set(Operation)
    for mode in PolicyMode:
        for op in Operation:
            assert isinstance(baseline(mode, op), Baseline)
            assert op in BASELINE[mode]


def test_matrix_matches_adr_0007() -> None:
    for op, row in ADR_0007_MATRIX.items():
        assert len(row) == len(_COLUMN_MODES)
        for mode, letter in zip(_COLUMN_MODES, row, strict=True):
            assert baseline(mode, op) is _LETTER_TO_BASELINE[letter], (mode, op)


def test_exclude_denies_everything() -> None:
    policy = _P(PolicyMode.EXCLUDE, allow=tuple(Operation))
    for op in Operation:
        assert resolve(policy, op) is PolicyDecision.DENY


def test_distill_only_direct_training_is_allowed() -> None:
    # ADR-0025: a source's classification never blocks training.
    assert baseline(PolicyMode.DISTILL_ONLY, Operation.DIRECT_TRAINING) is Baseline.ALLOW
    assert resolve(_P(PolicyMode.DISTILL_ONLY), Operation.DIRECT_TRAINING) is PolicyDecision.ALLOW
    assert baseline(PolicyMode.DISTILL_ONLY, Operation.EVALUATION) is Baseline.ALLOW
    assert (
        baseline(PolicyMode.DISTILL_ONLY, Operation.SYNTHETIC_GENERATION_SUPPORT) is Baseline.ALLOW
    )
    # The inverse of the removed conflict: an explicit allow for these operations now loads.
    validate_policy_lists(PolicyMode.DISTILL_ONLY, [Operation.DIRECT_TRAINING], [])
    validate_policy_lists(PolicyMode.DISTILL_ONLY, [Operation.EVALUATION], [])
    validate_policy_lists(PolicyMode.DISTILL_ONLY, [Operation.SYNTHETIC_GENERATION_SUPPORT], [])


def test_explicit_allow_cannot_lift_remaining_hard_deny() -> None:
    # `distill_only` keeps one hard deny: raw redistribution. ADR-0025 did not open it.
    with pytest.raises(PolicyConflict):
        validate_policy_lists(PolicyMode.DISTILL_ONLY, [Operation.REDISTRIBUTE_RAW], [])
    policy = _P(PolicyMode.DISTILL_ONLY, allow=(Operation.REDISTRIBUTE_RAW,))
    assert resolve(policy, Operation.REDISTRIBUTE_RAW) is PolicyDecision.DENY


def test_explicit_allow_lifts_default_deny() -> None:
    validate_policy_lists(PolicyMode.DIRECT, [Operation.THIRD_PARTY_API], [])
    policy = _P(PolicyMode.DIRECT, allow=(Operation.THIRD_PARTY_API,))
    assert resolve(policy, Operation.THIRD_PARTY_API) is PolicyDecision.ALLOW
    assert resolve(_P(PolicyMode.DIRECT), Operation.THIRD_PARTY_API) is PolicyDecision.DENY


def test_explicit_allow_lifts_review() -> None:
    assert (
        resolve(_P(PolicyMode.REVIEW_REQUIRED), Operation.EXTRACT) is PolicyDecision.REVIEW_REQUIRED
    )
    policy = _P(PolicyMode.REVIEW_REQUIRED, allow=(Operation.EXTRACT,))
    assert resolve(policy, Operation.EXTRACT) is PolicyDecision.ALLOW


def test_deny_overrides_allow() -> None:
    policy = _P(PolicyMode.DIRECT, allow=(Operation.EXTRACT,), deny=(Operation.EXTRACT,))
    assert resolve(policy, Operation.EXTRACT) is PolicyDecision.DENY


def test_outward_ops_never_baseline_allow() -> None:
    outward = (
        Operation.THIRD_PARTY_API,
        Operation.CLOUD_PROCESSING,
        Operation.REDISTRIBUTE_RAW,
        Operation.REDISTRIBUTE_DERIVED,
    )
    for mode in PolicyMode:
        for op in outward:
            assert baseline(mode, op) is not Baseline.ALLOW, (mode, op)
