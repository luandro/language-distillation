"""`langpipe schemas` commands: generate and drift-check the committed JSON Schema files."""

from pathlib import Path
from typing import Annotated

import typer

from langpipe.cli.context import guarded
from langpipe.schemas.generate import DEFAULT_SCHEMA_DIR, check, generate

schemas_app = typer.Typer(no_args_is_help=True)

SchemaDirOption = Annotated[Path, typer.Option("--dir")]


@schemas_app.command("generate")
@guarded
def generate_command(schema_dir: SchemaDirOption = DEFAULT_SCHEMA_DIR) -> None:
    typer.echo(f"written={len(generate(schema_dir))}")


@schemas_app.command("check")
@guarded
def check_command(schema_dir: SchemaDirOption = DEFAULT_SCHEMA_DIR) -> None:
    drift = check(schema_dir)
    if not drift:
        typer.echo("status=ok")
        return
    for name in drift:
        typer.echo(f"drift={name}")
    raise typer.Exit(code=1)
