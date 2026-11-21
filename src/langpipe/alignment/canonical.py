"""Canonical locator segment aligner ``canonical_locator@0.1.0`` (M3 WP3.6, ADR-0011 §3).

Groups already persisted normalized segments by preserved coordinate metadata:
two segments correspond only through exactly equal coordinate keys under the
caller-selected namespace. The aligner never reads source files, never creates
segments and never compares sentence or text content, so no Cartesian expansion
or similarity heuristic can invent correspondence.

Key schemes, selected by the request's ``AlignmentConfig``:

* ``versification_id`` set — scripture keys ``(namespace, versification_id,
  book, chapter, verse position)``; only ``unit=verse`` participates. Simple
  numeric labels and inclusive numeric bridges map to coordinate sets; multiple
  pieces sharing the exact original label join one component; suffix labels
  such as ``3a`` are their own opaque coordinate and never collapse into ``3``;
  published labels are retained diagnostics, never coordinates. Headings,
  introductions, footnotes and unknown blocks are reported unmatched.
* ``versification_id`` unset — ref keys ``(namespace, ref)``. Language, row,
  column and sentence part never enter keys; empty refs are unmatched.
  Verse-shaped locators without a declared versification are rejected.

Fixed unmatched reason codes (diagnostics, never free text):
``unit_not_verse``, ``missing_locator``, ``malformed_locator``,
``missing_ref``, ``no_counterpart``.

Hard failures (``AlignmentFailed``): ``duplicate_book`` (one book under two
source objects on a side), ``ambiguous_coordinates`` (overlapping distinct
verse claims within one side unless pieces share the exact original label),
``incompatible_versification`` (scripture data, no declared versification) and
``invalid_coordinates`` (a segment ID repeated in the input sequences).

A component is ``structural`` only when each side covers the same coordinate
set; partial bridge coverage emits ``candidate`` with the fixed
``partial_coordinate_coverage`` reason and is excluded from Stage 5 downstream.
Group and member order follow the caller's document order (the input
sequences); IDs are never re-sorted.
"""

import re
from collections.abc import Sequence
from typing import ClassVar

from langpipe.alignment.base import AlignmentConfig, SegmentGroup, SegmentMatchOutput
from langpipe.domain.enums import AlignmentMode, AlignmentStatus
from langpipe.domain.errors import AlignmentFailed
from langpipe.domain.hashing import canonical_json, sha256_bytes
from langpipe.domain.models.observation import Segment

_SINGLE_VERSE = re.compile(r"[0-9]+")
_SUFFIX_VERSE = re.compile(r"[0-9]+[a-z]")
_NUMERIC_BRIDGE = re.compile(r"([0-9]+)-([0-9]+)")

# One coordinate key: scripture keys are (book, chapter, position) — the
# position is an int for numeric verses and bridges, the opaque label itself
# for suffix verses such as "3a" — and ref keys are (ref,). Both schemes share
# this hashable shape; a single call uses exactly one scheme.
_Key = tuple[int | str, ...]
# Per segment: coordinate keys, or a fixed unmatched reason when unkeyable.
_Keys = tuple[_Key, ...]
_KeysOrReason = _Keys | str

PARTIAL_COVERAGE = "partial_coordinate_coverage"
UNMATCHED_REASONS: frozenset[str] = frozenset(
    {"unit_not_verse", "missing_locator", "malformed_locator", "missing_ref", "no_counterpart"}
)


def _verse_positions(label: str) -> tuple[int | str, ...] | None:
    """Coordinate positions claimed by one verse label; ``None`` when malformed."""
    if _SINGLE_VERSE.fullmatch(label):
        return (int(label),)
    if _SUFFIX_VERSE.fullmatch(label):
        return (label,)
    bridge = _NUMERIC_BRIDGE.fullmatch(label)
    if bridge is not None:
        start, end = int(bridge.group(1)), int(bridge.group(2))
        if start > end:
            return None
        return tuple(range(start, end + 1))
    return None


def _scripture_keys(segment: Segment) -> _KeysOrReason:
    locator = segment.locator
    unit = locator.get("unit")
    if unit is None:
        return "missing_locator"
    if unit != "verse":
        return "unit_not_verse"
    book = locator.get("book")
    chapter = locator.get("chapter")
    label = locator.get("verse")
    if not isinstance(book, str) or not book or chapter is None or label is None:
        return "missing_locator"
    if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
        return "malformed_locator"
    if not isinstance(label, str):
        return "malformed_locator"
    positions = _verse_positions(label)
    if positions is None:
        return "malformed_locator"
    return tuple((book, chapter, position) for position in positions)


def _ref_key(segment: Segment) -> _KeysOrReason:
    ref = segment.locator.get("ref")
    if not isinstance(ref, str) or not ref:
        return "missing_ref"
    return ((ref,),)


class CanonicalLocatorAligner:
    """Coordinate-keyed matcher over persisted segments; evidence, never truth."""

    name: ClassVar[str] = "canonical_locator"
    version: ClassVar[str] = "0.1.0"

    def align(
        self,
        source: Sequence[Segment],
        target: Sequence[Segment],
        config: AlignmentConfig,
    ) -> SegmentMatchOutput:
        source_segments = list(source)
        target_segments = list(target)
        self._check_unique_ids(source_segments, target_segments)
        scripture = config.versification_id is not None
        if not scripture:
            self._reject_undeclared_scripture(source_segments, target_segments)

        keyed = [
            _scripture_keys(segment) if scripture else _ref_key(segment)
            for segment in source_segments + target_segments
        ]
        if scripture:
            self._check_duplicate_book(source_segments, target_segments)
            self._check_ambiguous_coordinates(source_segments, keyed[: len(source_segments)])
            self._check_ambiguous_coordinates(target_segments, keyed[len(source_segments) :])

        groups, grouped = self._components(source_segments, target_segments, keyed, config)
        unmatched = self._unmatched(source_segments, target_segments, keyed, grouped)
        return SegmentMatchOutput(groups=groups, unmatched=unmatched)

    # ----- preflight checks ---------------------------------------------------------------

    @staticmethod
    def _check_unique_ids(source: list[Segment], target: list[Segment]) -> None:
        seen: set[str] = set()
        for segment in source + target:
            if segment.id in seen:
                raise AlignmentFailed("invalid_coordinates")
            seen.add(segment.id)

    @staticmethod
    def _reject_undeclared_scripture(source: list[Segment], target: list[Segment]) -> None:
        for segment in source + target:
            if segment.locator.get("unit") == "verse":
                raise AlignmentFailed("incompatible_versification")

    @staticmethod
    def _check_duplicate_book(source: list[Segment], target: list[Segment]) -> None:
        for side in (source, target):
            owner: dict[str, str] = {}
            for segment in side:
                book = segment.locator.get("book")
                if not isinstance(book, str):
                    continue
                previous = owner.setdefault(book, segment.source_object_id)
                if previous != segment.source_object_id:
                    raise AlignmentFailed("duplicate_book")

    @staticmethod
    def _check_ambiguous_coordinates(side: list[Segment], keyed: list[_KeysOrReason]) -> None:
        claims: dict[_Key, set[str]] = {}
        for segment, keys_or_reason in zip(side, keyed, strict=True):
            if isinstance(keys_or_reason, str):
                continue
            label = segment.locator["verse"]
            assert isinstance(label, str)  # guaranteed by _scripture_keys
            for key in keys_or_reason:
                claims.setdefault(key, set()).add(label)
        for claimed_labels in claims.values():
            if len(claimed_labels) > 1:
                raise AlignmentFailed("ambiguous_coordinates")

    # ----- grouping -----------------------------------------------------------------------

    def _components(
        self,
        source: list[Segment],
        target: list[Segment],
        keyed: list[_KeysOrReason],
        config: AlignmentConfig,
    ) -> tuple[tuple[SegmentGroup, ...], set[int]]:
        n = len(source)
        parent = list(range(n + len(target)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        holders: dict[_Key, list[int]] = {}
        for index, keys_or_reason in enumerate(keyed):
            if isinstance(keys_or_reason, str):
                continue
            for key in keys_or_reason:
                holders.setdefault(key, []).append(index)
        for indexes in holders.values():
            for other in indexes[1:]:
                union(indexes[0], other)

        components: dict[int, tuple[list[int], list[int]]] = {}
        for index in range(n + len(target)):
            source_indexes, target_indexes = components.setdefault(find(index), ([], []))
            (source_indexes if index < n else target_indexes).append(index)

        groups: list[tuple[int, SegmentGroup]] = []
        grouped: set[int] = set()
        for source_indexes, target_indexes in components.values():
            if not source_indexes or not target_indexes:
                continue
            grouped.update(source_indexes)
            grouped.update(target_indexes)
            source_members = tuple(source[i] for i in sorted(source_indexes))
            target_members = tuple(target[i - n] for i in sorted(target_indexes))
            structural = self._coverage(keyed, source_indexes) == self._coverage(
                keyed, target_indexes
            )
            groups.append(
                (
                    min(source_indexes),
                    SegmentGroup(
                        source_segments=source_members,
                        target_segments=target_members,
                        group_key=self._group_key(config, source_members, target_members),
                        status=(
                            AlignmentStatus.STRUCTURAL if structural else AlignmentStatus.CANDIDATE
                        ),
                        reason=None if structural else PARTIAL_COVERAGE,
                    ),
                )
            )
        return tuple(group for _, group in sorted(groups, key=lambda item: item[0])), grouped

    @staticmethod
    def _coverage(keyed: list[_KeysOrReason], indexes: list[int]) -> set[_Key]:
        coverage: set[_Key] = set()
        for index in indexes:
            keys_or_reason = keyed[index]
            if not isinstance(keys_or_reason, str):
                coverage.update(keys_or_reason)
        return coverage

    @staticmethod
    def _unmatched(
        source: list[Segment],
        target: list[Segment],
        keyed: list[_KeysOrReason],
        grouped: set[int],
    ) -> tuple[tuple[str, str], ...]:
        unmatched: list[tuple[str, str]] = []
        for index, segment in enumerate(source + target):
            if index in grouped:
                continue
            keys_or_reason = keyed[index]
            reason = keys_or_reason if isinstance(keys_or_reason, str) else "no_counterpart"
            unmatched.append((segment.id, reason))
        return tuple(unmatched)

    def _group_key(
        self,
        config: AlignmentConfig,
        source_members: tuple[Segment, ...],
        target_members: tuple[Segment, ...],
    ) -> str:
        return sha256_bytes(
            canonical_json(
                {
                    "method": f"{self.name}@{self.version}",
                    "mode": AlignmentMode.CANONICAL.value,
                    "namespace": config.namespace,
                    "versification_id": config.versification_id,
                    "source_segment_ids": [segment.id for segment in source_members],
                    "target_segment_ids": [segment.id for segment in target_members],
                }
            ).encode("utf-8")
        )
