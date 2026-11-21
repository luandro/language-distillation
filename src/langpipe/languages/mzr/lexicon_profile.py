"""Marúbo (``mzr``) Lexicon Profile.

Isolates language-specific phonotactics, foreign graphemes, clitic inventory,
and known conventional names from generic pipeline code (AGENTS.md).
"""

from __future__ import annotations

# In Pano/Marúbo, foreign letters not part of native orthography.
# Note: 'c' followed by 'h' (ch) is native; solitary 'c' or 'c' before a/o/u is foreign.
MZR_FOREIGN_LETTERS: frozenset[str] = frozenset({"f", "g", "j", "l", "q", "z", "d", "b"})

# Clitic and inflectional endings commonly found in running text or alignment artifacts
MZR_CLITIC_ENDINGS: tuple[str, ...] = (
    "rasĩní",
    "rasĩni",
    "rasĩ",
    "namã",
    "katsai",
    "tishõki",
    "pa",
    "nẽ",
    "ro",
    "ni",
    "ma",
    "ki",
    "vere",
    "vai",
    "ai",
)

# Known biblical and foreign proper names frequently attested in parallel Bible corpora
MZR_CONVENTIONAL_NAMES: frozenset[str] = frozenset(
    {
        "judas",
        "iscariotes",
        "noemi",
        "elimeleque",
        "simão",
        "pedro",
        "maria",
        "madalena",
        "jesus",
        "cristo",
        "paulo",
        "saulo",
        "davi",
        "noé",
        "noe",
        "samaria",
        "nilo",
        "caldeu",
        "caldeus",
        "judeu",
        "judeus",
        "israel",
        "israelita",
        "israelitas",
        "fariseu",
        "fariseus",
        "cananeu",
        "jebuseu",
        "yavé",
        "yave",
        "moises",
        "abraão",
        "abraao",
        "belem",
        "jerusalem",
        "efrata",
        "adao",
        "adão",
        "eva_biblica",
    }
)

# Conventional affixes used in Marúbo morphology
MZR_AFFIX_INVENTORY: tuple[str, ...] = (
    "n",
    "0",
    "ai",
    "katsai",
    "vai",
    "shina",
    "nis",
    "ma",
    "tinpa",
    "ya",
    "sho",
    "nõ",
    "ki",
    "ra",
    "mis",
)

from langpipe.languages.base import LexiconProfile  # noqa: E402

MZR_LEXICON_PROFILE = LexiconProfile(
    foreign_letters=MZR_FOREIGN_LETTERS,
    clitic_endings=MZR_CLITIC_ENDINGS,
    conventional_names=MZR_CONVENTIONAL_NAMES,
    affix_inventory=frozenset(MZR_AFFIX_INVENTORY),
)
