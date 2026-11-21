"""DictionarySessionBuilder: one display-ready entry model for web and print.

Both the portal's Dictionary tab and the print edition read the entries
produced here, so the screen and the printed book cannot disagree about
normalization, letter bucketing, or evidence status.

Pure functions over dicts: no filesystem, no network, no language-specific rules.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from langpipe.lexicon.audit.model import LexicalClass
from langpipe.lexicon.reverse import normalize_search_key

# `Author (1993, 2000) [ASJP]` / `Costa (2002 ABRALIN)` / `Cesarino (2013:7)`
_SOURCE_RE = re.compile(r"^([A-ZÀ-Þ][A-Za-zÀ-ÿ'´\s]*?)\s*\(([^)]*)\)\s*(.*)$")
_YEAR_RE = re.compile(r"(\d{4}[a-z]?)")
_CORPUS_ALIGNMENT = "corpus alignment"

# Validation-basis kinds. Each is derived from what the entry already records:
# the works named in `provenance` and the number of citations mined from the
# corpus. None of them asserts a human review, a gold standard, or a
# confidence class the artifact does not carry (ADR-0027 D10).
BASIS_SOURCE_ASSERTION = "source_assertion"
BASIS_SOURCE_AND_CORPUS = "source_and_corpus"
BASIS_CORPUS_ONLY = "corpus_only"
BASIS_UNRECORDED = "unrecorded"

__all__ = [
    "BASIS_CORPUS_ONLY",
    "BASIS_SOURCE_AND_CORPUS",
    "BASIS_SOURCE_ASSERTION",
    "BASIS_UNRECORDED",
    "DictionarySessionBuilder",
    "normalize_key",
]


def normalize_key(text: str) -> str:
    """Accent-insensitive, case-insensitive key used for matching and bucketing."""
    return normalize_search_key(text or "")


def _letter_for(headword: str) -> str:
    """Bucket letter derived from the normalized key.

    'á' buckets under A, 'õpo' under O. The raw first character is never
    used: the precomposed nasal vowels would each get their own bucket.
    """
    key = normalize_key(headword)
    for ch in key:
        if ch.isalpha():
            return ch.upper()
    return "#"


def _split_works(provenance: str) -> list[tuple[str, str]]:
    """Parse a provenance string into (author, years) work references.

    The `ex:` example tail often contains its own semicolons and parentheses
    (e.g. "Costa (2000b, 2002); ex: kiya-rantsha (avião; lit. barco longo)"),
    so the example tail is cut BEFORE the remaining work clauses are split
    on semicolons. Splitting first would leak the example text into the
    bibliography as spurious works.
    """
    works: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # Cut the example tail first: everything from the first "ex:" onwards.
    head = (provenance or "").split("ex:")[0]

    for chunk in head.split(";"):
        piece = chunk.strip()
        if not piece or piece.lower().startswith(_CORPUS_ALIGNMENT):
            continue

        match = _SOURCE_RE.match(piece)
        if match:
            author = match.group(1).strip()
            years = ", ".join(sorted(set(_YEAR_RE.findall(match.group(2)))))
        else:
            author = piece
            years = ""

        key = (author, years)
        if key not in seen:
            seen.add(key)
            works.append(key)

    return works


def _source_label(author: str, years: str) -> str:
    """'Costa' + '1993, 2000' -> 'Costa (1993, 2000)'."""
    return f"{author} ({years})" if years else author


def _signal_detail(audit: dict[str, Any], field: str) -> str:
    """First audit-signal detail value recorded for `field`.

    The audit rules store the clitic and the base name they detected in the
    signal detail. They are read from the data rather than re-derived here:
    guessing `surface[:-len(clitic)]` would manufacture a morpheme boundary
    the audit never recorded.
    """
    for signal in audit.get("signals") or []:
        detail = signal.get("detail") or {}
        value = detail.get(field)
        if value:
            return str(value)
    return ""


def _validation_basis(provenance: str, attestations: int) -> dict[str, Any]:
    """Describe the basis an entry actually records, not an assumed one.

    The only two signals available in the artifact are the works named in
    `provenance` and the corpus citations. A `validated` entry backed by an
    imported dictionary assertion is exactly that: an imported assertion. When
    nothing is recorded the basis stays `unrecorded` instead of being guessed.
    """
    sources = [_source_label(author, years) for author, years in _split_works(provenance)]
    if sources and attestations:
        kind = BASIS_SOURCE_AND_CORPUS
    elif sources:
        kind = BASIS_SOURCE_ASSERTION
    elif attestations:
        kind = BASIS_CORPUS_ONLY
    else:
        kind = BASIS_UNRECORDED
    return {"kind": kind, "sources": sources, "corpus_attestations": attestations}


class DictionarySessionBuilder:
    """Builds the display-ready dictionary session from canonical lexicon entries."""

    def __init__(
        self,
        target_lang: str = "und",
        target_name: str = "Language",
        contact_lang: str = "por",
        contact_name: str = "Português",
        language_family: str = "",
        glottocode: str = "",
        territory: str = "",
    ) -> None:
        self.target_lang = target_lang
        self.target_name = target_name
        self.contact_lang = contact_lang
        self.contact_name = contact_name
        self.language_family = language_family
        self.glottocode = glottocode
        self.territory = territory

    # -- entry construction -------------------------------------------------

    def _build_entry(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        headword = (raw.get("headword") or "").strip()
        if not headword:
            return None

        audit = raw.get("audit") or {}
        semantics = raw.get("semantics") or {}

        examples = []
        for citation in raw.get("citations") or []:
            examples.append(
                {
                    "citation_id": citation.get("citation_id", ""),
                    "source_ref": citation.get("source_ref", ""),
                    "target_text": citation.get("target_text", ""),
                    "reference_text": citation.get("reference_text", ""),
                    "matched_token": citation.get("matched_token", ""),
                    "score": citation.get("score", 0.0),
                }
            )

        glosses = raw.get(f"glosses_{self.contact_lang}") or raw.get("glosses") or []
        if isinstance(glosses, str):
            glosses = [glosses]

        return {
            "headword": headword,
            "search_key": normalize_key(headword),
            "letter": _letter_for(headword),
            "pos": raw.get("pos", ""),
            "glosses": list(glosses),
            "status": raw.get("status", ""),
            "provenance": raw.get("provenance", ""),
            "examples": examples,
            "domain": semantics.get("primary_domain") or "general",
            "valence": semantics.get("valence", ""),
            "inalienability": semantics.get("inalienability", ""),
            "confidence": semantics.get("confidence", 0.0),
            "related_entry": audit.get("related_entry"),
            "lexical_class": audit.get("lexical_class", "lemma"),
            "flags": list(audit.get("flags") or []),
            "reasons": list(audit.get("reasons") or []),
            "attestations": len(examples),
            # Filled by `_attach_forms` after every entry exists: a form can
            # only be attached once its base is known to be in the payload.
            "forms": [],
            "validation_basis": _validation_basis(raw.get("provenance", ""), len(examples)),
        }

    # -- inflected forms ----------------------------------------------------

    def _attach_forms(
        self,
        built: list[dict[str, Any]],
        sources: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Attach each recorded inflected surface to the entry that owns its base.

        The base is the `audit.related_entry` the audit step recorded, matched
        against a built headword on the normalized key (the same key the rest of
        the pipeline matches on). A form is never promoted to a headword: it is
        listed under its base entry, so the alphabetical body keeps one row per
        lemma (ADR-0027 D9).

        A form whose base is not in the payload cannot be attached to anything.
        Those forms are returned as the session-level `form_index` instead: the
        reader's search can still find the surface and say what it is a form of,
        without the entry appearing in the A-Z list.
        """
        by_key: dict[str, list[dict[str, Any]]] = {}
        for entry in built:
            by_key.setdefault(entry["search_key"], []).append(entry)

        index: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in sources or []:
            audit = raw.get("audit") or {}
            if audit.get("lexical_class") != LexicalClass.INFLECTED_FORM.value:
                continue
            surface = (raw.get("headword") or "").strip()
            base = (audit.get("related_entry") or "").strip() or _signal_detail(audit, "base_name")
            if not surface or not base:
                continue

            search_key = normalize_key(surface)
            base_key = normalize_key(base)
            if (search_key, base_key) in seen:
                continue
            seen.add((search_key, base_key))

            targets = by_key.get(base_key, [])
            pos = raw.get("pos", "")
            clitic = _signal_detail(audit, "clitic")
            for target in targets:
                target["forms"].append(
                    {
                        "surface": surface,
                        "search_key": search_key,
                        "pos": pos,
                        "clitic": clitic,
                    }
                )
            index.append(
                {
                    "surface": surface,
                    "search_key": search_key,
                    "base": base,
                    "base_search_key": base_key,
                    "lemma": targets[0]["headword"] if targets else None,
                    "pos": pos,
                    "clitic": clitic,
                    "attestations": len(raw.get("citations") or []),
                    "provenance": raw.get("provenance", ""),
                }
            )

        for entry in built:
            entry["forms"].sort(key=lambda f: (f["search_key"], f["surface"]))
        index.sort(key=lambda f: (f["search_key"], f["surface"], f["base_search_key"]))
        return index

    # -- facets -------------------------------------------------------------

    @staticmethod
    def _facet(values: list[str]) -> list[dict[str, Any]]:
        counter = Counter(values)
        return [
            {"value": value, "count": count}
            for value, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    # -- bibliography --------------------------------------------------------

    def _build_bibliography(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: Counter[tuple[str, str]] = Counter()
        for entry in entries:
            for work in _split_works(entry.get("provenance", "")):
                counter[work] += 1

        ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
        bibliography = []
        for index, ((author, years), count) in enumerate(ordered, start=1):
            label = f"{author} ({years})" if years else author
            bibliography.append(
                {
                    "index": index,
                    "label": label,
                    "author": author,
                    "years": years,
                    "count": count,
                }
            )
        return bibliography

    # -- public API ---------------------------------------------------------

    def build(
        self,
        entries: list[dict[str, Any]],
        *,
        morphology: list[dict[str, Any]] | None = None,
        parallel_sentences: list[dict[str, Any]] | None = None,
        forms_source: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build the dictionary session payload from canonical lexicon entries.

        `entries` is the published set (the clean view: the lemmas). `forms_source`
        is where inflected surfaces are read from; it defaults to `entries`, so a
        caller that already passes a mixed list keeps working. Callers that
        publish a filtered view (the portal, the print exporter) must pass the
        full lexicon here, or the excluded inflected forms are simply unseen.
        """
        built = [e for e in (self._build_entry(raw) for raw in entries) if e is not None]
        built.sort(key=lambda e: (e["search_key"], e["headword"]))

        form_index = self._attach_forms(
            built, forms_source if forms_source is not None else entries
        )

        letter_counts = Counter(e["letter"] for e in built)
        letters = [
            {"letter": letter, "count": letter_counts[letter]} for letter in sorted(letter_counts)
        ]

        return {
            "meta": {
                "target_lang": self.target_lang,
                "target_name": self.target_name,
                "contact_lang": self.contact_lang,
                "contact_name": self.contact_name,
                "language_family": self.language_family,
                "glottocode": self.glottocode,
                "territory": self.territory,
                "total_entries": len(built),
                "total_letters": len(letters),
                "total_forms": len(form_index),
                "generated_from": f"exports/{self.target_lang}/dictionary.json",
            },
            "entries": built,
            "letters": letters,
            "facets": {
                "pos": self._facet([e["pos"] for e in built]),
                "domain": self._facet([e["domain"] for e in built]),
                "status": self._facet([e["status"] for e in built]),
            },
            "morphology": list(morphology or []),
            "parallel_sentences": list(parallel_sentences or []),
            "form_index": form_index,
            "bibliography": self._build_bibliography(built),
        }
