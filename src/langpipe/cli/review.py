"""`langpipe review` commands for the human review queue (WP4.8, ADR-0013 §4-5).

The CLI builds its authority registry from structured language profile configuration
(`ReviewAuthorityGrant`): an identity that no configured profile grants authority is
denied by the real service. No built-in fixture reviewer exists.
"""

from typing import Annotated

import typer

from langpipe.cli.context import get_context, guarded
from langpipe.domain.enums import ReviewDecisionKind, ReviewTaskType
from langpipe.review.authority import registry_from_profiles
from langpipe.review.recalc import RecalcService
from langpipe.review.service import ReviewService

review_app = typer.Typer(name="review", help="Human review queue and decisions")


def _service() -> ReviewService:
    ctx = get_context()
    return ReviewService(
        ctx.repo,
        registry_from_profiles(),
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )


@review_app.command("list")
@guarded
def list_tasks(
    task_type: Annotated[str | None, typer.Option("--type", help="Filter by task type.")] = None,
    role: Annotated[str | None, typer.Option("--role", help="Filter by required role.")] = None,
    status: Annotated[
        str | None,
        typer.Option(
            "--status",
            help="Filter by queue state (open|in_review|resolved|cancelled); default open.",
        ),
    ] = None,
    min_priority: Annotated[
        float | None, typer.Option("--min-priority", help="Only tasks at or above this priority.")
    ] = None,
    language: Annotated[
        str | None, typer.Option("--language", help="Filter by target language (ISO 639-3).")
    ] = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Show at most N tasks.")] = None,
) -> None:
    service = _service()
    tasks = service.list_tasks(
        task_type=ReviewTaskType(task_type) if task_type is not None else None,
        required_role=role,
        status=status if status is not None else "open",
        min_priority=min_priority,
        language=language,
        limit=limit,
    )
    # Identifiers, enum values and scores only; a queue listing never echoes source content.
    typer.echo(f"{'ID':<32} {'Type':<20} {'Target':<32} {'Priority':>8} {'Role':<22} Reason")
    for task in tasks:
        typer.echo(
            f"{task.id:<32} {task.task_type.value:<20} {task.target_id:<32} "
            f"{task.priority:>8g} {task.required_role:<22} {task.reason}"
        )


@review_app.command("decide")
@guarded
def decide(
    task_id: Annotated[str, typer.Option("--task-id", help="Open review task id.")],
    decision: Annotated[
        str, typer.Option("--decision", help="accept|reject|modify|uncertain|defer")
    ],
    reviewer: Annotated[str, typer.Option("--reviewer", help="Reviewer identifier.")],
    role: Annotated[str, typer.Option("--role", help="Reviewer role.")],
    notes: Annotated[str | None, typer.Option("--notes", help="Optional decision notes.")] = None,
    superseding: Annotated[
        str | None, typer.Option("--superseding", help="Superseding object id (modify).")
    ] = None,
) -> None:
    result = _service().record_decision(
        task_id,
        ReviewDecisionKind(decision),
        reviewer,
        role,
        superseding_object_id=superseding,
        notes=notes,
    )
    target_status = "unchanged" if result.target_status is None else result.target_status.value
    typer.echo(
        f"decision_id={result.decision.id} task_id={task_id} decision={decision} "
        f"target_status={target_status} task_status={result.task_status}"
    )


@review_app.command("recalc")
@guarded
def recalc(
    object_ids: Annotated[
        list[str] | None,
        typer.Option("--object", help="Object ID to recalculate (can be repeated)."),
    ] = None,
    all_stale: Annotated[
        bool,
        typer.Option("--all-stale", help="Recalculate all stale objects across the repository."),
    ] = False,
) -> None:
    ctx = get_context()
    service = RecalcService(
        ctx.repo,
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )
    result = service.recalculate(object_ids=object_ids, all_stale=all_stale)
    typer.echo(
        f"run_id={result.run.id} recalculated={len(result.recalculated_ids)} "
        f"skipped={len(result.skipped_ids)}"
    )
    for oid in result.recalculated_ids:
        typer.echo(f"  recalculated {oid}")
    for oid in result.skipped_ids:
        typer.echo(f"  skipped {oid} (not stale)")
