import unicodedata

from langpipe.tokenization.base import TokenKind, TokenOutput
from langpipe.tokenization.registry import GENERIC_TOKENIZERS
from langpipe.tokenization.whitespace_punct import WhitespacePunctTokenizer


def _tokens(text: str) -> list[tuple[str, TokenKind]]:
    return [(tok.surface, tok.kind) for tok in WhitespacePunctTokenizer().tokenize(text)]


def _surfaces(text: str) -> list[str]:
    return [surface for surface, _ in _tokens(text)]


def test_hyphenated_word_is_one_token() -> None:
    assert _surfaces("mabi-ki nawa") == ["mabi-ki", "nawa"]
    assert _tokens("mabi-ki")[0] == ("mabi-ki", TokenKind.WORD)


def test_trailing_hyphen_is_punct() -> None:
    assert _tokens("wesa-") == [("wesa", TokenKind.WORD), ("-", TokenKind.PUNCT)]


def test_leading_hyphen_is_punct() -> None:
    assert _tokens("-wesa") == [("-", TokenKind.PUNCT), ("wesa", TokenKind.WORD)]


def test_apostrophe_internal_vs_quote() -> None:
    assert _tokens("ka'a") == [("ka'a", TokenKind.WORD)]
    assert _tokens("ka’a") == [("ka’a", TokenKind.WORD)]
    assert _tokens("'ka'") == [
        ("'", TokenKind.PUNCT),
        ("ka", TokenKind.WORD),
        ("'", TokenKind.PUNCT),
    ]


def test_punctuation_each_char_token() -> None:
    assert _tokens("...") == [
        (".", TokenKind.PUNCT),
        (".", TokenKind.PUNCT),
        (".", TokenKind.PUNCT),
    ]
    assert _tokens("a,b;") == [
        ("a", TokenKind.WORD),
        (",", TokenKind.PUNCT),
        ("b", TokenKind.WORD),
        (";", TokenKind.PUNCT),
    ]


def test_combining_marks_stay_in_word() -> None:
    nfd = unicodedata.normalize("NFD", "kanuñ")
    assert nfd != "kanuñ"
    assert _tokens(nfd) == [(nfd, TokenKind.WORD)]


def test_digits_are_number_tokens() -> None:
    assert _tokens("12 34") == [("12", TokenKind.NUMBER), ("34", TokenKind.NUMBER)]


def test_mixed_alphanumeric_is_split_documented_limitation() -> None:
    assert _tokens("2a") == [("2", TokenKind.NUMBER), ("a", TokenKind.WORD)]


def test_joiner_between_digits_is_punct() -> None:
    assert _tokens("12-34") == [
        ("12", TokenKind.NUMBER),
        ("-", TokenKind.PUNCT),
        ("34", TokenKind.NUMBER),
    ]


def test_other_whitespace_is_separator_not_token() -> None:
    assert _surfaces("a\tb c") == ["a", "b", "c"]


def test_ordinals_are_contiguous_and_surface_matches_slice() -> None:
    text = "mabi-ki nawa, 12."
    tokens = WhitespacePunctTokenizer().tokenize(text)
    assert [tok.ordinal for tok in tokens] == list(range(len(tokens)))
    assert all(isinstance(tok, TokenOutput) for tok in tokens)
    assert all(tok.surface == text[tok.norm_start : tok.norm_end] for tok in tokens)


def test_empty_text_has_no_tokens() -> None:
    assert WhitespacePunctTokenizer().tokenize("") == ()


def test_subclass_can_override_joiners() -> None:
    class NoHyphenTokenizer(WhitespacePunctTokenizer):
        name = "no_hyphen_test"
        version = "0.1.0"
        joiners = frozenset({"'"})

    assert [tok.surface for tok in NoHyphenTokenizer().tokenize("mabi-ki")] == [
        "mabi",
        "-",
        "ki",
    ]


def test_generic_tokenizers_registry_exposes_versioned_name() -> None:
    assert [t.name + "@" + t.version for t in GENERIC_TOKENIZERS] == ["whitespace_punct@0.1.0"]
