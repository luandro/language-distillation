"""Policy for PostgreSQL-dependent tests: optional local skips vs required CI failures.

Each case runs a child pytest process so the session-level hook and the `pg_url`
fixture are exercised for real. PostgreSQL availability is forced to False in the
child, so these tests never open a database or network connection.
"""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRE_ENV = "LANGPIPE_REQUIRE_POSTGRES"

CHILD_CONFTEST = """
import tests.fixtures.db as db

db.pg_available = lambda: False
pytest_plugins = ["tests.fixtures.db"]
"""


@pytest.fixture
def child(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    pytester.makeconftest(CHILD_CONFTEST)
    return pytester


def test_required_postgres_unavailable_fails(
    child: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REQUIRE_ENV, "1")
    monkeypatch.setenv(
        "LANGPIPE_TEST_DATABASE_URL",
        "postgresql+psycopg://probe-user:hunter2-secret@127.0.0.1:1/langpipe_test",
    )
    child.makepyfile("def test_needs_db(pg_url):\n    assert pg_url\n")
    result = child.runpytest_subprocess("-q", "-p", "no:cacheprovider")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*PostgreSQL unreachable*"])
    output = result.stdout.str() + result.stderr.str()
    assert "hunter2-secret" not in output
    assert "127.0.0.1:1" not in output


def test_required_mode_fails_on_any_skipped_test(
    child: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REQUIRE_ENV, "1")
    child.makepyfile(
        "import pytest\n\n"
        "def test_passes():\n    assert True\n\n"
        "def test_skipped():\n    pytest.skip('deliberate')\n"
    )
    result = child.runpytest_subprocess("-q", "-p", "no:cacheprovider")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*skipped*"])


def test_required_mode_passes_when_nothing_skipped(
    child: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REQUIRE_ENV, "1")
    child.makepyfile("def test_passes():\n    assert True\n")
    result = child.runpytest_subprocess("-q", "-p", "no:cacheprovider")
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*1 passed*"])


def test_optional_local_mode_skips_when_postgres_unavailable(
    child: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REQUIRE_ENV, raising=False)
    child.makepyfile("def test_needs_db(pg_url):\n    assert pg_url\n")
    result = child.runpytest_subprocess("-q", "-p", "no:cacheprovider", "-rs")
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*1 skipped*"])


def test_optional_local_mode_allows_skips(
    child: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(REQUIRE_ENV, "0")
    child.makepyfile("import pytest\n\ndef test_skipped():\n    pytest.skip('deliberate')\n")
    result = child.runpytest_subprocess("-q", "-p", "no:cacheprovider")
    assert result.ret == 0
