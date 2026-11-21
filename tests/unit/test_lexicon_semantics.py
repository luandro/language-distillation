"""Unit tests for Pivot-Side Grammatical Valence & Semantic Domain Induction (WP 1.2)."""

from langpipe.lexicon.semantics import (
    GrammaticalValence,
    NounInalienability,
    PivotSemanticsClassifier,
    SemanticDomain,
    enrich_dictionary_with_semantics,
)


def test_valence_induction():
    classifier = PivotSemanticsClassifier()

    # Intransitive motion/posture/state verbs
    vi_entry = {"headword": "ka", "pos": "verb", "glosses_por": ["ir", "caminhar"]}
    vi_res = classifier.classify_entry(vi_entry)
    assert vi_res.valence == GrammaticalValence.INTRANSITIVE

    vi_arrive = {"headword": "nuku", "pos": "verb", "glosses_por": ["chegar"]}
    assert classifier.classify_entry(vi_arrive).valence == GrammaticalValence.INTRANSITIVE

    # Transitive verbs
    vt_entry = {"headword": "pi", "pos": "verb", "glosses_por": ["comer"]}
    vt_res = classifier.classify_entry(vt_entry)
    assert vt_res.valence == GrammaticalValence.TRANSITIVE

    vt_kill = {"headword": "yamama", "pos": "verb", "glosses_por": ["matar"]}
    assert classifier.classify_entry(vt_kill).valence == GrammaticalValence.TRANSITIVE

    # Ditransitive verbs
    vd_entry = {"headword": "in", "pos": "verb", "glosses_por": ["dar", "entregar"]}
    vd_res = classifier.classify_entry(vd_entry)
    assert vd_res.valence == GrammaticalValence.DITRANSITIVE


def test_inalienability_induction():
    classifier = PivotSemanticsClassifier()

    # Body parts (inalienable)
    hand = {"headword": "meken", "pos": "noun", "glosses_por": ["mão"]}
    assert classifier.classify_entry(hand).inalienability == NounInalienability.INALIENABLE_BODY

    eye = {"headword": "vero", "pos": "noun", "glosses_por": ["olho"]}
    assert classifier.classify_entry(eye).inalienability == NounInalienability.INALIENABLE_BODY

    # Kinship (inalienable)
    child = {"headword": "vaki", "pos": "noun", "glosses_por": ["criança", "filho"]}
    assert classifier.classify_entry(child).inalienability == NounInalienability.INALIENABLE_KIN

    father = {"headword": "papa", "pos": "noun", "glosses_por": ["pai"]}
    assert classifier.classify_entry(father).inalienability == NounInalienability.INALIENABLE_KIN

    # Free goods / Artifacts (alienable)
    hammock = {"headword": "pani", "pos": "noun", "glosses_por": ["rede de dormir"]}
    assert classifier.classify_entry(hammock).inalienability == NounInalienability.ALIENABLE


def test_semantic_domains():
    classifier = PivotSemanticsClassifier()

    fish = {"headword": "yapa", "pos": "noun", "glosses_por": ["peixe"]}
    assert classifier.classify_entry(fish).primary_domain == SemanticDomain.FAUNA

    tree = {"headword": "iwi", "pos": "noun", "glosses_por": ["árvore", "madeira"]}
    assert classifier.classify_entry(tree).primary_domain == SemanticDomain.FLORA

    river = {"headword": "paru", "pos": "noun", "glosses_por": ["rio", "água"]}
    assert classifier.classify_entry(river).primary_domain == SemanticDomain.UNIVERSE_NATURE

    canoe = {"headword": "tamina", "pos": "noun", "glosses_por": ["canoa", "barco"]}
    assert classifier.classify_entry(canoe).primary_domain == SemanticDomain.ARTIFACTS_TOOLS

    two = {"headword": "ravweoki", "pos": "num", "glosses_por": ["dois"]}
    assert classifier.classify_entry(two).primary_domain == SemanticDomain.QUANTITY_STATE


def test_enrich_dictionary_with_semantics():
    raw_dict = {
        "language_code": "und",
        "lexicon": [
            {"headword": "vaki", "pos": "noun", "glosses_por": ["criança", "filho"]},
            {"headword": "pi", "pos": "verb", "glosses_por": ["comer"]},
            {"headword": "ka", "pos": "verb", "glosses_por": ["ir"]},
            {"headword": "yapa", "pos": "noun", "glosses_por": ["peixe"]},
        ],
    }

    enriched = enrich_dictionary_with_semantics(raw_dict)
    lex = enriched["lexicon"]

    vaki_e = next(e for e in lex if e["headword"] == "vaki")
    pi_e = next(e for e in lex if e["headword"] == "pi")
    ka_e = next(e for e in lex if e["headword"] == "ka")

    assert vaki_e["semantics"]["inalienability"] == "inalienable_kin"
    assert pi_e["semantics"]["valence"] == "transitive"
    assert ka_e["semantics"]["valence"] == "intransitive"

    stats = enriched["semantics_stats"]
    assert stats["valence_distribution"]["transitive"] == 1
    assert stats["valence_distribution"]["intransitive"] == 1
