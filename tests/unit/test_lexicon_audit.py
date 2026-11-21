"""Unit tests for Lexicon Audit, Clef Dictionary Cleanup, and LexiconView.

Adheres to:
- AGENTS.md Invariants 1, 2, 4, 9, 10
- ADR-0006: Decision models restricted on unseen target language
- ADR-0020: Clef as pivot-side quality judge
- ADR-0021: Lexicon audit and consumer views
"""

from langpipe.lexicon.audit.clef_gloss import HeuristicGlossClassifier
from langpipe.lexicon.audit.decide import decide_entry_audit
from langpipe.lexicon.audit.model import LexicalClass, UseScope
from langpipe.lexicon.audit.rules import audit_entry_rules
from langpipe.lexicon.audit.service import audit_lexicon_dict
from langpipe.lexicon.audit.view import LexiconView
from langpipe.synthesis.grounding import GroundingValidator


def test_clean_lemmas_false_positive_guard():
    """Ensure core Marúbo native words are NEVER falsely excluded or classified as names."""
    core_native_words = [
        {"headword": "yapa", "glosses_por": ["peixe"], "status": "validated"},
        {"headword": "wapa", "glosses_por": ["cachorro"], "status": "validated"},
        {"headword": "vaki", "glosses_por": ["criança, filho"], "status": "validated"},
        {"headword": "pi", "glosses_por": ["comer"], "status": "validated"},
        {"headword": "ia", "glosses_por": ["formiga"], "status": "validated"},
        {"headword": "ui", "glosses_por": ["ver"], "status": "validated"},
        {"headword": "chi", "glosses_por": ["fogo"], "status": "validated"},
        {"headword": "kini", "glosses_por": ["pintar, desenhar"], "status": "validated"},
        {"headword": "txiro", "glosses_por": ["macaco-prego"], "status": "validated"},
        {"headword": "ẽa", "glosses_por": ["eu"], "status": "validated"},
        {"headword": "mia", "glosses_por": ["você, tu"], "status": "validated"},
    ]

    classifier = HeuristicGlossClassifier()
    for entry in core_native_words:
        signals, flags = audit_entry_rules(entry, lang_code="mzr")
        clef_res = classifier.classify_gloss(entry.get("glosses_por", []))
        audit = decide_entry_audit(entry, signals, flags, clef_res, lang_code="mzr")

        assert audit.lexical_class == LexicalClass.LEMMA, (
            f"False positive: {entry['headword']} should be LEMMA"
        )
        assert UseScope.GROUNDING in audit.use_scopes, (
            f"{entry['headword']} must have GROUNDING use scope"
        )
        assert UseScope.SYNTHESIS_PROMPT in audit.use_scopes


def test_proper_nouns_detected_and_categorized():
    """Names must be classified as PROPER_NOUN and excluded from grounding lemmas."""
    name_entries = [
        {"headword": "judas", "glosses_por": ["iscariotes"], "status": "supported"},
        {"headword": "noemi", "glosses_por": ["elimeleque"], "status": "supported"},
        {"headword": "simão", "glosses_por": ["pedro"], "status": "supported"},
        {"headword": "pedro", "glosses_por": ["simão"], "status": "supported"},
        {"headword": "iscariotes", "glosses_por": ["judas"], "status": "supported"},
        {"headword": "caldeu", "glosses_por": ["caldeus"], "status": "supported"},
        {"headword": "judeu", "glosses_por": ["judeus"], "status": "supported"},
        {"headword": "nilo", "glosses_por": ["rio"], "status": "supported"},
        {"headword": "elimeleque", "glosses_por": ["noemi"], "status": "supported"},
    ]

    classifier = HeuristicGlossClassifier()
    for entry in name_entries:
        signals, flags = audit_entry_rules(entry, lang_code="mzr")
        clef_res = classifier.classify_gloss(entry.get("glosses_por", []))
        audit = decide_entry_audit(entry, signals, flags, clef_res, lang_code="mzr")

        assert audit.lexical_class == LexicalClass.PROPER_NOUN, (
            f"{entry['headword']} should be PROPER_NOUN"
        )
        assert UseScope.GROUNDING not in audit.use_scopes, (
            f"{entry['headword']} must not be in GROUNDING"
        )
        assert UseScope.ONOMASTICON in audit.use_scopes


def test_inflected_tokens_and_artifacts_detected():
    """Inflected forms and transcription artifacts must be identified and excluded."""
    noisy_entries = [
        {"headword": "davipa", "glosses_por": ["davi"], "status": "supported"},  # Davi + -pa
        {"headword": "israelrasĩní", "glosses_por": ["israelitas"], "status": "supported"},
        {"headword": "jesusvere", "glosses_por": ["persegues"], "status": "supported"},
        {"headword": "3tíi", "glosses_por": ["galo"], "status": "supported"},  # Digit artifact
        {"headword": "10tíi", "glosses_por": ["dízimo"], "status": "supported"},  # Digit artifact
        {"headword": "ana revu", "glosses_por": ["língua"], "status": "supported"},  # Multiword
    ]

    classifier = HeuristicGlossClassifier()
    for entry in noisy_entries:
        signals, flags = audit_entry_rules(entry, lang_code="mzr")
        clef_res = classifier.classify_gloss(entry.get("glosses_por", []))
        audit = decide_entry_audit(entry, signals, flags, clef_res, lang_code="mzr")

        assert audit.lexical_class in (
            LexicalClass.INFLECTED_FORM,
            LexicalClass.ARTIFACT,
            LexicalClass.MULTIWORD,
        ), f"{entry['headword']} must not be LEMMA"
        assert UseScope.GROUNDING not in audit.use_scopes


def test_lexicon_view_and_grounding_integration():
    """Clean LexiconView must reject names like 'judas' while accepting native lemmas."""
    test_lexicon = [
        {"headword": "vaki", "glosses_por": ["criança"], "status": "validated"},
        {"headword": "pi", "glosses_por": ["comer"], "status": "validated"},
        {"headword": "nami", "glosses_por": ["carne"], "status": "validated"},
        {"headword": "judas", "glosses_por": ["iscariotes"], "status": "supported"},
        {"headword": "3tíi", "glosses_por": ["galo"], "status": "supported"},
    ]
    raw_dict = {"language_code": "mzr", "language_name": "Marúbo", "lexicon": test_lexicon}

    audited_dict = audit_lexicon_dict(raw_dict, lang_code="mzr")
    clean_view = LexiconView(audited_dict, view="clean")
    names_view = LexiconView(audited_dict, view="names")

    # Clean view should only contain genuine lemmas
    assert "vaki" in clean_view.stems
    assert "pi" in clean_view.stems
    assert "nami" in clean_view.stems
    assert "judas" not in clean_view.stems
    assert "3tíi" not in clean_view.stems

    # Names view should contain proper names
    assert "judas" in names_view.stems

    # Grounding validator with clean view rejects 'judas' as an unverified token!
    validator = GroundingValidator(lang_code="mzr", lexicon_view=clean_view)
    report = validator.validate("judas-n nami pi-ai")
    assert report.valid is False
    assert "judas-n" in report.unverified_tokens

    # Valid sentence passes
    valid_report = validator.validate("vaki-n nami pi-ai")
    assert valid_report.valid is True
