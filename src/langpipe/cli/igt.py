"""CLI commands for IGT import and morphology operations (M5 WP5.7)."""

from typing import Annotated

import typer

from langpipe.cli.context import get_context, guarded
from langpipe.igt.service import extract_igt
from langpipe.morphology.service import assert_igt

igt_app = typer.Typer(no_args_is_help=True)


def _flag(value: bool) -> str:
    return "true" if value else "false"


@igt_app.command("extract")
@guarded
def extract(
    source_ref: Annotated[str, typer.Argument(help="Source ID or unique key.")],
    reader: Annotated[
        str | None,
        typer.Option("--reader", help="Explicit reader reference (e.g. toolbox_igt@0.1.0)."),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Explicit target language code."),
    ] = None,
    contact_language: Annotated[
        str | None,
        typer.Option("--contact-language", help="Optional contact language code."),
    ] = None,
) -> None:
    """Import an ingested IGT source into observations and text-tier segments."""
    result = extract_igt(
        get_context(),
        source_ref,
        reader=reader,
        language=language,
        contact_language=contact_language,
    )
    report_id = result.report.id if result.report is not None else "none"
    typer.echo(
        f"source_id={result.source.id} run_id={result.run.id} records={result.records} "
        f"segments={result.segments} words={result.words} morphs={result.morphs} "
        f"report_id={report_id} reused={_flag(result.reused)}"
    )


@igt_app.command("assert")
@guarded
def assert_morphology(
    tokenization_run: Annotated[
        str,
        typer.Option("--tokenization-run", help="Tokenization run ID."),
    ],
    igt_run: Annotated[
        str,
        typer.Option("--igt-run", help="IGT extract run ID."),
    ],
    exclude_refs: Annotated[
        list[str] | None,
        typer.Option("--exclude-ref", help="Held-out IGT reference(s) to exclude from assertion."),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Optional language code override."),
    ] = None,
    contact_language: Annotated[
        str | None,
        typer.Option("--contact-language", help="Optional contact language code override."),
    ] = None,
) -> None:
    """Assert morphology hypotheses from IGT observations on mapped tokens."""
    result = assert_igt(
        get_context(),
        tokenization_run_id=tokenization_run,
        igt_extract_run_id=igt_run,
        exclude_refs=exclude_refs or (),
        language=language,
        contact_language=contact_language,
    )
    report_id = result.report.id if result.report is not None else "none"
    typer.echo(
        f"run_id={result.run.id} analyses={result.totals['analyses']} "
        f"morphemes={result.totals['morphemes']} allomorphs={result.totals['allomorphs']} "
        f"report_id={report_id} reused={_flag(result.reused)}"
    )
