"""NLLB pair encoding with explicit, verified source and target language tags.

NLLB tokenizers take the language prefix token from tokenizer state. Setting only
``src_lang`` before ``text_target=`` leaves the label prefix to whatever state the
tokenizer was last left in, so the decoder can learn wrong target tags. This
helper sets both languages on every call and checks the emitted prefix ids.
"""

from __future__ import annotations

from typing import Any, Protocol


class _NllbTokenizer(Protocol):
    src_lang: str | None
    tgt_lang: str | None

    def __call__(self, text: str | None = None, **kwargs: Any) -> dict[str, Any]: ...

    def convert_tokens_to_ids(self, token: str) -> int: ...


def encode_pair(
    tokenizer: _NllbTokenizer,
    src_text: str,
    tgt_text: str,
    src_lang: str,
    tgt_lang: str,
    max_source_length: int,
    max_target_length: int,
) -> dict[str, list[int]]:
    """Encode one parallel pair, with source and target language tags set explicitly."""
    tokenizer.src_lang = src_lang
    tokenizer.tgt_lang = tgt_lang
    inp = tokenizer(src_text, max_length=max_source_length, truncation=True)
    out = tokenizer(text_target=tgt_text, max_length=max_target_length, truncation=True)

    src_id = tokenizer.convert_tokens_to_ids(src_lang)
    tgt_id = tokenizer.convert_tokens_to_ids(tgt_lang)
    if inp["input_ids"][0] != src_id:
        raise ValueError(f"source prefix {inp['input_ids'][0]} != {src_lang} id {src_id}")
    if out["input_ids"][0] != tgt_id:
        raise ValueError(f"label prefix {out['input_ids'][0]} != {tgt_lang} id {tgt_id}")

    return {
        "input_ids": inp["input_ids"],
        "attention_mask": inp["attention_mask"],
        "labels": out["input_ids"],
    }
