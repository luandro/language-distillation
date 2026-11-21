"""Language profile registry. Profiles are data; registered profiles are added in WP2.7.

Final ``NORMALIZATION_PROFILES`` and ``TOKENIZERS`` registries are composed here from the generic
components plus every language package's exported components (M2 WP2.6). The language-package
import is deferred into ``_build_registries`` to break the import cycle with ``languages/base.py``.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from langpipe.domain.hashing import canonical_json
from langpipe.normalization.base import NormalizationProfile
from langpipe.normalization.profiles import GENERIC_NORMALIZATION_PROFILES
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.base import Tokenizer
from langpipe.tokenization.registry import GENERIC_TOKENIZERS


@dataclass(frozen=True)
class ReviewAuthorityGrant:
    """One reviewer authorization configured inside a language profile (ADR-0013 §4).

    Structured profile data, not code: a deployment grants review authority by listing
    these on its language profiles. A profile with no grants confers no authority —
    the review service fails closed (M4-PLAN C3).
    """

    reviewer_id: str
    role: str
    languages: tuple[str, ...]
    # None = the authorization is not domain-scoped; a scoped grant says nothing
    # about untagged objects.
    domains: tuple[str, ...] | None = None


@dataclass(frozen=True)
class MorphologyProfile:
    """Language-specific morphology parameters (ADR-0017 scope fence).

    Boundary marks, unknown-gloss markers, Toolbox marker aliases and stem-length
    limits live here and only here; generic pipeline code reads the profile and
    must never hardcode a language-specific value. Values are working assumptions
    until verified against the primary description (`docs/languages/<iso>.md`).
    """

    boundary_marks: tuple[str, ...] = ("-", "=")
    clitic_marks: tuple[str, ...] = ("=",)
    unknown_gloss_markers: tuple[str, ...] = ("***", "?", "??")
    toolbox_markers: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "text": ("\\t", "\\tx"),
            "morphs": ("\\m", "\\mb"),
            "glosses": ("\\g", "\\ge"),
            "translation": ("\\f", "\\ft"),
        }
    )
    min_stem_length: int = 2
    grammatical_label_pattern: str = r"^[A-Z0-9]+$"


@dataclass(frozen=True)
class LexiconProfile:
    """Language-specific lexicon parameters (foreign letters, names, clitic endings)."""

    foreign_letters: frozenset[str] = frozenset()
    clitic_endings: tuple[str, ...] = ()
    conventional_names: frozenset[str] = frozenset()
    affix_inventory: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GrammarProfile:
    """Language-specific grammatical parameters (alignment, case, TAM, word order)."""

    alignment_type: str = "nominative_accusative"
    default_word_order: str = "SOV"
    ergative_suffixes: tuple[str, ...] = ()
    absolutive_suffixes: tuple[str, ...] = ("",)
    dative_suffixes: tuple[str, ...] = ()
    genitive_suffixes: tuple[str, ...] = ()
    negation_suffixes: tuple[str, ...] = ()
    interrogative_suffixes: tuple[str, ...] = ()
    imperative_suffixes: tuple[str, ...] = ()
    transitive_tam_suffixes: tuple[str, ...] = ()
    intransitive_tam_suffixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DerivedSource:
    """One harvested parallel file and the derived-row artifact built from it (ADR-0026).

    ``lines_file``, ``derived_file`` and ``provenance`` are data: they name real harvested
    artifacts, and the provenance string is written into every derived row's lineage. A
    language profile owns them so that generic builder code never carries a language- or
    corpus-specific identifier (ADR-0028).
    """

    lines_file: str
    derived_file: str
    provenance: str


@dataclass(frozen=True)
class HarvestedSources:
    """Harvested parallel sources a language profile declares for derived-row building.

    ``stanza`` groups printed two-column blocks; ``sentence`` merges numbered lines up to a
    sentence end on both sides. ``stanza_pdf``/``stanza_pages`` locate where the stanza table
    is re-read to verify the harvested rows against the printed page.
    """

    stanza: DerivedSource | None = None
    sentence: DerivedSource | None = None
    stanza_pdf: str = ""
    stanza_pages: tuple[int, int] | None = None


@dataclass(frozen=True)
class LanguageProfile:
    language: str  # ISO 639-3
    name: str  # e.g. "generic"
    version: str  # e.g. "0.1.0"
    normalization: str  # versioned name in NORMALIZATION_PROFILES
    tokenizer: str  # versioned name in TOKENIZERS
    review_authority: tuple[ReviewAuthorityGrant, ...] = ()
    morphology: MorphologyProfile = field(default_factory=MorphologyProfile)
    lexicon: LexiconProfile = field(default_factory=LexiconProfile)
    grammar: GrammarProfile = field(default_factory=GrammarProfile)
    # Provenances whose rows are ritual chant: a record without an explicit register label
    # inherits the chant register from them. Source data, so it lives on the profile.
    chant_provenances: tuple[str, ...] = ()
    harvested_sources: HarvestedSources = field(default_factory=HarvestedSources)


GENERIC_PROFILE = LanguageProfile(
    "und", "generic", "0.1.0", "default_text@0.1.0", "whitespace_punct@0.1.0"
)


def _build_registries() -> tuple[
    VersionedRegistry[NormalizationProfile],
    VersionedRegistry[Tokenizer],
    dict[str, LanguageProfile],
]:
    from langpipe.languages.mzr.profile import (
        MZR_PROFILE,
        MaruboPilotTokenizer,
        MaruboStandardProfile,
    )

    normalization = VersionedRegistry((*GENERIC_NORMALIZATION_PROFILES, MaruboStandardProfile()))
    tokenizers = VersionedRegistry((*GENERIC_TOKENIZERS, MaruboPilotTokenizer()))
    return normalization, tokenizers, {"mzr": MZR_PROFILE}


NORMALIZATION_PROFILES, TOKENIZERS, _REGISTERED_PROFILES = _build_registries()

LANGUAGE_PROFILES: Mapping[str, LanguageProfile] = _REGISTERED_PROFILES


def profile_for(language: str) -> LanguageProfile:
    return LANGUAGE_PROFILES.get(language, GENERIC_PROFILE)


def profile_identity(profile: Any, default_language: str | None = None) -> str:
    """Stable string identity or digest for any language or morphology profile."""
    if isinstance(profile, str):
        lp = profile_for(profile)
        return f"{lp.name}@{lp.version}"
    if isinstance(profile, LanguageProfile):
        return f"{profile.name}@{profile.version}"
    if isinstance(profile, MorphologyProfile):
        payload = {
            "boundary_marks": list(profile.boundary_marks),
            "clitic_marks": list(profile.clitic_marks),
            "unknown_gloss_markers": list(profile.unknown_gloss_markers),
            "toolbox_markers": {k: list(v) for k, v in sorted(profile.toolbox_markers.items())},
            "min_stem_length": profile.min_stem_length,
            "grammatical_label_pattern": profile.grammatical_label_pattern,
        }
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]
        return f"morphology_profile:{digest}"
    if profile is not None:
        name = getattr(profile, "name", type(profile).__name__)
        version = getattr(profile, "version", "0.1.0")
        return f"{name}@{version}"
    lp = profile_for(default_language or "und")
    return f"{lp.name}@{lp.version}"
