"""Morphology inducer registry keyed by ``name@version`` (M5-PLAN §6 WP5.8, ADR-0017).

Resolves a method reference to a registered `MorphologyInducer`.
Unknown references raise the typed `UnsupportedMethod`.
"""

from typing import Final

from langpipe.domain.errors import UnsupportedSource
from langpipe.morphology.adapters.bpe_char import BpeCharInducer
from langpipe.morphology.adapters.igt_assertion import IgtAssertionInducer
from langpipe.morphology.adapters.igt_projection import IgtProjectionInducer
from langpipe.morphology.adapters.morfessor import MorfessorInducer
from langpipe.morphology.adapters.unsegmented import UnsegmentedInducer
from langpipe.morphology.base import MorphologyInducer
from langpipe.text.registry import VersionedRegistry

METHOD_UNSEGMENTED: Final = "unsegmented"
METHOD_IGT_ASSERTION: Final = "igt_assertion"
METHOD_IGT_PROJECTION: Final = "igt_projection"
METHOD_BPE_CHAR: Final = "bpe_char"
METHOD_MORFESSOR: Final = "morfessor_baseline"


class UnsupportedMethod(Exception):
    """No registered morphology inducer matches the requested method reference."""

    def __init__(self) -> None:
        super().__init__("unsupported morphology induction method")


class MorphologyRegistry(VersionedRegistry[MorphologyInducer]):
    """Versioned registry of morphology inducers raising `UnsupportedMethod` on missing."""

    def get(self, ref: str) -> MorphologyInducer:
        try:
            return super().get(ref)
        except UnsupportedSource:
            raise UnsupportedMethod() from None


INDUCERS: Final[tuple[MorphologyInducer, ...]] = (
    UnsegmentedInducer(),
    IgtAssertionInducer(),
    IgtProjectionInducer(),
    BpeCharInducer(),
    MorfessorInducer(),
)

MORPHOLOGY_INDUCERS: Final[MorphologyRegistry] = MorphologyRegistry(INDUCERS)


def get_morphology_inducer(method: str) -> MorphologyInducer:
    """Resolve a method reference to its registered inducer.

    ``name@version`` pins exactly one version; a bare name selects the highest registered
    version of that name. Anything unresolvable fails with `UnsupportedMethod`.
    """
    return MORPHOLOGY_INDUCERS.get(method)


def morphology_induction_methods() -> list[str]:
    """Every registered method reference, sorted."""
    return MORPHOLOGY_INDUCERS.names()


__all__ = [
    "INDUCERS",
    "METHOD_BPE_CHAR",
    "METHOD_IGT_ASSERTION",
    "METHOD_IGT_PROJECTION",
    "METHOD_MORFESSOR",
    "METHOD_UNSEGMENTED",
    "MORPHOLOGY_INDUCERS",
    "MorphologyRegistry",
    "UnsupportedMethod",
    "get_morphology_inducer",
    "morphology_induction_methods",
]
