"""scripts/ci.sh must refuse to run Alembic against any database not named *_test.

`uv`, `docker` are replaced by logging stubs on PATH. The only real call allowed is
the guard's own `uv run python -` (SQLAlchemy URL parsing, no connection). Nothing
here opens a database connection or migrates anything.
"""

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPT = REPO_ROOT / "scripts" / "ci.sh"
PYPROJECT = REPO_ROOT / "pyproject.toml"
SECRET = "hunter2-secret"
TEST_URL = "postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe_test"

UV_STUB = """#!/usr/bin/env bash
echo "uv $*" >> "$CI_CALL_LOG"
if [ "$1" = run ] && [ "$2" = python ] && [ "$3" = - ]; then
  exec "$REAL_UV" "$@"
fi
exit 0
"""

DOCKER_STUB = """#!/usr/bin/env bash
echo "docker $*" >> "$CI_CALL_LOG"
exit 0
"""

# Fails only the non-blocking whole-repo lint report; every other uv call succeeds.
REST_LINT_FAILS_UV_STUB = """#!/usr/bin/env bash
echo "uv $*" >> "$CI_CALL_LOG"
if [ "$1" = run ] && [ "$2" = ruff ] && [ "$3" = check ] && [ "$4" = . ]; then
  echo "src/langpipe/example.py:1:1: E501 simulated finding" >&2
  exit 1
fi
if [ "$1" = run ] && [ "$2" = python ] && [ "$3" = - ]; then
  exec "$REAL_UV" "$@"
fi
exit 0
"""

# Fails the blocking lint tier; the gate must stop before any database or test work.
BLOCKING_LINT_FAILS_UV_STUB = """#!/usr/bin/env bash
echo "uv $*" >> "$CI_CALL_LOG"
if [ "$1" = run ] && [ "$2" = ruff ] && [ "$3" = check ] && [ "$4" = src ]; then
  echo "src/langpipe/example.py:1:1: E501 simulated finding" >&2
  exit 1
fi
if [ "$1" = run ] && [ "$2" = python ] && [ "$3" = - ]; then
  exec "$REAL_UV" "$@"
fi
exit 0
"""


def _write_stubs(tmp_path: Path, uv_body: str) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("uv", uv_body), ("docker", DOCKER_STUB)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    return bin_dir, tmp_path / "calls.log"


@pytest.fixture
def stubbed_ci(tmp_path: Path) -> tuple[Path, Path]:
    return _write_stubs(tmp_path, UV_STUB)


def _run_ci(bin_dir: Path, log: Path, database_url: str) -> subprocess.CompletedProcess[str]:
    real_uv = shutil.which("uv")
    assert real_uv is not None
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "REAL_UV": real_uv,
        "CI_CALL_LOG": str(log),
        "LANGPIPE_TEST_DATABASE_URL": database_url,
    }
    return subprocess.run(
        ["bash", str(CI_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _calls(log: Path) -> str:
    return log.read_text() if log.exists() else ""


def _pytest_invocations(content: str) -> list[list[str]]:
    """Tokenized ci.sh lines whose command invokes ``pytest`` (inline comments dropped)."""
    invocations: list[list[str]] = []
    for raw in content.splitlines():
        words: list[str] = []
        for word in raw.split():
            if word.startswith("#"):
                break
            words.append(word)
        if "pytest" in words:
            invocations.append(words)
    return invocations


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://langpipe:hunter2-secret@localhost:55432/langpipe",
        "postgresql+psycopg://langpipe:hunter2-secret@localhost:55432/langpipe_test"
        "?dbname=langpipe",
        "postgresql+psycopg://langpipe:hunter2-secret@localhost:55432/langpipe_test"
        "?database=langpipe",
        "postgresql+psycopg://langpipe:hunter2-secret@localhost:55432/langpipe_test?service=app",
        "not a url hunter2-secret",
        "postgresql+psycopg://langpipe:hunter2-secret@localhost:notaport/langpipe_test",
    ],
    ids=[
        "application-db",
        "dbname-query",
        "database-query",
        "service-query",
        "malformed",
        "bad-port",
    ],
)
def test_ci_refuses_non_test_database_before_migrating(
    stubbed_ci: tuple[Path, Path], database_url: str
) -> None:
    bin_dir, log = stubbed_ci
    result = _run_ci(bin_dir, log, database_url)
    calls = _calls(log)

    assert result.returncode != 0
    assert "alembic" not in calls
    assert "docker" not in calls
    assert "_test" in result.stderr
    output = result.stdout + result.stderr
    assert SECRET not in output
    assert "localhost" not in output


def test_ci_migrates_test_database_when_guard_passes(stubbed_ci: tuple[Path, Path]) -> None:
    bin_dir, log = stubbed_ci
    result = _run_ci(bin_dir, log, TEST_URL)
    calls = _calls(log)

    assert result.returncode == 0, result.stderr
    assert "alembic -x url=" in calls
    assert "docker compose up -d --wait db" in calls
    # Full gate order (WP4.12): quality gates first, the URL refusal guard before any
    # docker work, migrations before the test pass. The alembic line carries the test
    # database URL, so it is matched by prefix and suffix instead of exactly.
    expected_exact = (
        "uv sync --frozen",
        "uv run python -",
        "uv run ruff check src tests",
        "uv run ruff format --check src tests",
        "uv run ruff check . --exclude src --exclude tests",
        "uv run ruff format --check . --exclude src --exclude tests",
        "uv run mypy src",
        "uv run python -m langpipe.schemas check",
        "docker compose up -d --wait db",
    )
    lines = calls.splitlines()
    cursor = 0
    for step in expected_exact:
        while cursor < len(lines) and lines[cursor] != step:
            cursor += 1
        assert cursor < len(lines), f"missing or out-of-order CI step: {step}"
        cursor += 1
    while cursor < len(lines) and not (
        lines[cursor].startswith("uv run alembic -x url=")
        and lines[cursor].endswith(" upgrade head")
    ):
        cursor += 1
    assert cursor < len(lines), "missing or out-of-order CI step: alembic upgrade head"
    cursor += 1
    while cursor < len(lines) and lines[cursor] != "uv run pytest -q":
        cursor += 1
    assert cursor < len(lines), "missing or out-of-order CI step: pytest"


def test_non_blocking_lint_report_never_fails_the_gate(tmp_path: Path) -> None:
    """Findings outside src/ and tests/ are reported, not fatal (tsk #273).

    The whole-repo lint pass exists to keep the inherited debt visible. If it could fail the
    gate, every commit would be blocked by notebooks and ops scripts it never touched, which is
    the state that made the old ``ruff check .`` line impossible to satisfy.
    """
    bin_dir, log = _write_stubs(tmp_path, REST_LINT_FAILS_UV_STUB)
    result = _run_ci(bin_dir, log, TEST_URL)
    calls = _calls(log)

    assert result.returncode == 0, result.stderr
    assert "uv run ruff check . --exclude src --exclude tests" in calls
    # The gate ran to completion despite the non-zero lint result.
    assert "docker compose up -d --wait db" in calls
    assert "uv run pytest -q" in calls
    assert "non-blocking ruff findings outside src/ and tests/" in result.stderr


def test_blocking_lint_failure_stops_the_gate(tmp_path: Path) -> None:
    """The src/ and tests/ tier is still fatal, and still comes first."""
    bin_dir, log = _write_stubs(tmp_path, BLOCKING_LINT_FAILS_UV_STUB)
    result = _run_ci(bin_dir, log, TEST_URL)
    calls = _calls(log)

    assert result.returncode != 0
    assert "uv run ruff check src tests" in calls
    assert "docker compose up -d --wait db" not in calls
    assert "uv run pytest -q" not in calls


def test_ci_never_selects_realdata_marker() -> None:
    """The default gate keeps ``realdata`` deselected (WP2.16).

    Deselection lives in ``pyproject.toml`` (``addopts = "-m 'not realdata and not
    native_alignment'"``); the CI script must never pass a ``-m realdata`` override that
    would select the opt-in, operator-machine-only real-data tests.
    """
    content = CI_SCRIPT.read_text()
    assert "-m realdata" not in content
    assert "-m'realdata'" not in content


def test_ci_never_selects_native_alignment_marker() -> None:
    """The default gate also keeps ``native_alignment`` deselected (WP3.0).

    The optional ``alignment`` extra compiles a C binary, so base CI stays compiler-free:
    deselection lives in ``pyproject.toml`` addopts, and the CI script must never pass a
    ``-m native_alignment`` override that would select the opt-in native tests (which
    would fail, not skip, without the extra installed).
    """
    content = CI_SCRIPT.read_text()
    assert "-m native_alignment" not in content
    assert "-m'native_alignment'" not in content


def test_ci_never_selects_optional_morphology_marker() -> None:
    """The default gate keeps ``optional_morphology`` deselected (WP5.12).

    The optional ``morphology`` extra pulls in morfessor, so base CI stays extra-free:
    deselection lives in ``pyproject.toml`` addopts, and the CI script must never pass a
    ``-m optional_morphology`` override.
    """
    content = CI_SCRIPT.read_text()
    assert "-m optional_morphology" not in content
    assert "-m'optional_morphology'" not in content


def test_ci_pytest_requires_postgres_and_forbids_skips() -> None:
    """The CI pytest run must set ``LANGPIPE_REQUIRE_POSTGRES=1`` (WP4.12).

    With that variable set, ``tests/fixtures/db.py`` fails the session when *any* test
    skips — not only when PostgreSQL is unreachable — so the zero-skip gate is enforced
    rather than hoped for.
    """
    invocations = _pytest_invocations(CI_SCRIPT.read_text())
    assert len(invocations) == 1
    assert invocations[0][0] == "LANGPIPE_REQUIRE_POSTGRES=1"


_FORBIDDEN_SELECTION_FLAGS = ("-m", "-k", "--deselect", "--ignore", "-x", "--maxfail")


def test_ci_pytest_does_not_narrow_selection() -> None:
    """The CI pytest invocation must collect everything by default (WP4.12).

    Deselection of the opt-in ``realdata``/``native_alignment`` markers lives in
    ``pyproject.toml`` addopts. The script must pass no marker or keyword expression,
    no deselect/ignore list, no fail-fast limit, and no explicit path argument, so the
    default collection keeps running the unit, contract, service, golden and
    integration suites together.
    """
    invocations = _pytest_invocations(CI_SCRIPT.read_text())
    assert len(invocations) == 1
    words = invocations[0]
    arguments = words[words.index("pytest") + 1 :]
    # Match by prefix: `--maxfail=1` carries its value inline and `-mrealdata` attaches
    # it directly, so an exact-token comparison would let both through.
    narrowed = [
        argument
        for argument in arguments
        for flag in _FORBIDDEN_SELECTION_FLAGS
        if argument.startswith(flag)
    ]
    assert narrowed == [], f"pytest must not narrow test selection: {narrowed}"
    positionals = [word for word in arguments if not word.startswith("-")]
    assert positionals == [], f"pytest must not receive explicit path arguments: {positionals}"


def test_pyproject_contains_required_strict_markers_and_deselections() -> None:
    """The two existing marker guards rely on ``pyproject.toml`` addopts (WP4.12).

    ``ci.sh`` passes no ``-m`` override, so the addopts deselection
    ``-m 'not realdata and not native_alignment'`` and ``--strict-markers`` decide what
    the default gate selects; both must stay in place.
    """
    data = tomllib.loads(PYPROJECT.read_text())
    addopts = data["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--strict-markers" in addopts
    assert "-m 'not realdata and not native_alignment and not optional_morphology'" in addopts
