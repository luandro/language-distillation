"""Guard against re-adding a rights gate to the training eligibility path (ADR-0025)."""

from __future__ import annotations

from pathlib import Path

ELIGIBILITY = Path(__file__).resolve().parents[2] / "src/langpipe/training/eligibility.py"


def test_training_gate_does_not_consult_policy_or_a_provenance_blocklist() -> None:
    source = ELIGIBILITY.read_text(encoding="utf-8")

    # A rights gate would need a policy/mode lookup or a source-identity blocklist.
    assert "governance.policy" not in source
    assert "PolicyMode" not in source
    assert "REJECTED_PROVENANCE" not in source
    # It must still expose the one traceability check.
    assert "source_id" in source
    assert "policy_id" in source
    assert "provenance" in source
