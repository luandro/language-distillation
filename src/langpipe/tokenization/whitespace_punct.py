"""Generic whitespace/punctuation tokenizer ``whitespace_punct@0.1.0`` (M2 WP2.6).

Operates on normalized text only. Character classes:
- word-char: Unicode category ``L*`` or ``M*``
- digit: ``Nd``
- joiner: ``joiners`` (kept only between two word-chars)
- separator: any ``isspace`` character (emits no token)
- punct: everything else (one token per character)
"""

import unicodedata
from typing import ClassVar

from langpipe.tokenization.base import TokenKind, TokenOutput


def _is_word_char(ch: str) -> bool:
    return unicodedata.category(ch)[0] in ("L", "M")


def _is_digit(ch: str) -> bool:
    return unicodedata.category(ch) == "Nd"


class WhitespacePunctTokenizer:
    name: ClassVar[str] = "whitespace_punct"
    version: ClassVar[str] = "0.1.0"
    joiners: ClassVar[frozenset[str]] = frozenset({"-", "‐", "'", "’"})

    def tokenize(self, normalized: str) -> tuple[TokenOutput, ...]:
        tokens: list[TokenOutput] = []
        n = len(normalized)
        i = 0
        while i < n:
            ch = normalized[i]
            if ch.isspace():
                i += 1
                continue
            if _is_word_char(ch):
                end = self._word_end(normalized, i)
                kind = TokenKind.WORD
            elif _is_digit(ch):
                end = i + 1
                while end < n and _is_digit(normalized[end]):
                    end += 1
                kind = TokenKind.NUMBER
            else:
                end = i + 1
                kind = TokenKind.PUNCT
            tokens.append(
                TokenOutput(
                    ordinal=len(tokens),
                    kind=kind,
                    norm_start=i,
                    norm_end=end,
                    surface=normalized[i:end],
                )
            )
            i = end
        return tuple(tokens)

    def _word_end(self, text: str, start: int) -> int:
        # word-char+ (joiner word-char+)*; a joiner is consumed only when a word-char follows it.
        n = len(text)
        end = start
        while True:
            while end < n and _is_word_char(text[end]):
                end += 1
            if end + 1 < n and text[end] in self.joiners and _is_word_char(text[end + 1]):
                end += 1
                continue
            return end
