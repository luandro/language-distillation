"""The reader-facing dictionary must not overclaim its validation basis.

Card #270: the web reader and the print edition called every `validated` entry
"gold standard", which the artifact never records. These tests pin two rules:

1. no reader-facing status label claims human review, consensus, or a gold
   standard (those are not recorded anywhere in the artifact);
2. a label that names a basis class (a published source, corpus attestation)
   may only render when the shipped data actually records that class.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from langpipe.lexicon.audit.view import LexiconView
from langpipe.lexicon.dictionary.session import (
    BASIS_CORPUS_ONLY,
    BASIS_SOURCE_AND_CORPUS,
    BASIS_SOURCE_ASSERTION,
    BASIS_UNRECORDED,
    DictionarySessionBuilder,
)
from tests.fixtures.artifacts import BUILT_LEXICON, requires_built_lexicon

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_INDEX = REPO_ROOT / "exports" / "web" / "index.html"
JS_PATH = REPO_ROOT / "exports" / "web" / "dictionary.js"


def _web_source() -> str:
    return WEB_INDEX.read_text(encoding="utf-8")


def _status_labels() -> dict[str, dict[str, str]]:
    """The two `status_labels` blocks (pt, en), parsed without a JS runtime."""
    source = _web_source()
    blocks = re.findall(r"status_labels:\s*\{(.*?)\}", source, re.DOTALL)
    assert len(blocks) == 2, f"expected a pt and an en status_labels block, got {len(blocks)}"
    parsed = []
    for block in blocks:
        pairs = re.findall(r"(\w+):\s*\"([^\"]*)\"", block)
        parsed.append(dict(pairs))
    assert set(parsed[0]) == set(parsed[1]), "pt and en must label the same statuses"
    return {"pt": parsed[0], "en": parsed[1]}


def _session():
    if not BUILT_LEXICON.exists():
        pytest.skip(f"needs the built Marúbo lexicon ({BUILT_LEXICON.name} in exports/mzr)")
    with open(REPO_ROOT / "exports" / "mzr" / "dictionary.json", encoding="utf-8") as f:
        raw = json.load(f)
    clean = LexiconView(raw, view="clean").entries
    return DictionarySessionBuilder().build(clean, forms_source=raw["lexicon"])


@pytest.fixture(scope="module")
def shipped_session():
    return _session()


# --- status labels ---------------------------------------------------------

FORBIDDEN_CLAIMS = (
    "padrão-ouro",
    "padrao-ouro",
    "padrão ouro",
    "gold-standard",
    "gold standard",
    "revisão humana",
    "human review",
    "peer review",
    "consenso de especialistas",
    "expert consensus",
)


def test_status_labels_claim_no_unrecorded_authority():
    labels = _status_labels()
    for locale, mapping in labels.items():
        for status, label in mapping.items():
            low = label.lower()
            for claim in FORBIDDEN_CLAIMS:
                assert claim not in low, f"{locale}.{status} claims {claim!r}: {label!r}"


def test_validated_label_names_the_basis_the_artifact_records(shipped_session):
    """If the label names a class, every validated entry must carry that class.

    This is the guard that fails when the data changes and the label does not:
    a corpus-only or unrecorded validation cannot keep the "published source"
    label, and a source assertion cannot claim corpus attestation.
    """
    labels = _status_labels()
    session = shipped_session
    validated = [e for e in session["entries"] if e["status"] == "validated"]
    assert validated, "the shipped artifact should still have validated entries"

    source_phrases = ("fonte publicada", "published source")
    corpus_phrases = ("atestação no corpus", "corpus attestation")

    for locale, mapping in labels.items():
        label = mapping["validated"].lower()
        if any(phrase in label for phrase in source_phrases):
            missing = [e["headword"] for e in validated if not e["validation_basis"]["sources"]]
            assert not missing, (
                f"{locale}.validated names a published source, but {len(missing)} "
                f"validated entries record no work: {missing[:5]}"
            )
        if any(phrase in label for phrase in corpus_phrases):
            missing = [
                e["headword"] for e in validated if not e["validation_basis"]["corpus_attestations"]
            ]
            assert not missing, (
                f"{locale}.validated names corpus attestation, but {len(missing)} "
                f"validated entries cite no corpus line: {missing[:5]}"
            )


def test_basis_kind_templates_exist_in_both_locales():
    """Every kind the server can emit has pt and en wording."""
    source = _web_source()
    for kind in (
        BASIS_SOURCE_ASSERTION,
        BASIS_SOURCE_AND_CORPUS,
        BASIS_CORPUS_ONLY,
        BASIS_UNRECORDED,
    ):
        key = f"dict_basis_{kind}"
        assert source.count(f"{key}:") == 2, f"{key} must exist once per locale"


def test_every_shipped_basis_kind_has_a_reader_label(shipped_session):
    """No entry may render a basis the UI has no words for."""
    source = _web_source()
    session = shipped_session
    kinds = {e["validation_basis"]["kind"] for e in session["entries"]}
    assert kinds
    for kind in kinds:
        assert f"dict_basis_{kind}:" in source, f"no reader wording for basis {kind!r}"


@requires_built_lexicon
def test_reader_basis_text_is_derived_from_the_entry_not_a_constant():
    """The pane must read `validation_basis`; a hard-coded verdict would drift."""
    js = JS_PATH.read_text(encoding="utf-8")
    assert "entry.validation_basis" in js or "data.validation_basis" in js
    assert "dict_basis_" in js


def test_dictionary_surface_does_not_emit_the_gold_standard_label():
    """A banned phrase in the dictionary block would reach readers verbatim."""
    source = _web_source()
    start = source.index("dict_basis_label")
    window = source[max(0, start - 4000) : start]
    for claim in ("Padrão-Ouro", "Gold-Standard", "Gold Standard"):
        assert claim not in window


# --- print legend ----------------------------------------------------------


def _legend(entries) -> str:
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    exporter = PrintableDictionaryExporter(
        target_lang="mzr", target_name="Marúbo", contact_lang="por"
    )
    return exporter._render_status_legend(entries)


def _entry(headword: str, status: str, provenance: str, attestations: int) -> dict:
    return {
        "headword": headword,
        "status": status,
        "attestations": attestations,
        "validation_basis": {
            "kind": (
                BASIS_SOURCE_AND_CORPUS
                if provenance and attestations
                else BASIS_SOURCE_ASSERTION
                if provenance
                else BASIS_CORPUS_ONLY
                if attestations
                else BASIS_UNRECORDED
            ),
            "sources": [provenance] if provenance else [],
            "corpus_attestations": attestations,
        },
    }


def test_print_legend_claims_only_the_basis_the_entries_record():
    source_only = _legend([_entry("a", "validated", "Costa (2002)", 0)])
    assert "obra publicada nomeada na bibliografia" in source_only
    assert "atestação do corpus" not in source_only

    corpus_only = _legend([_entry("b", "validated", "", 2)])
    assert "atestação do corpus" in corpus_only
    assert "obra publicada nomeada na bibliografia" not in corpus_only

    both = _legend([_entry("c", "validated", "Costa (2002)", 1)])
    assert "obra publicada nomeada na bibliografia" in both
    assert "atestação do corpus" in both


def test_print_legend_admits_an_unrecorded_basis():
    legend = _legend([_entry("d", "validated", "", 0)])
    assert "não registra a base desta validação" in legend
    assert "obra publicada nomeada na bibliografia" not in legend
    assert "atestação do corpus" not in legend


def test_print_legend_never_asserts_human_review_or_a_gold_standard():
    legend = _legend([_entry("a", "validated", "Costa (2002)", 1)])
    low = legend.lower()
    assert "padrão-ouro" not in low
    assert "gold standard" not in low and "gold-standard" not in low
    # The legend may *deny* expert consensus; it may never assert it.
    for match in re.finditer(r"consenso de especialistas", low):
        before = low[max(0, match.start() - 40) : match.start()]
        assert "não significa" in before or "nem" in before, legend


def test_print_legend_counts_match_the_entries():
    entries = [
        _entry("a", "validated", "Costa (2002)", 0),
        _entry("b", "validated", "Costa (2002)", 3),
        _entry("c", "supported", "", 1),
    ]
    legend = _legend(entries)
    assert "Dos 2 verbetes com ✓, 1 trazem exemplo atestado" in legend
    assert "1 registram apenas a obra de origem" in legend


def test_print_legend_note_is_omitted_when_nothing_is_validated():
    legend = _legend([_entry("c", "supported", "", 1)])
    assert "legend-note" not in legend


def test_shipped_artifact_legend_reports_the_measured_split(shipped_session):
    """36 of the 144 ✓ entries cite a corpus line; 108 name only the work."""
    session = shipped_session
    legend = _legend(session["entries"])
    assert "Dos 144 verbetes com ✓, 36 trazem exemplo atestado" in legend
    assert "108 registram apenas a obra de origem" in legend
