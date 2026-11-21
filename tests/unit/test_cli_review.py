"""CLI contract tests for the review commands (WP4.8).

Argument forwarding is pinned with a replaced service; authority configuration is
pinned end to end: the CLI builds its registry from language profile configuration,
so an unconfigured identity is denied against the real service, and configured
language/domain boundaries hold.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.enums import (
    EntityType,
    LifecycleStatus,
    LineageKind,
    ReviewDecisionKind,
    ReviewTaskType,
    RunStage,
)
from langpipe.domain.errors import LangpipeError
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.lexical import Lexeme
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.languages import base as languages_base
from langpipe.languages.base import LanguageProfile, ReviewAuthorityGrant
from langpipe.review.base import UnauthorizedReviewer
from langpipe.review.service import ReviewService
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from tests.service.manifests import manifest_data, write_manifest, write_origin_file

TASK_ID = "rtask_01H00000000000000000000000"
LANGUAGE = "mzr"


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


def _task(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "id": TASK_ID,
        "task_type": ReviewTaskType.LEXICAL_SENSE,
        "target_id": "lex_01H00000000000000000000000",
        "priority": 6.0,
        "required_role": "community_linguist",
        "reason": "Lexical candidate review",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _registered_source(ctx: AppContext, tmp_path: Path, key: str):
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, b"origin bytes\n")
    data = manifest_data(
        key=key, mode="direct", objects=[{"path": relative, "media_type": "text/plain"}]
    )
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _candidate_lexeme(ctx: AppContext, source_object_id: str, *, domain: str | None = None):
    run_id = (
        RunRecorder(ctx)
        .start(RunStage.LEXICAL_INDUCTION, "langpipe.test", {}, [source_object_id])
        .id
    )
    lexeme = Lexeme(
        id=ctx.new_id(IdPrefix.LEXEME),
        language=LANGUAGE,
        domain=domain,
        run_id=run_id,
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_lexeme(lexeme)
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=lexeme.id,
                to_id=source_object_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run_id,
                created_at=ctx.clock(),
            )
        )
    return lexeme


def test_review_list_help(cli_ctx: AppContext) -> None:
    result = CliRunner().invoke(app, ["review", "list", "--help"])
    assert result.exit_code == 0, result.output
    for option in ("--type", "--role", "--limit", "--status", "--min-priority", "--language"):
        assert option in result.output


def test_review_list_renders_queue(cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.review as command

    seen: dict[str, object] = {}

    class Service:
        def __init__(self, _repo: object, _registry: object, **_kwargs: object) -> None:
            pass

        def list_tasks(self, **kwargs: object) -> list[SimpleNamespace]:
            seen.update(kwargs)
            return [
                _task(),
                _task(
                    id="rtask_01H00000000000000000000001",
                    task_type=ReviewTaskType.GOVERNANCE_EXPORT,
                    priority=0.5,
                    required_role="editorial_steward",
                    reason="Export eligibility",
                ),
            ]

    monkeypatch.setattr(command, "ReviewService", Service)
    result = CliRunner().invoke(
        app,
        [
            "review",
            "list",
            "--type",
            "lexical_sense",
            "--role",
            "community_linguist",
            "--status",
            "open",
            "--min-priority",
            "2.5",
            "--language",
            "mzr",
            "--limit",
            "5",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == {
        "task_type": ReviewTaskType.LEXICAL_SENSE,
        "required_role": "community_linguist",
        "limit": 5,
        "status": "open",
        "min_priority": 2.5,
        "language": "mzr",
    }
    for column in ("ID", "Type", "Target", "Priority", "Role", "Reason"):
        assert column in result.stdout
    assert TASK_ID in result.stdout
    assert "lexical_sense" in result.stdout
    assert "6" in result.stdout
    assert "community_linguist" in result.stdout
    assert "rtask_01H00000000000000000000001" in result.stdout
    assert "governance_export" in result.stdout
    assert "editorial_steward" in result.stdout


def test_review_list_empty_queue_renders_header_only(
    cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import langpipe.cli.review as command

    class Service:
        def __init__(self, _repo: object, _registry: object, **_kwargs: object) -> None:
            pass

        def list_tasks(self, **_kwargs: object) -> list[SimpleNamespace]:
            return []

    monkeypatch.setattr(command, "ReviewService", Service)
    result = CliRunner().invoke(app, ["review", "list"])
    assert result.exit_code == 0, result.output
    assert "ID" in result.stdout


def test_review_decide_success(cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.review as command

    seen: dict[str, object] = {}

    class Service:
        def __init__(self, _repo: object, _registry: object, **_kwargs: object) -> None:
            pass

        def record_decision(
            self,
            task_id: str,
            decision: ReviewDecisionKind,
            reviewer_id: str,
            reviewer_role: str,
            superseding_object_id: str | None = None,
            notes: str | None = None,
        ) -> SimpleNamespace:
            seen.update(
                task_id=task_id,
                decision=decision,
                reviewer_id=reviewer_id,
                reviewer_role=reviewer_role,
                superseding_object_id=superseding_object_id,
                notes=notes,
            )
            return SimpleNamespace(
                decision=SimpleNamespace(id="rdec_01H00000000000000000000000"),
                target_status=LifecycleStatus.VALIDATED,
                task_status="resolved",
            )

    monkeypatch.setattr(command, "ReviewService", Service)
    result = CliRunner().invoke(
        app,
        [
            "review",
            "decide",
            "--task-id",
            TASK_ID,
            "--decision",
            "accept",
            "--reviewer",
            "linguist_1",
            "--role",
            "community_linguist",
            "--notes",
            "checked with speaker",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == {
        "task_id": TASK_ID,
        "decision": ReviewDecisionKind.ACCEPT,
        "reviewer_id": "linguist_1",
        "reviewer_role": "community_linguist",
        "superseding_object_id": None,
        "notes": "checked with speaker",
    }
    assert "rdec_01H00000000000000000000000" in result.stdout
    assert "accept" in result.stdout
    assert "validated" in result.stdout
    assert "resolved" in result.stdout


def test_review_decide_passes_superseding(
    cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import langpipe.cli.review as command

    seen: dict[str, object] = {}

    class Service:
        def __init__(self, _repo: object, _registry: object, **_kwargs: object) -> None:
            pass

        def record_decision(
            self,
            task_id: str,
            decision: ReviewDecisionKind,
            reviewer_id: str,
            reviewer_role: str,
            superseding_object_id: str | None = None,
            notes: str | None = None,
        ) -> SimpleNamespace:
            seen.update(
                task_id=task_id,
                decision=decision,
                reviewer_id=reviewer_id,
                reviewer_role=reviewer_role,
                superseding_object_id=superseding_object_id,
                notes=notes,
            )
            return SimpleNamespace(
                decision=SimpleNamespace(id="rdec_01H00000000000000000000002"),
                target_status=LifecycleStatus.DEPRECATED,
                task_status="resolved",
            )

    monkeypatch.setattr(command, "ReviewService", Service)
    result = CliRunner().invoke(
        app,
        [
            "review",
            "decide",
            "--task-id",
            TASK_ID,
            "--decision",
            "modify",
            "--reviewer",
            "linguist_1",
            "--role",
            "community_linguist",
            "--superseding",
            "lex_01H00000000000000000000009",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen["superseding_object_id"] == "lex_01H00000000000000000000009"
    assert seen["notes"] is None
    assert "deprecated" in result.stdout


def test_review_decide_unauthorized_diagnostics(
    cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import langpipe.cli.review as command

    class Service:
        def __init__(self, _repo: object, _registry: object, **_kwargs: object) -> None:
            pass

        def record_decision(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            raise UnauthorizedReviewer("stranger", "community_linguist", "mzr")

    monkeypatch.setattr(command, "ReviewService", Service)
    result = CliRunner().invoke(
        app,
        [
            "review",
            "decide",
            "--task-id",
            TASK_ID,
            "--decision",
            "accept",
            "--reviewer",
            "stranger",
            "--role",
            "community_linguist",
        ],
    )
    assert result.exit_code == UnauthorizedReviewer.exit_code
    assert result.stderr.strip() == "error=UnauthorizedReviewer"


def test_review_decide_unexpected_error_is_redacted(
    cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    import langpipe.cli.review as command

    class Service:
        def __init__(self, _repo: object, _registry: object, **_kwargs: object) -> None:
            pass

        def record_decision(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            raise RuntimeError("SECRET-REVIEW-CONTENT")

    monkeypatch.setattr(command, "ReviewService", Service)
    result = CliRunner().invoke(
        app,
        [
            "review",
            "decide",
            "--task-id",
            TASK_ID,
            "--decision",
            "accept",
            "--reviewer",
            "linguist_1",
            "--role",
            "community_linguist",
        ],
    )
    assert result.exit_code == LangpipeError.exit_code
    assert "SECRET-REVIEW-CONTENT" not in result.stdout + result.stderr
    assert result.stderr.strip() == "error=LangpipeError"


# --- end-to-end authority configuration (real service, profile-built registry) ------------------


def _configured_profiles() -> dict[str, LanguageProfile]:
    return {
        LANGUAGE: LanguageProfile(
            LANGUAGE,
            "test_profile",
            "0.1.0",
            "default_text@0.1.0",
            "whitespace_punct@0.1.0",
            review_authority=(
                ReviewAuthorityGrant(
                    reviewer_id="linguist_1", role="community_linguist", languages=(LANGUAGE,)
                ),
                ReviewAuthorityGrant(
                    reviewer_id="elder_1",
                    role="native_speaker_elder",
                    languages=(LANGUAGE,),
                    domains=("ritual",),
                ),
            ),
        )
    }


def _review_service(ctx: AppContext) -> ReviewService:
    from langpipe.review.authority import registry_from_profiles

    return ReviewService(
        ctx.repo,
        registry_from_profiles(),
        clock=ctx.clock,
        new_id=ctx.new_id,
        code_revision=ctx.code_revision,
    )


def _queue_task(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    *,
    required_role: str = "community_linguist",
    **lexeme_kwargs: object,
):
    """One governed candidate with a queue entry, built through the real service."""
    registered = _registered_source(ctx, tmp_path, key)
    lexeme = _candidate_lexeme(ctx, registered.objects[0].id, **lexeme_kwargs)  # type: ignore[arg-type]
    task = _review_service(ctx).create_task(lexeme.id, ReviewTaskType.LEMMA, required_role)
    return task, lexeme


def test_cli_decide_denies_unconfigured_identity_end_to_end(
    cli_ctx: AppContext, tmp_path: Path
) -> None:
    # The shipped profiles configure no reviewer authority at all: default deny.
    task, lexeme = _queue_task(cli_ctx, tmp_path, "cli-unconfigured-src")
    result = CliRunner().invoke(
        app,
        [
            "review",
            "decide",
            "--task-id",
            task.id,
            "--decision",
            "accept",
            "--reviewer",
            "linguist_1",
            "--role",
            "community_linguist",
        ],
    )
    assert result.exit_code == UnauthorizedReviewer.exit_code, result.output
    assert result.stderr.strip() == "error=UnauthorizedReviewer"
    assert cli_ctx.repo.count(EntityType.REVIEW_DECISION) == 0
    assert cli_ctx.repo.get_review_task(task.id).status == "open"
    assert cli_ctx.repo.get_lexeme(lexeme.id).status is LifecycleStatus.CANDIDATE


def test_cli_decide_honors_configured_language_and_domain_boundaries(
    cli_ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(languages_base, "LANGUAGE_PROFILES", _configured_profiles())
    untagged_task, untagged_lexeme = _queue_task(cli_ctx, tmp_path, "cli-configured-src")
    ritual_task, ritual_lexeme = _queue_task(
        cli_ctx,
        tmp_path,
        "cli-configured-ritual-src",
        required_role="native_speaker_elder",
        domain="ritual",
    )
    plain_task, plain_lexeme = _queue_task(cli_ctx, tmp_path, "cli-configured-plain-src")

    # The configured community linguist decides the untagged target through the CLI.
    ok = CliRunner().invoke(
        app,
        [
            "review",
            "decide",
            "--task-id",
            untagged_task.id,
            "--decision",
            "accept",
            "--reviewer",
            "linguist_1",
            "--role",
            "community_linguist",
        ],
    )
    assert ok.exit_code == 0, ok.output
    assert "validated" in ok.stdout
    assert cli_ctx.repo.get_lexeme(untagged_lexeme.id).status is LifecycleStatus.VALIDATED

    # The configured elder covers only the ritual domain: inside the boundary succeeds.
    elder_ok = CliRunner().invoke(
        app,
        [
            "review",
            "decide",
            "--task-id",
            ritual_task.id,
            "--decision",
            "accept",
            "--reviewer",
            "elder_1",
            "--role",
            "native_speaker_elder",
        ],
    )
    assert elder_ok.exit_code == 0, elder_ok.output
    assert cli_ctx.repo.get_lexeme(ritual_lexeme.id).status is LifecycleStatus.VALIDATED

    # Outside the configured boundary (untagged fails closed) is denied.
    denied = CliRunner().invoke(
        app,
        [
            "review",
            "decide",
            "--task-id",
            plain_task.id,
            "--decision",
            "accept",
            "--reviewer",
            "elder_1",
            "--role",
            "native_speaker_elder",
        ],
    )
    assert denied.exit_code == UnauthorizedReviewer.exit_code, denied.output
    assert denied.stderr.strip() == "error=UnauthorizedReviewer"
    assert cli_ctx.repo.get_lexeme(plain_lexeme.id).status is LifecycleStatus.CANDIDATE
    assert cli_ctx.repo.count(EntityType.REVIEW_DECISION) == 2


def test_review_recalc_arguments_validation(cli_ctx: AppContext) -> None:
    # Neither --object nor --all-stale
    res1 = CliRunner().invoke(app, ["review", "recalc"])
    assert res1.exit_code != 0
    assert "error=" in res1.stderr

    # Both --object and --all-stale
    res2 = CliRunner().invoke(app, ["review", "recalc", "--all-stale", "--object", "sense_01"])
    assert res2.exit_code != 0
    assert "error=" in res2.stderr


def test_review_recalc_success(cli_ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    import langpipe.cli.review as command
    from langpipe.review.recalc import RecalcResult

    called_kwargs: dict[str, object] = {}

    class DummyRecalc:
        def __init__(self, target: object, **_kwargs: object) -> None:
            pass

        def recalculate(self, **kwargs: object) -> RecalcResult:
            called_kwargs.update(kwargs)
            return RecalcResult(
                run=SimpleNamespace(id="run_01H00000000000000000000000"),  # type: ignore[arg-type]
                recalculated_ids=("sense_01",),
                skipped_ids=(),
            )

    monkeypatch.setattr(command, "RecalcService", DummyRecalc)
    result = CliRunner().invoke(app, ["review", "recalc", "--all-stale"])
    assert result.exit_code == 0, result.output
    assert called_kwargs == {"object_ids": None, "all_stale": True}
    assert "recalculated sense_01" in result.stdout
    assert "run_id=run_01H00000000000000000000000" in result.stdout
