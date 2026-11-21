"""CLI contract tests for the lexicon commands (WP4.7)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.enums import Operation, PolicyDecision
from langpipe.domain.errors import LangpipeError, PolicyDenied
from langpipe.domain.ids import new_id
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore


@pytest.fixture
def cli_ctx(tmp_path: Path) -> Iterator[AppContext]:
    context = AppContext(
        repo=InMemoryRepository(),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )
    set_context_factory(lambda: context)
    yield context
    reset_context_factory()


def test_induce_help(cli_ctx: AppContext) -> None:
    result = CliRunner().invoke(app, ["lexicon", "induce", "--help"])
    assert result.exit_code == 0, result.output
    assert "--run-id" in result.output
    assert "--method" in result.output
    assert "--target-language" in result.output
    assert "--contact-language" in result.output


def test_induce_success(cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.lexicon as command

    seen: dict[str, object] = {}

    class Service:
        def __init__(self, _ctx: object) -> None:
            pass

        def induce_lexicon(
            self,
            run_id: str,
            *,
            method: str,
            target_language: str | None,
            contact_language: str | None,
        ) -> object:
            seen.update(
                run_id=run_id,
                method=method,
                target_language=target_language,
                contact_language=contact_language,
            )
            return SimpleNamespace(
                run=SimpleNamespace(id="run_result"),
                lexemes=2,
                senses=3,
                evidence_items=6,
                reused=True,
                status_counts={"candidate": 4, "supported": 1},
            )

    monkeypatch.setattr(command, "LexicalService", Service)
    result = CliRunner().invoke(
        app,
        [
            "lexicon",
            "induce",
            "--run-id",
            "run_input",
            "--method",
            "wordlist_tabular@0.1.0",
            "--target-language",
            "qaa",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == {
        "run_id": "run_input",
        "method": "wordlist_tabular@0.1.0",
        "target_language": "qaa",
        "contact_language": None,
    }
    assert result.stdout.strip() == (
        "run_id=run_result lexemes=2 senses=3 evidence_items=6 reused=true candidate=4 supported=1"
    )


def test_induce_default_method(cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.lexicon as command

    seen: dict[str, object] = {}

    class Service:
        def __init__(self, _ctx: object) -> None:
            pass

        def induce_lexicon(self, run_id: str, **kwargs: object) -> object:
            seen.update(kwargs)
            return SimpleNamespace(
                run=SimpleNamespace(id="run_result"),
                lexemes=0,
                senses=0,
                evidence_items=0,
                reused=False,
                status_counts={},
            )

    monkeypatch.setattr(command, "LexicalService", Service)
    result = CliRunner().invoke(app, ["lexicon", "induce", "--run-id", "run_input"])
    assert result.exit_code == 0, result.output
    assert seen == {
        "method": "alignment_cooccurrence@0.1.0",
        "target_language": None,
        "contact_language": None,
    }
    assert result.stdout.strip() == (
        "run_id=run_result lexemes=0 senses=0 evidence_items=0 reused=false"
    )


def test_induce_failure_diagnostics(cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.lexicon as command

    class Service:
        def __init__(self, _ctx: object) -> None:
            pass

        def induce_lexicon(self, _run_id: str, **_kwargs: object) -> object:
            raise PolicyDenied("src_hidden", Operation.DISTILL_LEXICON, PolicyDecision.DENY)

    monkeypatch.setattr(command, "LexicalService", Service)
    result = CliRunner().invoke(app, ["lexicon", "induce", "--run-id", "run_input"])
    assert result.exit_code == 3
    assert result.stderr.strip() == "error=PolicyDenied"


def test_induce_unexpected_error_is_redacted(
    cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import langpipe.cli.lexicon as command

    class Service:
        def __init__(self, _ctx: object) -> None:
            pass

        def induce_lexicon(self, _run_id: str, **_kwargs: object) -> object:
            raise RuntimeError("SECRET-LEXICON-CONTENT")

    monkeypatch.setattr(command, "LexicalService", Service)
    result = CliRunner().invoke(app, ["lexicon", "induce", "--run-id", "run_input"])
    assert result.exit_code == LangpipeError.exit_code
    assert "SECRET-LEXICON-CONTENT" not in result.stdout + result.stderr
    assert result.stderr.strip() == "error=LangpipeError"
