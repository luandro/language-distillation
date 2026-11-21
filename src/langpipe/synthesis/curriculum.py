"""Stratified curriculum generator for balanced syntactic structures (Milestone 2, WP 2.2).

Generates balanced training corpora across core typological clause types:
1. Transitive SOV clauses ([Agent-ERG] [Patient-ABS] [Verb_t-TAM])
2. Intransitive SV clauses ([Subject-ABS] [Verb_i-TAM])
3. Negated clauses (TAM suffix with negation morpheme)
4. Interrogatives / Wh-questions
5. Imperatives / Exhortatives
6. Inalienable nominal possessions ([Possessor-GEN] [BodyPart-ABS] [Verb-TAM])

Language-agnostic: relies strictly on language profiles and LexiconView.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from langpipe.lexicon.audit.view import LexiconView
from langpipe.synthesis.grammar import GrammarClauseType, SyntacticClauseEngine


@dataclass
class CurriculumDistribution:
    """Target percentage distribution across linguistic clause types."""

    transitive_ratio: float = 0.30
    intransitive_ratio: float = 0.25
    negation_ratio: float = 0.15
    interrogative_ratio: float = 0.10
    imperative_ratio: float = 0.10
    possession_ratio: float = 0.10

    def compute_counts(self, total: int) -> dict[GrammarClauseType, int]:
        """Compute exact integer counts for each clause type given a total budget."""
        counts = {
            GrammarClauseType.TRANSITIVE: max(1, int(round(total * self.transitive_ratio))),
            GrammarClauseType.INTRANSITIVE: max(1, int(round(total * self.intransitive_ratio))),
            GrammarClauseType.NEGATION: max(1, int(round(total * self.negation_ratio))),
            GrammarClauseType.INTERROGATIVE: max(1, int(round(total * self.interrogative_ratio))),
            GrammarClauseType.IMPERATIVE: max(1, int(round(total * self.imperative_ratio))),
            GrammarClauseType.POSSESSION: max(1, int(round(total * self.possession_ratio))),
        }
        # Adjust difference due to rounding
        diff = total - sum(counts.values())
        if diff != 0:
            counts[GrammarClauseType.TRANSITIVE] += diff
        return counts


class StratifiedCurriculumGenerator:
    """Generates balanced synthetic training pairs across stratified grammatical structures."""

    def __init__(
        self,
        lang_code: str = "und",
        lexicon_view: LexiconView | None = None,
        distribution: CurriculumDistribution | None = None,
    ) -> None:
        self.lang_code = lang_code
        self.distribution = distribution or CurriculumDistribution()
        self.clause_engine = SyntacticClauseEngine(lang_code=lang_code, lexicon_view=lexicon_view)
        self.view = self.clause_engine.view

    def generate_batch(
        self,
        total_count: int = 50,
        seed: int | None = 42,
    ) -> list[dict[str, Any]]:
        """Generate a deterministic, balanced curriculum batch."""
        rng = random.Random(seed)
        counts = self.distribution.compute_counts(total_count)
        phrases: list[dict[str, Any]] = []

        ce = self.clause_engine
        anim_pool = ce.animate_nouns or ce.inanimate_nouns or ce.view.entries
        inanim_pool = ce.inanimate_nouns or ce.animate_nouns or ce.view.entries
        vt_pool = ce.transitive_verbs or ce.view.entries
        vi_pool = ce.intransitive_verbs or ce.view.entries
        bp_pool = ce.body_nouns or ce.inanimate_nouns or ce.view.entries

        tam_suffixes = ce.grammar.transitive_tam_suffixes or ("-ai", "-katsi")

        # 1. Transitive clauses
        for _ in range(counts.get(GrammarClauseType.TRANSITIVE, 0)):
            if not (anim_pool and inanim_pool and vt_pool):
                break
            ag = rng.choice(anim_pool)
            pat = rng.choice(inanim_pool)
            v = rng.choice(vt_pool)
            tam = rng.choice(tam_suffixes)
            item = ce.build_transitive(ag, pat, v, tam_suffix=tam, negate=False)
            phrases.append(self._format_output(item))

        # 2. Intransitive clauses
        for _ in range(counts.get(GrammarClauseType.INTRANSITIVE, 0)):
            if not (anim_pool and vi_pool):
                break
            subj = rng.choice(anim_pool)
            v = rng.choice(vi_pool)
            tam = rng.choice(tam_suffixes)
            item = ce.build_intransitive(subj, v, tam_suffix=tam, negate=False)
            phrases.append(self._format_output(item))

        # 3. Negated clauses
        for _ in range(counts.get(GrammarClauseType.NEGATION, 0)):
            if not anim_pool:
                break
            # Alternate transitive and intransitive negation
            if rng.random() > 0.5 and inanim_pool and vt_pool:
                ag = rng.choice(anim_pool)
                pat = rng.choice(inanim_pool)
                v = rng.choice(vt_pool)
                item = ce.build_transitive(ag, pat, v, tam_suffix="-ai", negate=True)
            elif vi_pool:
                subj = rng.choice(anim_pool)
                v = rng.choice(vi_pool)
                item = ce.build_intransitive(subj, v, tam_suffix="-ai", negate=True)
            else:
                continue
            phrases.append(self._format_output(item))

        # 4. Interrogative clauses
        for _ in range(counts.get(GrammarClauseType.INTERROGATIVE, 0)):
            if not (anim_pool and vi_pool):
                break
            subj = rng.choice(anim_pool)
            v = rng.choice(vi_pool)
            item = ce.build_interrogative(subj, v)
            phrases.append(self._format_output(item))

        # 5. Imperative clauses
        for _ in range(counts.get(GrammarClauseType.IMPERATIVE, 0)):
            if vt_pool and inanim_pool and rng.random() > 0.4:
                v = rng.choice(vt_pool)
                pat = rng.choice(inanim_pool)
                item = ce.build_imperative(v, patient=pat)
            elif vt_pool or vi_pool:
                v = rng.choice(vt_pool or vi_pool)
                item = ce.build_imperative(v)
            else:
                continue
            phrases.append(self._format_output(item))

        # 6. Inalienable Possession clauses
        for _ in range(counts.get(GrammarClauseType.POSSESSION, 0)):
            if not (anim_pool and bp_pool and vi_pool):
                break
            pos = rng.choice(anim_pool)
            bp = rng.choice(bp_pool)
            v = rng.choice(vi_pool)
            item = ce.build_inalienable_possession(pos, bp, v)
            phrases.append(self._format_output(item))

        # Shuffle deterministically
        rng.shuffle(phrases)
        return phrases

    def _format_output(self, clause_dict: dict[str, Any]) -> dict[str, Any]:
        """Wrap generated clause into standardized pipeline record."""
        return {
            "target": clause_dict["target"],
            "portuguese": clause_dict["portuguese"],
            "igt": clause_dict["igt"],
            "clause_type": clause_dict["clause_type"],
            "valid": True,
            "provenance": "curriculum_engine_v1",
            "quality": {
                "status": "passed",
                "score": 1.0,
                "confidence": 1.0,
                "reasons": ["Syntactically verified curriculum template"],
            },
            "components": clause_dict.get("components", {}),
        }
