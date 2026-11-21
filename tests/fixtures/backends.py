"""Backend fixtures (`repo` for memory and PostgreSQL) and the application context (`ctx`)."""

import itertools
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.ids import new_id
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.storage.repository import Repository

BACKENDS = ["memory", pytest.param("postgres", marks=pytest.mark.integration)]
CLOCK_START = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(params=BACKENDS)
def repo(request: pytest.FixtureRequest) -> Iterator[Repository]:
    if request.param == "memory":
        yield InMemoryRepository()
        return
    try:
        backend = request.getfixturevalue("pg_repository")
    except pytest.FixtureLookupError:
        pytest.skip("PostgresRepository not implemented (WP9)")
    yield backend


def _stepping_clock() -> Callable[[], datetime]:
    """Each call returns the next whole second after CLOCK_START, so output is deterministic."""
    ticks = itertools.count()
    return lambda: CLOCK_START + timedelta(seconds=next(ticks))


@pytest.fixture
def ctx(repo: Repository, tmp_path: Path) -> AppContext:
    return AppContext(
        repo=repo,
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=_stepping_clock(),
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )
