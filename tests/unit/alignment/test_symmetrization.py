from langpipe.alignment.base import IndexLink
from langpipe.alignment.symmetrization import symmetrize
from langpipe.domain.enums import Symmetrization


def test_intersection_union_exact() -> None:
    forward = (IndexLink(0, 1), IndexLink(1, 0), IndexLink(1, 0))
    reverse = (IndexLink(1, 0), IndexLink(0, 0))
    assert symmetrize(forward, reverse, Symmetrization.INTERSECTION) == (IndexLink(1, 0),)
    assert symmetrize(forward, reverse, Symmetrization.UNION) == (
        IndexLink(0, 0),
        IndexLink(0, 1),
        IndexLink(1, 0),
    )


def test_none_reports_directional_only_and_deduplicates_both_inputs() -> None:
    forward = (IndexLink(0, 0), IndexLink(0, 0), IndexLink(1, 0))
    reverse = (IndexLink(1, 0), IndexLink(1, 0))
    assert symmetrize(forward, reverse, Symmetrization.NONE) == ()
    assert symmetrize(forward, reverse, Symmetrization.UNION) == (IndexLink(0, 0), IndexLink(1, 0))
