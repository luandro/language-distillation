from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    size_bytes: int
    uri: str  # "file://<abs path>"


class ContentStore(Protocol):
    def put_bytes(self, data: bytes) -> StoredObject: ...

    def put_file(self, path: Path) -> StoredObject: ...

    def exists(self, sha256: str) -> bool: ...

    def open(self, sha256: str) -> BinaryIO: ...  # opened "rb"; ObjectMissing if absent

    def read_bytes(self, sha256: str) -> bytes: ...

    def verify(self, sha256: str) -> None: ...  # ObjectMissing | HashMismatch
