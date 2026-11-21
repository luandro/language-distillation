"""Pure-Python deterministic character BPE baseline (M5-PLAN §6 WP5.11, ADR-0019 §5).

Learned from the pinned tokenization run's token types (merges cap config-pinned;
ties broken lexicographically). Segments carry `morpheme_id=None` and are never promotable.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import ClassVar

from langpipe.domain.enums import (
    Abstention,
    AnalysisKind,
    LifecycleStatus,
    LineageKind,
    SpanRepresentation,
)
from langpipe.domain.ids import IdFactory, IdPrefix, new_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.morphology import (
    MorphAnalysis,
    MorphSegment,
)
from langpipe.morphology.base import (
    MorphAnalysisCandidate,
    MorphologyInducer,
    MorphologyInductionInput,
    MorphologyInductionOutput,
)
from langpipe.morphology.scoring import score_analysis
from langpipe.morphology.spans import check_analysis, segmentation_signature

DEFAULT_MERGES_CAP: int = 50


def _default_id(prefix: IdPrefix) -> str:
    return new_id(prefix)


def _apply_merges(surface: str, merges: Sequence[tuple[str, str]]) -> list[str]:
    pieces = list(surface)
    for p0, p1 in merges:
        merged = p0 + p1
        new_pieces: list[str] = []
        i = 0
        while i < len(pieces):
            if i < len(pieces) - 1 and pieces[i] == p0 and pieces[i + 1] == p1:
                new_pieces.append(merged)
                i += 2
            else:
                new_pieces.append(pieces[i])
                i += 1
        pieces = new_pieces
    return pieces


class BpeCharInducer(MorphologyInducer):
    """The character BPE baseline `bpe_char@0.1.0`.

    Learns subword vocabulary purely from character n-grams across token types,
    breaking equal-frequency ties lexicographically. Emits unlinked segments
    (`morpheme_id=None`) with status `candidate`.
    """

    name: ClassVar[str] = "bpe_char"
    version: ClassVar[str] = "0.1.0"

    def __init__(self, new_id_factory: IdFactory | None = None) -> None:
        self._new_id: IdFactory = new_id_factory if new_id_factory is not None else _default_id

    @property
    def method_id(self) -> str:
        return f"{self.name}@{self.version}"

    def induce(self, input: MorphologyInductionInput) -> MorphologyInductionOutput:
        analyses: list[MorphAnalysisCandidate] = []
        lineage_edges: list[LineageEdge] = []
        abstentions: dict[str, Abstention] = {}
        now = datetime.now(UTC)
        method_str = self.method_id

        # Profile boundary marks if profile provides them
        boundary_marks: tuple[str, ...] = ()
        if input.profile is not None and hasattr(input.profile, "boundary_marks"):
            boundary_marks = tuple(input.profile.boundary_marks)

        # 1. Config merges cap
        policy = input.policy or {}
        merges_val = policy.get("merges", policy.get("max_merges", DEFAULT_MERGES_CAP))
        try:
            merges_cap = max(0, int(merges_val)) if merges_val is not None else DEFAULT_MERGES_CAP
        except (ValueError, TypeError):
            merges_cap = DEFAULT_MERGES_CAP

        # 2. Collect unique token types (WP5.11: learned from token types, not token occurrences)
        unique_types = {
            tok.normalized_surface if tok.normalized_surface is not None else tok.raw_surface
            for tok in input.tokens
        }
        words = sorted(w for w in unique_types if w)

        # 3. Learn merges deterministically from token types
        word_pieces: dict[str, list[str]] = {w: list(w) for w in words}
        learned_merges: list[tuple[str, str]] = []

        for _ in range(merges_cap):
            pair_counts: dict[tuple[str, str], int] = defaultdict(int)
            for _word, wp_pieces in word_pieces.items():
                for i in range(len(wp_pieces) - 1):
                    pair_counts[(wp_pieces[i], wp_pieces[i + 1])] += 1

            if not pair_counts:
                break

            max_freq = max(pair_counts.values())
            if max_freq <= 0:
                break

            # Ties broken lexicographically
            best_pair = min(
                (p for p, c in pair_counts.items() if c == max_freq),
                key=lambda p: (p[0], p[1]),
            )
            learned_merges.append(best_pair)
            merged_str = best_pair[0] + best_pair[1]

            new_word_pieces: dict[str, list[str]] = {}
            for word, wp_pieces in word_pieces.items():
                new_w: list[str] = []
                i = 0
                while i < len(wp_pieces):
                    if (
                        i < len(wp_pieces) - 1
                        and wp_pieces[i] == best_pair[0]
                        and wp_pieces[i + 1] == best_pair[1]
                    ):
                        new_w.append(merged_str)
                        i += 2
                    else:
                        new_w.append(wp_pieces[i])
                        i += 1
                new_word_pieces[word] = new_w
            word_pieces = new_word_pieces

        # 4. Generate segmentations for all tokens
        for token in input.tokens:
            if token.normalized_surface is not None:
                surface = token.normalized_surface
                span_rep = SpanRepresentation.NORMALIZED
            else:
                surface = token.raw_surface
                span_rep = SpanRepresentation.RAW

            if not surface:
                abstentions[token.id] = Abstention.INSUFFICIENT_EVIDENCE
                continue

            cached_pieces = word_pieces.get(surface)
            pieces: list[str] = (
                cached_pieces
                if cached_pieces is not None
                else _apply_merges(surface, learned_merges)
            )

            analysis_id = self._new_id(IdPrefix.MORPH_ANALYSIS)
            segments: list[MorphSegment] = []
            curr = 0

            for idx, piece in enumerate(pieces):
                seg_id = self._new_id(IdPrefix.MORPH_SEGMENT)
                p_len = len(piece)
                seg = MorphSegment(
                    id=seg_id,
                    analysis_id=analysis_id,
                    ordinal=idx,
                    start=curr,
                    end=curr + p_len,
                    is_zero=False,
                    surface=piece,
                    morpheme_id=None,
                    allomorph_id=None,
                    role=None,
                    source_gloss=None,
                    created_at=now,
                )
                segments.append(seg)
                curr += p_len

            kind = AnalysisKind.SEGMENTED if len(segments) > 1 else AnalysisKind.UNSEGMENTED
            if kind is AnalysisKind.UNSEGMENTED:
                # Unsegmented analysis requires an abstention reason per contract
                sig = segmentation_signature(kind, segments)
                status, breakdown = score_analysis(
                    method=method_str,
                    linked_morphemes=(),
                    segments=segments,
                    evidence_items=(),
                    current_status=LifecycleStatus.CANDIDATE,
                )
                ana = MorphAnalysis(
                    id=analysis_id,
                    target_token_id=token.id,
                    analysis_kind=kind,
                    method=method_str,
                    span_representation=span_rep,
                    surface=surface,
                    signature=sig,
                    abstention=Abstention.INSUFFICIENT_EVIDENCE,
                    status=LifecycleStatus.CANDIDATE,
                    score_breakdown=breakdown,
                    run_id=input.run_id,
                    created_at=now,
                )
                check_analysis(ana, segments, boundary_marks)
                abstentions[token.id] = Abstention.INSUFFICIENT_EVIDENCE
            else:
                sig = segmentation_signature(kind, segments)
                status, breakdown = score_analysis(
                    method=method_str,
                    linked_morphemes=(),
                    segments=segments,
                    evidence_items=(),
                    current_status=LifecycleStatus.CANDIDATE,
                )
                ana = MorphAnalysis(
                    id=analysis_id,
                    target_token_id=token.id,
                    analysis_kind=kind,
                    method=method_str,
                    span_representation=span_rep,
                    surface=surface,
                    signature=sig,
                    abstention=None,
                    status=LifecycleStatus.CANDIDATE,
                    score_breakdown=breakdown,
                    run_id=input.run_id,
                    created_at=now,
                )
                check_analysis(ana, segments, boundary_marks)

            analyses.append(MorphAnalysisCandidate(analysis=ana, segments=segments, features=()))

            lineage_edges.append(
                LineageEdge(
                    id=self._new_id(IdPrefix.LINEAGE),
                    from_id=analysis_id,
                    to_id=token.id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=input.run_id,
                    created_at=now,
                )
            )
            for seg in segments:
                lineage_edges.append(
                    LineageEdge(
                        id=self._new_id(IdPrefix.LINEAGE),
                        from_id=analysis_id,
                        to_id=seg.id,
                        kind=LineageKind.DERIVED_FROM,
                        run_id=input.run_id,
                        created_at=now,
                    )
                )

        return MorphologyInductionOutput(
            analyses=analyses,
            lineage_edges=lineage_edges,
            abstentions=abstentions,
        )
