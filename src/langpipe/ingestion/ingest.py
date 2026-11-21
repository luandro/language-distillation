"""Stage 1: copy registered origin bytes into the raw store and record an ingest report."""

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    ArtifactKind,
    AuditEventType,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    SourceStatus,
    most_restrictive,
)
from langpipe.domain.errors import NotFound, PolicyDenied, SchemaViolation, SourceChanged
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix, is_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.domain.models.source import RawBlob, Source, SourceObject
from langpipe.governance import effective_policy
from langpipe.governance.policy import resolve
from langpipe.ingestion.runs import RunRecorder
from langpipe.logging import log_event
from langpipe.storage.objects.base import StoredObject

INGEST_TOOL = "langpipe.ingest"
REPORT_SCHEMA = "ingest-report"
REPORT_SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    source: Source
    run: ProcessingRun
    blobs: tuple[RawBlob, ...]
    report: Artifact | None
    reused: bool


def resolve_source(ctx: AppContext, source_ref: str) -> Source:
    """Accept a source id or a source key. Raises NotFound for an unknown source."""
    if is_id(source_ref, IdPrefix.SOURCE):
        return ctx.repo.get_source(source_ref)
    source = ctx.repo.find_source_by_key(source_ref)
    if source is None:
        raise NotFound(EntityType.SOURCE.value, source_ref)
    return source


def ingest_source(ctx: AppContext, source_ref: str) -> IngestResult:
    source = resolve_source(ctx, source_ref)
    policy = effective_policy(ctx.repo, source)

    # Policy gate first: a denial writes no run, no store object and no semantic row.
    decision = resolve(policy, Operation.INGEST)
    if decision is not PolicyDecision.ALLOW:
        _record_denial(ctx, source, decision)
        raise PolicyDenied(source.id, Operation.INGEST, decision)

    objects = ctx.repo.list_source_objects(source.id)
    input_ids = [obj.id for obj in objects]
    recorder = RunRecorder(ctx)
    reusable = recorder.find_reusable(RunStage.RAW_INGESTION, INGEST_TOOL, {}, input_ids)
    if reusable is not None:
        return IngestResult(
            source=source,
            run=reusable,
            blobs=_blobs_for(ctx, objects),
            report=_report_of(ctx, reusable.id),
            reused=True,
        )

    run = recorder.start(RunStage.RAW_INGESTION, INGEST_TOOL, {}, input_ids)
    try:
        stored = _store_origins(ctx, objects)
        report = _write_report(ctx, source, run, objects)
        with ctx.repo.transaction():
            blobs = tuple(
                ctx.repo.add_raw_blob(
                    RawBlob(
                        sha256=item.sha256,
                        size_bytes=item.size_bytes,
                        storage_backend="local",
                        stored_at=ctx.clock(),
                        ingestion_run_id=run.id,
                    )
                )
                for item in stored
            )
            artifact = Artifact(
                id=ctx.new_id(IdPrefix.ARTIFACT),
                run_id=run.id,
                kind=ArtifactKind.INGEST_REPORT,
                media_type="application/json",
                sha256=report.sha256,
                size_bytes=report.size_bytes,
                access_class=most_restrictive(obj.access_class for obj in objects),
                schema_name=REPORT_SCHEMA,
                schema_version=REPORT_SCHEMA_VERSION,
                created_at=ctx.clock(),
            )
            ctx.repo.add_artifact(artifact)
            for obj in objects:
                ctx.repo.add_run_io(run.id, obj.id, RunIoRole.INPUT)
                ctx.repo.add_lineage_edge(
                    LineageEdge(
                        id=ctx.new_id(IdPrefix.LINEAGE),
                        from_id=artifact.id,
                        to_id=obj.id,
                        kind=LineageKind.DERIVED_FROM,
                        run_id=run.id,
                        created_at=ctx.clock(),
                    )
                )
            ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
            updated = ctx.repo.set_source_status(source.id, SourceStatus.INGESTED, ctx.clock())
            ctx.repo.add_audit_event(
                AuditEvent(
                    id=ctx.new_id(IdPrefix.AUDIT),
                    event_type=AuditEventType.RAW_INGESTED,
                    actor=ctx.actor,
                    subject_id=source.id,
                    run_id=run.id,
                    details={},
                    occurred_at=ctx.clock(),
                )
            )
            succeeded = recorder.succeed(run.id)
    except BaseException as error:
        # Orphan bytes in the store are accepted (ADR-0008); no semantic rows survive.
        recorder.fail(run.id, error)
        if isinstance(error, OSError):
            # OS messages and exception chains carry restricted paths: expose a fixed code only.
            raise SchemaViolation() from None
        raise

    log_event(logger, "source.ingested", source_id=source.id, run_id=run.id, objects=len(objects))
    return IngestResult(
        source=updated,
        run=succeeded,
        blobs=blobs,
        report=artifact,
        reused=False,
    )


def _store_origins(ctx: AppContext, objects: list[SourceObject]) -> list[StoredObject]:
    stored: list[StoredObject] = []
    for obj in objects:
        item = ctx.raw_store.put_file(_origin_path(obj.origin_uri))
        if item.sha256 != obj.sha256:
            raise SourceChanged(obj.sha256, item.sha256)
        ctx.raw_store.verify(item.sha256)
        stored.append(item)
    return stored


def _write_report(
    ctx: AppContext, source: Source, run: ProcessingRun, objects: list[SourceObject]
) -> StoredObject:
    # IDs, hashes and sizes only: the report must never carry raw text, titles or file names.
    payload = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "source_id": source.id,
        "run_id": run.id,
        "objects": [
            {
                "source_object_id": obj.id,
                "sha256": obj.sha256,
                "size_bytes": obj.size_bytes,
            }
            for obj in objects
        ],
    }
    return ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))


def _blobs_for(ctx: AppContext, objects: list[SourceObject]) -> tuple[RawBlob, ...]:
    blobs: list[RawBlob] = []
    for obj in objects:
        blob = ctx.repo.get_raw_blob(obj.sha256)
        if blob is None:
            raise NotFound("raw_blob", obj.sha256)
        blobs.append(blob)
    return tuple(blobs)


def _report_of(ctx: AppContext, run_id: str) -> Artifact | None:
    outputs = [
        object_id for object_id, role in ctx.repo.list_run_io(run_id) if role is RunIoRole.OUTPUT
    ]
    return ctx.repo.get_artifact(outputs[0]) if outputs else None


def _origin_path(origin_uri: str) -> Path:
    return Path(unquote(urlsplit(origin_uri).path))


def _record_denial(ctx: AppContext, source: Source, decision: PolicyDecision) -> None:
    with ctx.repo.transaction():
        ctx.repo.add_audit_event(
            AuditEvent(
                id=ctx.new_id(IdPrefix.AUDIT),
                event_type=AuditEventType.POLICY_DENIED,
                actor=ctx.actor,
                subject_id=source.id,
                run_id=None,
                details={"operation": Operation.INGEST.value, "decision": decision.value},
                occurred_at=ctx.clock(),
            )
        )
    log_event(
        logger,
        "policy.denied",
        level=logging.WARNING,
        source_id=source.id,
        operation=Operation.INGEST.value,
        decision=decision.value,
    )
