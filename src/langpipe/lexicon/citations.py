"""Attested Citation and Example Miner for LKB Lexicons (WP 1.1).

Associates verified dictionary lemmas with attested, authentic parallel sentence
citations extracted from bilingual corpora (e.g. ScriptureEarth USFM and parallel reference texts).

Completely language-agnostic: operates on arbitrary (target, reference) text pairs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParallelCorpusVerse:
    """One aligned parallel verse from bilingual corpus."""

    book: str
    chapter: int
    verse: int
    target_text: str
    reference_text: str

    @property
    def source_ref(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse}"


@dataclass
class AttestedCitation:
    """An attested sentence citation exemplifying a dictionary lemma in authentic context."""

    citation_id: str
    source_ref: str
    target_text: str
    reference_text: str
    matched_token: str
    headword: str
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "source_ref": self.source_ref,
            "target_text": self.target_text,
            "reference_text": self.reference_text,
            "matched_token": self.matched_token,
            "headword": self.headword,
            "score": self.score,
        }


def clean_usfm_text(raw_usfm: str) -> str:
    """Clean USFM markup, stripping footnotes, cross-references, and markers."""
    # Remove footnotes: \f ... \f* and \fe ... \fe*
    text = re.sub(r"\\f[e]?\s+.*?(?:\\f[e]?\*)", "", raw_usfm, flags=re.DOTALL)
    # Remove cross-references: \x ... \x*
    text = re.sub(r"\\x\s+.*?(?:\\x\*)", "", text, flags=re.DOTALL)
    # Remove all remaining backslash markers like \p, \q, \v 1, \c 1, \s1
    text = re.sub(r"\\[a-zA-Z0-9\+\*]+", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_usfm_verses(usfm_content: str, book_code: str) -> dict[tuple[int, int], str]:
    """Parse USFM string into mapping of (chapter, verse) -> clean text."""
    verses: dict[tuple[int, int], str] = {}
    current_chapter = 0
    current_verse = 0
    current_text_parts: list[str] = []

    def commit_verse() -> None:
        nonlocal current_text_parts
        if current_chapter > 0 and current_verse > 0 and current_text_parts:
            combined = " ".join(current_text_parts)
            cleaned = clean_usfm_text(combined)
            if cleaned:
                verses[(current_chapter, current_verse)] = cleaned
        current_text_parts = []

    lines = usfm_content.splitlines()
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue

        c_match = re.match(r"^\\c\s+(\d+)", line_s)
        if c_match:
            commit_verse()
            current_chapter = int(c_match.group(1))
            current_verse = 0
            continue

        v_match = re.match(r"^\\v\s+(\d+)(?:-(\d+))?\s*(.*)", line_s)
        if v_match:
            commit_verse()
            current_verse = int(v_match.group(1))
            rest = v_match.group(3)
            if rest:
                current_text_parts.append(rest)
            continue

        # Skip section headings and intros
        if re.match(r"^\\[smh]\d?", line_s):
            continue

        if current_chapter > 0 and current_verse > 0:
            current_text_parts.append(line_s)

    commit_verse()
    return verses


def parse_reference_verses(ref_content: str) -> dict[tuple[int, int], str]:
    """Parse reference text file into mapping of (chapter, verse) -> clean text."""
    verses: dict[tuple[int, int], str] = {}
    current_chapter = 0
    current_verse = 0
    current_text_parts: list[str] = []

    def commit_verse() -> None:
        nonlocal current_text_parts
        if current_chapter > 0 and current_verse > 0 and current_text_parts:
            combined = " ".join(current_text_parts)
            # Remove any footnote markers like \fn ... \*fn
            combined = re.sub(r"\\fn.*?\\\*fn", "", combined, flags=re.DOTALL)
            combined = re.sub(r"\\[a-zA-Z0-9\-\*]+", " ", combined)
            cleaned = re.sub(r"\s+", " ", combined).strip()
            if cleaned:
                verses[(current_chapter, current_verse)] = cleaned
        current_text_parts = []

    lines = ref_content.splitlines()
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue

        # Look for \v Abbrev.Chapter.Verse or \v Chapter:Verse
        v_match = re.match(r"^\\v\s+(?:[A-Za-z0-9]+\.)?(\d+)[.:](\d+)", line_s)
        if v_match:
            commit_verse()
            current_chapter = int(v_match.group(1))
            current_verse = int(v_match.group(2))
            continue

        # Skip metadata headers
        if line_s.startswith("\\"):
            continue

        if current_chapter > 0 and current_verse > 0:
            current_text_parts.append(line_s)

    commit_verse()
    return verses


def load_parallel_verses_from_dirs(
    target_dir: Path, reference_dir: Path
) -> list[ParallelCorpusVerse]:
    """Load and pair verses from parallel corpora directories."""
    parallel_verses: list[ParallelCorpusVerse] = []
    if not target_dir.exists() or not reference_dir.exists():
        return parallel_verses

    # Collect target USFM files
    target_files = {p.stem.upper(): p for p in target_dir.glob("*.usfm")}
    ref_files = {p.stem.upper(): p for p in reference_dir.glob("*.txt")}

    common_books = sorted(set(target_files.keys()) & set(ref_files.keys()))

    for book in common_books:
        t_path = target_files[book]
        r_path = ref_files[book]

        t_content = t_path.read_text(encoding="utf-8", errors="replace")
        r_content = r_path.read_text(encoding="utf-8", errors="replace")

        t_verses = parse_usfm_verses(t_content, book)
        r_verses = parse_reference_verses(r_content)

        common_keys = sorted(set(t_verses.keys()) & set(r_verses.keys()))
        for chap, verse_num in common_keys:
            t_txt = t_verses[(chap, verse_num)]
            r_txt = r_verses[(chap, verse_num)]
            if t_txt and r_txt:
                parallel_verses.append(
                    ParallelCorpusVerse(
                        book=book,
                        chapter=chap,
                        verse=verse_num,
                        target_text=t_txt,
                        reference_text=r_txt,
                    )
                )

    return parallel_verses


@dataclass
class CorpusIndex:
    """Precomputed inverted token index for instant corpus citation retrieval."""

    verses: list[ParallelCorpusVerse]
    token_to_verses: dict[str, list[tuple[int, str]]]

    @classmethod
    def build(cls, verses: list[ParallelCorpusVerse]) -> CorpusIndex:
        index: dict[str, list[tuple[int, str]]] = {}
        for idx, v in enumerate(verses):
            words = re.findall(r"[\w\-\~]+", v.target_text.lower())
            seen_in_verse: set[str] = set()
            for w in words:
                clean_w = w.strip("-")
                if clean_w and clean_w not in seen_in_verse:
                    seen_in_verse.add(clean_w)
                    index.setdefault(clean_w, []).append((idx, w))
        return cls(verses=verses, token_to_verses=index)

    def find_citations(self, headword: str, max_citations: int = 2) -> list[AttestedCitation]:
        hw_clean = headword.strip().lower()
        if not hw_clean or len(hw_clean) < 2:
            return []

        matches: list[tuple[int, str, bool]] = []
        seen_verse_ids: set[int] = set()

        # 1. Exact matches
        for v_idx, raw_token in self.token_to_verses.get(hw_clean, []):
            if v_idx not in seen_verse_ids:
                seen_verse_ids.add(v_idx)
                matches.append((v_idx, raw_token, True))

        # 2. Prefix matches (if headword >= 3 chars)
        if len(hw_clean) >= 3 and len(matches) < max_citations * 5:
            for token_key, v_list in self.token_to_verses.items():
                if (
                    token_key.startswith(hw_clean)
                    and token_key != hw_clean
                    and len(token_key) <= len(hw_clean) + 6
                ):
                    for v_idx, raw_token in v_list:
                        if v_idx not in seen_verse_ids:
                            seen_verse_ids.add(v_idx)
                            matches.append((v_idx, raw_token, False))
                            if len(matches) >= max_citations * 10:
                                break

        candidates: list[tuple[float, AttestedCitation]] = []
        for v_idx, matched_token, is_exact in matches:
            pv = self.verses[v_idx]
            target = pv.target_text
            word_count = len(target.split())
            length_penalty = abs(word_count - 16) * 0.02
            exact_bonus = 0.5 if is_exact else 0.0
            score = round(max(0.1, 1.0 + exact_bonus - length_penalty), 3)

            cit_id = hashlib.sha256(f"{hw_clean}:{pv.source_ref}:{target}".encode()).hexdigest()[
                :12
            ]

            candidates.append(
                (
                    score,
                    AttestedCitation(
                        citation_id=cit_id,
                        source_ref=pv.source_ref,
                        target_text=target,
                        reference_text=pv.reference_text,
                        matched_token=matched_token,
                        headword=hw_clean,
                        score=score,
                    ),
                )
            )

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in candidates[:max_citations]]


def find_citations_for_lemma(
    headword: str,
    parallel_verses: list[ParallelCorpusVerse] | CorpusIndex,
    max_citations: int = 2,
) -> list[AttestedCitation]:
    """Find authentic parallel sentence citations for a specific lemma."""
    if isinstance(parallel_verses, CorpusIndex):
        index = parallel_verses
    else:
        index = CorpusIndex.build(parallel_verses)
    return index.find_citations(headword, max_citations=max_citations)


def enrich_lexicon_with_citations(
    dict_data: dict[str, Any],
    parallel_verses: list[ParallelCorpusVerse] | CorpusIndex,
    max_citations: int = 2,
) -> dict[str, Any]:
    """Attach authentic corpus citations to each entry in the dictionary."""
    if isinstance(parallel_verses, CorpusIndex):
        index = parallel_verses
    else:
        index = CorpusIndex.build(parallel_verses)

    enriched = dict(dict_data)
    entries = list(dict_data.get("lexicon", []))
    new_entries: list[dict[str, Any]] = []

    cited_count = 0

    for e in entries:
        e_copy = dict(e)
        hw = e.get("headword", "")
        citations = index.find_citations(hw, max_citations=max_citations)
        e_copy["citations"] = [c.to_dict() for c in citations]
        if citations:
            cited_count += 1
            if not e_copy.get("example"):
                e_copy["example"] = citations[0].target_text
                e_copy["trans"] = citations[0].reference_text

        new_entries.append(e_copy)

    enriched["lexicon"] = new_entries
    enriched["total_entries"] = len(new_entries)
    enriched["citations_stats"] = {
        "total_parallel_verses": len(index.verses),
        "entries_with_citations": cited_count,
        "citation_coverage_pct": round(cited_count / max(1, len(new_entries)) * 100, 1),
    }
    return enriched


ROOT = Path(__file__).resolve().parent.parent.parent.parent


def enrich_persisted_dictionary(
    lang_code: str,
    corpus_target_dir: Path | None = None,
    corpus_reference_dir: Path | None = None,
) -> dict[str, Any]:
    """Mine citations and persist enriched dictionary files on disk."""
    if corpus_target_dir is None:
        corpus_target_dir = ROOT / "var" / f"scriptureearth_{lang_code}"
    if corpus_reference_dir is None:
        corpus_reference_dir = ROOT / "var" / "external" / "parallel_por"

    verses = load_parallel_verses_from_dirs(corpus_target_dir, corpus_reference_dir)
    if not verses:
        raise ValueError(
            f"No parallel verses found between {corpus_target_dir} and {corpus_reference_dir}"
        )

    index = CorpusIndex.build(verses)

    lang_dir = ROOT / "exports" / lang_code
    dict_file = lang_dir / "dictionary.json"
    clean_file = lang_dir / "dictionary.clean.json"

    updated_files = []
    enriched_clean: dict[str, Any] = {}

    if clean_file.exists():
        with open(clean_file, encoding="utf-8") as f:
            clean_data = json.load(f)
        enriched_clean = enrich_lexicon_with_citations(clean_data, index)
        with open(clean_file, "w", encoding="utf-8") as f:
            json.dump(enriched_clean, f, indent=2, ensure_ascii=False)
        updated_files.append(str(clean_file))

    if dict_file.exists():
        with open(dict_file, encoding="utf-8") as f:
            full_data = json.load(f)
        enriched_full = enrich_lexicon_with_citations(full_data, index)
        with open(dict_file, "w", encoding="utf-8") as f:
            json.dump(enriched_full, f, indent=2, ensure_ascii=False)
        updated_files.append(str(dict_file))

    return {
        "language_code": lang_code,
        "parallel_verses_count": len(verses),
        "updated_files": updated_files,
        "clean_coverage": enriched_clean.get("citations_stats"),
    }
