"""Deterministic rule-based signals for Lexicon Audit (ADR-0021)."""

from __future__ import annotations

import re
from typing import Any

from langpipe.languages.base import profile_for
from langpipe.lexicon.audit.model import AuditFlag, AuditSignal


def audit_entry_rules(
    entry: dict[str, Any], lang_code: str = "und"
) -> tuple[list[AuditSignal], list[AuditFlag]]:
    """Evaluate deterministic rules on a dictionary entry.

    Returns:
        tuple of (signals, flags)
    """
    signals: list[AuditSignal] = []
    flags: list[AuditFlag] = []

    profile = profile_for(lang_code)
    lex = profile.lexicon
    conventional_names = lex.conventional_names
    foreign_letters = lex.foreign_letters
    clitic_endings = lex.clitic_endings

    headword = entry.get("headword", "").strip().lower()
    clean_hw = re.sub(r"[^\w\s\-]", "", headword)
    glosses = [g.strip().lower() for g in entry.get("glosses_por", [])]

    # 1. Non-lexical & Formatting Artifacts
    if any(char.isdigit() for char in headword):
        signals.append(
            AuditSignal(
                rule_id="digit_artifact",
                source="rule",
                value="artifact",
                detail={"char": [c for c in headword if c.isdigit()]},
            )
        )

    if " " in headword or "\t" in headword:
        signals.append(
            AuditSignal(
                rule_id="multiword",
                source="rule",
                value="multiword",
                detail={"tokens": headword.split()},
            )
        )

    # 2. Known Conventional Names (Direct Match)
    if headword in conventional_names or clean_hw in conventional_names:
        signals.append(
            AuditSignal(
                rule_id="conventional_name",
                source="rule",
                value="proper_noun",
                detail={"name": headword},
            )
        )

    # 3. Foreign Letters Check (Safe letters: f, g, j, l, q, z, d, b, solitary c)
    foreign_chars = set()
    for i, char in enumerate(headword):
        if char in foreign_letters:
            foreign_chars.add(char)
        elif char == "c":
            # In native orthography, 'c' is only valid as part of 'ch'
            next_char = headword[i + 1] if i + 1 < len(headword) else ""
            if next_char != "h":
                foreign_chars.add("c")

    if foreign_chars:
        signals.append(
            AuditSignal(
                rule_id="foreign_letters",
                source="rule",
                value="foreign_phonotactics",
                detail={"foreign_chars": sorted(foreign_chars)},
            )
        )

    # 4. Name + Clitic Ending (e.g. davipa = davi + pa, jesusvere = jesus + vere)
    if headword not in conventional_names and clean_hw not in conventional_names:
        for ending in clitic_endings:
            if headword.endswith(ending) and len(headword) > len(ending) + 2:
                base = headword[: -len(ending)].rstrip("-")
                # Only fires if remainder is a known name or has foreign characters
                base_has_foreign = any(c in foreign_letters for c in base)
                if base in conventional_names or base_has_foreign:
                    signals.append(
                        AuditSignal(
                            rule_id="name_plus_clitic",
                            source="rule",
                            value="inflected_form",
                            detail={"base_name": base, "clitic": ending},
                        )
                    )
                    break

    # 5. Gloss contains name check
    for g in glosses:
        g_clean = re.sub(r"[^\w\s]", "", g).strip()
        if g_clean in conventional_names:
            flags.append(AuditFlag.GLOSS_IS_NAME)
            signals.append(
                AuditSignal(
                    rule_id="gloss_is_name",
                    source="rule",
                    value="gloss_name",
                    detail={"gloss": g},
                )
            )

    return signals, flags
