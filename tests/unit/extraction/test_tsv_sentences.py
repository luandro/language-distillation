from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.enums import SourceType
from langpipe.domain.errors import ExtractionFailed
from langpipe.extraction.base import ExtractionContext
from langpipe.extraction.registry import EXTRACTORS, default_extractor_for
from langpipe.extraction.tsv import TsvExtractor
from langpipe.extraction.tsv_sentences import TsvSentencesExtractor

FIXTURE_SOURCES = Path(__file__).parents[2] / "golden" / "fixture" / "sources"
PARALLEL = ("qaa", "por")


def _ctx(languages: tuple[str, ...] = PARALLEL) -> ExtractionContext:
    return ExtractionContext(
        source_id="src-test",
        source_object_id="obj-test",
        source_type=SourceType.PARALLEL_TEXT,
        media_type="text/tab-separated-values",
        source_languages=languages,
        language=None,
    )


def _extract(data: bytes, languages: tuple[str, ...] = PARALLEL):  # type: ignore[no-untyped-def]
    return TsvSentencesExtractor().extract(data, _ctx(languages))


def _fixture_output():  # type: ignore[no-untyped-def]
    return _extract((FIXTURE_SOURCES / "01-parallel-distill" / "parallel.tsv").read_bytes())


def test_txt14_one_qaa_two_por_units() -> None:
    out = _fixture_output()

    txt14 = [u for u in out.units if u.locator["ref"] == "TXT.1.4"]
    qaa = [u for u in txt14 if u.language == "qaa"]
    por = [u for u in txt14 if u.language == "por"]
    assert [u.raw_text for u in qaa] == ["rumi tesa mabi-ki."]
    assert [u.raw_text for u in por] == ["O pajé vê a canoa.", "Ele sorri."]
    # Actual golden 1:2 membership, not inferred from a translated paraphrase.
    assert len(qaa) == 1 and len(por) == 2
    # Splitting only inserts units: ordinals stay contiguous in document order.
    assert len(out.units) == 9
    assert [u.ordinal for u in out.units] == list(range(9))
    assert out.empty_units == ()


def test_cell_offsets_and_locator_preserved() -> None:
    out = _fixture_output()

    por = [u for u in out.units if u.locator["ref"] == "TXT.1.4" and u.language == "por"]
    assert [dict(u.locator) for u in por] == [
        {
            "row": 5,
            "column": "por",
            "ref": "TXT.1.4",
            "sentence_part": 0,
            "cell_start": 0,
            "cell_end": 18,
        },
        {
            "row": 5,
            "column": "por",
            "ref": "TXT.1.4",
            "sentence_part": 1,
            "cell_start": 19,
            "cell_end": 29,
        },
    ]
    # Offsets are direct half-open slices of the original cell: inter-unit
    # whitespace stays in the source bytes, never inside a unit.
    cell = "O pajé vê a canoa. Ele sorri."
    assert [u.raw_text for u in por] == [cell[0:18], cell[19:29]]
    # A single-sentence por cell still carries its part index and full-cell offsets.
    single = next(u for u in out.units if u.locator["ref"] == "TXT.1.2" and u.language == "por")
    assert single.raw_text == "A canoa foi ao rio."
    assert single.locator["sentence_part"] == 0
    assert (single.locator["cell_start"], single.locator["cell_end"]) == (0, 19)
    # Non-split languages keep the plain tsv locator exactly.
    qaa = next(u for u in out.units if u.locator["ref"] == "TXT.1.1" and u.language == "qaa")
    assert dict(qaa.locator) == {"row": 2, "column": "qaa", "ref": "TXT.1.1"}


def test_unsplit_qaa_and_wesa_ra() -> None:
    out = _fixture_output()

    qaa = [u for u in out.units if u.language == "qaa"]
    assert [u.raw_text for u in qaa] == [
        "kanu mabi tesa.",
        "mabi-ki nawa wesa.",
        "kanu nawa wesa-ra.",
        "rumi tesa mabi-ki.",
    ]
    # Hyphenated forms and final periods never split a non-configured language.
    assert not any("sentence_part" in u.locator for u in qaa)
    assert not any("cell_start" in u.locator for u in qaa)


def test_delimiter_runs_and_final_fragment() -> None:
    data = (
        "ref\tqaa\tpor\nR1\tq1\tVem!!! Agora?! Já.\nR2\tq2\tUm. dois\nR3\tq3\t3.14 é.\n"
    ).encode()
    out = _extract(data)

    por = [u for u in out.units if u.language == "por"]
    assert [u.raw_text for u in por] == ["Vem!!!", "Agora?!", "Já.", "Um.", "dois", "3.14 é."]
    # Maximal delimiter runs stay with their sentence.
    assert [(u.locator["cell_start"], u.locator["cell_end"]) for u in por[:3]] == [
        (0, 6),
        (7, 14),
        (15, 18),
    ]
    assert [u.locator["sentence_part"] for u in por] == [0, 1, 2, 0, 1, 0]
    # A final fragment without a trailing delimiter is still a unit.
    assert por[4].raw_text == "dois"
    assert (por[4].locator["cell_start"], por[4].locator["cell_end"]) == (4, 8)
    # A delimiter not followed by whitespace or end does not split.
    assert por[5].raw_text == "3.14 é."
    assert [u.ordinal for u in out.units] == list(range(len(out.units)))


def test_ragged_input_same_failure() -> None:
    secret = "SECRETCELLTEXT"
    data = f"ref\tqaa\tpor\nR1\tkanu\tcanoa\nR2\t{secret}\n".encode()

    with pytest.raises(ExtractionFailed) as exc_info:
        _extract(data)

    err = exc_info.value
    assert err.code == "tsv_ragged_row"
    assert err.line == 3
    assert secret not in str(err)

    # Header and language failures are identical to the composed M2 parser.
    for bad, code, line in [
        (b"ref\tnote\nR1\tfoo\n", "tsv_header_invalid", 1),
        (b"ref\tqaa\tfra\nR1\tkanu\tfoo\n", "tsv_language_column_unknown", 1),
    ]:
        with pytest.raises(ExtractionFailed) as base_info:
            TsvExtractor().extract(bad, _ctx())
        with pytest.raises(ExtractionFailed) as wrapped_info:
            _extract(bad)
        assert (
            (wrapped_info.value.code, wrapped_info.value.line)
            == (
                base_info.value.code,
                base_info.value.line,
            )
            == (code, line)
        )


def test_default_tsv_unchanged() -> None:
    # The sentence adapter is opt-in by explicit name; M2 defaults are untouched.
    assert default_extractor_for(SourceType.PARALLEL_TEXT, "text/tab-separated-values") == (
        "tsv@0.1.0"
    )
    assert default_extractor_for(SourceType.MONOLINGUAL_TEXT, "text/tab-separated-values") == (
        "tsv@0.1.0"
    )
    extractor = EXTRACTORS.get("tsv_sentences@0.1.0")
    assert extractor.name == "tsv_sentences"  # type: ignore[attr-defined]
    assert extractor.version == "0.1.0"  # type: ignore[attr-defined]
    assert EXTRACTORS.get("tsv@0.1.0").name == "tsv"  # type: ignore[attr-defined]
    # The plain extractor keeps its M2 behavior on the same fixture.
    plain = TsvExtractor().extract(
        (FIXTURE_SOURCES / "01-parallel-distill" / "parallel.tsv").read_bytes(), _ctx()
    )
    assert len(plain.units) == 8


def test_metadata_stats_and_empty_units_preserved() -> None:
    data = b"ref\tqaa\tpor\tnote\nR1\tkanu\tUm. Dois.\tn1\nR2\tmabi\t\tn2\n"
    out = _extract(data)

    assert out.stats["metadata_cells"] == 2
    assert out.empty_units == ({"row": 3, "column": "por"},)
    assert [u.raw_text for u in out.units if u.language == "por"] == ["Um.", "Dois."]
    assert [u.ordinal for u in out.units] == list(range(4))


@given(st.binary(max_size=200))
def test_tsv_sentences_extractor_is_deterministic(data: bytes) -> None:
    def run() -> object:
        try:
            return _extract(data)
        except ExtractionFailed as exc:
            return (exc.code, exc.line)

    assert run() == run()
