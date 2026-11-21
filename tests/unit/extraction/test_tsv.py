from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.enums import SourceType
from langpipe.domain.errors import ExtractionFailed
from langpipe.extraction.base import ExtractionContext
from langpipe.extraction.tsv import TsvExtractor

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
    return TsvExtractor().extract(data, _ctx(languages))


def test_tsv_parallel_fixture_units() -> None:
    data = (FIXTURE_SOURCES / "01-parallel-distill" / "parallel.tsv").read_bytes()
    out = _extract(data)

    assert len(out.units) == 8
    assert [u.ordinal for u in out.units] == list(range(8))
    assert {u.language for u in out.units} == {"qaa", "por"}
    assert out.units[0].locator == {"row": 2, "column": "qaa", "ref": "TXT.1.1"}
    assert out.units[0].raw_text == "kanu mabi tesa."
    assert out.units[1].locator == {"row": 2, "column": "por", "ref": "TXT.1.1"}
    assert out.units[1].raw_text == "O homem vê a canoa."
    assert out.empty_units == ()


def test_tsv_golden_wordlist_03_is_malformed_row_two() -> None:
    # Golden 03 row 2 ("kanu\thomem") has two fields under a three-field header.
    # Strict parsing rejects it; bytes are not repaired (spec/fixture conflict, see WP2.3 notes).
    data = (FIXTURE_SOURCES / "03-wordlist" / "wordlist.tsv").read_bytes()

    with pytest.raises(ExtractionFailed) as exc_info:
        _extract(data)

    assert exc_info.value.code == "tsv_ragged_row"
    assert exc_info.value.line == 2


def test_tsv_wordlist_without_ref_column_counts_note_metadata() -> None:
    # Explicitly valid synthetic wordlist: same vocabulary as golden 03, row 2 has an empty note.
    data = (
        "qaa\tpor\tnote\n"
        "kanu\thomem\t\n"
        "mabi\tcanoa; tronco\ttwo candidate senses\n"
        "rumi\tpajé\tdomain-specific (ritual/traditional)\n"
    ).encode()
    out = _extract(data)

    assert [(u.language, u.raw_text, u.locator) for u in out.units] == [
        ("qaa", "kanu", {"row": 2, "column": "qaa"}),
        ("por", "homem", {"row": 2, "column": "por"}),
        ("qaa", "mabi", {"row": 3, "column": "qaa"}),
        ("por", "canoa; tronco", {"row": 3, "column": "por"}),
        ("qaa", "rumi", {"row": 4, "column": "qaa"}),
        ("por", "pajé", {"row": 4, "column": "por"}),
    ]
    assert [u.ordinal for u in out.units] == list(range(6))
    assert out.stats["metadata_cells"] == 3
    assert out.empty_units == ()
    assert all("ref" not in u.locator for u in out.units)
    assert all("two candidate senses" not in u.raw_text for u in out.units)
    assert all("domain-specific" not in u.raw_text for u in out.units)


def test_tsv_empty_cell_is_reported_not_emitted() -> None:
    data = b"ref\tqaa\tpor\nR1\tkanu\t\nR2\t\tcanoa\n"
    out = _extract(data)

    assert [u.raw_text for u in out.units] == ["kanu", "canoa"]
    assert [u.ordinal for u in out.units] == [0, 1]
    assert out.empty_units == (
        {"row": 2, "column": "por"},
        {"row": 3, "column": "qaa"},
    )


def test_tsv_ragged_row_fails_with_line_only() -> None:
    secret = "SECRETCELLTEXT"
    data = f"ref\tqaa\tpor\nR1\tkanu\tcanoa\nR2\t{secret}\n".encode()

    with pytest.raises(ExtractionFailed) as exc_info:
        _extract(data)

    err = exc_info.value
    assert err.code == "tsv_ragged_row"
    assert err.line == 3
    assert secret not in str(err)


def test_tsv_unknown_language_column_fails() -> None:
    data = b"ref\tqaa\tfra\nR1\tkanu\tfoo\n"

    with pytest.raises(ExtractionFailed) as exc_info:
        _extract(data)

    assert exc_info.value.code == "tsv_language_column_unknown"


def test_tsv_header_without_language_column_fails() -> None:
    with pytest.raises(ExtractionFailed) as exc_info:
        _extract(b"ref\tnote\nR1\tfoo\n")

    assert exc_info.value.code == "tsv_header_invalid"


def test_tsv_bom_and_crlf_counted_and_absent_from_text() -> None:
    data = b"\xef\xbb\xbfref\tqaa\tpor\r\nR1\tkanu\tcanoa\r\nR2\tmabi\tcanoa\r\n\r\n\r\n"
    out = _extract(data)

    assert out.stats["bom_removed"] == 1
    assert out.stats["crlf_lines"] == 5
    assert out.stats["trailing_empty_lines"] == 2
    assert [u.raw_text for u in out.units] == ["kanu", "canoa", "mabi", "canoa"]
    assert all("\r" not in u.raw_text and "\n" not in u.raw_text for u in out.units)
    assert all("﻿" not in u.raw_text for u in out.units)


def test_tsv_cell_text_is_not_trimmed() -> None:
    out = _extract(b"ref\tqaa\tpor\nR1\t kanu  \tcanoa\n")

    assert out.units[0].raw_text == " kanu  "


def test_tsv_first_column_is_ref_even_when_it_looks_like_a_language_code() -> None:
    out = _extract(b"pos\tqaa\nN1\tkanu\n")

    assert out.units[0].locator == {"row": 2, "column": "qaa", "ref": "N1"}
    assert out.stats.get("metadata_cells", 0) == 0


def test_tsv_later_three_letter_non_language_column_fails() -> None:
    with pytest.raises(ExtractionFailed) as exc_info:
        _extract(b"ref\tqaa\tpos\nR1\tkanu\tN\n")

    assert exc_info.value.code == "tsv_language_column_unknown"
    assert exc_info.value.line == 1


def test_tsv_duplicate_language_columns_are_kept_in_column_order() -> None:
    out = _extract(b"qaa\tqaa\nkanu\tmabi\n", ("qaa",))

    assert [u.raw_text for u in out.units] == ["kanu", "mabi"]
    assert [u.ordinal for u in out.units] == [0, 1]
    assert all(u.locator == {"row": 2, "column": "qaa"} for u in out.units)


def test_tsv_whitespace_only_cell_is_an_observation_not_empty() -> None:
    out = _extract(b"ref\tqaa\tpor\nR1\t \tcanoa\n")

    assert [u.raw_text for u in out.units] == [" ", "canoa"]
    assert out.empty_units == ()


def test_tsv_final_terminator_adds_no_trailing_empty_line_stat() -> None:
    out = _extract(b"ref\tqaa\tpor\nR1\tkanu\tcanoa\n")

    assert "trailing_empty_lines" not in out.stats
    assert [u.raw_text for u in out.units] == ["kanu", "canoa"]


def test_tsv_invalid_utf8_raises_decode_error() -> None:
    with pytest.raises(ExtractionFailed) as exc_info:
        _extract(b"ref\tqaa\tpor\nR1\t\xff\xfe\tcanoa\n")

    assert exc_info.value.code == "decode_error"


def test_tsv_is_registered_with_pinned_version() -> None:
    assert TsvExtractor.name == "tsv"
    assert TsvExtractor.version == "0.1.0"


@given(st.binary(max_size=200))
def test_tsv_extractor_is_deterministic(data: bytes) -> None:
    def run() -> object:
        try:
            return _extract(data)
        except ExtractionFailed as exc:
            return (exc.code, exc.line)

    assert run() == run()
