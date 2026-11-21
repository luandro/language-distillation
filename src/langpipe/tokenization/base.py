"""Tokenizer interface. Tokenizers are pure and never see raw text (M2 E2)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from langpipe.text.registry import Versioned


class TokenKind(StrEnum):
    WORD = "word"
    NUMBER = "number"
    PUNCT = "punct"


@dataclass(frozen=True)
class TokenOutput:
    ordinal: int
    kind: TokenKind
    norm_start: int
    norm_end: int
    surface: str  # surface == normalized[norm_start:norm_end]


class Tokenizer(Versioned, Protocol):
    def tokenize(self, normalized: str) -> tuple[TokenOutput, ...]: ...
