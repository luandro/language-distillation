"""`langpipe synth export` argument and failure handling (ADR-0025 traceability)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from langpipe.cli.app import app


def test_malformed_source_index_exits_with_code_2(tmp_path: Path) -> None:
    index = tmp_path / "index.json"
    index.write_text("[1, 2, 3]", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "synth",
            "export",
            "--lang",
            "mzr",
            "--output",
            str(tmp_path / "out"),
            "--source-index",
            str(index),
        ],
    )

    assert result.exit_code == 2
    assert "must be an object" in result.output
