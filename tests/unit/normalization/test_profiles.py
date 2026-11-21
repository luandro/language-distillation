from langpipe.normalization.profiles import (
    DEFAULT_TEXT_PROFILE,
    GENERIC_NORMALIZATION_PROFILES,
    UNICODE_NFC_PROFILE,
)
from langpipe.text.registry import VersionedRegistry, versioned_name


def test_generic_profile_versioned_names_are_pinned() -> None:
    assert versioned_name(UNICODE_NFC_PROFILE) == "unicode_nfc@1.0.0"
    assert versioned_name(DEFAULT_TEXT_PROFILE) == "default_text@0.1.0"


def test_generic_profiles_are_a_tuple_of_shipped_instances() -> None:
    assert isinstance(GENERIC_NORMALIZATION_PROFILES, tuple)
    assert GENERIC_NORMALIZATION_PROFILES == (UNICODE_NFC_PROFILE, DEFAULT_TEXT_PROFILE)
    assert all(
        profile is shipped
        for profile, shipped in zip(
            GENERIC_NORMALIZATION_PROFILES,
            (UNICODE_NFC_PROFILE, DEFAULT_TEXT_PROFILE),
            strict=True,
        )
    )


def test_consumer_can_build_registry_from_generic_profiles() -> None:
    registry = VersionedRegistry(GENERIC_NORMALIZATION_PROFILES)

    assert registry.names() == ["default_text@0.1.0", "unicode_nfc@1.0.0"]
    assert registry.get("default_text@0.1.0") is DEFAULT_TEXT_PROFILE
    assert registry.get("unicode_nfc") is UNICODE_NFC_PROFILE


def test_profile_rule_chains() -> None:
    assert [rule.name for rule in UNICODE_NFC_PROFILE.rules] == ["nfc"]
    assert [rule.name for rule in DEFAULT_TEXT_PROFILE.rules] == ["nfc", "whitespace"]


def test_no_case_folding_punctuation_mapping_or_compatibility_mapping() -> None:
    # Uppercase, curly apostrophe, hyphen, precomposed Á and the compatibility ligature U+FB01 must
    # all survive: M2 has no case folding, quote/punctuation mapping, or NFKC.
    raw = "Ka’-BÁﬁ"

    assert DEFAULT_TEXT_PROFILE.normalize(raw).normalized == raw
