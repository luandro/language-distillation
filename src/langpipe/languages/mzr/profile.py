"""Marúbo (``mzr``) pilot profile, normalizer and tokenizer stub (M2 WP2.7).

No morphology, clitic list, stem or suffix inventory is encoded. Clitic boundaries stay M5
``MorphAnalysis`` candidates; the tokenizer never splits words (ADR-0010, E2).
"""

from pathlib import Path
from typing import ClassVar

from langpipe.languages.base import (
    DerivedSource,
    HarvestedSources,
    LanguageProfile,
    MorphologyProfile,
)
from langpipe.languages.inventory import Inventory, inventory_diagnostics, load_inventory
from langpipe.normalization.base import NormalizationResult, NormalizationRule, RuleChainProfile
from langpipe.normalization.rules import NfcRule, WhitespaceRule
from langpipe.tokenization.whitespace_punct import WhitespacePunctTokenizer

MZR_INVENTORY: Inventory = load_inventory(Path(__file__).with_name("inventory.yaml"))


class MaruboStandardProfile(RuleChainProfile):
    name: ClassVar[str] = "marubo_standard"
    version: ClassVar[str] = "0.1.0"
    rules: ClassVar[tuple[NormalizationRule, ...]] = (NfcRule(), WhitespaceRule())

    def normalize(self, raw: str) -> NormalizationResult:
        result = super().normalize(raw)
        diagnostics = inventory_diagnostics(result.normalized, MZR_INVENTORY)
        if not diagnostics:
            return result
        merged = dict(result.diagnostics)
        for key, count in diagnostics.items():
            merged[key] = merged.get(key, 0) + count
        return NormalizationResult(
            raw=result.raw,
            normalized=result.normalized,
            offsets=result.offsets,
            events=result.events,
            diagnostics=merged,
        )


class MaruboPilotTokenizer(WhitespacePunctTokenizer):
    name: ClassVar[str] = "marubo_pilot"
    version: ClassVar[str] = "0.1.0"
    # Same joiners as the generic tokenizer in 0.1.0; a separate name so it can version on its own.
    joiners: ClassVar[frozenset[str]] = frozenset({"-", "‐", "'", "’"})


MZR_MORPHOLOGY = MorphologyProfile(
    # Working assumption, copied from the generic defaults (docs/languages/mzr.md
    # §Open items): boundary marks, clitic mark, unknown-gloss markers, Toolbox
    # marker aliases and the stem-length floor are unverified until the
    # primary-description and orthography reviews land. They are declared
    # explicitly here so the mzr profile versions its own morphology contract.
    boundary_marks=("-", "="),
    clitic_marks=("=",),
    unknown_gloss_markers=("***", "?", "??"),
    toolbox_markers={
        "text": ("\\t", "\\tx"),
        "morphs": ("\\m", "\\mb"),
        "glosses": ("\\g", "\\ge"),
        "translation": ("\\f", "\\ft"),
    },
    min_stem_length=2,
    grammatical_label_pattern=r"^[A-Z0-9]+$",
)

from langpipe.languages.mzr.grammar_profile import MZR_GRAMMAR_PROFILE  # noqa: E402
from langpipe.languages.mzr.lexicon_profile import MZR_LEXICON_PROFILE  # noqa: E402

MZR_STANZA_SOURCE = DerivedSource(
    # Cesarino 2018 Wenía article: a two-column printed table, grouped into stanzas and
    # verified by re-reading the layout text of the table pages.
    lines_file="cesarino_2018_wenia_parallel.jsonl",
    derived_file="cesarino_2018_wenia_stanza_derived.jsonl",
    provenance="harvested:cesarino_2018_wenia_parallel",
)

MZR_SENTENCE_SOURCE = DerivedSource(
    lines_file="zenodo_1008779_cesarino_marubo_2017_parallel.jsonl",
    derived_file="zenodo_1008779_cesarino_marubo_2017_sentence_derived.jsonl",
    provenance="harvested:zenodo_1008779_cesarino_marubo_2017_parallel",
)

MZR_HARVESTED_SOURCES = HarvestedSources(
    stanza=MZR_STANZA_SOURCE,
    sentence=MZR_SENTENCE_SOURCE,
    stanza_pdf="var/external/wenia_2018/wenia_2018.pdf",
    stanza_pages=(15, 48),
)

# Harvested sources that are ritual chant (Wenía song-poems, Cesarino 2017 chant verses).
MZR_CHANT_PROVENANCES: tuple[str, ...] = (
    MZR_STANZA_SOURCE.provenance,
    MZR_SENTENCE_SOURCE.provenance,
)

MZR_PROFILE = LanguageProfile(
    "mzr",
    "mzr_pilot",
    "0.1.0",
    "marubo_standard@0.1.0",
    "marubo_pilot@0.1.0",
    morphology=MZR_MORPHOLOGY,
    lexicon=MZR_LEXICON_PROFILE,
    grammar=MZR_GRAMMAR_PROFILE,
    chant_provenances=MZR_CHANT_PROVENANCES,
    harvested_sources=MZR_HARVESTED_SOURCES,
)
