"""Clef Semantic Quality & Selectional Restriction Judge for Synthetic Data.

Follows ADR-0006 and ADR-0020:
- Operates primarily on pivot-language representations and semantic frames.
- Identifies and quarantines nonsensical, absurd, or unnatural sentences.
- Never promotes directly to 'validated' (reserved for human reviewers).
"""

from __future__ import annotations

from typing import Any, Protocol

from langpipe.synthesis.grounding import GroundingReport
from langpipe.synthesis.quality import (
    ClefJudgment,
    compute_judgment_id,
    decide_quality,
)
from langpipe.synthesis.structural import check_structural_alignment


class ClefJudge(Protocol):
    """Protocol for Clef semantic evaluation judges."""

    judge_model: str
    calibration_status: str

    def judge_phrase(
        self,
        target_phrase: str,
        igt_gloss: str,
        portuguese_translation: str,
        grounding_report: GroundingReport,
        l1_checks: dict[str, bool] | None = None,
    ) -> ClefJudgment:
        """Perform semantic quality evaluation of a synthetic phrase."""
        ...


class HeuristicClefJudge:
    """Deterministic, offline semantic & selectional restriction judge.

    Applies lexical animacy and predicate-argument compatibility rules:
    - Humans/Hunters: can eat, hunt, speak, cook, walk, make tools.
    - Animals: can move, eat (prey), run; cannot cook/burn, weave, speak.
    - Edibles: can be eaten, cooked.
    - Inanimates/Environment: cannot be active volitional agents of verbs like
      matar, queimar, comer.
    """

    judge_model: str = "clef-heuristic-v1"
    calibration_status: str = "uncalibrated"

    # Semantic Categories for Stems
    HUMANS = {
        "vaki",
        "yora",
        "yõi",
        "eva",
        "papa",
        "chuna",
        "chuna-katsi",
        "chanin",
        "shava",
        "kõi",
        "tata",
        "vawa",
        "koka",
        "vavi",
        "ẽa",
        "mia",
        "nukẽ",
        "nuki",
        "ato",
        "hanto",
    }
    ANIMALS = {
        "isu",
        "yapa",
        "inõ",
        "chai",
        "mana",
        "nawĩ",
        "kapa",
        "rono",
        "yawa",
        "vapa",
        "sisi",
        "awá",
        "yama",
        "wapa",
        "takari",
    }
    FLYING_CREATURES = {"chai", "sisi", "manin"}
    EDIBLE_OBJECTS = {
        "nami",
        "yapa",
        "matsu",
        "shave",
        "vimi",
        "kopi",
        "inĩ",
        "nawa",
        "kapa",
        "isu",
        "mana",
        "waka",
    }
    INANIMATES = {
        "vapa",
        "mene",
        "tapit",
        "nia",
        "vari",
        "use",
        "tapi",
        "vake",
        "kachi",
        "shavĩ",
        "nono",
        "pani",
        "mansin",
        "kinpu",
        "iwi",
    }

    # Predicate restrictions
    PREDICATES = {
        "pi": {
            "meaning": "comer",
            "allowed_agents": HUMANS | ANIMALS,
            "allowed_patients": EDIBLE_OBJECTS,
            "disallowed_patients": HUMANS,
        },
        "yamama": {
            "meaning": "matar",
            "allowed_agents": HUMANS | {"inõ", "yawa", "rono"},  # Humans or lethal predators
            "disallowed_agents": {"yapa", "chai", "sisi", "isu"} | INANIMATES | EDIBLE_OBJECTS,
            "allowed_patients": ANIMALS | HUMANS,
            "disallowed_patients": INANIMATES,
        },
        "yoin": {
            "meaning": "queimar / assar",
            "allowed_agents": HUMANS,  # A fish or monkey cannot cook/burn!
            "allowed_patients": EDIBLE_OBJECTS | INANIMATES,
            "disallowed_agents": ANIMALS | INANIMATES,
        },
        "nuya": {
            "meaning": "voar",
            "allowed_agents": FLYING_CREATURES,
            "disallowed_agents": {"yapa", "vaki", "inõ", "mana"},
        },
        "ina": {
            "meaning": "pegar / agarrar",
            "allowed_agents": HUMANS | ANIMALS,
            "allowed_patients": ANIMALS | EDIBLE_OBJECTS | INANIMATES,
        },
        "nuku": {
            "meaning": "chegar",
            "allowed_agents": HUMANS | ANIMALS,
        },
        "ui": {
            "meaning": "ver",
            "allowed_agents": HUMANS | ANIMALS,
            "allowed_patients": HUMANS | ANIMALS | INANIMATES | EDIBLE_OBJECTS | {"taka"},
        },
        "ninka": {
            "meaning": "ouvir",
            "allowed_agents": HUMANS | ANIMALS,
            "allowed_patients": HUMANS | ANIMALS | {"shaka", "pashu"},
        },
        "aka": {
            "meaning": "fazer / beber / agir",
            "allowed_agents": HUMANS | ANIMALS,
            "allowed_patients": EDIBLE_OBJECTS | INANIMATES | {"ravweoki", "waka"},
        },
        "kiki": {
            "meaning": "tecer",
            "allowed_agents": HUMANS,
            "allowed_patients": {"pani", "tapi"},
            "disallowed_agents": ANIMALS | INANIMATES,
        },
        "kini": {
            "meaning": "pintar / desenhar",
            "allowed_agents": HUMANS,
            "allowed_patients": {"mansin", "kinpu", "tapit", "yora", "vaki"},
            "disallowed_agents": ANIMALS | INANIMATES,
        },
    }

    def __init__(self, lang_code: str = "und") -> None:
        self.lang_code = lang_code

    def judge_phrase(
        self,
        target_phrase: str,
        igt_gloss: str,
        portuguese_translation: str,
        grounding_report: GroundingReport,
        l1_checks: dict[str, bool] | None = None,
    ) -> ClefJudgment:
        """Evaluate semantic plausibility and quarantine absurd phrases."""
        if l1_checks is None:
            l1_checks = check_structural_alignment(
                target_phrase, igt_gloss, portuguese_translation, self.lang_code
            )

        # Extract stems identified in grounding
        stems = grounding_report.identified_stems

        # Frame extraction heuristic:
        # In SOV clauses:
        # If 3 stems: [Agent, Patient, Verb]
        # If 2 stems: [Agent, Verb] or [Patient, Verb]
        agent: str | None = None
        patient: str | None = None
        verb: str | None = None

        if len(stems) >= 3:
            agent = stems[0]
            patient = stems[1]
            verb = stems[2]
        elif len(stems) == 2:
            agent = stems[0]
            verb = stems[1]

        selection_violation = False
        violation_detail = ""
        p_plausible = 0.90
        p_implausible = 0.10
        p_fidelity = 0.95

        # Check predicate restrictions
        if verb and verb in self.PREDICATES:
            rule = self.PREDICATES[verb]
            allowed_agents = rule.get("allowed_agents")
            disallowed_agents = rule.get("disallowed_agents")
            allowed_patients = rule.get("allowed_patients")
            disallowed_patients = rule.get("disallowed_patients")

            # Check agent
            if agent:
                if disallowed_agents and agent in disallowed_agents:
                    selection_violation = True
                    violation_detail = (
                        f"'{agent}' ({rule['meaning']}) não pode ser agente volicional do predicado"
                    )
                    p_plausible = 0.05
                    p_implausible = 0.95
                elif allowed_agents and agent not in allowed_agents:
                    selection_violation = True
                    violation_detail = f"'{agent}' não é agente válido para o predicado '{verb}'"
                    p_plausible = 0.15
                    p_implausible = 0.85

            # Check patient
            if patient and not selection_violation:
                if disallowed_patients and patient in disallowed_patients:
                    selection_violation = True
                    violation_detail = f"'{patient}' não pode ser paciente/alvo de '{verb}'"
                    p_plausible = 0.10
                    p_implausible = 0.90
                elif allowed_patients and patient not in allowed_patients:
                    selection_violation = True
                    violation_detail = (
                        f"'{patient}' é semanticamente incompatível com o verbo '{verb}'"
                    )
                    p_plausible = 0.20
                    p_implausible = 0.80

        # Also inspect Portuguese translation for obvious world-knowledge absurdity
        pt_lower = portuguese_translation.lower()
        absurd_patterns = [
            "peixe queimará",
            "peixe queima",
            "peixe assará",
            "peixe matará",
            "peixe mata",
            "carne come",
            "carne comeu",
            "carne matará",
        ]
        if any(bad in pt_lower for bad in absurd_patterns):
            selection_violation = True
            violation_detail = (
                f"agente '{agent or 'sujeito'}' (peixe/carne) semanticamente impossível "
                f"para a ação no mundo real ({portuguese_translation})"
            )
            p_plausible = 0.02
            p_implausible = 0.98

        l2_answers = {
            "p_plausible": p_plausible,
            "p_implausible": p_implausible,
            "p_fidelity": p_fidelity,
            "selection_violation": selection_violation,
            "violation_detail": violation_detail,
        }

        status, reasons, score, critique = decide_quality(
            grounding_valid=grounding_report.valid,
            l1_checks=l1_checks,
            l2_answers=l2_answers,
            calibration_status=self.calibration_status,
        )

        return ClefJudgment(
            judgment_id=compute_judgment_id(target_phrase),
            phrase_id=compute_judgment_id(target_phrase, "phrase"),
            judge_model=self.judge_model,
            calibration_status=self.calibration_status,
            checks=l1_checks,
            answers=l2_answers,
            status=status,
            reasons=reasons,
            score=score,
            critique=critique,
        )


class MockClefJudge:
    """Mock Judge for testing and controlled grading."""

    judge_model: str = "mock-clef-v1"
    calibration_status: str = "uncalibrated"

    def __init__(self, force_status: Any = None) -> None:
        self.force_status = force_status

    def judge_phrase(
        self,
        target_phrase: str,
        igt_gloss: str,
        portuguese_translation: str,
        grounding_report: GroundingReport,
        l1_checks: dict[str, bool] | None = None,
    ) -> ClefJudgment:
        heuristic = HeuristicClefJudge()
        judgment = heuristic.judge_phrase(
            target_phrase, igt_gloss, portuguese_translation, grounding_report, l1_checks
        )
        if self.force_status:
            judgment.status = self.force_status
        return judgment


def get_clef_judge(judge_name: str = "heuristic", lang_code: str = "und") -> ClefJudge:
    """Factory function for Clef Semantic Judges."""
    norm = judge_name.strip().lower()
    if norm in ("mock", "test"):
        return MockClefJudge()
    return HeuristicClefJudge(lang_code=lang_code)
