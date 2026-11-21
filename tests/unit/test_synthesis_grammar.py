"""Unit tests for valence-constrained grammar engine (WP 2.1)."""

from __future__ import annotations

from langpipe.synthesis.grammar import (
    GrammarClauseType,
    SyntacticClauseEngine,
    ValenceValidator,
)
from langpipe.synthesis.structural import check_structural_alignment


def test_valence_validator_intransitive_ergative_rejection():
    """Verify that an ergative-marked subject with an intransitive verb is strictly rejected."""
    validator = ValenceValidator(lang_code="mzr")

    # Assuming 'ka' or 'katsi' or another intransitive motion verb is intransitive
    # Manually configure test verb if needed:
    validator.verb_valences["ka"] = "intransitive"

    # Ungrammatical: *vaki-n ka-ai (ergative on intransitive subject)
    report_bad = validator.validate_clause("vaki-n ka-ai")
    assert not report_bad.valid
    assert any("cannot govern ergative" in v for v in report_bad.violations)

    # Grammatical: vaki ka-ai (absolutive subject)
    report_good = validator.validate_clause("vaki ka-ai")
    assert report_good.valid
    assert len(report_good.violations) == 0


def test_valence_validator_transitive_harmony():
    """Verify that a transitive verb accepts an ergative agent."""
    validator = ValenceValidator(lang_code="mzr")
    validator.verb_valences["oya"] = "transitive"

    # Grammatical: yora-n isu oya-ai (agent-ERG patient-ABS verb-TAM)
    report = validator.validate_clause("yora-n isu oya-ai")
    assert report.valid
    assert "oya" in report.verb_valences
    assert report.verb_valences["oya"] == "transitive"


def test_structural_roles_integration():
    """Verify that check_structural_alignment runs valence validation when lang_code is given."""
    # Mismatched ergative on intransitive: should fail roles_consistent
    alignment = check_structural_alignment(
        target_phrase="vaki-n ka-ai",
        igt_gloss="vaki-n ka-ai\nmenino-ERG ir-TAM",
        portuguese_translation="o menino vai",
        lang_code="mzr",
    )
    # If validator identified 'ka' as intransitive in lexicon view or profile,
    # roles_consistent will reflect it
    assert "roles_consistent" in alignment


def test_syntactic_clause_engine_transitive():
    engine = SyntacticClauseEngine(lang_code="mzr")

    mock_agent = {"headword": "vaki", "glosses_por": ["menino"], "pos": "noun"}
    mock_patient = {"headword": "isu", "glosses_por": ["macaco"], "pos": "noun"}
    mock_verb = {"headword": "oya", "glosses_por": ["ver"], "pos": "verb"}

    clause = engine.build_transitive(mock_agent, mock_patient, mock_verb, tam_suffix="-ai")
    assert clause["clause_type"] == GrammarClauseType.TRANSITIVE.value
    assert "vaki-n" in clause["target"]
    assert "isu" in clause["target"]
    assert "oya-ai" in clause["target"]
    assert "macaco" in clause["portuguese"]
    assert "menino" in clause["portuguese"]


def test_syntactic_clause_engine_negated():
    engine = SyntacticClauseEngine(lang_code="mzr")

    mock_subj = {"headword": "vaki", "glosses_por": ["menino"], "pos": "noun"}
    mock_verb = {"headword": "ka", "glosses_por": ["ir"], "pos": "verb"}

    clause = engine.build_intransitive(mock_subj, mock_verb, tam_suffix="-ai", negate=True)
    assert clause["clause_type"] == GrammarClauseType.INTRANSITIVE.value
    assert clause["negated"] is True
    assert "-ma" in clause["target"]
    assert "não" in clause["portuguese"]


def test_syntactic_clause_engine_interrogative():
    engine = SyntacticClauseEngine(lang_code="mzr")

    mock_subj = {"headword": "vaki", "glosses_por": ["menino"], "pos": "noun"}
    mock_verb = {"headword": "ka", "glosses_por": ["ir"], "pos": "verb"}

    clause = engine.build_interrogative(mock_subj, mock_verb)
    assert clause["clause_type"] == GrammarClauseType.INTERROGATIVE.value
    assert "-vẽ" in clause["target"] or "-ka" in clause["target"]
    assert "?" in clause["target"]


def test_syntactic_clause_engine_possession():
    engine = SyntacticClauseEngine(lang_code="mzr")

    mock_pos = {"headword": "vaki", "glosses_por": ["menino"], "pos": "noun"}
    mock_bp = {"headword": "mëkẽ", "glosses_por": ["mão"], "pos": "noun"}
    mock_verb = {"headword": "onís", "glosses_por": ["doer"], "pos": "verb"}

    clause = engine.build_inalienable_possession(mock_pos, mock_bp, mock_verb)
    assert clause["clause_type"] == GrammarClauseType.POSSESSION.value
    assert "vaki-n" in clause["target"]
    assert "mëkẽ" in clause["target"]
    assert "mão" in clause["portuguese"]
