import itertools

from hypothesis import given
from hypothesis import strategies as st

from langpipe.tokenization.whitespace_punct import WhitespacePunctTokenizer

_ALPHABET = st.sampled_from(
    list("abcXYZ")
    + ["ñ", "́", "ʼ", "1", "9", "٣", "-", "‐", "'", "’", ".", ",", "!", "(", " ", "\t", " "]
)
_TEXT = st.text(alphabet=_ALPHABET, max_size=60)


@given(_TEXT)
def test_tokens_cover_all_non_space_chars_in_order_without_overlap(text: str) -> None:
    tokens = WhitespacePunctTokenizer().tokenize(text)

    covered: list[int] = []
    for tok in tokens:
        covered.extend(range(tok.norm_start, tok.norm_end))
    expected = [i for i, ch in enumerate(text) if not ch.isspace()]

    assert covered == expected
    assert all(prev.norm_end <= cur.norm_start for prev, cur in itertools.pairwise(tokens))


@given(_TEXT)
def test_surface_equals_slice(text: str) -> None:
    for tok in WhitespacePunctTokenizer().tokenize(text):
        assert tok.surface == text[tok.norm_start : tok.norm_end]
        assert tok.surface != ""


@given(_TEXT)
def test_deterministic(text: str) -> None:
    tokenizer = WhitespacePunctTokenizer()
    assert tokenizer.tokenize(text) == tokenizer.tokenize(text)
    assert tokenizer.tokenize(text) == WhitespacePunctTokenizer().tokenize(text)
