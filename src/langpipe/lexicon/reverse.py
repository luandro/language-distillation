"""Language-agnostic reverse bi-directional lexicon index (Milestone 1, WP 1.3).

Constructs an inverted index mapping contact language glosses/headwords to target
indigenous language lemmas, preserving grammatical category, semantic domains,
valence, and attested corpus citations.

Strict language-isolation: All logic is parameterized by contact/target language
codes and conventions without language hardcoding.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_PAREN_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_SEPARATOR_RE = re.compile(r"[,;/\n]+")
_ARTICLE_RE = re.compile(r"^(?:o|a|os|as|um|uma|uns|umas)\s+", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s-]", re.UNICODE)


def normalize_search_key(text: str) -> str:
    """Normalize text for accent-insensitive, case-insensitive index lookups."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = _PUNCT_RE.sub(" ", stripped).lower()
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_contact_headwords(gloss: str) -> list[str]:
    """Parse a composite gloss string into individual contact-language headword keys.

    Handles parenthetical removal, punctuation splitting, and article stripping.
    Example:
        'criança, filho (menino)' -> ['criança', 'filho', 'menino']
        'o sol' -> ['sol', 'o sol']
    """
    if not gloss or not gloss.strip():
        return []

    # First collect any parenthesized content words (e.g. 'criança (menino)' -> extract 'menino')
    paren_matches = _PAREN_RE.findall(gloss)
    paren_inner = []
    for match in paren_matches:
        inner = match[1:-1].strip()
        # Skip pure grammatical tags like (s), (v), (f), (gír)
        if len(inner) > 2 and not inner.startswith(("v.", "s.", "adj.", "f.", "m.", "adv.")):
            paren_inner.append(inner)

    # Strip parentheses from main gloss string
    clean_gloss = _PAREN_RE.sub(" ", gloss)

    # Split by separators
    parts = _SEPARATOR_RE.split(clean_gloss)
    all_raw = [p.strip() for p in parts if p.strip()] + paren_inner

    headwords: list[str] = []
    seen: set[str] = set()

    for item in all_raw:
        item_clean = re.sub(r"\s+", " ", item).strip().strip(".-_\"'()")
        if not item_clean or len(item_clean) < 2:
            continue

        item_lower = item_clean.lower()
        if item_lower not in seen:
            seen.add(item_lower)
            headwords.append(item_clean)

        # If it has a leading article, also add the bare headword
        bare = _ARTICLE_RE.sub("", item_clean).strip()
        if bare and bare.lower() != item_lower and len(bare) >= 2 and bare.lower() not in seen:
            seen.add(bare.lower())
            headwords.append(bare)

    return headwords


@dataclass
class ReverseSense:
    """Target language sense corresponding to a contact language headword."""

    target_headword: str
    pos: str
    original_gloss: str
    provenance: str = ""
    valence: str | None = None
    inalienability: str | None = None
    primary_domain: str | None = None
    subdomains: list[str] = field(default_factory=list)
    attestation_count: int = 0
    sample_citation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReverseEntry:
    """A contact language headword with one or more target language senses."""

    contact_headword: str
    normalized_key: str
    senses: list[ReverseSense] = field(default_factory=list)
    total_attestations: int = 0

    def add_sense(self, sense: ReverseSense) -> None:
        # Avoid duplicate senses for the same target headword
        for existing in self.senses:
            if existing.target_headword == sense.target_headword and existing.pos == sense.pos:
                # Merge or upgrade citation info if new sense has more citations
                if sense.attestation_count > existing.attestation_count:
                    existing.attestation_count = sense.attestation_count
                    existing.sample_citation = sense.sample_citation
                return
        self.senses.append(sense)
        self.total_attestations += sense.attestation_count
        # Sort senses by attestation count descending, then target headword
        self.senses.sort(key=lambda s: (-s.attestation_count, s.target_headword))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contact_headword": self.contact_headword,
            "normalized_key": self.normalized_key,
            "total_attestations": self.total_attestations,
            "sense_count": len(self.senses),
            "senses": [s.to_dict() for s in self.senses],
        }


class ReverseLexiconIndex:
    """Inverted index mapping contact language vocabulary to target language lemmas."""

    def __init__(self, contact_language: str = "por") -> None:
        self.contact_language = contact_language
        self._entries: dict[str, ReverseEntry] = {}
        self._normalized_map: dict[str, list[str]] = {}

    @property
    def entries(self) -> dict[str, ReverseEntry]:
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def build_from_lexicon(
        self,
        lexicon_entries: list[dict[str, Any]],
        contact_lang_field: str | None = None,
    ) -> ReverseLexiconIndex:
        """Index a list of dictionary entry dicts into the reverse dictionary."""
        field_key = contact_lang_field or f"glosses_{self.contact_language}"

        for entry in lexicon_entries:
            target_hw = entry.get("headword") or entry.get("lemma")
            if not target_hw:
                continue

            pos = entry.get("pos", "unk")
            provenance = entry.get("provenance", "")
            citations = entry.get("citations") or []
            attestation_count = len(citations)
            sample_citation = citations[0] if citations else None

            semantics = entry.get("semantics") or {}
            valence = semantics.get("valence")
            inalienability = semantics.get("inalienability")
            primary_domain = semantics.get("primary_domain")
            subdomains = semantics.get("subdomains") or []

            # Extract contact gloss strings
            raw_glosses: list[str] = []
            if field_key in entry and isinstance(entry[field_key], list):
                raw_glosses.extend(entry[field_key])
            elif "glosses" in entry and isinstance(entry["glosses"], list):
                raw_glosses.extend(entry["glosses"])
            elif "trans" in entry and isinstance(entry["trans"], str):
                raw_glosses.append(entry["trans"])
            elif "meaning" in entry and isinstance(entry["meaning"], str):
                raw_glosses.append(entry["meaning"])

            for raw_gloss in raw_glosses:
                extracted_keys = extract_contact_headwords(raw_gloss)
                for key in extracted_keys:
                    normalized = normalize_search_key(key)
                    if not normalized:
                        continue

                    # Canonical capitalization for the entry
                    canonical_key = key.lower()
                    if canonical_key not in self._entries:
                        self._entries[canonical_key] = ReverseEntry(
                            contact_headword=canonical_key,
                            normalized_key=normalized,
                        )
                        if normalized not in self._normalized_map:
                            self._normalized_map[normalized] = []
                        self._normalized_map[normalized].append(canonical_key)

                    sense = ReverseSense(
                        target_headword=target_hw,
                        pos=pos,
                        original_gloss=raw_gloss,
                        provenance=provenance,
                        valence=valence,
                        inalienability=inalienability,
                        primary_domain=primary_domain,
                        subdomains=subdomains,
                        attestation_count=attestation_count,
                        sample_citation=sample_citation,
                    )
                    self._entries[canonical_key].add_sense(sense)

        return self

    def lookup(
        self,
        query: str,
        exact: bool = False,
        limit: int = 50,
    ) -> list[ReverseEntry]:
        """Search the reverse index by query term.

        Supports exact matching, accent-insensitive matching, and prefix matching.
        """
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        norm_query = normalize_search_key(cleaned_query)
        if not norm_query:
            return []

        # 1. Exact canonical or normalized match
        exact_matches: list[ReverseEntry] = []
        if cleaned_query.lower() in self._entries:
            exact_matches.append(self._entries[cleaned_query.lower()])
        elif norm_query in self._normalized_map:
            for canonical in self._normalized_map[norm_query]:
                entry = self._entries.get(canonical)
                if entry and entry not in exact_matches:
                    exact_matches.append(entry)

        if exact or (exact_matches and len(exact_matches) >= limit):
            return exact_matches[:limit]

        # 2. Prefix / Substring matching on normalized keys
        prefix_matches: list[ReverseEntry] = []
        for norm_key, canonical_list in self._normalized_map.items():
            if norm_key == norm_query:
                continue
            if norm_key.startswith(norm_query) or (
                len(norm_query) >= 3 and f" {norm_query}" in norm_key
            ):
                for canonical in canonical_list:
                    entry = self._entries.get(canonical)
                    if entry and entry not in exact_matches and entry not in prefix_matches:
                        prefix_matches.append(entry)

        # Sort prefix matches by total attestations descending, then length, then alphabetical
        prefix_matches.sort(
            key=lambda e: (-e.total_attestations, len(e.contact_headword), e.contact_headword)
        )

        combined = exact_matches + prefix_matches
        return combined[:limit]

    def to_dict(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Serialize reverse index to a dictionary sorted alphabetically."""
        sorted_entries = sorted(self._entries.values(), key=lambda e: e.contact_headword)
        meta = {
            "contact_language": self.contact_language,
            "total_contact_headwords": len(sorted_entries),
            "total_senses": sum(len(e.senses) for e in sorted_entries),
        }
        if metadata:
            meta.update(metadata)

        return {
            "metadata": meta,
            "entries": [e.to_dict() for e in sorted_entries],
        }

    def save_json(self, output_path: Path | str, metadata: dict[str, Any] | None = None) -> None:
        """Write reverse dictionary index to disk."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict(metadata=metadata)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
