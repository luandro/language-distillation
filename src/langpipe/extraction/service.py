"""Stage 2: ``ExtractionService`` turns ingested source objects into raw segments (M2 WP2.9).

Pure extractors (WP2.3/WP2.4) never read the origin: only this service reads bytes, and only from
``ctx.raw_store`` after hash verification. Reports carry IDs, counts and allowlisted locators only
(never raw text, file names or TSV cell values); see M2 E10.
"""

import logging
import re
from collections.abc import Mapping
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
    SourceStatus,
    SourceType,
    most_restrictive,
)
from langpipe.domain.errors import (
    ExtractionFailed,
    ObjectMissing,
    PolicyDenied,
    SchemaViolation,
    SourceNotIngested,
    UnsupportedSource,
)
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.domain.models.source import Source, SourceObject
from langpipe.extraction.base import ExtractionContext, ExtractionOutput
from langpipe.extraction.registry import EXTRACTORS, default_extractor_for
from langpipe.governance import effective_policy
from langpipe.governance.policy import resolve
from langpipe.ingestion.ingest import resolve_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.logging import log_event
from langpipe.segmentation.recorder import ObservationRecorder, SegmentInput
from langpipe.text.registry import versioned_name

EXTRACT_TOOL = "langpipe.extract"
REPORT_SCHEMA = "extraction-report"
REPORT_SCHEMA_VERSION = 1
ERROR_SCHEMA = "extraction-error"
ERROR_SCHEMA_VERSION = 1
LOG_COUNT_FIELD = "count"
logger = logging.getLogger(__name__)

# Report locator allowlist. Text-bearing keys (ref, note_ref, caller, para, published_*) are never
# copied into a report; they stay on the governed Segment rows (M2 E10).
_INT_LOCATOR_KEYS = ("chapter", "para_index", "part", "note_index", "line", "row", "column_index")
_TEXT_LOCATOR_KEYS = ("book", "verse", "unit", "marker")
_UNIT_VALUES = frozenset({"verse", "heading", "footnote", "introduction", "unknown"})
_BOOK = re.compile(r"[A-Z0-9]{3}")
_MARKER = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_VERSE = re.compile(r"[0-9]+[a-z]?(?:-[0-9]+[a-z]?)?")


@dataclass(frozen=True)
class ExtractionResult:
    source: Source
    run: ProcessingRun
    segments: int
    skipped_objects: tuple[str, ...]
    report: Artifact | None
    reused: bool


def extract_source(
    ctx: AppContext,
    source_ref: str,
    *,
    extractor: str | None = None,
    language: str | None = None,
) -> ExtractionResult:
    source = resolve_source(ctx, source_ref)

    # Gate first under source row lock: a denial (or a revoked source) writes one audit
    # event and no run, no rows.
    try:
        with ctx.repo.transaction():
            ctx.repo.lock_sources([source.id])
            policy = effective_policy(ctx.repo, source)
            decision = resolve(policy, Operation.EXTRACT)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                raise PolicyDenied(source.id, Operation.EXTRACT, decision)
    except PolicyDenied as exc:
        _record_denial(ctx, source, exc.decision)
        raise

    if source.status is not SourceStatus.INGESTED:
        raise SourceNotIngested(source.id)

    # An explicit override that is not a source language is invalid before any run starts.
    if language is not None and language not in source.languages:
        raise SchemaViolation()

    objects = ctx.repo.list_source_objects(source.id)
    planned, skipped = _plan(source, objects, extractor)
    if not planned:
        raise UnsupportedSource("no_extractor")

    input_ids = [obj.id for obj, _ in planned]
    config: dict[str, JsonValue] = {
        "extractors": {obj.id: name for obj, name in planned},
        "language": language,
    }
    access_class = most_restrictive(obj.access_class for obj in objects)

    recorder = RunRecorder(ctx)
    reusable = recorder.find_reusable(RunStage.EXTRACTION, EXTRACT_TOOL, config, input_ids)
    if reusable is not None:
        try:
            with ctx.repo.transaction():
                ctx.repo.lock_sources([source.id])
                current_source = ctx.repo.get_source(source.id)
                policy = effective_policy(ctx.repo, current_source)
                decision = resolve(policy, Operation.EXTRACT)
                if (
                    current_source.status is SourceStatus.REVOKED
                    or decision is not PolicyDecision.ALLOW
                ):
                    raise PolicyDenied(source.id, Operation.EXTRACT, decision)
                return ExtractionResult(
                    source=current_source,
                    run=reusable,
                    segments=len(ctx.repo.list_segments_for_run(reusable.id)),
                    skipped_objects=tuple(obj.id for obj, _ in skipped),
                    report=_report_of(ctx, reusable.id),
                    reused=True,
                )
        except PolicyDenied as error:
            _record_denial(ctx, source, error.decision)
            raise

    run = recorder.start(RunStage.EXTRACTION, EXTRACT_TOOL, config, input_ids)
    observer = ObservationRecorder(ctx.repo, ctx.clock, ctx.new_id)
    try:
        with observer.unit_of_work():
            ctx.repo.lock_sources([source.id])
            current_source = ctx.repo.get_source(source.id)
            policy = effective_policy(ctx.repo, current_source)
            decision = resolve(policy, Operation.EXTRACT)
            if (
                current_source.status is SourceStatus.REVOKED
                or decision is not PolicyDecision.ALLOW
            ):
                raise PolicyDenied(source.id, Operation.EXTRACT, decision)

            outputs = _run_extractors(ctx, current_source, planned, language)
            stored = ctx.artifact_store.put_bytes(
                canonical_json(_report_payload(source, run, outputs, skipped)).encode("utf-8")
            )
            report_artifact = Artifact(
                id=ctx.new_id(IdPrefix.ARTIFACT),
                run_id=run.id,
                kind=ArtifactKind.EXTRACTION_REPORT,
                media_type="application/json",
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                access_class=access_class,
                schema_name=REPORT_SCHEMA,
                schema_version=REPORT_SCHEMA_VERSION,
                created_at=ctx.clock(),
            )
            segments = 0
            for obj, _name, output in outputs:
                built = observer.record_segments(
                    run_id=run.id,
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
                segments += len(built)
            ctx.repo.add_artifact(report_artifact)
            ctx.repo.add_run_io(run.id, report_artifact.id, RunIoRole.OUTPUT)
            for obj, _name in planned:
                ctx.repo.add_lineage_edge(
                    LineageEdge(
                        id=ctx.new_id(IdPrefix.LINEAGE),
                        from_id=report_artifact.id,
                        to_id=obj.id,
                        kind=LineageKind.DERIVED_FROM,
                        run_id=run.id,
                        created_at=ctx.clock(),
                    )
                )
            succeeded = recorder.succeed(run.id)
    except ExtractionFailed as error:
        try:
            _fail_with_error_artifact(ctx, run, error, access_class)
        except BaseException as record_error:
            # Recording the error artifact failed: still mark the run failed, then re-raise.
            recorder.fail(run.id, record_error)
        raise
    except BaseException as error:
        if isinstance(error, PolicyDenied):
            _record_denial(ctx, source, error.decision)
        recorder.fail(run.id, error)
        if isinstance(error, OSError):
            # OS messages and exception chains carry restricted paths: expose a fixed code only.
            raise SchemaViolation() from None
        raise

    log_event(
        logger,
        "extraction.succeeded",
        source_id=source.id,
        run_id=run.id,
        **{LOG_COUNT_FIELD: segments},
    )
    return ExtractionResult(
        source=source,
        run=succeeded,
        segments=segments,
        skipped_objects=tuple(obj.id for obj, _ in skipped),
        report=report_artifact,
        reused=False,
    )


def _plan(
    source: Source, objects: list[SourceObject], override: str | None
) -> tuple[list[tuple[SourceObject, str]], list[tuple[SourceObject, str]]]:
    planned: list[tuple[SourceObject, str]] = []
    skipped: list[tuple[SourceObject, str]] = []
    for obj in objects:
        if source.source_type is SourceType.IGT:
            # No M2 extractor exists for IGT and an override does not lift that (§4.3).
            skipped.append((obj, "igt_not_in_m2"))
            continue
        ref = (
            override
            if override is not None
            else default_extractor_for(source.source_type, obj.media_type)
        )
        if ref is None:
            skipped.append((obj, "no_extractor"))
            continue
        planned.append((obj, versioned_name(EXTRACTORS.get(ref))))
    return planned, skipped


def _run_extractors(
    ctx: AppContext,
    source: Source,
    planned: list[tuple[SourceObject, str]],
    language: str | None,
) -> list[tuple[SourceObject, str, ExtractionOutput]]:
    outputs: list[tuple[SourceObject, str, ExtractionOutput]] = []
    for obj, name in planned:
        extractor = EXTRACTORS.get(name)
        if ctx.repo.get_raw_blob(obj.sha256) is None:
            raise ObjectMissing(obj.sha256)
        ctx.raw_store.verify(obj.sha256)
        data = ctx.raw_store.read_bytes(obj.sha256)
        extract_ctx = ExtractionContext(
            source_id=source.id,
            source_object_id=obj.id,
            source_type=source.source_type,
            media_type=obj.media_type,
            source_languages=source.languages,
            language=language,
        )
        output = extractor.extract(data, extract_ctx)
        for unit in output.units:
            if unit.language not in source.languages:
                raise SchemaViolation()
        outputs.append((obj, name, output))
    return outputs


def _report_payload(
    source: Source,
    run: ProcessingRun,
    outputs: list[tuple[SourceObject, str, ExtractionOutput]],
    skipped: list[tuple[SourceObject, str]],
) -> dict[str, object]:
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "source_id": source.id,
        "run_id": run.id,
        "objects": [
            {
                "source_object_id": obj.id,
                "extractor": name,
                "units": len(output.units),
                "stats": dict(output.stats),
                "empty_units": [_project_locator(locator) for locator in output.empty_units],
            }
            for obj, name, output in outputs
        ],
        "skipped": [{"source_object_id": obj.id, "reason": reason} for obj, reason in skipped],
    }


def _project_locator(locator: Mapping[str, str | int]) -> dict[str, str | int]:
    """Keep only allowlisted locator keys whose values pass the value grammar."""
    projected: dict[str, str | int] = {}
    for key in _INT_LOCATOR_KEYS:
        value = locator.get(key)
        if type(value) is int and value >= 0:
            projected[key] = value
    for key in _TEXT_LOCATOR_KEYS:
        value = locator.get(key)
        if not isinstance(value, str):
            continue
        if key == "unit":
            if value in _UNIT_VALUES:
                projected[key] = value
        elif key == "book":
            if _BOOK.fullmatch(value):
                projected[key] = value
        elif key == "marker":
            if _MARKER.fullmatch(value):
                projected[key] = value
        elif value == "" or _VERSE.fullmatch(value):
            projected[key] = value
    return projected


def _fail_with_error_artifact(
    ctx: AppContext, run: ProcessingRun, error: ExtractionFailed, access_class: AccessClass
) -> None:
    stored = ctx.artifact_store.put_bytes(
        canonical_json(
            {
                "schema": ERROR_SCHEMA,
                "schema_version": ERROR_SCHEMA_VERSION,
                "source_object_id": error.source_object_id,
                "code": error.code,
                "line": error.line,
            }
        ).encode("utf-8")
    )
    artifact = Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.EXTRACTION_ERROR,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=access_class,
        schema_name=ERROR_SCHEMA,
        schema_version=ERROR_SCHEMA_VERSION,
        created_at=ctx.clock(),
    )
    RunRecorder(ctx).fail(
        run.id, error, artifact=artifact, artifact_inputs=[error.source_object_id]
    )


def _report_of(ctx: AppContext, run_id: str) -> Artifact | None:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT:
            return ctx.repo.get_artifact(object_id)
    return None


def _record_denial(ctx: AppContext, source: Source, decision: PolicyDecision) -> None:
    with ctx.repo.transaction():
        ctx.repo.add_audit_event(
            AuditEvent(
                id=ctx.new_id(IdPrefix.AUDIT),
                event_type=AuditEventType.POLICY_DENIED,
                actor=ctx.actor,
                subject_id=source.id,
                run_id=None,
                details={"operation": Operation.EXTRACT.value, "decision": decision.value},
                occurred_at=ctx.clock(),
            )
        )
    log_event(
        logger,
        "policy.denied",
        level=logging.WARNING,
        source_id=source.id,
        operation=Operation.EXTRACT.value,
        decision=decision.value,
    )
