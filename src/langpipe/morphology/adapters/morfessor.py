"""Morfessor baseline morphology inducer (M5-PLAN §6 WP5.12, ADR-0019 §5).

Trains an unsupervised Morfessor BaselineModel over token surfaces offline.
Requires the optional `morphology` extra (`morfessor==2.0.6`).
Segments carry `morpheme_id=None` and candidate status.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

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
from langpipe.domain.models.observation import TokenOccurrence
from langpipe.morphology.base import (
    MorphAnalysisCandidate,
    MorphologyInducer,
    MorphologyInductionInput,
    MorphologyInductionOutput,
)
from langpipe.morphology.scoring import score_analysis
from langpipe.morphology.spans import check_analysis, segmentation_signature


def _default_id(prefix: IdPrefix) -> str:
    return new_id(prefix)


def _get_morfessor() -> Any:
    """Import morfessor lazily or fail with actionable guidance."""
    try:
        import morfessor

        return morfessor
    except ImportError:
        raise RuntimeError(
            "morfessor is an optional extra: install with 'uv sync --extra morphology'"
        ) from None


class MorfessorInducer(MorphologyInducer):
    """Unsupervised morphology induction baseline using Morfessor 2.0.

    Trains offline on token frequencies, breaking segmentation using Viterbi search.
    Emits candidate-only analyses (`status=CANDIDATE`) with unlinked segments (`morpheme_id=None`).
    """

    name: ClassVar[str] = "morfessor_baseline"
    version: ClassVar[str] = "0.1.0"

    def __init__(self, seed: int = 42, new_id_factory: IdFactory | None = None) -> None:
        self._seed: int = seed
        self._new_id: IdFactory = new_id_factory if new_id_factory is not None else _default_id

    @property
    def method_id(self) -> str:
        return f"{self.name}@{self.version}"

    def induce(self, input: MorphologyInductionInput) -> MorphologyInductionOutput:
        analyses: list[MorphAnalysisCandidate] = []
        lineage_edges: list[LineageEdge] = []
        abstentions: dict[str, Abstention] = {}
        now = datetime.now(UTC)

        train_pool: Sequence[TokenOccurrence] = (
            input.training_tokens if input.training_tokens is not None else input.tokens
        )
        counts: Counter[str] = Counter()
        for tok in train_pool:
            surf = tok.normalized_surface if tok.normalized_surface is not None else tok.raw_surface
            if surf and surf.strip():
                counts[surf] += 1

        if not counts:
            for tok in input.tokens:
                abstentions[tok.id] = Abstention.INSUFFICIENT_EVIDENCE
            return MorphologyInductionOutput(
                analyses=(),
                lineage_edges=(),
                abstentions=abstentions,
                words_mapped=0,
                words_unmapped={},
            )

        morfessor_mod = _get_morfessor()

        import random

        random.seed(self._seed)

        model = morfessor_mod.BaselineModel()
        model.load_data([(count, word) for word, count in counts.items()])
        model.train_batch()

        # Cache segmentations per surface
        segmented_cache: dict[str, list[str]] = {}

        boundary_marks = (
            tuple(input.profile.boundary_marks)
            if input.profile is not None and hasattr(input.profile, "boundary_marks")
            else ("-", "=")
        )

        for tok in input.tokens:
            if tok.normalized_surface is not None:
                surface = tok.normalized_surface
                span_rep = SpanRepresentation.NORMALIZED
            else:
                surface = tok.raw_surface
                span_rep = SpanRepresentation.RAW

            if not surface or not surface.strip():
                abstentions[tok.id] = Abstention.INSUFFICIENT_EVIDENCE
                continue

            if surface not in segmented_cache:
                parts, _ = model.viterbi_segment(surface)
                segmented_cache[surface] = list(parts)

            parts = segmented_cache[surface]
            analysis_id = self._new_id(IdPrefix.MORPH_ANALYSIS)
            segments: list[MorphSegment] = []
            curr = 0

            for idx, part in enumerate(parts):
                seg_id = self._new_id(IdPrefix.MORPH_SEGMENT)
                p_len = len(part)
                seg = MorphSegment(
                    id=seg_id,
                    analysis_id=analysis_id,
                    ordinal=idx,
                    start=curr,
                    end=curr + p_len,
                    is_zero=False,
                    surface=part,
                    morpheme_id=None,
                    allomorph_id=None,
                    role=None,
                    source_gloss=None,
                    created_at=now,
                )
                segments.append(seg)
                curr += p_len

            kind = AnalysisKind.SEGMENTED if len(segments) > 1 else AnalysisKind.UNSEGMENTED
            sig = segmentation_signature(kind, segments)
            _, breakdown = score_analysis(
                method=self.method_id,
                linked_morphemes=(),
                segments=segments,
                evidence_items=(),
                current_status=LifecycleStatus.CANDIDATE,
            )

            ana = MorphAnalysis(
                id=analysis_id,
                target_token_id=tok.id,
                analysis_kind=kind,
                method=self.method_id,
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
                    to_id=tok.id,
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
            words_mapped=len(analyses),
            words_unmapped={},
        )
