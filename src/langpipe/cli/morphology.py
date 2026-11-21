"""CLI commands for Stage 8 morphology induction and inspection (M5 WP5.9)."""

from typing import Annotated

import typer

from langpipe.cli.context import get_context, guarded
from langpipe.evaluation.morphology_service import evaluate_morphology_benchmark
from langpipe.morphology.service import induce_morphology

morph_app = typer.Typer(no_args_is_help=True)


def _flag(value: bool) -> str:
    return "true" if value else "false"


@morph_app.command("induce")
@guarded
def induce(
    tokenization_run: Annotated[
        str,
        typer.Option("--tokenization-run", help="Tokenization run ID."),
    ],
    method: Annotated[
        str,
        typer.Option("--method", help="Induction method reference (e.g. unsegmented@0.1.0)."),
    ],
    inventory_run: Annotated[
        str | None,
        typer.Option("--inventory-run", help="Optional morphology inventory run ID."),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Optional target language code override."),
    ] = None,
) -> None:
    """Induce morphology candidate segmentations from token occurrences."""
    result = induce_morphology(
        get_context(),
        tokenization_run_id=tokenization_run,
        method=method,
        inventory_run_id=inventory_run,
        language=language,
    )
    report_id = result.report.id if result.report is not None else "none"
    typer.echo(
        f"run_id={result.run.id} analyses={result.totals['analyses']} "
        f"segments={result.totals['segments']} report_id={report_id} "
        f"reused={_flag(result.reused)}"
    )


@morph_app.command("analyses")
@guarded
def list_analyses(
    token: Annotated[
        str,
        typer.Option("--token", help="Target token occurrence ID."),
    ],
) -> None:
    """List morphology analyses for a token occurrence (IDs and digests only; no surfaces)."""
    ctx = get_context()
    analyses = ctx.repo.list_morph_analyses_for_token(token)
    for a in sorted(analyses, key=lambda x: (x.method, x.id)):
        overall = f"{a.score_breakdown.overall:.4f}" if a.score_breakdown is not None else "none"
        typer.echo(
            f"id={a.id} method={a.method} kind={a.analysis_kind.value} "
            f"status={a.status.value} signature={a.signature} score_overall={overall}"
        )


@morph_app.command("benchmark")
@guarded
def benchmark(
    run: Annotated[
        list[str],
        typer.Option("--run", help="Evaluated morphology induction run ID(s)."),
    ],
    gold: Annotated[
        str | None,
        typer.Option("--gold", help="Path to frozen MorphGold JSON file."),
    ] = None,
    gold_from_igt: Annotated[
        str | None,
        typer.Option("--gold-from-igt", help="IGT extract run ID to derive gold from."),
    ] = None,
    gold_ref: Annotated[
        list[str] | None,
        typer.Option("--gold-ref", help="IGT record reference(s) for held-out gold."),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Optional language code override."),
    ] = None,
) -> None:
    """Benchmark morphology induction runs against gold annotations (Gate 40, ADR-0019)."""
    if not gold and not gold_from_igt:
        typer.echo("Error: either --gold or --gold-from-igt must be provided", err=True)
        raise typer.Exit(code=2)
    if gold and gold_from_igt:
        typer.echo("Error: cannot provide both --gold and --gold-from-igt", err=True)
        raise typer.Exit(code=2)

    target_gold = gold if gold else gold_from_igt
    assert target_gold is not None
    summary = evaluate_morphology_benchmark(
        get_context(),
        evaluated_run_ids=run,
        gold=target_gold,
        refs=gold_ref or (),
        language=language,
    )
    typer.echo(
        f"run_id={summary.run.id} report_id={summary.report.id} "
        f"evaluated_runs={len(run)} reused={_flag(summary.reused)}"
    )
    for method, met in sorted(summary.metrics.items()):
        typer.echo(
            f"method={method} f1={met.boundary_f1:.4f} exact={met.exact_accuracy:.4f} "
            f"coverage={met.coverage:.4f} abstention={met.abstention_rate:.4f}"
        )
