"""Governance decisions (M5-PLAN WP5.5, ADR-0018 §6).

`effective_policy` is the single door: every operation decision reads the static
`SourcePolicy` composed with the append-only approval overlay, and no module outside
this package or `storage/` consults the static policy directly (guarded by
`tests/unit/test_governance_single_door.py`). `policy` holds the ADR-0007 baseline
resolution, `guard` and `lineage_policy` its lineage-facing consumers.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langpipe.governance.approvals import (
        APPROVABLE_OPERATIONS,
        EffectivePolicy,
        effective_policy,
        get_source_policy,
        record_approval,
    )

__all__ = [
    "APPROVABLE_OPERATIONS",
    "EffectivePolicy",
    "effective_policy",
    "get_source_policy",
    "record_approval",
]


def __getattr__(name: str) -> object:
    if name in __all__:
        from langpipe.governance import approvals

        return getattr(approvals, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
