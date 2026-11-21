"""WP3.6 canonical locator aligner: coordinate-keyed n:m grouping (ADR-0011 §3).

Two segments correspond only through exactly equal coordinate keys under the
caller-selected namespace; there is no sentence/text similarity and no Cartesian
expansion. Components of the bipartite overlap graph become groups exactly once;
anything without a usable key or an opposite-side counterpart is reported
unmatched with a fixed reason code. Raw fixture strings below are synthetic.
"""

import re
from datetime import UTC, datetime

import pytest

from langpipe.alignment.base import AlignmentConfig
from langpipe.alignment.canonical import CanonicalLocatorAligner
from langpipe.domain.enums import AlignmentStatus
from langpipe.domain.errors import AlignmentFailed
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.observation import Segment

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
ALIGNER = CanonicalLocatorAligner()
SCRIPTURE = AlignmentConfig(namespace="scripture", versification_id="declared-vrs")
TSV = AlignmentConfig(namespace="fixture-01")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
# One default source object per side, as one book per USFM file would have.
SOURCE_OBJECT = new_id(IdPrefix.SOURCE_OBJECT)
TARGET_OBJECT = new_id(IdPrefix.SOURCE_OBJECT)


def _segment(
    locator: dict[str, str | int],
    *,
    language: str = "qaa",
    ordinal: int = 0,
    source_object_id: str | None = None,
) -> Segment:
    default_object = TARGET_OBJECT if language != "qaa" else SOURCE_OBJECT
    return Segment.model_validate(
        {
            "id": new_id(IdPrefix.SEGMENT),
            "source_id": new_id(IdPrefix.SOURCE),
            "source_object_id": source_object_id or default_object,
            "run_id": new_id(IdPrefix.RUN),
            "ordinal": ordinal,
            "language": language,
            "locator": locator,
            "raw_text": f"synthetic unit {ordinal}",
            "created_at": NOW,
        }
    )


def _verse(
    book: str,
    chapter: int,
    verse: str,
    *,
    part: int = 0,
    ordinal: int = 0,
    published: str | None = None,
    language: str = "qaa",
    source_object_id: str | None = None,
) -> Segment:
    locator: dict[str, str | int] = {
        "book": book,
        "chapter": chapter,
        "verse": verse,
        "unit": "verse",
        "para": "p",
        "para_index": 0,
        "part": part,
    }
    if published is not None:
        locator["published_verse"] = published
    return _segment(locator, language=language, ordinal=ordinal, source_object_id=source_object_id)


def _ref(
    ref: str,
    *,
    ordinal: int = 0,
    sentence_part: int | None = None,
    language: str = "qaa",
) -> Segment:
    locator: dict[str, str | int] = {"row": ordinal + 1, "column": language, "ref": ref}
    if sentence_part is not None:
        locator["sentence_part"] = sentence_part
    return _segment(locator, language=language, ordinal=ordinal)


def _ids(segments: tuple[Segment, ...]) -> tuple[str, ...]:
    return tuple(segment.id for segment in segments)


def test_one_to_one_structural() -> None:
    output = ALIGNER.align(
        [_verse("MRK", 2, "3")], [_verse("MRK", 2, "3", language="por")], SCRIPTURE
    )

    assert len(output.groups) == 1
    group = output.groups[0]
    assert len(group.source_segments) == 1
    assert len(group.target_segments) == 1
    assert group.status is AlignmentStatus.STRUCTURAL
    assert group.reason is None
    assert output.unmatched == ()


def test_bridge_one_to_two_structural() -> None:
    source = [_verse("MRK", 1, "5-6")]
    target = [_verse("MRK", 1, "5", language="por"), _verse("MRK", 1, "6", language="por")]

    output = ALIGNER.align(source, target, SCRIPTURE)

    assert len(output.groups) == 1
    group = output.groups[0]
    assert len(group.source_segments) == 1
    assert _ids(group.target_segments) == _ids(tuple(target))
    assert group.status is AlignmentStatus.STRUCTURAL


def test_ref_pieces_one_to_two_structural() -> None:
    # Golden TXT.1.4 shape: one qaa unit, two por sentence units sharing one ref.
    source = [_ref("TXT.1.4")]
    target = [
        _ref("TXT.1.4", ordinal=1, sentence_part=0, language="por"),
        _ref("TXT.1.4", ordinal=2, sentence_part=1, language="por"),
    ]

    output = ALIGNER.align(source, target, TSV)

    assert len(output.groups) == 1
    group = output.groups[0]
    assert len(group.source_segments) == 1
    assert _ids(group.target_segments) == _ids(tuple(target))
    assert group.status is AlignmentStatus.STRUCTURAL


def test_two_to_two_overlap_connected() -> None:
    source = [_verse("MRK", 1, "1-2"), _verse("MRK", 1, "3")]
    target = [_verse("MRK", 1, "1", language="por"), _verse("MRK", 1, "2-3", language="por")]

    output = ALIGNER.align(source, target, SCRIPTURE)

    assert len(output.groups) == 1
    group = output.groups[0]
    assert _ids(group.source_segments) == _ids(tuple(source))
    assert _ids(group.target_segments) == _ids(tuple(target))
    assert group.status is AlignmentStatus.STRUCTURAL


def test_two_to_three_overlap_connected() -> None:
    source = [_verse("MRK", 1, "1-3"), _verse("MRK", 1, "4")]
    target = [
        _verse("MRK", 1, "1", language="por"),
        _verse("MRK", 1, "2", language="por"),
        _verse("MRK", 1, "3-4", language="por"),
    ]

    output = ALIGNER.align(source, target, SCRIPTURE)

    assert len(output.groups) == 1
    group = output.groups[0]
    assert _ids(group.source_segments) == _ids(tuple(source))
    assert _ids(group.target_segments) == _ids(tuple(target))
    assert group.status is AlignmentStatus.STRUCTURAL


def test_verse_pieces_join_one_component_in_input_order() -> None:
    # Two pieces sharing the exact original label on one side are one side of
    # the group — not an ambiguity and not two groups. Member order is the
    # caller's document order: the aligner is stable and never re-sorts by ID.
    piece_zero = _verse("MRK", 2, "3", part=0, ordinal=4)
    piece_one = _verse("MRK", 2, "3", part=1, ordinal=5)
    target = [_verse("MRK", 2, "3", language="por")]

    output = ALIGNER.align([piece_one, piece_zero], target, SCRIPTURE)

    assert len(output.groups) == 1
    group = output.groups[0]
    assert _ids(group.source_segments) == (piece_one.id, piece_zero.id)
    assert _ids(group.target_segments) == _ids(tuple(target))
    assert group.status is AlignmentStatus.STRUCTURAL


def test_duplicate_edition_book_rejected() -> None:
    first_object = new_id(IdPrefix.SOURCE_OBJECT)
    second_object = new_id(IdPrefix.SOURCE_OBJECT)
    source = [
        _verse("MRK", 1, "1", source_object_id=first_object),
        _verse("MRK", 1, "2", ordinal=1, source_object_id=second_object),
    ]
    target = [_verse("MRK", 1, "1", language="por"), _verse("MRK", 1, "2", language="por")]

    with pytest.raises(AlignmentFailed) as exc_info:
        ALIGNER.align(source, target, SCRIPTURE)

    assert exc_info.value.code == "duplicate_book"


def test_malformed_or_missing_locator_unmatched() -> None:
    heading = _segment(
        {"book": "MRK", "chapter": 1, "unit": "heading", "marker": "s", "para_index": 0}
    )
    missing = _segment({}, ordinal=1)
    bad_types = _segment({"book": "MRK", "chapter": "1", "verse": "3", "unit": "verse"}, ordinal=2)
    mixed_bridge = _verse("MRK", 1, "3a-4", ordinal=3)
    target = [_verse("MRK", 1, "3", language="por")]

    output = ALIGNER.align([heading, missing, bad_types, mixed_bridge], target, SCRIPTURE)

    assert output.groups == ()
    assert dict(output.unmatched) == {
        heading.id: "unit_not_verse",
        missing.id: "missing_locator",
        bad_types.id: "malformed_locator",
        mixed_bridge.id: "malformed_locator",
        target[0].id: "no_counterpart",
    }


def test_empty_ref_unmatched() -> None:
    empty = _ref("")
    source = [_ref("TXT.1.1", ordinal=1)]
    target = [_ref("TXT.1.1", language="por")]

    output = ALIGNER.align([empty, *source], target, TSV)

    assert len(output.groups) == 1
    assert _ids(output.groups[0].source_segments) == (source[0].id,)
    assert dict(output.unmatched) == {empty.id: "missing_ref"}


def test_unrelated_namespace_yields_no_groups() -> None:
    # Disjoint coordinate vocabularies under one request never match, and the
    # aligner never falls back to text similarity to invent correspondence.
    source = [_ref("SRC.1"), _ref("SRC.2")]
    target = [_ref("TGT.1", language="por")]

    output = ALIGNER.align(source, target, TSV)

    assert output.groups == ()
    assert dict(output.unmatched) == {
        source[0].id: "no_counterpart",
        source[1].id: "no_counterpart",
        target[0].id: "no_counterpart",
    }


def test_suffix_label_matches_only_exact_label() -> None:
    source = [_verse("MRK", 2, "3a")]
    target = [_verse("MRK", 2, "3", language="por"), _verse("MRK", 2, "3a", language="por")]

    output = ALIGNER.align(source, target, SCRIPTURE)

    assert len(output.groups) == 1
    group = output.groups[0]
    assert _ids(group.target_segments) == (target[1].id,)
    assert group.status is AlignmentStatus.STRUCTURAL
    assert dict(output.unmatched) == {target[0].id: "no_counterpart"}


def test_published_label_is_diagnostic_only() -> None:
    # published_verse values differ; numeric coordinates still correspond.
    source = [_verse("MRK", 2, "3", published="103")]
    target = [_verse("MRK", 2, "3", published="3", language="por")]

    output = ALIGNER.align(source, target, SCRIPTURE)

    assert len(output.groups) == 1
    assert output.groups[0].status is AlignmentStatus.STRUCTURAL
    assert output.unmatched == ()


def test_incompatible_versification_rejected() -> None:
    # Scripture-shaped locators without a declared versification are rejected,
    # never silently treated as a ref namespace.
    source = [_verse("MRK", 2, "3")]
    target = [_verse("MRK", 2, "3", language="por")]

    with pytest.raises(AlignmentFailed) as exc_info:
        ALIGNER.align(source, target, TSV)

    assert exc_info.value.code == "incompatible_versification"


def test_headings_and_notes_excluded() -> None:
    heading = _segment(
        {"book": "MRK", "chapter": 1, "unit": "heading", "marker": "s", "para_index": 0}
    )
    footnote = _segment(
        {
            "book": "MRK",
            "chapter": 1,
            "verse": "1",
            "unit": "footnote",
            "note_index": 0,
            "caller": "+",
            "note_ref": "1:1",
        },
        language="por",
        ordinal=1,
    )
    source = [_verse("MRK", 1, "1", ordinal=1), heading]
    target = [_verse("MRK", 1, "1", language="por"), footnote]

    output = ALIGNER.align(source, target, SCRIPTURE)

    assert len(output.groups) == 1
    assert _ids(output.groups[0].source_segments) == (source[0].id,)
    assert _ids(output.groups[0].target_segments) == (target[0].id,)
    assert dict(output.unmatched) == {
        heading.id: "unit_not_verse",
        footnote.id: "unit_not_verse",
    }


def test_bridge_partial_coverage_is_candidate() -> None:
    source = [_verse("MRK", 1, "1-3")]
    target = [_verse("MRK", 1, "1", language="por"), _verse("MRK", 1, "2", language="por")]

    output = ALIGNER.align(source, target, SCRIPTURE)

    assert len(output.groups) == 1
    group = output.groups[0]
    assert group.status is AlignmentStatus.CANDIDATE
    assert group.reason == "partial_coordinate_coverage"
    assert output.unmatched == ()


def test_ambiguous_coordinates_rejected() -> None:
    # Overlapping distinct verse claims within one edition fail preflight;
    # only pieces sharing the exact original label may overlap.
    source = [_verse("MRK", 2, "3"), _verse("MRK", 2, "3-4", ordinal=1)]
    target = [_verse("MRK", 2, "3", language="por")]

    with pytest.raises(AlignmentFailed) as exc_info:
        ALIGNER.align(source, target, SCRIPTURE)

    assert exc_info.value.code == "ambiguous_coordinates"


def test_group_key_is_stable_and_sensitive_to_orientation_and_namespace() -> None:
    source = [_verse("MRK", 2, "3")]
    target = [_verse("MRK", 2, "3", language="por")]

    first = ALIGNER.align(source, target, SCRIPTURE)
    rerun = ALIGNER.align(source, target, SCRIPTURE)
    flipped = ALIGNER.align(target, source, SCRIPTURE)
    other_namespace = ALIGNER.align(
        source, target, AlignmentConfig(namespace="other", versification_id="declared-vrs")
    )

    key = first.groups[0].group_key
    assert SHA256_PATTERN.fullmatch(key)
    assert rerun.groups[0].group_key == key
    assert flipped.groups[0].group_key != key
    assert other_namespace.groups[0].group_key != key


def test_groups_follow_document_order() -> None:
    source = [_verse("MRK", 1, "2"), _verse("MRK", 1, "1", ordinal=1)]
    target = [_verse("MRK", 1, "1", language="por"), _verse("MRK", 1, "2", language="por")]

    output = ALIGNER.align(source, target, SCRIPTURE)

    assert [group.source_segments[0].locator["verse"] for group in output.groups] == ["2", "1"]
    assert _ids(output.groups[0].target_segments) == (target[1].id,)
    assert _ids(output.groups[1].target_segments) == (target[0].id,)
