import pytest

from langpipe.domain.errors import SchemaViolation, UnsupportedSource
from langpipe.text.registry import Versioned, VersionedRegistry, versioned_name


def make(name: str, version: str) -> Versioned:
    return type("Fake", (), {"name": name, "version": version})()


def test_registry_rejects_duplicate_versioned_names() -> None:
    with pytest.raises(ValueError):
        VersionedRegistry([make("tsv", "0.1.0"), make("tsv", "0.1.0")])


def test_registry_bare_name_resolves_highest_version() -> None:
    registry = VersionedRegistry(
        [make("tsv", "0.9.0"), make("tsv", "0.10.0"), make("tsv", "0.2.0"), make("usfm", "1.0.0")]
    )

    assert registry.get("tsv").version == "0.10.0"
    assert registry.get("tsv@0.9.0").version == "0.9.0"
    assert registry.names() == ["tsv@0.10.0", "tsv@0.2.0", "tsv@0.9.0", "usfm@1.0.0"]


def test_registry_unknown_name_raises_unsupported_source() -> None:
    registry = VersionedRegistry([make("tsv", "0.1.0")])

    for ref in ("missing", "tsv@9.9.9"):
        with pytest.raises(UnsupportedSource) as excinfo:
            registry.get(ref)
        assert excinfo.value.reason == "no_extractor"


def test_registry_rejects_non_numeric_registry_version() -> None:
    with pytest.raises(ValueError):
        VersionedRegistry([make("tsv", "0.1.0-beta")])


def test_versioned_name_rejects_invalid_name() -> None:
    with pytest.raises(SchemaViolation):
        versioned_name(make("TSV", "0.1.0"))
    assert versioned_name(make("tsv", "0.1.0")) == "tsv@0.1.0"
