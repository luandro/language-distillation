"""Strict, source-specific example extractor for Costa (2002), *Ergatividade cindida em Marubo*.

The source (``var/external/marubo_sources/costa_2002.txt``) is OCR text of a printed paper. Its
numbered examples are laid out as a citation line, one or more Marubo lines, one or more gloss
lines, and a quoted Portuguese free translation, all separated by blank lines and interleaved
with prose. The generic :mod:`langpipe.harvest.extractors.igt_parser` was written for line-per-tier
Leipzig blocks; applied here it invents structure (it assigns one quoted line to both ``eng`` and
``por`` and assumes numbered tiers), so this pilot does not use it.

Design rules (invariant 9: no invented Marúbo):

* A block starts at a line matching ``^\\((\\d+)\\)`` and ends before the next such line or before a
  prose paragraph (a long line of running text, detected by shape only).
* A block is **accepted** only when every condition holds: exactly one identifiable printed
  Marubo utterance line, a gloss tier, exactly one quoted Portuguese sentence, no OCR-noise
  characters in the utterance, and no leading ungrammaticality mark. Otherwise it is held back
  with one machine reason. The noise rule is deliberately narrow: it certifies the Marúbo
  utterance, not the gloss, which is emitted verbatim from the OCR text layer and may itself
  contain misread segments (``qc.gloss_certified`` is therefore ``false``).
* Printed Marubo text is never repaired. Only Unicode NFC and whitespace collapse are applied, to
  every emitted string. No lexical, morphological or orthographic correction is attempted.
* Nothing here calls a model or the network; the module is a pure function of its input text.

Reason precedence is fixed and documented in :data:`HOLD_REASONS`. The extractor emits candidates
as evidence only: admission into a training file is a separate, explicit owner action (see
``exports/harvested_parallel/candidates/README.md``).
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Final

EXTRACTOR_ID: Final = "costa_examples/1"
LANG: Final = "mzr"
REGISTER: Final = "elicited_example"
ENG: Final = ""

REASON_NO_GLOSS = "no_gloss_tier"
REASON_NO_TRANSLATION = "no_translation"
REASON_TRANSLATION_NOT_SENTENCE = "translation_not_sentence"
REASON_OCR_NOISE = "ocr_noise"
REASON_STARRED = "starred_example"
REASON_MULTIPLE_TRANSLATIONS = "multiple_translations"
REASON_AMBIGUOUS = "ambiguous_boundary"
REASON_WORD_LIST = "word_list_not_sentence"

#: Allowed machine reasons, in the order the classify step applies them.
HOLD_REASONS: Final[tuple[str, ...]] = (
    REASON_STARRED,
    REASON_OCR_NOISE,
    REASON_MULTIPLE_TRANSLATIONS,
    REASON_WORD_LIST,
    REASON_NO_TRANSLATION,
    REASON_TRANSLATION_NOT_SENTENCE,
    REASON_NO_GLOSS,
    REASON_AMBIGUOUS,
)

_BLOCK_START: Final = re.compile(r"^\((\d+)\)")
# A block also *ends* at an OCR-spaced or dot-marked example number (``( 14)``, ``·(12)``); those
# variants are not accepted as block starts, but they must not bleed into the previous example.
_NEXT_EXAMPLE: Final = re.compile(r"^\u00b7?\(\s*\d+\s*\)")
# A gloss label: at least two uppercase letters after ``-``/``=`` (``NP-ERG``, ``pintar=AUX.T-REC``)
# or a dotted label (``gente.NOM``, ``3SG.POSS``). Single-letter labels (``ka'ma-N``, ``'isu-0``)
# belong to the printed Marubo surface line, not to a gloss tier.
_GLOSS_TAG: Final = re.compile(r"[-=][A-Z]{2,}|[-=][A-Z]\.[A-Z]|\.[A-Z]{2,}")
# A morpheme boundary that carries a grammatical label; used only to spot a truncated utterance
# whose subject sits on the example-number line (``(7) ma'tu-N``).
_MORPH_TOKEN: Final = re.compile(r"[^\s]+[-=][A-Z]")
# Sublabel such as ``a.`` / ``b.`` opening a sub-example.
_LABEL: Final = re.compile(r"^[a-z]\.\s+")
_DIGIT_RUN: Final = re.compile(r"\d{2,}")
# A digit touching a letter (``1siN``): the stress mark misread as ``1``. A bare ``-0`` (zero
# morpheme) never touches a letter and stays legal.
_DIGIT_NEXT_TO_LETTER: Final = re.compile(r"(?<=[^\W\d_])\d|\d(?=[^\W\d_])")
_QUOTE_CHARS: Final = "'\"\u2018\u2019"
_NOISE_CHARS: Final = frozenset("\u00b7}{\\_~\u00ac")
_STAR_MARKS: Final = ("*", "?", "#")

_TRANSLATION = "translation"
_SHORT_QUOTE = "short_quote"
_GLOSS = "gloss"
_CONTENT = "content"
_PHONETIC = "phonetic"
_IGNORABLE = "ignorable"
_PROSE = "prose"
_BLANK = "blank"


@dataclass(frozen=True, slots=True)
class Candidate:
    """An accepted example: evidence for the owner, never an automatic training row."""

    ref: str
    src: str
    tgt: str
    eng: str
    lang: str
    register: str
    gloss: str
    qc: dict[str, object] = field(default_factory=dict)
    source_file: str = ""
    source_sha256: str = ""
    line_start: int = 0
    line_end: int = 0


@dataclass(frozen=True, slots=True)
class HeldBack:
    """A block that could not be accepted, with the machine reason and the raw printed text."""

    ref: str
    reason: str
    raw: str
    source_file: str = ""
    source_sha256: str = ""
    line_start: int = 0
    line_end: int = 0


def _normalise(text: str) -> str:
    """NFC + whitespace collapse. The only transformation ever applied to printed text."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _strip_quotes(text: str) -> str:
    """Drop the printed quotation marks around a free translation, keeping final punctuation."""
    inner = text.strip()
    while inner and inner[0] in _QUOTE_CHARS:
        inner = inner[1:]
    while inner and inner[-1] in _QUOTE_CHARS:
        inner = inner[:-1]
    return inner.strip()


def _is_sentence(text: str) -> bool:
    return text.endswith((".", "!", "?")) and len(text.split()) >= 2


_SENTENCE_CLOSE: Final = re.compile(r"[.!?][\u2019']?[.\s]*$")


def _is_quoted(text: str) -> bool:
    """True for a printed quoted translation or lexical gloss.

    Marubo words open with a glottal apostrophe (``'kama``, ``'kiki-ai``), so a leading quote
    alone proves nothing: the line must also close, as ``'...'``, ``''...'``, or ``'... .'``.
    """
    if text.startswith('"') or text.startswith("\u2018"):
        return True
    if not text.startswith("'"):
        return False
    if text.startswith("''") or text.endswith(("'", "\u2019")):
        return True
    return bool(_SENTENCE_CLOSE.search(text))


def _has_ocr_noise(text: str) -> bool:
    if any(char in _NOISE_CHARS for char in text):
        return True
    if _DIGIT_RUN.search(text) or _DIGIT_NEXT_TO_LETTER.search(text):
        return True
    return any(token.isdigit() for token in text.split())


def _is_ignorable(text: str) -> bool:
    return not any(char.isalpha() for char in text)


def _words(text: str) -> list[str]:
    """Tokens that carry at least one letter; OCR symbol junk (``··``, ``\\``) is not a word."""
    return [token for token in text.split() if any(char.isalpha() for char in token)]


def _is_running_text(text: str) -> bool:
    """Running prose, a running head or a section heading: never a Marubo utterance line."""
    words = [word for word in text.split() if any(char.isalpha() for char in word)]
    if len(words) >= 7 and any(len(word) >= 4 and word[1:].islower() for word in words):
        return True
    return len(words) >= 3 and all(word.upper() == word for word in words)


def _classify_line(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return _BLANK
    if stripped[0] in "[{/":
        return _PHONETIC
    if stripped[0] in _QUOTE_CHARS and _is_quoted(stripped):
        inner = _strip_quotes(stripped)
        return _TRANSLATION if _is_sentence(inner) else _SHORT_QUOTE
    if stripped[0] in _QUOTE_CHARS and _is_running_text(stripped):
        # A long printed line that opens with a quotation mark is quoted prose whose closing mark
        # OCR dropped (``'O homem que foi pescaré irmao dele( a).•``); it is not a Marubo line.
        return _SHORT_QUOTE
    if _is_running_text(stripped):
        return _PROSE
    if _GLOSS_TAG.search(stripped):
        return _GLOSS
    if _is_ignorable(stripped):
        return _IGNORABLE
    return _CONTENT


def _ref_prefix(source_ref: str) -> str:
    stem = os.path.splitext(os.path.basename(source_ref))[0]
    return stem.replace("_", "-")


@dataclass(frozen=True, slots=True)
class _Block:
    number: int
    header_rest: str
    body: tuple[str, ...]
    line_start: int
    line_end: int
    raw: str


def _split_lines(text: str) -> list[str]:
    """Split on ``\\n`` only: OCR page form feeds must not shift printed line numbers."""
    return [line.rstrip("\r") for line in text.replace("\r\n", "\n").split("\n")]


def _find_blocks(lines: list[str]) -> list[_Block]:
    blocks: list[_Block] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        match = _BLOCK_START.match(stripped)
        if match is None:
            index += 1
            continue
        end = index
        cursor = index + 1
        while cursor < len(lines):
            probe = _LABEL.sub("", lines[cursor].strip())
            if _NEXT_EXAMPLE.match(probe):
                break
            kind = _classify_line(probe)
            if kind == _PROSE:
                break
            if kind != _BLANK:
                end = cursor
            cursor += 1
        blocks.append(
            _Block(
                number=int(match.group(1)),
                header_rest=_LABEL.sub("", stripped[match.end() :]).strip(),
                body=tuple(lines[index + 1 : end + 1]),
                line_start=index + 1,
                line_end=end + 1,
                raw="\n".join(lines[index : end + 1]),
            )
        )
        index = end + 1
    return blocks


@dataclass(slots=True)
class _Parts:
    translations: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    glosses: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    fragments: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    header_orphan: bool = False


def _collect(block: _Block) -> _Parts:
    parts = _Parts()
    header_rest = _normalise(block.header_rest)
    if header_rest:
        parts.texts.append(header_rest)
        kind = _classify_line(header_rest)
        if kind == _TRANSLATION:
            parts.translations.append(header_rest)
            parts.quotes.append(header_rest)
        elif kind == _SHORT_QUOTE:
            parts.quotes.append(header_rest)
        elif kind == _GLOSS:
            parts.glosses.append(header_rest)
        elif kind == _CONTENT:
            if len(_words(header_rest)) >= 2:
                parts.candidates.append(header_rest)
            elif _MORPH_TOKEN.search(header_rest):
                # The utterance almost certainly continues on the following printed line.
                parts.header_orphan = True
    for line in block.body:
        text = _normalise(_LABEL.sub("", line.strip()))
        if not text:
            continue
        parts.texts.append(text)
        kind = _classify_line(text)
        if kind == _TRANSLATION:
            parts.translations.append(text)
            parts.quotes.append(text)
        elif kind == _SHORT_QUOTE:
            parts.quotes.append(text)
        elif kind == _GLOSS:
            parts.glosses.append(text)
        elif kind == _CONTENT:
            if len(text.split()) >= 2:
                parts.candidates.append(text)
            else:
                parts.fragments.append(text)
    return parts


def _hold_reason(parts: _Parts) -> str | None:
    # Check the Marúbo utterance line(s) for leading ungrammaticality marks.
    # The spec requires "no leading */?# ungrammaticality mark" on the printed
    # Marúbo line, not on gloss/translation lines within the same block.
    if any(text.startswith(_STAR_MARKS) for text in parts.candidates):
        return REASON_STARRED
    if parts.candidates and any(_has_ocr_noise(text) for text in parts.candidates):
        return REASON_OCR_NOISE
    if len(parts.translations) > 1:
        return REASON_MULTIPLE_TRANSLATIONS
    if not parts.candidates and not parts.translations and (parts.glosses or parts.quotes):
        return REASON_WORD_LIST
    if not parts.quotes:
        return REASON_NO_TRANSLATION
    if not parts.translations:
        return REASON_TRANSLATION_NOT_SENTENCE
    if not parts.glosses:
        return REASON_NO_GLOSS
    if len(parts.candidates) != 1 or parts.fragments or parts.header_orphan:
        return REASON_AMBIGUOUS
    return None


def _qc() -> dict[str, object]:
    # The noise check covers the Marúbo utterance only. The gloss is emitted verbatim from the
    # OCR text layer, which misreads some segments (for example ʃ as "cy"), so it is evidence
    # for a human reader, never a certified analysis.
    return {"extractor": EXTRACTOR_ID, "accepted": True, "gloss_certified": False}


def extract_examples(text: str, *, source_ref: str) -> tuple[list[Candidate], list[HeldBack]]:
    """Split ``text`` into accepted :class:`Candidate` rows and :class:`HeldBack` rows.

    ``source_ref`` names the input file (e.g. ``costa_2002.txt``); its stem, with underscores
    replaced by hyphens, becomes the ``ref`` prefix (``costa-2002:ex2``).
    """
    source_file = os.path.basename(source_ref)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    prefix = _ref_prefix(source_ref)
    candidates: list[Candidate] = []
    held: list[HeldBack] = []
    for block in _find_blocks(_split_lines(text)):
        ref = f"{prefix}:ex{block.number}"
        parts = _collect(block)
        reason = _hold_reason(parts)
        if reason is not None:
            held.append(
                HeldBack(
                    ref=ref,
                    reason=reason,
                    raw=_normalise_block(block.raw),
                    source_file=source_file,
                    source_sha256=digest,
                    line_start=block.line_start,
                    line_end=block.line_end,
                )
            )
            continue
        candidates.append(
            Candidate(
                ref=ref,
                src=_normalise(parts.candidates[0]),
                tgt=_normalise(_strip_quotes(parts.translations[0])),
                eng=ENG,
                lang=LANG,
                register=REGISTER,
                gloss=_normalise(" ".join(parts.glosses)),
                qc=_qc(),
                source_file=source_file,
                source_sha256=digest,
                line_start=block.line_start,
                line_end=block.line_end,
            )
        )
    candidates.sort(key=lambda row: (row.line_start, row.ref))
    held.sort(key=lambda row: (row.line_start, row.ref))
    return candidates, held


def _normalise_block(raw: str) -> str:
    return "\n".join(_normalise(line) for line in _split_lines(raw))


def candidate_to_row(candidate: Candidate) -> dict[str, object]:
    """Stable-key-order JSON row for an accepted candidate (source Marubo text unmodified)."""
    return {
        "ref": candidate.ref,
        "src": candidate.src,
        "tgt": candidate.tgt,
        "eng": candidate.eng,
        "lang": candidate.lang,
        "register": candidate.register,
        "gloss": candidate.gloss,
        "qc": dict(candidate.qc),
        "source_file": candidate.source_file,
        "source_sha256": candidate.source_sha256,
        "line_start": candidate.line_start,
        "line_end": candidate.line_end,
    }


def held_back_to_row(held: HeldBack) -> dict[str, object]:
    """Stable-key-order JSON row for a held-back block."""
    return {
        "ref": held.ref,
        "reason": held.reason,
        "source_file": held.source_file,
        "source_sha256": held.source_sha256,
        "line_start": held.line_start,
        "line_end": held.line_end,
        "raw": held.raw,
    }
