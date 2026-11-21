"""Baseline lexical inducer ``alignment_cooccurrence@0.1.0`` (M4-PLAN §6 WP4.5, ADR-0013).

Turns symmetrized Stage 5 token alignment edges into *candidate* lexical knowledge. For each
distinct source-language orthographic form whose token co-occurs with contact-language forms
the adapter produces:

* one candidate `Lexeme` for that whole source form — never for a sub-token, and never for a
  contact form (Invariants 8 and 9; sub-token analysis is Milestone 5, ADR-0013 §2);
* one `form_lexeme` link with role ``primary_lemma``;
* one candidate `Sense` per distinct aligned contact form, whose surfaces are recorded as
  meaning hypotheses in `Sense.glosses`, so ambiguity and polysemy survive;
* two supporting `EvidenceItem`s per contributing observation: kind ``token_alignment`` for
  the token pair itself and kind ``segment_cooccurrence`` for the segment alignment group
  those tokens co-occur in, each keeping the same provenance, independence axis, polarity
  and strength as the observation it documents;
* ``derived_from`` lineage from every created object to the producing run, to each
  contributing alignment edge, to each contributing segment alignment, and to each
  supporting `EvidenceItem` (AGENTS.md invariant 4; global constraint 4).

Language separation is enforced on the resolved `Form`, never on the names of the caller's
maps: the source side of an edge must resolve to a form in the target language and the
target side to a form in the contact language (Invariants 8, 9). An edge whose endpoint form
belongs to the other language is skipped, exactly like an edge missing a token, a form or a
segment source, so nothing downstream of it is created.

Scoring and promotion are delegated to `langpipe.lexicon.scoring` (WP4.4): the policy may
raise a hypothesis from ``candidate`` to ``supported`` and can never produce ``validated``
(AGENTS.md invariant 3). A `Lexeme` is scored on every supporting item, a `Sense` only on
the items of its own gloss, so one form observed for two different meanings by one source
supports the lexeme without supporting either meaning hypothesis.

No adapter-invented linguistics: no part of speech, no morpheme split, no fusion of distinct
orthographic forms, no fabricated segment score and no invented independence source. The
same observation recorded as both a token pair and a segment co-occurrence is one
observation on one axis, never two independent sources.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from pydantic import ValidationError

from langpipe.domain.enums import (
    AlignmentDirection,
    EvidenceKind,
    EvidencePolarity,
    LifecycleStatus,
    LineageKind,
)
from langpipe.domain.errors import SchemaViolation
from langpipe.domain.ids import IdFactory, IdPrefix, new_id
from langpipe.domain.models.alignment import TokenAlignmentEdge
from langpipe.domain.models.base import DomainModel
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.lexical import FormLexemeLink, Lexeme, Sense
from langpipe.domain.models.observation import Form, Segment, TokenOccurrence
from langpipe.lexicon.base import LexicalInductionInput, LexicalInductionOutput
from langpipe.lexicon.scoring import (
    ALIGNMENT_SUPPORT,
    DEFAULT_POLICY,
    LexicalScorePolicy,
)

METHOD_ID: str = "alignment_cooccurrence@0.1.0"
PRIMARY_LEMMA_ROLE: str = "primary_lemma"

# Directions one instance consumes. The baseline is symmetrized-only: a directional link is
# a one-sided observation and never corroborates a lexical hypothesis by itself
# (EVIDENCE-AND-CONFIDENCE.md §Evidence independence).
DEFAULT_DIRECTIONS: frozenset[AlignmentDirection] = frozenset({AlignmentDirection.SYMMETRIZED})

# Deduplication key of the segment-group observation of one (form, gloss) pair: the
# alignment group the tokens co-occur in and the contact surface observed there.
_SegmentKey = tuple[str, str]


def _default_id(prefix: IdPrefix) -> str:
    return new_id(prefix)


@dataclass(frozen=True)
class _Observation:
    """One alignment-edge observation of a (source form, contact form) pair."""

    source_form: Form
    target_form: Form
    edge: TokenAlignmentEdge
    source_id: str | None
    score: float


class AlignmentLexicalInducer:
    """Induces candidate lexical hypotheses from symmetrized token alignment edges."""

    name: ClassVar[str] = "alignment_cooccurrence"
    version: ClassVar[str] = "0.1.0"
    method_id: ClassVar[str] = METHOD_ID

    def __init__(
        self,
        *,
        directions: Iterable[AlignmentDirection] = DEFAULT_DIRECTIONS,
        policy: LexicalScorePolicy | None = None,
        new_id: IdFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        selected = frozenset(directions)
        if not selected:
            raise ValueError("an inducer consumes at least one alignment direction")
        self.directions = selected
        self.policy = policy if policy is not None else DEFAULT_POLICY
        self._new_id: IdFactory = new_id if new_id is not None else _default_id
        self._clock: Callable[[], datetime] = (
            clock if clock is not None else lambda: datetime.now(UTC)
        )

    def induce(self, input: LexicalInductionInput) -> LexicalInductionOutput:
        groups = _grouped(_observations(input, self.directions))
        if not groups:
            return LexicalInductionOutput()

        policy = input.policy if input.policy is not None else self.policy
        now = self._clock()
        lexemes: list[Lexeme] = []
        form_links: list[FormLexemeLink] = []
        senses: list[Sense] = []
        evidence_items: list[EvidenceItem] = []
        lineage_edges: list[LineageEdge] = []

        for source_form_id in sorted(groups):
            group = _collapsed(groups[source_form_id])
            lexeme = _build(
                Lexeme,
                id=self._new_id(IdPrefix.LEXEME),
                language=input.target_language,
                lemma_form_id=group[0].source_form.id,
                run_id=input.run_id,
                created_at=now,
            )
            # Both required evidence kinds per contributing observation. The token-pair
            # observation is never deduplicated (one edge is one observation); the
            # segment-group observation is deduplicated per (group, gloss) so one group
            # observed by several token pairs stays one observation, and the strongest
            # observation of that group is the one recorded.
            token_evidence: list[tuple[EvidenceItem, _Observation]] = []
            retained: dict[_SegmentKey, _Observation] = {}
            order: dict[_SegmentKey, int] = {}
            for index, observation in enumerate(group):
                token_item = _token_evidence(
                    observation, lexeme.id, input.run_id, now, self._new_id
                )
                token_evidence.append((token_item, observation))
                key = (observation.edge.segment_alignment_id, observation.target_form.text)
                current = retained.get(key)
                if current is None or observation.score > current.score:
                    retained[key] = observation
                order.setdefault(key, index)
            # Mint one item per retained group in first-seen order, so the output order is
            # independent of the alignment edge order while a group keeps one observation.
            segment_evidence = [
                (
                    _segment_evidence(retained[key], lexeme.id, input.run_id, now, self._new_id),
                    key,
                )
                for key in sorted(order, key=lambda item: order[item])
            ]
            evidence: list[EvidenceItem] = [item for item, _ in token_evidence]
            evidence.extend(item for item, _ in segment_evidence)

            lexeme = _promote(lexeme, policy, evidence, input.target_language)
            lexemes.append(lexeme)
            form_links.append(
                _build(
                    FormLexemeLink,
                    id=self._new_id(IdPrefix.FORM_LEXEME),
                    form_id=group[0].source_form.id,
                    lexeme_id=lexeme.id,
                    role=PRIMARY_LEMMA_ROLE,
                    run_id=input.run_id,
                    created_at=now,
                )
            )
            evidence_items.extend(evidence)

            # Every created object points at the run that produced it and at each input
            # observation it was derived from. A `Lexeme` sees every observation of its
            # form, a `Sense` only the observations of its own gloss.
            lineage_edges.append(_edge(lexeme.id, input.run_id, input.run_id, now, self._new_id))
            for parent in sorted({observation.edge.id for observation in group}):
                lineage_edges.append(_edge(lexeme.id, parent, input.run_id, now, self._new_id))
            for parent in sorted({key[0] for key in retained}):
                lineage_edges.append(_edge(lexeme.id, parent, input.run_id, now, self._new_id))
            for item in evidence:
                lineage_edges.append(_edge(lexeme.id, item.id, input.run_id, now, self._new_id))
            # Each evidence item points at the one input observation it documents.
            for item, observation in token_evidence:
                lineage_edges.append(
                    _edge(item.id, observation.edge.id, input.run_id, now, self._new_id)
                )
            for item, key in segment_evidence:
                lineage_edges.append(_edge(item.id, key[0], input.run_id, now, self._new_id))

            for gloss in sorted({observation.target_form.text for observation in group}):
                gloss_observations = [o for o in group if o.target_form.text == gloss]
                sense = _build(
                    Sense,
                    id=self._new_id(IdPrefix.SENSE),
                    lexeme_id=lexeme.id,
                    glosses={input.contact_language: [gloss]},
                    run_id=input.run_id,
                    created_at=now,
                )
                sense_evidence = [
                    item
                    for item in evidence
                    if item.claim is not None and item.claim.get("gloss") == gloss
                ]
                sense = _promote(sense, policy, sense_evidence, input.target_language)
                senses.append(sense)
                lineage_edges.append(_edge(sense.id, lexeme.id, input.run_id, now, self._new_id))
                lineage_edges.append(_edge(sense.id, input.run_id, input.run_id, now, self._new_id))
                for parent in sorted({observation.edge.id for observation in gloss_observations}):
                    lineage_edges.append(_edge(sense.id, parent, input.run_id, now, self._new_id))
                for parent in sorted({key[0] for key in retained if key[1] == gloss}):
                    lineage_edges.append(_edge(sense.id, parent, input.run_id, now, self._new_id))
                for item in sense_evidence:
                    lineage_edges.append(_edge(sense.id, item.id, input.run_id, now, self._new_id))

        return LexicalInductionOutput(
            lexemes=lexemes,
            form_links=form_links,
            senses=senses,
            concepts=[],
            evidence_items=evidence_items,
            lineage_edges=lineage_edges,
        )


def _observations(
    data: LexicalInductionInput, directions: frozenset[AlignmentDirection]
) -> list[_Observation]:
    """Resolve every usable alignment edge into a (source form, contact form) observation.

    An edge is used only when its direction is selected, both endpoints resolve to a pinned
    token, both tokens resolve to a persisted form of their side's language and a token
    without `form_id` resolves its form by surface within that side. An endpoint form in the
    other language is rejected here: a contact form is never a target-language lemma and a
    target-language form is never a meaning hypothesis (Invariants 8, 9).
    """
    segments: Mapping[str, Segment] = data.segments or {}
    observations: list[_Observation] = []
    for edge in data.alignment_edges:
        if edge.direction not in directions:
            continue
        source = data.source_tokens.get(edge.source_token_id)
        target = data.target_tokens.get(edge.target_token_id)
        if source is None or target is None:
            continue
        source_form = _form_of(source, data.source_forms, data.target_language)
        target_form = _form_of(target, data.target_forms, data.contact_language)
        if source_form is None or target_form is None:
            continue
        observations.append(
            _Observation(
                source_form=source_form,
                target_form=target_form,
                edge=edge,
                source_id=_source_id(segments, source),
                score=edge.score if edge.score is not None else 1.0,
            )
        )
    return observations


def _form_of(token: TokenOccurrence, forms: Mapping[str, Form], language: str) -> Form | None:
    if token.form_id is not None:
        form = forms.get(token.form_id)
        # An explicit pin still names its language: a form of another language is unusable
        # on this side however the caller resolved it.
        return form if form is not None and form.language == language else None
    surface = token.normalized_surface or token.raw_surface
    for form in forms.values():
        if form.language == language and form.text == surface:
            return form
    return None


def _source_id(segments: Mapping[str, Segment], token: TokenOccurrence) -> str | None:
    """Provenance of one observation: the source of the token's segment, when it is pinned."""
    segment = segments.get(token.segment_id)
    return None if segment is None else segment.source_id


def _grouped(observations: Sequence[_Observation]) -> dict[str, list[_Observation]]:
    grouped: dict[str, list[_Observation]] = {}
    for observation in observations:
        grouped.setdefault(observation.source_form.id, []).append(observation)
    return grouped


def _collapsed(group: Sequence[_Observation]) -> list[_Observation]:
    """Collapse repeated observations of one exact (edge, gloss) pair, keeping the strongest.

    The same edge reaching one source form twice is a single observation: deduplicating by
    edge id and gloss never credits one alignment as independent corroboration.
    """
    best: dict[tuple[str, str], _Observation] = {}
    for observation in group:
        key = (observation.edge.id, observation.target_form.text)
        current = best.get(key)
        if current is None or observation.score > current.score:
            best[key] = observation
    return [best[key] for key in sorted(best)]


def _token_evidence(
    observation: _Observation, target_id: str, run_id: str, now: datetime, next_id: IdFactory
) -> EvidenceItem:
    """The token-pair observation itself (kind ``token_alignment``)."""
    return _claim(
        observation,
        EvidenceKind.TOKEN_ALIGNMENT,
        next_id(IdPrefix.EVIDENCE),
        target_id,
        run_id,
        now,
    )


def _segment_evidence(
    observation: _Observation, target_id: str, run_id: str, now: datetime, next_id: IdFactory
) -> EvidenceItem:
    """The segment-group co-occurrence observation (kind ``segment_cooccurrence``).

    Same provenance, axis, polarity and strength as the token observation: no independent
    corroboration is inferred and no segment score is fabricated.
    """
    return _claim(
        observation,
        EvidenceKind.SEGMENT_COOCCURRENCE,
        next_id(IdPrefix.EVIDENCE),
        target_id,
        run_id,
        now,
    )


def _claim(
    observation: _Observation,
    kind: EvidenceKind,
    item_id: str,
    target_id: str,
    run_id: str,
    now: datetime,
) -> EvidenceItem:
    return _build(
        EvidenceItem,
        id=item_id,
        kind=kind,
        polarity=EvidencePolarity.SUPPORTS,
        target_id=target_id,
        claim={
            "gloss": observation.target_form.text,
            "source_form": observation.source_form.text,
        },
        source_id=observation.source_id,
        run_id=run_id,
        strength={ALIGNMENT_SUPPORT: observation.score},
        created_at=now,
    )


def _edge(
    from_id: str,
    to_id: str,
    run_id: str,
    now: datetime,
    next_id: IdFactory,
) -> LineageEdge:
    return _build(
        LineageEdge,
        id=next_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run_id,
        created_at=now,
    )


def _promote[M: DomainModel](
    model: M,
    policy: LexicalScorePolicy,
    evidence: Sequence[EvidenceItem],
    target_language: str,
) -> M:
    """Attach the versioned score breakdown and the status the policy may grant.

    Candidate -> supported only: `evaluate_promotion` never returns `validated`
    (AGENTS.md invariant 3; ADR-0013 §3).
    """
    breakdown = policy.compute_score(evidence, target_language)
    status = policy.evaluate_promotion(
        LifecycleStatus.CANDIDATE, breakdown, evidence, target_language
    )
    assert status is not LifecycleStatus.VALIDATED  # invariant 3, enforced by the policy
    return model.model_copy(update={"status": status, "score_breakdown": breakdown})


def _build[M: DomainModel](model: type[M], **data: object) -> M:
    """Validate through the domain model; pydantic errors never leak field values."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise SchemaViolation() from exc


__all__ = [
    "DEFAULT_DIRECTIONS",
    "METHOD_ID",
    "PRIMARY_LEMMA_ROLE",
    "AlignmentLexicalInducer",
]
