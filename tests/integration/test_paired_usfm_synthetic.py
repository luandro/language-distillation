"""Synthetic paired-USFM parity for scripture coordinate matching (WP3.13, M3-PLAN §6).

Two synthetic USFM editions of the same corpus exercise every coordinate phenomenon a real
ScriptureEarth pair can contain: numeric bridges overlapping two single labels (``\\v 3-4``
against ``\\v 3`` and ``\\v 4``), note-separated verse pieces, verses present on only one side,
alternate/suffix verse labels, a verse-free front-matter book (``XXF``), partial bridge
coverage and declared-versification compatibility. Expected membership comes from an
**independent** rescan oracle built in this module: it expands bridges, keeps verse-only
locators and builds the bipartite overlap graph itself. It never imports or calls
``CanonicalLocatorAligner``, so it cannot inherit the aligner's answer; self-check tests pin the
oracle's own behavior, including the cases it must refuse.

Token links come only from the explicit test-injected ``MockTokenAligner`` of
``tests.fixtures.alignment`` under a ``mock@0.1.0`` reference. That double is a compiler-free
test facility, is never named eflomal in diagnostics, and never satisfies native requirements.
The separately marked ``native_alignment`` suite in ``test_eflomal_native.py`` (WP3.0/WP3.8)
proves the production adapter: this module calls ``eflomal@0.1.0`` only to prove that a native
failure leaves the Stage 4 evidence intact, and only when the pinned distribution is installed.

Every test runs against both repositories through the shared ``ctx`` fixture, so memory and
PostgreSQL prove the same pair semantics (M3-PLAN §6: zero database skips in required mode).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from langpipe.alignment.base import AlignmentConfig, AlignmentSide
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AlignmentMode,
    AlignmentStatus,
    ArtifactKind,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    RunStatus,
)
from langpipe.domain.errors import AlignmentFailed
from langpipe.domain.models.alignment import SegmentAlignment
from langpipe.extraction.service import extract_source
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.normalization.service import normalize_extraction
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.service import tokenize_normalization
from tests.fixtures.alignment import MockTokenAligner
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

USFM = "text/x-usfm"
VERSIFICATION = "synthetic-vrs-1"
SCRIPTURE = AlignmentConfig(namespace="scripture", versification_id=VERSIFICATION)
MOCK_TOKEN = "mock@0.1.0"
STRUCTURAL = "structural"
AUTHORITY = "synthetic-pairs-steward"
# Opaque suffix verse labels: digits followed by letters, never collapsed into the bare number
# (ADR-0011 §3). Any letter suffix is a distinct coordinate, not only ``a``.
_SUFFIX_LABEL = re.compile(r"[0-9]+[a-z]+")
NATIVE_FAILURE_CODES = frozenset(
    {"backend_unavailable", "backend_failed", "backend_timeout", "invalid_adapter_output"}
)
# The pinned upstream distribution's fixed failure for a requested seed (ADR-0011 §6).
_NATIVE_SEED_CODE = "unsupported_seed"

# ---------------------------------------------------------------------------------------------
# Synthetic paired USFM: one source edition and one target edition of the same corpus
# ---------------------------------------------------------------------------------------------

# Source phenomena: a bridge overlapping two target labels; a note-split verse; a verse the
# target omits (5); suffix labels with no target counterpart (8a and 9b); a heading after
# verse text.
_SOURCE_TST = """\\id TST
\\c 1
\\v 1 alpha
\\v 3-4 gamma
\\v 5 epsilon\\f + \\ft a note\\f* epsilon tail
\\p
\\v 7 eta
\\s a heading
\\v 8a theta
\\v 9b theta bis
"""
# Target phenomena: the two single labels covered by the bridge; a verse the source omits (2);
# a bare version of the source's suffix label that must stay a distinct coordinate.
_TARGET_TST = """\\id TST
\\c 1
\\v 1 um
\\v 2 dois
\\v 3 tres
\\v 4 quatro
\\v 6 seis
\\v 7 sete
\\v 8 oito
"""
# Verse-free front matter on both sides, in the shape of a real XXF book.
_SOURCE_XXF = """\\id XXF
\\mt2 Front matter
\\c 1
\\p
Just front matter text.
"""
_TARGET_XXF = """\\id XXF
\\mt2 Front matter
\\c 1
\\p
Other front matter text.
"""

BOOKS: dict[str, tuple[bytes, bytes]] = {
    "TST": (_SOURCE_TST.encode("utf-8"), _TARGET_TST.encode("utf-8")),
    "XXF": (_SOURCE_XXF.encode("utf-8"), _TARGET_XXF.encode("utf-8")),
}


# ---------------------------------------------------------------------------------------------
# Independent coordinate oracle (test-only; does not import the production aligner)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Piece:
    book: str
    chapter: int
    label: str
    verse: bool


def _positions(label: str) -> tuple[int | str, ...] | None:
    """Coordinate positions claimed by one verse label; ``None`` when malformed.

    Any letter suffix (``3a``, ``8b``) keeps its opaque label and never collapses into the
    bare number, matching ``CanonicalLocatorAligner``; it matches only that exact label.
    """
    text = label.strip()
    if text.isdigit():
        return (int(text),)
    if _SUFFIX_LABEL.fullmatch(text):
        return (text,)  # opaque suffix label; never collapsed into the bare number
    if "-" in text:
        start, _, end = text.partition("-")
        if start.isdigit() and end.isdigit() and int(start) <= int(end):
            return tuple(range(int(start), int(end) + 1))
    return None


def _book_pieces(data: bytes) -> list[_Piece]:
    """Pieces of one USFM book by independent scan: verse pieces plus non-verse text units.

    The scan is marker-based, not line-based: a note (``\\f ...\\f*``, ``\\x ...\\x*``) ends the
    current piece wherever it appears, so text after its closer on the same line starts a new
    piece of the same verse. Paragraph and poetry markers do not end a verse piece. Headings,
    introductions, unknown blocks and note text are recorded as non-verse pieces because the
    aligner reports them as unmatched with a ``unit_not_verse`` reason.
    """
    pieces: list[_Piece] = []
    book = ""
    chapter = 0
    label = ""
    in_verse = False
    awaiting_resume = False
    in_hidden = False  # inside a note: text there is note content, not a unit of its own
    text = data.decode("utf-8")
    for match in re.finditer(r"\\([A-Za-z]+)(\*?)|\n|([^\\\n]+)", text):
        marker, closer, body = match.group(1), match.group(2), match.group(3)
        if marker == "id":
            book = text[match.end() :].split()[0]
        elif marker == "c":
            chapter = int(text[match.end() :].split()[0])
            label = ""
            in_verse = False
            awaiting_resume = False
        elif marker == "v":
            label = text[match.end() :].split()[0]
            pieces.append(_Piece(book, chapter, label, verse=True))
            in_verse = True
            awaiting_resume = False
        elif marker in {"f", "fe", "x"} and not closer:
            awaiting_resume = False
            in_hidden = True
        elif marker in {"f", "x"} and closer:
            in_hidden = False
            awaiting_resume = in_verse  # text after the closer resumes the verse
        elif body and awaiting_resume:
            pieces.append(_Piece(book, chapter, label, verse=True))
            awaiting_resume = False
        elif body and not in_hidden and not in_verse:
            pieces.append(_Piece(book, chapter, label, verse=False))
    return pieces


@dataclass(frozen=True)
class _Edition:
    """One edition's pieces, per-book verse-piece counts and coordinate keys."""

    pieces: tuple[_Piece, ...]
    inventory: Mapping[str, int]
    coverage: Mapping[int, frozenset[str]]

    @property
    def verse_pieces(self) -> tuple[_Piece, ...]:
        """Verse pieces only, in document order."""
        return tuple(piece for piece in self.pieces if piece.verse)

    @property
    def non_verse(self) -> tuple[_Piece, ...]:
        """Non-verse text units (headings, introductions, notes, unknown blocks)."""
        return tuple(piece for piece in self.pieces if not piece.verse)


def _edition(books: Mapping[str, bytes]) -> _Edition:
    pieces: list[_Piece] = []
    inventory: dict[str, int] = defaultdict(int)
    for name in sorted(books):
        for piece in _book_pieces(books[name]):
            pieces.append(piece)
            if piece.verse:
                inventory[piece.book] += 1
    coverage: dict[int, frozenset[str]] = {}
    for index, piece in enumerate(pieces):
        if not piece.verse:
            continue
        values = _positions(piece.label)
        if values is None:
            continue  # malformed label: never a coordinate, never part of a group
        coverage[index] = frozenset(f"{piece.book}|{piece.chapter}|{value}" for value in values)
    return _Edition(tuple(pieces), dict(inventory), coverage)


@dataclass
class Oracle:
    """Expected structure of one pair, derived without the production aligner."""

    source: _Edition
    target: _Edition
    components: list[tuple[tuple[int, ...], tuple[int, ...]]] = field(default_factory=list)

    def compute(self) -> None:
        holders: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for side, edition in ((0, self.source), (1, self.target)):
            for index, values in edition.coverage.items():
                for value in values:
                    holders[value].append((side, index))
        nodes: list[tuple[int, int]] = [(0, index) for index in self.source.coverage] + [
            (1, index) for index in self.target.coverage
        ]
        position_of = {node: position for position, node in enumerate(nodes)}
        parent = list(range(len(nodes)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        for value_nodes in holders.values():
            # A coordinate claimed by only one side never bridges the two sides.
            if {node[0] for node in value_nodes} != {0, 1}:
                continue
            first = position_of[value_nodes[0]]
            for other in value_nodes[1:]:
                union(first, position_of[other])
        groups: dict[int, tuple[list[int], list[int]]] = {}
        for node in nodes:
            left, right = groups.setdefault(find(position_of[node]), ([], []))
            (left if node[0] == 0 else right).append(node[1])
        self.components = [
            (tuple(sorted(left)), tuple(sorted(right)))
            for left, right in groups.values()
            if left and right
        ]

    # ----- expected counts -------------------------------------------------------------------

    @property
    def group_count(self) -> int:
        return len(self.components)

    @property
    def matched_source(self) -> int:
        return sum(len(left) for left, _ in self.components)

    @property
    def matched_target(self) -> int:
        return sum(len(right) for _, right in self.components)

    @property
    def unmatched_source(self) -> int:
        """Source verse pieces with no counterpart; non-verse units are excluded here."""
        return len(self.source.coverage) - self.matched_source

    @property
    def unmatched_target(self) -> int:
        """Target verse pieces with no counterpart; non-verse units are excluded here."""
        return len(self.target.coverage) - self.matched_target

    @property
    def book_inventory(self) -> dict[str, list[int]]:
        """(source, target) verse-piece counts per declared book, zero-retaining.

        Books declared on either side stay visible, so a verse-free edition such as XXF is
        reported as ``[0, 0]`` rather than silently disappearing from the inventory.
        """
        declared = {
            *(piece.book for piece in self.source.pieces),
            *(piece.book for piece in self.target.pieces),
        }
        return {
            book: [self.source.inventory.get(book, 0), self.target.inventory.get(book, 0)]
            for book in sorted(declared)
        }

    def coverage_pairs(self) -> list[tuple[frozenset[str], frozenset[str]]]:
        """Per-component coordinate coverage of the source and the target side."""
        pairs: list[tuple[frozenset[str], frozenset[str]]] = []
        for left, right in self.components:
            source_coverage: set[str] = set()
            target_coverage: set[str] = set()
            for index in left:
                source_coverage |= self.source.coverage[index]
            for index in right:
                target_coverage |= self.target.coverage[index]
            pairs.append((frozenset(source_coverage), frozenset(target_coverage)))
        return pairs

    def structural_components(self) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
        """Components whose two sides claim exactly the same coordinate set."""
        return [
            component
            for component, (left, right) in zip(self.components, self.coverage_pairs(), strict=True)
            if left == right
        ]

    def partial_components(self) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
        """Components whose two sides claim different coordinate sets: candidate, not structural."""
        return [
            component
            for component, (left, right) in zip(self.components, self.coverage_pairs(), strict=True)
            if left != right
        ]

    def bridge_components(self) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
        """Components whose source side covers more than one coordinate position."""
        return [
            component
            for component, (left, _right) in zip(
                self.components, self.coverage_pairs(), strict=True
            )
            if len(left) > 1 or any(len(self.source.coverage[index]) > 1 for index in component[0])
        ]


def _oracle(books: Mapping[str, tuple[bytes, bytes]] | None = None) -> Oracle:
    editions = BOOKS if books is None else books
    oracle = Oracle(
        source=_edition({name: pair[0] for name, pair in editions.items()}),
        target=_edition({name: pair[1] for name, pair in editions.items()}),
    )
    oracle.compute()
    return oracle


# ---------------------------------------------------------------------------------------------
# Synthetic pipeline
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Side:
    source_id: str
    language: str
    normalization_run_id: str
    segment_ids: tuple[str, ...]
    tokenization_run_id: str


@dataclass(frozen=True)
class PairFlow:
    source: Side
    target: Side

    def side(self, language: str) -> AlignmentSide:
        side = self.source if language == self.source.language else self.target
        return AlignmentSide(side.source_id, side.language, side.normalization_run_id)


def _build_side(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    language: str,
    books: Mapping[str, tuple[bytes, bytes]],
) -> Side:
    objects: list[dict[str, str]] = []
    for name in sorted(books):
        relative = f"{name}.usfm"
        write_origin_file(tmp_path, relative, books[name][0 if language == "mzr" else 1])
        objects.append({"path": relative, "media_type": USFM})
    manifest = manifest_data(
        key=key,
        title=f"Synthetic {language} edition",
        objects=objects,
    )
    manifest["languages"] = [language]
    manifest["policy"] = {
        "mode": "distill_only",
        "access_class": "community",
        "authority": AUTHORITY,
        "allow": ["align"],
    }
    registered = register_source(ctx, write_manifest(tmp_path, manifest, name=f"{key}.yaml"))
    ingest_source(ctx, registered.source.id)
    extraction = extract_source(ctx, registered.source.id, extractor="usfm@0.1.0")
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    verse_segments = [
        item
        for item in ctx.repo.list_segments_for_run(normalization.run.id)
        if item.locator.get("unit") == "verse"
    ]
    return Side(
        source_id=registered.source.id,
        language=language,
        normalization_run_id=normalization.run.id,
        segment_ids=tuple(item.id for item in verse_segments),
        tokenization_run_id=tokenization.run.id,
    )


def _pair(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    books: Mapping[str, tuple[bytes, bytes]] | None = None,
) -> PairFlow:
    editions = BOOKS if books is None else books
    source = _build_side(ctx, tmp_path / "source", f"{key}-mzr", "mzr", editions)
    target = _build_side(ctx, tmp_path / "target", f"{key}-por", "por", editions)
    return PairFlow(source=source, target=target)


def _stage4(ctx: AppContext, pair: PairFlow, *, config: AlignmentConfig = SCRIPTURE) -> Any:
    return SegmentAlignmentService(ctx).align(pair.side("mzr"), pair.side("por"), config=config)


def _groups(ctx: AppContext, segment_run_id: str) -> list[SegmentAlignment]:
    return list(ctx.repo.list_segment_alignments_for_run(segment_run_id))


def _segment(
    ctx: AppContext, pair: PairFlow, language: str, label: str, *, part: int | None = None
) -> Any:
    """The normalized verse segment of one side by verse label (and piece when given)."""
    side = pair.source if language == "mzr" else pair.target
    found = [
        item
        for item in ctx.repo.list_segments_for_run(side.normalization_run_id)
        if item.locator.get("unit") == "verse" and str(item.locator.get("verse")) == label
    ]
    if part is not None:
        found = [item for item in found if item.locator.get("part") == part]
    assert len(found) == 1, (label, part, len(found))
    return found[0]


def _tokens(ctx: AppContext, pair: PairFlow, language: str, segment_id: str) -> list[Any]:
    side = pair.source if language == "mzr" else pair.target
    return [
        token
        for token in ctx.repo.list_tokens(segment_id)
        if token.run_id == side.tokenization_run_id
    ]


def _side_tokens(
    ctx: AppContext, pair: PairFlow, language: str, segment_ids: tuple[str, ...]
) -> set[str]:
    return {
        token.id for segment_id in segment_ids for token in _tokens(ctx, pair, language, segment_id)
    }


def _mock_links(
    alignment_ids: list[str],
) -> dict[str, tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]]:
    """Explicit link matrix: index 0 of each side, in both directions."""
    return {alignment_id: (((0, 0),), ((0, 0),)) for alignment_id in alignment_ids}


def _stage5_mock(ctx: AppContext, pair: PairFlow, segment_run_id: str) -> Any:
    links = _mock_links([group.id for group in _groups(ctx, segment_run_id)])
    return TokenAlignmentService(ctx, aligners=VersionedRegistry((MockTokenAligner(links),))).align(
        segment_run_id,
        source_tokenization_run_id=pair.source.tokenization_run_id,
        target_tokenization_run_id=pair.target.tokenization_run_id,
        method=MOCK_TOKEN,
        config=SCRIPTURE,
    )


def _report_payload(
    ctx: AppContext, segment_alignment_run_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Stage 4 report payload of one run plus every matched Stage 4 report artifact present."""
    for object_id, role in ctx.repo.list_run_io(segment_alignment_run_id):
        if role is not RunIoRole.OUTPUT:
            continue
        artifact = ctx.repo.get_artifact(object_id)
        if artifact.kind is not ArtifactKind.ALIGNMENT_FILE:
            continue
        return json.loads(ctx.artifact_store.read_bytes(artifact.sha256)), []
    return None


def _unmatched_segments(
    ctx: AppContext, pair: PairFlow, segment_alignment_run_id: str
) -> tuple[set[str], set[str]]:
    """(source, target) unmatched verse-segment ids reported by the Stage 4 report of one run."""
    found = _report_payload(ctx, segment_alignment_run_id)
    assert found is not None
    payload, _ = found
    source_ids = set(pair.source.segment_ids)
    target_ids = set(pair.target.segment_ids)
    return (
        {
            entry["segment_id"]
            for entry in payload["unmatched_source"]
            if entry["segment_id"] in source_ids
        },
        {
            entry["segment_id"]
            for entry in payload["unmatched_target"]
            if entry["segment_id"] in target_ids
        },
    )


def _non_verse_segments(ctx: AppContext, pair: PairFlow, language: str) -> set[str]:
    """Extracted non-verse segments of one side (headings, notes, unknown blocks)."""
    side = pair.source if language == "mzr" else pair.target
    return {
        segment.id
        for segment in ctx.repo.list_segments_for_run(side.normalization_run_id)
        if str(segment.locator.get("unit")) != "verse"
    }


def _verse_segments(ctx: AppContext, pair: PairFlow) -> set[str]:
    """Extracted verse segments of either side, across both editions."""
    return {
        segment.id
        for side in (pair.source, pair.target)
        for segment in ctx.repo.list_segments_for_run(side.normalization_run_id)
        if str(segment.locator.get("unit")) == "verse"
    }


def _assert_group_members_are_verse_segments(ctx: AppContext, groups: Any) -> None:
    for group in groups:
        for member_id in (*group.source_segment_ids, *group.target_segment_ids):
            segment = ctx.repo.get_segment(member_id)
            if segment.locator.get("unit") != "verse":
                raise AssertionError("group member is not a verse segment")


def _assert_no_empty_sided_group(groups: Any) -> None:
    for group in groups:
        if not group.source_segment_ids or not group.target_segment_ids:
            raise AssertionError("group with an empty side was published")


def _assert_unmatched_coordinates_agree(
    ctx: AppContext, pair: PairFlow, summary: Any, oracle: Oracle
) -> None:
    """The aligner's unmatched counts equal the oracle's, once non-verse units are excluded.

    The aligner reports every extracted non-verse unit as unmatched with a fixed
    ``unit_not_verse`` reason (ADR-0011 §3); the oracle only models verse coordinates. The
    two agree once that difference is accounted for, and the unmatched sets cover exactly the
    selected verse segments minus the matched ones.
    """
    assert summary.alignments == oracle.group_count
    assert summary.unmatched_source - oracle.unmatched_source == len(
        _non_verse_segments(ctx, pair, "mzr")
    )
    assert summary.unmatched_target - oracle.unmatched_target == len(
        _non_verse_segments(ctx, pair, "por")
    )
    unmatched_source, unmatched_target = _unmatched_segments(ctx, pair, summary.run.id)
    assert len(unmatched_source) == oracle.unmatched_source
    assert len(unmatched_target) == oracle.unmatched_target
    groups = _groups(ctx, summary.run.id)
    matched_source = {member for group in groups for member in group.source_segment_ids}
    matched_target = {member for group in groups for member in group.target_segment_ids}
    assert matched_source | unmatched_source == set(pair.source.segment_ids)
    assert matched_target | unmatched_target == set(pair.target.segment_ids)
    assert not (matched_source & unmatched_source)
    assert not (matched_target & unmatched_target)


def _report_unmatched_split(
    ctx: AppContext, pair: PairFlow, segment_alignment_run_id: str
) -> tuple[set[str], set[str], set[str], set[str]]:
    """Split one Stage 4 report's unmatched entries into (verse, non-verse) per side.

    This is the same separation the realdata suite's ``_unmatched_split`` performs: the
    report's unmatched lists cover **all** extracted units (verse locators without a
    counterpart plus headings, notes and front matter), while the oracle is verse-only. The
    regression tests below pin that contract so a missing operator input on the realdata side
    cannot silently change these semantics.
    """
    payload, _ = _report_payload(ctx, segment_alignment_run_id)
    verse_ids = _verse_segments(ctx, pair)
    verse_source, verse_target, other_source, other_target = set(), set(), set(), set()
    for side, verse_bucket, other_bucket in (
        ("unmatched_source", verse_source, other_source),
        ("unmatched_target", verse_target, other_target),
    ):
        for entry in payload[side]:
            segment_id = entry["segment_id"]
            (verse_bucket if segment_id in verse_ids else other_bucket).add(segment_id)
    return verse_source, verse_target, other_source, other_target


# ---------------------------------------------------------------------------------------------
# Structural (compiler-free) suite
# ---------------------------------------------------------------------------------------------


def test_bridge_overlap_forms_exactly_one_group(ctx: AppContext, tmp_path: Path) -> None:
    """``\\v 3-4`` on one side overlapping ``\\v 3`` and ``\\v 4`` is exactly one 1:2 group."""
    pair = _pair(ctx, tmp_path, "pairs-bridge")
    summary = _stage4(ctx, pair)
    oracle = _oracle()

    _assert_unmatched_coordinates_agree(ctx, pair, summary, oracle)

    bridge = _segment(ctx, pair, "mzr", "3-4")
    groups = [
        group for group in _groups(ctx, summary.run.id) if bridge.id in group.source_segment_ids
    ]
    assert len(groups) == 1
    member_labels = sorted(
        str(ctx.repo.get_segment(item).locator["verse"]) for item in groups[0].target_segment_ids
    )
    assert (len(groups[0].source_segment_ids), member_labels) == (1, ["3", "4"])
    assert groups[0].status.value == STRUCTURAL
    assert groups[0].mode is AlignmentMode.CANONICAL
    assert len(oracle.bridge_components()) == 1


def test_note_separated_pieces_share_one_group_membership(ctx: AppContext, tmp_path: Path) -> None:
    """Note-separated pieces of one verse join the same component; the note never joins one."""
    pair = _pair(ctx, tmp_path, "pairs-note")
    summary = _stage4(ctx, pair)
    oracle = _oracle()
    _assert_unmatched_coordinates_agree(ctx, pair, summary, oracle)

    pieces = [
        item
        for item in ctx.repo.list_segments_for_run(pair.source.normalization_run_id)
        if item.locator.get("unit") == "verse" and item.locator.get("verse") == "5"
    ]
    assert {item.locator["part"] for item in pieces} == {0, 1}
    _assert_group_members_are_verse_segments(ctx, _groups(ctx, summary.run.id))
    assert summary.alignments == oracle.group_count
    # Both source pieces of verse 5 are unmatched: the target has no verse 5.
    unmatched_source, _ = _unmatched_segments(ctx, pair, summary.run.id)
    assert {item.id for item in pieces} <= unmatched_source


def test_absent_verses_reported_without_empty_groups(ctx: AppContext, tmp_path: Path) -> None:
    """Verses present on only one side are unmatched entries, never empty-sided groups."""
    pair = _pair(ctx, tmp_path, "pairs-absent")
    summary = _stage4(ctx, pair)
    groups = _groups(ctx, summary.run.id)
    oracle = _oracle()

    _assert_no_empty_sided_group(groups)
    assert summary.unmatched_source > 0
    assert summary.unmatched_target > 0
    _assert_unmatched_coordinates_agree(ctx, pair, summary, oracle)

    unmatched_source, unmatched_target = _unmatched_segments(ctx, pair, summary.run.id)
    matched_source = {member for group in groups for member in group.source_segment_ids}
    matched_target = {member for group in groups for member in group.target_segment_ids}
    assert matched_source | unmatched_source == set(pair.source.segment_ids)
    assert matched_target | unmatched_target == set(pair.target.segment_ids)
    assert not (matched_source & unmatched_source)
    assert not (matched_target & unmatched_target)
    # Non-verse units (headings, notes, front matter) are reported unmatched with a fixed
    # reason, never grouped — verified by the oracle agreement helper above.
    assert _non_verse_segments(ctx, pair, "mzr")


def test_suffix_label_matches_only_its_exact_opaque_key(ctx: AppContext, tmp_path: Path) -> None:
    """``\\v 8a`` has no counterpart and stays unmatched; ``\\v 8`` is a distinct coordinate."""
    pair = _pair(ctx, tmp_path, "pairs-suffix")
    summary = _stage4(ctx, pair)

    source = _segment(ctx, pair, "mzr", "8a")
    target = _segment(ctx, pair, "por", "8")
    groups = _groups(ctx, summary.run.id)
    assert all(source.id not in group.source_segment_ids for group in groups)
    assert all(target.id not in group.target_segment_ids for group in groups)
    _assert_no_empty_sided_group(groups)
    unmatched_source, unmatched_target = _unmatched_segments(ctx, pair, summary.run.id)
    assert source.id in unmatched_source
    assert target.id in unmatched_target


def test_letter_suffix_labels_stay_opaque(ctx: AppContext, tmp_path: Path) -> None:
    """Every valid opaque suffix label (``8a`` and ``9b``) is its own coordinate.

    A ``b`` label must survive the same treatment as an ``a`` label: it never collapses into
    the bare number, never matches a target's bare verse, and is reported unmatched.
    """
    pair = _pair(ctx, tmp_path, "pairs-suffix-b")
    summary = _stage4(ctx, pair)

    label_a = _segment(ctx, pair, "mzr", "8a")
    label_b = _segment(ctx, pair, "mzr", "9b")
    target_eight = _segment(ctx, pair, "por", "8")
    groups = _groups(ctx, summary.run.id)
    for source in (label_a, label_b):
        assert all(source.id not in group.source_segment_ids for group in groups)
    assert all(target_eight.id not in group.target_segment_ids for group in groups)
    _assert_no_empty_sided_group(groups)
    unmatched_source, unmatched_target = _unmatched_segments(ctx, pair, summary.run.id)
    assert {label_a.id, label_b.id} <= unmatched_source
    assert target_eight.id in unmatched_target
    # Two suffix labels are two distinct coordinates, never one merged coordinate.
    assert label_a.locator["verse"] != label_b.locator["verse"]


def test_non_verse_units_never_enter_verse_expectations(ctx: AppContext, tmp_path: Path) -> None:
    """Non-verse unmatched units are counted apart from verse-only oracle expectations.

    The realdata helper's contract: verse-locator unmatched ids equal the oracle, while
    headings, notes and front matter are unmatched by construction and never mixed into the
    verse comparison. The complete selected input partitions into matched plus both unmatched
    populations.
    """
    pair = _pair(ctx, tmp_path, "pairs-nonverse")
    summary = _stage4(ctx, pair)
    oracle = _oracle()

    verse_source, verse_target, other_source, other_target = _report_unmatched_split(
        ctx, pair, summary.run.id
    )
    expected_verse_source = {
        piece
        for piece in pair.source.segment_ids
        if piece
        not in {item for group in _groups(ctx, summary.run.id) for item in group.source_segment_ids}
    }
    expected_verse_target = {
        piece
        for piece in pair.target.segment_ids
        if piece
        not in {item for group in _groups(ctx, summary.run.id) for item in group.target_segment_ids}
    }
    assert verse_source == expected_verse_source
    assert verse_target == expected_verse_target
    assert other_source == _non_verse_segments(ctx, pair, "mzr")
    assert other_target == _non_verse_segments(ctx, pair, "por")
    # The oracle's verse counts and the report's verse-only counts are the same numbers.
    assert len(verse_source) == oracle.unmatched_source
    assert len(verse_target) == oracle.unmatched_target
    # All-unit report counts are strictly larger when non-verse units exist.
    payload, _ = _report_payload(ctx, summary.run.id)
    non_verse = _non_verse_segments(ctx, pair, "mzr") | _non_verse_segments(ctx, pair, "por")
    if non_verse:
        assert summary.unmatched_source > oracle.unmatched_source
        assert summary.unmatched_target > oracle.unmatched_target
        assert len(payload["unmatched_source"]) == len(verse_source) + len(
            _non_verse_segments(ctx, pair, "mzr")
        )
        assert len(payload["unmatched_target"]) == len(verse_target) + len(
            _non_verse_segments(ctx, pair, "por")
        )


def test_non_verse_units_partition_the_selected_input(ctx: AppContext, tmp_path: Path) -> None:
    """Matched groups plus both unmatched populations exactly cover the selected input."""
    pair = _pair(ctx, tmp_path, "pairs-partition")
    summary = _stage4(ctx, pair)
    oracle = _oracle()
    _assert_unmatched_coordinates_agree(ctx, pair, summary, oracle)

    groups = _groups(ctx, summary.run.id)
    verse_source, verse_target, other_source, other_target = _report_unmatched_split(
        ctx, pair, summary.run.id
    )
    matched_source = {member for group in groups for member in group.source_segment_ids}
    matched_target = {member for group in groups for member in group.target_segment_ids}
    selected_source = set(pair.source.segment_ids) | _non_verse_segments(ctx, pair, "mzr")
    selected_target = set(pair.target.segment_ids) | _non_verse_segments(ctx, pair, "por")
    assert matched_source | verse_source | other_source == selected_source
    assert matched_target | verse_target | other_target == selected_target
    assert not (matched_source & (verse_source | other_source))
    assert not (matched_target & (verse_target | other_target))


def test_verse_free_book_contributes_no_verse_units(ctx: AppContext, tmp_path: Path) -> None:
    """The XXF front-matter book yields no verse segments and no group members on either side."""
    pair = _pair(ctx, tmp_path, "pairs-versefree")
    for side in (pair.source, pair.target):
        verse_units = [
            item
            for item in ctx.repo.list_segments_for_run(side.normalization_run_id)
            if item.locator.get("unit") == "verse" and str(item.locator.get("book")) == "XXF"
        ]
        assert not verse_units, "front matter produced verse-shaped segments"

    summary = _stage4(ctx, pair)
    groups = _groups(ctx, summary.run.id)
    _assert_no_empty_sided_group(groups)
    oracle = _oracle()
    assert oracle.book_inventory["XXF"] == [0, 0]
    _assert_unmatched_coordinates_agree(ctx, pair, summary, oracle)


def test_matching_declared_versification_passes(ctx: AppContext, tmp_path: Path) -> None:
    """Two sides sharing one declared versification align on coordinates alone."""
    pair = _pair(ctx, tmp_path, "pairs-versification-match")
    summary = _stage4(ctx, pair)

    assert summary.run.status is RunStatus.SUCCEEDED
    assert ctx.repo.get_run(summary.run.id).config["versification_id"] == VERSIFICATION
    assert _groups(ctx, summary.run.id)
    assert all(group.status.value == STRUCTURAL for group in _groups(ctx, summary.run.id))


def test_incompatible_declared_versification_fails(ctx: AppContext, tmp_path: Path) -> None:
    """Scripture-shaped locators with no declared versification are rejected, not reinterpreted."""
    pair = _pair(ctx, tmp_path, "pairs-versification-missing")
    with pytest.raises(AlignmentFailed) as excinfo:
        SegmentAlignmentService(ctx).align(
            pair.side("mzr"),
            pair.side("por"),
            config=AlignmentConfig(namespace="scripture", versification_id=None),
        )
    assert excinfo.value.code == "incompatible_versification"


def test_partial_coverage_is_candidate_not_structural(ctx: AppContext, tmp_path: Path) -> None:
    """A bridge claiming a coordinate the other side lacks is candidate, excluded from Stage 5."""
    books = BOOKS | {
        "TST": (b"\\id TST\n\\c 1\n\\v 1 a\n\\v 3-4 b\n", b"\\id TST\n\\c 1\n\\v 3 c\n")
    }
    pair = _pair(ctx, tmp_path, "pairs-partial", books)
    summary = _stage4(ctx, pair)

    groups = _groups(ctx, summary.run.id)
    assert len(groups) == 1
    # ``candidate`` is excluded from Stage 5 selection: only structural/approved groups are
    # eligible (ADR-0011 §2), so this group must never reach a token aligner.
    assert groups[0].status is AlignmentStatus.CANDIDATE
    assert groups[0].status.value != STRUCTURAL
    assert groups[0].score is None
    oracle = _oracle(books)
    assert len(oracle.partial_components()) == 1
    assert oracle.structural_components() == []


def test_oracle_matches_aligner_for_both_books(ctx: AppContext, tmp_path: Path) -> None:
    """Independent rescan oracle: components, unmatched counts and book inventory agree."""
    pair = _pair(ctx, tmp_path, "pairs-oracle")
    summary = _stage4(ctx, pair)
    oracle = _oracle()
    _assert_unmatched_coordinates_agree(ctx, pair, summary, oracle)

    groups = _groups(ctx, summary.run.id)
    structural = [group for group in groups if group.status.value == STRUCTURAL]
    assert len(structural) == len(oracle.structural_components())
    assert {len(group.source_segment_ids) for group in structural} == {1}
    assert {len(group.target_segment_ids) for group in structural} <= {1, 2}

    inventory = oracle.book_inventory
    assert inventory["TST"] == [len(pair.source.segment_ids), len(pair.target.segment_ids)]
    assert inventory["XXF"] == [0, 0]
    assert set(pair.source.segment_ids) == {
        segment.id
        for segment in ctx.repo.list_segments_for_run(pair.source.normalization_run_id)
        if segment.locator.get("unit") == "verse" and segment.locator.get("book") == "TST"
    }


def test_stage5_mock_edges_map_to_selected_occurrences(ctx: AppContext, tmp_path: Path) -> None:
    """Mock (never eflomal) links resolve to occurrences of the pinned tokenization runs."""
    pair = _pair(ctx, tmp_path, "pairs-stage5")
    segment = _stage4(ctx, pair)
    token = _stage5_mock(ctx, pair, segment.run.id)

    assert token.run.stage is RunStage.TOKEN_ALIGNMENT
    assert token.run.status is RunStatus.SUCCEEDED
    edges = ctx.repo.list_token_alignment_edges_for_run(token.run.id)
    assert edges
    alignments = {group.id: group for group in _groups(ctx, segment.run.id)}
    for edge in edges:
        group = alignments[edge.segment_alignment_id]
        source_tokens = _side_tokens(ctx, pair, "mzr", group.source_segment_ids)
        target_tokens = _side_tokens(ctx, pair, "por", group.target_segment_ids)
        assert edge.source_token_id in source_tokens
        assert edge.target_token_id in target_tokens
        assert ctx.repo.get_token(edge.source_token_id).run_id == pair.source.tokenization_run_id
        assert ctx.repo.get_token(edge.target_token_id).run_id == pair.target.tokenization_run_id
    assert ctx.repo.get_run(pair.source.tokenization_run_id).stage is RunStage.TOKENIZATION
    assert ctx.repo.get_run(pair.target.tokenization_run_id).stage is RunStage.TOKENIZATION


def test_mock_edges_use_selected_symmetrization_only(ctx: AppContext, tmp_path: Path) -> None:
    """The mock run persists all three directions with symmetrization metadata per direction."""
    pair = _pair(ctx, tmp_path, "pairs-directions")
    segment = _stage4(ctx, pair)
    token = _stage5_mock(ctx, pair, segment.run.id)

    edges = ctx.repo.list_token_alignment_edges_for_run(token.run.id)
    directions = {edge.direction.value for edge in edges}
    assert directions == {"forward", "reverse", "symmetrized"}
    for edge in edges:
        if edge.direction.value in {"forward", "reverse"}:
            assert edge.symmetrization.value == "none"
        else:
            assert edge.symmetrization.value == "intersection"


def test_ancestry_reaches_both_sources(ctx: AppContext, tmp_path: Path) -> None:
    """Every group derives from its member segments; ancestry is the two source ids."""
    pair = _pair(ctx, tmp_path, "pairs-ancestry")
    summary = _stage4(ctx, pair)

    for group in _groups(ctx, summary.run.id):
        parents = {
            edge.to_id
            for edge in ctx.repo.list_lineage_edges(group.id, "out")
            if edge.kind is LineageKind.DERIVED_FROM
        }
        assert parents == set((*group.source_segment_ids, *group.target_segment_ids))
        assert set(ancestor_source_ids(ctx.repo, group.id)) == {
            pair.source.source_id,
            pair.target.source_id,
        }
    report = summary.report
    assert report is not None
    assert set(ancestor_source_ids(ctx.repo, report.id)) == {
        pair.source.source_id,
        pair.target.source_id,
    }


def test_rerun_reuses_segment_run_without_new_groups(ctx: AppContext, tmp_path: Path) -> None:
    """Identical reruns reuse the segment run and publish no additional group rows."""
    pair = _pair(ctx, tmp_path, "pairs-rerun")
    first = _stage4(ctx, pair)
    second = _stage4(ctx, pair)

    assert second.reused is True
    assert second.run.id == first.run.id
    assert len(_groups(ctx, first.run.id)) == len(_groups(ctx, second.run.id))


def test_distill_only_pair_is_trainable_but_not_exportable(ctx: AppContext, tmp_path: Path) -> None:
    """ADR-0025: pair evidence trains under distill_only; outward operations stay denied."""
    pair = _pair(ctx, tmp_path, "pairs-trainable")
    segment = _stage4(ctx, pair)
    token = _stage5_mock(ctx, pair, segment.run.id)

    outputs: list[Any] = [
        *ctx.repo.list_segment_alignments_for_run(segment.run.id),
        *ctx.repo.list_token_alignment_edges_for_run(token.run.id),
    ]
    assert outputs
    for value in outputs:
        assert effective_decision(ctx.repo, value.id, Operation.DIRECT_TRAINING) is (
            PolicyDecision.ALLOW
        )
        assert effective_decision(ctx.repo, value.id, Operation.THIRD_PARTY_API) is (
            PolicyDecision.DENY
        )


def test_native_failure_keeps_segment_evidence(ctx: AppContext, tmp_path: Path) -> None:
    """A failing native token run leaves Stage 4 groups intact and creates no edges.

    The production ``eflomal@0.1.0`` adapter has no seed control (ADR-0011 §6), so a pinned seed
    is a deterministic adapter-side failure inside the real native path — not a mock. The
    failure is identified by its machine-readable fixed code (``AlignmentFailed.code``), never
    by ``str(exc)``, and the failed run belongs to Stage 5: ``TOKEN_ALIGNMENT``. The test
    snapshots the already-succeeded token runs so it can prove they kept no new edges.
    """
    pair = _pair(ctx, tmp_path, "pairs-native-failure")
    segment = _stage4(ctx, pair)
    groups = _groups(ctx, segment.run.id)
    assert groups
    edges_before = len(ctx.repo.list_token_alignment_edges_for_run(segment.run.id))
    failed_before = ctx.repo.count_runs(RunStatus.FAILED)

    service = TokenAlignmentService(ctx)
    failed_ids: list[str] = []
    original_fail = service.recorder.fail

    def capture_failure(run_id: str, error: BaseException, *args: Any, **kwargs: Any) -> Any:
        failed_ids.append(run_id)
        return original_fail(run_id, error, *args, **kwargs)

    service.recorder.fail = capture_failure  # type: ignore[method-assign]
    try:
        service.align(
            segment.run.id,
            source_tokenization_run_id=pair.source.tokenization_run_id,
            target_tokenization_run_id=pair.target.tokenization_run_id,
            method="eflomal@0.1.0",
            config=AlignmentConfig(
                namespace="scripture",
                versification_id=VERSIFICATION,
                random_seed=7,
            ),
        )
    except AlignmentFailed as exc:
        assert exc.code == _NATIVE_SEED_CODE
    else:
        raise AssertionError("the native adapter accepted a pinned seed")
    finally:
        service.recorder.fail = original_fail  # type: ignore[method-assign]

    assert len(failed_ids) == 1
    assert ctx.repo.count_runs(RunStatus.FAILED) == failed_before + 1
    failed = ctx.repo.get_run(failed_ids[0])
    assert failed.stage is RunStage.TOKEN_ALIGNMENT
    assert failed.status is RunStatus.FAILED
    assert ctx.repo.list_token_alignment_edges_for_run(failed.id) == []
    assert [
        object_id for object_id, role in ctx.repo.list_run_io(failed.id) if role is RunIoRole.OUTPUT
    ] == []

    # Stage 4 evidence and its run are untouched by the Stage 5 failure.
    assert _groups(ctx, segment.run.id) == groups
    assert ctx.repo.get_run(segment.run.id).status is RunStatus.SUCCEEDED
    assert len(ctx.repo.list_token_alignment_edges_for_run(segment.run.id)) == edges_before
    assert ctx.repo.count_runs(RunStatus.SUCCEEDED) >= 1
    assert all(group.status.value == STRUCTURAL for group in groups)


@pytest.mark.native_alignment
def test_native_batch_is_nonempty_with_bounded_valid_edges(ctx: AppContext, tmp_path: Path) -> None:
    """With the pinned native distribution installed, the pair produces bounded valid edges.

    Asserts structure only — every endpoint inside its group and the link count bounded by the
    group's token cross-product — never a fixed linguistic link matrix or accuracy claim.
    """
    pair = _pair(ctx, tmp_path, "pairs-native-batch")
    segment = _stage4(ctx, pair)
    groups = _groups(ctx, segment.run.id)
    assert groups
    token = TokenAlignmentService(ctx).align(
        segment.run.id,
        source_tokenization_run_id=pair.source.tokenization_run_id,
        target_tokenization_run_id=pair.target.tokenization_run_id,
        method="eflomal@0.1.0",
        config=SCRIPTURE,
    )

    edges = ctx.repo.list_token_alignment_edges_for_run(token.run.id)
    alignments = {group.id: group for group in groups}
    for edge in edges:
        group = alignments[edge.segment_alignment_id]
        assert edge.source_token_id in _side_tokens(ctx, pair, "mzr", group.source_segment_ids)
        assert edge.target_token_id in _side_tokens(ctx, pair, "por", group.target_segment_ids)
    for group in groups:
        source_count = len(_side_tokens(ctx, pair, "mzr", group.source_segment_ids))
        target_count = len(_side_tokens(ctx, pair, "por", group.target_segment_ids))
        linked = {
            (edge.source_token_id, edge.target_token_id)
            for edge in edges
            if edge.segment_alignment_id == group.id
        }
        assert len(linked) <= source_count * target_count


def test_reports_carry_no_surface_text_or_paths(ctx: AppContext, tmp_path: Path) -> None:
    """Both reports hold identifiers, counts and codes only — never verse text or book paths."""
    pair = _pair(ctx, tmp_path, "pairs-noleak")
    segment = _stage4(ctx, pair)
    token = _stage5_mock(ctx, pair, segment.run.id)

    for entry in (segment.report, token.report):
        assert entry is not None
        raw = ctx.artifact_store.read_bytes(entry.sha256)
        for marker in (
            b"alpha",
            b"gamma",
            b"epsilon",
            b"um",
            b"tres",
            b"quatro",
            b"oito",
            b"TST.usfm",
            str(tmp_path).encode("utf-8"),
        ):
            assert marker not in raw, "report leaked surface content"
    # The verse vocabulary is present in the corpus but absent from both reports.
    raw_bytes = b"\n".join(
        ctx.repo.get_segment(segment_id).raw_text.encode("utf-8")
        for segment_id in (*pair.source.segment_ids, *pair.target.segment_ids)
    )
    for entry in (segment.report, token.report):
        assert entry is not None
        raw = ctx.artifact_store.read_bytes(entry.sha256)
        assert raw_bytes not in raw


def test_run_io_records_selected_inputs_and_outputs(ctx: AppContext, tmp_path: Path) -> None:
    """Stage 4 and Stage 5 runs record their selected inputs and outputs as run I/O."""
    pair = _pair(ctx, tmp_path, "pairs-runio")
    segment = _stage4(ctx, pair)
    token = _stage5_mock(ctx, pair, segment.run.id)

    segment_inputs = {
        object_id
        for object_id, role in ctx.repo.list_run_io(segment.run.id)
        if role is RunIoRole.INPUT
    }
    assert pair.source.source_id in segment_inputs
    assert pair.target.source_id in segment_inputs
    for group in _groups(ctx, segment.run.id):
        assert {
            object_id
            for object_id, role in ctx.repo.list_run_io(segment.run.id)
            if role is RunIoRole.OUTPUT
        } >= {group.id}

    token_inputs = {
        object_id
        for object_id, role in ctx.repo.list_run_io(token.run.id)
        if role is RunIoRole.INPUT
    }
    assert segment.run.id in token_inputs
    assert any(
        ctx.repo.entity_type_of(object_id) is EntityType.SEGMENT for object_id in token_inputs
    )


# ---------------------------------------------------------------------------------------------
# Independent-oracle self checks (the oracle must fail on wrong expectations)
# ---------------------------------------------------------------------------------------------


def test_oracle_expands_numeric_bridges() -> None:
    """A numeric bridge expands to its covered positions; a suffix label stays opaque."""
    edition = _edition({"TST": b"\\id TST\n\\c 1\n\\v 3-4 text\n\\v 5a other\n"})
    assert [piece.label for piece in edition.verse_pieces] == ["3-4", "5a"]
    keys = [edition.coverage[index] for index, piece in enumerate(edition.pieces) if piece.verse]
    assert keys == [{"TST|1|3", "TST|1|4"}, {"TST|1|5a"}]
    assert edition.inventory == {"TST": 2}


def test_oracle_counts_note_separated_pieces_twice() -> None:
    """A note ends a piece: text after the note is a second piece with the same keys."""
    edition = _edition({"TST": b"\\id TST\n\\c 1\n\\v 5 before\\f + \\ft n\\f* after\n"})
    assert [piece.label for piece in edition.verse_pieces] == ["5", "5"]
    verse_keys = [
        edition.coverage[index] for index, piece in enumerate(edition.pieces) if piece.verse
    ]
    assert verse_keys == [{"TST|1|5"}, {"TST|1|5"}]
    # Note text is recorded as a non-verse unit, never as a coordinate key.
    assert edition.non_verse


def test_oracle_ignores_non_verse_units() -> None:
    """Headings, introductions and front matter yield no coordinate keys."""
    edition = _edition({"XXF": b"\\id XXF\n\\mt2 Front\n\\c 1\n\\p\nJust front matter text.\n"})
    assert edition.verse_pieces == ()
    assert edition.coverage == {}
    assert edition.inventory == {}


def test_oracle_rejects_collapsed_suffix_matching() -> None:
    """The oracle must not treat ``8a`` as covering coordinate ``8``."""
    source = _edition({"TST": b"\\id TST\n\\c 1\n\\v 8a x\n"})
    target = _edition({"TST": b"\\id TST\n\\c 1\n\\v 8 y\n"})
    oracle = Oracle(source=source, target=target)
    oracle.compute()
    assert oracle.group_count == 0
    assert oracle.unmatched_source == 1
    assert oracle.unmatched_target == 1


def test_oracle_rejects_bridge_grouping_for_covered_side() -> None:
    """A bridge claiming a coordinate only present on one side never forms a component."""
    source = _edition({"TST": b"\\id TST\n\\c 1\n\\v 3-4 x\n"})
    target = _edition({"TST": b"\\id TST\n\\c 1\n\\v 3 y\n"})
    oracle = Oracle(source=source, target=target)
    oracle.compute()
    assert oracle.group_count == 1
    assert oracle.structural_components() == []
    assert oracle.partial_components() == oracle.components
    assert oracle.coverage_pairs() == [({"TST|1|3", "TST|1|4"}, {"TST|1|3"})]
    assert len(oracle.bridge_components()) == 1


def test_oracle_group_count_for_the_committed_pair() -> None:
    """The committed pair's independent component, coverage and inventory counts are stable."""
    oracle = _oracle()
    coverage = oracle.coverage_pairs()
    assert oracle.group_count == 3
    assert len(oracle.structural_components()) == 3
    assert len(oracle.partial_components()) == 0
    assert coverage == [
        ({"TST|1|1"}, {"TST|1|1"}),
        ({"TST|1|3", "TST|1|4"}, {"TST|1|3", "TST|1|4"}),
        ({"TST|1|7"}, {"TST|1|7"}),
    ]
    assert [len(left) for left, _ in oracle.components] == [1, 1, 1]
    assert [len(right) for _, right in oracle.components] == [1, 2, 1]
    assert oracle.matched_source == 3
    assert oracle.matched_target == 4
    assert oracle.unmatched_source == 4  # verse 5 (two pieces) and verses 8a and 9b
    assert oracle.unmatched_target == 3  # verses 2, 6 and 8
    assert oracle.book_inventory == {"TST": [7, 7], "XXF": [0, 0]}


def test_mock_aligner_is_never_called_eflomal() -> None:
    """The compiler-free double is never registered as the native backend name."""
    registry = VersionedRegistry((MockTokenAligner({}),))
    assert registry.names() == ["mock@0.1.0"]
    assert "eflomal" not in registry.names()


# ---------------------------------------------------------------------------------------------
# Signed-metadata contract: the realdata gate's own validators, exercised compiler-free
# ---------------------------------------------------------------------------------------------


def _realdata_gate() -> Any:
    """The realdata suite's actual validators and gate, imported lazily.

    The realdata module imports the synthetic pipeline helpers from this module, so a
    module-level import here would be circular. Importing inside the tests keeps a single
    definition of the gate — this module never carries a second copy (senior review item 1).
    """
    from tests.integration import test_scriptureearth_parallel as realdata

    return realdata


def _committed_counts() -> dict[str, Any]:
    """The committed expectations file, parsed once and never written to."""
    path = Path(__file__).with_name("expected") / "scriptureearth_parallel_counts.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_counts_file_is_one_of_its_two_legal_states() -> None:
    """The committed expectations file is a *legal* record, validated by its own status.

    The checked-in file has two legal states, and the test accepts either — provided each one
    really satisfies the state it declares, through the realdata suite's **actual**
    validators and gate (never through copies):

    - ``unsigned`` template: structurally valid, ``null`` counts and ``UNREVIEWED``
      edition/versification placeholders, and **rejected by the review gate**;
    - ``reviewed`` record: structurally valid, complete reviewed fields and integer counts, and
      **accepted by the review gate**.

    No assertion pins the disk file to one state, so a genuine senior signing keeps the default
    suite green (senior review item 1). Both states are additionally proved independently of disk
    by the in-memory constructors, so the committed file's state never decides a verdict.
    """
    realdata = _realdata_gate()
    expected = _committed_counts()
    realdata._validate_expected(expected)
    assert set(expected) <= set(realdata._EXPECTED_KEYS)
    assert expected["schema"] == "scriptureearth-parallel-counts"
    assert expected["schema_version"] == 1
    if expected["status"] == "unsigned":
        assert expected["reviewed_by"] is None
        assert expected["reviewed_at"] is None
        _assert_template_counts_stay_null(expected)
        with pytest.raises(pytest.fail.Exception):
            realdata._reviewed_gate(expected)
    else:
        assert expected["status"] == "reviewed"
        realdata._reviewed_gate(expected)
        _assert_reviewed_counts_are_complete(expected)


def _assert_template_counts_stay_null(expected: dict[str, Any]) -> None:
    """The unsigned template keeps ``null`` counts and ``UNREVIEWED`` edition entries."""
    for side, language in (("source_mzr", "mzr"), ("source_por", "por")):
        entry = expected[side]
        assert entry["declared_edition_language"] == language
        assert str(entry["edition"]).startswith("UNREVIEWED")
        assert str(entry["versification"]).startswith("UNREVIEWED")
        for digest, size in entry["package_sha256_inventory"].items():
            assert re.fullmatch(r"[0-9a-f]{64}", digest)
            assert isinstance(size, int) and not isinstance(size, bool) and size >= 0
    counts = expected["expected_counts"]
    for key in ("common_groups", "unmatched_source", "unmatched_target"):
        assert counts[key] is None
    for book, pair_counts in counts["book_inventory"].items():
        assert isinstance(book, str) and book
        assert isinstance(pair_counts, list) and len(pair_counts) == 2
        for value in pair_counts:
            assert value is None


def _assert_reviewed_counts_are_complete(expected: dict[str, Any]) -> None:
    """A *reviewed* disk record keeps no placeholder and records integer counts everywhere.

    The gate already rejects each incomplete field; this pins the reviewed state's shape directly,
    so a signed file that somehow carried ``null`` counts or an ``UNREVIEWED`` edition would not
    be validated as legal merely because the gate let it through once.
    """
    for side in ("source_mzr", "source_por"):
        entry = expected[side]
        for key in ("edition", "versification"):
            value = str(entry[key])
            assert value.strip() and not value.startswith("UNREVIEWED")
    counts = expected["expected_counts"]
    for key in ("common_groups", "unmatched_source", "unmatched_target"):
        assert isinstance(counts[key], int) and not isinstance(counts[key], bool)
        assert counts[key] >= 0
    inventory = counts["book_inventory"]
    assert isinstance(inventory, dict) and inventory
    for pair_counts in inventory.values():
        assert isinstance(pair_counts, list) and len(pair_counts) == 2
        for value in pair_counts:
            assert isinstance(value, int) and not isinstance(value, bool)
            assert value >= 0


def test_complete_reviewed_record_passes_the_actual_gate() -> None:
    """The other legal state: a complete reviewed record passes the realdata gate.

    Calls the actual ``_reviewed_gate`` on the realdata suite's synthetic complete record, so a
    senior's prescribed signing keeps the default suite green — the positive case never reads the
    committed file and never depends on a fabricated signature on disk (senior review item 1).
    """
    realdata = _realdata_gate()
    realdata._reviewed_gate(realdata._complete_reviewed_record())


def test_disk_state_never_decides_the_gate_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signing the checked-in file changes no verdict: only the served record decides.

    Mirrors the realdata suite's patched-disk test with both disk states, so the default suite
    proves the property the senior's reproduction broke: an unsigned template is rejected even
    with a reviewer name, and a complete record passes. ``Path.read_text`` is patched and nothing
    is written to the expectations file.
    """
    realdata = _realdata_gate()
    real_read_text = Path.read_text
    for record, playbook in (
        (realdata._unsigned_template_record(), "reject"),
        (realdata._complete_reviewed_record(), "accept"),
    ):
        served = json.dumps(record)

        def _patched(self: Path, *args: Any, _served: str = served, **kwargs: Any) -> str:
            if self.name == "scriptureearth_parallel_counts.json":
                return _served
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _patched)
        loaded = realdata._load_expected()
        realdata._validate_expected(loaded)
        if playbook == "accept":
            realdata._reviewed_gate(loaded)
        else:
            with pytest.raises(pytest.fail.Exception) as excinfo:
                realdata._reviewed_gate(loaded)
            assert "is unsigned" in str(excinfo.value)
    monkeypatch.undo()
    assert tmp_path.exists()


def test_signed_count_rejects_invalid_shapes() -> None:
    """The actual count validator rejects bools, negatives and non-integers without a marker."""
    realdata = _realdata_gate()
    _signed_count = realdata._signed_count
    assert _signed_count(0, "x") == 0
    assert _signed_count(5594, "x") == 5594
    for bad in (True, False, -1, "5", 1.5, [1]):
        with pytest.raises(pytest.fail.Exception):
            _signed_count(bad, "x")
    assert _signed_count(None, "x", nullable=True) == -1
    with pytest.raises(pytest.fail.Exception):
        _signed_count(None, "x")


def test_signed_metadata_rejects_placeholders() -> None:
    """The actual metadata validator accepts the unsigned placeholder, rejects silent ones."""
    realdata = _realdata_gate()
    _signed_metadata = realdata._signed_metadata
    assert _signed_metadata("UNREVIEWED - operator must record the edition", "x", placeholder=True)
    for bad in (None, "", "   ", "placeholder", "TODO", "changeme", "<name>", "{{authority}}"):
        with pytest.raises(pytest.fail.Exception):
            _signed_metadata(bad, "x")
        with pytest.raises(pytest.fail.Exception):
            _signed_metadata(bad, "x", placeholder=True)


def test_placeholder_guard_rejects_template_editions() -> None:
    """A reviewed file whose ``UNREVIEWED`` placeholder survived signing fails the gate."""
    realdata = _realdata_gate()
    record = realdata._complete_reviewed_record()
    record["source_por"]["edition"] = "UNREVIEWED - operator must record the edition"
    with pytest.raises(pytest.fail.Exception):
        realdata._reviewed_gate(record)


def test_unsigned_template_is_negative_independent_of_disk() -> None:
    """The unsigned template built in memory is structurally valid and gate-rejected.

    The negative fixture comes from the realdata suite's in-memory constructor, never from the
    disk file, so a signed expectations file cannot make this regression pass by accident
    (senior review item 1).
    """
    realdata = _realdata_gate()
    template = realdata._unsigned_template_record()
    realdata._validate_expected(template)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        realdata._reviewed_gate(template)
    assert "is unsigned" in str(excinfo.value)
    named = json.loads(json.dumps(template))
    named["reviewed_by"] = "named-reviewer"
    named["reviewed_at"] = "2026-10-14T12:00:00Z"
    with pytest.raises(pytest.fail.Exception) as excinfo:
        realdata._reviewed_gate(named)
    assert "is unsigned" in str(excinfo.value)


def test_distinctive_metadata_key_is_absent_from_every_diagnostic() -> None:
    """A distinctive book key never reaches any safe-marked diagnostic (senior review item 2).

    The count validator labels entries by numeric position, so the injected key is absent from
    the gate's exception. The probe runs the actual gate on the realdata module's record.
    """
    realdata = _realdata_gate()
    record = realdata._complete_reviewed_record()
    record["expected_counts"]["book_inventory"] = {realdata._METADATA_SENTINEL: [-1, 0]}
    with pytest.raises(pytest.fail.Exception) as excinfo:
        realdata._reviewed_gate(record)
    assert realdata._METADATA_SENTINEL not in str(excinfo.value)


def test_registered_inventory_includes_timing_objects(tmp_path: Path) -> None:
    """The realdata package inventory covers every registered object, timing included.

    Compiler-free counterpart of the realdata regression: a synthetic package with USFM, timing
    and a note file yields an inventory keyed by every registered digest (senior review item 3).
    """
    realdata = _realdata_gate()
    ctx = realdata._memory_context(tmp_path)
    registration = realdata._timing_package_source(ctx, tmp_path, "synthetic-inventory")
    objects = ctx.repo.list_source_objects(registration.source.id)
    media_types = {source_object.media_type for source_object in objects}
    assert {"text/x-usfm", "text/x-sab-timing"} <= media_types
    inventory = realdata._registered_inventory(ctx, registration.source.id)
    assert set(inventory) == {source_object.sha256 for source_object in objects}
    assert all(int(size) > 0 for size in inventory.values())
