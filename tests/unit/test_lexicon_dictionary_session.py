"""Unit tests for the DictionarySessionBuilder (dictionary session + print edition)."""

from __future__ import annotations

from langpipe.lexicon.dictionary.session import DictionarySessionBuilder, normalize_key
from tests.fixtures.artifacts import requires_built_lexicon


def _entry(headword: str, **overrides):
    base = {
        "headword": headword,
        "pos": "noun",
        "glosses_por": ["glosa"],
        "status": "supported",
        "provenance": "Costa (2002)",
        "audit": {
            "lexical_class": "lemma",
            "flags": [],
            "reasons": [],
            "related_entry": None,
            "use_scopes": ["grounding"],
        },
        "citations": [],
        "semantics": {
            "confidence": 0.8,
            "primary_domain": "general",
            "valence": "non_verbal",
            "inalienability": "not_applicable",
            "subdomains": [],
        },
        "example": "",
        "trans": "",
    }
    base.update(overrides)
    return base


def _citation(ref: str, target: str, reference: str, score: float = 1.5):
    return {
        "citation_id": f"cid-{ref}",
        "headword": "x",
        "matched_token": "x",
        "source_ref": ref,
        "target_text": target,
        "reference_text": reference,
        "score": score,
    }


# --- normalization ---------------------------------------------------------


def test_normalize_key_strips_accents_and_case():
    assert normalize_key("coração") == "coracao"
    assert normalize_key("CORACAO") == "coracao"
    assert normalize_key("ẽa") == "ea"


def test_search_key_is_normalized_but_headword_is_preserved():
    session = DictionarySessionBuilder().build([_entry("ẽa", glosses_por=["eu"])])
    entry = session["entries"][0]
    assert entry["headword"] == "ẽa"
    assert entry["search_key"] == "ea"


def test_search_key_collapses_normalized_variants():
    """'é' and 'e' share a search key; the display form must not change."""
    session = DictionarySessionBuilder().build([_entry("mẽvi"), _entry("mevi")])
    keys = [e["search_key"] for e in session["entries"]]
    assert keys == ["mevi", "mevi"]
    heads = [e["headword"] for e in session["entries"]]
    assert set(heads) == {"mẽvi", "mevi"}


# --- letter bucketing -----------------------------------------------------


def test_letter_bucket_uses_normalized_key_not_raw_char():
    """'á' must bucket under A, not under a separate 'Á' bucket."""
    session = DictionarySessionBuilder().build([_entry("árvore")])
    assert session["entries"][0]["letter"] == "A"
    assert [letter["letter"] for letter in session["letters"]] == ["A"]


def test_nasal_vowel_headwords_bucket_by_base_letter():
    session = DictionarySessionBuilder().build([_entry("ẽa"), _entry("õpo"), _entry("ártemis")])
    buckets = {e["headword"]: e["letter"] for e in session["entries"]}
    assert buckets["ẽa"] == "E"
    assert buckets["õpo"] == "O"
    assert buckets["ártemis"] == "A"


def test_letters_are_sorted_and_carry_counts():
    session = DictionarySessionBuilder().build([_entry("mama"), _entry("mimi"), _entry("papa")])
    assert session["letters"] == [
        {"letter": "M", "count": 2},
        {"letter": "P", "count": 1},
    ]


# --- ordering -------------------------------------------------------------


def test_entries_sorted_by_normalized_key():
    session = DictionarySessionBuilder().build([_entry("õpo"), _entry("aakase"), _entry("nukẽ")])
    assert [e["search_key"] for e in session["entries"]] == [
        "aakase",
        "nuke",
        "opo",
    ]


# --- evidence preservation ------------------------------------------------


def test_status_is_preserved_verbatim():
    session = DictionarySessionBuilder().build(
        [_entry("waka", status="validated"), _entry("mama", status="candidate")]
    )
    by_head = {e["headword"]: e["status"] for e in session["entries"]}
    assert by_head["waka"] == "validated"
    assert by_head["mama"] == "candidate"


def test_glosses_are_never_collapsed_into_one_string():
    session = DictionarySessionBuilder().build([_entry("waka", glosses_por=["água", "rio"])])
    assert session["entries"][0]["glosses"] == ["água", "rio"]


def test_examples_are_built_from_citations():
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "waka",
                citations=[
                    _citation("GEN 1:1", "waka yapa", "a água boa", 1.5),
                    _citation("ACT 9:12", "waka ura", "a água longe", 1.48),
                ],
            )
        ]
    )
    entry = session["entries"][0]
    assert entry["attestations"] == 2
    assert [ex["source_ref"] for ex in entry["examples"]] == ["GEN 1:1", "ACT 9:12"]
    assert entry["examples"][0]["target_text"] == "waka yapa"
    assert entry["examples"][0]["reference_text"] == "a água boa"
    assert entry["examples"][0]["score"] == 1.5


def test_entry_without_citations_has_no_examples():
    session = DictionarySessionBuilder().build([_entry("waka")])
    assert session["entries"][0]["examples"] == []
    assert session["entries"][0]["attestations"] == 0


def test_example_ignores_stale_top_level_example_field():
    """`example`/`trans` duplicate citations[0]; citations are the source of truth."""
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "waka",
                example="STALE",
                trans="STALE",
                citations=[_citation("GEN 1:1", "waka yapa", "a água boa")],
            )
        ]
    )
    assert session["entries"][0]["examples"][0]["target_text"] == "waka yapa"


def test_related_entry_is_carried_through():
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "berequiasnẽ",
                audit={
                    "lexical_class": "inflected_form",
                    "flags": [],
                    "reasons": [],
                    "related_entry": "berequias",
                    "use_scopes": [],
                },
            )
        ]
    )
    assert session["entries"][0]["related_entry"] == "berequias"
    assert session["entries"][0]["lexical_class"] == "inflected_form"


def test_audit_flags_and_reasons_are_carried_through():
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "x",
                audit={
                    "lexical_class": "proper_noun",
                    "flags": ["gloss_is_name"],
                    "reasons": ["gloss looks like a name"],
                    "related_entry": None,
                    "use_scopes": [],
                },
            )
        ]
    )
    assert session["entries"][0]["flags"] == ["gloss_is_name"]
    assert session["entries"][0]["reasons"] == ["gloss looks like a name"]


# --- facets and stats -----------------------------------------------------


def test_facets_count_matches_entries():
    session = DictionarySessionBuilder().build(
        [
            _entry("a", pos="noun", status="validated"),
            _entry("b", pos="noun", status="supported"),
            _entry("c", pos="verb", status="supported"),
        ]
    )
    pos = {f["value"]: f["count"] for f in session["facets"]["pos"]}
    status = {f["value"]: f["count"] for f in session["facets"]["status"]}
    assert pos == {"noun": 2, "verb": 1}
    assert status == {"validated": 1, "supported": 2}
    assert sum(pos.values()) == len(session["entries"])


def test_domain_facet_defaults_to_general():
    session = DictionarySessionBuilder().build([_entry("a")])
    assert session["entries"][0]["domain"] == "general"


def test_meta_reports_totals():
    session = DictionarySessionBuilder(
        target_lang="mzr", target_name="Marúbo", contact_lang="por"
    ).build([_entry("a"), _entry("b")])
    assert session["meta"]["target_lang"] == "mzr"
    assert session["meta"]["target_name"] == "Marúbo"
    assert session["meta"]["total_entries"] == 2
    # 'a' and 'b' are two different letter buckets.
    assert session["meta"]["total_letters"] == 2


# --- bibliography ---------------------------------------------------------


def test_bibliography_deduplicates_works_and_orders_by_use():
    session = DictionarySessionBuilder().build(
        [
            _entry("a", provenance="Costa (2002); ex: a x"),
            _entry("b", provenance="Costa (2002); ex: b x"),
            _entry("c", provenance="Cesarino (2013); ex: c x"),
            _entry("d", provenance="Costa (1993, 2000) [ASJP]; ex: d x"),
        ]
    )
    labels = [b["label"] for b in session["bibliography"]]
    assert "Costa (2002)" in labels
    assert "Costa (1993, 2000)" in labels
    assert "Cesarino (2013)" in labels
    assert len(labels) == len(set(labels)), "bibliography must be de-duplicated"
    # most-cited work first
    assert labels[0] == "Costa (2002)"


def test_bibliography_ignores_corpus_alignment_provenance():
    session = DictionarySessionBuilder().build(
        [_entry("a", provenance="Corpus alignment (ACT 21:25, co-oc=3, dice=1.00)")]
    )
    assert session["bibliography"] == []


def test_bibliography_cuts_example_tail_before_splitting():
    """The example tail contains its own semicolons; it must not leak into the works."""
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "kiya",
                provenance="Costa (2000b, 2002); ex: kiya-rantsha (avião; lit. barco longo)",
            ),
            _entry(
                "shava",
                provenance=(
                    "Costa (1992, 2002); Cesarino (2013); "
                    "ex: na-shava-ma (ontem; lit. este dia não)"
                ),
            ),
        ]
    )
    labels = sorted(b["label"] for b in session["bibliography"])
    assert labels == ["Cesarino (2013)", "Costa (1992, 2002)", "Costa (2000b, 2002)"]
    for spurious in ("barco longo", "este dia", "kiya-rantsha", "avião"):
        assert not any(spurious in label for label in labels), labels


def test_bibliography_survives_unparseable_provenance():
    session = DictionarySessionBuilder().build([_entry("a", provenance="USFM GEN")])
    assert len(session["bibliography"]) == 1
    assert session["bibliography"][0]["author"] == "USFM GEN"


# --- optional sections ----------------------------------------------------


def test_morphology_and_parallel_sentences_pass_through():
    morph = [{"morpheme": "-n", "gloss": "ERG", "function": "Marcador ergativo"}]
    parallel = [{"marubo": "x", "igt_gloss": "y", "portugues": "z", "source": "GEN 1:1"}]
    session = DictionarySessionBuilder().build(
        [_entry("a")], morphology=morph, parallel_sentences=parallel
    )
    assert session["morphology"] == morph
    assert session["parallel_sentences"] == parallel


def test_build_is_deterministic():
    entries = [_entry("õpo"), _entry("aakase"), _entry("nukẽ")]
    first = DictionarySessionBuilder().build(entries)
    second = DictionarySessionBuilder().build(entries)
    assert first == second


def test_build_ignores_entries_without_headword():
    session = DictionarySessionBuilder().build(
        [_entry("a"), {"pos": "noun", "glosses_por": ["orphan"]}]
    )
    assert len(session["entries"]) == 1


# --- inflected forms -------------------------------------------------------


def _form(surface: str, base: str, clitic: str = "", **overrides):
    """An `inflected_form` row as the audit step writes it."""
    base_row = _entry(
        surface,
        status="supported",
        audit={
            "lexical_class": "inflected_form",
            "flags": [],
            "reasons": [f"Forma infletida: '{base}' + clítico '-{clitic}'."],
            "related_entry": base,
            "use_scopes": [],
            "signals": [
                {
                    "rule_id": "name_plus_clitic",
                    "source": "rule",
                    "value": "inflected_form",
                    "detail": {"base_name": base, "clitic": clitic},
                }
            ]
            if clitic
            else [],
        },
    )
    base_row.update(overrides)
    return base_row


def test_form_is_attached_to_the_entry_that_owns_its_base():
    session = DictionarySessionBuilder().build(
        [_entry("berequias")], forms_source=[_form("berequiasnẽ", "berequias", "nẽ")]
    )
    entry = session["entries"][0]
    assert [form["surface"] for form in entry["forms"]] == ["berequiasnẽ"]
    form = entry["forms"][0]
    assert form["search_key"] == "berequiasne"
    assert form["clitic"] == "nẽ"
    assert form["pos"] == "noun"


def test_attached_form_is_never_published_as_an_entry():
    """One row per lemma: the body stays at one entry, the form rides on it."""
    session = DictionarySessionBuilder().build(
        [_entry("berequias")], forms_source=[_form("berequiasnẽ", "berequias", "nẽ")]
    )
    assert len(session["entries"]) == 1
    assert session["meta"]["total_entries"] == 1
    assert session["form_index"][0]["lemma"] == "berequias"


def test_entry_without_forms_still_exposes_an_empty_list():
    session = DictionarySessionBuilder().build([_entry("waka")])
    assert session["entries"][0]["forms"] == []


def test_form_is_attached_to_every_homograph():
    """Two entries sharing a normalized headword both own the form."""
    session = DictionarySessionBuilder().build(
        [_entry("mẽvi"), _entry("mevi")],
        forms_source=[_form("mevipa", "mevi", "pa")],
    )
    assert [len(entry["forms"]) for entry in session["entries"]] == [1, 1]


def test_form_without_a_published_base_goes_to_the_session_index_only():
    session = DictionarySessionBuilder().build(
        [_entry("waka")], forms_source=[_form("berequiasnẽ", "berequias", "nẽ")]
    )
    assert [entry["headword"] for entry in session["entries"]] == ["waka"]
    assert session["meta"]["total_forms"] == 1
    orphan = session["form_index"][0]
    assert orphan["surface"] == "berequiasnẽ"
    assert orphan["base"] == "berequias"
    assert orphan["base_search_key"] == "berequias"
    assert orphan["lemma"] is None
    assert orphan["clitic"] == "nẽ"


def test_form_base_falls_back_to_the_audit_signal_detail():
    """`related_entry` may be empty; the recorded `base_name` still names the base."""
    row = _form("mevipa", "mevi", "pa")
    row["audit"]["related_entry"] = None
    session = DictionarySessionBuilder().build([_entry("mevi")], forms_source=[row])
    assert [form["surface"] for form in session["entries"][0]["forms"]] == ["mevipa"]


def test_forms_source_defaults_to_the_entries_argument():
    """A caller that passes a mixed list keeps working unchanged."""
    session = DictionarySessionBuilder().build(
        [_entry("berequias"), _form("berequiasnẽ", "berequias", "nẽ")]
    )
    # The form row is also an entry here (default behaviour), but it is attached
    # to its base rather than dropped.
    by_head = {entry["headword"]: entry for entry in session["entries"]}
    assert [form["surface"] for form in by_head["berequias"]["forms"]] == ["berequiasnẽ"]


def test_lemmas_are_not_treated_as_forms():
    session = DictionarySessionBuilder().build(
        [_entry("waka")], forms_source=[_entry("waka"), _entry("mama")]
    )
    assert session["form_index"] == []


@requires_built_lexicon
def test_real_lexicon_publishes_lemmas_only_and_indexes_orphan_forms():
    """Regression pin on the shipped artifact: the forms' bases are not lemmas.

    Measured 2026-10-22: the 63 `inflected_form` rows name Portuguese/onomastic
    bases (`berequias`, `jesus`, `sara`…) that the clean view does not publish,
    so none attaches. They stay reachable through `form_index` and must not
    inflate the 892 published entries.
    """
    import json
    from pathlib import Path

    from langpipe.lexicon.audit.view import LexiconView

    path = Path(__file__).resolve().parents[2] / "exports" / "mzr" / "dictionary.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    entries = LexiconView(raw, view="clean").entries
    session = DictionarySessionBuilder().build(entries, forms_source=raw["lexicon"])

    assert len(session["entries"]) == 892
    assert session["meta"]["total_entries"] == 892
    assert session["meta"]["total_forms"] == 63
    assert len(session["form_index"]) == 63
    assert sum(len(entry["forms"]) for entry in session["entries"]) == 0
    assert all(form["lemma"] is None for form in session["form_index"])
    assert all(form["base"] for form in session["form_index"])
    published = {entry["headword"] for entry in session["entries"]}
    assert not published & {form["surface"] for form in session["form_index"]}


# --- validation basis ------------------------------------------------------


def test_basis_source_assertion_when_only_a_work_is_recorded():
    session = DictionarySessionBuilder().build(
        [_entry("waka", status="validated", provenance="Costa (2002)")]
    )
    basis = session["entries"][0]["validation_basis"]
    assert basis["kind"] == "source_assertion"
    assert basis["sources"] == ["Costa (2002)"]
    assert basis["corpus_attestations"] == 0


def test_basis_source_and_corpus_when_both_are_recorded():
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "waka",
                status="validated",
                provenance="Costa (2002)",
                citations=[_citation("GEN 1:1", "waka yapa", "a água boa")],
            )
        ]
    )
    basis = session["entries"][0]["validation_basis"]
    assert basis["kind"] == "source_and_corpus"
    assert basis["corpus_attestations"] == 1


def test_basis_corpus_only_when_no_work_is_named():
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "waka",
                status="supported",
                provenance="Corpus alignment (GEN 1:1, co-oc=3, dice=1.00)",
                citations=[_citation("GEN 1:1", "waka yapa", "a água boa")],
            )
        ]
    )
    basis = session["entries"][0]["validation_basis"]
    assert basis["kind"] == "corpus_only"
    assert basis["sources"] == []


def test_basis_unrecorded_is_never_guessed():
    session = DictionarySessionBuilder().build(
        [_entry("waka", status="validated", provenance="", citations=[])]
    )
    basis = session["entries"][0]["validation_basis"]
    assert basis["kind"] == "unrecorded"
    assert basis["sources"] == []


@requires_built_lexicon
def test_real_lexicon_validated_entries_describe_an_imported_assertion():
    """144 validated entries, but 108 of them name a work and cite no corpus line.

    That asymmetry is why the reader label must not say "gold standard": the
    artifact records an imported assertion, not a reviewed derivation.
    """
    import json
    from collections import Counter
    from pathlib import Path

    from langpipe.lexicon.audit.view import LexiconView

    path = Path(__file__).resolve().parents[2] / "exports" / "mzr" / "dictionary.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    entries = LexiconView(raw, view="clean").entries
    session = DictionarySessionBuilder().build(entries, forms_source=raw["lexicon"])

    validated = [e for e in session["entries"] if e["status"] == "validated"]
    assert len(validated) == 144
    kinds = Counter(e["validation_basis"]["kind"] for e in validated)
    assert kinds == {"source_assertion": 108, "source_and_corpus": 36}
    assert all(e["validation_basis"]["sources"] for e in validated)
    # Every published entry carries a basis; none is silently blank.
    assert all(e["validation_basis"]["kind"] for e in session["entries"])
