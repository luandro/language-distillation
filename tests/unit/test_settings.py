import dataclasses
import getpass
import subprocess
from pathlib import Path

import pytest

from langpipe.config import Settings, code_revision
from langpipe.config import revision as revision_module


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: "tester")
    settings = Settings.from_env({})
    assert settings.database_url == (
        "postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe"
    )
    assert settings.data_dir == Path("var")
    assert settings.actor == "tester"
    assert settings.log_level == "INFO"
    assert settings.raw_dir == Path("var") / "raw"
    assert settings.artifact_dir == Path("var") / "artifacts"


def test_default_actor_falls_back_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_user() -> str:
        raise OSError("no login name")

    monkeypatch.setattr(getpass, "getuser", _no_user)
    assert Settings.from_env({}).actor == "unknown"


def test_env_overrides() -> None:
    env = {
        "LANGPIPE_DATABASE_URL": "postgresql+psycopg://u:p@db:5432/other",
        "LANGPIPE_DATA_DIR": "/srv/langpipe",
        "LANGPIPE_ACTOR": "linguist-1",
        "LANGPIPE_LOG_LEVEL": "DEBUG",
    }
    settings = Settings.from_env(env)
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/other"
    assert settings.data_dir == Path("/srv/langpipe")
    assert settings.actor == "linguist-1"
    assert settings.log_level == "DEBUG"
    assert settings.raw_dir == Path("/srv/langpipe/raw")
    assert settings.artifact_dir == Path("/srv/langpipe/artifacts")


def test_empty_env_value_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: "tester")
    settings = Settings.from_env({"LANGPIPE_ACTOR": "", "LANGPIPE_LOG_LEVEL": ""})
    assert settings.actor == "tester"
    assert settings.log_level == "INFO"


def test_settings_is_frozen() -> None:
    settings = Settings.from_env({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.actor = "someone-else"  # type: ignore[misc]


def test_code_revision_prefers_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGPIPE_CODE_REVISION", "abc123def456")

    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("git must not be called when env override is set")

    monkeypatch.setattr(revision_module.subprocess, "run", _fail)
    assert code_revision() == "abc123def456"


def test_code_revision_uses_git_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGPIPE_CODE_REVISION", raising=False)
    calls: list[tuple[object, dict[str, object]]] = []

    def _fake_run(args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="0123456789ab\n", stderr="")

    monkeypatch.setattr(revision_module.subprocess, "run", _fake_run)
    assert code_revision() == "0123456789ab"
    args, kwargs = calls[0]
    assert args == ["git", "rev-parse", "--short=12", "HEAD"]
    assert kwargs.get("shell") is not True
    assert kwargs.get("timeout") == 2
    assert kwargs.get("cwd") == Path(revision_module.__file__).resolve().parent


@pytest.mark.parametrize("failure", ["nonzero", "oserror", "timeout"])
def test_code_revision_falls_back_to_unknown(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    monkeypatch.delenv("LANGPIPE_CODE_REVISION", raising=False)

    def _fake_run(args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if failure == "nonzero":
            return subprocess.CompletedProcess(args, 128, stdout="", stderr="not a repo")
        if failure == "oserror":
            raise OSError("git not installed")
        raise subprocess.TimeoutExpired(cmd="git", timeout=2)

    monkeypatch.setattr(revision_module.subprocess, "run", _fake_run)
    assert code_revision() == "unknown"
