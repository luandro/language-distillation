"""``langpipe extract``, ``normalize``, ``tokenize`` and ``profiles list`` (M2 WP2.13).

These wrappers only parse arguments, call one service and print a ``key=value`` summary of
identifiers and counts. All pipeline logic lives in the services. Segment, token, TSV-cell and
file-name text is never echoed (M2 E10): ``tokenize`` runs normalization for the source first, so
one command drives Stage 3 (E1/C2).
"""

from collections.abc import Sequence
from typing import Annotated

import typer

from langpipe.cli.context import get_context, guarded
from langpipe.domain.errors import SchemaViolation
from langpipe.extraction.registry import EXTRACTORS
from langpipe.extraction.service import extract_source
from langpipe.ingestion.ingest import resolve_source
from langpipe.languages.base import LANGUAGE_PROFILES, NORMALIZATION_PROFILES, TOKENIZERS
from langpipe.normalization.service import normalize_extraction, select_extraction_run
from langpipe.tokenization.service import tokenize_normalization


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _parse_assignments(values: Sequence[str] | None) -> dict[str, str] | None:
    """Parse repeated ``ISO=NAME@VERSION`` options; malformed or duplicate entries are refused."""
    if not values:
        return None
    parsed: dict[str, str] = {}
    for value in values:
        key, separator, assigned = value.partition("=")
        if not separator or not key or not assigned or key in parsed:
            raise SchemaViolation()
        parsed[key] = assigned
    return parsed


@guarded
def extract(
    source_ref: str,
    extractor: Annotated[str | None, typer.Option("--extractor")] = None,
    language: Annotated[str | None, typer.Option("--language")] = None,
) -> None:
    result = extract_source(get_context(), source_ref, extractor=extractor, language=language)
    report_id = result.report.id if result.report is not None else "none"
    typer.echo(
        f"source_id={result.source.id} run_id={result.run.id} segments={result.segments} "
        f"skipped_objects={len(result.skipped_objects)} report_id={report_id} "
        f"reused={_flag(result.reused)}"
    )


@guarded
def normalize(
    source_ref: str,
    extraction_run: Annotated[str | None, typer.Option("--extraction-run")] = None,
    profile: Annotated[list[str] | None, typer.Option("--profile")] = None,
) -> None:
    ctx = get_context()
    source = resolve_source(ctx, source_ref)
    run = select_extraction_run(ctx, source, extraction_run)
    summary = normalize_extraction(ctx, run.id, profiles=_parse_assignments(profile))
    report_id = summary.report.id if summary.report is not None else "none"
    typer.echo(
        f"extraction_run_id={run.id} run_id={summary.run.id} segments={summary.segments} "
        f"failed={summary.failed} report_id={report_id} reused={_flag(summary.reused)}"
    )


@guarded
def tokenize(
    source_ref: str,
    extraction_run: Annotated[str | None, typer.Option("--extraction-run")] = None,
    profile: Annotated[list[str] | None, typer.Option("--profile")] = None,
    tokenizer: Annotated[list[str] | None, typer.Option("--tokenizer")] = None,
) -> None:
    ctx = get_context()
    source = resolve_source(ctx, source_ref)
    run = select_extraction_run(ctx, source, extraction_run)
    normalization = normalize_extraction(ctx, run.id, profiles=_parse_assignments(profile))
    summary = tokenize_normalization(
        ctx, normalization.run.id, tokenizers=_parse_assignments(tokenizer)
    )
    report_id = summary.report.id if summary.report is not None else "none"
    typer.echo(
        f"extraction_run_id={run.id} normalization_run_id={normalization.run.id} "
        f"run_id={summary.run.id} tokens={summary.tokens} forms={summary.forms} "
        f"skipped_segments={summary.skipped_failed_segments} report_id={report_id} "
        f"reused={_flag(summary.reused)}"
    )


profiles_app = typer.Typer(no_args_is_help=True)


@profiles_app.command("list")
@guarded
def list_profiles() -> None:
    for name in EXTRACTORS.names():
        typer.echo(f"kind=extractor name={name}")
    for name in NORMALIZATION_PROFILES.names():
        typer.echo(f"kind=normalization name={name}")
    for name in TOKENIZERS.names():
        typer.echo(f"kind=tokenizer name={name}")
    for language in sorted(LANGUAGE_PROFILES):
        profile = LANGUAGE_PROFILES[language]
        typer.echo(
            f"kind=language language={language} profile={profile.name}@{profile.version} "
            f"normalization={profile.normalization} tokenizer={profile.tokenizer}"
        )
