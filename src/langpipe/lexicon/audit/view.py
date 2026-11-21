"""Consumer LexiconView providing scoped dictionary access (ADR-0021)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langpipe.lexicon.audit.model import LexicalClass, UseScope

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


class LexiconView:
    """Scoped view over the Language Knowledge Base lexicon."""

    def __init__(self, dictionary_data: dict[str, Any], view: str = "clean") -> None:
        self.raw_data = dictionary_data
        self.view_name = view.strip().lower()
        self.language_code = dictionary_data.get("language_code", "und")
        self.language_name = dictionary_data.get("language_name", "Unknown")
        self.contact_language = dictionary_data.get("contact_language", "por")

        all_entries: list[dict[str, Any]] = dictionary_data.get("lexicon", [])
        self.entries = self._filter_entries(all_entries, self.view_name)
        self.stems = {e.get("headword", "").lower(): e for e in self.entries if e.get("headword")}

    def _filter_entries(self, entries: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
        """Filter entries according to requested view scope."""
        if view == "all":
            return entries

        filtered: list[dict[str, Any]] = []
        for e in entries:
            audit = e.get("audit", {})
            use_scopes = audit.get("use_scopes", [])
            lexical_class = audit.get("lexical_class", LexicalClass.LEMMA.value)

            if view in ("clean", "strict"):
                # Clean view: must have GROUNDING use scope
                # If entry hasn't been audited yet, default to including only if status == validated
                if audit:
                    if UseScope.GROUNDING.value in use_scopes:
                        filtered.append(e)
                else:
                    filtered.append(e)

            elif view == "names":
                if lexical_class == LexicalClass.PROPER_NOUN.value:
                    filtered.append(e)

            elif view == "quarantine" and audit and UseScope.GROUNDING.value not in use_scopes:
                filtered.append(e)

        return filtered

    @classmethod
    def load(
        cls,
        lang_code: str,
        view: str = "clean",
        dict_path: Path | None = None,
    ) -> LexiconView:
        """Load lexicon view from canonical export path or audited file."""
        if dict_path is None:
            dict_path = ROOT / "exports" / lang_code / "dictionary.json"

        if not dict_path.exists():
            return cls({"language_code": lang_code, "lexicon": []}, view=view)

        with open(dict_path, encoding="utf-8") as f:
            data = json.load(f)

        return cls(data, view=view)
