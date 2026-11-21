"""Label language-tag regression tests for NLLB pair encoding."""

from __future__ import annotations

from typing import Any

import pytest

from langpipe.training.nllb_encoding import encode_pair

IDS = {"por_Latn": 10, "mzr_Latn": 11, "</s>": 2}


class _StatefulTokenizer:
    """Mimics NLLB state: prefix comes from the tokenizer's current language fields.

    ``stale_tgt`` simulates the old bug where the target prefix follows whatever
    language the tokenizer last saw instead of the requested target.
    """

    def __init__(self) -> None:
        self.src_lang = "por_Latn"
        self.tgt_lang = "por_Latn"
        self.stale_tgt: str | None = None

    def convert_tokens_to_ids(self, token: str) -> int:
        return IDS[token]

    def __call__(
        self, text: str | None = None, text_target: str | None = None, **_: Any
    ) -> dict[str, Any]:
        if text_target is not None:
            lang = self.stale_tgt or self.tgt_lang
            return {"input_ids": [IDS[lang], 99, IDS["</s>"]]}
        return {"input_ids": [IDS[self.src_lang], 98, IDS["</s>"]], "attention_mask": [1, 1, 1]}


def test_encode_pair_sets_both_language_tags() -> None:
    tok = _StatefulTokenizer()
    out = encode_pair(tok, "Qual seu nome?", "Ãwẽ aská", "por_Latn", "mzr_Latn", 32, 32)
    assert out["input_ids"][0] == IDS["por_Latn"]
    assert out["labels"][0] == IDS["mzr_Latn"]


def test_encode_pair_reverse_direction() -> None:
    tok = _StatefulTokenizer()
    out = encode_pair(tok, "Ãwẽ aská", "Qual seu nome?", "mzr_Latn", "por_Latn", 32, 32)
    assert out["labels"][0] == IDS["por_Latn"]


def test_encode_pair_mixed_directions_on_shared_tokenizer() -> None:
    tok = _StatefulTokenizer()
    directions = [
        ("por_Latn", "mzr_Latn"),
        ("mzr_Latn", "por_Latn"),
        ("por_Latn", "mzr_Latn"),
        ("mzr_Latn", "por_Latn"),
    ]
    for src_lang, tgt_lang in directions:
        out = encode_pair(tok, "Qual seu nome?", "Ãwẽ aská", src_lang, tgt_lang, 32, 32)
        assert out["input_ids"][0] == IDS[src_lang]
        assert out["labels"][0] == IDS[tgt_lang]


def test_encode_pair_rejects_stale_label_prefix() -> None:
    tok = _StatefulTokenizer()
    tok.stale_tgt = "por_Latn"  # old-bug behaviour: target prefix ignores tgt_lang
    with pytest.raises(ValueError, match="label prefix"):
        encode_pair(tok, "Qual seu nome?", "Ãwẽ aská", "por_Latn", "mzr_Latn", 32, 32)
