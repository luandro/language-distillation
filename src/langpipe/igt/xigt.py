"""Xigt XML IGT reader, `xigt_xml@0.1.0` (WP5.6, M5-PLAN §7.6), plus the
test-only `write_xigt_xml` helper for round-trip proofs.

Pure: bytes to `IgtDocument`, with stdlib `xml.etree.ElementTree` only:

- pre-parse hardening: a byte-size cap (`MAX_XIGT_BYTES`) and refusal of any
  ``<!DOCTYPE``/``<!ENTITY`` (no DTD, no entity expansion, no network) raise
  `ExtractionFailed` with fixed codes before any XML machinery runs;
- reads ``xigt-corpus/igt/tier[@type]``: ``words`` (or ``tx``), ``morphemes``
  (``mb``, segmentation → words), ``glosses`` (``ge``, alignment → morphemes)
  and ``translations`` (``ft``). Item content comes from the item text or from
  a ``content`` reference (depth-limited against cycles). Only the first tier
  of each role feeds the parsed layer; duplicates are ignored;
- every item of every tier (including unknown tier types) is synthesized as an
  `IgtTierLine` with ``marker="xigt:<type>"``; ``line_number`` is the item's
  1-based position within its tier (stdlib ElementTree exposes no source line
  numbers), and ``raw`` is the resolved item text, so unknown tiers survive as
  evidence;
- unsupported or malformed per-record structures never crash and never fail the
  document: the record is `IgtParseStatus.UNPARSED` with a fixed diagnostic code
  (``unknown_tier_type``, ``unknown_tier_ref``, ``dangling_item_ref``,
  ``missing_words_tier``, ``morphs_unlocatable``).

Wholly malformed XML raises `ExtractionFailed("xml_malformed", ...)`. No
message carries source content: errors address documents and lines only.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import ClassVar

from langpipe.domain.enums import IgtFormat, IgtParseStatus
from langpipe.domain.errors import ExtractionFailed
from langpipe.domain.models.igt import IgtMorph, IgtTierLine, IgtWord
from langpipe.extraction.base import decode_utf8
from langpipe.igt.base import (
    IgtDocument,
    IgtRecord,
    locate_morphs,
    normalize_lang_code,
    source_object_id,
    split_at_boundary_marks,
)
from langpipe.languages.base import MorphologyProfile

MAX_XIGT_BYTES = 50 * 1024 * 1024

_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_MAX_CONTENT_DEPTH = 8

# Tier types this reader understands (v1-style one-letter aliases included).
_ROLE_BY_TYPE = {
    "words": "words",
    "tx": "words",
    "morphemes": "morphemes",
    "mb": "morphemes",
    "glosses": "glosses",
    "ge": "glosses",
    "translations": "translations",
    "ft": "translations",
}


def _local(element: ET.Element) -> str:
    """Namespace-insensitive element tag name."""
    return element.tag.rpartition("}")[2]


def _attrs(element: ET.Element) -> dict[str, str]:
    """Namespace-insensitive attribute view (``xml:lang`` becomes ``lang``)."""
    return {key.rpartition("}")[2]: value for key, value in element.attrib.items()}


def _items(element: ET.Element) -> list[ET.Element]:
    return [child for child in element if _local(child) == "item"]


def _ref(raw: str | None) -> str | None:
    return raw.lstrip("#") if raw else None


@dataclass(frozen=True)
class _TierInfo:
    element: ET.Element
    type_: str
    role: str | None


class _PerRecord:
    """Reads one ``igt`` element; the document reader creates one per record."""

    # Tier-level reference rules: on role (attr, expected role of the target).
    _TIER_REF_RULES: ClassVar[dict[str, tuple[str, str]]] = {
        "morphemes": ("segmentation", "words"),
        "glosses": ("alignment", "morphemes"),
    }

    def __init__(self, profile: MorphologyProfile) -> None:
        self.profile = profile
        self.diagnostics: list[str] = []
        self.status = IgtParseStatus.OK
        self.tiers: list[IgtTierLine] = []
        self.words: list[IgtWord] = []
        self.translations: dict[str, list[str]] = {}

    def diag(self, code: str) -> None:
        if code not in self.diagnostics:
            self.diagnostics.append(code)
        self.status = IgtParseStatus.UNPARSED

    def _resolve_text(self, item: ET.Element, elements: dict[str, ET.Element]) -> str | None:
        """Item content: its own text, or the ``content`` reference's text.

        ``None`` means an unresolvable (or cyclic) reference: reported as
        ``dangling_item_ref``, never attempted twice beyond the depth bound.
        """
        current = item
        seen: set[int] = set()
        for _ in range(_MAX_CONTENT_DEPTH):
            if id(current) in seen:
                return None
            seen.add(id(current))
            attrs = _attrs(current)
            if "content" not in attrs:
                return "".join(current.itertext())
            target = elements.get(_ref(attrs["content"]) or "")
            if target is None:
                return None
            current = target
        return None

    def read(self, element: ET.Element, ordinal: int) -> IgtRecord:
        tiers = [child for child in element if _local(child) == "tier"]
        elements: dict[str, ET.Element] = {}
        for candidate in element.iter():
            if _local(candidate) == "item" and "id" in _attrs(candidate):
                elements[_attrs(candidate)["id"]] = candidate

        tier_metadata: list[_TierInfo] = []
        roles_by_id: dict[str, str] = {}
        for tier in tiers:
            attrs = _attrs(tier)
            tier_type = attrs.get("type", "untyped")
            role = _ROLE_BY_TYPE.get(tier_type)
            if role is None:
                self.diag("unknown_tier_type")
            if "id" in attrs:
                roles_by_id[attrs["id"]] = role or "unknown"
            tier_metadata.append(_TierInfo(tier, tier_type, role))
        self._validate_tier_refs(tier_metadata, set(_tier_ids(tier_metadata)), roles_by_id)

        words_tier = next((info for info in tier_metadata if info.role == "words"), None)
        word_items = _items(words_tier.element) if words_tier is not None else []
        if not word_items:
            self.diag("missing_words_tier")

        self._synthesize_tier_lines(tier_metadata, elements)
        self._parse_words(tier_metadata, word_items, elements)
        self._parse_translations(tier_metadata, elements)

        attrs = _attrs(element)
        return IgtRecord(
            record_ordinal=ordinal,
            record_ref=attrs.get("id"),
            format=IgtFormat.XIGT,
            locator={"igt_ordinal": ordinal, "id": attrs.get("id")},
            tiers=self.tiers,
            words=self.words,
            translations=self.translations,
            parse_status=self.status,
            diagnostics=self.diagnostics,
        )

    def _validate_tier_refs(
        self,
        tier_metadata: list[_TierInfo],
        tier_ids: set[str],
        roles_by_id: dict[str, str],
    ) -> None:
        """Tier-level references must exist and point at the expected role."""
        for info in tier_metadata:
            rule = self._TIER_REF_RULES.get(info.role or "")
            if rule is None:
                continue
            attr, expected_role = rule
            target = _ref(_attrs(info.element).get(attr))
            if target is None:
                continue  # absent: item-level references carry the alignment
            if target not in tier_ids or roles_by_id.get(target) != expected_role:
                self.diag("unknown_tier_ref")

    def _synthesize_tier_lines(
        self, tier_metadata: list[_TierInfo], elements: dict[str, ET.Element]
    ) -> None:
        for info in tier_metadata:
            marker = f"xigt:{info.type_}"
            for position, item in enumerate(_items(info.element), start=1):
                text = self._resolve_text(item, elements)
                if text is None:
                    self.diag("dangling_item_ref")
                    text = ""
                self.tiers.append(IgtTierLine(marker=marker, line_number=position, raw=text))

    def _parse_words(
        self,
        tier_metadata: list[_TierInfo],
        word_items: list[ET.Element],
        elements: dict[str, ET.Element],
    ) -> None:
        marks = self.profile.boundary_marks
        word_ids = [_attrs(item).get("id") for item in word_items]
        word_texts: list[str] = []
        for item in word_items:
            text = self._resolve_text(item, elements)
            if text is None:
                self.diag("dangling_item_ref")
                text = ""
            word_texts.append(text)

        morph_tier = next((info for info in tier_metadata if info.role == "morphemes"), None)
        morph_specs: list[tuple[str | None, str, int]] = []
        if morph_tier is not None:
            word_index_by_id = {wid: i for i, wid in enumerate(word_ids) if wid is not None}
            for item in _items(morph_tier.element):
                text = self._resolve_text(item, elements)
                if text is None:
                    self.diag("dangling_item_ref")
                    continue
                segmentation = _ref(_attrs(item).get("segmentation"))
                index = word_index_by_id.get(segmentation) if segmentation is not None else None
                if index is None:
                    self.diag("dangling_item_ref")
                    continue
                morph_specs.append((_attrs(item).get("id"), text, index))

        gloss_tier = next((info for info in tier_metadata if info.role == "glosses"), None)
        gloss_by_morph_id: dict[str, str] = {}
        if gloss_tier is not None:
            morph_ids = {mid for mid, _text, _index in morph_specs if mid is not None}
            for item in _items(gloss_tier.element):
                text = self._resolve_text(item, elements)
                target = _ref(_attrs(item).get("alignment"))
                if text is None or target is None or target not in morph_ids:
                    self.diag("dangling_item_ref")
                    continue
                gloss_by_morph_id[target] = text

        words: list[IgtWord] = []
        for index, word_text in enumerate(word_texts):
            owned = [(mid, text) for mid, text, wi in morph_specs if wi == index]
            if owned:
                texts = [text for _mid, text in owned]
                boundaries = locate_morphs(word_text, texts, marks)
                if boundaries is None:
                    self.diag("morphs_unlocatable")
                    boundaries = [None] * len(texts)
                morphs = [
                    IgtMorph(
                        ordinal=position,
                        text=text,
                        boundary_before=boundaries[position],
                        gloss=gloss_by_morph_id.get(mid) if mid is not None else None,
                    )
                    for position, ((mid, text), boundary) in enumerate(
                        zip(owned, boundaries, strict=True)
                    )
                ]
            else:
                pieces = split_at_boundary_marks(word_text, marks)
                morphs = [
                    IgtMorph(ordinal=position, text=piece[0], boundary_before=piece[1])
                    for position, piece in enumerate(pieces)
                ]
            words.append(IgtWord(ordinal=index, text=word_text, morphs=morphs))
        self.words = words

    def _parse_translations(
        self, tier_metadata: list[_TierInfo], elements: dict[str, ET.Element]
    ) -> None:
        translation_tier = next(
            (info for info in tier_metadata if info.role == "translations"), None
        )
        if translation_tier is None:
            return
        for item in _items(translation_tier.element):
            attrs = _attrs(item)
            text = self._resolve_text(item, elements)
            if text is None:
                self.diag("dangling_item_ref")
                text = ""
            key = normalize_lang_code(attrs.get("lang"))
            self.translations.setdefault(key, []).append(text)


def _tier_ids(tier_metadata: list[_TierInfo]) -> list[str]:
    return [_attrs(info.element)["id"] for info in tier_metadata if "id" in _attrs(info.element)]


class XigtXmlReader:
    """Xigt XML reader. See the module docstring for the parse contract."""

    name: ClassVar[str] = "xigt_xml"
    version: ClassVar[str] = "0.1.0"

    def read(
        self,
        data: bytes,
        ctx: object = None,
        profile: MorphologyProfile | None = None,
    ) -> IgtDocument:
        obj_id = source_object_id(ctx)
        if len(data) > MAX_XIGT_BYTES:
            raise ExtractionFailed("xml_too_large", obj_id, None)
        lowered = data.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise ExtractionFailed("xml_entity_expansion_refused", obj_id, None)
        text, decode_stats = decode_utf8(data, obj_id)  # raises decode_error
        try:
            # Parse decoded Unicode string directly to prevent expat re-encoding/re-decoding
            # under a conflicting XML encoding declaration.
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            line = exc.position[0] if exc.position else None
            raise ExtractionFailed("xml_malformed", obj_id, line) from None
        root_tag = _local(root)
        if root_tag == "xigt-corpus":
            igt_elements = [child for child in root if _local(child) == "igt"]
        elif root_tag == "igt":
            igt_elements = [root]
        else:
            raise ExtractionFailed("xml_malformed", obj_id, None)

        profiled = profile if profile is not None else MorphologyProfile()
        records = [
            _PerRecord(profiled).read(element, ordinal)
            for ordinal, element in enumerate(igt_elements)
        ]

        stats: dict[str, int] = dict(decode_stats)
        stats["records"] = len(records)
        for status in IgtParseStatus:
            stats[status.value] = sum(1 for record in records if record.parse_status == status)
        stats["words"] = sum(len(record.words) for record in records)
        stats["morphs"] = sum(len(word.morphs) for record in records for word in record.words)
        for record in records:
            for code in record.diagnostics:
                stats[code] = stats.get(code, 0) + 1
        return IgtDocument(format=IgtFormat.XIGT, header=[], records=records, stats=stats)


def write_xigt_xml(doc: IgtDocument) -> str:
    """Test helper: serialize the parsed layer of every record to Xigt XML.

    Emits exactly the tier shapes the reader understands (words, morphemes by
    segmentation, glosses by alignment, translations with ``xml:lang``); items
    without a gloss are simply not emitted, and their absence round-trips as
    ``gloss=None``. Not a general writer: round-trip proofs only (WP5.6).
    """
    root = ET.Element("xigt-corpus")
    for record in doc.records:
        n = record.record_ordinal
        igt = ET.SubElement(root, "igt")
        if record.record_ref:
            igt.set("id", record.record_ref)
        words = ET.SubElement(igt, "tier", {"id": f"r{n}.tw", "type": "words"})
        for i, word in enumerate(record.words):
            ET.SubElement(words, "item", {"id": f"r{n}.w{i}"}).text = word.text
        morph_tier = ET.SubElement(
            igt, "tier", {"id": f"r{n}.tm", "type": "morphemes", "segmentation": f"r{n}.tw"}
        )
        for i, word in enumerate(record.words):
            for j, morph in enumerate(word.morphs):
                ET.SubElement(
                    morph_tier, "item", {"id": f"r{n}.m{i}.{j}", "segmentation": f"r{n}.w{i}"}
                ).text = morph.text
        gloss_tier = ET.SubElement(
            igt, "tier", {"id": f"r{n}.tg", "type": "glosses", "alignment": f"r{n}.tm"}
        )
        for i, word in enumerate(record.words):
            for j, morph in enumerate(word.morphs):
                if morph.gloss is not None:
                    ET.SubElement(
                        gloss_tier,
                        "item",
                        {"id": f"r{n}.g{i}.{j}", "alignment": f"r{n}.m{i}.{j}"},
                    ).text = morph.gloss
        translations = ET.SubElement(igt, "tier", {"id": f"r{n}.tt", "type": "translations"})
        for key, values in record.translations.items():
            for value in values:
                item = ET.SubElement(translations, "item")
                if key != "und":
                    item.set(_XML_LANG, key)
                item.text = value
    # ``encoding="unicode"`` returns ``str`` (the test-helper contract); the XML
    # declaration would make it bytes, and `XigtXmlReader.read` takes bytes only,
    # so round-trip callers ``str.encode("utf-8")`` explicitly.
    return ET.tostring(root, encoding="unicode")
