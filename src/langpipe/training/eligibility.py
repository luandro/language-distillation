"""Data-eligibility gate for NLLB training rows.

This gate is a **traceability** check, not a rights check (ADR-0025). A row is
eligible when it carries some provenance identity — ``source_id``, ``policy_id``,
or ``provenance`` — so that it can be traced back into the repository. License,
ownership, register, and policy mode are recorded metadata; they never block a
row.

The gate once rejected ``corpus:`` and ``harvested:`` provenance unconditionally.
ADR-0025 removed that blocklist: a source present in the repository is eligible.
"""

from __future__ import annotations

from typing import Any

REASON_MISSING_TRACEABILITY = "missing traceability id"
_TRACEABILITY_KEYS: tuple[str, ...] = ("source_id", "policy_id", "provenance")


def _rejection_reason(row: dict[str, Any]) -> str | None:
    """Return why ``row`` is malformed, or None when it carries a trace id."""
    for key in _TRACEABILITY_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return None
    return REASON_MISSING_TRACEABILITY


def filter_eligible(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split ``rows`` into (eligible, rejected).

    Rejected rows are returned as copies with a ``rejection_reason`` string added.
    Input rows are not mutated.
    """
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        reason = _rejection_reason(row)
        if reason is None:
            eligible.append(row)
        else:
            rejected.append({**row, "rejection_reason": reason})
    return eligible, rejected
