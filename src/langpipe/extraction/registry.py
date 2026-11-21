"""Extractor registry and default extractor resolution (M2 §4.3)."""

from collections.abc import Mapping

from langpipe.domain.enums import SourceType
from langpipe.extraction.base import Extractor
from langpipe.extraction.plain_lines import PlainLinesExtractor
from langpipe.extraction.tsv import TsvExtractor
from langpipe.extraction.tsv_sentences import TsvSentencesExtractor
from langpipe.extraction.usfm import UsfmExtractor
from langpipe.text.registry import VersionedRegistry

# Concrete extractors are registered in WP2.3 (tsv, plain_lines) and WP2.4 (usfm).
# tsv_sentences (M3 WP3.4) is opt-in by explicit name only, never a default (ADR-0011 §4).
EXTRACTORS: VersionedRegistry[Extractor] = VersionedRegistry(
    (TsvExtractor(), PlainLinesExtractor(), UsfmExtractor(), TsvSentencesExtractor())
)

_DEFAULTS: Mapping[tuple[SourceType | None, str], str] = {
    (None, "text/tab-separated-values"): "tsv@0.1.0",
    (None, "text/x-usfm"): "usfm@0.1.0",
    (SourceType.MONOLINGUAL_TEXT, "text/plain"): "plain_lines@0.1.0",
    (SourceType.PARALLEL_TEXT, "text/plain"): "plain_lines@0.1.0",
    (SourceType.EDUCATIONAL_PUBLICATION, "text/plain"): "plain_lines@0.1.0",
    (SourceType.PUBLICATION, "text/plain"): "plain_lines@0.1.0",
}

# No M2 extractor exists for these source types (C8, ADR-0010); objects are skipped and reported.
_NO_M2_EXTRACTOR: frozenset[SourceType] = frozenset(
    {SourceType.IGT, SourceType.AUDIO, SourceType.VIDEO}
)


def default_extractor_for(source_type: SourceType, media_type: str) -> str | None:
    if source_type in _NO_M2_EXTRACTOR:
        return None
    exact = _DEFAULTS.get((source_type, media_type))
    if exact is not None:
        return exact
    return _DEFAULTS.get((None, media_type))
