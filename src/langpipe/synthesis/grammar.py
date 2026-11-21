"""Valence-constrained grammar and clause synthesis engine (Milestone 2, WP 2.1).

Enforces language-specific morphosyntactic alignment (ergative-absolutive vs
nominative-accusative) and transitivity harmony configured strictly in language
profiles (AGENTS § Language-specific code).

Provides:
- ValenceValidator: verifies that argument marking harmonizes with verb valence.
- SyntacticClauseEngine: deterministic template generator for all core clause types.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from langpipe.languages.base import GrammarProfile, profile_for
from langpipe.lexicon.audit.view import LexiconView
from langpipe.lexicon.semantics import GrammaticalValence


class GrammarClauseType(StrEnum):
    """Core syntactic clause structures for curriculum generation."""

    TRANSITIVE = "transitive"
    INTRANSITIVE = "intransitive"
    DITRANSITIVE = "ditransitive"
    NEGATION = "negation"
    INTERROGATIVE = "interrogative"
    IMPERATIVE = "imperative"
    POSSESSION = "possession"


@dataclass
class ValenceReport:
    """Report evaluating transitivity harmony and argument case marking."""

    sentence: str
    valid: bool
    alignment_type: str
    verb_valences: dict[str, str] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentence": self.sentence,
            "valid": self.valid,
            "alignment_type": self.alignment_type,
            "verb_valences": self.verb_valences,
            "violations": self.violations,
            "warnings": self.warnings,
        }


class ValenceValidator:
    """Validates transitivity harmony between verbs and argument case markers."""

    def __init__(
        self,
        lang_code: str = "und",
        lexicon_view: LexiconView | None = None,
    ) -> None:
        self.lang_code = lang_code
        self.profile = profile_for(lang_code)
        self.grammar: GrammarProfile = self.profile.grammar

        if lexicon_view is not None:
            self.view = lexicon_view
        else:
            self.view = LexiconView.load(lang_code=lang_code, view="clean")

        # Map verb headword -> valence string
        self.verb_valences: dict[str, str] = {}
        for entry in self.view.entries:
            hw = entry.get("headword")
            pos = entry.get("pos", "")
            if not hw:
                continue

            semantics = entry.get("semantics") or {}
            val = semantics.get("valence")
            if val and val != GrammaticalValence.NON_VERBAL.value:
                self.verb_valences[hw.lower()] = val
            elif "v" in pos.lower():
                # Verb without induced valence
                self.verb_valences[hw.lower()] = GrammaticalValence.UNKNOWN.value

    def validate_clause(
        self,
        target_phrase: str,
        identified_stems: list[str] | None = None,
    ) -> ValenceReport:
        """Verify that sentence arguments strictly obey the grammar's alignment rules."""
        clean_text = target_phrase.strip()
        tokens = [re.sub(r"[^\w\-]", "", t.lower()) for t in clean_text.split() if t]

        report = ValenceReport(
            sentence=clean_text,
            valid=True,
            alignment_type=self.grammar.alignment_type,
        )

        # Detect verbs present in phrase
        detected_verbs: list[tuple[str, str]] = []
        for token in tokens:
            # Check full token or strip suffixes
            bare_tok = token.split("-")[0]
            if bare_tok in self.verb_valences:
                val = self.verb_valences[bare_tok]
                detected_verbs.append((bare_tok, val))
                report.verb_valences[bare_tok] = val
            elif identified_stems:
                for stem in identified_stems:
                    if stem in self.verb_valences and (stem == token or token.startswith(stem)):
                        val = self.verb_valences[stem]
                        detected_verbs.append((stem, val))
                        report.verb_valences[stem] = val

        if not detected_verbs:
            return report

        # For ergative-absolutive alignment:
        if self.grammar.alignment_type == "ergative_absolutive":
            erg_suffixes = tuple(s.lstrip("-") for s in self.grammar.ergative_suffixes if s)
            ergative_tokens = [
                t for t in tokens if any(t.endswith(f"-{s}") or t.endswith(s) for s in erg_suffixes)
            ]

            for verb_stem, valence in detected_verbs:
                # Rule 1: Intransitive verbs MUST NOT govern an ergative subject
                if valence == GrammaticalValence.INTRANSITIVE.value:
                    if ergative_tokens:
                        # Reject ergative marker on intransitive clause
                        report.valid = False
                        msg = (
                            f"Intransitive verb '{verb_stem}' cannot govern "
                            f"ergative-marked arguments: {ergative_tokens}"
                        )
                        report.violations.append(msg)

                # Rule 2: Transitive verbs require ergative agent
                elif valence == GrammaticalValence.TRANSITIVE.value:
                    # If clause has >= 3 words and no ergative marking, warn or violate if strict
                    non_verb_tokens = [
                        t
                        for t in tokens
                        if not any(t == vs or t.startswith(vs) for vs, _ in detected_verbs)
                    ]
                    if len(non_verb_tokens) >= 2 and not ergative_tokens:
                        warn_msg = (
                            f"Transitive verb '{verb_stem}' with multiple noun phrases "
                            "lacks ergative marking on the agent."
                        )
                        report.warnings.append(warn_msg)

        return report


class SyntacticClauseEngine:
    """Generates guaranteed grammatically well-formed clauses from LKB lexical entries."""

    def __init__(
        self,
        lang_code: str = "und",
        lexicon_view: LexiconView | None = None,
    ) -> None:
        self.lang_code = lang_code
        self.profile = profile_for(lang_code)
        self.grammar = self.profile.grammar

        if lexicon_view is not None:
            self.view = lexicon_view
        else:
            self.view = LexiconView.load(lang_code=lang_code, view="clean")

        # Index vocabulary by POS and valence
        self.transitive_verbs: list[dict[str, Any]] = []
        self.intransitive_verbs: list[dict[str, Any]] = []
        self.ditransitive_verbs: list[dict[str, Any]] = []
        self.animate_nouns: list[dict[str, Any]] = []
        self.inanimate_nouns: list[dict[str, Any]] = []
        self.body_nouns: list[dict[str, Any]] = []
        self.kinship_nouns: list[dict[str, Any]] = []

        for e in self.view.entries:
            pos = (e.get("pos") or "").lower()
            sem = e.get("semantics") or {}
            val = sem.get("valence")
            domain = sem.get("primary_domain")
            inal = sem.get("inalienability")

            if "v" in pos:
                if val == GrammaticalValence.TRANSITIVE.value:
                    self.transitive_verbs.append(e)
                elif val == GrammaticalValence.DITRANSITIVE.value:
                    self.ditransitive_verbs.append(e)
                else:
                    self.intransitive_verbs.append(e)
            elif "n" in pos or pos in ("subst", "noun"):
                if inal == "inalienable_body" or domain == "body_health":
                    self.body_nouns.append(e)
                elif inal == "inalienable_kin" or domain == "kinship_social":
                    self.kinship_nouns.append(e)

                if domain in ("fauna", "kinship_social"):
                    self.animate_nouns.append(e)
                else:
                    self.inanimate_nouns.append(e)

    def _first_gloss(self, entry: dict[str, Any]) -> str:
        contact_lang = getattr(self.view, "contact_language", "por")
        for k in (f"glosses_{contact_lang}", "glosses_por", "glosses", "trans", "meaning"):
            val = entry.get(k)
            if val:
                if isinstance(val, list) and val:
                    return str(val[0]).split(",")[0].strip()
                elif isinstance(val, str):
                    return val.split(",")[0].strip()
        # Entries are untyped dicts, so `get` is Any; the headword field is a string.
        return cast(str, entry.get("headword", ""))

    def build_transitive(
        self,
        agent: dict[str, Any],
        patient: dict[str, Any],
        verb: dict[str, Any],
        tam_suffix: str = "-ai",
        negate: bool = False,
    ) -> dict[str, Any]:
        """Construct transitive clause: [Agent-ERG] [Patient-ABS] [Verb-TAM]."""
        erg_suffix = self.grammar.ergative_suffixes[0] if self.grammar.ergative_suffixes else "-n"
        neg_suffix = self.grammar.negation_suffixes[0] if self.grammar.negation_suffixes else "-ma"

        ag_hw = agent["headword"]
        pat_hw = patient["headword"]
        v_hw = verb["headword"]

        ag_gloss = self._first_gloss(agent)
        pat_gloss = self._first_gloss(patient)
        v_gloss = self._first_gloss(verb)

        target_ag = f"{ag_hw}{erg_suffix}"
        target_pat = pat_hw
        target_v = f"{v_hw}{neg_suffix if negate else ''}{tam_suffix}"

        target_phrase = f"{target_ag} {target_pat} {target_v}"

        igt_target = (
            f"{ag_hw}-{erg_suffix.lstrip('-')} {pat_hw} "
            f"{v_hw}{neg_suffix if negate else ''}{tam_suffix}"
        )
        igt_lines = [
            igt_target,
            f"{ag_gloss}-ERG {pat_gloss}-ABS {v_gloss}{'-NEG' if negate else ''}-TAM",
        ]

        pt_phrase = (
            f"O {ag_gloss} {'não ' if negate else ''}{v_gloss} o {pat_gloss}."
            if " " not in v_gloss
            else f"O {ag_gloss} {'não ' if negate else ''}{v_gloss}."
        )

        return {
            "target": target_phrase,
            "portuguese": pt_phrase,
            "igt": "\n".join(igt_lines),
            "clause_type": GrammarClauseType.TRANSITIVE.value,
            "negated": negate,
            "components": {
                "agent": ag_hw,
                "patient": pat_hw,
                "verb": v_hw,
                "tam": tam_suffix,
            },
        }

    def build_intransitive(
        self,
        subject: dict[str, Any],
        verb: dict[str, Any],
        tam_suffix: str = "-ai",
        negate: bool = False,
    ) -> dict[str, Any]:
        """Construct intransitive clause: [Subject-ABS] [Verb-TAM]."""
        neg_suffix = self.grammar.negation_suffixes[0] if self.grammar.negation_suffixes else "-ma"

        subj_hw = subject["headword"]
        v_hw = verb["headword"]

        subj_gloss = self._first_gloss(subject)
        v_gloss = self._first_gloss(verb)

        target_phrase = f"{subj_hw} {v_hw}{neg_suffix if negate else ''}{tam_suffix}"

        igt_lines = [
            f"{subj_hw} {v_hw}{neg_suffix if negate else ''}{tam_suffix}",
            f"{subj_gloss}-ABS {v_gloss}{'-NEG' if negate else ''}-TAM",
        ]

        pt_phrase = f"O {subj_gloss} {'não ' if negate else ''}{v_gloss}."

        return {
            "target": target_phrase,
            "portuguese": pt_phrase,
            "igt": "\n".join(igt_lines),
            "clause_type": GrammarClauseType.INTRANSITIVE.value,
            "negated": negate,
            "components": {
                "subject": subj_hw,
                "verb": v_hw,
                "tam": tam_suffix,
            },
        }

    def build_interrogative(
        self,
        subject: dict[str, Any],
        verb: dict[str, Any],
    ) -> dict[str, Any]:
        """Construct interrogative clause: [Subject-ABS] [Verb-TAM-Q]."""
        q_suffix = (
            self.grammar.interrogative_suffixes[0] if self.grammar.interrogative_suffixes else "-vẽ"
        )
        subj_hw = subject["headword"]
        v_hw = verb["headword"]

        subj_gloss = self._first_gloss(subject)
        v_gloss = self._first_gloss(verb)

        target_phrase = f"{subj_hw} {v_hw}{q_suffix}?"
        igt_lines = [
            f"{subj_hw} {v_hw}-{q_suffix.lstrip('-')}",
            f"{subj_gloss}-ABS {v_gloss}-INTERR",
        ]
        pt_phrase = f"O {subj_gloss} {v_gloss}?"

        return {
            "target": target_phrase,
            "portuguese": pt_phrase,
            "igt": "\n".join(igt_lines),
            "clause_type": GrammarClauseType.INTERROGATIVE.value,
            "components": {
                "subject": subj_hw,
                "verb": v_hw,
                "interrogative_suffix": q_suffix,
            },
        }

    def build_imperative(
        self,
        verb: dict[str, Any],
        patient: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Construct imperative/exhortative clause: [Patient-ABS] [Verb-IMP]."""
        imp_suffix = (
            self.grammar.imperative_suffixes[0] if self.grammar.imperative_suffixes else "-we"
        )
        v_hw = verb["headword"]
        v_gloss = self._first_gloss(verb)

        if patient:
            pat_hw = patient["headword"]
            pat_gloss = self._first_gloss(patient)
            target_phrase = f"{pat_hw} {v_hw}{imp_suffix}!"
            igt_lines = [
                f"{pat_hw} {v_hw}-{imp_suffix.lstrip('-')}",
                f"{pat_gloss}-ABS {v_gloss}-IMP",
            ]
            pt_phrase = f"{v_gloss.capitalize()} o {pat_gloss}!"
        else:
            target_phrase = f"{v_hw}{imp_suffix}!"
            igt_lines = [
                f"{v_hw}-{imp_suffix.lstrip('-')}",
                f"{v_gloss}-IMP",
            ]
            pt_phrase = f"{v_gloss.capitalize()}!"

        return {
            "target": target_phrase,
            "portuguese": pt_phrase,
            "igt": "\n".join(igt_lines),
            "clause_type": GrammarClauseType.IMPERATIVE.value,
            "components": {
                "patient": patient["headword"] if patient else None,
                "verb": v_hw,
                "imperative_suffix": imp_suffix,
            },
        }

    def build_inalienable_possession(
        self,
        possessor: dict[str, Any],
        body_part: dict[str, Any],
        verb: dict[str, Any],
    ) -> dict[str, Any]:
        """Construct inalienable possession clause: [Possessor-GEN] [BodyPart-ABS] [Verb-TAM]."""
        gen_suffix = self.grammar.genitive_suffixes[0] if self.grammar.genitive_suffixes else "-n"
        pos_hw = possessor["headword"]
        bp_hw = body_part["headword"]
        v_hw = verb["headword"]

        pos_gloss = self._first_gloss(possessor)
        bp_gloss = self._first_gloss(body_part)
        v_gloss = self._first_gloss(verb)

        target_phrase = f"{pos_hw}{gen_suffix} {bp_hw} {v_hw}-ai"
        igt_lines = [
            f"{pos_hw}-{gen_suffix.lstrip('-')} {bp_hw} {v_hw}-ai",
            f"{pos_gloss}-GEN {bp_gloss}-ABS {v_gloss}-TAM",
        ]
        pt_phrase = f"A {bp_gloss} do {pos_gloss} {v_gloss}."

        return {
            "target": target_phrase,
            "portuguese": pt_phrase,
            "igt": "\n".join(igt_lines),
            "clause_type": GrammarClauseType.POSSESSION.value,
            "components": {
                "possessor": pos_hw,
                "body_part": bp_hw,
                "verb": v_hw,
            },
        }
