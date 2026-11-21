"""Canonical segmentation signature and structural segment checks (M5-PLAN §6 WP5.2, ADR-0017 §4).

The signature makes two analyses of the same token comparable: it is a sha256
over the ordered `[(start, end, is_zero, morpheme_id)]` payload only — method,
run, provenance and ordinals are deliberately excluded, so the same
segmentation from two methods agrees by signature while remaining distinct rows.

`check_segments` enforces the ADR-0017 §4 segmentation contract against a token
surface: ordered, non-overlapping, contiguous ordinals, surfaces that match the
spans they claim, and uncovered code points restricted to profile boundary marks
(they are orthography, not morphs). `check_analysis` enforces the analysis-kind
rules the frozen model cannot carry: `unsegmented` ⇒ exactly one whole-surface
segment with no morpheme, and `segmented` ⇒ no `abstention`.

Error messages here carry ordinals, positions, offsets and lengths only — never
surface text (invariant 7: no restricted text outside governed stores).
"""

from typing import Any

from langpipe.domain.enums import AnalysisKind
from langpipe.domain.hashing import canonical_json, sha256_bytes
from langpipe.domain.models.morphology import MorphAnalysis, MorphSegment


def segmentation_signature(
    analysis_kind: AnalysisKind,
    segments: list[MorphSegment] | list[dict[str, Any]],
) -> str:
    """Return the canonical signature of a segmentation.

    The digest covers `[(start, end, is_zero, morpheme_id)]` sorted by start,
    end, ordinal; `analysis_kind` documents the analysis being signed but is not
    part of the payload (M5-PLAN §6 WP5.2). Accepts `MorphSegment` rows or their
    plain-dict form (run configs and gold files carry dicts); both produce the
    same digest for the same spans. The kind rules (`unsegmented` ⇒ one
    whole-surface morpheme-less segment; `segmented` ⇒ no abstention) are
    enforced by `check_analysis`, not by the digest.
    """

    rows: list[tuple[int, list[Any]]] = []
    for segment in segments:
        if isinstance(segment, MorphSegment):
            ordinal: int = segment.ordinal
            rows.append(
                (ordinal, [segment.start, segment.end, segment.is_zero, segment.morpheme_id])
            )
        else:
            raw_ordinal = segment.get("ordinal")
            ordinal = 0 if raw_ordinal is None else int(raw_ordinal)
            rows.append(
                (
                    ordinal,
                    [
                        segment["start"],
                        segment["end"],
                        bool(segment.get("is_zero", False)),
                        segment.get("morpheme_id"),
                    ],
                )
            )
    rows.sort(key=lambda entry: (entry[1][0], entry[1][1], entry[0]))
    payload = [entry[1] for entry in rows]
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def check_segments(
    surface: str,
    segments: list[MorphSegment],
    boundary_marks: tuple[str, ...],
) -> None:
    """Validate a segmentation against its token surface; raise `ValueError` if broken.

    Contract (ADR-0017 §4): at least one segment; ordinals contiguous from 0;
    spans ascending and non-overlapping; every span within the surface; a
    segment's `surface` equals the slice it claims; zero width only with
    `is_zero=True`; every uncovered code point is a profile boundary mark.
    """

    if not segments:
        raise ValueError("segmentation must contain at least one segment")

    length = len(surface)
    covered = [False] * length
    previous_end: int | None = None
    for position, segment in enumerate(segments):
        where = f"segment {segment.ordinal} (position {position})"
        if segment.ordinal != position:
            raise ValueError(f"{where}: ordinals must be contiguous from 0, expected {position}")
        if segment.start < 0 or segment.end > length:
            raise ValueError(
                f"{where}: span [{segment.start}, {segment.end}) is outside the surface "
                f"of length {length}"
            )
        if previous_end is not None and segment.start < previous_end:
            raise ValueError(
                f"{where}: segments must be sorted and non-overlapping "
                f"(starts before previous end {previous_end})"
            )
        if segment.is_zero:
            if segment.start != segment.end:
                raise ValueError(f"{where}: an is_zero segment must have start == end")
            if segment.surface != "":
                raise ValueError(f"{where}: an is_zero segment must have an empty surface")
        else:
            if segment.start == segment.end:
                raise ValueError(f"{where}: an empty span requires is_zero=True")
            if segment.surface != surface[segment.start : segment.end]:
                # No surface text in the message: surfaces are governed content.
                raise ValueError(
                    f"{where}: surface does not match surface[{segment.start}:{segment.end}]"
                )
            for index in range(segment.start, segment.end):
                covered[index] = True
        previous_end = segment.end

    for index, char in enumerate(surface):
        if not covered[index] and char not in boundary_marks:
            raise ValueError(
                f"uncovered code point at index {index} is not a profile boundary mark"
            )


def check_analysis(
    analysis: MorphAnalysis,
    segments: list[MorphSegment],
    boundary_marks: tuple[str, ...],
) -> None:
    """Validate one analysis together with its segments; raise `ValueError` if broken.

    The §7.4 rule `unsegmented` ⇒ exactly one whole-surface segment with no
    morpheme cannot live on the frozen model, so producers and the repository
    call this single entry point instead. It also requires every segment to
    belong to the analysis, refuses an `abstention` on a `segmented` analysis,
    and pins `signature` to `segmentation_signature`. Messages carry ordinals,
    positions and lengths only — never surface text.
    """

    check_segments(analysis.surface, segments, boundary_marks)
    for segment in segments:
        if segment.analysis_id != analysis.id:
            raise ValueError(f"segment {segment.ordinal} does not belong to the analysis")

    if analysis.analysis_kind is AnalysisKind.UNSEGMENTED:
        if len(segments) != 1:
            raise ValueError(
                f"an unsegmented analysis must carry exactly one segment, got {len(segments)}"
            )
        segment = segments[0]
        if segment.is_zero:
            raise ValueError("an unsegmented analysis segment must not be is_zero")
        if segment.start != 0 or segment.end != len(analysis.surface):
            raise ValueError(
                f"an unsegmented analysis segment must span the whole surface "
                f"(expected [0, {len(analysis.surface)}), got "
                f"[{segment.start}, {segment.end}))"
            )
        if segment.morpheme_id is not None:
            raise ValueError("an unsegmented analysis segment must not link a morpheme")
    elif analysis.abstention is not None:
        raise ValueError("a segmented analysis must not carry an abstention")

    if analysis.signature != segmentation_signature(analysis.analysis_kind, segments):
        raise ValueError("analysis signature does not match its segmentation")
