import hashlib
import os
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

from langpipe.domain.errors import HashMismatch, InvalidId, ObjectMissing
from langpipe.domain.hashing import SHA256_PATTERN, sha256_file
from langpipe.storage.objects.base import StoredObject

_CHUNK_SIZE = 1 << 20
_READ_ONLY = 0o444


class LocalContentStore:
    """Immutable, content-addressed object store on the local filesystem.

    Objects are written once and never replaced. The store offers no delete,
    overwrite, rename or in-place write operation.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        (self._root / "sha256").mkdir(parents=True, exist_ok=True)
        (self._root / "tmp").mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, sha256: str) -> Path:
        if not SHA256_PATTERN.fullmatch(sha256):
            raise InvalidId()
        return self._root / "sha256" / sha256[0:2] / sha256[2:4] / sha256

    def put_bytes(self, data: bytes) -> StoredObject:
        return self._store((data,))

    def put_file(self, path: Path) -> StoredObject:
        with path.open("rb") as source:
            return self._store(iter(lambda: source.read(_CHUNK_SIZE), b""))

    def exists(self, sha256: str) -> bool:
        return self.path_for(sha256).is_file()

    def open(self, sha256: str) -> BinaryIO:
        try:
            return self.path_for(sha256).open("rb")
        except FileNotFoundError:
            raise ObjectMissing(sha256) from None

    def read_bytes(self, sha256: str) -> bytes:
        with self.open(sha256) as handle:
            return handle.read()

    def verify(self, sha256: str) -> None:
        path = self.path_for(sha256)
        if not path.is_file():
            raise ObjectMissing(sha256)
        actual, _ = sha256_file(path)
        if actual != sha256:
            raise HashMismatch(sha256, actual)

    def _store(self, chunks: Iterable[bytes]) -> StoredObject:
        tmp = self._root / "tmp" / str(uuid.uuid4())
        try:
            digest, size = self._write_tmp(tmp, chunks)
            final = self.path_for(digest)
            final.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(tmp, final)
            except FileExistsError:
                # Content-addressed: an existing object must be identical. Never overwrite it.
                self.verify(digest)
            else:
                os.chmod(final, _READ_ONLY)
            return StoredObject(sha256=digest, size_bytes=size, uri=final.as_uri())
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _write_tmp(tmp: Path, chunks: Iterable[bytes]) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with tmp.open("xb") as handle:
            for chunk in chunks:
                digest.update(chunk)
                size += len(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        return digest.hexdigest(), size
