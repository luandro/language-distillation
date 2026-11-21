"""Stage 7a: ``IgtExtractService`` turns IGT source objects into observations (M5 WP5.7).

Interlinear glossed text is imported as *observation*, never as analysis (ADR-0017 §1,
invariant 2): every record becomes one `IGTObservation` carrying the source's verbatim
tiers, and — when the record has a text tier — one raw `Segment` the M2 normalize and
tokenize stages consume unchanged. One run (``RunStage.EXTRACTION``, tool
``langpipe.igt-extract``) covers the whole import, so `langpipe normalize` and
`langpipe tokenize` accept it exactly like a Stage 2 run (M5-PLAN §7.6, G5).

Readers are pure (WP5.6): this service is the only place that reads raw bytes, and only
from ``ctx.raw_store`` after verification. The report carries ids and counts only — no
tier content, translation or word text (M2 E10).
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import JsonValue

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    AuditEventType,
    EntityType,
    IgtFormat,
    IgtParseStatus,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    most_restrictive,
)
from langpipe.domain.errors import (
    ObjectMissing,
    PolicyDenied,
    SchemaViolation,
    SourceNotIngested,
    UnsupportedSource,
)
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.igt import IGTObservation
from langpipe.domain.models.observation import Segment
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.domain.models.source import Source, SourceObject
from langpipe.extraction.base import ExtractionContext
from langpipe.governance import effective_policy
from langpipe.governance.policy import resolve
from langpipe.igt.base import IgtDocument
from langpipe.igt.registry import IGT_READERS, reader_for_media_type
from langpipe.igt.toolbox import SAFE_TOOLBOX_MARKERS
from langpipe.ingestion.ingest import resolve_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.languages.base import MorphologyProfile, profile_for, profile_identity
from langpipe.logging import log_event
from langpipe.text.registry import versioned_name

IGT_EXTRACT_TOOL = "langpipe.igt-extract"
REPORT_SCHEMA = "igt-extraction-report"
REPORT_SCHEMA_VERSION = 1
MIXED_READER = "mixed"
LOG_COUNT_FIELD = "count"
UNKNOWN_MARKER_PREFIX = "unknown_marker:"
_MARKER_LINE = re.compile(r"^\\(\S+)(?:[ \t](.*))?$")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IgtExtractResult:
    """One Stage 7a import: its run, its counts and (when stored) its report."""

    source: Source
    run: ProcessingRun
    records: int
    segments: int
    words: int
    morphs: int
    skipped_objects: tuple[str, ...]
    report: Artifact | None
    reused: bool


@dataclass(frozen=True)
class _Planned:
    """One source object paired with the canonical reader reference that will read it."""

    obj: SourceObject
    reader: str


@dataclass
class _Counts:
    """Accumulators for the report and the result; counters only, never content."""

    records: int = 0
    segments: int = 0
    words: int = 0
    morphs: int = 0
    parse_status_counts: dict[str, int] | None = None
    unknown_marker_counts: dict[str, int] | None = None

    def __post_init__(self) -> None:
        self.parse_status_counts = {status.value: 0 for status in IgtParseStatus}
        self.unknown_marker_counts = {}


class IgtExtractService:
    """Orchestrates Stage 7a: governed raw bytes -> observations + text-tier segments."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def extract(
        self,
        source_ref: str,
        *,
        reader: str | None = None,
        language: str | None = None,
        contact_language: str | None = None,
        profile: str | MorphologyProfile | None = None,
    ) -> IgtExtractResult:
        """Import every record of one ingested IGT source as an observation."""
        ctx = self.ctx
        source = resolve_source(ctx, source_ref)

        # Gate first under the source row lock: a denial writes one audit event and no run.
        source = _gate(ctx, source.id)
        if source.status is not SourceStatus.INGESTED:
            raise SourceNotIngested(source.id)

        target_language = _target_language(source, language)
        profile_ref = profile_identity(profile, target_language)
        if isinstance(profile, MorphologyProfile):
            profile_obj = profile
        elif isinstance(profile, str):
            profile_obj = profile_for(profile).morphology
        else:
            profile_obj = profile_for(target_language).morphology

        objects = ctx.repo.list_source_objects(source.id)
        planned = _plan(objects, reader)
        input_ids = [item.obj.id for item in planned]
        config: dict[str, JsonValue] = {
            "readers": {item.obj.id: item.reader for item in planned},
            "language": target_language,
            "contact_language": contact_language,
            "profile": profile_ref,
        }
        access_class = most_restrictive(obj.access_class for obj in objects)

        recorder = RunRecorder(ctx)
        reusable = recorder.find_reusable(RunStage.EXTRACTION, IGT_EXTRACT_TOOL, config, input_ids)
        if reusable is not None:
            return _reused_result(ctx, source.id, reusable)

        run = recorder.start(RunStage.EXTRACTION, IGT_EXTRACT_TOOL, config, input_ids)
        run_committed = False
        try:
            with ctx.repo.transaction():
                ctx.repo.lock_sources([source.id])
                current = ctx.repo.get_source(source.id)
                if current.status is not SourceStatus.INGESTED:
                    raise SourceNotIngested(current.id)
                _require_policy(ctx, current)
                counts = _import_records(ctx, current, run, planned, target_language, profile_obj)
                report = _store_report(
                    ctx, current, run, planned, counts, access_class, input_ids=input_ids
                )
                run = recorder.succeed(run.id)
                result = IgtExtractResult(
                    source=current,
                    run=run,
                    records=counts.records,
                    segments=counts.segments,
                    words=counts.words,
                    morphs=counts.morphs,
                    skipped_objects=(),
                    report=report,
                    reused=False,
                )
            run_committed = True

            log_event(
                logger,
                "igt_extraction.succeeded",
                source_id=source.id,
                run_id=run.id,
                **{LOG_COUNT_FIELD: counts.records},
            )
            return result
        except BaseException as error:
            if isinstance(error, PolicyDenied):
                _record_denial(ctx, source.id, error.decision)
            if not run_committed:
                try:
                    persisted = ctx.repo.get_run(run.id)
                    if persisted.status is RunStatus.RUNNING:
                        recorder.fail(run.id, error)
                except Exception:
                    pass
            if isinstance(error, OSError):
                # OS messages and exception chains carry restricted paths: fixed code only.
                raise SchemaViolation() from None
            raise


def extract_igt(
    ctx: AppContext,
    source_ref: str,
    *,
    reader: str | None = None,
    language: str | None = None,
    contact_language: str | None = None,
    profile: str | MorphologyProfile | None = None,
) -> IgtExtractResult:
    """Convenience wrapper around `IgtExtractService.extract` (CLI and test entry point)."""
    return IgtExtractService(ctx).extract(
        source_ref,
        reader=reader,
        language=language,
        contact_language=contact_language,
        profile=profile,
    )


def _target_language(source: Source, override: str | None) -> str:
    """Resolve the segment language: the explicit override or the source's first language."""
    if override is not None and override not in source.languages:
        raise SchemaViolation()
    language = (
        override if override is not None else (source.languages[0] if source.languages else None)
    )
    if language is None:
        # No language can label the text tier; refused before any run starts.
        raise SchemaViolation()
    return language


def _plan(objects: Sequence[SourceObject], override: str | None) -> list[_Planned]:
    """Pair each object with a registered reader; an unreadable object fails the import."""
    planned: list[_Planned] = []
    for obj in objects:
        name = override if override is not None else reader_for_media_type(obj.media_type)
        if name is None:
            raise UnsupportedSource("no_extractor")
        planned.append(_Planned(obj, versioned_name(IGT_READERS.get(name))))
    if not planned:
        raise UnsupportedSource("no_extractor")
    return planned


def _gate(ctx: AppContext, source_id: str) -> Source:
    """Lock and re-read one source, refusing unless `EXTRACT` and `READ_RAW` both allow.

    A denial records one `POLICY_DENIED` audit event (after the gate transaction rolls
    back) and re-raises. A revoked source is a deny regardless of the policy lists,
    so it is reported as `deny` rather than as the baseline's resolved decision.
    """
    try:
        with ctx.repo.transaction():
            ctx.repo.lock_sources([source_id])
            source = ctx.repo.get_source(source_id)
            _require_policy(ctx, source)
            return source
    except PolicyDenied as error:
        _record_denial(ctx, source_id, error.decision)
        raise


def _require_policy(ctx: AppContext, source: Source) -> None:
    """Raise `PolicyDenied` unless both stage-7a operations are allowed for `source`."""
    if source.status is SourceStatus.REVOKED:
        raise PolicyDenied(source.id, Operation.EXTRACT, PolicyDecision.DENY)
    policy = effective_policy(ctx.repo, source)
    decision = resolve(policy, Operation.EXTRACT)
    read_decision = resolve(policy, Operation.READ_RAW)
    if decision is not PolicyDecision.ALLOW:
        raise PolicyDenied(source.id, Operation.EXTRACT, decision)
    if read_decision is not PolicyDecision.ALLOW:
        raise PolicyDenied(source.id, Operation.EXTRACT, read_decision)


def _reused_result(ctx: AppContext, source_id: str, run: ProcessingRun) -> IgtExtractResult:
    """Re-check governance under lock, then report the counts the stored run already has."""
    try:
        with ctx.repo.transaction():
            ctx.repo.lock_sources([source_id])
            current = ctx.repo.get_source(source_id)
            _require_policy(ctx, current)
            observations = ctx.repo.list_igt_observations_for_run(run.id)
            segments = ctx.repo.list_segments_for_run(run.id)
    except PolicyDenied as error:
        _record_denial(ctx, source_id, error.decision)
        raise
    return IgtExtractResult(
        source=current,
        run=run,
        records=len(observations),
        segments=len(segments),
        words=_word_count(observations),
        morphs=_morph_count(observations),
        skipped_objects=(),
        report=_report_of(ctx, run.id),
        reused=True,
    )


def _import_records(
    ctx: AppContext,
    source: Source,
    run: ProcessingRun,
    planned: Sequence[_Planned],
    language: str,
    profile: MorphologyProfile | None = None,
) -> _Counts:
    """Read every planned object and persist one observation (and text-tier segment) per record."""
    counts = _Counts()
    for item in planned:
        document = _read_document(ctx, source, item, language, profile)
        ctx.repo.add_run_io(run.id, item.obj.id, RunIoRole.INPUT)
        _count_document(document, counts)
        for record in document.records:
            segment_id: str | None = None
            if record.words:
                segment_id = _record_segment(ctx, source, run, item.obj, record, language, profile)
                counts.segments += 1
            observation = IGTObservation(
                id=ctx.new_id(IdPrefix.IGT_OBSERVATION),
                source_id=source.id,
                source_object_id=item.obj.id,
                run_id=run.id,
                segment_id=segment_id,
                record_ordinal=record.record_ordinal,
                record_ref=record.record_ref,
                format=record.format,
                locator=dict(record.locator),
                tiers=record.tiers,
                words=record.words,
                translations=record.translations,
                parse_status=record.parse_status,
                diagnostics=record.diagnostics,
                created_at=ctx.clock(),
            )
            ctx.repo.add_igt_observation(observation)
            ctx.repo.add_run_io(run.id, observation.id, RunIoRole.OUTPUT)
            _link_extracted(ctx, run, observation.id, item.obj.id)
    return counts


def _read_document(
    ctx: AppContext,
    source: Source,
    item: _Planned,
    language: str,
    profile: MorphologyProfile | None = None,
) -> IgtDocument:
    """Verify and read one object's bytes, then hand them to its pure reader."""
    obj = item.obj
    if ctx.repo.get_raw_blob(obj.sha256) is None:
        raise ObjectMissing(obj.sha256)
    ctx.raw_store.verify(obj.sha256)
    data = ctx.raw_store.read_bytes(obj.sha256)
    reader = IGT_READERS.get(item.reader)
    read_ctx = ExtractionContext(
        source_id=source.id,
        source_object_id=obj.id,
        source_type=source.source_type,
        media_type=obj.media_type,
        source_languages=source.languages,
        language=language,
    )
    return reader.read(data, ctx=read_ctx, profile=profile)


def _extract_text_tier(record: Any, profile: MorphologyProfile | None = None) -> str:
    """Extract raw text of the text tier from record.tiers, falling back to word text."""
    profile = profile or MorphologyProfile()
    text_markers = set(profile.toolbox_markers.get("text", ("\\t", "\\tx")))

    text_parts: list[str] = []
    in_text_tier = False

    for tier in record.tiers:
        if record.format is IgtFormat.TOOLBOX:
            if tier.marker in text_markers:
                in_text_tier = True
                match = _MARKER_LINE.match(tier.raw)
                content = match[2] if match and match[2] is not None else ""
                text_parts.append(content)
            elif tier.marker == "" and in_text_tier:
                text_parts.append(tier.raw)
            elif tier.marker:
                in_text_tier = False
        elif (
            record.format is IgtFormat.XIGT
            and tier.marker in ("xigt:phrases", "xigt:phrase")
            and tier.raw
        ):
            text_parts.append(tier.raw)

    if text_parts:
        return "\n".join(text_parts)
    return " ".join(word.text for word in record.words)


def _record_segment(
    ctx: AppContext,
    source: Source,
    run: ProcessingRun,
    obj: SourceObject,
    record: object,
    language: str,
    profile: MorphologyProfile | None = None,
) -> str:
    """Persist the raw text-tier segment one observation points at."""
    from langpipe.igt.base import IgtRecord  # local import keeps the module header readable

    assert isinstance(record, IgtRecord)  # noqa: S101 - narrowed by the caller's loop
    locator: dict[str, str | int] = {"record_ordinal": record.record_ordinal}
    if record.record_ref is not None:
        locator["igt_ref"] = record.record_ref
    for key in ("line_start", "line_end"):
        value = record.locator.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            locator[key] = value
    segment = Segment(
        id=ctx.new_id(IdPrefix.SEGMENT),
        source_id=source.id,
        source_object_id=obj.id,
        run_id=run.id,
        ordinal=record.record_ordinal,
        language=language,
        locator=locator,
        raw_text=_extract_text_tier(record, profile),
        created_at=ctx.clock(),
    )
    ctx.repo.add_segment(segment)
    ctx.repo.add_run_io(run.id, segment.id, RunIoRole.OUTPUT)
    _link_extracted(ctx, run, segment.id, obj.id)
    return str(segment.id)


def _link_extracted(ctx: AppContext, run: ProcessingRun, from_id: str, to_id: str) -> None:
    """One `extracted_from` edge per derived row, addressed to its source object."""
    ctx.repo.add_lineage_edge(
        LineageEdge(
            id=ctx.new_id(IdPrefix.LINEAGE),
            from_id=from_id,
            to_id=to_id,
            kind=LineageKind.EXTRACTED_FROM,
            run_id=run.id,
            created_at=ctx.clock(),
        )
    )


def _count_document(document: IgtDocument, counts: _Counts) -> None:
    """Accumulate counters only: record, parse-status, word, morph and unknown-marker counts."""
    counts.records += len(document.records)
    for record in document.records:
        counts.words += len(record.words)
        counts.morphs += sum(len(word.morphs) for word in record.words)
        if counts.parse_status_counts is not None:
            counts.parse_status_counts[record.parse_status.value] += 1
    for key, value in document.stats.items():
        if key.startswith(UNKNOWN_MARKER_PREFIX) and counts.unknown_marker_counts is not None:
            tag = key.removeprefix(UNKNOWN_MARKER_PREFIX)
            k = key if tag in SAFE_TOOLBOX_MARKERS else f"{UNKNOWN_MARKER_PREFIX}UNKNOWN"
            counts.unknown_marker_counts[k] = counts.unknown_marker_counts.get(k, 0) + value


def _word_count(observations: Sequence[IGTObservation]) -> int:
    return sum(len(obs.words) for obs in observations)


def _morph_count(observations: Sequence[IGTObservation]) -> int:
    return sum(len(word.morphs) for obs in observations for word in obs.words)


def _report_of(ctx: AppContext, run_id: str) -> Artifact | None:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT:
            return ctx.repo.get_artifact(object_id)
    return None


def _store_report(
    ctx: AppContext,
    source: Source,
    run: ProcessingRun,
    planned: Sequence[_Planned],
    counts: _Counts,
    access_class: AccessClass,
    *,
    input_ids: Sequence[str],
) -> Artifact:
    payload = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run.id,
        "source_id": source.id,
        "readers": [item.reader for item in planned],
        "source_object_ids": list(input_ids),
        "records": counts.records,
        "parse_status_counts": counts.parse_status_counts,
        "segments": counts.segments,
        "words": counts.words,
        "morphs": counts.morphs,
        "unknown_marker_counts": counts.unknown_marker_counts,
    }
    stored = ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
    artifact = Artifact(
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
    ctx.repo.add_artifact(artifact)
    ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
    for obj_id in input_ids:
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=artifact.id,
                to_id=obj_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )
    return artifact


def _record_denial(ctx: AppContext, source_id: str, decision: PolicyDecision) -> None:
    with ctx.repo.transaction():
        ctx.repo.add_audit_event(
            AuditEvent(
                id=ctx.new_id(IdPrefix.AUDIT),
                event_type=AuditEventType.POLICY_DENIED,
                actor=ctx.actor,
                subject_id=source_id,
                run_id=None,
                details={"operation": Operation.EXTRACT.value, "decision": decision.value},
                occurred_at=ctx.clock(),
            )
        )
    log_event(
        logger,
        "policy.denied",
        level=logging.WARNING,
        source_id=source_id,
        operation=Operation.EXTRACT.value,
        decision=decision.value,
    )
