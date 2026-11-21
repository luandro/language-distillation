"""CLDF (Cross-Linguistic Data Formats) Dictionary Exporter (ADR-0003 & ADR-0016).

Serializes LKB lexicon into standard CLDF Dictionary component CSVs + metadata.json:
- entries.csv: ID, Headword, Part_Of_Speech, Language_ID, Lexical_Class
- senses.csv: ID, Entry_ID, Description (Gloss), Semantic_Domain, Valence
- examples.csv: ID, Sense_ID, Primary_Text, Translated_Text, Reference
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class CldfDictionaryExporter:
    """Exports language knowledge base entries to CLDF Dictionary tables."""

    def __init__(self, target_lang: str = "und", contact_lang: str = "por") -> None:
        self.target_lang = target_lang
        self.contact_lang = contact_lang

    def export(
        self,
        lexicon_entries: list[dict[str, Any]],
        output_dir: Path | str,
    ) -> dict[str, str]:
        """Write CLDF Dictionary tables into output directory."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        entries_csv = out / "entries.csv"
        senses_csv = out / "senses.csv"
        examples_csv = out / "examples.csv"
        metadata_json = out / "Dictionary-metadata.json"

        entries_rows = []
        senses_rows = []
        examples_rows = []

        for e_idx, entry in enumerate(lexicon_entries):
            hw = entry.get("headword") or entry.get("lemma")
            if not hw:
                continue

            entry_id = f"entry_{e_idx + 1}"
            pos = entry.get("pos", "noun")
            audit = entry.get("audit") or {}
            lex_class = audit.get("lexical_class", "lemma")

            entries_rows.append(
                {
                    "ID": entry_id,
                    "Headword": hw,
                    "Part_Of_Speech": pos,
                    "Language_ID": self.target_lang,
                    "Lexical_Class": lex_class,
                }
            )

            # Sense
            sense_id = f"sense_{e_idx + 1}_1"
            glosses = entry.get(f"glosses_{self.contact_lang}") or entry.get("glosses") or []
            if isinstance(glosses, list):
                gloss_str = ", ".join(glosses)
            else:
                gloss_str = str(entry.get("trans", ""))
            sem = entry.get("semantics") or {}

            senses_rows.append(
                {
                    "ID": sense_id,
                    "Entry_ID": entry_id,
                    "Description": gloss_str,
                    "Semantic_Domain": sem.get("primary_domain", "general"),
                    "Valence": sem.get("valence", "unknown"),
                    "Inalienability": sem.get("inalienability", "unknown"),
                }
            )

            # Examples / Citations
            citations = entry.get("citations") or []
            for c_idx, cit in enumerate(citations[:3]):
                ex_id = f"ex_{e_idx + 1}_{c_idx + 1}"
                src = cit.get("source_text") or cit.get("target_text", "")
                ref_txt = cit.get("reference_text") or cit.get("trans", "")
                reference = cit.get("source_ref") or cit.get("reference", "")

                if src:
                    examples_rows.append(
                        {
                            "ID": ex_id,
                            "Sense_ID": sense_id,
                            "Primary_Text": src,
                            "Translated_Text": ref_txt,
                            "Reference": reference,
                        }
                    )

        # Write CSV files
        self._write_csv(
            entries_csv,
            ["ID", "Headword", "Part_Of_Speech", "Language_ID", "Lexical_Class"],
            entries_rows,
        )
        self._write_csv(
            senses_csv,
            ["ID", "Entry_ID", "Description", "Semantic_Domain", "Valence", "Inalienability"],
            senses_rows,
        )
        self._write_csv(
            examples_csv,
            ["ID", "Sense_ID", "Primary_Text", "Translated_Text", "Reference"],
            examples_rows,
        )

        # Write CLDF metadata.json
        meta = {
            "@context": ["http://www.w3.org/ns/csvw", {"@language": "en"}],
            "dc:conformsTo": "http://cldf.clld.org/v1.0/terms.rdf#Dictionary",
            "dc:title": f"Language Knowledge Base Dictionary ({self.target_lang})",
            "tables": [
                {
                    "url": "entries.csv",
                    "dc:conformsTo": "http://cldf.clld.org/v1.0/terms.rdf#EntryTable",
                    "tableSchema": {
                        "columns": [
                            {"name": "ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#id"},
                            {
                                "name": "Headword",
                                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#name",
                            },
                            {
                                "name": "Part_Of_Speech",
                                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#partOfSpeech",
                            },
                            {
                                "name": "Language_ID",
                                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#languageReference",
                            },
                            {"name": "Lexical_Class"},
                        ]
                    },
                },
                {
                    "url": "senses.csv",
                    "dc:conformsTo": "http://cldf.clld.org/v1.0/terms.rdf#SenseTable",
                    "tableSchema": {
                        "columns": [
                            {"name": "ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#id"},
                            {
                                "name": "Entry_ID",
                                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#entryReference",
                            },
                            {
                                "name": "Description",
                                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#description",
                            },
                            {"name": "Semantic_Domain"},
                            {"name": "Valence"},
                            {"name": "Inalienability"},
                        ]
                    },
                },
                {
                    "url": "examples.csv",
                    "dc:conformsTo": "http://cldf.clld.org/v1.0/terms.rdf#ExampleTable",
                    "tableSchema": {
                        "columns": [
                            {"name": "ID", "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#id"},
                            {
                                "name": "Sense_ID",
                                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#senseReference",
                            },
                            {
                                "name": "Primary_Text",
                                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#primaryText",
                            },
                            {
                                "name": "Translated_Text",
                                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#translatedText",
                            },
                            {"name": "Reference"},
                        ]
                    },
                },
            ],
        }
        metadata_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        return {
            "entries_csv": str(entries_csv),
            "senses_csv": str(senses_csv),
            "examples_csv": str(examples_csv),
            "metadata_json": str(metadata_json),
        }

    def _write_csv(self, path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
