"""High-throughput batch generation and multi-gate rejection pipeline (Milestone 2, WP 2.3).

Executes end-to-end synthesis with three strict validation gates:
- Gate L0: GroundingValidator (Invariant 9: attested stems and approved affixes only)
- Gate L1: Structural & Valence Gate (transitivity harmony, TAM consistency, Leipzig IGT count)
- Gate L2: Clef Quality Judge (pivot-side semantic plausibility without target-language egress)

Saves validated and quarantined sets deterministically to disk.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from langpipe.languages.base import profile_for
from langpipe.lexicon.audit.view import LexiconView
from langpipe.synthesis.clef import ClefJudge, get_clef_judge
from langpipe.synthesis.curriculum import StratifiedCurriculumGenerator
from langpipe.synthesis.grounding import GroundingValidator
from langpipe.synthesis.quality import QualityStatus
from langpipe.synthesis.structural import check_structural_alignment


@dataclass
class BatchSynthesisSummary:
    """Statistical summary of a batch generation run."""

    target_language: str
    total_requested: int
    total_generated: int
    passed_count: int
    quarantined_count: int
    needs_review_count: int
    gate_l0_failures: int = 0
    gate_l1_failures: int = 0
    gate_l2_failures: int = 0
    output_file: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HighThroughputBatchHarness:
    """Batch generator coordinating curriculum synthesis, LLM expansion, and 3-gate rejection."""

    def __init__(
        self,
        lang_code: str = "und",
        provider_name: str = "mock",
        output_dir: Path | str | None = None,
        use_clef: bool = True,
    ) -> None:
        self.lang_code = lang_code
        self.profile = profile_for(lang_code)
        self.lexicon_view = LexiconView.load(lang_code=lang_code, view="clean")

        self.curriculum = StratifiedCurriculumGenerator(
            lang_code=lang_code, lexicon_view=self.lexicon_view
        )
        self.grounding = GroundingValidator(lang_code=lang_code, lexicon_view=self.lexicon_view)
        self.judge: ClefJudge | None = get_clef_judge(lang_code=lang_code) if use_clef else None

        self.output_dir = Path(output_dir) if output_dir else Path("exports") / lang_code
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_batch(
        self,
        target_count: int = 50,
        seed: int = 42,
    ) -> tuple[list[dict[str, Any]], BatchSynthesisSummary]:
        """Execute batch generation through L0, L1, and L2 gates."""
        summary = BatchSynthesisSummary(
            target_language=self.lang_code,
            total_requested=target_count,
            total_generated=0,
            passed_count=0,
            quarantined_count=0,
            needs_review_count=0,
        )

        # 1. Generate curriculum candidate batch
        candidates = self.curriculum.generate_batch(total_count=target_count, seed=seed)
        summary.total_generated = len(candidates)

        validated_phrases: list[dict[str, Any]] = []

        for c in candidates:
            target = c["target"]
            portuguese = c["portuguese"]
            igt = c.get("igt", "")

            # Gate L0: Lexical Grounding
            g_rep = self.grounding.validate(target)
            if not g_rep.valid:
                summary.gate_l0_failures += 1
                summary.quarantined_count += 1
                c["valid"] = False
                c["quarantined"] = True
                c["quality"] = {
                    "status": QualityStatus.QUARANTINED.value,
                    "score": 0.0,
                    "confidence": 1.0,
                    "reasons": g_rep.errors,
                }
                validated_phrases.append(c)
                continue

            # Gate L1: Structural & Valence Alignment
            s_rep = check_structural_alignment(
                target_phrase=target,
                igt_gloss=igt,
                portuguese_translation=portuguese,
                lang_code=self.lang_code,
            )
            if not (s_rep["tam_consistent"] and s_rep["roles_consistent"]):
                summary.gate_l1_failures += 1
                summary.quarantined_count += 1
                c["valid"] = False
                c["quarantined"] = True
                reasons = []
                if not s_rep["tam_consistent"]:
                    reasons.append("TAM suffix inconsistent with Portuguese translation.")
                if not s_rep["roles_consistent"]:
                    reasons.append("Transitivity harmony or role marking mismatch.")
                c["quality"] = {
                    "status": QualityStatus.QUARANTINED.value,
                    "score": 0.1,
                    "confidence": 1.0,
                    "reasons": reasons,
                }
                validated_phrases.append(c)
                continue

            # Gate L2: Clef Semantic Plausibility
            if self.judge:
                j_rep = self.judge.judge_phrase(
                    target_phrase=target,
                    igt_gloss=igt,
                    portuguese_translation=portuguese,
                    grounding_report=g_rep,
                    l1_checks=s_rep,
                )
                c["quality"] = j_rep.to_dict()
                if j_rep.status == QualityStatus.QUARANTINED:
                    summary.gate_l2_failures += 1
                    summary.quarantined_count += 1
                    c["quarantined"] = True
                    c["valid"] = False
                elif j_rep.status == QualityStatus.NEEDS_REVIEW:
                    summary.needs_review_count += 1
                    c["quarantined"] = False
                    c["valid"] = True
                    summary.passed_count += 1
                else:
                    c["quarantined"] = False
                    c["valid"] = True
                    summary.passed_count += 1
            else:
                c["quarantined"] = False
                c["valid"] = True
                summary.passed_count += 1

            validated_phrases.append(c)

        # Save to disk
        out_path = self.output_dir / "synthetic_phrases.json"
        summary.output_file = str(out_path)
        payload = {
            "metadata": summary.to_dict(),
            "phrases": validated_phrases,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return validated_phrases, summary
