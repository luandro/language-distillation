"""Language-isolation guard (M2 WP2.7, AGENTS § Language-specific code).

Only ``languages/base.py`` (the one registry import line) and CLI *help strings* may mention a
language name outside ``languages/mzr/``. Every other occurrence — imports, identifiers,
conditionals, non-help string literals — is an offender. The scanner parses the source with
``ast`` so it can tell a help string apart from language-specific logic.
"""

import ast
import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3] / "src" / "langpipe"
_PATTERN = re.compile(r"mzr|marubo|mar\u00fabo", re.IGNORECASE)
_BASE_ALLOWLISTED = {Path("languages/base.py")}

_Span = tuple[int, int, int, int]  # (start_line, start_col, end_line, end_col)


def _is_language_package(rel: Path) -> bool:
    return len(rel.parts) > 1 and rel.parts[0] == "languages" and rel.parts[1] == "mzr"


def _is_fully_allowlisted(rel: Path) -> bool:
    return rel in _BASE_ALLOWLISTED


def _allows_help_strings(rel: Path) -> bool:
    return bool(rel.parts) and rel.parts[0] == "cli"


def _span(node: ast.expr) -> _Span:
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def _string_spans(tree: ast.AST) -> list[_Span]:
    """Spans of literal help strings (``help=`` constant strings) and docstrings."""
    spans: list[_Span] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "help"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            spans.append(_span(node.value))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            first = body[0].value if body and isinstance(body[0], ast.Expr) else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                spans.append(_span(first))
    return spans


def _line_byte_offsets(source_bytes: bytes) -> list[int]:
    offsets = [0]
    for line in source_bytes.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _blank(source: str, spans: list[_Span]) -> str:
    raw_bytes = bytearray(source.encode("utf-8"))
    offsets = _line_byte_offsets(bytes(raw_bytes))
    for start_line, start_col, end_line, end_col in spans:
        start = offsets[start_line - 1] + start_col
        end = offsets[end_line - 1] + end_col
        for index in range(start, min(end, len(raw_bytes))):
            if raw_bytes[index] not in b"\r\n":
                raw_bytes[index] = ord(" ")
    return raw_bytes.decode("utf-8", errors="replace")


def _language_offenders(source: str, *, allow_help_strings: bool) -> list[str]:
    """Return language-name matches not permitted by the isolation rule.

    ``allow_help_strings`` permits matches inside CLI help/docstring strings; matches in code and
    any other string literal are always returned.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _PATTERN.findall(source)
    spans = _string_spans(tree) if allow_help_strings else []
    return _PATTERN.findall(_blank(source, spans))


def test_language_isolation() -> None:
    offenders = [
        rel.as_posix()
        for path in sorted(_SRC.rglob("*.py"))
        if not _is_language_package(rel := path.relative_to(_SRC))
        and not _is_fully_allowlisted(rel)
        and _language_offenders(
            path.read_text(encoding="utf-8"),
            allow_help_strings=_allows_help_strings(rel),
        )
    ]

    assert offenders == []


def test_scanner_allows_cli_help_string() -> None:
    source = (
        "import typer\n"
        "\n"
        "\n"
        "def cmd() -> None:\n"
        '    """Marubo profile commands."""\n'
        "    ...\n"
        "\n"
        "\n"
        'OPTION = typer.Option("x", help="Pick the Marubo profile")\n'
    )

    assert _language_offenders(source, allow_help_strings=True) == []


def test_scanner_rejects_language_specific_conditional() -> None:
    source = (
        "def resolve(language: str) -> int:\n"
        '    if language == "mzr":\n'
        "        return 1\n"
        "    return 0\n"
    )

    assert _language_offenders(source, allow_help_strings=True) != []


def test_scanner_rejects_language_specific_import() -> None:
    source = "from langpipe.languages.mzr.profile import MZR_PROFILE\n"

    assert _language_offenders(source, allow_help_strings=True) != []


def test_scanner_rejects_help_string_when_not_allowed() -> None:
    source = 'OPTION = typer.Option("x", help="Pick the Marubo profile")\n'

    assert _language_offenders(source, allow_help_strings=False) != []


def test_scanner_rejects_fstring_interpolation_in_help() -> None:
    source = 'OPTION = typer.Option("x", help=f"{resolve(\'mzr\')}")\n'

    assert _language_offenders(source, allow_help_strings=True) == ["mzr"]


def test_scanner_handles_non_ascii_help_with_trailing_code() -> None:
    source = 'OPTION = typer.Option("x", help="' + "ú" * 20 + '"); language = "mzr"\n'

    assert _language_offenders(source, allow_help_strings=True) == ["mzr"]


def test_scanner_allows_non_ascii_help_alone() -> None:
    source = 'OPTION = typer.Option("x", help="' + "ú" * 20 + ' Marubo")\n'

    assert _language_offenders(source, allow_help_strings=True) == []
