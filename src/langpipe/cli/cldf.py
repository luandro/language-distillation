"""`langpipe cldf` commands for governed CLDF interchange (WP4.10 §4).

Import runs the governed extraction and, by default, Stage 6 over the snapshot —
`--extract-only` stops after the extraction run, matching the wordlist two-step flow.
Export publishes one language's eligible lexical knowledge as a CLDF Dictionary.
Output is `key=value` lines with ids and counts only: a form, a gloss or any other
source content is never printed.
"""

from pathlib import Path
from typing import Annotated

import typer

from langpipe.cldf.exporter import CLDFExporter
from langpipe.cldf.importer import CLDFImporter
from langpipe.cli.context import get_context, guarded

cldf_app = typer.Typer(name="cldf", help="CLDF import and export")


def _flag(value: bool) -> str:
    return "true" if value else "false"


@cldf_app.command("import")
@guarded
def import_dataset(
    source_ref: Annotated[str, typer.Argument(help="Registered CLDF source id or key.")],
    target_language: Annotated[str | None, typer.Option("--target-language")] = None,
    contact_language: Annotated[str | None, typer.Option("--contact-language")] = None,
    extract_only: Annotated[
        bool, typer.Option("--extract-only", help="Stop after the governed extraction run.")
    ] = False,
) -> None:
    ctx = get_context()
    if extract_only:
        extraction = CLDFImporter(ctx).extract(
            source_ref, target_language=target_language, contact_language=contact_language
        )
        fields = [
            f"source_id={extraction.source.id}",
            f"run_id={extraction.run.id}",
            f"snapshot_id={extraction.snapshot.id}",
            f"report_id={extraction.report.id}",
            f"reused={_flag(extraction.reused)}",
        ]
        typer.echo(" ".join(fields))
        return
    extraction, induction = CLDFImporter(ctx).import_dataset(
        source_ref, target_language=target_language, contact_language=contact_language
    )
    fields = [
        f"source_id={extraction.source.id}",
        f"extraction_run_id={extraction.run.id}",
        f"run_id={induction.run.id}",
        f"snapshot_id={extraction.snapshot.id}",
        f"lexemes={induction.lexemes}",
        f"senses={induction.senses}",
        f"concepts={induction.concepts}",
        f"evidence_items={induction.evidence_items}",
        f"reused={_flag(induction.reused)}",
    ]
    fields.extend(f"{name}={count}" for name, count in sorted(induction.status_counts.items()))
    typer.echo(" ".join(fields))


@cldf_app.command("export")
@guarded
def export(
    language: Annotated[str, typer.Option("--language", help="ISO 639-3 language to export.")],
    output_dir: Annotated[Path, typer.Option("--output-dir", help="Dataset directory.")],
    include_supported: Annotated[
        bool,
        typer.Option(
            "--include-supported", help="Also export SUPPORTED rows, with a Status column."
        ),
    ] = False,
) -> None:
    ctx = get_context()
    result = CLDFExporter(ctx).export(
        language=language, output_dir=output_dir, include_supported=include_supported
    )
    fields = [
        f"run_id={result.run.id}",
        f"entries={result.exported.get('entries', 0)}",
        f"senses={result.exported.get('senses', 0)}",
        f"languages={result.exported.get('languages', 0)}",
        f"sources={result.exported.get('sources', 0)}",
        f"files={len(result.files)}",
        f"reused={_flag(result.reused)}",
    ]
    fields.extend(f"omitted.{name}={count}" for name, count in sorted(result.omitted.items()))
    typer.echo(" ".join(fields))
