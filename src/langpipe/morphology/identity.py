"""Morpheme canonical identity key calculation (M5-PLAN §7.1-8, ADR-0017 §8)."""

import unicodedata
from collections.abc import Mapping, Sequence

from langpipe.domain.enums import MorphRole
from langpipe.domain.hashing import canonical_json, sha256_bytes


def morpheme_identity_key(
    language: str,
    role: MorphRole,
    canonical_form: str,
    glosses: Mapping[str, Sequence[str]] | None = None,
    gloss_labels: Sequence[str] = (),
) -> str:
    """Canonical sha256 identity digest for a morpheme hypothesis within a run.

    Payload: ``(language, bound|free, NFC form, lexical glosses | sorted grammatical labels
    | UNKNOWN)``.
    """
    if role is MorphRole.ROOT:
        bound_or_free = "free"
    elif role in (
        MorphRole.CLITIC,
        MorphRole.UNKNOWN_BOUND,
        MorphRole.INFLECTIONAL_AFFIX,
        MorphRole.DERIVATIONAL_AFFIX,
        MorphRole.BOUND_LEXICAL,
    ):
        bound_or_free = "bound"
    else:
        bound_or_free = "unknown"

    nfc_form = unicodedata.normalize("NFC", canonical_form)

    meaning: object
    if glosses:
        entries: list[str] = []
        for lang_code in sorted(glosses):
            for gloss in sorted(glosses[lang_code]):
                entries.append(f"{lang_code}:{gloss}")
        meaning = entries if entries else "UNKNOWN"
    elif gloss_labels:
        meaning = sorted(gloss_labels)
    else:
        meaning = "UNKNOWN"

    payload = [language, bound_or_free, nfc_form, meaning]
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


__all__ = ["morpheme_identity_key"]
