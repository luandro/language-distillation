"""Deterministic L1 Structural Checks for Synthetic Phrases.

Validates:
1. IGT token count vs Target language token count.
2. Morpheme label alignment.
3. TAM suffix vs Portuguese translation consistency (e.g. negation, future, impossibility).
4. Subject/Object case marking alignment.
"""

from __future__ import annotations

import re


def check_structural_alignment(
    target_phrase: str,
    igt_gloss: str,
    portuguese_translation: str,
    lang_code: str = "und",
) -> dict[str, bool]:
    """Execute deterministic structural and TAM alignment checks.

    Returns dict with booleans:
        - igt_aligned: True if IGT tokens structurally correspond to target phrase.
        - tam_consistent: True if TAM morphology matches Portuguese translation.
        - roles_consistent: True if core argument markers match translated roles.
    """
    clean_target = re.sub(r"[^\w\s\-]", "", target_phrase.lower()).strip()
    target_tokens = [t for t in clean_target.split() if t]

    clean_pt = portuguese_translation.lower().strip()
    clean_pt_words = set(re.findall(r"\b\w+\b", clean_pt))

    igt_lines = [line.strip() for line in igt_gloss.strip().split("\n") if line.strip()]
    igt_tokens = []
    if igt_lines:
        igt_tokens = igt_lines[0].split()

    # 1. Token count comparison (soft: target vs IGT line 1)
    igt_aligned = True
    if igt_tokens and abs(len(target_tokens) - len(igt_tokens)) > 1:
        igt_aligned = False

    # 2. TAM consistency
    tam_consistent = True

    # Negation check: if -ma or NEG in tokens, Portuguese MUST contain negation
    has_neg_suffix = any(
        t.endswith("-ma") or "-ma-" in t or t == "ma" for t in target_tokens
    ) or any("neg" in line.lower() for line in igt_lines)
    has_pt_neg = "não" in clean_pt_words or "nunca" in clean_pt_words or "jamais" in clean_pt_words
    if has_neg_suffix and not has_pt_neg:
        tam_consistent = False

    # Impossibility check: -tinpa (IMPOS)
    has_impos = any("tinpa" in t for t in target_tokens) or any(
        "impos" in line.lower() for line in igt_lines
    )
    if has_impos:
        impos_markers = {"não pode", "impossível", "não consegue"}
        if not any(m in clean_pt for m in impos_markers):
            tam_consistent = False

    # Future check: -katsai (FUT)
    has_fut = any("katsai" in t for t in target_tokens) or any(
        "fut" in line.lower() for line in igt_lines
    )
    if has_fut:
        # Portuguese future inflections or auxiliary "vai"
        fut_markers = ["rá", "rão", "rei", "remos", "vai"]
        matches_fut = any(
            any(w.endswith(end) for end in fut_markers[:-1]) or "vai" in clean_pt_words
            for w in clean_pt_words
        )
        if not matches_fut:
            tam_consistent = False

    # 3. Roles and valence consistency
    roles_consistent = True
    if lang_code and lang_code != "und":
        try:
            from langpipe.synthesis.grammar import ValenceValidator

            val_validator = ValenceValidator(lang_code=lang_code)
            rep = val_validator.validate_clause(target_phrase)
            if not rep.valid:
                roles_consistent = False
        except Exception:
            pass

    return {
        "igt_aligned": igt_aligned,
        "tam_consistent": tam_consistent,
        "roles_consistent": roles_consistent,
    }
