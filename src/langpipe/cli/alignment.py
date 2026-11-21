"""`langpipe align` commands for segment and token alignment evidence."""

import typer

from langpipe.alignment.base import AlignmentConfig
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.selection import resolve_alignment_side
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.cli.context import get_context, guarded
from langpipe.domain.enums import RunStage, RunStatus, Symmetrization
from langpipe.domain.errors import (
    AlignmentFailed,
    AmbiguousInput,
    InvalidLineage,
)

align_app = typer.Typer(no_args_is_help=True)


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _unique_tokenization_run(ctx: AppContext, normalization_run_id: str) -> str:
    candidates: set[str] = {
        run.id
        for segment in ctx.repo.list_segments_for_run(normalization_run_id)
        for run in ctx.repo.list_runs_with_input(
            segment.id, RunStage.TOKENIZATION, RunStatus.SUCCEEDED
        )
    }
    if not candidates:
        raise AlignmentFailed("missing_tokenization")
    if len(candidates) > 1:
        raise AmbiguousInput(RunStage.TOKENIZATION, len(candidates))
    return next(iter(candidates))


@align_app.command("segments")
@guarded
def segments(
    source_a_ref: str,
    source_b_ref: str,
    method: str = "canonical_locator@0.1.0",
    source_language: str | None = None,
    target_language: str | None = None,
    source_normalization_run: str | None = None,
    target_normalization_run: str | None = None,
    namespace: str = typer.Option(..., "--namespace"),
    versification_id: str | None = None,
    threads: int = 1,
    timeout_seconds: float = 300.0,
    seed: int | None = None,
) -> None:
    # Segment aligners expose no seed support.
    if seed is not None:
        raise AlignmentFailed("unsupported_seed")
    if namespace == "scripture" and versification_id is None:
        raise AlignmentFailed("incompatible_versification")
    ctx = get_context()
    source = resolve_alignment_side(
        ctx, source_a_ref, source_language, source_normalization_run, None
    )
    target = resolve_alignment_side(
        ctx, source_b_ref, target_language, target_normalization_run, None
    )
    config = AlignmentConfig(
        namespace=namespace,
        versification_id=versification_id,
        threads=threads,
        timeout_seconds=timeout_seconds,
        random_seed=seed,
    )
    summary = SegmentAlignmentService(ctx).align(source, target, method=method, config=config)
    report_id = summary.report.id if summary.report is not None else "none"
    typer.echo(
        f"run_id={summary.run.id} report_id={report_id} alignments={summary.alignments} "
        f"unmatched_source={summary.unmatched_source} "
        f"unmatched_target={summary.unmatched_target} reused={_flag(summary.reused)}"
    )


@align_app.command("tokens")
@guarded
def tokens(
    segment_alignment_run_id: str,
    method: str = "eflomal@0.1.0",
    source_tokenization_run: str | None = None,
    target_tokenization_run: str | None = None,
    symmetrization: Symmetrization = Symmetrization.INTERSECTION,
    threads: int = 1,
    timeout_seconds: float = 300.0,
    seed: int | None = None,
) -> None:
    ctx = get_context()
    segment_run = ctx.repo.get_run(segment_alignment_run_id)
    if (
        segment_run.stage is not RunStage.SEGMENT_ALIGNMENT
        or segment_run.status is not RunStatus.SUCCEEDED
    ):
        raise InvalidLineage()
    sides = segment_run.config.get("sides")
    if not isinstance(sides, list) or len(sides) != 2:
        raise InvalidLineage()
    normalization_ids: list[str] = []
    for side in sides:
        if not isinstance(side, dict):
            raise InvalidLineage()
        normalization_id = side.get("normalization_run_id")
        if not isinstance(normalization_id, str):
            raise InvalidLineage()
        normalization_ids.append(normalization_id)
    namespace = segment_run.config.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        raise InvalidLineage()
    if "versification_id" not in segment_run.config:
        raise InvalidLineage()
    versification_id = segment_run.config["versification_id"]
    if versification_id is not None and not isinstance(versification_id, str):
        raise InvalidLineage()
    source_token_run = source_tokenization_run or _unique_tokenization_run(
        ctx, normalization_ids[0]
    )
    target_token_run = target_tokenization_run or _unique_tokenization_run(
        ctx, normalization_ids[1]
    )
    config = AlignmentConfig(
        namespace=namespace,
        versification_id=versification_id,
        symmetrization=symmetrization,
        threads=threads,
        timeout_seconds=timeout_seconds,
        random_seed=seed,
    )
    summary = TokenAlignmentService(ctx).align(
        segment_alignment_run_id,
        source_tokenization_run_id=source_token_run,
        target_tokenization_run_id=target_token_run,
        method=method,
        config=config,
    )
    typer.echo(
        f"run_id={summary.run.id} report_id={summary.report.id} edges={summary.edges} "
        f"unaligned_source={summary.unaligned_source} "
        f"unaligned_target={summary.unaligned_target} "
        f"skipped_groups={summary.skipped_groups} reused={_flag(summary.reused)}"
    )
