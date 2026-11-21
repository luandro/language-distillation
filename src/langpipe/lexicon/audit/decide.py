"""Decision table for Lexicon Audit (ADR-0021)."""

from __future__ import annotations

from typing import Any

from langpipe.lexicon.audit.model import (
    AuditFlag,
    AuditSignal,
    EntryAudit,
    LexicalClass,
    ProperNounKind,
    UseScope,
    compute_audit_id,
)


def decide_entry_audit(
    entry: dict[str, Any],
    signals: list[AuditSignal],
    flags: list[AuditFlag],
    clef_res: dict[str, Any],
    lang_code: str = "und",
) -> EntryAudit:
    """Apply the layered decision table to determine LexicalClass and UseScopes.

    Adheres strictly to ADR-0021:
    - Validated entries are never removed by machines (open review task only).
    - Foreign phonotactics + names are segregated to Onomasticon.
    - Cliticized forms become inflected_form.
    - Digits and non-lexical tokens become artifact.
    """
    headword = entry.get("headword", "").strip()
    status = entry.get("status", "supported")
    reasons: list[str] = []

    signal_rules = {s.rule_id: s for s in signals}
    clef_is_name = clef_res.get("is_name", False)

    # Invariant 3 Guard: Validated entries stay lemmas
    if status == "validated":
        use_scopes = [
            UseScope.GROUNDING,
            UseScope.SYNTHESIS_PROMPT,
            UseScope.DICTIONARY_EXPORT,
        ]
        review_req = bool(signals or clef_is_name)
        if review_req:
            reasons.append("Entrada validada possui sinais de alerta que exigem revisão humana.")
        return EntryAudit(
            audit_id=compute_audit_id(headword),
            headword=headword,
            lexical_class=LexicalClass.LEMMA,
            flags=flags,
            use_scopes=use_scopes,
            signals=signals,
            review_required=review_req,
            reasons=reasons,
        )

    # 1. Non-lexical Artifacts & Multiwords
    if "digit_artifact" in signal_rules:
        reasons.append("Contém dígitos ou artefatos numéricos de transcrição.")
        return EntryAudit(
            audit_id=compute_audit_id(headword),
            headword=headword,
            lexical_class=LexicalClass.ARTIFACT,
            flags=flags,
            use_scopes=[],
            signals=signals,
            review_required=False,
            reasons=reasons,
        )

    if "multiword" in signal_rules:
        reasons.append("Expressão composta com múltiplos termos separados por espaço.")
        return EntryAudit(
            audit_id=compute_audit_id(headword),
            headword=headword,
            lexical_class=LexicalClass.MULTIWORD,
            flags=flags,
            use_scopes=[],
            signals=signals,
            review_required=False,
            reasons=reasons,
        )

    # 2. Inflected tokens with clitics (e.g. davipa, jesusvere)
    if "name_plus_clitic" in signal_rules:
        base_name = signal_rules["name_plus_clitic"].detail.get("base_name")
        clitic = signal_rules["name_plus_clitic"].detail.get("clitic")
        reasons.append(f"Forma infletida de nome próprio: '{base_name}' + clítico '-{clitic}'.")
        return EntryAudit(
            audit_id=compute_audit_id(headword),
            headword=headword,
            lexical_class=LexicalClass.INFLECTED_FORM,
            related_entry=base_name,
            flags=flags,
            use_scopes=[],
            signals=signals,
            review_required=False,
            reasons=reasons,
        )

    # 3. Proper Nouns (Names, Toponyms, Ethnic Groups)
    has_name_signal = (
        "conventional_name" in signal_rules or "foreign_letters" in signal_rules or clef_is_name
    )

    if has_name_signal:
        kind_str = clef_res.get("name_kind") or "person"
        try:
            proper_kind = ProperNounKind(kind_str)
        except Exception:
            proper_kind = ProperNounKind.PERSON

        reasons.append(
            f"Nome próprio / onomástico detectado ({proper_kind.value}). "
            f"Isolado do léxico comum para evitar uso como vocabulário sintético geral."
        )

        return EntryAudit(
            audit_id=compute_audit_id(headword),
            headword=headword,
            lexical_class=LexicalClass.PROPER_NOUN,
            proper_noun_kind=proper_kind,
            flags=flags,
            use_scopes=[UseScope.ONOMASTICON],
            signals=signals,
            review_required=False,
            reasons=reasons,
        )

    # 4. Clean Canonical Lemma
    return EntryAudit(
        audit_id=compute_audit_id(headword),
        headword=headword,
        lexical_class=LexicalClass.LEMMA,
        flags=flags,
        use_scopes=[
            UseScope.GROUNDING,
            UseScope.SYNTHESIS_PROMPT,
            UseScope.DICTIONARY_EXPORT,
        ],
        signals=signals,
        review_required=bool(flags),
        reasons=["Lema auditado e elegível para vocabulário e geração."],
    )
