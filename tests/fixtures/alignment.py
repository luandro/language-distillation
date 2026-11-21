"""Test-only explicit token aligner; never added to production registries."""

from collections.abc import Sequence

from langpipe.alignment.base import (
    AlignmentConfig,
    BackendMetadata,
    IndexLink,
    TokenBatchOutput,
    TokenGroup,
    TokenLinks,
)

type _LinkPairs = tuple[tuple[int, int], ...]
type _LinksMap = dict[str, tuple[_LinkPairs, _LinkPairs]]


class MockTokenAligner:
    name = "mock"
    version = "0.1.0"

    def __init__(self, links: _LinksMap):
        self.links = links

    def align(self, groups: Sequence[TokenGroup], config: AlignmentConfig) -> TokenBatchOutput:
        return TokenBatchOutput(
            tuple(
                TokenLinks(
                    g.alignment_id,
                    tuple(IndexLink(*p) for p in self.links.get(g.alignment_id, ((), ()))[0]),
                    tuple(IndexLink(*p) for p in self.links.get(g.alignment_id, ((), ()))[1]),
                )
                for g in groups
            ),
            BackendMetadata("0.1.0", None, {}, False),
        )
