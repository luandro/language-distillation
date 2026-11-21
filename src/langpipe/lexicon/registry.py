"""Lexical inducer registry keyed by ``name@version`` (M4-PLAN §6 WP4.5, ADR-0013).

The Stage 6 service (WP4.7) resolves a method reference to a registered `LexicalInducer`
instead of importing adapters directly, so adding an inducer never changes its callers. A
``name@version`` reference pins that exact version; a bare name resolves to the latest
registered numeric version, matching the other registries (M2 E3).

Unknown references raise the typed :class:`UnsupportedMethod`, whose message carries a fixed
diagnostic and never echoes the requested method or any caller payload.
"""

from typing import cast

from langpipe.lexicon.adapters.alignment import AlignmentLexicalInducer
from langpipe.lexicon.adapters.cldf import CLDFLexicalInducer
from langpipe.lexicon.adapters.wordlist import WordlistAdapter
from langpipe.lexicon.base import LexicalInducer

METHOD_ALIGNMENT_COOCCURRENCE: str = "alignment_cooccurrence"
METHOD_CLDF_LEXICAL: str = "cldf_lexical"
METHOD_WORDLIST_TABULAR: str = "wordlist_tabular"

# `name`/`version` live on the adapter for `versioned_name`; the protocol itself carries only
# `method_id` and `induce`, so each entry is declared protocol-typed on registration.
INDUCERS: tuple[LexicalInducer, ...] = (
    cast(LexicalInducer, AlignmentLexicalInducer()),
    cast(LexicalInducer, CLDFLexicalInducer()),
    cast(LexicalInducer, WordlistAdapter()),
)

_REGISTRY: dict[str, LexicalInducer] = {inducer.method_id: inducer for inducer in INDUCERS}


class UnsupportedMethod(Exception):
    """No registered lexical inducer matches the requested method reference."""

    def __init__(self) -> None:
        super().__init__("unsupported lexical induction method")


def _version_key(reference: str) -> tuple[int, ...]:
    # Same dotted-integer subset the other registries accept (M2 E3).
    return tuple(int(part) for part in reference.rsplit("@", 1)[1].split("."))


def lexical_induction_methods() -> list[str]:
    """Every registered method reference, sorted."""
    return sorted(_REGISTRY)


def get_lexical_inducer(method: str) -> LexicalInducer:
    """Resolve a method reference to its registered inducer.

    ``name@version`` pins exactly one version; a bare name selects the highest registered
    version of that name. Anything unresolvable fails with :class:`UnsupportedMethod`.
    """
    if "@" in method:
        found = _REGISTRY.get(method)
        if found is not None:
            return found
        raise UnsupportedMethod()
    matches = [item for item in _REGISTRY.values() if item.method_id.rsplit("@", 1)[0] == method]
    if matches:
        return max(matches, key=lambda item: _version_key(item.method_id))
    raise UnsupportedMethod()


__all__ = [
    "INDUCERS",
    "METHOD_ALIGNMENT_COOCCURRENCE",
    "METHOD_CLDF_LEXICAL",
    "METHOD_WORDLIST_TABULAR",
    "UnsupportedMethod",
    "get_lexical_inducer",
    "lexical_induction_methods",
]
