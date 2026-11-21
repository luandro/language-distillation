"""Versioned component registries keyed by ``name@version`` (M2 E3)."""

from collections.abc import Iterable
from typing import ClassVar, Protocol

from pydantic import TypeAdapter, ValidationError

from langpipe.domain.errors import SchemaViolation, UnsupportedSource
from langpipe.domain.models.base import VERSIONED_NAME

_VERSIONED = TypeAdapter(VERSIONED_NAME)


class Versioned(Protocol):
    name: ClassVar[str]
    version: ClassVar[str]


def versioned_name(c: type[Versioned] | Versioned) -> str:
    ref = f"{c.name}@{c.version}"
    try:
        _VERSIONED.validate_python(ref)
    except ValidationError:
        raise SchemaViolation() from None
    return ref


def _version_key(version: str) -> tuple[int, ...]:
    # Supported registry-version subset for M2: dotted integers only (no prerelease tags).
    parts = version.split(".")
    if not all(part.isascii() and part.isdigit() for part in parts):
        raise ValueError(f"registry versions must be dotted integers: {version}")
    return tuple(int(part) for part in parts)


class VersionedRegistry[T: Versioned]:
    def __init__(self, items: Iterable[T]) -> None:
        self._items: dict[str, T] = {}
        for item in items:
            _version_key(item.version)
            ref = versioned_name(item)
            if ref in self._items:
                raise ValueError(f"duplicate versioned name: {ref}")
            self._items[ref] = item

    def get(self, ref: str) -> T:
        if "@" in ref:
            found = self._items.get(ref)
        else:
            candidates = [item for item in self._items.values() if item.name == ref]
            found = max(candidates, key=lambda item: _version_key(item.version), default=None)
        if found is None:
            raise UnsupportedSource("no_extractor")
        return found

    def names(self) -> list[str]:
        return sorted(self._items)
