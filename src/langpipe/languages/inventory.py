"""Character-inventory model and report-only diagnostics (M2 WP2.7).

The inventory is informational. Each ``characters`` entry must be exactly one NFC grapheme; the
model rejects malformed entries instead of normalizing them. Diagnostics never reject or rewrite
text; they only count code points outside a declared inventory. An empty inventory disables
diagnostics entirely.
"""

import unicodedata
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError, model_validator

from langpipe.domain.errors import SchemaViolation
from langpipe.domain.models.base import LANG_CODE, DomainModel


def _is_combining_mark(ch: str) -> bool:
    return unicodedata.category(ch)[0] == "M"


def _is_single_nfc_grapheme(item: str) -> bool:
    """True for exactly one NFC grapheme: a starter followed only by combining marks.

    Dependency-free and deliberately conservative: it rejects empty entries, leading combining
    marks, multiple starters (``ab``) and any entry that is not already NFC (``a`` + U+0303). It
    does not attempt Emoji/ZWJ or Hangul cluster segmentation; such entries are rejected rather
    than silently widened (WP2.7 contract note).
    """
    if not item or _is_combining_mark(item[0]):
        return False
    # Control characters, line breaks (LF, CR, etc.) and surrogates are never valid
    # grapheme starters
    first_cat = unicodedata.category(item[0])
    if first_cat[0] == "C" or item[0] in "\r\n":
        return False
    if unicodedata.normalize("NFC", item) != item:
        return False
    return all(_is_combining_mark(ch) for ch in item[1:])


class Inventory(DomainModel):
    language: LANG_CODE
    status: Literal["unverified", "provisional", "verified"]
    characters: tuple[str, ...]  # each item one NFC grapheme string; may be multi-codepoint
    digraphs: tuple[str, ...] = ()  # informational only in M2 (reviewed "tx", "sh")
    reviewed_by: str | None = None  # required unless status == "unverified"
    notes: str | None = None

    @model_validator(mode="after")
    def _reviewer_required(self) -> "Inventory":
        if self.status != "unverified" and not self.reviewed_by:
            raise ValueError("reviewed_by is required unless status is unverified")
        return self

    @model_validator(mode="after")
    def _characters_are_single_nfc_graphemes(self) -> "Inventory":
        for entry in self.characters:
            if not _is_single_nfc_grapheme(entry):
                raise ValueError("characters must be single NFC graphemes")
        return self


def load_inventory(path: Path) -> Inventory:
    # Errors reduce to one fixed code: messages must not echo inventory content or file paths.
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Inventory.model_validate(data)
    except (OSError, ValueError, yaml.YAMLError, ValidationError):
        raise SchemaViolation() from None


def _is_punct(ch: str) -> bool:
    # Mirrors the WP2.6 tokenizer classes: word-char (L*, M*) and digit (Nd) are content;
    # everything else, including whitespace and symbols, is the punct class.
    category = unicodedata.category(ch)
    return category[0] not in ("L", "M") and category != "Nd"


def inventory_diagnostics(text: str, inv: Inventory) -> dict[str, int]:
    if not inv.characters:
        return {}
    covered = {ch for item in inv.characters for ch in item}
    counts: dict[str, int] = {}
    for ch in text:
        if ch == " " or _is_punct(ch) or ch in covered:
            continue
        key = f"char_outside_inventory:U+{ord(ch):04X}"
        counts[key] = counts.get(key, 0) + 1
    return counts
