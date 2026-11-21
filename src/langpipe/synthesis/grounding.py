"""Grounding & Morphological Validator for Synthetic Phrases.

Implements Invariant 9: No unverified or hallucinated target-language stems
or illegal morphological combinations may enter the synthetic training set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langpipe.languages.base import profile_for
from langpipe.lexicon.audit.view import LexiconView


@dataclass
class GroundingReport:
    """Detailed grounding report for a synthetic phrase."""

    sentence: str
    target_language: str
    valid: bool
    identified_stems: list[str] = field(default_factory=list)
    identified_affixes: list[str] = field(default_factory=list)
    verified_tokens: list[dict[str, Any]] = field(default_factory=list)
    unverified_tokens: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentence": self.sentence,
            "target_language": self.target_language,
            "valid": self.valid,
            "identified_stems": self.identified_stems,
            "identified_affixes": self.identified_affixes,
            "verified_tokens": self.verified_tokens,
            "unverified_tokens": self.unverified_tokens,
            "errors": self.errors,
        }


class GroundingValidator:
    """Validates candidate target-language phrases strictly against LKB."""

    def __init__(
        self,
        lang_code: str = "und",
        dictionary_path: str | Path | None = None,
        lexicon_view: LexiconView | None = None,
    ) -> None:
        self.lang_code = lang_code

        if lexicon_view is not None:
            self.view = lexicon_view
        else:
            dict_p = Path(dictionary_path) if dictionary_path else None
            self.view = LexiconView.load(lang_code=lang_code, view="clean", dict_path=dict_p)

        self.language_name = self.view.language_name
        self.stems = self.view.stems

        # Load allowed morphology
        raw_morph = self.view.raw_data.get("morphology", []) or self.view.raw_data.get(
            "grammar", {}
        ).get("affixes", [])
        self.affixes: set[str] = set()
        for m in raw_morph:
            form = m.get("morpheme") or m.get("form") or ""
            if form:
                self.affixes.add(form.strip().lower().lstrip("-"))

        # Supplement affixes from language profile
        profile = profile_for(lang_code)
        if profile.lexicon.affix_inventory and len(self.affixes) < 5:
            self.affixes.update(profile.lexicon.affix_inventory)

    def validate(self, sentence: str) -> GroundingReport:
        """Evaluate a sentence against attested stems and morphological affixes."""
        clean_text = sentence.strip()
        # Tokenize by whitespace, stripping punctuation
        raw_tokens = clean_text.split()
        report = GroundingReport(
            sentence=clean_text,
            target_language=self.lang_code,
            valid=True,
        )

        for raw_tok in raw_tokens:
            cleaned = re.sub(r"[^\w\-\']", "", raw_tok.lower())
            if not cleaned:
                continue

            # 1. Exact match with an attested stem
            if cleaned in self.stems:
                entry = self.stems[cleaned]
                report.identified_stems.append(cleaned)
                report.verified_tokens.append(
                    {
                        "raw": raw_tok,
                        "stem": cleaned,
                        "affixes": [],
                        "glosses": entry.get("glosses_por", []),
                        "status": entry.get("status", "supported"),
                    }
                )
                continue

            # 2. Match with hyphens (e.g. vaki-n or yamama-katsai)
            if "-" in cleaned:
                parts = cleaned.split("-")
                stem_candidate = parts[0]
                affix_candidates = parts[1:]
                if stem_candidate in self.stems and all(
                    a in self.affixes for a in affix_candidates
                ):
                    entry = self.stems[stem_candidate]
                    report.identified_stems.append(stem_candidate)
                    report.identified_affixes.extend(affix_candidates)
                    report.verified_tokens.append(
                        {
                            "raw": raw_tok,
                            "stem": stem_candidate,
                            "affixes": affix_candidates,
                            "glosses": entry.get("glosses_por", []),
                            "status": entry.get("status", "supported"),
                        }
                    )
                    continue

            # 3. Suffix peeling for unhyphenated inflections
            peeled = False
            for affix in sorted(self.affixes, key=len, reverse=True):
                if cleaned.endswith(affix) and len(cleaned) > len(affix):
                    candidate_stem = cleaned[: -len(affix)].rstrip("-")
                    if candidate_stem in self.stems:
                        entry = self.stems[candidate_stem]
                        report.identified_stems.append(candidate_stem)
                        report.identified_affixes.append(affix)
                        report.verified_tokens.append(
                            {
                                "raw": raw_tok,
                                "stem": candidate_stem,
                                "affixes": [affix],
                                "glosses": entry.get("glosses_por", []),
                                "status": entry.get("status", "supported"),
                            }
                        )
                        peeled = True
                        break

            if not peeled:
                report.valid = False
                report.unverified_tokens.append(raw_tok)
                report.errors.append(
                    f"Invariant 9 Violation: Token '{raw_tok}' does not decompose "
                    f"into any attested {self.language_name} stem + documented affix in LKB."
                )

        return report
