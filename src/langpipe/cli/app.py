"""Root Typer application and console entry point (`langpipe`)."""

from enum import StrEnum
from typing import Annotated

import typer

from langpipe.cli.alignment import align_app
from langpipe.cli.cldf import cldf_app
from langpipe.cli.context import exit_with_error, exit_with_unexpected
from langpipe.cli.harvest import harvest_app
from langpipe.cli.igt import igt_app
from langpipe.cli.lexicon import lexicon_app
from langpipe.cli.lineage import lineage_app
from langpipe.cli.morphology import morph_app
from langpipe.cli.review import review_app
from langpipe.cli.schemas import schemas_app
from langpipe.cli.scriptureearth import scriptureearth_app
from langpipe.cli.source import source_app
from langpipe.cli.synthesis import synth_app
from langpipe.cli.text import extract, normalize, profiles_app, tokenize
from langpipe.domain.errors import LangpipeError
from langpipe.logging import configure_logging


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(source_app, name="source")
app.add_typer(align_app, name="align")
app.add_typer(cldf_app, name="cldf")
app.add_typer(harvest_app, name="harvest")
app.add_typer(lexicon_app, name="lexicon")
app.add_typer(lineage_app, name="lineage")
app.add_typer(review_app, name="review")
app.add_typer(schemas_app, name="schemas")
app.add_typer(profiles_app, name="profiles")
app.add_typer(scriptureearth_app, name="scriptureearth")
app.add_typer(synth_app, name="synth")
app.add_typer(igt_app, name="igt")
app.add_typer(morph_app, name="morph")
app.command("extract")(extract)
app.command("normalize")(normalize)
app.command("tokenize")(tokenize)


@app.callback()
def root(
    log_level: Annotated[LogLevel, typer.Option("--log-level")] = LogLevel.INFO,
) -> None:
    configure_logging(log_level.value)


def main() -> None:
    try:
        app()
    except LangpipeError as error:
        exit_with_error(error)
    except Exception:
        # Backstop for failures outside a guarded command, such as the root callback.
        exit_with_unexpected()
