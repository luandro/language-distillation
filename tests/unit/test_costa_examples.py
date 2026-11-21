"""Unit tests for the Costa (2002) example extractor.

See: src/langpipe/languages/mzr/costa_examples.py
"""

from __future__ import annotations

from langpipe.languages.mzr.costa_examples import (
    extract_examples,
)

# ---------------------------------------------------------------------------
# Fixture: the accepted (2) kama example from the spec (lines 124–131)
# ---------------------------------------------------------------------------

ACCEPT_LINES = [
    "(2) 'kama",
    "",
    "ka'ma-N 'kiNpu-0 'kini=a-vai",
    "' nome próprio'",
    "NP-ERG",
    "cyia-ABS",
    "pintar=AUX.T-REC",
    "''Kama pintou a cuia.'",
]
ACCEPT_TEXT = "\n".join(ACCEPT_LINES)

ACCEPT_EXPECTED_REF = "costa-2002:ex2"


# ---------------------------------------------------------------------------
# Fixture: prose paragraph that should NOT be mistaken for an example
# ---------------------------------------------------------------------------

PROSE_LINES = [
    "(1) Cabecalho",
    "",
    "Ergatividade cindida em Marubo",
    "",
    "Raquel Costa",
    "",
    "Museu Nacional/ Universidade Federal do Rio de Janeiro",
    "",
    "1. INTRODUCAO",
    "",
    "Estudos tipologicos desenvolvidos nas tres ultimas decadias levaram",
    "a um conjunto de generalizacoes envolvendo as linguas ergativas.",
    "Entre elas, a presencia constante de cisoes, condicionadas por fatores",
    "semanticos ou sintaticos.",
]
PROSE_TEXT = "\n".join(PROSE_LINES)


# ---------------------------------------------------------------------------
# Hold-back reason texts — built from line lists (so \\n produces real newlines)
# ---------------------------------------------------------------------------

STARRED_LINES = [
    "(1) *kama va",
    "",
    "ka'ma-N",
    "NP-ERG",
    "'Kama pintou a cuia.'",
]
STARRED_TEXT = "\n".join(STARRED_LINES)

OCR_NOISE_LINES = [
    "(1) 'kama va·",
    "",
    "ka'ma-N",
    "NP-ERG",
    "'Kama pintou a cuia.'",
]
OCR_NOISE_TEXT = "\n".join(OCR_NOISE_LINES)

MULTI_TRANSLATION_LINES = [
    "(1) 'kama",
    "",
    "ka'ma-N",
    "NP-ERG",
    "'Kama pintou a cuia.'",
    "",
    "'Outra traducao.'",
]
MULTI_TRANSLATION_TEXT = "\n".join(MULTI_TRANSLATION_LINES)

TRANSLATION_NOT_SENTENCE_LINES = [
    "(1) 'kama va",
    "",
    "ka'ma-N",
    "NP-ERG",
    "'orn;a'",
]
TRANSLATION_NOT_SENTENCE_TEXT = "\n".join(TRANSLATION_NOT_SENTENCE_LINES)

NO_TRANSLATION_LINES = [
    "(1) 'kama",
    "",
    "ka'ma-N",
]
NO_TRANSLATION_TEXT = "\n".join(NO_TRANSLATION_LINES)

NO_GLOSS_TIER_LINES = [
    "(1) 'kama",
    "",
    "ka'ma-N",
    "'Kama pintou a cuia.'",
]
NO_GLOSS_TIER_TEXT = "\n".join(NO_GLOSS_TIER_LINES)

AMBIGUOUS_LINES = [
    "(1) 'kama",
    "",
    "ka'ma-N",
    "NP-ERG",
    "'Kama pintou a cuia.'",
    "",
    "",
    "ka'ma-N-outro",
    "",
    "mais gloss",
]
AMBIGUOUS_TEXT = "\n".join(AMBIGUOUS_LINES)

WORD_LIST_LINES = [
    "(1) 'kama",
    "",
    "NP-ERG",
]
WORD_LIST_TEXT = "\n".join(WORD_LIST_LINES)


# ---------------------------------------------------------------------------
# Tests: accepted example (fixture from spec)
# ---------------------------------------------------------------------------


def test_extract_accept_fixture():
    """Accept the (2) 'kama block — the spec's example accept case."""
    candidates, held = extract_examples(ACCEPT_TEXT, source_ref="costa_2002.txt")
    assert len(candidates) == 1, f"Expected 1 candidate, got {len(candidates)}"
    assert candidates[0].ref == ACCEPT_EXPECTED_REF
    assert candidates[0].src == "ka'ma-N 'kiNpu-0 'kini=a-vai"
    assert candidates[0].tgt == "Kama pintou a cuia."
    assert candidates[0].gloss == "NP-ERG cyia-ABS pintar=AUX.T-REC"
    assert candidates[0].qc == {
        "extractor": "costa_examples/1",
        "accepted": True,
        "gloss_certified": False,
    }


# ---------------------------------------------------------------------------
# Tests: hold-back reasons — one test per reason
# ---------------------------------------------------------------------------

HOLD_REASONS = [
    "starred_example",
    "ocr_noise",
    "multiple_translations",
    "translation_not_sentence",
    "no_translation",
    "no_gloss_tier",
    "ambiguous_boundary",
    "word_list_not_sentence",
]


def test_hold_reasons():
    """Each hold reason produces the expected result."""
    reason_texts = {
        "starred_example": STARRED_TEXT,
        "ocr_noise": OCR_NOISE_TEXT,
        "multiple_translations": MULTI_TRANSLATION_TEXT,
        "translation_not_sentence": TRANSLATION_NOT_SENTENCE_TEXT,
        "no_translation": NO_TRANSLATION_TEXT,
        "no_gloss_tier": NO_GLOSS_TIER_TEXT,
        "ambiguous_boundary": AMBIGUOUS_TEXT,
        "word_list_not_sentence": WORD_LIST_TEXT,
    }
    for reason, text in reason_texts.items():
        candidates, held = extract_examples(text, source_ref="costa_2002.txt")
        assert len(held) >= 1, f"{reason}: expected at least 1 held, got {len(held)}"
        actual_reason = held[0].reason
        assert actual_reason == reason, f"{reason}: expected {reason}, got {actual_reason}"


# ---------------------------------------------------------------------------
# Tests: prose paragraph not mistaken for an example
# ---------------------------------------------------------------------------


def test_prose_not_mistaken_for_example():
    """A long prose paragraph must not be accepted as an example."""
    candidates, held = extract_examples(PROSE_TEXT, source_ref="costa_2002.txt")
    assert len(candidates) == 0, f"Expected 0 candidates from prose, got {len(candidates)}"


# ---------------------------------------------------------------------------
# Tests: determinism (run twice -> identical bytes)
# ---------------------------------------------------------------------------


def test_determinism():
    """Running the extractor twice on the same text must produce identical output."""
    candidates1, held1 = extract_examples(PROSE_TEXT, source_ref="costa_2002.txt")
    candidates2, held2 = extract_examples(PROSE_TEXT, source_ref="costa_2002.txt")
    assert len(candidates1) == len(candidates2)
    assert len(held1) == len(held2)
    for c1, c2 in zip(candidates1, candidates2, strict=False):
        assert c1.ref == c2.ref
        assert c1.src == c2.src
        assert c1.tgt == c2.tgt
        assert c1.gloss == c2.gloss
    for h1, h2 in zip(held1, held2, strict=False):
        assert h1.reason == h2.reason
        assert h1.raw == h2.raw


# ---------------------------------------------------------------------------
# Tests: NFC-only text preservation
# ---------------------------------------------------------------------------


def test_nfc_preservation():
    """Text must only have NFC normalization applied — no other changes."""
    text = ACCEPT_TEXT
    candidates, held = extract_examples(text, source_ref="costa_2002.txt")
    assert len(candidates) == 1
    # The src should be NFC-normalized but not otherwise altered
    assert candidates[0].src == "ka'ma-N 'kiNpu-0 'kini=a-vai"


# ---------------------------------------------------------------------------
# OCR contamination and serialized determinism
# ---------------------------------------------------------------------------

OCR_DIGIT_TEXT = "\n".join(
    [
        "(8) tJa'nu",
        "tJa'nu-N maN 1siN-0 'paki-ai",
        "NP-ERG cuia-ABS derrubar-PRES/IM",
        "'Tjanu derrubou a cuia.'",
    ]
)


def test_digit_touching_a_letter_is_held_as_ocr_noise():
    candidates, held = extract_examples(OCR_DIGIT_TEXT, source_ref="costa_2002.txt")
    assert candidates == []
    assert [h.reason for h in held] == ["ocr_noise"]


def test_zero_morpheme_is_not_ocr_noise():
    candidates, _ = extract_examples(ACCEPT_TEXT, source_ref="costa_2002.txt")
    assert [c.src for c in candidates] == ["ka'ma-N 'kiNpu-0 'kini=a-vai"]


def test_serialized_output_is_byte_identical_with_accepted_and_held_rows():
    import json
    from dataclasses import asdict

    text = ACCEPT_TEXT + "\n\n" + OCR_DIGIT_TEXT

    def run() -> str:
        cands, held = extract_examples(text, source_ref="costa_2002.txt")
        assert cands and held
        return json.dumps([asdict(r) for r in (*cands, *held)], sort_keys=True)

    assert run() == run()
