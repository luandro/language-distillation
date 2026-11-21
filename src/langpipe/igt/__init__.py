"""IGT readers (WP5.6, Gate 35): pure Toolbox and Xigt-XML readers.

Public surface: the reader DTOs (`IgtRecord`, `IgtDocument`), the `IgtReader`
protocol, the Leipzig gloss splitter (`split_gloss` / `SplitGlossResult`), the
two registered readers and the versioned registry.
"""

from langpipe.igt.base import IgtDocument, IgtReader, IgtRecord
from langpipe.igt.gloss import SplitGlossResult, split_gloss
from langpipe.igt.registry import IGT_READERS, reader_for_media_type
from langpipe.igt.service import IgtExtractResult, IgtExtractService, extract_igt
from langpipe.igt.toolbox import ToolboxIgtReader
from langpipe.igt.xigt import XigtXmlReader, write_xigt_xml

__all__ = [
    "IGT_READERS",
    "IgtDocument",
    "IgtExtractResult",
    "IgtExtractService",
    "IgtReader",
    "IgtRecord",
    "SplitGlossResult",
    "ToolboxIgtReader",
    "XigtXmlReader",
    "extract_igt",
    "reader_for_media_type",
    "split_gloss",
    "write_xigt_xml",
]
