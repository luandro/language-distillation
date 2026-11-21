"""Helpers that write source manifests and origin files, plus fault-injection and I/O spies."""

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType, RunStatus
from langpipe.domain.models.run import ProcessingRun

DEFAULT_OBJECTS: list[dict[str, Any]] = [
    {"path": "texts/a.txt", "media_type": "text/plain"},
]
STORE_METHODS = ("put_file", "put_bytes", "open", "verify", "read_bytes", "exists")


def manifest_data(
    *,
    key: str = "test-source",
    title: str = "Test source",
    mode: str = "direct",
    access_class: str = "public",
    objects: list[dict[str, Any]] | None = None,
    **policy_overrides: Any,
) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "mode": mode,
        "access_class": access_class,
        "authority": "test-authority",
        **policy_overrides,
    }
    return {
        "manifest_version": 1,
        "key": key,
        "title": title,
        "source_type": "parallel_text",
        "languages": ["mzr"],
        "provenance": {"acquired_from": "test"},
        # Quoted so YAML keeps a string and Pydantic parses it as an aware UTC datetime.
        "acquired_at": "2026-01-01T00:00:00+00:00",
        "policy": policy,
        "objects": list(DEFAULT_OBJECTS if objects is None else objects),
    }


def write_manifest(directory: Path, data: dict[str, Any], name: str = "manifest.yaml") -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def write_origin_file(directory: Path, relative: str, content: bytes) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def raise_on(
    target: object,
    method: str,
    error: BaseException,
    when: Callable[[tuple[Any, ...]], bool] = lambda args: True,
) -> Any:
    """Patch `target.method` so calls matching `when` raise `error`; other calls run for real."""
    original = getattr(target, method)

    def faulty(*args: Any, **kwargs: Any) -> Any:
        if when(args):
            raise error
        return original(*args, **kwargs)

    return patch.object(target, method, side_effect=faulty)


@contextmanager
def spy_all_io(ctx: AppContext) -> Iterator[list[MagicMock]]:
    """Record every store method on both stores and every `Path.open` made inside the block."""
    with ExitStack() as stack:
        mocks: list[MagicMock] = []
        for store in (ctx.raw_store, ctx.artifact_store):
            for name in STORE_METHODS:
                spy = patch.object(store, name, wraps=getattr(store, name))
                mocks.append(stack.enter_context(spy))
        opener = patch.object(Path, "open", autospec=True, side_effect=Path.open)
        mocks.append(stack.enter_context(opener))
        yield mocks


def record_finished_runs(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> list[ProcessingRun]:
    """Keep every run returned by finish_run, including failed runs whose ids are not returned."""
    finished: list[ProcessingRun] = []
    original = ctx.repo.finish_run

    def record(*args: object, **kwargs: object) -> ProcessingRun:
        run = original(*args, **kwargs)  # type: ignore[arg-type]
        finished.append(run)
        return run

    monkeypatch.setattr(ctx.repo, "finish_run", record)
    return finished


def is_success_transition(args: tuple[Any, ...]) -> bool:
    """`when` predicate for finish_run: matches only the transition to SUCCEEDED."""
    return len(args) > 1 and args[1] is RunStatus.SUCCEEDED


def state_counts(ctx: AppContext) -> dict[str, int]:
    """Row counts for every semantic table, lineage, blobs, runs and audit events."""
    repo = ctx.repo
    values = {entity.value: repo.count(entity) for entity in EntityType}
    values["lineage"] = repo.count_lineage_edges()
    values["blobs"] = repo.count_raw_blobs()
    values["audit"] = len(repo.list_audit_events())
    return values
