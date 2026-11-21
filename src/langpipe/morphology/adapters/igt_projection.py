"""Stage 8 IGT projection morphology inducer `igt_projection@0.1.0` (M5-PLAN §6 WP5.10, Gate 39).

Algorithm (deterministic, §7.9):
1. Splits at profile boundary marks if present;
2. Else suffix/prefix stripping against bound allomorphs from pinned inventory with
   remainder >= min_stem_length;
3. Enumerates all consistent segmentations up to cap (default 8, config-pinned);
4. No match -> abstains with `insufficient_evidence` (service writes nothing for token);
5. Emits `morphology_induction`/`supports` evidence with
   `independence_group="inventory:" + inv_run_id`;
6. Emits `morphology_induction`/`contradicts` evidence when inventory holds an IGT assertion
   for the identical normalized surface with a different signature;
7. Never assigns features, never creates morphemes (unknown pieces have `morpheme_id=None`,
   `role=unknown`).
"""

import itertools
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import ClassVar

from langpipe.domain.enums import (
    Abstention,
    AnalysisKind,
    EvidenceKind,
    EvidencePolarity,
    LifecycleStatus,
    LineageKind,
    MorphRole,
    SpanRepresentation,
)
from langpipe.domain.ids import IdFactory, IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.morphology import (
    Allomorph,
    MorphAnalysis,
    Morpheme,
    MorphSegment,
)
from langpipe.languages.base import MorphologyProfile
from langpipe.morphology.base import (
    MorphAnalysisCandidate,
    MorphologyInducer,
    MorphologyInductionInput,
    MorphologyInductionOutput,
)
from langpipe.morphology.scoring import score_analysis
from langpipe.morphology.spans import check_analysis, check_segments, segmentation_signature

DEFAULT_SEGMENTATION_CAP = 8

BOUND_ROLES: frozenset[MorphRole] = frozenset(
    {
        MorphRole.CLITIC,
        MorphRole.UNKNOWN_BOUND,
        MorphRole.INFLECTIONAL_AFFIX,
        MorphRole.DERIVATIONAL_AFFIX,
        MorphRole.BOUND_LEXICAL,
        MorphRole.REDUPLICANT,
    }
)


def _default_id(prefix: IdPrefix) -> str:
    return new_id(prefix)


def _split_boundary_marks(
    surface: str, boundary_marks: tuple[str, ...]
) -> list[tuple[int, int, str]]:
    """Split surface at boundary marks into contiguous non-boundary slices."""
    pieces: list[tuple[int, int, str]] = []
    start: int | None = None
    for i, ch in enumerate(surface):
        if ch in boundary_marks:
            if start is not None:
                pieces.append((start, i, surface[start:i]))
                start = None
        else:
            if start is None:
                start = i
    if start is not None:
        pieces.append((start, len(surface), surface[start : len(surface)]))
    return pieces


def _get_prefix_chains(
    surface: str,
    n: int,
    idx: int,
    bound_by_form: dict[str, list[tuple[Morpheme, Allomorph]]],
) -> list[list[tuple[int, int]]]:
    chains: list[list[tuple[int, int]]] = [[]]
    for length in range(1, n - idx):
        sub = surface[idx : idx + length]
        if sub in bound_by_form:
            for sc in _get_prefix_chains(surface, n, idx + length, bound_by_form):
                chains.append([(idx, idx + length)] + sc)
    return chains


def _get_suffix_chains(
    surface: str,
    idx: int,
    bound_by_form: dict[str, list[tuple[Morpheme, Allomorph]]],
) -> list[list[tuple[int, int]]]:
    chains: list[list[tuple[int, int]]] = [[]]
    for length in range(1, idx + 1):
        sub = surface[idx - length : idx]
        if sub in bound_by_form:
            for sc in _get_suffix_chains(surface, idx - length, bound_by_form):
                chains.append(sc + [(idx - length, idx)])
    return chains


type SegmentPiece = tuple[int, int, str, Morpheme | None, Allomorph | None]


class IgtProjectionInducer(MorphologyInducer):
    """The Stage 8 IGT projection inducer `igt_projection@0.1.0`."""

    name: ClassVar[str] = "igt_projection"
    version: ClassVar[str] = "0.1.0"

    def __init__(self, new_id_factory: IdFactory | None = None) -> None:
        self._new_id: IdFactory = new_id_factory if new_id_factory is not None else _default_id

    @property
    def method_id(self) -> str:
        return f"{self.name}@{self.version}"

    def induce(self, input: MorphologyInductionInput) -> MorphologyInductionOutput:
        now = datetime.now(UTC)
        profile: MorphologyProfile = (
            input.profile
            if input.profile is not None and isinstance(input.profile, MorphologyProfile)
            else MorphologyProfile()
        )
        boundary_marks = tuple(profile.boundary_marks)
        min_stem_length = int(getattr(profile, "min_stem_length", 2))

        # Config cap if pinned in policy or profile
        cap = DEFAULT_SEGMENTATION_CAP
        if input.policy is not None and hasattr(input.policy, "cap"):
            cap = int(input.policy.cap)
        elif input.policy is not None and isinstance(input.policy, dict):
            raw_cap = input.policy.get("cap", input.policy.get("segmentation_cap", cap))
            if raw_cap is not None:
                cap = int(raw_cap)

        abstentions: dict[str, Abstention] = {}

        # If no inventory is provided, all tokens honestly abstain
        if input.inventory is None or not input.inventory.run_id:
            for token in input.tokens:
                abstentions[token.id] = Abstention.INSUFFICIENT_EVIDENCE
            return MorphologyInductionOutput(abstentions=abstentions)

        inv_run_id = input.inventory.run_id
        morphemes_by_id = {m.id: m for m in input.inventory.morphemes}

        bound_morpheme_ids = {m.id for m in input.inventory.morphemes if m.role in BOUND_ROLES}

        allomorphs_by_form: dict[str, list[tuple[Morpheme, Allomorph]]] = defaultdict(list)
        for inv_allo in input.inventory.allomorphs:
            if inv_allo.morpheme_id in morphemes_by_id and not inv_allo.is_zero and inv_allo.form:
                allomorphs_by_form[inv_allo.form].append(
                    (morphemes_by_id[inv_allo.morpheme_id], inv_allo)
                )

        bound_by_form: dict[str, list[tuple[Morpheme, Allomorph]]] = defaultdict(list)
        for inv_allo in input.inventory.allomorphs:
            if (
                inv_allo.morpheme_id in bound_morpheme_ids
                and not inv_allo.is_zero
                and inv_allo.form
            ):
                bound_by_form[inv_allo.form].append(
                    (morphemes_by_id[inv_allo.morpheme_id], inv_allo)
                )

        analyses: list[MorphAnalysisCandidate] = []
        evidence_items: list[EvidenceItem] = []
        lineage_edges: list[LineageEdge] = []

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

            has_boundary = any(bm in surface for bm in boundary_marks)
            candidate_segmentations: list[Sequence[SegmentPiece]] = []

            if has_boundary:
                # 1. Split at boundary marks
                pieces = _split_boundary_marks(surface, boundary_marks)
                if pieces:
                    options_per_piece: list[list[SegmentPiece]] = []
                    for start, end, piece_str in pieces:
                        matches = allomorphs_by_form.get(piece_str, [])
                        if matches:
                            options_per_piece.append(
                                [(start, end, piece_str, m, a) for m, a in matches]
                            )
                        else:
                            options_per_piece.append([(start, end, piece_str, None, None)])

                    for seg in itertools.product(*options_per_piece):
                        candidate_segmentations.append(seg)
            else:
                # 2. Suffix/prefix stripping against bound allomorphs
                n = len(surface)
                all_prefixes = _get_prefix_chains(surface, n, 0, bound_by_form)
                all_suffixes = _get_suffix_chains(surface, n, bound_by_form)

                for p_chain in all_prefixes:
                    p_end = p_chain[-1][1] if p_chain else 0
                    for s_chain in all_suffixes:
                        s_start = s_chain[0][0] if s_chain else n
                        if s_start >= p_end + min_stem_length and (p_chain or s_chain):
                            # Valid stem remainder >= min_stem_length
                            stem_start = p_end
                            stem_end = s_start
                            stem_text = surface[stem_start:stem_end]

                            options_per_segment: list[list[SegmentPiece]] = []

                            for p_start, p_fin in p_chain:
                                sub = surface[p_start:p_fin]
                                matches = bound_by_form[sub]
                                options_per_segment.append(
                                    [(p_start, p_fin, sub, m, a) for m, a in matches]
                                )

                            stem_matches = allomorphs_by_form.get(stem_text, [])
                            if stem_matches:
                                options_per_segment.append(
                                    [
                                        (stem_start, stem_end, stem_text, m, a)
                                        for m, a in stem_matches
                                    ]
                                )
                            else:
                                options_per_segment.append(
                                    [(stem_start, stem_end, stem_text, None, None)]
                                )

                            for s_start_span, s_fin in s_chain:
                                sub = surface[s_start_span:s_fin]
                                matches = bound_by_form[sub]
                                options_per_segment.append(
                                    [(s_start_span, s_fin, sub, m, a) for m, a in matches]
                                )

                            for seg in itertools.product(*options_per_segment):
                                candidate_segmentations.append(seg)

            if not candidate_segmentations:
                # 4. No match -> abstain
                abstentions[token.id] = Abstention.INSUFFICIENT_EVIDENCE
                continue

            # Compute preliminary signature and sort deterministically
            unique_candidates: dict[str, Sequence[SegmentPiece]] = {}
            for cand_seg in candidate_segmentations:
                # Build mock dict for signature calculation
                seg_dicts = [
                    {
                        "start": start,
                        "end": end,
                        "is_zero": False,
                        "morpheme_id": m.id if m is not None else None,
                        "ordinal": idx,
                    }
                    for idx, (start, end, _, m, _) in enumerate(cand_seg)
                ]
                sig = segmentation_signature(AnalysisKind.SEGMENTED, seg_dicts)
                if sig not in unique_candidates:
                    unique_candidates[sig] = cand_seg

            # Deterministic sorting by signature digest
            sorted_signatures = sorted(unique_candidates.keys())[:cap]

            for sig in sorted_signatures:
                seg_items = unique_candidates[sig]
                analysis_id = self._new_id(IdPrefix.MORPH_ANALYSIS)

                segments: list[MorphSegment] = []
                for idx, (start, end, seg_surface, m, allo) in enumerate(seg_items):
                    seg_id = self._new_id(IdPrefix.MORPH_SEGMENT)
                    role = m.role if m is not None else MorphRole.UNKNOWN
                    morph_seg = MorphSegment(
                        id=seg_id,
                        analysis_id=analysis_id,
                        ordinal=idx,
                        start=start,
                        end=end,
                        is_zero=False,
                        surface=seg_surface,
                        morpheme_id=m.id if m is not None else None,
                        allomorph_id=allo.id if allo is not None else None,
                        role=role,
                        source_gloss=None,
                        created_at=now,
                    )
                    segments.append(morph_seg)

                # Check segments contract
                check_segments(surface, segments, boundary_marks)

                # Evidence: supports
                token_evidence: list[EvidenceItem] = []
                sup_evi = EvidenceItem(
                    id=self._new_id(IdPrefix.EVIDENCE),
                    kind=EvidenceKind.MORPHOLOGY_INDUCTION,
                    polarity=EvidencePolarity.SUPPORTS,
                    target_id=analysis_id,
                    independence_group=f"inventory:{inv_run_id}",
                    claim={
                        "method": self.method_id,
                        "inventory_run_id": inv_run_id,
                    },
                    run_id=input.run_id,
                    created_at=now,
                )
                token_evidence.append(sup_evi)

                # Contradiction evidence when inventory holds an IGT assertion for the identical
                # normalized surface with a different signature
                if input.inventory.surface_signatures:
                    asserted_sigs = input.inventory.surface_signatures.get(surface, ())
                    if asserted_sigs and sig not in asserted_sigs:
                        contra_evi = EvidenceItem(
                            id=self._new_id(IdPrefix.EVIDENCE),
                            kind=EvidenceKind.MORPHOLOGY_INDUCTION,
                            polarity=EvidencePolarity.CONTRADICTS,
                            target_id=analysis_id,
                            independence_group=f"inventory:{inv_run_id}",
                            claim={
                                "method": self.method_id,
                                "inventory_run_id": inv_run_id,
                                "asserted_signatures": list(asserted_sigs),
                                "projected_signature": sig,
                            },
                            run_id=input.run_id,
                            created_at=now,
                        )
                        token_evidence.append(contra_evi)

                # Score analysis
                linked_morphemes = [m for _, _, _, m, _ in seg_items if m is not None]
                status, score_bd = score_analysis(
                    method=self.method_id,
                    linked_morphemes=linked_morphemes,
                    segments=segments,
                    evidence_items=token_evidence,
                    current_status=LifecycleStatus.CANDIDATE,
                )

                analysis = MorphAnalysis(
                    id=analysis_id,
                    target_token_id=token.id,
                    analysis_kind=AnalysisKind.SEGMENTED,
                    method=self.method_id,
                    span_representation=span_rep,
                    surface=surface,
                    signature=sig,
                    abstention=None,
                    status=status,
                    score_breakdown=score_bd,
                    run_id=input.run_id,
                    created_at=now,
                )
                check_analysis(analysis, segments, boundary_marks)

                analyses.append(MorphAnalysisCandidate(analysis=analysis, segments=segments))
                evidence_items.extend(token_evidence)

                # Lineage edges
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
                seen_morphemes: set[str] = set()
                for m in linked_morphemes:
                    if m.id not in seen_morphemes:
                        seen_morphemes.add(m.id)
                        lineage_edges.append(
                            LineageEdge(
                                id=self._new_id(IdPrefix.LINEAGE),
                                from_id=analysis_id,
                                to_id=m.id,
                                kind=LineageKind.DERIVED_FROM,
                                run_id=input.run_id,
                                created_at=now,
                            )
                        )

        return MorphologyInductionOutput(
            analyses=analyses,
            morphemes=[],
            allomorphs=[],
            features=[],
            evidence_items=evidence_items,
            lineage_edges=lineage_edges,
            abstentions=abstentions,
        )


__all__ = ["IgtProjectionInducer"]
