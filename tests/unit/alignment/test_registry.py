"""WP3.6 alignment registry: version pinning, latest resolution, fixed diagnostics.

``VersionedRegistry`` keeps its existing M2 exception behavior unchanged; the
alignment layer maps unresolvable method references to the fixed
``unknown_method`` diagnostic. Production defaults never contain mocks.
"""

import pytest

from langpipe.alignment.base import AlignmentConfig, SegmentMatchOutput
from langpipe.alignment.canonical import CanonicalLocatorAligner
from langpipe.alignment.registry import SEGMENT_ALIGNERS, resolve_aligner
from langpipe.domain.errors import AlignmentFailed, UnsupportedSource
from langpipe.domain.models.observation import Segment
from langpipe.text.registry import VersionedRegistry, versioned_name


class _StubAligner:
    """Test-only aligner versions; never registered in production defaults."""

    name = "stub"

    def __init__(self, version: str) -> None:
        self.version = version

    def align(
        self,
        source: list[Segment],
        target: list[Segment],
        config: AlignmentConfig,
    ) -> SegmentMatchOutput:
        raise AssertionError("stub aligner is never invoked")


def test_production_registry_pins_canonical_locator() -> None:
    found = SEGMENT_ALIGNERS.get("canonical_locator@0.1.0")

    assert isinstance(found, CanonicalLocatorAligner)
    assert SEGMENT_ALIGNERS.names() == ["canonical_locator@0.1.0"]
    assert versioned_name(found) == "canonical_locator@0.1.0"


def test_latest_numeric_version_resolution() -> None:
    registry = VersionedRegistry((_StubAligner("0.1.0"), _StubAligner("0.2.0")))

    assert registry.get("stub").version == "0.2.0"
    assert registry.get("stub@0.1.0").version == "0.1.0"
    assert registry.get("stub@0.2.0").version == "0.2.0"


def test_unknown_method_fixed_diagnostic() -> None:
    for method in ("eflomal", "canonical_locator@9.9.9", "not_an_aligner@1.0.0"):
        with pytest.raises(AlignmentFailed) as exc_info:
            resolve_aligner(SEGMENT_ALIGNERS, method)
        assert exc_info.value.code == "unknown_method"
        # Fixed diagnostic only; the unknown method reference is never echoed back.
        assert str(exc_info.value) == "alignment failed: code=unknown_method"


def test_versioned_registry_m2_exception_unchanged() -> None:
    with pytest.raises(UnsupportedSource) as exc_info:
        SEGMENT_ALIGNERS.get("canonical_locator@9.9.9")

    assert exc_info.value.reason == "no_extractor"


def test_resolve_aligner_resolves_registered_methods() -> None:
    found = resolve_aligner(SEGMENT_ALIGNERS, "canonical_locator")

    assert isinstance(found, CanonicalLocatorAligner)
    assert found is SEGMENT_ALIGNERS.get("canonical_locator@0.1.0")
