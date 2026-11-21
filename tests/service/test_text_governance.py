"""WP2.11 governance invariants: policy follows lineage through the M2 text layers.

The M2 services are separate work packages; this module drives the same pure components and
the M1/M2 recorder directly to build the raw/normalized/token/form lineage graph, then proves
that governance is inherited from the ancestor sources of every derived object.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType, Operation, PolicyDecision, RunStage
from langpipe.domain.errors import NormalizationFailed, PolicyDenied
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.domain.models.source import SourceObject
from langpipe.extraction.base import ExtractionContext
from langpipe.extraction.registry import EXTRACTORS, default_extractor_for
from langpipe.extraction.service import extract_source
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.languages.base import NORMALIZATION_PROFILES, TOKENIZERS, profile_for
from langpipe.lineage.impact import impact_of
from langpipe.normalization.base import NormalizationResult
from langpipe.segmentation.recorder import (
    NormalizedSegmentInput,
    ObservationRecorder,
    SegmentInput,
    TokenInput,
)
from langpipe.tokenization.base import TokenKind
from tests.service.manifests import spy_all_io, state_counts

FIXTURE_SOURCES = Path(__file__).resolve().parents[1] / "golden" / "fixture" / "sources"
DISTILL_ONLY_SOURCE = "01-parallel-distill"
DIRECT_SOURCE = "02-educational-direct"
EXCLUDED_SOURCE = "06-excluded"
DIRECT_TRAINING = Operation.DIRECT_TRAINING
THIRD_PARTY_API = Operation.THIRD_PARTY_API


@dataclass(frozen=True)
class _Pipeline:
    source_id: str
    raw_segments: tuple[Segment, ...]
    normalized_segments: tuple[Segment, ...]
    tokens: tuple[TokenOccurrence, ...]

    @property
    def form_ids(self) -> tuple[str, ...]:
        return tuple(sorted({t.form_id for t in self.tokens if t.form_id is not None}))

    def object_ids(self) -> tuple[str, ...]:
        return (
            *(segment.id for segment in self.raw_segments),
            *(segment.id for segment in self.normalized_segments),
            *(token.id for token in self.tokens),
            *self.form_ids,
        )


def _build_pipeline(ctx: AppContext, dirname: str) -> _Pipeline:
    """Register + ingest + extract + normalize + tokenize one golden source, recording lineage."""
    registration = register_source(ctx, FIXTURE_SOURCES / dirname / "manifest.yaml")
    ingest_source(ctx, registration.source.key)
    source = registration.source
    recorder = ObservationRecorder(ctx.repo, ctx.clock, ctx.new_id)
    runner = RunRecorder(ctx)

    planned: list[tuple[SourceObject, str]] = []
    for obj in ctx.repo.list_source_objects(source.id):
        name = default_extractor_for(source.source_type, obj.media_type)
        if name is not None:
            planned.append((obj, name))

    extraction_run = runner.start(
        RunStage.EXTRACTION,
        "langpipe.extract",
        {"extractors": {obj.id: name for obj, name in planned}},
        [obj.id for obj, _ in planned],
    )
    raw_segments: list[Segment] = []
    with recorder.unit_of_work():
        for obj, name in planned:
            ctx.raw_store.verify(obj.sha256)
            output = EXTRACTORS.get(name).extract(
                ctx.raw_store.read_bytes(obj.sha256),
                ExtractionContext(
                    source_id=source.id,
                    source_object_id=obj.id,
                    source_type=source.source_type,
                    media_type=obj.media_type,
                    source_languages=source.languages,
                    language=None,
                ),
            )
            raw_segments.extend(
                recorder.record_segments(
                    run_id=extraction_run.id,
                    source_object_id=obj.id,
                    segments=[
                        SegmentInput(
                            ordinal=unit.ordinal,
                            language=unit.language,
                            locator=dict(unit.locator),
                            raw_text=unit.raw_text,
                        )
                        for unit in output.units
                    ],
                )
            )
        runner.succeed(extraction_run.id)

    _Prepared = tuple[Segment, str, NormalizedSegmentInput, NormalizationResult | None]
    prepared: list[_Prepared] = []
    for raw in raw_segments:
        profile_name = profile_for(raw.language).normalization
        try:
            result = NORMALIZATION_PROFILES.get(profile_name).normalize(raw.raw_text)
        except NormalizationFailed:
            result = None
        item = (
            NormalizedSegmentInput(raw.id, None, failed=True)
            if result is None
            else NormalizedSegmentInput(raw.id, result.normalized, failed=False)
        )
        prepared.append((raw, profile_name, item, result))

    groups: dict[str, list[_Prepared]] = {}
    for entry in prepared:
        groups.setdefault(entry[1], []).append(entry)

    profiles_config = {name: [entry[0].id for entry in entries] for name, entries in groups.items()}
    normalization_run = runner.start(
        RunStage.NORMALIZATION,
        "langpipe.normalize",
        {"profiles": profiles_config},
        [raw.id for raw in raw_segments],
    )
    normalized_segments: list[Segment] = []
    normalization_results: dict[str, NormalizationResult] = {}
    with recorder.unit_of_work():
        for profile_name, entries in groups.items():
            built = recorder.record_normalized_segments(
                run_id=normalization_run.id,
                normalization_profile=profile_name,
                items=[entry[2] for entry in entries],
            )
            for entry, segment in zip(entries, built, strict=True):
                normalized_segments.append(segment)
                if entry[3] is not None:
                    normalization_results[segment.id] = entry[3]
        runner.succeed(normalization_run.id)

    tokenization_run = runner.start(
        RunStage.TOKENIZATION,
        "langpipe.tokenize",
        {"normalization_run_id": normalization_run.id},
        [segment.id for segment in normalized_segments],
    )
    tokens: list[TokenOccurrence] = []
    with recorder.unit_of_work():
        for segment in normalized_segments:
            result = normalization_results.get(segment.id)
            profile_name = segment.normalization_profile
            if result is None or profile_name is None:
                continue
            tokenizer_name = profile_for(segment.language).tokenizer
            inputs: list[TokenInput] = []
            for token in TOKENIZERS.get(tokenizer_name).tokenize(result.normalized):
                raw_start, raw_end = result.offsets.raw_span(token.norm_start, token.norm_end)
                raw_surface = segment.raw_text[raw_start:raw_end]
                if not raw_surface.strip():
                    continue
                inputs.append(
                    TokenInput(
                        ordinal=len(inputs),
                        raw_surface=raw_surface,
                        raw_start=raw_start,
                        raw_end=raw_end,
                        form_text=token.surface if token.kind is TokenKind.WORD else None,
                        normalized_surface=token.surface,
                        norm_start=token.norm_start,
                        norm_end=token.norm_end,
                    )
                )
            tokens.extend(
                recorder.record_normalized_tokens(
                    run_id=tokenization_run.id,
                    segment_id=segment.id,
                    tokenizer=tokenizer_name,
                    orthography_profile=profile_name,
                    tokens=inputs,
                )
            )
        runner.succeed(tokenization_run.id)

    return _Pipeline(
        source_id=source.id,
        raw_segments=tuple(raw_segments),
        normalized_segments=tuple(normalized_segments),
        tokens=tuple(tokens),
    )


def _form_ids_for(pipeline: _Pipeline, surface: str) -> set[str]:
    return {
        token.form_id
        for token in pipeline.tokens
        if token.normalized_surface == surface and token.form_id is not None
    }


def test_distill_only_segments_tokens_forms_are_trainable(ctx: AppContext) -> None:
    # ADR-0025: a distill_only label no longer blocks training.
    pipeline = _build_pipeline(ctx, DISTILL_ONLY_SOURCE)

    object_ids = pipeline.object_ids()
    assert object_ids
    for object_id in object_ids:
        assert effective_decision(ctx.repo, object_id, DIRECT_TRAINING) is PolicyDecision.ALLOW, (
            object_id
        )


def test_shared_form_inherits_combined_decisions(ctx: AppContext) -> None:
    distill = _build_pipeline(ctx, DISTILL_ONLY_SOURCE)
    direct = _build_pipeline(ctx, DIRECT_SOURCE)

    distill_forms = _form_ids_for(distill, "mabi")
    direct_forms = _form_ids_for(direct, "mabi")
    # Each source must attest its own (nonempty, single) form, and the two must be the same row.
    assert distill_forms == direct_forms
    assert len(distill_forms) == 1
    form_id = next(iter(distill_forms))

    # The shared Form descends from both sources: the combined decision is inherited.
    assert ancestor_source_ids(ctx.repo, form_id) == sorted([distill.source_id, direct.source_id])

    # Training is allowed under ADR-0025, extraction is allowed, and raw redistribution stays
    # closed for the distill_only ancestor.
    assert effective_decision(ctx.repo, form_id, DIRECT_TRAINING) is PolicyDecision.ALLOW
    assert effective_decision(ctx.repo, form_id, Operation.EXTRACT) is PolicyDecision.ALLOW
    assert effective_decision(ctx.repo, form_id, Operation.REDISTRIBUTE_RAW) is PolicyDecision.DENY


def test_direct_only_token_allows_direct_training_decision(ctx: AppContext) -> None:
    direct = _build_pipeline(ctx, DIRECT_SOURCE)

    token = next(
        token
        for token in direct.tokens
        if token.normalized_surface == "shara" and token.form_id is not None
    )

    assert effective_decision(ctx.repo, token.id, DIRECT_TRAINING) is PolicyDecision.ALLOW
    assert effective_decision(ctx.repo, token.form_id, DIRECT_TRAINING) is PolicyDecision.ALLOW


def test_excluded_source_has_no_descendants_after_text_pipeline(ctx: AppContext) -> None:
    _build_pipeline(ctx, DISTILL_ONLY_SOURCE)
    registration = register_source(ctx, FIXTURE_SOURCES / EXCLUDED_SOURCE / "manifest.yaml")
    excluded = registration.source
    before = state_counts(ctx)

    # Both gates must refuse the excluded source, with no store I/O. The extract denial must not be
    # masked by the still-not-ingested status (policy is checked before the ingestion check).
    with spy_all_io(ctx) as mocks:
        with pytest.raises(PolicyDenied):
            ingest_source(ctx, excluded.id)
        with pytest.raises(PolicyDenied):
            extract_source(ctx, excluded.id)
        assert all(mock.call_count == 0 for mock in mocks)

    # Only the two denial audit events are recorded: no run, semantic row, lineage or blob.
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 2}
    assert ctx.repo.descendants(excluded.id) == []
    assert effective_decision(ctx.repo, excluded.id, DIRECT_TRAINING) is PolicyDecision.DENY


def test_impact_of_source_reaches_normalized_segments_tokens_and_forms(ctx: AppContext) -> None:
    pipeline = _build_pipeline(ctx, DISTILL_ONLY_SOURCE)

    impact = {
        entry.object_id: entry.entity_type for entry in impact_of(ctx.repo, pipeline.source_id)
    }

    for segment in (*pipeline.raw_segments, *pipeline.normalized_segments):
        assert impact[segment.id] is EntityType.SEGMENT
    for token in pipeline.tokens:
        assert impact[token.id] is EntityType.TOKEN_OCCURRENCE
    for form_id in pipeline.form_ids:
        assert impact[form_id] is EntityType.FORM


def test_third_party_api_denied_for_all_m2_outputs(ctx: AppContext) -> None:
    pipeline = _build_pipeline(ctx, DISTILL_ONLY_SOURCE)

    for object_id in pipeline.object_ids():
        assert effective_decision(ctx.repo, object_id, THIRD_PARTY_API) is PolicyDecision.DENY


def test_ancestor_source_ids_follow_lineage(ctx: AppContext) -> None:
    distill = _build_pipeline(ctx, DISTILL_ONLY_SOURCE)
    direct = _build_pipeline(ctx, DIRECT_SOURCE)

    raw_segment = distill.raw_segments[0]
    token = direct.tokens[0]

    assert ancestor_source_ids(ctx.repo, raw_segment.id) == [distill.source_id]
    assert ancestor_source_ids(ctx.repo, token.id) == [direct.source_id]
