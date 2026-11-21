"""CLI tests for source approve and withdraw-approval commands (WP5.5)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from langpipe.app_context import AppContext
from langpipe.cli.app import app
from langpipe.cli.context import reset_context_factory, set_context_factory
from langpipe.domain.enums import PolicyMode, RunStage, RunStatus
from langpipe.domain.ids import new_id
from langpipe.languages import base as languages_base
from langpipe.languages.base import LanguageProfile, ReviewAuthorityGrant
from langpipe.review.authority import ROLE_GOVERNANCE_STEWARD
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from tests.contract.builders import NOW, make_policy, make_run, make_source


@pytest.fixture
def cli_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppContext]:
    profile = LanguageProfile(
        "mzr",
        "test_profile",
        "0.1.0",
        "default_text@0.1.0",
        "whitespace_punct@0.1.0",
        review_authority=(
            ReviewAuthorityGrant(
                reviewer_id="steward-1",
                role=ROLE_GOVERNANCE_STEWARD,
                languages=("mzr",),
            ),
        ),
    )
    monkeypatch.setattr(languages_base, "LANGUAGE_PROFILES", {"mzr": profile})

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


def _create_source(ctx: AppContext, key: str = "test-source") -> str:
    reg_run = make_run(
        stage=RunStage.SOURCE_REGISTRATION, status=RunStatus.SUCCEEDED, finished_at=NOW
    )
    policy = make_policy(mode=PolicyMode.REVIEW_REQUIRED)
    source = make_source(policy, reg_run.id, key=key, languages=("mzr",))
    with ctx.repo.transaction():
        ctx.repo.add_run(reg_run)
        ctx.repo.add_policy(policy)
        ctx.repo.add_source(source)
    return source.id


def test_cli_source_approve_and_withdraw(cli_ctx: AppContext) -> None:
    runner = CliRunner()
    source_id = _create_source(cli_ctx, "igt-source")

    # 1. Approve
    result = runner.invoke(
        app,
        [
            "source",
            "approve",
            "--source",
            "igt-source",
            "--operation",
            "extract",
            "--approver",
            "steward-1",
            "--basis",
            "Approved for extraction",
        ],
    )
    assert result.exit_code == 0, result.output
    assert f"source_id={source_id} operation=extract action=grant" in result.output
    assert "approval_id=" in result.output

    # 2. Check source show
    show_result = runner.invoke(app, ["source", "show", "igt-source"])
    assert show_result.exit_code == 0, show_result.output
    show_json = json.loads(show_result.output)
    assert "extract" in show_json["effective_approved_operations"]

    # 3. Withdraw
    withdraw_result = runner.invoke(
        app,
        [
            "source",
            "withdraw-approval",
            "--source",
            "igt-source",
            "--operation",
            "extract",
            "--approver",
            "steward-1",
            "--basis",
            "Withdrawn per steward",
        ],
    )
    assert withdraw_result.exit_code == 0, withdraw_result.output
    assert f"source_id={source_id} operation=extract action=withdraw" in withdraw_result.output

    # 4. Check source show after withdraw
    show_result2 = runner.invoke(app, ["source", "show", "igt-source"])
    assert show_result2.exit_code == 0
    show_json2 = json.loads(show_result2.output)
    assert "extract" not in show_json2["effective_approved_operations"]


def test_cli_source_approve_unauthorized_fails(cli_ctx: AppContext) -> None:
    runner = CliRunner()
    _create_source(cli_ctx, "igt-source")

    result = runner.invoke(
        app,
        [
            "source",
            "approve",
            "--source",
            "igt-source",
            "--operation",
            "extract",
            "--approver",
            "unregistered-user",
            "--basis",
            "No authority",
        ],
    )
    assert result.exit_code != 0
