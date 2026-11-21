"""CLI commands for synthetic data generation, quality filtering, and dataset export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from langpipe.synthesis.batch import HighThroughputBatchHarness
from langpipe.synthesis.export_dataset import (
    BENCHMARK_VERSION,
    DEFAULT_MAX_REGISTER_SHARE,
    DatasetExporter,
    load_source_index,
)

synth_app = typer.Typer(
    name="synth",
    help="Synthetic data generation, multi-gate validation, and NMT dataset export.",
    no_args_is_help=True,
)


@synth_app.command("batch")
def batch_command(
    lang: Annotated[
        str,
        typer.Option("--lang", "-l", help="Target language code (e.g. mzr)."),
    ] = "und",
    count: Annotated[
        int,
        typer.Option("--count", "-n", help="Total number of synthetic phrases to generate."),
    ] = 100,
    seed: Annotated[
        int,
        typer.Option("--seed", "-s", help="Random seed for reproducibility."),
    ] = 42,
    output_dir: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Custom output directory."),
    ] = None,
) -> None:
    typer.echo(
        f"🚀 Starting batch generation for {lang}: requesting {count} phrases (seed={seed})..."
    )
    harness = HighThroughputBatchHarness(lang_code=lang, output_dir=output_dir)
    phrases, summary = harness.run_batch(target_count=count, seed=seed)

    typer.echo("\n✅ Batch generation finished!")
    typer.echo(f"   • Total generated:    {summary.total_generated}")
    typer.echo(f"   • Passed all gates:   {summary.passed_count}")
    typer.echo(f"   • Needs human review: {summary.needs_review_count}")
    typer.echo(f"   • Quarantined:        {summary.quarantined_count}")
    typer.echo(f"   • L0 failures:        {summary.gate_l0_failures}")
    typer.echo(f"   • L1 failures:        {summary.gate_l1_failures}")
    typer.echo(f"   • L2 failures:        {summary.gate_l2_failures}")
    typer.echo(f"   • Output stored in:   {summary.output_file}")


@synth_app.command("export")
def export_command(
    lang: Annotated[
        str,
        typer.Option("--lang", "-l", help="Target language code (e.g. mzr)."),
    ] = "und",
    output_dir: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Custom output directory."),
    ] = None,
    source_index: Annotated[
        Path,
        typer.Option(
            "--source-index",
            help=(
                "Provenance -> trace-id JSON map (operator-generated from registered "
                "sources; one entry per provenance prefix)."
            ),
        ),
    ] = Path("var/exports/source_index.json"),
    max_register_share: Annotated[
        float,
        typer.Option(
            "--max-register-share",
            help=(
                "Cap on any harvested register's share of test and val, anchored on the "
                "scripture block; overflow rows go to train. 1.0 disables the cap."
            ),
        ),
    ] = DEFAULT_MAX_REGISTER_SHARE,
    benchmark_version: Annotated[
        int,
        typer.Option(
            "--benchmark-version",
            help=(
                "Held-out benchmark revision: 2 (default) repairs or excludes defective "
                "Bible val/test rows and builds the chant benchmark; 1 is the legacy selection. "
                "Scores are comparable only within one version."
            ),
        ),
    ] = BENCHMARK_VERSION,
) -> None:
    """Export validated synthetic and attested parallel data into NMT and LoRA formats."""
    typer.echo(f"📦 Exporting fine-tuning datasets for {lang}...")
    # Load synthetic phrases
    synth_file = Path("exports") / lang / "synthetic_phrases.json"
    phrases = []
    if synth_file.exists():
        with open(synth_file, encoding="utf-8") as f:
            data = json.load(f)
            phrases = data.get("phrases", [])

    try:
        index = load_source_index(source_index)
    except ValueError as exc:
        typer.echo(f"error={exc}", err=True)
        raise typer.Exit(code=2) from None
    if not index:
        typer.echo(
            f"warning: no source index at {source_index}; rows will carry provenance only",
            err=True,
        )

    exporter = DatasetExporter(
        lang_code=lang,
        output_dir=output_dir,
        source_index=index,
        source_index_path=source_index,
    )
    try:
        summary = exporter.export(
            synthetic_phrases=phrases,
            max_register_share=max_register_share,
            benchmark_version=benchmark_version,
        )
    except ValueError as exc:
        typer.echo(f"error={exc}", err=True)
        raise typer.Exit(code=2) from None

    typer.echo("\n✅ Datasets successfully exported!")
    typer.echo(
        f"   • Train partition:  {summary.train_count} pairs "
        f"({summary.synthetic_train_count} synth + "
        f"{summary.corpus_train_count} corpus + "
        f"{summary.harvested_train_count} harvested oral)"
    )
    typer.echo(
        f"   • Val partition:    {summary.val_count} pairs "
        f"({summary.harvested_val_count} harvested oral, 100% human gold truth)"
    )
    typer.echo(
        f"   • Test partition:   {summary.test_count} pairs "
        f"({summary.harvested_test_count} harvested oral, 100% human gold truth)"
    )
    typer.echo(f"   • Trace ids missing:{summary.rows_without_source_ids} row(s)")
    typer.echo(f"   • Test pure gold:   {summary.test_purity_verified}")
    typer.echo(f"   • Val pure gold:    {summary.val_purity_verified}")
    typer.echo(
        f"   • Register cap:     {summary.max_register_share} "
        f"(limits {summary.register_cap_limits}, "
        f"moved to train {summary.register_overflow_to_train})"
    )
    typer.echo(f"   • Output directory: {summary.output_dir}")
