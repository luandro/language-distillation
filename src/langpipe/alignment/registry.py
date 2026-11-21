"""Alignment adapter registries keyed by ``name@version`` (M3 WP3.6, §5.2).

``SEGMENT_ALIGNERS`` holds the production segment aligners; the token registry
is added with the eflomal adapter in WP3.8. Unknown method references resolve
to the fixed ``unknown_method`` diagnostic while ``VersionedRegistry`` keeps
its existing M2 exception behavior unchanged. Production defaults never
contain mocks.
"""

from langpipe.alignment.adapters.eflomal import EflomalAligner
from langpipe.alignment.base import SegmentAligner, TokenAligner
from langpipe.alignment.canonical import CanonicalLocatorAligner
from langpipe.domain.errors import AlignmentFailed, UnsupportedSource
from langpipe.text.registry import Versioned, VersionedRegistry

SEGMENT_ALIGNERS: VersionedRegistry[SegmentAligner] = VersionedRegistry(
    (CanonicalLocatorAligner(),)
)
TOKEN_ALIGNERS: VersionedRegistry[TokenAligner] = VersionedRegistry((EflomalAligner(),))


def resolve_aligner[T: Versioned](registry: VersionedRegistry[T], method: str) -> T:
    """Resolve a method reference to a registered adapter.

    A bare name resolves to its latest numeric version; a ``name@version``
    reference pins that exact version. Any unresolvable reference fails with
    the fixed ``unknown_method`` code and never echoes the requested method
    or any caller payload back.
    """
    try:
        return registry.get(method)
    except UnsupportedSource:
        raise AlignmentFailed("unknown_method") from None
