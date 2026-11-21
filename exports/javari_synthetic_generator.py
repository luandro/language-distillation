#!/usr/bin/env python3
"""Unified Synthetic Data Generator & Anti-Hallucination Grounding Validator
for all Indigenous Languages of the Vale do Javari (Amazonas, Brazil).

Supported languages:
- mzr (Marúbo)
- mcf (Matsés)
- mpu (Matis)
- xor (Korubo)
- knm (Kanamari)
- cul (Kulina)
"""

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent


class JavariLanguageToolkit:
    def __init__(self, lang_code: str = "mzr") -> None:
        self.lang_code = lang_code
        dict_path = ROOT / lang_code / "dictionary.json"
        if not dict_path.exists():
            # Fallback to root dictionary if mzr
            if lang_code == "mzr" and (ROOT / "dictionary.json").exists():
                dict_path = ROOT / "dictionary.json"
            else:
                raise FileNotFoundError(f"Dictionary for {lang_code} not found at {dict_path}")

        with open(dict_path, encoding="utf-8") as f:
            self.data = json.load(f)

        self.name = self.data.get("language_name", lang_code)
        self.family = self.data.get("language_family", "Indigenous")
        self.lexicon = {entry["headword"]: entry for entry in self.data["lexicon"]}
        self.allowed_stems = set(self.lexicon.keys())
        self.allowed_affixes = {a["morpheme"] for a in self.data.get("morphology", [])} or {
            a["form"] for a in self.data.get("grammar", {}).get("affixes", [])
        }
        if not self.allowed_affixes:
            self.allowed_affixes = {"-ki", "-ra", "-n", "-ma"}

    def validate_sentence(self, sentence: str) -> tuple[bool, list[str]]:
        """Verify that every word in a sentence adheres to the attested vocabulary."""
        tokens = sentence.strip(".").split()
        errors = []
        for token in tokens:
            cleaned = token.lower()
            if cleaned in self.allowed_stems:
                continue
            matched = False
            for affix in self.allowed_affixes:
                suffix = affix.lstrip("-")
                if cleaned.endswith(suffix):
                    stem = cleaned[: -len(suffix)].rstrip("-")
                    if stem in self.allowed_stems:
                        matched = True
                        break
            if not matched:
                errors.append(f"Unverified word/stem in {self.name}: '{token}'")
        return (len(errors) == 0, errors)

    def print_summary(self) -> None:
        print(f"=== {self.name} ({self.lang_code}) — {self.family} Family ===")
        print("Territory: Vale do Javari (Amazonas, Brazil)")
        print(f"Attested Stems: {len(self.allowed_stems)} | Affixes: {len(self.allowed_affixes)}")
        print(f"Vocab Sample: {', '.join(sorted(list(self.allowed_stems))[:5])}...")
        print()

    def get_llm_prompt(self, target_portuguese: str) -> dict[str, Any]:
        return {
            "target_language": f"{self.name} ({self.lang_code})",
            "instruction": (
                f"Translate into {self.name} using ONLY allowed vocabulary. Zero hallucination."
            ),
            "input_portuguese": target_portuguese,
            "allowed_lexicon": {k: v.get("glosses_por", []) for k, v in self.lexicon.items()},
            "allowed_affixes": list(self.allowed_affixes),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Javari Valley Synthetic Data Toolkit")
    parser.add_argument(
        "--lang",
        default="all",
        choices=["all", "mzr", "mcf", "mpu", "xor", "knm", "cul"],
        help="Language to run (default: all)",
    )
    parser.add_argument(
        "--validate",
        type=str,
        default=None,
        help="Validate a candidate target language sentence against attested stems and morphology",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Generate a zero-hallucination few-shot prompt for translating Portuguese text",
    )
    args = parser.parse_args()

    if args.validate:
        target_lang = "mzr" if args.lang == "all" else args.lang
        toolkit = JavariLanguageToolkit(target_lang)
        valid, errors = toolkit.validate_sentence(args.validate)
        print(f"Grounding Validation for {toolkit.name} ('{args.validate}'):")
        if valid:
            print("  [SUCCESS] All stems and affixes are strictly verified against the LKB!")
        else:
            print("  [REJECTED - Invariant 9 Violation]:")
            for err in errors:
                print(f"   ! {err}")
        return

    if args.prompt:
        target_lang = "mzr" if args.lang == "all" else args.lang
        toolkit = JavariLanguageToolkit(target_lang)
        prompt_data = toolkit.get_llm_prompt(args.prompt)
        print(json.dumps(prompt_data, indent=2, ensure_ascii=False))
        return

    languages = ["mzr", "mcf", "mpu", "xor", "knm", "cul"] if args.lang == "all" else [args.lang]

    for lang in languages:
        toolkit = JavariLanguageToolkit(lang)
        toolkit.print_summary()
        examples = toolkit.data.get("attested_examples", []) or toolkit.data.get(
            "parallel_sentences", []
        )
        if examples:
            print("  [Attested Training Exemplars]:")
            for ex in examples[:2]:
                src = ex.get("marubo") or ex.get("source")
                tgt = ex.get("portugues") or ex.get("target")
                print(f"   * {src} <--> {tgt}")
        print("-" * 50)


if __name__ == "__main__":
    main()
