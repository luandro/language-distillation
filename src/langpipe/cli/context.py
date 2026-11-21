"""Application context for CLI commands, plus the shared error wrapper and error report.

The wrapper lives here, not in `app.py`, so command modules can use it without an import cycle.
"""

import functools
import sys
from collections.abc import Callable

import typer
from typer.exceptions import TyperException

from langpipe.app_context import AppContext, build_context
from langpipe.config.settings import Settings
from langpipe.domain.errors import LangpipeError
from langpipe.domain.ids import IdPrefix, is_id

_factory: Callable[[], AppContext] | None = None

# Typer and Click use these for exit codes and usage errors. They are never failures to report.
# typer.Exit subclasses RuntimeError, so it must be re-raised before any broad `except Exception`.
_CONTROL_FLOW = (typer.Exit, typer.Abort, TyperException)


def set_context_factory(factory: Callable[[], AppContext]) -> None:
    global _factory
    _factory = factory


def reset_context_factory() -> None:
    global _factory
    _factory = None


def get_context() -> AppContext:
    if _factory is not None:
        return _factory()
    return build_context(Settings.from_env())


def report(error: LangpipeError) -> None:
    # Only the class name and validated identifiers: messages may echo input or content.
    fields = [f"error={type(error).__name__}"]
    source_id = getattr(error, "source_id", None)
    if isinstance(source_id, str) and is_id(source_id, IdPrefix.SOURCE):
        fields.append(f"source_id={source_id}")
    typer.echo(" ".join(fields), err=True)


def report_unexpected() -> None:
    # Operational failures (SQL, filesystem, driver) can carry parameters, paths or content.
    # Print only the fixed class name.
    typer.echo(f"error={LangpipeError.__name__}", err=True)


def guarded[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Report failures and exit with a code, so CliRunner and the console script agree.

    LangpipeError keeps its own code and safe report. Any other Exception is reported with the
    fixed generic diagnostic and the generic exit code. Its message, SQL, and traceback are dropped.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except LangpipeError as error:
            report(error)
            raise typer.Exit(code=error.exit_code) from None
        except _CONTROL_FLOW:
            raise
        except Exception:
            report_unexpected()
            raise typer.Exit(code=LangpipeError.exit_code) from None

    return wrapper


def exit_with_error(error: LangpipeError) -> None:
    """Used by `main()` for errors that escape a command; prints the report and exits."""
    report(error)
    sys.exit(error.exit_code)


def exit_with_unexpected() -> None:
    """Used by `main()` for unexpected errors that escape a command; prints the fixed report."""
    report_unexpected()
    sys.exit(LangpipeError.exit_code)
