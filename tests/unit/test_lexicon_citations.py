"""Unit tests for Attested Citation and Example Miner (WP 1.1)."""

from langpipe.lexicon.citations import (
    ParallelCorpusVerse,
    clean_usfm_text,
    enrich_lexicon_with_citations,
    find_citations_for_lemma,
    parse_reference_verses,
    parse_usfm_verses,
)


def test_clean_usfm_text():
    sample = r"\p \v 1 Txitavíki mai akápari.\f + \fr 1.5 \ft Hebraicõ vana.\f* \v 2 Mai tanatĩpa."
    cleaned = clean_usfm_text(sample)
    assert r"\f" not in cleaned
    assert "Hebraicõ" not in cleaned
    assert "Txitavíki mai akápari" in cleaned
    assert "Mai tanatĩpa" in cleaned


def test_parse_usfm_and_reference_verses():
    usfm_data = """\\c 1
\\v 1
In the beginning God created the heavens and the earth.
\\v 2
The earth was without form and void.
\\c 2
\\v 1
Thus the heavens and the earth were finished.
"""
    ref_data = """\\v GEN.1.1
No princípio criou Deus os céus e a terra.
\\v GEN.1.2
E a terra estava desordenada e vazia.
\\v GEN.2.1
Assim os céus e a terra foram acabados.
"""
    usfm_map = parse_usfm_verses(usfm_data, "GEN")
    ref_map = parse_reference_verses(ref_data)

    assert (1, 1) in usfm_map
    assert (1, 2) in usfm_map
    assert (2, 1) in usfm_map

    assert (1, 1) in ref_map
    assert (1, 2) in ref_map
    assert (2, 1) in ref_map

    assert "beginning" in usfm_map[(1, 1)]
    assert "princípio" in ref_map[(1, 1)]


def test_find_citations_for_lemma():
    verses = [
        ParallelCorpusVerse(
            book="GEN",
            chapter=1,
            verse=1,
            target_text="vaki-n nami pi-ai.",
            reference_text="A criança está comendo a carne.",
        ),
        ParallelCorpusVerse(
            book="GEN",
            chapter=1,
            verse=2,
            target_text="yapa vaki oĩ-katsai.",
            reference_text="O peixe verá a criança.",
        ),
        ParallelCorpusVerse(
            book="EXO",
            chapter=2,
            verse=5,
            target_text="mai shavá aka.",
            reference_text="Fez a terra clara.",
        ),
    ]

    # Test exact match
    cits_yapa = find_citations_for_lemma("yapa", verses)
    assert len(cits_yapa) == 1
    assert cits_yapa[0].source_ref == "GEN 1:2"
    assert cits_yapa[0].matched_token == "yapa"

    # Test stem + affix match (vaki-n matches lemma vaki)
    cits_vaki = find_citations_for_lemma("vaki", verses)
    assert len(cits_vaki) == 2
    assert cits_vaki[0].headword == "vaki"
    assert any(c.matched_token == "vaki-n" for c in cits_vaki)
    assert any(c.matched_token == "vaki" for c in cits_vaki)


def test_enrich_lexicon_with_citations():
    verses = [
        ParallelCorpusVerse(
            book="GEN",
            chapter=1,
            verse=1,
            target_text="vaki-n nami pi-ai.",
            reference_text="A criança está comendo a carne.",
        )
    ]
    dict_data = {
        "language_code": "und",
        "lexicon": [
            {"headword": "vaki", "glosses_por": ["criança"]},
            {"headword": "nami", "glosses_por": ["carne"]},
            {"headword": "ono", "glosses_por": ["anta"]},
        ],
    }

    enriched = enrich_lexicon_with_citations(dict_data, verses)
    vaki_entry = next(e for e in enriched["lexicon"] if e["headword"] == "vaki")
    nami_entry = next(e for e in enriched["lexicon"] if e["headword"] == "nami")
    ono_entry = next(e for e in enriched["lexicon"] if e["headword"] == "ono")

    assert len(vaki_entry["citations"]) == 1
    assert vaki_entry["citations"][0]["source_ref"] == "GEN 1:1"
    assert vaki_entry["example"] == "vaki-n nami pi-ai."
    assert vaki_entry["trans"] == "A criança está comendo a carne."

    assert len(nami_entry["citations"]) == 1
    assert len(ono_entry["citations"]) == 0

    assert enriched["citations_stats"]["entries_with_citations"] == 2
