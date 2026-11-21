"""Data models and enums for Lexicon Audit and Cleanup (ADR-0021)."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal


class LexicalClass(StrEnum):
    """Categorization of dictionary entries after audit."""

    LEMMA = "lemma"
    PROPER_NOUN = "proper_noun"
    INFLECTED_FORM = "inflected_form"
    ORTHOGRAPHIC_VARIANT = "orthographic_variant"
    LOANWORD = "loanword"
    MULTIWORD = "multiword"
    ARTIFACT = "artifact"
    UNKNOWN = "unknown"


class ProperNounKind(StrEnum):
    """Subtypes for proper nouns."""

    PERSON = "person"
    PLACE = "place"
    ETHNIC_GROUP = "ethnic_group"
    DEITY = "deity"
    OTHER = "other"


class AuditFlag(StrEnum):
    """Evidence and metadata flags assigned during lexicon audit."""

    LOW_EVIDENCE = "low_evidence"
    GLOSS_IS_NAME = "gloss_is_name"
    NATIVE_WORD_GLOSSED_WITH_NAME = "native_word_glossed_with_name"
    RECIPROCAL_SWAP = "reciprocal_swap"
    GLOSS_HUB = "gloss_hub"
    GLOSS_INFLECTED = "gloss_inflected"
    POS_SUSPECT = "pos_suspect"
    TRANSLATION_CONVENTION = "translation_convention"
    HOMOGRAPH_WITH_PORTUGUESE = "homograph_with_portuguese"


class UseScope(StrEnum):
    """Permitted downstream use scopes for an entry."""

    GROUNDING = "grounding"  # Used by GroundingValidator for Invariant 9
    SYNTHESIS_PROMPT = "synthesis_prompt"  # Sampled in LLM prompts
    DICTIONARY_EXPORT = "dictionary_export"  # Included in primary clean dictionary
    ONOMASTICON = "onomasticon"  # Included in named entities/onomasticon view


@dataclass(frozen=True)
class AuditSignal:
    """A detected rule or classifier observation."""

    rule_id: str
    source: Literal["rule", "clef"]
    value: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntryAudit:
    """Audit record for a single dictionary entry."""

    audit_id: str
    headword: str
    lexical_class: LexicalClass
    proper_noun_kind: ProperNounKind | None = None
    flags: list[AuditFlag] = field(default_factory=list)
    related_entry: str | None = None
    use_scopes: list[UseScope] = field(default_factory=list)
    signals: list[AuditSignal] = field(default_factory=list)
    review_required: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["lexical_class"] = self.lexical_class.value
        d["proper_noun_kind"] = self.proper_noun_kind.value if self.proper_noun_kind else None
        d["flags"] = [f.value if isinstance(f, AuditFlag) else str(f) for f in self.flags]
        d["use_scopes"] = [u.value if isinstance(u, UseScope) else str(u) for u in self.use_scopes]
        return d


def compute_audit_id(headword: str, ruleset_version: str = "v1") -> str:
    """Deterministic hash ID for an entry audit."""
    raw = f"{headword.strip().lower()}:{ruleset_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
