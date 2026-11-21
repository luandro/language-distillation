"""Generic normalization profiles (M2 WP2.5). Language-specific profiles live under languages/."""

from typing import ClassVar

from langpipe.normalization.base import NormalizationProfile, NormalizationRule, RuleChainProfile
from langpipe.normalization.rules import NfcRule, WhitespaceRule


class UnicodeNfcProfile(RuleChainProfile):
    name: ClassVar[str] = "unicode_nfc"
    version: ClassVar[str] = "1.0.0"
    rules: ClassVar[tuple[NormalizationRule, ...]] = (NfcRule(),)


class DefaultTextProfile(RuleChainProfile):
    name: ClassVar[str] = "default_text"
    version: ClassVar[str] = "0.1.0"
    rules: ClassVar[tuple[NormalizationRule, ...]] = (NfcRule(), WhitespaceRule())


UNICODE_NFC_PROFILE = UnicodeNfcProfile()
DEFAULT_TEXT_PROFILE = DefaultTextProfile()

# Consumers build their registry from this tuple; languages/base.py owns the final registry (WP2.7).
GENERIC_NORMALIZATION_PROFILES: tuple[NormalizationProfile, ...] = (
    UNICODE_NFC_PROFILE,
    DEFAULT_TEXT_PROFILE,
)
