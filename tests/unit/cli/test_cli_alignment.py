"""CLI contract tests for the alignment commands (WP3.10)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.enums import Operation, PolicyDecision, RunStage, RunStatus, Symmetrization
from langpipe.domain.errors import (
    AlignmentFailed,
    AmbiguousInput,
    InvalidLineage,
    LangpipeError,
    PolicyDenied,
)
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


def _fields(line: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line.split())


def test_alignment_command_help() -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["align", "--help"]).exit_code == 0
    assert runner.invoke(app, ["align", "segments", "--help"]).exit_code == 0
    assert runner.invoke(app, ["align", "tokens", "--help"]).exit_code == 0


def test_bare_segment_method_resolves_registered_version() -> None:
    from langpipe.alignment.registry import SEGMENT_ALIGNERS, resolve_aligner

    aligner = resolve_aligner(SEGMENT_ALIGNERS, "canonical_locator")
    assert f"{aligner.name}@{aligner.version}" == "canonical_locator@0.1.0"


def test_bare_token_method_matches_registered_version() -> None:
    from langpipe.alignment.registry import TOKEN_ALIGNERS

    aligner = TOKEN_ALIGNERS.get("eflomal")
    assert f"{aligner.name}@{aligner.version}" == "eflomal@0.1.0"


def test_segments_default_method_and_success_format(
    cli_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    import langpipe.cli.alignment as command

    source = SimpleNamespace(source_id="src_a", language="mzr", normalization_run_id="run_a")
    target = SimpleNamespace(source_id="src_a", language="por", normalization_run_id="run_b")
    seen = {}

    def resolve(_ctx, _ref, language, norm, token):
        assert token is None
        return source if language == "mzr" else target

    class Service:
        def __init__(self, _ctx):
            pass

        def align(self, a, b, *, method, config):
            seen.update(method=method, source=a, target=b, config=config)
            return SimpleNamespace(
                run=SimpleNamespace(id="run_result"),
                report=SimpleNamespace(id="artifact_report"),
                alignments=2,
                unmatched_source=1,
                unmatched_target=3,
                reused=True,
            )

    monkeypatch.setattr(command, "resolve_alignment_side", resolve)
    monkeypatch.setattr(command, "SegmentAlignmentService", Service)
    result = CliRunner().invoke(
        app,
        [
            "align",
            "segments",
            "bilingual",
            "bilingual",
            "--source-language",
            "mzr",
            "--target-language",
            "por",
            "--namespace",
            "refs",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen["method"] == "canonical_locator@0.1.0"
    assert result.stdout.strip() == (
        "run_id=run_result report_id=artifact_report alignments=2 unmatched_source=1 "
        "unmatched_target=3 reused=true"
    )


def test_segments_pinned_versioned_method(cli_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.alignment as command

    seen = {}
    monkeypatch.setattr(
        command,
        "resolve_alignment_side",
        lambda *args: SimpleNamespace(source_id="src", language="mzr", normalization_run_id="run"),
    )

    class Service:
        def __init__(self, _ctx):
            pass

        def align(self, *_args, method, config):
            seen["method"] = method
            seen["namespace"] = config.namespace
            return SimpleNamespace(
                run=SimpleNamespace(id="r"),
                report=None,
                alignments=0,
                unmatched_source=0,
                unmatched_target=0,
                reused=False,
            )

    monkeypatch.setattr(command, "SegmentAlignmentService", Service)
    result = CliRunner().invoke(
        app, ["align", "segments", "a", "b", "--namespace", "tsv", "--method", "fixture@9.1.0"]
    )
    assert result.exit_code == 0, result.output
    assert seen == {"method": "fixture@9.1.0", "namespace": "tsv"}


def test_scripture_requires_versification(cli_ctx) -> None:
    result = CliRunner().invoke(app, ["align", "segments", "a", "b", "--namespace", "scripture"])
    assert result.exit_code == 12
    assert result.stderr.strip() == "error=AlignmentFailed"


def test_segment_seed_is_rejected_before_context_or_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import langpipe.cli.alignment as command

    monkeypatch.setattr(command, "get_context", lambda: pytest.fail("context must not be created"))
    result = CliRunner().invoke(
        app, ["align", "segments", "a", "b", "--namespace", "refs", "--seed", "5"]
    )
    assert result.exit_code == 12
    assert result.stderr.strip() == "error=AlignmentFailed"


@pytest.mark.parametrize(
    ("failure", "exit_code", "diagnostic"),
    [
        (AlignmentFailed("backend_failed"), 12, "error=AlignmentFailed"),
        (RuntimeError("SECRET-ALIGNMENT-CONTENT"), LangpipeError.exit_code, "error=LangpipeError"),
    ],
)
def test_backend_failure_is_redacted(
    cli_ctx, monkeypatch: pytest.MonkeyPatch, failure: Exception, exit_code: int, diagnostic: str
) -> None:
    import langpipe.cli.alignment as command

    monkeypatch.setattr(command, "resolve_alignment_side", lambda *args: object())

    class Service:
        def __init__(self, _ctx):
            pass

        def align(self, *_args, **_kwargs):
            raise failure

    monkeypatch.setattr(command, "SegmentAlignmentService", Service)
    result = CliRunner().invoke(app, ["align", "segments", "a", "b", "--namespace", "refs"])
    assert result.exit_code == exit_code
    assert "SECRET-ALIGNMENT-CONTENT" not in result.stdout + result.stderr
    assert result.stderr.strip() == diagnostic


def test_alignment_error_codes_are_preserved(cli_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.alignment as command

    monkeypatch.setattr(
        command,
        "resolve_alignment_side",
        lambda *args: (_ for _ in ()).throw(AlignmentFailed("invalid_adapter_output")),
    )
    result = CliRunner().invoke(app, ["align", "segments", "a", "b", "--namespace", "refs"])
    assert result.exit_code == 12
    assert result.stderr.strip() == "error=AlignmentFailed"


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (AmbiguousInput(RunStage.NORMALIZATION, 2), 11),
        (PolicyDenied("src_hidden", Operation.ALIGN, PolicyDecision.DENY), 3),
    ],
)
def test_selection_and_governance_errors_keep_exit_codes(
    cli_ctx, monkeypatch: pytest.MonkeyPatch, error: Exception, exit_code: int
) -> None:
    import langpipe.cli.alignment as command

    def fail(*_args):
        raise error

    monkeypatch.setattr(command, "resolve_alignment_side", fail)
    result = CliRunner().invoke(app, ["align", "segments", "a", "b", "--namespace", "refs"])
    assert result.exit_code == exit_code
    assert "src_hidden" not in result.stdout + result.stderr


def test_tokens_default_method_and_success_format(cli_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.alignment as command
    from langpipe.domain.enums import RunStatus

    segment_run = SimpleNamespace(
        id="run_seg",
        stage=RunStage.SEGMENT_ALIGNMENT,
        status=RunStatus.SUCCEEDED,
        config={
            "sides": [
                {"normalization_run_id": "norm_a"},
                {"normalization_run_id": "norm_b"},
            ],
            "namespace": "scripture",
            "versification_id": "eng",
        },
    )
    seen = {}

    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda run_id: segment_run)
    monkeypatch.setattr(
        command,
        "_unique_tokenization_run",
        lambda _ctx, norm_id: "tok_a" if norm_id == "norm_a" else "tok_b",
    )

    class Service:
        def __init__(self, _ctx):
            pass

        def align(
            self,
            segment_alignment_run_id,
            *,
            source_tokenization_run_id,
            target_tokenization_run_id,
            method,
            config,
        ):
            seen.update(
                segment_run_id=segment_alignment_run_id,
                source_tok=source_tokenization_run_id,
                target_tok=target_tokenization_run_id,
                method=method,
                config=config,
            )
            return SimpleNamespace(
                run=SimpleNamespace(id="run_token_res"),
                report=SimpleNamespace(id="artifact_token_rep"),
                edges=5,
                unaligned_source=2,
                unaligned_target=1,
                skipped_groups=0,
                reused=False,
            )

    monkeypatch.setattr(command, "TokenAlignmentService", Service)
    result = CliRunner().invoke(app, ["align", "tokens", "run_seg"])
    assert result.exit_code == 0, result.output
    assert seen["method"] == "eflomal@0.1.0"
    assert seen["source_tok"] == "tok_a"
    assert seen["target_tok"] == "tok_b"
    assert seen["config"].namespace == "scripture"
    assert seen["config"].versification_id == "eng"
    assert result.stdout.strip() == (
        "run_id=run_token_res report_id=artifact_token_rep edges=5 unaligned_source=2 "
        "unaligned_target=1 skipped_groups=0 reused=false"
    )


def test_tokens_forwards_symmetrization(cli_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.alignment as command

    segment_run = SimpleNamespace(
        id="run_seg",
        stage=RunStage.SEGMENT_ALIGNMENT,
        status=RunStatus.SUCCEEDED,
        config={
            "sides": [{"normalization_run_id": "a"}, {"normalization_run_id": "b"}],
            "namespace": "refs",
            "versification_id": None,
        },
    )
    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda _id: segment_run)
    monkeypatch.setattr(command, "_unique_tokenization_run", lambda *_args: "tok")
    seen = {}

    class Service:
        def __init__(self, _ctx):
            pass

        def align(self, *_args, config, **_kwargs):
            seen["symmetrization"] = config.symmetrization
            return SimpleNamespace(
                run=SimpleNamespace(id="r"),
                report=SimpleNamespace(id="a"),
                edges=0,
                unaligned_source=0,
                unaligned_target=0,
                skipped_groups=0,
                reused=False,
            )

    monkeypatch.setattr(command, "TokenAlignmentService", Service)
    result = CliRunner().invoke(app, ["align", "tokens", "run_seg", "--symmetrization", "union"])
    assert result.exit_code == 0, result.output
    assert seen["symmetrization"] is Symmetrization.UNION


def test_invalid_symmetrization_is_usage_error(cli_ctx) -> None:
    result = CliRunner().invoke(
        app, ["align", "tokens", "run_seg", "--symmetrization", "grow_diag_final"]
    )
    assert result.exit_code == 2


@pytest.mark.parametrize(
    ("failure", "exit_code", "diagnostic"),
    [
        (AlignmentFailed("backend_failed"), 12, "error=AlignmentFailed"),
        (RuntimeError("SECRET-TOKEN-PAYLOAD"), LangpipeError.exit_code, "error=LangpipeError"),
    ],
)
def test_tokens_backend_failure_is_redacted(
    cli_ctx, monkeypatch: pytest.MonkeyPatch, failure: Exception, exit_code: int, diagnostic: str
) -> None:
    import langpipe.cli.alignment as command
    from langpipe.domain.enums import RunStatus

    segment_run = SimpleNamespace(
        id="run_seg",
        stage=RunStage.SEGMENT_ALIGNMENT,
        status=RunStatus.SUCCEEDED,
        config={
            "sides": [
                {"normalization_run_id": "norm_a"},
                {"normalization_run_id": "norm_b"},
            ],
            "namespace": "refs",
            "versification_id": None,
        },
    )
    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda run_id: segment_run)
    monkeypatch.setattr(command, "_unique_tokenization_run", lambda *args: "tok_run")

    class Service:
        def __init__(self, _ctx):
            pass

        def align(self, *_args, **_kwargs):
            raise failure

    monkeypatch.setattr(command, "TokenAlignmentService", Service)
    result = CliRunner().invoke(app, ["align", "tokens", "run_seg"])
    assert result.exit_code == exit_code
    assert "SECRET-TOKEN-PAYLOAD" not in result.stdout + result.stderr
    assert result.stderr.strip() == diagnostic


def test_tokens_unsupported_seed_is_forwarded(cli_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.alignment as command

    segment_run = SimpleNamespace(
        id="run_seg",
        stage=RunStage.SEGMENT_ALIGNMENT,
        status=RunStatus.SUCCEEDED,
        config={
            "sides": [{"normalization_run_id": "a"}, {"normalization_run_id": "b"}],
            "namespace": "refs",
            "versification_id": None,
        },
    )
    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda _id: segment_run)
    monkeypatch.setattr(command, "_unique_tokenization_run", lambda *_args: "tok")
    seen = {}

    class Service:
        def __init__(self, _ctx):
            pass

        def align(self, *_args, config, **_kwargs):
            seen["seed"] = config.random_seed
            raise AlignmentFailed("unsupported_seed")

    monkeypatch.setattr(command, "TokenAlignmentService", Service)
    result = CliRunner().invoke(app, ["align", "tokens", "run_seg", "--seed", "5"])
    assert result.exit_code == 12
    assert result.stderr.strip() == "error=AlignmentFailed"
    assert seen["seed"] == 5


@pytest.mark.parametrize(
    "segment_run",
    [
        SimpleNamespace(stage=RunStage.NORMALIZATION, status=RunStatus.SUCCEEDED, config={}),
        SimpleNamespace(stage=RunStage.SEGMENT_ALIGNMENT, status=RunStatus.FAILED, config={}),
    ],
)
def test_tokens_requires_succeeded_segment_alignment_run(cli_ctx, monkeypatch, segment_run) -> None:
    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda _id: segment_run)
    result = CliRunner().invoke(app, ["align", "tokens", "run_bad"])
    assert result.exit_code == InvalidLineage.exit_code
    assert result.stderr.strip() == "error=InvalidLineage"


@pytest.mark.parametrize("namespace", [None, ""])
def test_tokens_rejects_missing_namespace(cli_ctx, monkeypatch, namespace) -> None:
    segment_run = SimpleNamespace(
        stage=RunStage.SEGMENT_ALIGNMENT,
        status=RunStatus.SUCCEEDED,
        config={
            "sides": [{"normalization_run_id": "a"}, {"normalization_run_id": "b"}],
            "namespace": namespace,
            "versification_id": None,
        },
    )
    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda _id: segment_run)
    result = CliRunner().invoke(app, ["align", "tokens", "run_bad"])
    assert result.exit_code == InvalidLineage.exit_code


@pytest.mark.parametrize("versification", ["missing", 42])
def test_tokens_rejects_malformed_versification(cli_ctx, monkeypatch, versification) -> None:
    config = {
        "sides": [{"normalization_run_id": "a"}, {"normalization_run_id": "b"}],
        "namespace": "refs",
    }
    if versification != "missing":
        config["versification_id"] = versification
    segment_run = SimpleNamespace(
        stage=RunStage.SEGMENT_ALIGNMENT,
        status=RunStatus.SUCCEEDED,
        config=config,
    )
    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda _id: segment_run)
    result = CliRunner().invoke(app, ["align", "tokens", "run_bad"])
    assert result.exit_code == InvalidLineage.exit_code


def test_tokens_missing_tokenization_exit_12(cli_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.alignment as command
    from langpipe.domain.enums import RunStatus

    segment_run = SimpleNamespace(
        id="run_seg",
        stage=RunStage.SEGMENT_ALIGNMENT,
        status=RunStatus.SUCCEEDED,
        config={
            "sides": [
                {"normalization_run_id": "norm_a"},
                {"normalization_run_id": "norm_b"},
            ],
            "namespace": "refs",
            "versification_id": None,
        },
    )
    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda run_id: segment_run)
    monkeypatch.setattr(
        command,
        "_unique_tokenization_run",
        lambda *args: (_ for _ in ()).throw(AlignmentFailed("missing_tokenization")),
    )
    result = CliRunner().invoke(app, ["align", "tokens", "run_seg"])
    assert result.exit_code == 12
    assert result.stderr.strip() == "error=AlignmentFailed"


def test_tokens_ambiguous_tokenization_exit_11(cli_ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.alignment as command
    from langpipe.domain.enums import RunStatus

    segment_run = SimpleNamespace(
        id="run_seg",
        stage=RunStage.SEGMENT_ALIGNMENT,
        status=RunStatus.SUCCEEDED,
        config={
            "sides": [
                {"normalization_run_id": "norm_a"},
                {"normalization_run_id": "norm_b"},
            ],
            "namespace": "refs",
            "versification_id": None,
        },
    )
    monkeypatch.setattr(cli_ctx.repo, "get_run", lambda run_id: segment_run)
    monkeypatch.setattr(
        command,
        "_unique_tokenization_run",
        lambda *args: (_ for _ in ()).throw(AmbiguousInput(RunStage.TOKENIZATION, 3)),
    )
    result = CliRunner().invoke(app, ["align", "tokens", "run_seg"])
    assert result.exit_code == 11
    assert result.stderr.strip() == "error=AmbiguousInput"
