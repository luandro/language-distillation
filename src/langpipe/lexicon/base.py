"""Stage 6 lexical candidate induction protocol and DTOs (M4-PLAN §6 WP4.5, ADR-0013).

Pure in-memory contracts between the induction service (WP4.7) and its adapters. Nothing
here persists, reads governance policy or carries credentials: run ids, language tags,
alignment references and surfaces already validated by earlier stages.

The protocol is deliberately asymmetry-free in one direction only — a contact language
(Invariants 8 and 9). `contact_language` names the language whose aligned forms are recorded
as meaning hypotheses (`Sense.glosses`); an adapter never writes a contact form as a
target-language lexical form.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from langpipe.domain.models.alignment import TokenAlignmentEdge
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.lexical import Concept, FormLexemeLink, Lexeme, Sense
from langpipe.domain.models.observation import Form, Segment, TokenOccurrence
from langpipe.lexicon.scoring import LexicalScorePolicy


@dataclass(frozen=True)
class LexicalInductionInput:
    """One pinned induction request: the Stage 5 evidence and its resolved references.

    `alignment_edges` are the edges selected from one succeeded token-alignment run; the
    token, form and segment maps are those objects resolved by id (or, for forms, by text
    when a token carries no `form_id`). `run_id` is the producing Stage 6 run, so lineage
    records provenance rather than an arbitrary actor.

    A wordlist induction (WP4.6) pins its raw object instead: `data` holds the exact bytes
    read from the immutable raw store, `source_id` names the registered source the object
    belongs to and `source_object_id` the object itself. `independence_group` lets a caller
    record that several wordlists share one provenance (or that one wordlist is its own
    axis), defaulting to the source.
    """

    run_id: str
    target_language: str
    contact_language: str
    alignment_edges: Sequence[TokenAlignmentEdge] = ()
    source_tokens: Mapping[str, TokenOccurrence] = field(default_factory=dict)
    target_tokens: Mapping[str, TokenOccurrence] = field(default_factory=dict)
    source_forms: Mapping[str, Form] = field(default_factory=dict)
    target_forms: Mapping[str, Form] = field(default_factory=dict)
    segments: Mapping[str, Segment] | None = None
    policy: LexicalScorePolicy | None = None
    data: bytes = b""
    source_id: str | None = None
    source_object_id: str | None = None
    independence_group: str | None = None


@dataclass(frozen=True)
class LexicalInductionOutput:
    """Candidate knowledge, its supporting evidence and its lineage. Never validated truth.

    `lexemes` and `senses` are hypotheses (`LifecycleStatus.CANDIDATE` at most `SUPPORTED`;
    ADR-0013 §3). `evidence_items` document why each hypothesis exists and `lineage_edges`
    carries the `derived_from` relations to the producing run and the alignment edges.
    """

    lexemes: list[Lexeme] = field(default_factory=list)
    form_links: list[FormLexemeLink] = field(default_factory=list)
    senses: list[Sense] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    lineage_edges: list[LineageEdge] = field(default_factory=list)


class LexicalInducer(Protocol):
    """A versioned lexical candidate inducer (`name@version`, resolved by method id).

    Implementations are pure with respect to the request: they consume the pinned input,
    return the output and leave every persistence and governance decision to the caller
    (WP4.7). An inducer MUST NOT create `validated` status, MUST NOT write a contact form as
    a target-language form, and MUST NOT segment a whole token (M4 scope fence, ADR-0013 §2).
    """

    method_id: str

    def induce(self, input: LexicalInductionInput) -> LexicalInductionOutput:
        """Induce candidate lexical knowledge from one pinned alignment request."""
        ...


__all__ = [
    "LexicalInducer",
    "LexicalInductionInput",
    "LexicalInductionOutput",
]
