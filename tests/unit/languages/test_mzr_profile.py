import unicodedata

from langpipe.languages.base import (
    LANGUAGE_PROFILES,
    NORMALIZATION_PROFILES,
    TOKENIZERS,
    LanguageProfile,
    profile_for,
)
from langpipe.languages.mzr.profile import (
    MZR_INVENTORY,
    MZR_PROFILE,
    MaruboPilotTokenizer,
    MaruboStandardProfile,
)
from langpipe.text.registry import versioned_name


def test_mzr_profile_registered_and_versioned() -> None:
    from langpipe.languages.mzr.grammar_profile import MZR_GRAMMAR_PROFILE
    from langpipe.languages.mzr.lexicon_profile import MZR_LEXICON_PROFILE
    from langpipe.languages.mzr.profile import (
        MZR_CHANT_PROVENANCES,
        MZR_HARVESTED_SOURCES,
        MZR_MORPHOLOGY,
    )

    assert (
        LanguageProfile(
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
        == MZR_PROFILE
    )
    assert LANGUAGE_PROFILES["mzr"] is MZR_PROFILE
    assert profile_for("mzr") is MZR_PROFILE
    assert versioned_name(MaruboStandardProfile()) == "marubo_standard@0.1.0"
    assert versioned_name(MaruboPilotTokenizer()) == "marubo_pilot@0.1.0"
    assert NORMALIZATION_PROFILES.get("marubo_standard@0.1.0").name == "marubo_standard"
    assert TOKENIZERS.get("marubo_pilot@0.1.0").name == "marubo_pilot"


def test_mzr_profile_versions_pinned_in_registries() -> None:
    assert "marubo_standard@0.1.0" in NORMALIZATION_PROFILES.names()
    assert "marubo_pilot@0.1.0" in TOKENIZERS.names()
    assert "default_text@0.1.0" in NORMALIZATION_PROFILES.names()
    assert "whitespace_punct@0.1.0" in TOKENIZERS.names()


def test_shipped_inventory_is_unverified_and_empty() -> None:
    assert MZR_INVENTORY.language == "mzr"
    assert MZR_INVENTORY.status == "unverified"
    assert MZR_INVENTORY.characters == ()
    assert MZR_INVENTORY.digraphs == ()
    assert MZR_INVENTORY.reviewed_by is None


def test_mzr_nfc_unifies_decomposed_nasal_vowels() -> None:
    profile = MaruboStandardProfile()
    decomposed = unicodedata.normalize("NFD", "shovimakĩ")
    precomposed = unicodedata.normalize("NFC", "shovimakĩ")

    assert decomposed != precomposed
    assert profile.normalize(decomposed).normalized == profile.normalize(precomposed).normalized


def test_mzr_tokenizer_keeps_hyphen_attached_suffix() -> None:
    surfaces = [tok.surface for tok in MaruboPilotTokenizer().tokenize("mabi-ki wesa-ra")]

    assert surfaces == ["mabi-ki", "wesa-ra"]


def test_mzr_profile_does_not_split_listed_clitic_examples() -> None:
    surfaces = [tok.surface for tok in MaruboPilotTokenizer().tokenize("txipo shovimakĩ")]

    assert surfaces == ["txipo", "shovimakĩ"]


def test_mzr_variants_remain_distinct() -> None:
    profile = MaruboStandardProfile()

    assert profile.normalize("kanu").normalized != profile.normalize("kanú").normalized


def test_mzr_profile_rules_are_nfc_then_whitespace() -> None:
    assert [rule.name for rule in MaruboStandardProfile.rules] == ["nfc", "whitespace"]
