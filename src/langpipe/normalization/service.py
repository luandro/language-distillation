"""Stage 3a: ``NormalizationService`` turns extracted raw segments into derived normalized ones.

A normalization run writes a *new* ``Segment`` per input raw segment (ADR-0010): it copies
``raw_text``, ``locator``, ``language``, ``source_id``, ``source_object_id`` and ``ordinal``
verbatim, sets ``normalized_text``/``normalization_profile`` (or ``status=normalization_failed``),
and links it with ``normalized_from``. The raw rows are never touched.

Reports hold identifiers, counts, code-point offsets and rule names only, never text (M2 E10).
"""

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    AuditEventType,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    RunStatus,
    SegmentStatus,
    SourceStatus,
    most_restrictive,
)
from langpipe.domain.errors import (
    AmbiguousInput,
    InvalidLineage,
    NormalizationFailed,
    NotFound,
    PolicyDenied,
)
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import Segment
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.domain.models.source import Source, SourceObject
from langpipe.governance import effective_policy
from langpipe.governance.policy import resolve
from langpipe.ingestion.runs import RunRecorder
from langpipe.languages.base import NORMALIZATION_PROFILES, profile_for
from langpipe.logging import log_event
from langpipe.normalization.base import NormalizationEvent, NormalizationResult
from langpipe.segmentation.recorder import NormalizedSegmentInput, ObservationRecorder
from langpipe.text.registry import versioned_name

NORMALIZE_TOOL = "langpipe.normalize"
REPORT_SCHEMA = "normalization-report"
REPORT_SCHEMA_VERSION = 1
COUNT_FIELD = "count"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizationResultSummary:
    run: ProcessingRun
    segments: int
    failed: int
    report: Artifact | None
    reused: bool


@dataclass(frozen=True)
class _Entry:
    raw: Segment
    profile: str
    item: NormalizedSegmentInput
    result: NormalizationResult | None
    failure_code: str | None


def normalize_extraction(
    ctx: AppContext,
    extraction_run_id: str,
    *,
    profiles: Mapping[str, str] | None = None,
) -> NormalizationResultSummary:
    extraction_run = ctx.repo.get_run(extraction_run_id)
    if (
        extraction_run.status is not RunStatus.SUCCEEDED
        or extraction_run.stage is not RunStage.EXTRACTION
    ):
        raise InvalidLineage()

    raw_segments = ctx.repo.list_segments_for_run(extraction_run_id)
    source_objects = _input_source_objects(ctx, extraction_run_id)
    source_ids = sorted({obj.source_id for obj in source_objects})
    if not source_ids:
        raise InvalidLineage()
    if any(segment.source_id not in source_ids for segment in raw_segments):
        raise InvalidLineage()

    ensure_normalize_allowed(ctx, source_ids)

    profile_by_language = _resolve_profiles(raw_segments, profiles)
    config: dict[str, JsonValue] = {
        "extraction_run_id": extraction_run_id,
        "profiles": dict(sorted(profile_by_language.items())),
    }
    input_ids = [segment.id for segment in raw_segments]
    recorder = RunRecorder(ctx)
    reusable = recorder.find_reusable(RunStage.NORMALIZATION, NORMALIZE_TOOL, config, input_ids)
    if reusable is not None:
        return _reused_summary(ctx, reusable)

    access_class = most_restrictive(obj.access_class for obj in source_objects)
    run = recorder.start(RunStage.NORMALIZATION, NORMALIZE_TOOL, config, input_ids)
    observer = ObservationRecorder(ctx.repo, ctx.clock, ctx.new_id)
    built: list[tuple[_Entry, Segment]] = []
    report: Artifact | None = None
    succeeded: ProcessingRun = run
    try:
        entries = _prepare(raw_segments, profile_by_language)
        with observer.unit_of_work():
            built = _record(observer, run, entries)
            report = _store_report(
                ctx, run, extraction_run_id, profile_by_language, built, access_class
            )
            succeeded = recorder.succeed(run.id)
    except BaseException as error:
        recorder.fail(run.id, error)
        raise

    total = len(built)
    failed = sum(
        1 for _entry, segment in built if segment.status is SegmentStatus.NORMALIZATION_FAILED
    )
    log_event(logger, "normalization.succeeded", run_id=run.id, **{COUNT_FIELD: total})
    return NormalizationResultSummary(succeeded, total, failed, report, False)


def select_extraction_run(ctx: AppContext, source: Source, run_id: str | None) -> ProcessingRun:
    """Resolve one succeeded extraction run for a source: explicit id, else the unique one."""
    object_ids = {obj.id for obj in ctx.repo.list_source_objects(source.id)}
    if run_id is not None:
        run = ctx.repo.get_run(run_id)
        if (
            run.status is not RunStatus.SUCCEEDED
            or run.stage is not RunStage.EXTRACTION
            or not _input_ids(ctx, run.id) <= object_ids
        ):
            raise InvalidLineage()
        return run

    candidates: dict[str, ProcessingRun] = {}
    for object_id in sorted(object_ids):
        for run in ctx.repo.list_runs_with_input(
            object_id, RunStage.EXTRACTION, RunStatus.SUCCEEDED
        ):
            candidates[run.id] = run
    if not candidates:
        raise NotFound(EntityType.PROCESSING_RUN.value, source.id)
    if len(candidates) > 1:
        raise AmbiguousInput(RunStage.EXTRACTION, len(candidates))
    return next(iter(candidates.values()))


def ensure_normalize_allowed(ctx: AppContext, source_ids: Sequence[str]) -> None:
    """One audit event and ``PolicyDenied`` for the first source that may not be normalized."""
    try:
        with ctx.repo.transaction():
            ctx.repo.lock_sources(sorted(source_ids))
            for source_id in sorted(source_ids):
                source = ctx.repo.get_source(source_id)
                decision = resolve(effective_policy(ctx.repo, source), Operation.NORMALIZE)
                if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                    raise PolicyDenied(source_id, Operation.NORMALIZE, decision)
    except PolicyDenied as exc:
        _record_denial(ctx, exc.source_id, exc.decision)
        raise


def _prepare(
    raw_segments: Sequence[Segment], profile_by_language: Mapping[str, str]
) -> list[_Entry]:
    entries: list[_Entry] = []
    for raw in raw_segments:
        name = profile_by_language[raw.language]
        profile = NORMALIZATION_PROFILES.get(name)
        try:
            result = profile.normalize(raw.raw_text)
        except NormalizationFailed as error:
            entries.append(
                _Entry(raw, name, NormalizedSegmentInput(raw.id, None, True), None, error.code)
            )
        else:
            entries.append(
                _Entry(
                    raw,
                    name,
                    NormalizedSegmentInput(raw.id, result.normalized, False),
                    result,
                    None,
                )
            )
    return entries


def _record(
    observer: ObservationRecorder, run: ProcessingRun, entries: Sequence[_Entry]
) -> list[tuple[_Entry, Segment]]:
    groups: dict[str, list[_Entry]] = {}
    for entry in entries:
        groups.setdefault(entry.profile, []).append(entry)

    built: list[tuple[_Entry, Segment]] = []
    for profile_name in sorted(groups):
        group = groups[profile_name]
        segments = observer.record_normalized_segments(
            run_id=run.id,
            normalization_profile=profile_name,
            items=[entry.item for entry in group],
        )
        built.extend(zip(group, segments, strict=True))
    return built


def _store_report(
    ctx: AppContext,
    run: ProcessingRun,
    extraction_run_id: str,
    profile_by_language: Mapping[str, str],
    built: Sequence[tuple[_Entry, Segment]],
    access_class: AccessClass,
) -> Artifact:
    failure_codes: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    for entry, segment in built:
        if entry.failure_code is not None:
            failure_codes[entry.failure_code] = failure_codes.get(entry.failure_code, 0) + 1
        result = entry.result
        rows.append(
            {
                "segment_id": segment.id,
                "raw_segment_id": entry.raw.id,
                "status": segment.status.value,
                "events": [] if result is None else [_event_row(event) for event in result.events],
                "diagnostics": {} if result is None else dict(result.diagnostics),
            }
        )

    failed = sum(
        1 for _entry, segment in built if segment.status is SegmentStatus.NORMALIZATION_FAILED
    )
    payload = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "extraction_run_id": extraction_run_id,
        "run_id": run.id,
        "profiles": dict(sorted(profile_by_language.items())),
        "segments": rows,
        "totals": {"segments": len(built), "failed": failed},
        "failure_codes": dict(sorted(failure_codes.items())),
    }
    stored = ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
    artifact = Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.NORMALIZATION_REPORT,
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
    for _entry, segment in built:
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=artifact.id,
                to_id=segment.id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )
    return artifact


def _event_row(event: NormalizationEvent) -> dict[str, object]:
    return {
        "rule": event.rule,
        "raw_start": event.raw_start,
        "raw_end": event.raw_end,
        "norm_start": event.norm_start,
        "norm_end": event.norm_end,
    }


def _resolve_profiles(
    raw_segments: Sequence[Segment], overrides: Mapping[str, str] | None
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for segment in raw_segments:
        if segment.language in resolved:
            continue
        override = None if overrides is None else overrides.get(segment.language)
        name = override if override is not None else profile_for(segment.language).normalization
        resolved[segment.language] = versioned_name(NORMALIZATION_PROFILES.get(name))
    return resolved


def _input_source_objects(ctx: AppContext, run_id: str) -> list[SourceObject]:
    objects: list[SourceObject] = []
    for object_id, role in ctx.repo.list_run_io(run_id):
        if (
            role is RunIoRole.INPUT
            and ctx.repo.entity_type_of(object_id) is EntityType.SOURCE_OBJECT
        ):
            objects.append(ctx.repo.get_source_object(object_id))
    return objects


def _input_ids(ctx: AppContext, run_id: str) -> set[str]:
    return {
        object_id for object_id, role in ctx.repo.list_run_io(run_id) if role is RunIoRole.INPUT
    }


def _reused_summary(ctx: AppContext, run: ProcessingRun) -> NormalizationResultSummary:
    segments = ctx.repo.list_segments_for_run(run.id)
    total = len(segments)
    failed = sum(1 for segment in segments if segment.status is SegmentStatus.NORMALIZATION_FAILED)
    report = _report_of(ctx, run.id)
    if report is not None:
        totals = json.loads(ctx.artifact_store.read_bytes(report.sha256))["totals"]
        total = int(totals["segments"])
        failed = int(totals["failed"])
    return NormalizationResultSummary(run, total, failed, report, True)


def _report_of(ctx: AppContext, run_id: str) -> Artifact | None:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT:
            return ctx.repo.get_artifact(object_id)
    return None


def _record_denial(ctx: AppContext, source_id: str, decision: PolicyDecision) -> None:
    with ctx.repo.transaction():
        ctx.repo.add_audit_event(
            AuditEvent(
                id=ctx.new_id(IdPrefix.AUDIT),
                event_type=AuditEventType.POLICY_DENIED,
                actor=ctx.actor,
                subject_id=source_id,
                run_id=None,
                details={"operation": Operation.NORMALIZE.value, "decision": decision.value},
                occurred_at=ctx.clock(),
            )
        )
    log_event(
        logger,
        "policy.denied",
        level=logging.WARNING,
        source_id=source_id,
        operation=Operation.NORMALIZE.value,
        decision=decision.value,
    )
