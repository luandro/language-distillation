import os
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.errors import NotFound
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.verify import verify_source
from tests.service.manifests import manifest_data, write_manifest, write_origin_file


def _register_three(ctx: AppContext, tmp_path: Path) -> str:
    objects = []
    for name, content in (("a", b"alpha\n"), ("b", b"beta\n"), ("c", b"gamma\n")):
        write_origin_file(tmp_path, f"texts/{name}.txt", content)
        objects.append({"path": f"texts/{name}.txt", "media_type": "text/plain"})
    path = write_manifest(tmp_path, manifest_data(objects=objects))
    return register_source(ctx, path).source.id


def test_verify_source_reports_corrupted_object(ctx: AppContext, tmp_path: Path) -> None:
    source_id = _register_three(ctx, tmp_path)
    ingest_source(ctx, source_id)
    objects = ctx.repo.list_source_objects(source_id)
    corrupted = next(o for o in objects if o.original_path == "texts/b.txt")
    stored = ctx.raw_store.path_for(corrupted.sha256)
    os.chmod(stored, 0o644)
    with stored.open("ab") as handle:
        handle.write(b"tampered\n")

    checks = verify_source(ctx, source_id)

    assert [c.source_object_id for c in checks] == [o.id for o in objects]
    assert [c.status for c in checks] == ["ok", "mismatch", "ok"]
    assert checks[1].sha256 == corrupted.sha256


def test_verify_reports_missing_stored_object(ctx: AppContext, tmp_path: Path) -> None:
    source_id = _register_three(ctx, tmp_path)
    ingest_source(ctx, source_id)
    objects = ctx.repo.list_source_objects(source_id)
    removed = objects[0]
    ctx.raw_store.path_for(removed.sha256).unlink()

    checks = verify_source(ctx, source_id)

    assert [c.status for c in checks] == ["missing", "ok", "ok"]


def test_verify_not_ingested(ctx: AppContext, tmp_path: Path) -> None:
    _register_three(ctx, tmp_path)

    checks = verify_source(ctx, "test-source")

    assert len(checks) == 3
    assert {c.status for c in checks} == {"not_ingested"}


def test_verify_accepts_source_key(ctx: AppContext, tmp_path: Path) -> None:
    source_id = _register_three(ctx, tmp_path)
    ingest_source(ctx, source_id)

    checks = verify_source(ctx, "test-source")

    assert {c.status for c in checks} == {"ok"}


def test_verify_unknown_source_is_not_found(ctx: AppContext) -> None:
    with pytest.raises(NotFound):
        verify_source(ctx, "no-such-source")
