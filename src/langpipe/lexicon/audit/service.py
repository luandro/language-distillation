"""Service coordinating the Lexicon Audit pipeline (ADR-0021)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from langpipe.lexicon.audit.clef_gloss import get_gloss_classifier
from langpipe.lexicon.audit.decide import decide_entry_audit
from langpipe.lexicon.audit.model import LexicalClass, UseScope
from langpipe.lexicon.audit.rules import audit_entry_rules

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


def audit_lexicon_dict(
    raw_dict_data: dict[str, Any],
    lang_code: str = "und",
    ruleset_version: str = "1.0.0",
) -> dict[str, Any]:
    """Execute complete lexicon audit on a dictionary data structure.

    Returns new dictionary with 'audit' blocks attached to every entry and summary metrics.
    """
    classifier = get_gloss_classifier()
    lexicon_items = raw_dict_data.get("lexicon", [])

    clean_count = 0
    proper_nouns_count = 0
    inflected_count = 0
    artifacts_count = 0

    audited_entries: list[dict[str, Any]] = []

    for entry in lexicon_items:
        entry_copy = dict(entry)
        signals, flags = audit_entry_rules(entry_copy, lang_code=lang_code)
        clef_res = classifier.classify_gloss(entry_copy.get("glosses_por", []))
        audit = decide_entry_audit(entry_copy, signals, flags, clef_res, lang_code=lang_code)

        entry_copy["audit"] = audit.to_dict()
        audited_entries.append(entry_copy)

        # Count metrics
        if UseScope.GROUNDING.value in audit.use_scopes:
            clean_count += 1
        elif audit.lexical_class == LexicalClass.PROPER_NOUN:
            proper_nouns_count += 1
        elif audit.lexical_class == LexicalClass.INFLECTED_FORM:
            inflected_count += 1
        elif audit.lexical_class == LexicalClass.ARTIFACT:
            artifacts_count += 1

    result = dict(raw_dict_data)
    result["lexicon"] = audited_entries
    result["audit_summary"] = {
        "ruleset_version": ruleset_version,
        "total_entries": len(audited_entries),
        "clean_lemmas_count": clean_count,
        "proper_nouns_count": proper_nouns_count,
        "inflected_count": inflected_count,
        "artifacts_count": artifacts_count,
    }
    return result


def audit_and_save_dictionary(lang_code: str) -> dict[str, Any]:
    """Audit the canonical dictionary on disk and emit scoped files."""
    dict_file = ROOT / "exports" / lang_code / "dictionary.json"
    if not dict_file.exists():
        raise FileNotFoundError(f"Dictionary file not found at {dict_file}")

    with open(dict_file, encoding="utf-8") as f:
        data = json.load(f)

    audited = audit_lexicon_dict(data, lang_code=lang_code)

    # 1. Update canonical dictionary with audit blocks
    with open(dict_file, "w", encoding="utf-8") as f:
        json.dump(audited, f, indent=2, ensure_ascii=False)

    # 2. Emit clean dictionary (only grounding eligible lemmas)
    clean_entries = [
        e
        for e in audited["lexicon"]
        if UseScope.GROUNDING.value in e.get("audit", {}).get("use_scopes", [])
    ]
    clean_data = dict(audited)
    clean_data["total_entries"] = len(clean_entries)
    clean_data["lexicon"] = clean_entries
    with open(ROOT / "exports" / lang_code / "dictionary.clean.json", "w", encoding="utf-8") as f:
        json.dump(clean_data, f, indent=2, ensure_ascii=False)

    # 3. Emit names / onomasticon
    names_entries = [
        e
        for e in audited["lexicon"]
        if e.get("audit", {}).get("lexical_class") == LexicalClass.PROPER_NOUN.value
    ]
    names_data = dict(audited)
    names_data["total_entries"] = len(names_entries)
    names_data["lexicon"] = names_entries
    with open(ROOT / "exports" / lang_code / "dictionary.names.json", "w", encoding="utf-8") as f:
        json.dump(names_data, f, indent=2, ensure_ascii=False)

    # 4. Emit quarantine (excluded from grounding)
    quarantine_entries = [
        e
        for e in audited["lexicon"]
        if UseScope.GROUNDING.value not in e.get("audit", {}).get("use_scopes", [])
    ]
    quar_data = dict(audited)
    quar_data["total_entries"] = len(quarantine_entries)
    quar_data["lexicon"] = quarantine_entries
    with open(
        ROOT / "exports" / lang_code / "dictionary.quarantine.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(quar_data, f, indent=2, ensure_ascii=False)

    # `audit_lexicon_dict` returns an untyped JSON-shaped dict; `audit_summary` is the
    # summary block it always writes.
    return cast(dict[str, Any], audited["audit_summary"])
