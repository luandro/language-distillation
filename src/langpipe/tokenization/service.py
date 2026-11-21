"""Stage 3b: ``TokenizationService`` turns normalized segments into tokens and forms.

Only OK normalized segments are tokenized. A tokenizer never sees raw text: the normalized
offset map (rebuilt from the pinned profile) maps each normalized span back to its raw span and
raw surface. If that mapping is degenerate (empty or whitespace raw surface) the whole segment
is reported as ``token_span_unmappable`` and gets no tokens (never fabricated). Punct/number
tokens carry no Form; word Forms are ``get_or_create`` by (language, profile, text) (M2 E7).
"""

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    EntityType,
    LineageKind,
    RunIoRole,
    RunStage,
    RunStatus,
    SegmentStatus,
    most_restrictive,
)
from langpipe.domain.errors import InvalidLineage, SchemaViolation
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.domain.models.run import Artifact, ProcessingRun
from langpipe.ingestion.runs import RunRecorder
from langpipe.languages.base import NORMALIZATION_PROFILES, TOKENIZERS, profile_for
from langpipe.logging import log_event
from langpipe.normalization.service import ensure_normalize_allowed
from langpipe.segmentation.recorder import ObservationRecorder, TokenInput
from langpipe.text.registry import versioned_name
from langpipe.tokenization.base import TokenKind

TOKENIZE_TOOL = "langpipe.tokenize"
REPORT_SCHEMA = "tokenization-report"
REPORT_SCHEMA_VERSION = 1
COUNT_FIELD = "count"
SKIP_NORMALIZATION_FAILED = "normalization_failed"
SKIP_UNMAPPABLE = "token_span_unmappable"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenizationSummary:
    run: ProcessingRun
    tokens: int
    forms: int
    skipped_failed_segments: int
    report: Artifact | None
    reused: bool


@dataclass(frozen=True)
class _Plan:
    segment: Segment
    inputs: tuple[TokenInput, ...]
    counts: Mapping[str, int]
    skip_reason: str | None


def tokenize_normalization(
    ctx: AppContext,
    normalization_run_id: str,
    *,
    tokenizers: Mapping[str, str] | None = None,
) -> TokenizationSummary:
    normalization_run = ctx.repo.get_run(normalization_run_id)
    if (
        normalization_run.status is not RunStatus.SUCCEEDED
        or normalization_run.stage is not RunStage.NORMALIZATION
    ):
        raise InvalidLineage()

    segments = ctx.repo.list_segments_for_run(normalization_run_id)
    source_ids = _ancestor_source_ids(ctx, normalization_run, segments)
    if not source_ids:
        raise InvalidLineage()

    ensure_normalize_allowed(ctx, sorted(source_ids))

    tokenizer_by_language = _resolve_tokenizers(segments, tokenizers)
    config: dict[str, JsonValue] = {
        "normalization_run_id": normalization_run_id,
        "tokenizers": dict(sorted(tokenizer_by_language.items())),
    }
    input_ids = [segment.id for segment in segments]
    recorder = RunRecorder(ctx)
    reusable = recorder.find_reusable(RunStage.TOKENIZATION, TOKENIZE_TOOL, config, input_ids)
    if reusable is not None:
        return _reused_summary(ctx, reusable)

    access_class = _access_class(ctx, source_ids)
    run = recorder.start(RunStage.TOKENIZATION, TOKENIZE_TOOL, config, input_ids)
    observer = ObservationRecorder(ctx.repo, ctx.clock, ctx.new_id)
    built: list[tuple[_Plan, list[TokenOccurrence]]] = []
    skipped: list[dict[str, str]] = []
    report: Artifact | None = None
    succeeded: ProcessingRun = run
    try:
        plans = _prepare(segments, tokenizer_by_language)
        with observer.unit_of_work():
            # Every input segment (failed ones included) is a run input; only OK ones get tokens.
            for plan in plans:
                ctx.repo.add_run_io(run.id, plan.segment.id, RunIoRole.INPUT)
            for plan in plans:
                if plan.skip_reason is not None:
                    skipped.append({"segment_id": plan.segment.id, "reason": plan.skip_reason})
                    continue
                profile_name = plan.segment.normalization_profile
                if profile_name is None:
                    raise InvalidLineage()
                tokens = observer.record_normalized_tokens(
                    run_id=run.id,
                    segment_id=plan.segment.id,
                    tokenizer=tokenizer_by_language[plan.segment.language],
                    orthography_profile=profile_name,
                    tokens=plan.inputs,
                )
                built.append((plan, tokens))
            report = _store_report(
                ctx, run, normalization_run_id, tokenizer_by_language, built, skipped, access_class
            )
            succeeded = recorder.succeed(run.id)
    except BaseException as error:
        recorder.fail(run.id, error)
        raise

    total = sum(plan.counts["tokens"] for plan, _tokens in built)
    forms = len(_form_ids(built))
    log_event(logger, "tokenization.succeeded", run_id=run.id, **{COUNT_FIELD: total})
    return TokenizationSummary(succeeded, total, forms, len(skipped), report, False)


def _prepare(segments: Sequence[Segment], tokenizer_by_language: Mapping[str, str]) -> list[_Plan]:
    plans: list[_Plan] = []
    for segment in segments:
        if segment.status is not SegmentStatus.OK or segment.normalization_profile is None:
            plans.append(_Plan(segment, (), {}, SKIP_NORMALIZATION_FAILED))
            continue

        profile = NORMALIZATION_PROFILES.get(segment.normalization_profile)
        result = profile.normalize(segment.raw_text)
        if result.normalized != segment.normalized_text:
            # A profile that no longer reproduces its own output is not tokenizable.
            raise SchemaViolation()

        tokenizer = TOKENIZERS.get(tokenizer_by_language[segment.language])
        inputs: list[TokenInput] = []
        counts = {"tokens": 0, "words": 0, "punct": 0, "numbers": 0}
        unmappable = False
        for token in tokenizer.tokenize(result.normalized):
            raw_start, raw_end = result.offsets.raw_span(token.norm_start, token.norm_end)
            raw_surface = segment.raw_text[raw_start:raw_end]
            if raw_start == raw_end or not raw_surface or not raw_surface.strip():
                unmappable = True
                break
            counts["tokens"] += 1
            if token.kind is TokenKind.WORD:
                counts["words"] += 1
                form_text: str | None = token.surface
            elif token.kind is TokenKind.PUNCT:
                counts["punct"] += 1
                form_text = None
            else:
                counts["numbers"] += 1
                form_text = None
            inputs.append(
                TokenInput(
                    ordinal=len(inputs),
                    raw_surface=raw_surface,
                    raw_start=raw_start,
                    raw_end=raw_end,
                    form_text=form_text,
                    normalized_surface=token.surface,
                    norm_start=token.norm_start,
                    norm_end=token.norm_end,
                )
            )
        if unmappable:
            plans.append(_Plan(segment, (), {}, SKIP_UNMAPPABLE))
        else:
            plans.append(_Plan(segment, tuple(inputs), counts, None))
    return plans


def _store_report(
    ctx: AppContext,
    run: ProcessingRun,
    normalization_run_id: str,
    tokenizer_by_language: Mapping[str, str],
    built: Sequence[tuple[_Plan, list[TokenOccurrence]]],
    skipped: Sequence[dict[str, str]],
    access_class: AccessClass,
) -> Artifact:
    rows = [
        {
            "segment_id": plan.segment.id,
            "tokens": plan.counts["tokens"],
            "words": plan.counts["words"],
            "punct": plan.counts["punct"],
            "numbers": plan.counts["numbers"],
        }
        for plan, _tokens in built
    ]
    payload = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "normalization_run_id": normalization_run_id,
        "run_id": run.id,
        "tokenizers": dict(sorted(tokenizer_by_language.items())),
        "segments": rows,
        "skipped": list(skipped),
        "totals": {
            "tokens": sum(plan.counts["tokens"] for plan, _tokens in built),
            "words": sum(plan.counts["words"] for plan, _tokens in built),
            "punct": sum(plan.counts["punct"] for plan, _tokens in built),
            "numbers": sum(plan.counts["numbers"] for plan, _tokens in built),
            "forms": len(_form_ids(built)),
            "skipped": len(skipped),
        },
    }
    stored = ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
    artifact = Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.TOKENIZATION_REPORT,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=access_class,
        schema_name=REPORT_SCHEMA,
        schema_version=REPORT_SCHEMA_VERSION,
        created_at=ctx.clock(),
    )
    ctx.repo.add_artifact(artifact)
    ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
    for plan, _tokens in built:
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=artifact.id,
                to_id=plan.segment.id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )
    return artifact


def _form_ids(built: Sequence[tuple[_Plan, list[TokenOccurrence]]]) -> set[str]:
    return {
        token.form_id for _plan, tokens in built for token in tokens if token.form_id is not None
    }


def _resolve_tokenizers(
    segments: Sequence[Segment], overrides: Mapping[str, str] | None
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for segment in segments:
        if segment.language in resolved:
            continue
        override = None if overrides is None else overrides.get(segment.language)
        name = override if override is not None else profile_for(segment.language).tokenizer
        resolved[segment.language] = versioned_name(TOKENIZERS.get(name))
    return resolved


def _ancestor_source_ids(
    ctx: AppContext, normalization_run: ProcessingRun, segments: Sequence[Segment]
) -> set[str]:
    source_ids = {segment.source_id for segment in segments}
    if source_ids:
        return source_ids

    # No normalized outputs: recover ancestry from the normalization run's input segments.
    for object_id, role in ctx.repo.list_run_io(normalization_run.id):
        if role is RunIoRole.INPUT and ctx.repo.entity_type_of(object_id) is EntityType.SEGMENT:
            source_ids.add(ctx.repo.get_segment(object_id).source_id)
    if source_ids:
        return source_ids

    # Or from the configured extraction run's source objects, when it produced zero segments.
    extraction_run_id = normalization_run.config.get("extraction_run_id")
    if isinstance(extraction_run_id, str):
        for object_id, role in ctx.repo.list_run_io(extraction_run_id):
            if (
                role is RunIoRole.INPUT
                and ctx.repo.entity_type_of(object_id) is EntityType.SOURCE_OBJECT
            ):
                source_ids.add(ctx.repo.get_source_object(object_id).source_id)
    return source_ids


def _access_class(ctx: AppContext, source_ids: Iterable[str]) -> AccessClass:
    classes = [
        obj.access_class
        for source_id in sorted(source_ids)
        for obj in ctx.repo.list_source_objects(source_id)
    ]
    if not classes:
        raise InvalidLineage()
    return most_restrictive(classes)


def _reused_summary(ctx: AppContext, run: ProcessingRun) -> TokenizationSummary:
    report = _report_of(ctx, run.id)
    tokens = forms = skipped = 0
    if report is not None:
        totals = json.loads(ctx.artifact_store.read_bytes(report.sha256))["totals"]
        tokens = int(totals["tokens"])
        forms = int(totals["forms"])
        skipped = int(totals["skipped"])
    return TokenizationSummary(run, tokens, forms, skipped, report, True)


def _report_of(ctx: AppContext, run_id: str) -> Artifact | None:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT:
            return ctx.repo.get_artifact(object_id)
    return None
