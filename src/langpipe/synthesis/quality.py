"""Quality, Judgment Data Models, and Decision Rules for Synthetic Data.

Follows ADR-0006 and ADR-0020:
- Clef judges operate on pivot-language frames and structural alignment.
- Automated confidence never promotes to 'validated' (only human authorities can).
- Semantically absurd phrases or selectional violations are quarantined.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class QualityStatus(StrEnum):
    """Quality lifecycle status for synthetic phrases."""

    PASSED_AUTOMATED = "passed_automated"  # Grounded & semantically plausible automated pass
    NEEDS_REVIEW = "needs_review"  # Uncertain band or judge inconsistency
    QUARANTINED = "quarantined"  # Confident semantic or selectional failure (set aside)
    REJECTED = "rejected"  # Hard fail (lexical hallucination or structural invalidity)


class FailureReason(StrEnum):
    """Specific failure reasons for quarantined or rejected phrases."""

    HALLUCINATION = "hallucination"
    GLOSS_MISMATCH = "gloss_mismatch"
    TAM_MISMATCH = "tam_mismatch"
    STRUCTURAL = "structural"
    SELECTIONAL_VIOLATION = "selectional_violation"
    SEMANTIC_IMPLAUSIBILITY = "semantic_implausibility"
    TRANSLATION_INFIDELITY = "translation_infidelity"
    UNNATURAL = "unnatural"
    JUDGE_INCONSISTENT = "judge_inconsistent"


@dataclass
class ClefJudgment:
    """Record of a Clef quality evaluation for a synthetic phrase."""

    judgment_id: str
    phrase_id: str
    judge_model: str
    calibration_status: str  # "uncalibrated" | "calibrated"
    checks: dict[str, bool] = field(default_factory=dict)
    answers: dict[str, Any] = field(default_factory=dict)
    status: QualityStatus = QualityStatus.NEEDS_REVIEW
    reasons: list[FailureReason] = field(default_factory=list)
    score: float = 0.0
    critique: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert judgment to JSON-serializable dictionary."""
        d = asdict(self)
        d["status"] = self.status.value
        d["reasons"] = [r.value if isinstance(r, FailureReason) else str(r) for r in self.reasons]
        return d


def compute_judgment_id(phrase: str, judge_version: str = "v1") -> str:
    """Generate deterministic hash ID for a phrase judgment."""
    raw = f"{phrase.strip().lower()}:{judge_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def decide_quality(
    grounding_valid: bool,
    l1_checks: dict[str, bool],
    l2_answers: dict[str, Any],
    calibration_status: str = "uncalibrated",
) -> tuple[QualityStatus, list[FailureReason], float, str]:
    """Pure decision rule for synthetic data quality grading.

    Args:
        grounding_valid: True if Invariant 9 passes (zero lexical hallucination).
        l1_checks: Results of deterministic structural checks (tam_consistent, roles_valid, etc.).
        l2_answers: Answers from semantic Clef judge (p_plausible, p_fidelity, selection_viol).
        calibration_status: Whether the judge has passed the calibration benchmark gate.

    Returns:
        tuple of (status, reasons, score, critique)
    """
    reasons: list[FailureReason] = []

    # 1. Hard fail L0: Hallucination
    if not grounding_valid:
        reasons.append(FailureReason.HALLUCINATION)
        return (
            QualityStatus.REJECTED,
            reasons,
            0.0,
            "Rejeitado: Violação do Invariante 9 (lemas ou afixos não atestados no LKB).",
        )

    # 2. Hard fail L1: Structural checks
    if not l1_checks.get("tam_consistent", True):
        reasons.append(FailureReason.TAM_MISMATCH)
    if not l1_checks.get("igt_aligned", True):
        reasons.append(FailureReason.GLOSS_MISMATCH)
    if not l1_checks.get("roles_consistent", True):
        reasons.append(FailureReason.STRUCTURAL)

    p_plausible = float(l2_answers.get("p_plausible", 0.5))
    p_implausible = float(l2_answers.get("p_implausible", 0.5))
    p_fidelity = float(l2_answers.get("p_fidelity", 1.0))
    selection_violation = bool(l2_answers.get("selection_violation", False))
    violation_detail = l2_answers.get("violation_detail", "")

    # Check for judge inconsistency (e.g. both plausible and implausible high or low)
    if abs((p_plausible + p_implausible) - 1.0) > 0.4:
        reasons.append(FailureReason.JUDGE_INCONSISTENT)

    if selection_violation:
        reasons.append(FailureReason.SELECTIONAL_VIOLATION)
    if p_plausible < 0.4:
        reasons.append(FailureReason.SEMANTIC_IMPLAUSIBILITY)
    if p_fidelity < 0.5:
        reasons.append(FailureReason.TRANSLATION_INFIDELITY)

    # Calculate overall quality score
    score = round(max(0.0, min(1.0, p_plausible * p_fidelity)), 3)

    critique_parts: list[str] = []
    if FailureReason.SELECTIONAL_VIOLATION in reasons:
        detail = violation_detail or "argumentos incompatíveis com o predicado"
        critique_parts.append(f"Violação Selecional: {detail}.")
    if FailureReason.SEMANTIC_IMPLAUSIBILITY in reasons:
        critique_parts.append("Semântica Implausível: evento absurdo ou improvável no mundo real.")
    if FailureReason.TAM_MISMATCH in reasons:
        critique_parts.append(
            "Conflito TAM: sufixos de tempo/modo/aspecto em desacordo com a tradução em português."
        )
    if FailureReason.GLOSS_MISMATCH in reasons:
        critique_parts.append("Desalinhamento IGT: discrepância entre glosa interlinear e texto.")

    # Status classification
    quarantine_conditions = (
        FailureReason.TAM_MISMATCH in reasons
        or FailureReason.GLOSS_MISMATCH in reasons
        or FailureReason.SELECTIONAL_VIOLATION in reasons
        or p_plausible < 0.4
    )
    if quarantine_conditions:
        status = QualityStatus.QUARANTINED
    elif FailureReason.JUDGE_INCONSISTENT in reasons or (0.4 <= p_plausible < 0.75):
        status = QualityStatus.NEEDS_REVIEW
    else:
        status = QualityStatus.PASSED_AUTOMATED

    critique = " ".join(critique_parts) or "Aprovado: Frase válida gramatical e semanticamente."

    return (status, reasons, score, critique)
