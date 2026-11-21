"""Explicit M2 run selection for alignment sides (M3-PLAN WP3.5, ADR-0011 §4).

One side pins one succeeded normalization run — and, for Stage 5, one succeeded
tokenization run that consumes it. Defaults are unique-only: zero applicable runs are
an input error and multiple runs raise ``AmbiguousInput``; there is no "latest"
selection and no mixture of generations. Resolution walks the existing run I/O graph
only (source -> extraction runs -> raw segments -> normalization runs -> tokenization
runs); no implicit list-all interface is added.
"""

from langpipe.alignment.base import AlignmentSide
from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType, RunIoRole, RunStage, RunStatus
from langpipe.domain.errors import AmbiguousInput, InvalidLineage, NotFound, SchemaViolation
from langpipe.domain.models.observation import Segment
from langpipe.domain.models.run import ProcessingRun
from langpipe.domain.models.source import Source
from langpipe.ingestion.ingest import resolve_source
from langpipe.storage.repository import Repository


def resolve_alignment_side(
    ctx: AppContext,
    source_ref: str,
    language: str | None,
    normalization_run_id: str | None,
    tokenization_run_id: str | None,
) -> AlignmentSide:
    """Resolve one alignment side: source, explicit language and pinned runs.

    ``normalization_run_id``/``tokenization_run_id`` are explicit pins; an omitted
    normalization pin falls back to the unique applicable run. ``tokenization_run_id``
    left as ``None`` yields a Stage 4 side (no token pin): Stage 5 callers pass one.
    """
    repo = ctx.repo
    source = resolve_source(ctx, source_ref)
    side_language = _resolve_language(source, language)

    if normalization_run_id is not None:
        normalization = _succeeded_run(repo, normalization_run_id, RunStage.NORMALIZATION)
        _require_side_segment(repo, normalization, source.id, side_language)
    else:
        normalization = _unique_normalization(repo, source.id, side_language)

    tokenization_id: str | None = None
    if tokenization_run_id is not None:
        tokenization = _succeeded_run(repo, tokenization_run_id, RunStage.TOKENIZATION)
        _require_consumed_normalization(repo, tokenization, normalization.id)
        tokenization_id = tokenization.id

    return AlignmentSide(
        source_id=source.id,
        language=side_language,
        normalization_run_id=normalization.id,
        tokenization_run_id=tokenization_id,
    )


def _resolve_language(source: Source, language: str | None) -> str:
    if language is not None:
        if language not in source.languages:
            raise SchemaViolation()
        return language
    if len(source.languages) != 1:
        raise AmbiguousInput(RunStage.SEGMENT_ALIGNMENT, len(source.languages))
    return source.languages[0]


def _succeeded_run(repo: Repository, run_id: str, stage: RunStage) -> ProcessingRun:
    run = repo.get_run(run_id)  # NotFound when the pinned run does not exist
    if run.stage is not stage or run.status is not RunStatus.SUCCEEDED:
        raise InvalidLineage()
    return run


def _input_segments(repo: Repository, run_id: str) -> list[Segment]:
    segments: list[Segment] = []
    for object_id, role in repo.list_run_io(run_id):
        if role is RunIoRole.INPUT and repo.entity_type_of(object_id) is EntityType.SEGMENT:
            segments.append(repo.get_segment(object_id))
    return segments


def _require_side_segment(
    repo: Repository, run: ProcessingRun, source_id: str, language: str
) -> None:
    """A pinned normalization run must consume at least one segment of this side."""
    for segment in _input_segments(repo, run.id):
        if segment.source_id == source_id and segment.language == language:
            return
    raise InvalidLineage()


def _unique_normalization(repo: Repository, source_id: str, language: str) -> ProcessingRun:
    """The unique succeeded normalization run applicable to (source, language).

    Applicable means: reachable from this source through extraction runs and consuming
    at least one raw segment of the side's language. Candidate discovery unions every
    generation, so two generations are ambiguous, never merged or auto-picked.
    """
    candidates: dict[str, ProcessingRun] = {}
    for obj in repo.list_source_objects(source_id):
        for extraction in repo.list_runs_with_input(
            obj.id, RunStage.EXTRACTION, RunStatus.SUCCEEDED
        ):
            for segment in repo.list_segments_for_run(extraction.id):
                if segment.source_id != source_id or segment.language != language:
                    continue
                for run in repo.list_runs_with_input(
                    segment.id, RunStage.NORMALIZATION, RunStatus.SUCCEEDED
                ):
                    candidates[run.id] = run
    if not candidates:
        raise NotFound(EntityType.PROCESSING_RUN.value, source_id)
    if len(candidates) > 1:
        raise AmbiguousInput(RunStage.NORMALIZATION, len(candidates))
    return next(iter(candidates.values()))


def _require_consumed_normalization(
    repo: Repository, tokenization: ProcessingRun, normalization_run_id: str
) -> None:
    """A pinned tokenization run must consume segments of the selected normalization run."""
    inputs = _input_segments(repo, tokenization.id)
    if not inputs or any(segment.run_id != normalization_run_id for segment in inputs):
        raise InvalidLineage()
