"""IGT reader registry (WP5.6): the two pure readers, keyed ``name@version``."""

from langpipe.igt.base import IgtReader
from langpipe.igt.toolbox import ToolboxIgtReader
from langpipe.igt.xigt import XigtXmlReader
from langpipe.text.registry import VersionedRegistry

IGT_READERS: VersionedRegistry[IgtReader] = VersionedRegistry((ToolboxIgtReader(), XigtXmlReader()))

_MEDIA_TYPES: dict[str, str] = {
    "text/plain": "toolbox_igt",
    "application/xml": "xigt_xml",
    "text/xml": "xigt_xml",
    "application/xigt+xml": "xigt_xml",
}


def reader_for_media_type(media_type: str) -> str | None:
    """Resolve a media type to a registered reader reference ``name@version``.

    Parameters after ``;`` are ignored and matching is case-insensitive; unknown
    media types return ``None`` (WP5.7 decides how to fail closed on that).
    """
    base = media_type.partition(";")[0].strip().lower()
    name = _MEDIA_TYPES.get(base)
    if name is None:
        return None
    return IGT_READERS.get(name).name + "@" + IGT_READERS.get(name).version
