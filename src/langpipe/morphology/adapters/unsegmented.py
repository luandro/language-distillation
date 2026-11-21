"""Unsegmented baseline morphology inducer (M5-PLAN §6 WP5.8, ADR-0017 §5).

Emits exactly one whole-surface segment per token with `morpheme_id=None`, `role=None`,
`analysis_kind=unsegmented`, and `abstention=insufficient_evidence`.
"""

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


def _default_id(prefix: IdPrefix) -> str:
    return new_id(prefix)


class UnsegmentedInducer(MorphologyInducer):
    """The null morphology baseline `unsegmented@0.1.0`.

    Consumes pinned tokens and emits an unsegmented analysis for every token,
    marking the token as abstained with `insufficient_evidence`.
    """

    name: ClassVar[str] = "unsegmented"
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

        for token in input.tokens:
            if token.normalized_surface is not None:
                surface = token.normalized_surface
                span_rep = SpanRepresentation.NORMALIZED
            else:
                surface = token.raw_surface
                span_rep = SpanRepresentation.RAW

            analysis_id = self._new_id(IdPrefix.MORPH_ANALYSIS)
            segment_id = self._new_id(IdPrefix.MORPH_SEGMENT)

            segment = MorphSegment(
                id=segment_id,
                analysis_id=analysis_id,
                ordinal=0,
                start=0,
                end=len(surface),
                is_zero=False,
                surface=surface,
                morpheme_id=None,
                allomorph_id=None,
                role=None,
                source_gloss=None,
                created_at=now,
            )

            sig = segmentation_signature(AnalysisKind.UNSEGMENTED, [segment])

            _, breakdown = score_analysis(
                method=method_str,
                linked_morphemes=(),
                segments=[segment],
                evidence_items=(),
                current_status=LifecycleStatus.CANDIDATE,
            )

            analysis = MorphAnalysis(
                id=analysis_id,
                target_token_id=token.id,
                analysis_kind=AnalysisKind.UNSEGMENTED,
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

            # Invariant check: verify structural correctness against contract
            check_analysis(analysis, [segment], boundary_marks)

            analyses.append(
                MorphAnalysisCandidate(
                    analysis=analysis,
                    segments=[segment],
                    features=[],
                )
            )

            edge = LineageEdge(
                id=self._new_id(IdPrefix.LINEAGE),
                from_id=analysis.id,
                to_id=token.id,
                kind=LineageKind.DERIVED_FROM,
                run_id=input.run_id,
                created_at=now,
            )
            lineage_edges.append(edge)

            abstentions[token.id] = Abstention.INSUFFICIENT_EVIDENCE

        return MorphologyInductionOutput(
            analyses=analyses,
            morphemes=[],
            allomorphs=[],
            features=[],
            evidence_items=[],
            lineage_edges=lineage_edges,
            abstentions=abstentions,
        )


__all__ = ["UnsegmentedInducer"]
