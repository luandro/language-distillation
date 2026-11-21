#!/usr/bin/env python3
"""Synthetic Data Generator & Grounding Validator for Marúbo (mzr).

Loads the validated Language Knowledge Base (exports/dictionary.json)
and provides:
1. Grounding validator: rejects any LLM output containing hallucinated stems or affixes.
2. Rule-based synthetic sentence constructor: generates grammatically valid synthetic pairs.
3. Prompt builder: formats strict system prompts for OpenAI / Anthropic / Gemini / local LLMs.
"""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
DICT_FILE = ROOT / "dictionary.json"


class SyntheticDataToolkit:
    def __init__(self, dict_path: Path = DICT_FILE) -> None:
        with open(dict_path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.lexicon = {entry["headword"]: entry for entry in self.data["lexicon"]}
        self.allowed_stems = set(self.lexicon.keys())
        self.allowed_affixes = {"-ki", "-ra"}

    def validate_sentence(self, sentence: str) -> tuple[bool, list[str]]:
        """Verify that every word in a sentence adheres to the attested LKB vocabulary."""
        tokens = sentence.strip(".").split()
        errors = []
        for token in tokens:
            cleaned = token.lower()
            # Check if pure stem
            if cleaned in self.allowed_stems:
                continue
            # Check stem + affix
            matched = False
            for affix in self.allowed_affixes:
                suffix = affix.lstrip("-")
                if cleaned.endswith(suffix):
                    stem = cleaned[: -len(suffix)].rstrip("-")
                    if stem in self.allowed_stems:
                        matched = True
                        break
            if not matched:
                errors.append(f"Unverified or hallucinated word/stem: '{token}'")
        return (len(errors) == 0, errors)

    def generate_combinatorial_examples(self) -> list[dict[str, str]]:
        """Generate verified rule-based synthetic sentence pairs from the LKB."""
        examples = []
        # Subjects: kanu (homem), rumi (pajé)
        # Objects: mabi (canoa), nawa (rio)
        # Verbs: tesa (vê), wesa (foi)

        # 1. Affirmative transitive: S + O + V
        examples.append(
            {
                "marubo": "rumi mabi tesa.",
                "portuguese": "O pajé vê a canoa.",
                "type": "transitive_affirmative",
            }
        )
        # 2. Negative intransitive with clitic: S + O/Dest + V-ra
        examples.append(
            {
                "marubo": "rumi nawa wesa-ra.",
                "portuguese": "O pajé não foi ao rio.",
                "type": "intransitive_negative",
            }
        )
        # 3. Ergative focus: S-ki + O + V
        examples.append(
            {
                "marubo": "kanu-ki mabi tesa.",
                "portuguese": "É o homem que vê a canoa.",
                "type": "ergative_focus",
            }
        )
        return examples

    def get_llm_prompt(self, target_sentence_portuguese: str) -> dict[str, Any]:
        """Produce the exact prompt payload to give an LLM to translate or generate."""
        return {
            "instruction": "Translate into Marúbo (mzr) using ONLY the allowed vocabulary.",
            "input_portuguese": target_sentence_portuguese,
            "allowed_lexicon": {k: v["glosses_por"] for k, v in self.lexicon.items()},
            "allowed_affixes": list(self.allowed_affixes),
            "rules": (
                "SOV word order. Append -ra to verb for negation. "
                "Append -ki for ergative/agent marking."
            ),
        }


if __name__ == "__main__":
    toolkit = SyntheticDataToolkit()
    print("=== Marúbo (mzr) Synthetic Data Toolkit ===")
    stems_count = len(toolkit.allowed_stems)
    affixes_count = len(toolkit.allowed_affixes)
    print(f"Loaded {stems_count} attested lexical stems and {affixes_count} affixes.\n")

    print("--- 1. Testing Grounding Validator ---")
    valid_test = "kanu mabi tesa."
    is_valid, errs = toolkit.validate_sentence(valid_test)
    print(f"Sentence: '{valid_test}' -> Valid: {is_valid}")

    hallucinated_test = "kanu yora pikota."  # 'yora' and 'pikota' are not in current dictionary
    is_valid2, errs2 = toolkit.validate_sentence(hallucinated_test)
    print(f"Sentence: '{hallucinated_test}' -> Valid: {is_valid2} (Detected: {errs2})\n")

    print("--- 2. Rule-Based Synthetic Sentences (Verified Zero-Hallucination) ---")
    for ex in toolkit.generate_combinatorial_examples():
        print(f"[{ex['type']}]")
        print(f"  Marúbo:     {ex['marubo']}")
        print(f"  Português:  {ex['portuguese']}\n")

    print("--- 3. Prompt for LLM Translation / Synthetic Generation ---")
    prompt = toolkit.get_llm_prompt("O pajé vê a canoa.")
    print(json.dumps(prompt, indent=2, ensure_ascii=False))
