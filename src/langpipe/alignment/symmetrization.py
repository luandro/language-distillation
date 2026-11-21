"""Exact set intersection/union for directional token links."""

from collections.abc import Sequence

from langpipe.alignment.base import IndexLink
from langpipe.domain.enums import Symmetrization


def symmetrize(
    forward: Sequence[IndexLink], reverse: Sequence[IndexLink], mode: Symmetrization
) -> tuple[IndexLink, ...]:
    fwd = {(item.source_index, item.target_index) for item in forward}
    rev = {(item.source_index, item.target_index) for item in reverse}
    if mode is Symmetrization.INTERSECTION:
        pairs = fwd & rev
    elif mode is Symmetrization.UNION:
        pairs = fwd | rev
    else:
        pairs = set()
    return tuple(IndexLink(a, b) for a, b in sorted(pairs))
