"""Wordlist parser and induction adapter ``wordlist_tabular@0.1.0`` (M4-PLAN §6 WP4.6, ADR-0013).

Governed ingestion of tabular wordlists (e.g. the golden fixture's
``03-wordlist/wordlist.tsv``) and the extraction of their entries into candidate lexical
hypotheses. Two surfaces, one module:

* :func:`parse_wordlist` — pure tabular decoding. Strict UTF-8 (an undecodable byte is a
  typed failure, never a replacement character, and the offending bytes never reach a
  message), header-driven column resolution, and ragged or blank rows skipped rather than
  "repaired".
* :class:`WordlistAdapter` — a :class:`~langpipe.lexicon.base.LexicalInducer` turning those
  entries into candidate `Lexeme`/`Sense` hypotheses, `dictionary_assertion`
  `EvidenceItem`s and `derived_from` lineage.

Invariant-shaped decisions live here:

* A contact-language translation is a meaning hypothesis carried as a `Sense` gloss
  (`glosses={contact_language: [gloss]}`), never a target-language lexical form
  (Invariants 8 and 9; ADR-0013 §1). Only a target-language `Form` the caller pins can
  become a lemma, and nothing else in a row becomes a form.
* No adapter-invented linguistics: no part of speech, no concept minted from a gloss, no
  second lexeme for a repeated headword. A semicolon cell (`canoa; tronco`) yields two
  `Sense`s under one `Lexeme` (Phenomenon 2) and the entry's register/domain note is
  copied onto them (Phenomenon 9). Machine confidence never produces `validated`: the
  scoring policy grants `supported` at most (Invariant 3; ADR-0013 §3).

Governance is not this adapter's decision: the governed entry point in
`langpipe.ingest.wordlist` registers the `Source`, verifies sha256, ingests under
`Operation.INGEST` and extracts under `Operation.EXTRACT` (ADR-0007). This module only
decodes bytes it was handed, after that entry point read them from the immutable raw store.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Final

from pydantic import ValidationError

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LifecycleStatus, LineageKind
from langpipe.domain.errors import ExtractionFailed, LangpipeError, SchemaViolation
from langpipe.domain.ids import IdFactory, IdPrefix, new_id
from langpipe.domain.models.base import DomainModel
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.lexical import FormLexemeLink, Lexeme, Sense
from langpipe.domain.models.observation import Form
from langpipe.lexicon.base import LexicalInductionInput, LexicalInductionOutput
from langpipe.lexicon.scoring import DEFAULT_POLICY, DICTIONARY_SUPPORT, LexicalScorePolicy

METHOD_ID: str = "wordlist_tabular@0.1.0"
PRIMARY_LEMMA_ROLE: str = "primary_lemma"

# The language the gloss column is taken to be in when neither the header nor the request
# names one. Same fallback the language column resolution used before it was made explicit.
DEFAULT_CONTACT_LANGUAGE: str = "por"

# A 3-letter column name names its column's language; anything else names a metadata role.
_LANGUAGE_TAG: Final = re.compile(r"^[a-z]{3}$")

# Metadata column names, by role.
_DOMAIN_COLUMNS: Final = frozenset({"domain", "register", "area", "field", "semantic_domain"})
_NOTE_COLUMNS: Final = frozenset({"note", "notes", "remark", "remarks", "comment", "comments"})
_POS_COLUMNS: Final = frozenset({"pos", "word_class", "grammatical_info", "part_of_speech"})

# Domain tags read out of a note: `domain-specific (ritual/traditional)`,
# `domain: ritual/traditional`, `register: ritual/traditional`, or a bare `ritual/traditional`.
_DOMAIN_PARENTHESISED: Final = re.compile(r"\(([^()]*[/:][^()]*)\)")
_DOMAIN_COLON: Final = re.compile(r"^([a-z][a-z -]*):\s*(\S.*)$", re.IGNORECASE)
_DOMAIN_SLASHY: Final = re.compile(r"^[a-z][a-z0-9_ -]*[/:][a-z0-9_/: -]*$", re.IGNORECASE)


def _default_id(prefix: IdPrefix) -> str:
    return new_id(prefix)


def _required(value: str | None, field: str) -> str:
    """A pinned provenance reference the wordlist adapter cannot induce without.

    A wordlist induction without `source_id`/`source_object_id` has no provenance, so it is
    a caller error rather than something to invent here (Invariant 4).
    """
    if value is None:
        raise ValueError(f"a wordlist induction pins {field}")
    return value


@dataclass(frozen=True)
class WordlistEntry:
    """One decoded wordlist row: its headword, gloss(es), note, domain tag and locator.

    `line` is the 1-based row number counting the header as row 1, so an assertion's
    provenance is a locator a reviewer can check without re-reading the raw object.
    `contact_language` names the language the glosses are in (the header's gloss column).
    """

    headword: str
    glosses: tuple[str, ...]
    note: str | None = None
    domain: str | None = None
    pos: str | None = None
    line: int = 0
    contact_language: str = DEFAULT_CONTACT_LANGUAGE


@dataclass(frozen=True)
class _Header:
    """Column roles resolved from the first line of a wordlist file."""

    headword: int
    gloss: int
    note: int | None
    domain: int | None
    pos: int | None
    contact_language: str
    width: int


class WordlistFormatError(LangpipeError, ValueError):
    """A wordlist that cannot be decoded into entries, or a pin the adapter cannot accept.

    Subclasses `ValueError` and `LangpipeError`, so a caller may catch either. The message
    carries only a fixed code — never a row, a cell or a byte of source content.
    """

    HEADER_INVALID: ClassVar[str] = "wordlist_header_invalid"
    ENTRY_INVALID: ClassVar[str] = "wordlist_entry_invalid"
    # The header names no gloss language that is not the target language, or its gloss
    # column is in a language the request does not ask for: refuse, never silently relabel.
    GLOSS_LANGUAGE_INVALID: ClassVar[str] = "wordlist_gloss_language_invalid"
    # A pinned lemma form whose language is not the target language, or whose text does not
    # match the headword it is keyed by (ADR-0013 §1).
    LEMMA_PIN_INVALID: ClassVar[str] = "wordlist_lemma_pin_invalid"

    exit_code: ClassVar[int] = 4

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_wordlist(
    data: bytes,
    source_object_id: str,
    *,
    target_language: str = "qaa",
    contact_language: str | None = None,
) -> tuple[WordlistEntry, ...]:
    """Decode one tabular wordlist into entries. Pure: no storage, no policy check.

    Column roles come from the header when it names them (a language tag, `note`, `domain`
    or `pos`), and a declared column keeps its declared role: only columns that declare
    nothing are assigned by position, the first as the headword column and the next as the
    contact-language gloss column. `target_language` names the headword column's language
    and `contact_language` the language the gloss column is *requested* to be in; an
    explicit gloss-column tag wins over the request and is never relabelled. A header that
    leaves a required role unresolvable — no column a target headword can come from, or no
    gloss column at all — is refused, never repaired. A row that does not carry both
    resolved columns is skipped, never padded: a two-field row under a three-field header
    is an entry without a note, and a one-field row is not an entry at all.
    """
    lines = _lines(_decode(data, source_object_id))
    header = _header(
        lines[0].split("\t") if lines else (),
        target_language,
        requested_contact=contact_language,
    )
    if header is None:
        # Either no header at all, or a header that names no headword and no gloss column.
        raise WordlistFormatError(WordlistFormatError.HEADER_INVALID)

    entries: list[WordlistEntry] = []
    for line_no, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split("\t")]
        # A row wider than the header is unusable: its extra columns cannot be assigned to
        # the roles the header declares, so it contributes no entry. A shorter row is fine
        # as long as the two required columns are present (a note-less entry).
        if len(cells) > header.width:
            continue
        headword = _cell(cells, header.headword)
        gloss_cell = _cell(cells, header.gloss)
        if headword is None or gloss_cell is None:
            continue
        glosses = tuple(part for part in (g.strip() for g in gloss_cell.split(";")) if part)
        if not glosses:
            continue
        note = _cell(cells, header.note)
        entries.append(
            WordlistEntry(
                headword=headword,
                glosses=glosses,
                note=note,
                domain=_domain(_cell(cells, header.domain), note),
                pos=_cell(cells, header.pos),
                line=line_no,
                contact_language=header.contact_language,
            )
        )
    return tuple(entries)


class WordlistAdapter:
    """Induces candidate lexical hypotheses from one governed wordlist raw object."""

    name: ClassVar[str] = "wordlist_tabular"
    version: ClassVar[str] = "0.1.0"
    method_id: ClassVar[str] = METHOD_ID

    def __init__(
        self,
        *,
        policy: LexicalScorePolicy | None = None,
        new_id: IdFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy if policy is not None else DEFAULT_POLICY
        self._new_id: IdFactory = new_id if new_id is not None else _default_id
        self._clock: Callable[[], datetime] = (
            clock if clock is not None else lambda: datetime.now(UTC)
        )

    def induce(self, input: LexicalInductionInput) -> LexicalInductionOutput:
        source_id = _required(input.source_id, "source_id")
        source_object_id = _required(input.source_object_id, "source_object_id")
        entries = parse_wordlist(
            input.data,
            source_object_id,
            target_language=input.target_language,
            contact_language=input.contact_language,
        )
        if not entries:
            return LexicalInductionOutput()

        policy = input.policy if input.policy is not None else self.policy
        now = self._clock()
        independence_group = input.independence_group or source_id
        forms = _pinned_forms(
            input.target_forms or {}, input.target_language, {entry.headword for entry in entries}
        )

        # One headword is one lexeme however many senses it carries (Phenomenon 2); a
        # headword repeated across rows is several observations of that one lexeme, and
        # each keeps its own evidence item.
        grouped: dict[str, list[WordlistEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.headword, []).append(entry)

        lexemes: list[Lexeme] = []
        form_links: list[FormLexemeLink] = []
        senses: list[Sense] = []
        evidence_items: list[EvidenceItem] = []
        lineage_edges: list[LineageEdge] = []

        for headword in sorted(grouped):
            group = sorted(grouped[headword], key=lambda entry: entry.line)
            form = forms.get(headword)
            lexeme = _build(
                Lexeme,
                id=self._new_id(IdPrefix.LEXEME),
                language=input.target_language,
                lemma_form_id=None if form is None else form.id,
                run_id=input.run_id,
                created_at=now,
            )
            entry_evidence = [
                self._evidence(
                    entry,
                    gloss,
                    lexeme.id,
                    input.run_id,
                    source_id,
                    independence_group,
                    now,
                )
                for entry in group
                for gloss in entry.glosses
            ]
            lexeme = _promote(lexeme, policy, entry_evidence, input.target_language)
            lexemes.append(lexeme)
            if form is not None:
                form_links.append(
                    _build(
                        FormLexemeLink,
                        id=self._new_id(IdPrefix.FORM_LEXEME),
                        form_id=form.id,
                        lexeme_id=lexeme.id,
                        role=PRIMARY_LEMMA_ROLE,
                        run_id=input.run_id,
                        created_at=now,
                    )
                )
            evidence_items.extend(entry_evidence)
            for parent in (input.run_id, source_object_id, *[item.id for item in entry_evidence]):
                lineage_edges.append(_edge(lexeme.id, parent, input.run_id, now, self._new_id))
            for item in entry_evidence:
                lineage_edges.append(
                    _edge(item.id, source_object_id, input.run_id, now, self._new_id)
                )

            # One sense per distinct gloss: each gloss is its own meaning hypothesis and
            # keeps its own domain tag and its own supporting evidence.
            for gloss in sorted({gloss for entry in group for gloss in entry.glosses}):
                gloss_entries = [entry for entry in group if gloss in entry.glosses]
                sense_evidence = [
                    item
                    for item in entry_evidence
                    if item.claim is not None and item.claim.get("gloss") == gloss
                ]
                sense = _build(
                    Sense,
                    id=self._new_id(IdPrefix.SENSE),
                    lexeme_id=lexeme.id,
                    # The entry's own gloss-column language: a row whose header says the
                    # glosses are Spanish is a Spanish meaning hypothesis, never a
                    # relabelled Portuguese one (Invariants 8 and 9).
                    glosses={gloss_entries[0].contact_language: [gloss]},
                    domain=_shared_domain(gloss_entries),
                    run_id=input.run_id,
                    created_at=now,
                )
                sense = _promote(sense, policy, sense_evidence, input.target_language)
                senses.append(sense)
                lineage_edges.append(_edge(sense.id, input.run_id, input.run_id, now, self._new_id))
                lineage_edges.append(_edge(sense.id, lexeme.id, input.run_id, now, self._new_id))
                for item in sense_evidence:
                    lineage_edges.append(_edge(sense.id, item.id, input.run_id, now, self._new_id))

        return LexicalInductionOutput(
            lexemes=lexemes,
            form_links=form_links,
            senses=senses,
            concepts=[],
            evidence_items=evidence_items,
            lineage_edges=lineage_edges,
        )

    def _evidence(
        self,
        entry: WordlistEntry,
        gloss: str,
        lemma_id: str,
        run_id: str,
        source_id: str,
        independence_group: str | None,
        now: datetime,
    ) -> EvidenceItem:
        """The dictionary assertion this row makes about the lemma and this gloss.

        `target_id` is the lexeme: the row asserts the headword carries this meaning, so
        the assertion is evidence for the lexeme, while the gloss itself stays one sense
        hypothesis of it. `domain` and `strength` are the raw components the policy reads
        (EVIDENCE-AND-CONFIDENCE.md §Score breakdown): one governed, recorded assertion is
        support at full weight, and a domain tag recorded on the row is carried onto the
        evidence so domain stability is computed from it rather than invented.
        """
        return _build(
            EvidenceItem,
            id=self._new_id(IdPrefix.EVIDENCE),
            kind=EvidenceKind.DICTIONARY_ASSERTION,
            polarity=EvidencePolarity.SUPPORTS,
            target_id=lemma_id,
            claim={"headword": entry.headword, "gloss": gloss, "note": entry.note},
            source_id=source_id,
            run_id=run_id,
            strength={DICTIONARY_SUPPORT: 1.0},
            independence_group=independence_group,
            domain=entry.domain,
            created_at=now,
        )


def _pinned_forms(
    forms: Mapping[str, Form], target_language: str, headwords: set[str]
) -> Mapping[str, Form]:
    """Accept the caller's headword -> `Form` pins, rejecting the inconsistent ones.

    A pin names the target-language lexical form of one headword (ADR-0013 §1). A headword
    whose pinned form spells that headword in the target language is the lemma. A same-key
    form with a different language or spelling is an inconsistent pin and is refused with a
    fixed diagnostic. Unrelated entries in a mixed-language form map remain unused; the
    adapter never chooses among forms by text, relabels a form's language, or fabricates a
    form from the glosses.
    """
    pinned: dict[str, Form] = {}
    for headword, form in forms.items():
        if headword not in headwords:
            continue
        if form.language != target_language:
            raise WordlistFormatError(WordlistFormatError.LEMMA_PIN_INVALID)
        if not _matches_headword(form.text, headword):
            raise WordlistFormatError(WordlistFormatError.LEMMA_PIN_INVALID)
        pinned[headword] = form
    return pinned


def _matches_headword(text: str, headword: str) -> bool:
    """The headword comparison: both surfaces are already NFC or fail validation.

    `Form` validates its text as NFC at construction and a decoded wordlist row is UTF-8
    NFC, so the comparison is NFC on both sides by construction rather than a second
    normalization this adapter would have to own. A caller whose orthography profile
    normalizes further must resolve the headword to that form's text before pinning it.
    """
    return unicodedata.is_normalized("NFC", text) and text == headword


def _shared_domain(entries: Sequence[WordlistEntry]) -> str | None:
    """The domain tag the entries of one gloss agree on, when exactly one is recorded.

    Two rows recording different registers for one gloss are disagreement, not a merge:
    the disagreement is preserved by leaving the tag unset rather than picking a winner.
    """
    domains = {entry.domain for entry in entries if entry.domain}
    return next(iter(domains)) if len(domains) == 1 else None


def _domain(column: str | None, note: str | None) -> str | None:
    """Resolve a domain tag from an explicit domain column, else from the note text.

    Recognised note forms are the ones wordlists actually use:
    `domain-specific (ritual/traditional)`, `domain: ritual/traditional`,
    `register: ritual/traditional` and a bare `ritual/traditional`. Anything else
    (`two candidate senses`, `n.`) is a remark about the row, not a register, and stays in
    `note`.
    """
    if column:
        return column
    if not note:
        return None
    parenthesised = _DOMAIN_PARENTHESISED.search(note)
    if parenthesised is not None:
        return parenthesised.group(1).strip()
    colon = _DOMAIN_COLON.match(note)
    if colon is not None and colon.group(1).strip().lower() in _DOMAIN_COLUMNS:
        return colon.group(2).strip()
    if _DOMAIN_SLASHY.fullmatch(note):
        return note
    return None


def _decode(data: bytes, source_object_id: str) -> str:
    """Strict UTF-8 with BOM removal. An undecodable byte fails, never gets replaced."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[len(b"\xef\xbb\xbf") :]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # `from None`: the decoder message quotes the offending byte; never surface content.
        raise ExtractionFailed("decode_error", source_object_id, None) from None


def _lines(text: str) -> list[str]:
    lines = re.split(r"\r\n|\r|\n", text)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return lines


def _header(
    columns: Sequence[str],
    target_language: str,
    *,
    requested_contact: str | None = None,
) -> _Header | None:
    """Resolve column roles from the header row, falling back to unlabelled position.

    A 3-letter language tag names its column's language: the tag equal to `target_language`
    is the headword column, any other tag is the contact gloss column and names that
    column's language. `note`, `domain` and `pos` name metadata columns. A declared column
    keeps its declared role: positional fallback — the first columns that declare nothing
    at all — may never overwrite it, so a non-target language column never becomes the
    headword column and a metadata column never becomes a headword or gloss column
    (Invariants 8 and 9; ADR-0013 §1). A header that leaves a required role unresolvable
    is refused, never repaired.

    The gloss language follows the header when the header names one, and the request
    otherwise; when both name one they must agree. A header whose language tags all name
    the target language declares no translation column, and a request that disagrees with
    the header's gloss column is a refusal rather than a relabel.

    `None` means the header names neither a headword nor a gloss column at all.
    """
    headword = gloss = note = domain = pos = None
    foreign: list[str] = []
    unlabelled: list[int] = []
    target_tags = 0
    for index, column in enumerate(columns):
        name = column.strip().lower()
        if name in _DOMAIN_COLUMNS:
            domain = index
        elif name in _NOTE_COLUMNS:
            note = index
        elif name in _POS_COLUMNS:
            pos = index
        elif _LANGUAGE_TAG.fullmatch(name):
            if name == target_language:
                target_tags += 1
                if headword is None:
                    headword = index
            else:
                # The first non-target language tag is the gloss column and names it.
                foreign.append(name)
                if gloss is None:
                    gloss = index
        else:
            unlabelled.append(index)
    if headword is None:
        # No column declares the target language, so the headword column can only be one
        # that declares nothing at all: a declared non-target language column is a
        # translation column and a declared metadata column is neither.
        headword = unlabelled[0] if unlabelled else None
    if not foreign and target_tags and len(columns) >= 2:
        # Every language tag is the target language: the header names no translation
        # column, whatever else it names.
        raise WordlistFormatError(WordlistFormatError.GLOSS_LANGUAGE_INVALID)
    if gloss is None and not target_tags:
        # No language tag named a gloss column or the target column: the positional rule
        # takes the next genuinely unlabelled column as the gloss.
        gloss = next((index for index in unlabelled if index != headword), None)
    if headword is None or gloss is None:
        return None

    if foreign:
        gloss_language = foreign[0]
        if requested_contact is not None and requested_contact != gloss_language:
            # The request asks for a translation language this header does not declare.
            raise WordlistFormatError(WordlistFormatError.GLOSS_LANGUAGE_INVALID)
    else:
        # No language tag named the gloss column: the positional gloss column takes the
        # requested language, and a request naming the target language names no
        # translation (Invariant 9).
        gloss_language = (
            requested_contact if requested_contact is not None else DEFAULT_CONTACT_LANGUAGE
        )
        if gloss_language == target_language:
            raise WordlistFormatError(WordlistFormatError.GLOSS_LANGUAGE_INVALID)
    return _Header(
        headword=headword,
        gloss=gloss,
        note=note,
        domain=domain,
        pos=pos,
        contact_language=gloss_language,
        width=len(columns),
    )


def _cell(cells: Sequence[str], index: int | None) -> str | None:
    if index is None or index >= len(cells):
        return None
    value = cells[index].strip()
    return value or None


def _edge(
    from_id: str,
    to_id: str,
    run_id: str,
    now: datetime,
    next_id: IdFactory,
) -> LineageEdge:
    return _build(
        LineageEdge,
        id=next_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run_id,
        created_at=now,
    )


def _promote[M: DomainModel](
    model: M,
    policy: LexicalScorePolicy,
    evidence: Sequence[EvidenceItem],
    target_language: str,
) -> M:
    """Attach the versioned score breakdown and the status the policy may grant.

    Candidate -> supported only: `evaluate_promotion` never returns `validated`
    (AGENTS.md invariant 3; ADR-0013 §3).
    """
    breakdown = policy.compute_score(evidence, target_language)
    status = policy.evaluate_promotion(
        LifecycleStatus.CANDIDATE, breakdown, evidence, target_language
    )
    return model.model_copy(update={"status": status, "score_breakdown": breakdown})


def _build[M: DomainModel](model: type[M], **data: object) -> M:
    """Validate through the domain model; pydantic errors never leak field values."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise SchemaViolation() from exc


__all__ = [
    "METHOD_ID",
    "PRIMARY_LEMMA_ROLE",
    "WordlistAdapter",
    "WordlistEntry",
    "WordlistFormatError",
    "parse_wordlist",
]
