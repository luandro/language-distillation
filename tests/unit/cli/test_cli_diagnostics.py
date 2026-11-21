"""`diagnostic_lines` must strip only the known Pydantic field-shadow warning blocks.

Unrelated warnings, unexpected indented content and ordinary error lines are CLI
diagnostics or at least not the known import-time noise, so they must survive unchanged:
a broad filter would hide them from every CLI assertion.
"""

import sys
from pathlib import Path

import pytest

from tests.unit.cli import diagnostic_lines

REPO_ROOT = Path(__file__).resolve().parents[3]
_MODELS_MODULE = REPO_ROOT / "src/langpipe/domain/models"
EVIDENCE_MODEL_LINE = 14
LEXEME_MODEL_LINE = 96
SENSE_MODEL_LINE = 132

KNOWN_WARNING_HEADERS = [
    f"{_MODELS_MODULE / 'evidence.py'}:{EVIDENCE_MODEL_LINE}: UserWarning: "
    'Field name "register" in "EvidenceItem" shadows an attribute in parent "DomainModel"',
    f"{_MODELS_MODULE / 'lexical.py'}:{LEXEME_MODEL_LINE}: UserWarning: "
    'Field name "register" in "Lexeme" shadows an attribute in parent "DomainModel"',
    f"{_MODELS_MODULE / 'lexical.py'}:{SENSE_MODEL_LINE}: UserWarning: "
    'Field name "register" in "Sense" shadows an attribute in parent "DomainModel"',
]
ECHO_LINES = [
    "  class EvidenceItem(DomainModel):",
    "  class Lexeme(DomainModel):",
    "  class Sense(DomainModel):",
]


def test_known_field_shadow_warning_blocks_are_removed() -> None:
    stderr = "".join(
        f"{header}\n{echo}\n"
        for header, echo in zip(KNOWN_WARNING_HEADERS, ECHO_LINES, strict=True)
    )

    assert diagnostic_lines(stderr) == []


def test_known_warnings_removed_but_diagnostics_kept() -> None:
    stderr = "".join(
        f"{header}\n{echo}\n"
        for header, echo in zip(KNOWN_WARNING_HEADERS, ECHO_LINES, strict=True)
    )
    stderr += "error=LangpipeError\n"

    assert diagnostic_lines(stderr) == ["error=LangpipeError"]


def test_unrelated_user_warning_survives() -> None:
    line = "example.py:1: UserWarning: unexpected warning"

    assert diagnostic_lines(line) == [line]


def test_unrelated_user_warning_about_another_field_survives() -> None:
    line = (
        f"{_MODELS_MODULE / 'lexical.py'}:200: UserWarning: "
        'Field name "pos" in "Lexeme" shadows an attribute in parent "DomainModel"'
    )

    assert diagnostic_lines(line) == [line]


def test_unrelated_user_warning_about_another_model_survives() -> None:
    line = (
        f"{_MODELS_MODULE / 'lexical.py'}:200: UserWarning: "
        'Field name "register" in "SenseGroup" shadows an attribute in parent "DomainModel"'
    )

    assert diagnostic_lines(line) == [line]


def test_indented_content_next_to_unknown_header_survives() -> None:
    unknown_header = "example.py:1: UserWarning: unexpected warning"

    lines = diagnostic_lines(f"{unknown_header}\n  RESTRICTED_SENTINEL\n")

    assert lines == [unknown_header, "  RESTRICTED_SENTINEL"]


def test_indented_content_after_known_block_is_kept() -> None:
    stderr = (
        f"{KNOWN_WARNING_HEADERS[1]}\n  class Lexeme(DomainModel):\n  unexpected indented detail\n"
    )

    assert diagnostic_lines(stderr) == ["  unexpected indented detail"]


def test_ordinary_error_line_survives() -> None:
    assert diagnostic_lines("error=expected") == ["error=expected"]


def test_plain_stderr_is_unchanged() -> None:
    lines = ["error=LangpipeError", "  indented detail", "warning: something odd"]

    assert diagnostic_lines("\n".join(lines)) == lines


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX stderr only")
def test_real_console_script_stderr_has_only_known_warning_blocks() -> None:
    """The filter must match the warnings langpipe actually prints today."""
    import subprocess

    script = Path(sys.executable).with_name("langpipe")
    completed = subprocess.run(
        [str(script), "--help"], capture_output=True, text=True, check=False, timeout=120
    )
    kept = diagnostic_lines(completed.stderr)

    assert completed.returncode == 0, completed.stderr
    assert kept == [], kept
    assert len(KNOWN_WARNING_HEADERS) == 3
