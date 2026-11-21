"""Shared helper for CLI tests that must exercise the installed console script."""

import os
import subprocess
import sys
from pathlib import Path

CONSOLE_TIMEOUT_SECONDS = 120
# Pydantic prints a field-shadow UserWarning at import time for every model whose
# `register` field shadows the deprecated `BaseModel.register` method. Each warning is a
# header line (`path:line: UserWarning: Field name "register" ...`) followed by the
# indented source echo of the model class line. None of it is a CLI diagnostic, so the two
# known blocks are dropped: CLI diagnostics are unindented `key=value` lines on stderr and
# must survive untouched.
_FIELD_SHADOW_MODELS = ("EvidenceItem", "Lexeme", "Sense")
_FIELD_SHADOW_WARNING_BODY = 'UserWarning: Field name "register" in "'


def _is_field_shadow_warning(line: str) -> bool:
    return _FIELD_SHADOW_WARNING_BODY in line and any(
        f'"{model}"' in line for model in _FIELD_SHADOW_MODELS
    )


def diagnostic_lines(stderr: str) -> list[str]:
    """Stderr lines that the CLI itself wrote, without the known import-time warning blocks."""
    lines = stderr.splitlines()
    kept: list[str] = []
    for index, line in enumerate(lines):
        if _is_field_shadow_warning(line):
            continue  # the header line
        if line.startswith(" ") and index and _is_field_shadow_warning(lines[index - 1]):
            continue  # the source echo of the preceding known warning header
        kept.append(line)
    return kept


def run_console(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the `langpipe` console script that ships with this environment, not CliRunner."""
    script = Path(sys.executable).with_name("langpipe")
    return subprocess.run(
        [str(script), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=False,
        timeout=CONSOLE_TIMEOUT_SECONDS,
    )
