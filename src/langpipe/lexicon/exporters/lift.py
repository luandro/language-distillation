"""LIFT (Lexicon Interchange Format) XML Exporter for SIL FieldWorks and WeSay (WP 1.4).

Conforms to SIL LIFT 0.13 specification (ADR-0003). Emits clean, validated dictionary
entries with lexical units, senses, grammatical categories, glosses, semantic domains,
and attested corpus examples.

Strict language-isolation: Completely parameterized by language codes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class LiftExporter:
    """Exports language knowledge base entries to standard LIFT XML format."""

    def __init__(self, target_lang: str = "und", contact_lang: str = "por") -> None:
        self.target_lang = target_lang
        self.contact_lang = contact_lang

    def export(
        self,
        lexicon_entries: list[dict[str, Any]],
        output_path: Path | str,
        producer: str = "langpipe-lkb-v1",
    ) -> Path:
        """Serialize entries into LIFT XML document."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        lift_root = ET.Element(
            "lift",
            {
                "version": "0.13",
                "producer": producer,
            },
        )

        # Header with fields
        header = ET.SubElement(lift_root, "header")
        fields = ET.SubElement(header, "fields")
        f_sem = ET.SubElement(fields, "field", {"tag": "semantic-domain"})
        ET.SubElement(f_sem, "form", {"lang": "en"}).text = "SIL RapidWords Domain"

        for entry in lexicon_entries:
            hw = entry.get("headword") or entry.get("lemma")
            if not hw:
                continue

            entry_el = ET.SubElement(lift_root, "entry", {"id": f"{self.target_lang}_{hw}"})

            # Lexical unit (the headword in target language)
            lex_unit = ET.SubElement(entry_el, "lexical-unit")
            form_el = ET.SubElement(lex_unit, "form", {"lang": self.target_lang})
            text_el = ET.SubElement(form_el, "text")
            text_el.text = hw

            # Sense
            sense_el = ET.SubElement(entry_el, "sense")

            # Grammatical info (POS)
            pos = entry.get("pos", "noun")
            ET.SubElement(sense_el, "grammatical-info", {"value": pos})

            # Gloss in contact language
            glosses = entry.get(f"glosses_{self.contact_lang}") or entry.get("glosses") or []
            if isinstance(glosses, list) and glosses:
                gloss_text = ", ".join(glosses)
            elif entry.get("trans"):
                gloss_text = str(entry["trans"])
            else:
                gloss_text = ""

            if gloss_text:
                g_el = ET.SubElement(sense_el, "gloss", {"lang": self.contact_lang})
                t_el = ET.SubElement(g_el, "text")
                t_el.text = gloss_text

            # Semantic domain field if present
            sem = entry.get("semantics") or {}
            domain = sem.get("primary_domain")
            if domain and domain != "general":
                field_el = ET.SubElement(sense_el, "field", {"type": "semantic-domain"})
                f_form = ET.SubElement(field_el, "form", {"lang": "en"})
                ET.SubElement(f_form, "text").text = domain

            # Attested citations / examples
            citations = entry.get("citations") or []
            for cit in citations[:3]:  # Top 3 attested examples
                src_txt = cit.get("source_text") or cit.get("target_text")
                trans_txt = cit.get("reference_text") or cit.get("trans")
                ref = cit.get("source_ref") or cit.get("reference", "")

                if src_txt:
                    ex_el = ET.SubElement(sense_el, "example")
                    ex_form = ET.SubElement(ex_el, "form", {"lang": self.target_lang})
                    ET.SubElement(ex_form, "text").text = src_txt

                    if trans_txt:
                        tr_el = ET.SubElement(ex_el, "translation")
                        tr_form = ET.SubElement(tr_el, "form", {"lang": self.contact_lang})
                        ET.SubElement(tr_form, "text").text = trans_txt

                    if ref:
                        ET.SubElement(ex_el, "source").text = ref

        # Write formatted XML
        tree = ET.ElementTree(lift_root)
        ET.indent(tree, space="  ", level=0)
        tree.write(str(out), encoding="utf-8", xml_declaration=True)
        return out
