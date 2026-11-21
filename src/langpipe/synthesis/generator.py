"""Synthetic Phrase Pipeline & Generation Engine.

Orchestrates prompt formatting, LLM completions (Poolside/OpenAI/Mock),
slot-filling grounding, and Leipzig IGT morphological verification.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from langpipe.synthesis.clef import ClefJudge, get_clef_judge
from langpipe.synthesis.grounding import GroundingReport, GroundingValidator
from langpipe.synthesis.providers import LLMProvider, get_provider
from langpipe.synthesis.quality import ClefJudgment, QualityStatus


@dataclass
class SyntheticPhrase:
    """A generated and grounded synthetic phrase with lineage."""

    target_phrase: str
    igt_gloss: str
    portuguese_translation: str
    grounding: GroundingReport
    provider: str
    model: str
    metadata: dict[str, Any]
    judgment: ClefJudgment | None = None

    def to_dict(self) -> dict[str, Any]:
        is_quarantined = self.judgment is not None and self.judgment.status in (
            QualityStatus.QUARANTINED,
            QualityStatus.REJECTED,
        )
        return {
            "target_phrase": self.target_phrase,
            "igt_gloss": self.igt_gloss,
            "portuguese_translation": self.portuguese_translation,
            "grounding": self.grounding.to_dict(),
            "valid": self.grounding.valid and not is_quarantined,
            "quarantined": is_quarantined,
            "quality": self.judgment.to_dict() if self.judgment else None,
            "provider": self.provider,
            "model": self.model,
            "metadata": self.metadata,
        }


class SyntheticPipeline:
    """End-to-end synthetic sentence generator and grounding engine."""

    def __init__(
        self,
        lang_code: str = "und",
        provider: LLMProvider | None = None,
        validator: GroundingValidator | None = None,
        judge: ClefJudge | None = None,
    ) -> None:
        self.lang_code = lang_code
        self.validator = validator or GroundingValidator(lang_code=lang_code)
        self.provider = provider or get_provider("poolside")
        self.judge = judge or get_clef_judge("heuristic", lang_code=lang_code)

    def _build_prompt(self, count: int = 5) -> list[dict[str, str]]:
        """Construct a grounded prompt strictly containing allowed LKB stems and affixes."""
        stems_sample = {
            k: v.get("glosses_por", []) for k, v in list(self.validator.stems.items())[:60]
        }
        affixes_sample = list(self.validator.affixes)

        system_prompt = (
            f"You are a computational linguist generating grounded synthetic training phrases for "
            f"{self.validator.language_name} ({self.lang_code}).\n"
            "CRITICAL INVARIANT 9: DO NOT invent any vocabulary or suffixes. "
            "Use ONLY stems from the provided lexicon.\n"
            "Grammar template for target language:\n"
            "- Word Order: SOV (Subject - Object - Verb)\n"
            "- Subject in transitive clause takes ERG suffix (e.g. '-n')\n"
            "- Direct object takes zero ABS marker\n"
            "- Verb inflects with TAM suffixes (e.g. '-ai' PRES, '-katsai' FUT, '-ma' NEG)\n"
            "Respond strictly with a valid JSON array of objects with keys: "
            "'target', 'igt', 'portugues'."
        )

        user_prompt = (
            f"Generate exactly {count} distinct, grammatically valid sentences in "
            f"{self.validator.language_name}.\n"
            f"Allowed Stems: {json.dumps(stems_sample, ensure_ascii=False)}\n"
            f"Allowed Affixes: {json.dumps(affixes_sample, ensure_ascii=False)}\n\n"
            "Output JSON format:\n"
            "[\n"
            "  {\n"
            '    "target": "vaki-n isu yamama-katsai",\n'
            '    "igt": "criança-ERG macaco matar-FUT",\n'
            '    "portugues": "O menino matará o macaco."\n'
            "  }\n"
            "]"
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _extract_json(self, raw_text: str) -> list[dict[str, Any]]:
        """Safely extract JSON array from LLM response text."""
        cleaned = raw_text.strip()
        # Strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        match = re.search(r"\[\s*\{.*\}\s*\]", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict) and "data" in parsed and isinstance(parsed["data"], list):
                return parsed["data"]
            return [parsed]
        except Exception:
            return []

    def _generate_slot_filled_fallback(self, count: int) -> list[dict[str, str]]:
        """Deterministic slot-filler adhering 100% to Invariant 9 and selectional restrictions."""
        coherent_frames = [
            ("vaki-n nami pi-ai", "vaki-n nami.ABS pi-ai", "A criança está comendo carne."),
            ("vaki-n nami pi-katsai", "vaki-n nami.ABS pi-katsai", "A criança comerá carne."),
            (
                "vaki-n nami pi-vai",
                "vaki-n nami.ABS pi-vai",
                "A criança comeu carne hoje cedo.",
            ),
            ("vaki-n nami pi-ma", "vaki-n nami.ABS pi-ma", "A criança não comeu carne."),
            ("yora-n isu ui-ai", "yora-n isu.ABS ui-ai", "A pessoa está vendo o macaco."),
            ("yora-n isu ui-katsai", "yora-n isu.ABS ui-katsai", "A pessoa verá o macaco."),
            (
                "yora-n isu yamama-katsai",
                "yora-n isu.ABS yamama-katsai",
                "O homem matará o macaco.",
            ),
            (
                "yora-n yapa vi-vai",
                "yora-n yapa.ABS vi-vai",
                "O homem pegou o peixe hoje cedo.",
            ),
            ("vaki-n yapa pi-ai", "vaki-n yapa.ABS pi-ai", "O menino come o peixe."),
            ("chai nuya-ai", "chai nuya-ai", "O pássaro está voando."),
            ("chai nuya-katsai", "chai nuya-katsai", "O pássaro voará amanhã."),
            ("chai nuya-tinpa", "chai nuya-tinpa", "O pássaro não pode voar."),
            ("vaki nuku-ai", "vaki nuku-ai", "A criança está chegando."),
            ("vaki nuku-katsai", "vaki nuku-katsai", "A criança chegará amanhã."),
            (
                "inõ-n mana yamama-vai",
                "inõ-n mana.ABS yamama-vai",
                "A onça matou a anta recentemente.",
            ),
            ("eva-n pani kiki-ai", "eva-n pani.ABS kiki-ai", "A mãe está tecendo a rede."),
            (
                "yora-n mansin kini-ai",
                "yora-n mansin.ABS kini-ai",
                "A pessoa está pintando a cuia.",
            ),
        ]

        phrases = []
        for i in range(count):
            target_str, igt, pt = coherent_frames[i % len(coherent_frames)]
            phrases.append(
                {
                    "target": target_str,
                    "igt": igt,
                    "portugues": pt,
                }
            )
        return phrases

    def generate_phrases(self, count: int = 20) -> list[SyntheticPhrase]:
        """Generate, ground, and validate target-language synthetic phrases."""
        results: list[SyntheticPhrase] = []
        raw_items: list[dict[str, Any]] = []

        try:
            messages = self._build_prompt(count=min(count, 10))
            completion = self.provider.complete(messages, temperature=0.3)
            raw_items = self._extract_json(completion)
        except Exception:
            raw_items = []

        # If LLM returned fewer or failed, supplement with deterministic slot-filling
        if len(raw_items) < count:
            deficit = count - len(raw_items)
            raw_items.extend(self._generate_slot_filled_fallback(deficit))

        for item in raw_items[:count]:
            target_text = (
                item.get("target") or item.get("target_phrase") or item.get("sentence") or ""
            )
            igt = item.get("igt") or item.get("glosa") or ""
            portugues = item.get("portugues") or item.get("traducao") or ""

            if not target_text:
                continue

            grounding = self.validator.validate(target_text)
            judgment = self.judge.judge_phrase(
                target_phrase=target_text,
                igt_gloss=igt,
                portuguese_translation=portugues,
                grounding_report=grounding,
            )

            phrase = SyntheticPhrase(
                target_phrase=target_text,
                igt_gloss=igt,
                portuguese_translation=portugues,
                grounding=grounding,
                judgment=judgment,
                provider=self.provider.provider_name,
                model=self.provider.model_name,
                metadata={
                    "language": self.lang_code,
                    "stems_count": len(grounding.identified_stems),
                    "affixes_count": len(grounding.identified_affixes),
                    "invariant_9_compliant": grounding.valid,
                    "quality_status": judgment.status.value,
                    "clef_score": judgment.score,
                },
            )
            results.append(phrase)

        return results
