"""WP4.6 unit tests: wordlist source adapter.

The adapter is pure: bytes in, candidate hypotheses out. Governance (registered `Source`,
sha256 verification, `Operation.INGEST` / `Operation.EXTRACT` checks) is the job of the
governed entry point in `langpipe.ingest.wordlist`, exercised in
`tests/service/test_wordlist_ingest.py`; these tests never touch a repository, so nothing
here can leak restricted material beyond the assertion surfaces below.
"""

import logging
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LifecycleStatus, LineageKind
from langpipe.domain.errors import ExtractionFailed
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.lexical import Lexeme, Sense
from langpipe.domain.models.observation import Form
from langpipe.lexicon.adapters.wordlist import (
    WordlistAdapter,
    WordlistFormatError,
    parse_wordlist,
)
from langpipe.lexicon.base import LexicalInductionInput, LexicalInductionOutput
from langpipe.lexicon.registry import (
    UnsupportedMethod,
    get_lexical_inducer,
    lexical_induction_methods,
)
from langpipe.lexicon.scoring import LexicalScorePolicy
from langpipe.storage.objects.local import LocalContentStore

FIXTURE_SOURCES = Path(__file__).parents[1] / "golden" / "fixture" / "sources"
WORDLIST = FIXTURE_SOURCES / "03-wordlist" / "wordlist.tsv"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
RUN_ID = new_id(IdPrefix.RUN)
SOURCE_ID = new_id(IdPrefix.SOURCE)
SOURCE_OBJECT_ID = new_id(IdPrefix.SOURCE_OBJECT)
TARGET_LANGUAGE = "qaa"
CONTACT_LANGUAGE = "por"

# Golden `03-wordlist/wordlist.tsv`: two-column `kanu` row, `mabi` with two
# semicolon-delimited glosses, `rumi` carrying a domain note.
GOLDEN = (
    "qaa\tpor\tnote\n"
    "kanu\thomem\n"
    "mabi\tcanoa; tronco\ttwo candidate senses\n"
    "rumi\tpajé\tdomain-specific (ritual/traditional)\n"
).encode()


class Clock:
    """Deterministic clock so identifiers and `created_at` never depend on wall time."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return NOW


def _ids(counter: list[int]):
    """Sequential-but-distinct id factory: `lex_1`, `lex_2`, ... prefixed per entity type."""

    def factory(prefix: IdPrefix) -> str:
        counter[0] += 1
        return f"{prefix.value}_{counter[0]:026d}"

    return factory


def _form(text: str, *, language: str = TARGET_LANGUAGE) -> Form:
    return Form(
        id=new_id(IdPrefix.FORM),
        language=language,
        orthography_profile=f"{language}-nfc@1.0",
        text=text,
        run_id=new_id(IdPrefix.RUN),
        created_at=NOW,
    )


def _input(
    data: bytes = GOLDEN,
    *,
    source_id: str = SOURCE_ID,
    source_object_id: str = SOURCE_OBJECT_ID,
    run_id: str = RUN_ID,
    target_language: str = TARGET_LANGUAGE,
    contact_language: str = CONTACT_LANGUAGE,
    target_forms: Mapping[str, Form] | None = None,
    independence_group: str | None = None,
    policy: LexicalScorePolicy | None = None,
) -> LexicalInductionInput:
    return LexicalInductionInput(
        data=data,
        source_id=source_id,
        source_object_id=source_object_id,
        run_id=run_id,
        target_language=target_language,
        contact_language=contact_language,
        policy=policy,
        independence_group=independence_group,
        target_forms=target_forms,
    )


def _induce(
    data: bytes = GOLDEN,
    *,
    target_forms: Mapping[str, Form] | None = None,
    independence_group: str | None = None,
    target_language: str = TARGET_LANGUAGE,
    contact_language: str = CONTACT_LANGUAGE,
) -> tuple[WordlistAdapter, LexicalInductionOutput]:
    counter = [0]
    adapter = WordlistAdapter(new_id=_ids(counter), clock=Clock())
    output = adapter.induce(
        _input(
            data,
            target_forms=target_forms,
            independence_group=independence_group,
            target_language=target_language,
            contact_language=contact_language,
        )
    )
    return adapter, output


def _lexeme_of(output: LexicalInductionOutput, headword: str) -> Lexeme:
    lexeme_ids = {
        str(item.claim.get("headword")): item.target_id
        for item in output.evidence_items
        if item.claim is not None
    }
    target_id = lexeme_ids.get(headword)
    for lexeme in output.lexemes:
        if lexeme.id == target_id:
            return lexeme
    raise AssertionError(f"no lexeme for headword {headword!r}")


def _glosses(output: LexicalInductionOutput) -> list[str]:
    return sorted(gloss for sense in output.senses for gloss in sense.glosses[CONTACT_LANGUAGE])


# --- parsing ----------------------------------------------------------------------


def test_parses_the_golden_wordlist_fixture() -> None:
    entries = parse_wordlist(WORDLIST.read_bytes(), "sobj_x")

    assert [(e.headword, e.glosses, e.note) for e in entries] == [
        ("kanu", ("homem",), None),
        ("mabi", ("canoa", "tronco"), "two candidate senses"),
        ("rumi", ("pajé",), "domain-specific (ritual/traditional)"),
    ]


def test_header_columns_are_resolved_by_language_tag() -> None:
    entries = parse_wordlist(GOLDEN, "sobj_x")

    # `qaa` is the target column and `por` the contact column; `note` is metadata.
    assert all(entry.contact_language == CONTACT_LANGUAGE for entry in entries)


def test_two_column_wordlist_without_notes_parses() -> None:
    data = b"qaa\tpor\nkanu\thomem\n"

    assert [(e.headword, e.glosses, e.note) for e in parse_wordlist(data, "sobj_x")] == [
        ("kanu", ("homem",), None)
    ]


def test_header_falls_back_to_column_position_without_language_tags() -> None:
    data = b"form\ttranslation\tremarks\nkanu\thomem\t\n"

    entries = parse_wordlist(data, "sobj_x", target_language=TARGET_LANGUAGE)

    assert [(e.headword, e.glosses, e.note) for e in entries] == [("kanu", ("homem",), None)]


def test_normal_mzr_header_resolves_the_target_column() -> None:
    # A real Marúbo wordlist header: `mzr` is the target column and `por` the gloss column.
    data = b"mzr\tpor\nkanu\thomem\n"

    entries = parse_wordlist(data, "sobj_x", target_language="mzr")

    assert [(e.headword, e.glosses) for e in entries] == [("kanu", ("homem",))]


def test_reversed_header_columns_still_resolve_by_language_tag() -> None:
    # Column order is not a contract: the language tag decides, so `por` first resolves to
    # the gloss column and `mzr` to the headword column.
    data = b"por\tmzr\nhomem\tkanu\n"

    entries = parse_wordlist(data, "sobj_x", target_language="mzr")

    assert [(e.headword, e.glosses) for e in entries] == [("kanu", ("homem",))]


def test_non_portuguese_gloss_column_names_its_own_language() -> None:
    # The gloss column's language tag is the gloss language, never a fixed `por`.
    entries = parse_wordlist(b"qaa\tspa\nkanu\thombre\n", "sobj_x", target_language="qaa")

    assert [e.contact_language for e in entries] == ["spa"]


def test_a_declared_contact_headword_column_is_refused_not_relabelled() -> None:
    # `por` declares column 0 Portuguese and `note` declares column 1 a note column, so no
    # column can carry target-language headwords: the header is refused instead of reading
    # `homem` as a target headword with `remarks` as its Portuguese gloss (Invariants 8 and
    # 9; ADR-0013 §1). Candidate status would not make the misattribution acceptable.
    with pytest.raises(WordlistFormatError) as failure:
        parse_wordlist(
            b"por\tnote\nhomem\tremarks\n",
            "sobj_x",
            target_language="mzr",
            contact_language="por",
        )

    assert failure.value.code == WordlistFormatError.HEADER_INVALID


def test_a_metadata_column_is_never_relabelled_as_the_gloss_column() -> None:
    # Positional fallback may only land on genuinely unlabelled columns: `note` declares
    # its column metadata, so this header names a headword column but no gloss column at
    # all, and a remark must never become a translation.
    with pytest.raises(WordlistFormatError) as failure:
        parse_wordlist(
            b"headword\tnote\nkanu\tremarks\n",
            "sobj_x",
            target_language="qaa",
            contact_language="por",
        )

    assert failure.value.code == WordlistFormatError.HEADER_INVALID


def test_a_target_column_with_only_a_note_column_names_no_gloss() -> None:
    # A header naming the target column and a note column declares no translation column,
    # so there is no gloss language to read the second column in.
    with pytest.raises(WordlistFormatError) as failure:
        parse_wordlist(
            b"mzr\tnote\nkanu\tremarks\n",
            "sobj_x",
            target_language="mzr",
            contact_language="por",
        )

    assert failure.value.code == WordlistFormatError.GLOSS_LANGUAGE_INVALID


def test_an_unlabelled_column_beside_a_declared_language_column_still_parses() -> None:
    # `por` declares the gloss column; the one genuinely unlabelled column takes the
    # headword role, so the positional fallback survives beside a declared column without
    # ever relabelling the declared one.
    data = b"por\tmzr headword\nhomem\tkanu\n"

    entries = parse_wordlist(data, "sobj_x", target_language="mzr", contact_language="por")

    assert [(e.headword, e.glosses, e.contact_language) for e in entries] == [
        ("kanu", ("homem",), "por")
    ]


def test_invalid_utf8_is_rejected_without_echoing_bytes() -> None:
    with pytest.raises(ExtractionFailed) as failure:
        parse_wordlist(b"kanu\thomem\n" + b"\xff\xfe", "sobj_x")

    assert failure.value.code == "decode_error"
    assert "kanu" not in str(failure.value)


def test_empty_input_is_rejected() -> None:
    with pytest.raises(WordlistFormatError) as failure:
        parse_wordlist(b"", "sobj_x")

    assert failure.value.code == "wordlist_header_invalid"
    assert isinstance(failure.value, ValueError)


def test_single_column_header_is_rejected() -> None:
    # One column resolves to neither a headword/gloss pair nor a language split, so no
    # role can be assigned.
    with pytest.raises(WordlistFormatError) as failure:
        parse_wordlist(b"qaa\nkanu\n", "sobj_x")

    assert failure.value.code == "wordlist_header_invalid"


def test_ragged_short_rows_are_skipped_not_fatal() -> None:
    data = b"qaa\tpor\tnote\nkanu\nmabi\tcanoa\n"

    entries = parse_wordlist(data, "sobj_x")

    assert [e.headword for e in entries] == ["mabi"]


def test_ragged_long_rows_are_skipped_not_fatal() -> None:
    data = b"qaa\tpor\tnote\nkanu\thomem\textra\tcolumns\nmabi\tcanoa\n"

    entries = parse_wordlist(data, "sobj_x")

    assert [e.headword for e in entries] == ["mabi"]


def test_blank_and_whitespace_lines_are_skipped() -> None:
    data = b"qaa\tpor\tnote\n\n   \nkanu\thomem\n"

    assert [e.headword for e in parse_wordlist(data, "sobj_x")] == ["kanu"]


def test_empty_headword_or_gloss_cell_skips_the_row() -> None:
    data = b"qaa\tpor\tnote\nkanu\t\n\thomem\nmabi\tcanoa\n"

    assert [e.headword for e in parse_wordlist(data, "sobj_x")] == ["mabi"]


def test_semicolon_glosses_split_into_stripped_list() -> None:
    data = b"qaa\tpor\tnote\nmabi\tcanoa ; tronco\n"

    assert parse_wordlist(data, "sobj_x")[0].glosses == ("canoa", "tronco")


def test_empty_gloss_segments_are_dropped() -> None:
    data = b"qaa\tpor\tnote\nmabi\tcanoa;; ;\n"

    assert parse_wordlist(data, "sobj_x")[0].glosses == ("canoa",)


def test_domain_note_is_extracted_from_parentheses() -> None:
    data = "qaa\tpor\tnote\nrumi\tpajé\tdomain-specific (ritual/traditional)\n".encode()

    assert parse_wordlist(data, "sobj_x")[0].domain == "ritual/traditional"


def test_domain_column_is_used_when_present() -> None:
    data = "qaa\tpor\tdomain\nrumi\tpajé\tritual/traditional\n".encode()

    assert parse_wordlist(data, "sobj_x")[0].domain == "ritual/traditional"


def test_bare_slash_note_is_a_domain_tag() -> None:
    data = "qaa\tpor\tnote\nrumi\tpajé\tritual/tradicional\n".encode()

    assert parse_wordlist(data, "sobj_x")[0].domain == "ritual/tradicional"


def test_pos_note_is_not_a_domain() -> None:
    data = b"qaa\tpor\tnote\nmabi\tcanoa\tn.\n"

    assert parse_wordlist(data, "sobj_x")[0].domain is None


def test_note_without_domain_marker_leaves_domain_unset() -> None:
    data = b"qaa\tpor\tnote\nmabi\tcanoa\ttwo candidate senses\n"

    assert parse_wordlist(data, "sobj_x")[0].domain is None


def test_explicit_domain_column_name_domain_is_metadata() -> None:
    data = b"qaa\tpor\tpos\tnote\nmabi\tcanoa\tn.\ttwo candidate senses\n"

    entry = parse_wordlist(data, "sobj_x")[0]

    assert entry.note == "two candidate senses"
    assert entry.domain is None


# --- induction --------------------------------------------------------------------


def test_kanu_yields_one_lexeme_and_one_sense() -> None:
    _, output = _induce()

    lexeme = _lexeme_of(output, "kanu")
    senses = [sense for sense in output.senses if sense.lexeme_id == lexeme.id]

    assert [gloss for sense in senses for gloss in sense.glosses[CONTACT_LANGUAGE]] == ["homem"]


def test_mabi_yields_one_lexeme_with_two_senses() -> None:
    # Phenomenon 2: `canoa; tronco` is one lexeme with two distinct meaning hypotheses.
    _, output = _induce()

    lexeme = _lexeme_of(output, "mabi")
    senses = [sense for sense in output.senses if sense.lexeme_id == lexeme.id]

    assert len(senses) == 2
    assert sorted(gloss for sense in senses for gloss in sense.glosses[CONTACT_LANGUAGE]) == [
        "canoa",
        "tronco",
    ]


def test_each_sense_is_one_gloss() -> None:
    _, output = _induce()

    assert all(len(sense.glosses[CONTACT_LANGUAGE]) == 1 for sense in output.senses)


def test_rumi_sense_carries_the_domain_tag() -> None:
    # Phenomenon 9: the register/domain note survives as a `Sense` domain tag.
    _, output = _induce()

    lexeme = _lexeme_of(output, "rumi")
    sense = next(s for s in output.senses if s.lexeme_id == lexeme.id)

    assert sense.domain == "ritual/traditional"


def test_entry_without_domain_has_no_domain_tag() -> None:
    _, output = _induce()

    lexeme = _lexeme_of(output, "mabi")
    senses = [s for s in output.senses if s.lexeme_id == lexeme.id]

    assert all(sense.domain is None for sense in senses)


def test_lexeme_uses_the_target_language_and_run() -> None:
    _, output = _induce()

    lexeme = output.lexemes[0]

    assert lexeme.language == TARGET_LANGUAGE
    assert lexeme.run_id == RUN_ID
    assert lexeme.status is LifecycleStatus.CANDIDATE


def test_lexeme_lemma_form_is_linked_when_a_form_is_pinned() -> None:
    forms = {"kanu": _form("kanu")}
    _, output = _induce(target_forms=forms)

    lexeme = _lexeme_of(output, "kanu")

    assert lexeme.lemma_form_id == forms["kanu"].id
    links = [link for link in output.form_links if link.lexeme_id == lexeme.id]
    assert len(links) == 1
    assert links[0].form_id == forms["kanu"].id
    assert links[0].role == "primary_lemma"
    assert links[0].run_id == RUN_ID


def test_lexeme_without_pinned_form_has_no_lemma_and_no_link() -> None:
    _, output = _induce()

    assert all(lexeme.lemma_form_id is None for lexeme in output.lexemes)
    assert output.form_links == []


def test_a_form_is_never_linked_twice_to_the_same_lexeme() -> None:
    data = b"qaa\tpor\nkanu\thomem\nkanu\thomem\n"
    forms = {"kanu": _form("kanu")}
    _, output = _induce(data, target_forms=forms)

    assert len(output.form_links) == 1


def test_contact_glosses_are_never_target_language_forms() -> None:
    # Invariants 8 & 9: a Portuguese surface is a gloss on a `Sense`, never a
    # target-language `Lexeme` or a lemma of one, however the caller resolves forms.
    forms = {"kanu": _form("kanu"), "homem": _form("homem", language=CONTACT_LANGUAGE)}
    _, output = _induce(target_forms=forms)

    linked = {link.form_id for link in output.form_links}
    lemmas = {lexeme.lemma_form_id for lexeme in output.lexemes if lexeme.lemma_form_id}
    contact_form_ids = {forms["homem"].id}

    assert not any(lexeme.language == CONTACT_LANGUAGE for lexeme in output.lexemes)
    assert not linked & contact_form_ids
    assert not lemmas & contact_form_ids
    assert linked == {forms["kanu"].id}
    # The contact surface is preserved as a meaning hypothesis on the sense.
    assert "homem" in {
        gloss for sense in output.senses for gloss in sense.glosses[CONTACT_LANGUAGE]
    }


def test_normal_mzr_wordlist_induces_the_requested_language() -> None:
    # A normal `mzr`/`por` header must resolve the target column by tag, not by position
    # fallback, so the induced lexemes are in the requested target language.
    data = b"mzr\tpor\nkanu\thomem\n"

    _, output = _induce(data, target_language="mzr")

    assert [lexeme.language for lexeme in output.lexemes] == ["mzr"]
    assert output.senses[0].glosses == {CONTACT_LANGUAGE: ["homem"]}


def test_reversed_columns_induce_the_requested_language() -> None:
    data = b"por\tmzr\nhomem\tkanu\n"

    _, output = _induce(data, target_language="mzr")

    assert [lexeme.language for lexeme in output.lexemes] == ["mzr"]
    assert output.senses[0].glosses == {CONTACT_LANGUAGE: ["homem"]}


def test_an_explicit_gloss_column_language_is_not_relabelled() -> None:
    # An explicitly Spanish gloss column stays Spanish: the requested contact language is a
    # request, and when the header names a different translation language the adapter
    # refuses instead of relabelling the column (Invariants 8 & 9).
    data = b"qaa\tspa\nkanu\thombre\n"

    with pytest.raises(WordlistFormatError) as failure:
        _induce(data)

    assert failure.value.code == WordlistFormatError.GLOSS_LANGUAGE_INVALID


def test_a_requested_spanish_translation_keeps_the_header_language() -> None:
    # The same wordlist read as Spanish is not refused: the request agrees with the header.
    data = b"qaa\tspa\nkanu\thombre\n"

    _, output = _induce(data, contact_language="spa")

    assert output.senses[0].glosses == {"spa": ["hombre"]}


def test_a_gloss_language_disagreeing_with_the_request_is_rejected() -> None:
    # A header whose only gloss column is neither the requested contact language nor the
    # target language cannot be read as that translation: refuse, never silently relabel.
    data = b"qaa\teng\nkanu\tman\n"

    with pytest.raises(WordlistFormatError) as failure:
        _induce(data)

    assert failure.value.code == WordlistFormatError.GLOSS_LANGUAGE_INVALID


def test_a_target_tag_in_the_gloss_column_is_rejected() -> None:
    # Two target-language columns name no gloss language at all.
    data = b"qaa\tqaa\nkanu\tkanu\n"

    with pytest.raises(WordlistFormatError) as failure:
        _induce(data, target_language="qaa")

    assert failure.value.code == WordlistFormatError.GLOSS_LANGUAGE_INVALID


def test_a_same_spelling_contact_language_form_is_rejected_as_a_lemma_pin() -> None:
    # A same-key Form is an explicit pin. Its language must match the target language;
    # silently ignoring it would conceal a caller's inconsistent pin (ADR-0013 §1).
    data = b"qaa\tpor\nkanu\thomem\n"
    forms = {"kanu": _form("kanu", language=CONTACT_LANGUAGE)}

    with pytest.raises(WordlistFormatError) as failure:
        _induce(data, target_forms=forms)

    assert failure.value.code == WordlistFormatError.LEMMA_PIN_INVALID


def test_a_pin_whose_text_is_not_the_headword_is_rejected() -> None:
    # A pinned form is a lemma only for the headword it spells: `mabi` cannot be the lemma
    # of `kanu`, however the caller's mapping is keyed.
    data = b"qaa\tpor\nkanu\thomem\n"
    forms = {"kanu": _form("mabi")}

    with pytest.raises(WordlistFormatError) as failure:
        _induce(data, target_forms=forms)

    assert failure.value.code == WordlistFormatError.LEMMA_PIN_INVALID


def test_a_pin_matching_the_headword_under_normalization_is_accepted() -> None:
    # The established normalization/profile contract: a form whose text is the headword
    # under NFC is the same lexical form, and is pinned as the lemma.
    headword = unicodedata.normalize("NFC", "kanu\u0301")
    data = f"qaa\tpor\n{headword}\thomem\n".encode()
    forms = {headword: _form(headword)}

    _, output = _induce(data, target_forms=forms)

    assert output.form_links
    assert output.lexemes[0].lemma_form_id == forms[headword].id


def test_a_missing_pin_leaves_the_lemma_unset() -> None:
    # The caller resolves forms; a headword without a pin stays a hypothesis with no lemma.
    data = b"qaa\tpor\nkanu\thomem\n"

    _, output = _induce(data)

    assert all(lexeme.lemma_form_id is None for lexeme in output.lexemes)
    assert output.form_links == []


def test_golden_fixture_file_induces_the_full_vocabulary() -> None:
    _, output = _induce(WORDLIST.read_bytes())

    assert len(output.lexemes) == 3
    assert len(output.senses) == 4


# --- evidence ---------------------------------------------------------------------


def test_evidence_items_are_dictionary_assertions_with_source_attribution() -> None:
    _, output = _induce()

    assert output.evidence_items
    for item in output.evidence_items:
        assert item.kind is EvidenceKind.DICTIONARY_ASSERTION
        assert item.polarity is EvidencePolarity.SUPPORTS
        assert item.source_id == SOURCE_ID
        assert item.run_id == RUN_ID


def test_each_gloss_gets_its_own_evidence_item() -> None:
    _, output = _induce()

    claims = sorted(
        (str(item.claim.get("headword")), str(item.claim.get("gloss")))
        for item in output.evidence_items
    )
    assert claims == [
        ("kanu", "homem"),
        ("mabi", "canoa"),
        ("mabi", "tronco"),
        ("rumi", "pajé"),
    ]


def test_evidence_strength_is_full_dictionary_support() -> None:
    _, output = _induce()

    assert all(item.strength == {"dictionary_support": 1.0} for item in output.evidence_items)


def test_evidence_claim_carries_headword_gloss_and_note() -> None:
    _, output = _induce()

    rumi = next(
        item
        for item in output.evidence_items
        if item.claim is not None and item.claim.get("headword") == "rumi"
    )
    assert rumi.claim == {
        "headword": "rumi",
        "gloss": "pajé",
        "note": "domain-specific (ritual/traditional)",
    }
    # The domain tag is a field on the item, not a claim key: the policy reads it directly
    # for domain stability.
    assert rumi.domain == "ritual/traditional"
    assert rumi.target_id  # the lexeme it supports


def test_evidence_note_is_none_when_the_row_has_no_note() -> None:
    data = b"qaa\tpor\tnote\nkanu\thomem\n"
    _, output = _induce(data)

    kanu = output.evidence_items[0]

    assert kanu.claim is not None
    assert kanu.claim["note"] is None


def test_independence_group_defaults_to_the_source() -> None:
    _, output = _induce()

    assert all(item.independence_group == SOURCE_ID for item in output.evidence_items)


def test_explicit_independence_group_is_honoured() -> None:
    _, output = _induce(independence_group="wordlist-03")

    assert all(item.independence_group == "wordlist-03" for item in output.evidence_items)


def test_one_source_records_one_independence_axis_per_lexeme() -> None:
    _, output = _induce()

    assert all(
        lexeme.score_breakdown is not None and len(lexeme.score_breakdown.independence_groups) == 1
        for lexeme in output.lexemes
    )


# --- lineage ----------------------------------------------------------------------


def test_lexeme_lineage_reaches_run_source_object_and_evidence() -> None:
    _, output = _induce()
    pairs = {(edge.from_id, edge.to_id) for edge in output.lineage_edges}

    lexeme = _lexeme_of(output, "mabi")
    lexeme_evidence = {item.id for item in output.evidence_items if item.target_id == lexeme.id}

    assert (lexeme.id, RUN_ID) in pairs
    assert (lexeme.id, SOURCE_OBJECT_ID) in pairs
    assert lexeme_evidence <= {to_id for from_id, to_id in pairs if from_id == lexeme.id}
    assert all(edge.kind is LineageKind.DERIVED_FROM for edge in output.lineage_edges)


def test_sense_lineage_reaches_run_lexeme_and_its_own_evidence() -> None:
    _, output = _induce()
    pairs = {(edge.from_id, edge.to_id) for edge in output.lineage_edges}

    lexeme = _lexeme_of(output, "mabi")
    canoa = next(
        sense
        for sense in output.senses
        if sense.lexeme_id == lexeme.id and sense.glosses[CONTACT_LANGUAGE] == ["canoa"]
    )
    canoa_evidence = {
        item.id
        for item in output.evidence_items
        if item.claim is not None and item.claim.get("gloss") == "canoa"
    }
    tronco_evidence = {
        item.id
        for item in output.evidence_items
        if item.claim is not None and item.claim.get("gloss") == "tronco"
    }

    assert (canoa.id, RUN_ID) in pairs
    assert (canoa.id, lexeme.id) in pairs
    assert canoa_evidence <= {to_id for from_id, to_id in pairs if from_id == canoa.id}
    assert not tronco_evidence & {to_id for from_id, to_id in pairs if from_id == canoa.id}


def test_evidence_items_link_back_to_the_source_object() -> None:
    _, output = _induce()
    pairs = {(edge.from_id, edge.to_id) for edge in output.lineage_edges}

    assert all((item.id, SOURCE_OBJECT_ID) in pairs for item in output.evidence_items)


def test_no_lineage_edge_points_at_itself() -> None:
    _, output = _induce()

    assert all(edge.from_id != edge.to_id for edge in output.lineage_edges)


# --- promotion semantics ----------------------------------------------------------


def test_single_source_never_promotes_a_lexeme() -> None:
    _, output = _induce()

    assert all(lexeme.status is LifecycleStatus.CANDIDATE for lexeme in output.lexemes)
    assert all(sense.status is LifecycleStatus.CANDIDATE for sense in output.senses)


def test_no_status_is_ever_validated() -> None:
    # AGENTS.md invariant 3: machine confidence never creates `validated`.
    _, output = _induce()

    statuses = {lexeme.status for lexeme in output.lexemes} | {
        sense.status for sense in output.senses
    }
    assert statuses <= {LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED}


def test_dictionary_evidence_alone_never_promotes_under_the_default_policy() -> None:
    # Two independent wordlists give diversity 1.0 + dictionary 1.0 + domain stability 1.0
    # = 0.20 + 0.20 + 0.10 = 0.50, below the 0.75 default threshold. The threshold is
    # deliberately above what one evidence kind can reach: dictionary support alone never
    # promotes target-language knowledge (WP4.5 makes the same point for alignment).
    data = b"qaa\tpor\tnote\nmabi\tcanoa; tronco\n"
    counter = [0]
    adapter = WordlistAdapter(new_id=_ids(counter), clock=Clock())
    first = adapter.induce(_input(data, independence_group="wordlist-a"))
    second = adapter.induce(_input(data, independence_group="wordlist-b", run_id=RUN_ID))

    assert first.lexemes[0].status is LifecycleStatus.CANDIDATE
    assert second.lexemes[0].status is LifecycleStatus.CANDIDATE
    assert second.lexemes[0].score_breakdown is not None
    # One axis observed by two gloss rows: diversity 0.5, dictionary 1.0, domain 1.0,
    # minus the formulaic-source penalty for the second item on the same axis.
    assert second.lexemes[0].score_breakdown.overall == 0.30000000000000004
    assert second.lexemes[0].score_breakdown.independence_groups == ["wordlist-b"]


def test_a_passing_policy_promotes_a_single_axis_lexeme_to_supported() -> None:
    # Same evidence with the second axis gate opened: one wordlist row at threshold 0.45
    # clears the gates, and the policy still returns `supported` at most (Invariant 3).
    policy = LexicalScorePolicy(promotion_threshold=0.45, min_independent_sources=1)
    data = b"qaa\tpor\tnote\nmabi\tcanoa\n"
    counter = [0]
    adapter = WordlistAdapter(new_id=_ids(counter), clock=Clock())
    first = adapter.induce(_input(data, independence_group="wordlist-a", policy=policy))
    second = adapter.induce(_input(data, independence_group="wordlist-b", policy=policy))

    assert first.lexemes[0].status is LifecycleStatus.SUPPORTED
    # Two axes share the same single source: two rows are still two items, so the
    # formulaic-source penalty applies, and the score still clears the threshold.
    assert second.lexemes[0].status is LifecycleStatus.SUPPORTED
    assert all(sense.status is LifecycleStatus.SUPPORTED for sense in second.senses)
    assert LifecycleStatus.VALIDATED not in {lexeme.status for lexeme in second.lexemes} | {
        sense.status for sense in second.senses
    }


def test_senses_scored_from_their_own_gloss_evidence() -> None:
    _, output = _induce()

    assert all(sense.score_breakdown is not None for sense in output.senses)
    assert all(sense.score_breakdown.overall >= 0.0 for sense in output.senses)


# --- registry ---------------------------------------------------------------------


def test_registry_resolves_the_wordlist_method() -> None:
    inducer = get_lexical_inducer("wordlist_tabular@0.1.0")

    assert inducer.method_id == "wordlist_tabular@0.1.0"
    assert "wordlist_tabular@0.1.0" in lexical_induction_methods()


def test_registry_resolves_a_bare_wordlist_name() -> None:
    inducer = get_lexical_inducer("wordlist_tabular")

    assert inducer.method_id == "wordlist_tabular@0.1.0"


def test_registry_still_resolves_the_alignment_method() -> None:
    assert get_lexical_inducer("alignment_cooccurrence@0.1.0").method_id == (
        "alignment_cooccurrence@0.1.0"
    )


def test_registry_rejects_an_unknown_method() -> None:
    with pytest.raises(UnsupportedMethod):
        get_lexical_inducer("wordlist_ragged@0.1.0")


# --- determinism and output shape -------------------------------------------------


def test_induce_returns_the_declared_output_shape() -> None:
    _, output = _induce()

    assert isinstance(output, LexicalInductionOutput)
    assert isinstance(output.concepts, list)
    assert output.concepts == []
    assert isinstance(output.form_links, list)
    assert isinstance(output.evidence_items, list)
    assert isinstance(output.lineage_edges, list)


def test_every_generated_identifier_uses_its_own_prefix() -> None:
    _, output = _induce()

    assert all(lexeme.id.startswith("lex_") for lexeme in output.lexemes)
    assert all(sense.id.startswith("sense_") for sense in output.senses)
    assert all(item.id.startswith("ev_") for item in output.evidence_items)
    assert all(edge.id.startswith("lin_") for edge in output.lineage_edges)


def test_row_order_does_not_change_the_output() -> None:
    ordered = "qaa\tpor\tnote\nmabi\tcanoa; tronco\nkanu\thomem\nrumi\tpajé\n".encode()
    shuffled = "qaa\tpor\tnote\nrumi\tpajé\nmabi\tcanoa; tronco\nkanu\thomem\n".encode()

    _, first = _induce(ordered)
    _, second = _induce(shuffled)

    def digest(output: LexicalInductionOutput) -> list[tuple]:
        # Normalize IDs by their semantic headword/gloss associations. Run and source
        # identifiers are stable inputs, but generated IDs and row locators are not.
        headword_by_lexeme = {
            item.target_id: str(item.claim.get("headword"))
            for item in output.evidence_items
            if item.claim is not None
        }
        gloss_by_evidence = {
            item.id: (str(item.claim.get("headword")), str(item.claim.get("gloss")))
            for item in output.evidence_items
            if item.claim is not None
        }
        lexemes = sorted(
            (
                headword_by_lexeme[lexeme.id],
                lexeme.language,
                str(lexeme.status),
                lexeme.lemma_form_id is None,
            )
            for lexeme in output.lexemes
        )
        senses = sorted(
            (
                headword_by_lexeme[sense.lexeme_id],
                _gloss_tags(sense),
                sense.domain,
                str(sense.status),
            )
            for sense in output.senses
        )
        evidence = sorted(
            (
                str(item.claim.get("headword")),
                str(item.claim.get("gloss")),
                item.kind.value,
                item.polarity.value,
                item.domain,
                item.independence_group,
            )
            for item in output.evidence_items
            if item.claim is not None
        )
        lineage = sorted(
            (
                _semantic_node(output, edge.from_id, headword_by_lexeme, gloss_by_evidence),
                _semantic_node(output, edge.to_id, headword_by_lexeme, gloss_by_evidence),
                edge.kind.value,
            )
            for edge in output.lineage_edges
        )
        links = sorted(
            (headword_by_lexeme[link.lexeme_id], link.role) for link in output.form_links
        )
        return [*lexemes, *senses, *evidence, *links, *lineage]

    assert digest(first) == digest(second)


def _gloss_tags(sense: Sense) -> tuple[str, tuple[str, ...]]:
    language, glosses = next(iter(sense.glosses.items()))
    return language, tuple(glosses)


def _kind_of(output: LexicalInductionOutput, object_id: str) -> str:
    if any(lexeme.id == object_id for lexeme in output.lexemes):
        return "lexeme"
    if any(sense.id == object_id for sense in output.senses):
        return "sense"
    if any(item.id == object_id for item in output.evidence_items):
        return "evidence"
    return "pinned"


def _semantic_node(
    output: LexicalInductionOutput,
    object_id: str,
    headword_by_lexeme: dict[str, str],
    gloss_by_evidence: dict[str, tuple[str, str]],
) -> tuple[str, ...]:
    if object_id in headword_by_lexeme:
        return ("lexeme", headword_by_lexeme[object_id])
    if object_id in gloss_by_evidence:
        return ("evidence", *gloss_by_evidence[object_id])
    for sense in output.senses:
        if sense.id == object_id:
            return ("sense", headword_by_lexeme[sense.lexeme_id], *_gloss_tags(sense)[1])
    return (_kind_of(output, object_id), object_id)


def test_empty_wordlist_body_produces_no_candidates() -> None:
    _, output = _induce(b"qaa\tpor\tnote\n")

    assert output.lexemes == []
    assert output.senses == []
    assert output.evidence_items == []
    assert output.lineage_edges == []


def test_parsed_entries_expose_their_locator() -> None:
    entries = parse_wordlist(GOLDEN, "sobj_x")

    # Row numbers are 1-based with the header as row 1: the first entry is row 2.
    assert [entry.line for entry in entries] == [2, 3, 4]


def test_raw_source_bytes_are_never_mutated_or_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The exact bytes read from the immutable raw store are the bytes handed to the adapter.
    # Storing them first and re-reading by digest proves the round trip is lossless and that
    # the adapter reads what it was given; a sentinel headword proves neither the parse path
    # nor a failure path logs content.
    caplog.set_level(logging.DEBUG, logger="langpipe")
    sentinel_wordlist = b"qaa\tpor\tnote\nSENTINELWORD\thomem\n"
    store = LocalContentStore(tmp_path / "raw")
    stored = store.put_bytes(sentinel_wordlist)

    _, output = _induce(store.read_bytes(stored.sha256))

    assert _lexeme_of(output, "SENTINELWORD")
    assert store.read_bytes(stored.sha256) == sentinel_wordlist
    store.verify(stored.sha256)
    assert "SENTINELWORD" not in caplog.text
    # A decode failure carries a fixed code only, never the offending bytes.
    with pytest.raises(ExtractionFailed) as failure:
        _induce(b"qaa\tpor\nSENTINELWORD\xff\xfe\n")
    assert failure.value.code == "decode_error"
    assert "SENTINELWORD" not in str(failure.value)
    assert "SENTINELWORD" not in repr(failure.value)
    assert "SENTINELWORD" not in caplog.text
