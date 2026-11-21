"""Stage 0: register a source manifest, its policy and its origin objects (no bytes are stored)."""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AuditEventType,
    LineageKind,
    Operation,
    PolicyDecision,
    PolicyMode,
    RunIoRole,
    RunStage,
)
from langpipe.domain.errors import PolicyDenied, SchemaViolation, SourceConflict
from langpipe.domain.hashing import sha256_file
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import AuditEvent, ProcessingRun
from langpipe.domain.models.source import (
    ObjectSpec,
    Source,
    SourceManifest,
    SourceObject,
    SourcePolicy,
)
from langpipe.governance import get_source_policy
from langpipe.governance.policy import resolve
from langpipe.ingestion.runs import RunRecorder
from langpipe.logging import log_event

REGISTER_TOOL = "langpipe.register"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegistrationResult:
    source: Source
    policy: SourcePolicy
    objects: tuple[SourceObject, ...]
    run: ProcessingRun
    reused: bool


@dataclass(frozen=True)
class _Origin:
    spec: ObjectSpec
    path: Path
    sha256: str
    size_bytes: int


def load_manifest(path: Path) -> SourceManifest:
    # Errors are reduced to a fixed code: messages would echo manifest content or paths.
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return SourceManifest.model_validate(data)
    except (OSError, ValueError, yaml.YAMLError, ValidationError):
        raise SchemaViolation() from None


def register_source(ctx: AppContext, manifest_path: Path) -> RegistrationResult:
    manifest = load_manifest(manifest_path)
    manifest_sha256 = manifest.manifest_sha256()

    existing = ctx.repo.find_source_by_key(manifest.key)
    if existing is not None:
        if existing.manifest_sha256 != manifest_sha256:
            raise SourceConflict(manifest.key)
        return _reused(ctx, existing)

    now = ctx.clock()
    policy = _build_policy(ctx, manifest, now)
    # Preflight: no run, row or store write exists yet, so a failure here leaves no trace.
    origins = _preflight(manifest, _manifest_dir(manifest_path), policy)

    recorder = RunRecorder(ctx)
    run = recorder.start(
        RunStage.SOURCE_REGISTRATION,
        REGISTER_TOOL,
        {"manifest_sha256": manifest_sha256},
        input_ids=(),
    )
    try:
        source = Source(
            id=ctx.new_id(IdPrefix.SOURCE),
            key=manifest.key,
            title=manifest.title,
            source_type=manifest.source_type,
            languages=tuple(manifest.languages),
            provenance=manifest.provenance,
            policy_id=policy.id,
            acquired_at=manifest.acquired_at,
            domains=tuple(manifest.domains),
            registers=tuple(manifest.registers),
            manifest_sha256=manifest_sha256,
            registration_run_id=run.id,
            created_at=now,
            updated_at=now,
        )
        objects = tuple(_source_object(ctx, source, run, policy, o, now) for o in origins)
        with ctx.repo.transaction():
            ctx.repo.add_policy(policy)
            ctx.repo.add_source(source)
            for obj in objects:
                ctx.repo.add_source_object(obj)
                ctx.repo.add_lineage_edge(
                    LineageEdge(
                        id=ctx.new_id(IdPrefix.LINEAGE),
                        from_id=obj.id,
                        to_id=source.id,
                        kind=LineageKind.IMPORTED_FROM,
                        run_id=run.id,
                        created_at=ctx.clock(),
                    )
                )
            for node_id in (source.id, *(obj.id for obj in objects)):
                ctx.repo.add_run_io(run.id, node_id, RunIoRole.OUTPUT)
            _audit(ctx, AuditEventType.POLICY_CREATED, policy.id, run.id, {})
            _audit(
                ctx,
                AuditEventType.SOURCE_REGISTERED,
                source.id,
                run.id,
                {"mode": policy.mode.value, "objects": len(objects)},
            )
            succeeded = recorder.succeed(run.id)
    except BaseException as error:
        recorder.fail(run.id, error)
        if isinstance(error, OSError):
            # OS messages and exception chains carry restricted paths: expose a fixed code only.
            raise SchemaViolation() from None
        raise

    log_event(logger, "source.registered", source_id=source.id, run_id=run.id, objects=len(objects))
    return RegistrationResult(
        source=source,
        policy=policy,
        objects=objects,
        run=succeeded,
        reused=False,
    )


def _reused(ctx: AppContext, source: Source) -> RegistrationResult:
    return RegistrationResult(
        source=source,
        policy=get_source_policy(ctx.repo, source),
        objects=tuple(ctx.repo.list_source_objects(source.id)),
        run=ctx.repo.get_run(source.registration_run_id),
        reused=True,
    )


def _build_policy(ctx: AppContext, manifest: SourceManifest, now: datetime) -> SourcePolicy:
    spec = manifest.resolved_policy
    return SourcePolicy(
        id=ctx.new_id(IdPrefix.POLICY),
        mode=spec.mode,
        access_class=spec.access_class,
        authority=spec.authority,
        allow=tuple(spec.allow),
        deny=tuple(spec.deny),
        restrictions=dict(spec.restrictions),
        policy_version=1,
        created_at=now,
    )


def _preflight(manifest: SourceManifest, manifest_dir: Path, policy: SourcePolicy) -> list[_Origin]:
    # `exclude` records metadata only: no origin is resolved, read or hashed.
    if manifest.resolved_policy.mode is PolicyMode.EXCLUDE:
        return []
    decision = resolve(policy, Operation.INGEST)
    if decision is not PolicyDecision.ALLOW:
        # No source exists yet, so the denial is not audited; the manifest key names it.
        raise PolicyDenied(manifest.key, Operation.INGEST, decision)
    return [_origin(spec, manifest_dir) for spec in manifest.objects]


def _manifest_dir(manifest_path: Path) -> Path:
    try:
        return manifest_path.parent.resolve()
    except OSError:
        raise SchemaViolation() from None


def _origin(spec: ObjectSpec, manifest_dir: Path) -> _Origin:
    try:
        path = (manifest_dir / spec.path).resolve()
        if not path.is_relative_to(manifest_dir) or not path.is_file():
            raise SchemaViolation()
        digest, size = sha256_file(path)
    except OSError:
        # Path resolution and stat failures name the restricted file: never render them.
        raise SchemaViolation() from None
    return _Origin(spec=spec, path=path, sha256=digest, size_bytes=size)


def _source_object(
    ctx: AppContext,
    source: Source,
    run: ProcessingRun,
    policy: SourcePolicy,
    origin: _Origin,
    now: datetime,
) -> SourceObject:
    return SourceObject(
        id=ctx.new_id(IdPrefix.SOURCE_OBJECT),
        source_id=source.id,
        original_path=origin.spec.path,
        origin_uri=origin.path.as_uri(),
        sha256=origin.sha256,
        size_bytes=origin.size_bytes,
        media_type=origin.spec.media_type,
        access_class=origin.spec.access_class or policy.access_class,
        registration_run_id=run.id,
        created_at=now,
    )


def _audit(
    ctx: AppContext,
    event_type: AuditEventType,
    subject_id: str,
    run_id: str,
    details: dict[str, str | int | bool],
) -> None:
    ctx.repo.add_audit_event(
        AuditEvent(
            id=ctx.new_id(IdPrefix.AUDIT),
            event_type=event_type,
            actor=ctx.actor,
            subject_id=subject_id,
            run_id=run_id,
            details=details,
            occurred_at=ctx.clock(),
        )
    )
