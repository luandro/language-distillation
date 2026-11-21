"""Unit tests for language-agnostic reverse bi-directional lexicon index (WP 1.3)."""

from __future__ import annotations

import json
from pathlib import Path

from langpipe.lexicon.reverse import (
    ReverseLexiconIndex,
    extract_contact_headwords,
    normalize_search_key,
)


def test_normalize_search_key():
    assert normalize_search_key("Água") == "agua"
    assert normalize_search_key("Criança, Filho!") == "crianca filho"
    assert normalize_search_key("mão-de-obra") == "mao-de-obra"
    assert normalize_search_key("  Coração   ") == "coracao"


def test_extract_contact_headwords():
    # Basic comma separation
    words = extract_contact_headwords("criança, filho, menino")
    assert "criança" in words
    assert "filho" in words
    assert "menino" in words

    # Parenthetical handling: extracts main terms and informative parenthetical content
    words2 = extract_contact_headwords("canoa (embarcação)")
    assert "canoa" in words2
    assert "embarcação" in words2

    # Grammatical abbreviation parentheticals should not be extracted as headwords
    words3 = extract_contact_headwords("correr (v. intr.)")
    assert "correr" in words3
    assert "v. intr." not in words3

    # Leading article extraction
    words4 = extract_contact_headwords("o sol")
    assert "sol" in words4
    assert "o sol" in words4


def test_reverse_lexicon_index_build_and_lookup():
    mock_lexicon = [
        {
            "headword": "vaki",
            "pos": "noun",
            "glosses_por": ["criança, filho (menino)"],
            "provenance": "Grammar (2000)",
            "semantics": {
                "valence": "non_verbal",
                "inalienability": "inalienable_kin",
                "primary_domain": "kinship_social",
            },
            "citations": [
                {
                    "citation_id": "c1",
                    "reference": "GEN 1:1",
                    "source_text": "vaki ka-ai",
                    "target_text": "a criança vai",
                }
            ],
        },
        {
            "headword": "yapa",
            "pos": "noun",
            "glosses_por": ["criança pequena", "bebê"],
            "provenance": "Field notes",
            "semantics": {
                "valence": "non_verbal",
                "inalienability": "alienable",
                "primary_domain": "kinship_social",
            },
            "citations": [],
        },
        {
            "headword": "vana",
            "pos": "verb",
            "glosses_por": ["falar, dizer"],
            "semantics": {
                "valence": "intransitive",
                "primary_domain": "perception_mind",
            },
            "citations": [
                {
                    "citation_id": "c2",
                    "reference": "ACT 2:4",
                    "source_text": "vana-ai",
                    "target_text": "falou",
                }
            ],
        },
    ]

    index = ReverseLexiconIndex(contact_language="por").build_from_lexicon(mock_lexicon)

    assert len(index) >= 5

    # Exact lookup
    results = index.lookup("criança", exact=True)
    assert len(results) == 1
    entry = results[0]
    assert entry.contact_headword == "criança"
    # Senses should have vaki ranked first because it has an attested citation
    assert len(entry.senses) >= 1
    assert entry.senses[0].target_headword == "vaki"
    assert entry.senses[0].attestation_count == 1
    assert entry.senses[0].primary_domain == "kinship_social"

    # Accent-insensitive lookup: "crianca" finds "criança"
    results_unaccented = index.lookup("crianca")
    assert any(e.contact_headword == "criança" for e in results_unaccented)

    # Prefix lookup: "beb" finds "bebê"
    results_prefix = index.lookup("beb")
    assert any(e.contact_headword == "bebê" for e in results_prefix)

    # Verb lookup: "falar" finds "vana"
    results_verb = index.lookup("falar")
    assert len(results_verb) == 1
    assert results_verb[0].senses[0].target_headword == "vana"
    assert results_verb[0].senses[0].valence == "intransitive"


def test_reverse_lexicon_serialization(tmp_path: Path):
    mock_lexicon = [
        {
            "headword": "tii",
            "pos": "noun",
            "glosses_por": ["fogo"],
            "citations": [],
            "semantics": {"primary_domain": "universe_nature"},
        }
    ]

    index = ReverseLexiconIndex(contact_language="por").build_from_lexicon(mock_lexicon)
    out_file = tmp_path / "reverse.json"
    index.save_json(out_file, metadata={"target_language": "test"})

    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["metadata"]["contact_language"] == "por"
    assert data["metadata"]["target_language"] == "test"
    assert len(data["entries"]) == 1
    assert data["entries"][0]["contact_headword"] == "fogo"
    assert data["entries"][0]["senses"][0]["target_headword"] == "tii"
