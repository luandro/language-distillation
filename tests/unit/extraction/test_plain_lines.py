from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.enums import SourceType
from langpipe.domain.errors import ExtractionFailed, UnsupportedSource
from langpipe.extraction.base import ExtractionContext
from langpipe.extraction.plain_lines import PlainLinesExtractor

FIXTURE_SOURCES = Path(__file__).parents[2] / "golden" / "fixture" / "sources"


def _ctx(languages: tuple[str, ...] = ("qaa",), language: str | None = None) -> ExtractionContext:
    return ExtractionContext(
        source_id="src-test",
        source_object_id="obj-test",
        source_type=SourceType.MONOLINGUAL_TEXT,
        media_type="text/plain",
        source_languages=languages,
        language=language,
    )


def _extract(data: bytes, ctx: ExtractionContext | None = None):  # type: ignore[no-untyped-def]
    return PlainLinesExtractor().extract(data, ctx or _ctx())


def test_plain_lines_preserves_nfd_and_internal_spacing() -> None:
    data = (FIXTURE_SOURCES / "05-monolingual" / "text.txt").read_bytes()
    out = _extract(data)

    assert [u.raw_text for u in out.units] == [
        "kanu mabi tesa.",
        "rumi shara.",
        "kanú wesa.",
    ]
    assert out.units[2].raw_text.encode("utf-8") == "kanú wesa.".encode()
    assert [u.locator for u in out.units] == [{"line": 1}, {"line": 2}, {"line": 3}]
    assert all(u.language == "qaa" for u in out.units)


def test_plain_lines_keeps_leading_trailing_and_double_spaces_verbatim() -> None:
    out = _extract(b"  kanu  mabi \n")

    assert out.units[0].raw_text == "  kanu  mabi "


def test_plain_lines_counts_and_skips_blank_lines() -> None:
    out = _extract(b"kanu\n\n   \nmabi\n\n\n")

    assert [u.raw_text for u in out.units] == ["kanu", "mabi"]
    assert [u.locator for u in out.units] == [{"line": 1}, {"line": 4}]
    assert out.stats["blank_lines"] == 4


def test_plain_lines_requires_single_language() -> None:
    ctx = _ctx(languages=("qaa", "por"))

    with pytest.raises(UnsupportedSource) as exc_info:
        _extract(b"kanu\n", ctx)

    assert exc_info.value.reason == "language_ambiguous"


def test_plain_lines_explicit_language_overrides_ambiguous_sources() -> None:
    ctx = _ctx(languages=("qaa", "por"), language="qaa")

    out = _extract(b"kanu\n", ctx)

    assert [u.language for u in out.units] == ["qaa"]


def test_plain_lines_uses_single_source_language() -> None:
    out = _extract(b"kanu\n", _ctx(languages=("mzr",)))

    assert [u.language for u in out.units] == ["mzr"]


def test_plain_lines_bom_and_crlf_counted_and_absent_from_text() -> None:
    out = _extract(b"\xef\xbb\xbfkanu\r\nmabi\rtesa\r\n")

    assert out.stats["bom_removed"] == 1
    assert out.stats["crlf_lines"] == 3
    assert [u.raw_text for u in out.units] == ["kanu", "mabi", "tesa"]
    assert all("\r" not in u.raw_text and "\n" not in u.raw_text for u in out.units)


def test_plain_lines_invalid_utf8_raises_decode_error() -> None:
    with pytest.raises(ExtractionFailed) as exc_info:
        _extract(b"kanu\n\xff\n")

    assert exc_info.value.code == "decode_error"


def test_plain_lines_is_registered_with_pinned_version() -> None:
    assert PlainLinesExtractor.name == "plain_lines"
    assert PlainLinesExtractor.version == "0.1.0"


@given(st.binary(max_size=200))
def test_extractors_are_deterministic(data: bytes) -> None:
    from langpipe.extraction.tsv import TsvExtractor

    def run(extractor_cls: type) -> object:  # type: ignore[type-arg]
        try:
            return extractor_cls().extract(data, _ctx())
        except ExtractionFailed as exc:
            return (exc.code, exc.line)

    assert run(PlainLinesExtractor) == run(PlainLinesExtractor)
    assert run(TsvExtractor) == run(TsvExtractor)
