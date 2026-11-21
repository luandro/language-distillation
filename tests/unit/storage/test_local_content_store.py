import hashlib
import io
import os
import secrets
from pathlib import Path

import pytest

from langpipe.domain.errors import HashMismatch, InvalidId, ObjectMissing
from langpipe.domain.hashing import sha256_bytes
from langpipe.storage.objects.base import ContentStore, StoredObject
from langpipe.storage.objects.local import LocalContentStore


@pytest.fixture
def store(tmp_path: Path) -> LocalContentStore:
    return LocalContentStore(tmp_path / "store")


def test_put_is_content_addressed_and_idempotent(store: LocalContentStore) -> None:
    data = b"raw source bytes"
    first = store.put_bytes(data)
    stat_before = store.path_for(first.sha256).stat()

    second = store.put_bytes(data)
    stat_after = store.path_for(first.sha256).stat()

    assert second == first
    assert first.sha256 == sha256_bytes(data)
    assert first.size_bytes == len(data)
    assert stat_after.st_ino == stat_before.st_ino
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns


def test_stored_object_uri_is_absolute_file_uri(store: LocalContentStore) -> None:
    stored = store.put_bytes(b"uri")
    assert stored.uri == store.path_for(stored.sha256).as_uri()
    assert stored.uri.startswith("file:///")


def test_path_layout_is_sharded_by_hash_prefix(store: LocalContentStore) -> None:
    digest = sha256_bytes(b"layout")
    expected = store.root / "sha256" / digest[0:2] / digest[2:4] / digest
    assert store.path_for(digest) == expected


def test_stored_file_is_read_only(store: LocalContentStore) -> None:
    stored = store.put_bytes(b"read only")
    mode = store.path_for(stored.sha256).stat().st_mode & 0o777
    assert mode == 0o444


def test_open_returns_read_only_stream(store: LocalContentStore) -> None:
    stored = store.put_bytes(b"stream me")
    with store.open(stored.sha256) as handle:
        assert handle.read() == b"stream me"
        with pytest.raises(io.UnsupportedOperation):
            handle.write(b"x")  # type: ignore[arg-type]


def test_store_has_no_mutation_api(store: LocalContentStore) -> None:
    for name in ("delete", "remove", "overwrite", "write", "put_at"):
        assert not hasattr(store, name), name


def test_read_bytes_returns_immutable_bytes(store: LocalContentStore) -> None:
    stored = store.put_bytes(b"immutable")
    data = store.read_bytes(stored.sha256)
    assert type(data) is bytes
    assert data == b"immutable"


def test_verify_detects_corruption(store: LocalContentStore) -> None:
    stored = store.put_bytes(b"pristine")
    path = store.path_for(stored.sha256)
    os.chmod(path, 0o644)
    with path.open("ab") as handle:
        handle.write(b"!")

    with pytest.raises(HashMismatch):
        store.verify(stored.sha256)


def test_verify_intact_object_passes(store: LocalContentStore) -> None:
    stored = store.put_bytes(b"intact")
    store.verify(stored.sha256)


def test_verify_missing_raises_object_missing(store: LocalContentStore) -> None:
    with pytest.raises(ObjectMissing):
        store.verify(sha256_bytes(b"never stored"))


def test_open_missing_raises_object_missing(store: LocalContentStore) -> None:
    with pytest.raises(ObjectMissing):
        store.open(sha256_bytes(b"never stored"))


def test_put_over_corrupted_existing_raises_hash_mismatch(store: LocalContentStore) -> None:
    data = b"will be corrupted"
    stored = store.put_bytes(data)
    path = store.path_for(stored.sha256)
    os.chmod(path, 0o644)
    with path.open("ab") as handle:
        handle.write(b"?")

    with pytest.raises(HashMismatch):
        store.put_bytes(data)


def test_put_file_streams_large_file(store: LocalContentStore, tmp_path: Path) -> None:
    payload = secrets.token_bytes(5 * 1024 * 1024)
    source = tmp_path / "large.bin"
    source.write_bytes(payload)

    stored = store.put_file(source)

    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert stored.size_bytes == len(payload)
    assert store.read_bytes(stored.sha256) == payload


def test_put_file_matches_put_bytes(store: LocalContentStore, tmp_path: Path) -> None:
    source = tmp_path / "small.txt"
    source.write_bytes(b"same content")
    assert store.put_file(source) == store.put_bytes(b"same content")


def test_no_temporary_files_left_behind(store: LocalContentStore) -> None:
    store.put_bytes(b"tidy")
    store.put_bytes(b"tidy")
    assert list((store.root / "tmp").iterdir()) == []


def test_rejects_malformed_sha256(store: LocalContentStore) -> None:
    for bad in ("../../etc/passwd", "ABCDEF", "", "g" * 64):
        with pytest.raises(InvalidId):
            store.path_for(bad)


def test_local_store_satisfies_content_store_protocol(store: LocalContentStore) -> None:
    protocol_store: ContentStore = store
    stored = protocol_store.put_bytes(b"protocol")
    assert isinstance(stored, StoredObject)
    assert protocol_store.exists(stored.sha256)
    assert not protocol_store.exists(sha256_bytes(b"absent"))
