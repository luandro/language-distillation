"""WP4.5 unit tests: lexical candidate induction protocol and baseline adapter.

Contracts under test (M4-PLAN §6 WP4.5, ADR-0013, AGENTS.md invariants 2/3/4/8/9):
- `alignment_cooccurrence@0.1.0` resolves from the registry; unknown references fail
  with a typed error that echoes neither the caller payload nor the method string;
- symmetrized token alignment edges become a candidate `Lexeme`, a `form_lexeme` link,
  candidate `Sense`s (gloss hypotheses) and supporting `EvidenceItem`s of both required
  kinds, `token_alignment` and `segment_cooccurrence`;
- contact-language forms are recorded strictly as glosses on `Sense`, never as
  target-language lexical forms and never as a lexeme lemma (Invariants 8, 9): a form in
  the wrong language is rejected on both the explicit-id and the surface path;
- whole tokens only: `wesa-ra` stays one orthographic whole; sub-token analysis is M5;
- `derived_from` lineage reaches the producing run, the contributing alignment edges and
  the supporting evidence items, for `Lexeme` and `Sense` alike (global constraint 4);
- automated scoring produces `candidate` or `supported`, never `validated` (Invariant 3).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from langpipe.domain.enums import (
    AlignmentDirection,
    AlignmentMode,
    AlignmentStatus,
    EvidenceKind,
    EvidencePolarity,
    LifecycleStatus,
    LineageKind,
    Symmetrization,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.alignment import SegmentAlignment, TokenAlignmentEdge
from langpipe.domain.models.lexical import Sense
from langpipe.domain.models.observation import Form, Segment, TokenOccurrence
from langpipe.lexicon.adapters.alignment import AlignmentLexicalInducer
from langpipe.lexicon.base import LexicalInductionInput, LexicalInductionOutput
from langpipe.lexicon.registry import (
    UnsupportedMethod,
    get_lexical_inducer,
    lexical_induction_methods,
)
from langpipe.lexicon.scoring import POLICY_VERSION, LexicalScorePolicy

NOW = datetime(2026, 1, 1, tzinfo=UTC)
TARGET_LANGUAGE = "mzr"
CONTACT_LANGUAGE = "por"
ORTHOGRAPHY = "mzr-nfc@1.0"
TOKENIZER = "whitespace@1.0"
SOURCE_A = new_id(IdPrefix.SOURCE)
SOURCE_B = new_id(IdPrefix.SOURCE)
METHOD = "alignment_cooccurrence@0.1.0"


def _form(text: str, *, language: str = TARGET_LANGUAGE) -> Form:
    return Form(
        id=new_id(IdPrefix.FORM),
        language=language,
        orthography_profile=ORTHOGRAPHY,
        text=text,
        run_id=new_id(IdPrefix.RUN),
        created_at=NOW,
    )


def _segment(source_id: str) -> Segment:
    return Segment(
        id=new_id(IdPrefix.SEGMENT),
        source_id=source_id,
        source_object_id=new_id(IdPrefix.SOURCE_OBJECT),
        run_id=new_id(IdPrefix.RUN),
        ordinal=0,
        language=TARGET_LANGUAGE,
        locator={},
        raw_text="x y",
        created_at=NOW,
    )


def _segment_alignment(alignment_id: str, source_segment: Segment, run_id: str) -> SegmentAlignment:
    """One binary alignment group whose source side is the token's segment."""
    return SegmentAlignment(
        id=alignment_id,
        source_segment_ids=(source_segment.id,),
        target_segment_ids=(new_id(IdPrefix.SEGMENT),),
        method="eflomal_preordering@0.1.0",
        mode=AlignmentMode.CANONICAL,
        status=AlignmentStatus.STRUCTURAL,
        score=None,
        group_key=sha256(source_segment.id.encode()).hexdigest(),
        run_id=run_id,
        created_at=NOW,
    )


def _token(segment_id: str, surface: str, *, form: Form | None) -> TokenOccurrence:
    return TokenOccurrence(
        id=new_id(IdPrefix.TOKEN),
        segment_id=segment_id,
        run_id=new_id(IdPrefix.RUN),
        ordinal=0,
        raw_surface=surface,
        normalized_surface=surface,
        tokenizer=TOKENIZER,
        form_id=None if form is None else form.id,
        created_at=NOW,
    )


def _edge(
    source: TokenOccurrence,
    target: TokenOccurrence,
    *,
    score: float | None,
    direction: AlignmentDirection,
    segment_alignment_id: str | None = None,
) -> TokenAlignmentEdge:
    return TokenAlignmentEdge(
        id=new_id(IdPrefix.TOKEN_ALIGNMENT),
        segment_alignment_id=(
            new_id(IdPrefix.SEGMENT_ALIGNMENT)
            if segment_alignment_id is None
            else segment_alignment_id
        ),
        source_token_id=source.id,
        target_token_id=target.id,
        direction=direction,
        algorithm="eflomal@0.1.0",
        score=score,
        symmetrization=(
            Symmetrization.INTERSECTION
            if direction is AlignmentDirection.SYMMETRIZED
            else Symmetrization.NONE
        ),
        run_id=new_id(IdPrefix.RUN),
        created_at=NOW,
    )


@dataclass(frozen=True)
class _Link:
    """One (source form, contact gloss) token alignment observation."""

    source: str
    target: str
    score: float | None = None
    direction: AlignmentDirection = AlignmentDirection.SYMMETRIZED
    source_id: str | None = None
    # Distinct edges between one (form, gloss) pair: two occurrences of the same form in
    # the same segment group, or the same group observed twice.
    variant: int = 0
    # When set, every edge of this link belongs to that segment alignment group.
    segment_alignment_id: str | None = None


@dataclass(frozen=True)
class _Scene:
    data: LexicalInductionInput
    source_forms: Mapping[str, Form]
    target_forms: Mapping[str, Form]
    edges: Mapping[tuple[str, str, str | None], TokenAlignmentEdge]
    segment_alignments: Mapping[str, SegmentAlignment]
    run_id: str


def _scene(
    links: Sequence[_Link],
    *,
    link_forms: bool = True,
    policy: LexicalScorePolicy | None = None,
) -> _Scene:
    """Build one induction input: tokens, forms, segments and token alignment edges."""
    run = new_id(IdPrefix.RUN)
    source_forms: dict[str, Form] = {}
    target_forms: dict[str, Form] = {}
    segments: dict[str, Segment] = {}
    source_tokens: dict[str, TokenOccurrence] = {}
    target_tokens: dict[str, TokenOccurrence] = {}
    edges: dict[tuple[str, str, str | None], TokenAlignmentEdge] = {}
    segment_alignments: dict[str, SegmentAlignment] = {}

    for link in links:
        source_form = source_forms.setdefault(link.source, _form(link.source))
        target_form = target_forms.setdefault(
            link.target, _form(link.target, language=CONTACT_LANGUAGE)
        )
        source_id = link.source_id or new_id(IdPrefix.SOURCE)
        segment = segments.get(source_id)
        if segment is None:
            segment = _segment(source_id)
            segments[segment.id] = segment
        source_key = f"{link.source}@{source_id}"
        source_token = source_tokens.get(source_key)
        if source_token is None:
            source_token = _token(segment.id, link.source, form=source_form if link_forms else None)
            source_tokens[source_key] = source_token
        target_key = f"{link.target}@{link.variant}"
        target_token = target_tokens.get(target_key)
        if target_token is None:
            target_token = _token(
                new_id(IdPrefix.SEGMENT), link.target, form=target_form if link_forms else None
            )
            target_tokens[target_key] = target_token
        # Without an explicit group the edge owns a fresh one, so one (form, gloss)
        # observation never silently shares a segment group with another observation.
        group_id = link.segment_alignment_id
        if group_id is None:
            group_id = new_id(IdPrefix.SEGMENT_ALIGNMENT)
            segment_alignments[group_id] = _segment_alignment(group_id, segment, run)
        elif group_id not in segment_alignments:
            segment_alignments[group_id] = _segment_alignment(group_id, segment, run)
        edges[(link.source, link.target, link.source_id, link.variant)] = _edge(
            source_token,
            target_token,
            score=link.score,
            direction=link.direction,
            segment_alignment_id=group_id,
        )

    return _Scene(
        LexicalInductionInput(
            run_id=run,
            target_language=TARGET_LANGUAGE,
            contact_language=CONTACT_LANGUAGE,
            alignment_edges=list(edges.values()),
            source_tokens={token.id: token for token in source_tokens.values()},
            target_tokens={token.id: token for token in target_tokens.values()},
            source_forms={form.id: form for form in source_forms.values()},
            target_forms={form.id: form for form in target_forms.values()},
            segments=segments,
            policy=policy,
        ),
        source_forms,
        target_forms,
        edges,
        segment_alignments,
        run,
    )


def _glosses(output: LexicalInductionOutput) -> list[str]:
    return sorted(gloss for sense in output.senses for gloss in sense.glosses[CONTACT_LANGUAGE])


def _lineage_pairs(output: LexicalInductionOutput) -> set[tuple[str, str]]:
    return {(edge.from_id, edge.to_id) for edge in output.lineage_edges}


# --- registry ----------------------------------------------------------------------


def test_registry_resolves_the_registered_baseline_method() -> None:
    inducer = get_lexical_inducer(METHOD)
    assert inducer.method_id == METHOD
    assert METHOD in lexical_induction_methods()


def test_registry_rejects_an_unknown_method() -> None:
    with pytest.raises(UnsupportedMethod):
        get_lexical_inducer("alignment_cooccurrence@9.9.9")
    with pytest.raises(UnsupportedMethod):
        get_lexical_inducer("wordlist_cooccurrence@0.1.0")


def test_unsupported_method_error_echoes_neither_the_method_nor_a_payload() -> None:
    with pytest.raises(UnsupportedMethod) as failure:
        get_lexical_inducer("alignment_cotopérix@0.1.0")
    assert "alignment_cotopérix" not in str(failure.value)


# --- baseline induction ------------------------------------------------------------


def test_alignment_edge_yields_one_candidate_lexeme_link_and_sense() -> None:
    scene = _scene([_Link("wesa", "canoa", score=0.8)])
    output = AlignmentLexicalInducer().induce(scene.data)

    assert len(output.lexemes) == 1
    lexeme = output.lexemes[0]
    assert lexeme.language == TARGET_LANGUAGE
    assert lexeme.lemma_form_id == scene.source_forms["wesa"].id
    assert lexeme.run_id == scene.run_id
    assert lexeme.status is LifecycleStatus.CANDIDATE
    assert lexeme.score_breakdown is not None
    assert lexeme.score_breakdown.policy_version == POLICY_VERSION

    assert len(output.form_links) == 1
    link = output.form_links[0]
    assert (link.form_id, link.lexeme_id, link.role, link.run_id) == (
        scene.source_forms["wesa"].id,
        lexeme.id,
        "primary_lemma",
        scene.run_id,
    )

    assert len(output.senses) == 1
    sense = output.senses[0]
    assert sense.lexeme_id == lexeme.id
    assert sense.glosses == {CONTACT_LANGUAGE: ["canoa"]}
    assert sense.status is LifecycleStatus.CANDIDATE
    assert sense.run_id == scene.run_id
    assert sense.score_breakdown is not None


def test_token_alignment_evidence_records_kind_claim_strength_and_source() -> None:
    scene = _scene([_Link("wesa", "canoa", score=0.4, source_id=SOURCE_A)])
    output = AlignmentLexicalInducer().induce(scene.data)
    edge_id = scene.edges[("wesa", "canoa", SOURCE_A, 0)].id
    token_evidence = [
        item for item in output.evidence_items if item.kind is EvidenceKind.TOKEN_ALIGNMENT
    ]

    assert len(token_evidence) == 1
    item = token_evidence[0]
    assert item.polarity is EvidencePolarity.SUPPORTS
    assert item.target_id == output.lexemes[0].id
    assert item.claim == {"gloss": "canoa", "source_form": "wesa"}
    assert item.strength == {"alignment_support": 0.4}
    assert item.run_id == scene.run_id
    assert item.source_id == SOURCE_A
    assert (item.id, edge_id) in _lineage_pairs(output)


def test_evidence_strength_defaults_to_full_support_for_an_unscored_edge() -> None:
    scene = _scene([_Link("wesa", "canoa")])
    output = AlignmentLexicalInducer().induce(scene.data)

    assert sorted(item.strength["alignment_support"] for item in output.evidence_items) == [
        1.0,
        1.0,
    ]
    for item in output.evidence_items:
        assert item.source_id is not None  # every item carries its own provenance
        assert item.strength == {"alignment_support": 1.0}


def test_each_contributing_edge_is_recorded_as_its_own_evidence_item() -> None:
    # Two independent sources observing one pair are two observations: each keeps its own
    # provenance and strength, so no axis is invented or silently collapsed.
    scene = _scene(
        [
            _Link("wesa", "canoa", score=0.5, source_id=SOURCE_A),
            _Link("wesa", "canoa", score=1.0, source_id=SOURCE_B),
        ]
    )
    output = AlignmentLexicalInducer().induce(scene.data)

    assert len(output.lexemes) == 1
    assert len(output.senses) == 1
    assert len(output.evidence_items) == 4  # two edges, token_alignment + segment_cooccurrence
    assert sorted(item.strength["alignment_support"] for item in output.evidence_items) == [
        0.5,
        0.5,
        1.0,
        1.0,
    ]
    assert {item.source_id for item in output.evidence_items} == {SOURCE_A, SOURCE_B}


def test_segment_cooccurrence_evidence_is_emitted_for_aligned_input() -> None:
    # WP4.5 requires both kinds: the observed segment-group co-occurrence of the aligned
    # tokens is recorded next to the token-pair observation.
    scene = _scene([_Link("wesa", "canoa", score=0.6, source_id=SOURCE_A)])
    output = AlignmentLexicalInducer().induce(scene.data)
    edge = scene.edges[("wesa", "canoa", SOURCE_A, 0)]
    segment_evidence = [
        item for item in output.evidence_items if item.kind is EvidenceKind.SEGMENT_COOCCURRENCE
    ]

    assert len(segment_evidence) == 1
    item = segment_evidence[0]
    assert item.polarity is EvidencePolarity.SUPPORTS
    assert item.target_id == output.lexemes[0].id
    assert item.claim == {"gloss": "canoa", "source_form": "wesa"}
    assert item.source_id == SOURCE_A
    assert item.run_id == scene.run_id
    assert item.strength == {"alignment_support": 0.6}
    # Parent lineage is the actual segment alignment the tokens co-occur in.
    assert (item.id, edge.segment_alignment_id) in _lineage_pairs(output)


def test_both_required_evidence_kinds_are_emitted_per_edge() -> None:
    scene = _scene([_Link("wesa", "canoa", score=0.6, source_id=SOURCE_A)])
    output = AlignmentLexicalInducer().induce(scene.data)
    kinds = {item.kind for item in output.evidence_items}

    assert kinds == {EvidenceKind.TOKEN_ALIGNMENT, EvidenceKind.SEGMENT_COOCCURRENCE}
    assert len(output.evidence_items) == 2


def test_segment_cooccurrence_evidence_keeps_the_same_source_and_strength_axis() -> None:
    # No independent corroboration is inferred: the segment-group observation carries the
    # same provenance, independence axis and strength as the token observation.
    scene = _scene([_Link("wesa", "canoa", score=0.75, source_id=SOURCE_A)])
    output = AlignmentLexicalInducer().induce(scene.data)
    token_item, segment_item = sorted(output.evidence_items, key=lambda item: item.kind.value)

    assert segment_item.source_id == token_item.source_id
    assert segment_item.strength == token_item.strength
    assert segment_item.independence_group == token_item.independence_group
    assert segment_item.polarity is token_item.polarity
    assert segment_item.claim == token_item.claim


def test_several_token_edges_of_one_source_add_no_independent_sources() -> None:
    # Two occurrences of the same form in the same segment group are still one source: the
    # segment co-occurrence evidence never multiplies independent axes.
    group = new_id(IdPrefix.SEGMENT_ALIGNMENT)
    scene = _scene(
        [
            _Link("mabi", "canoa", score=0.5, source_id=SOURCE_A, segment_alignment_id=group),
            _Link(
                "mabi",
                "canoa",
                score=0.9,
                source_id=SOURCE_A,
                variant=1,
                segment_alignment_id=group,
            ),
        ]
    )
    output = AlignmentLexicalInducer().induce(scene.data)
    lexeme = output.lexemes[0]

    assert {item.kind for item in output.evidence_items} == {
        EvidenceKind.TOKEN_ALIGNMENT,
        EvidenceKind.SEGMENT_COOCCURRENCE,
    }
    assert lexeme.score_breakdown is not None
    assert lexeme.score_breakdown.independence_groups == [SOURCE_A]
    assert len(lexeme.score_breakdown.independence_groups) == 1


def test_repeated_segment_group_observations_are_deduplicated() -> None:
    # One segment group observed by several token pairs yields a single segment
    # co-occurrence observation per (form, gloss) pair, not one per edge.
    group = new_id(IdPrefix.SEGMENT_ALIGNMENT)
    scene = _scene(
        [
            _Link(
                "mabi",
                "canoa",
                score=0.5,
                source_id=SOURCE_A,
                variant=0,
                segment_alignment_id=group,
            ),
            _Link(
                "mabi",
                "canoa",
                score=0.9,
                source_id=SOURCE_A,
                variant=1,
                segment_alignment_id=group,
            ),
            _Link(
                "mabi",
                "canoa",
                score=0.7,
                source_id=SOURCE_B,
                variant=2,
                segment_alignment_id=group,
            ),
        ]
    )
    output = AlignmentLexicalInducer().induce(scene.data)
    segment_evidence = [
        item for item in output.evidence_items if item.kind is EvidenceKind.SEGMENT_COOCCURRENCE
    ]

    assert len(segment_evidence) == 1
    assert segment_evidence[0].strength == {"alignment_support": 0.9}
    assert segment_evidence[0].source_id == SOURCE_A


def test_two_independent_sources_support_the_lexeme_but_not_either_sense() -> None:
    # Senior ruling 4: two independent sources split across different glosses support the
    # lexeme, yet neither sense has the two axes a promotion gate demands.
    policy = LexicalScorePolicy(promotion_threshold=0.5)
    scene = _scene(
        [
            _Link("mabi", "canoa", source_id=SOURCE_A),
            _Link("mabi", "tronco", source_id=SOURCE_B),
        ],
        policy=policy,
    )
    output = AlignmentLexicalInducer().induce(scene.data)
    lexeme = output.lexemes[0]

    assert lexeme.status is LifecycleStatus.SUPPORTED
    assert lexeme.score_breakdown is not None
    assert len(lexeme.score_breakdown.independence_groups) == 2
    # Each sense saw one source only: a single axis never passes the diversity gate.
    for sense in output.senses:
        assert sense.status is LifecycleStatus.CANDIDATE
        assert sense.score_breakdown is not None
        assert len(sense.score_breakdown.independence_groups) == 1


# --- ambiguity and whole-token preservation ----------------------------------------


def test_one_source_form_with_two_glosses_yields_two_candidate_senses() -> None:
    scene = _scene([_Link("mabi", "canoa"), _Link("mabi", "tronco")])
    output = AlignmentLexicalInducer().induce(scene.data)

    assert len(output.lexemes) == 1
    assert len(output.form_links) == 1
    assert len(output.senses) == 2
    assert _glosses(output) == ["canoa", "tronco"]
    assert {sense.lexeme_id for sense in output.senses} == {output.lexemes[0].id}
    for sense in output.senses:
        assert sense.status in {LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED}


def test_hyphenated_form_is_never_segmented() -> None:
    # M4 scope fence: sub-token analysis of `-ra` belongs to Milestone 5, so the adapter
    # keeps the whole token intact and never invents a morpheme or a second sense for it.
    scene = _scene([_Link("wesa-ra", "canoa")])
    output = AlignmentLexicalInducer().induce(scene.data)
    lemma = scene.source_forms["wesa-ra"]

    assert len(output.lexemes) == 1
    assert len(output.senses) == 1
    assert output.senses[0].glosses == {CONTACT_LANGUAGE: ["canoa"]}
    assert output.lexemes[0].lemma_form_id == lemma.id
    assert lemma.text == "wesa-ra"
    assert not {gloss.strip("-") for gloss in _glosses(output)} & {"ra", "wesa"}


def test_distinct_source_forms_stay_distinct_lexemes() -> None:
    scene = _scene([_Link("wesa", "canoa"), _Link("kape", "canoa")])
    output = AlignmentLexicalInducer().induce(scene.data)

    assert len(output.lexemes) == 2
    assert len(output.form_links) == 2
    assert len(output.senses) == 2
    assert {lexeme.lemma_form_id for lexeme in output.lexemes} == {
        scene.source_forms["wesa"].id,
        scene.source_forms["kape"].id,
    }


# --- invariants --------------------------------------------------------------------


def test_contact_forms_are_glosses_never_target_language_forms() -> None:
    scene = _scene([_Link("mabi", "canoa"), _Link("mabi", "tronco")])
    output = AlignmentLexicalInducer().induce(scene.data)
    target_form_ids = {form.id for form in scene.target_forms.values()}

    assert all(sense.glosses.keys() == {CONTACT_LANGUAGE} for sense in output.senses)
    for sense in output.senses:
        assert sense.concept_id is None
    for lexeme in output.lexemes:
        assert lexeme.language == TARGET_LANGUAGE
        assert lexeme.lemma_form_id not in target_form_ids
    assert not any(
        link.form_id in target_form_ids for link in output.form_links
    )  # no contact form is ever linked to a target lexeme


def test_explicit_source_form_id_in_a_foreign_language_is_rejected() -> None:
    # An explicit `form_id` still names the pinning language: a Portuguese form is never a
    # Marúbo lemma, however the caller resolved it (Invariants 8, 9; ADR-0013 §1).
    scene = _scene([_Link("wesa", "canoa")])
    wrong = scene.source_forms["wesa"].model_copy(
        update={"language": CONTACT_LANGUAGE, "text": "canoa"}
    )
    data = replace(
        scene.data, source_forms={**scene.data.source_forms, scene.source_forms["wesa"].id: wrong}
    )
    output = AlignmentLexicalInducer().induce(data)

    assert output.lexemes == []
    assert output.form_links == []
    assert output.senses == []
    assert output.evidence_items == []
    assert output.lineage_edges == []


def test_explicit_target_form_id_in_a_foreign_language_is_rejected() -> None:
    # The target side accepts only a contact-language form as a meaning hypothesis, so a
    # Portuguese gloss is dropped when the pinned form is labelled target-language.
    scene = _scene([_Link("wesa", "canoa")])
    wrong = scene.target_forms["canoa"].model_copy(update={"language": TARGET_LANGUAGE})
    data = replace(
        scene.data,
        target_forms={**scene.data.target_forms, scene.target_forms["canoa"].id: wrong},
    )
    output = AlignmentLexicalInducer().induce(data)

    assert output.lexemes == []
    assert output.senses == []
    assert output.evidence_items == []


def test_valid_explicit_form_ids_still_resolve_on_both_sides() -> None:
    # Control for the two rejection tests: correctly labelled pins are used.
    scene = _scene([_Link("wesa", "canoa")])
    output = AlignmentLexicalInducer().induce(scene.data)

    lexeme = output.lexemes[0]
    assert lexeme.lemma_form_id == scene.source_forms["wesa"].id
    assert output.senses[0].glosses == {CONTACT_LANGUAGE: ["canoa"]}
    assert output.form_links[0].form_id == scene.source_forms["wesa"].id


def test_surface_resolution_still_rejects_a_foreign_language_form() -> None:
    # The fallback path already filtered by language; keep both paths equivalent.
    scene = _scene([_Link("wesa", "canoa")], link_forms=False)
    wrong = scene.source_forms["wesa"].model_copy(update={"language": CONTACT_LANGUAGE})
    data = replace(scene.data, source_forms={scene.source_forms["wesa"].id: wrong})
    output = AlignmentLexicalInducer().induce(data)

    assert output.lexemes == []
    assert output.senses == []


def test_only_the_mismatched_edge_is_dropped_when_other_edges_are_usable() -> None:
    # One broken observation never poisons the rest of the run: its group disappears, the
    # other source form still induces.
    scene = _scene([_Link("wesa", "canoa"), _Link("kape", "tronco")])
    wrong = scene.source_forms["wesa"].model_copy(
        update={"language": CONTACT_LANGUAGE, "text": "canoa"}
    )
    source_forms = dict(scene.data.source_forms)
    source_forms[scene.source_forms["wesa"].id] = wrong
    output = AlignmentLexicalInducer().induce(replace(scene.data, source_forms=source_forms))

    assert [lexeme.lemma_form_id for lexeme in output.lexemes] == [scene.source_forms["kape"].id]
    assert _glosses(output) == ["tronco"]


def test_no_concept_is_created_by_alignment_evidence() -> None:
    scene = _scene([_Link("mabi", "canoa"), _Link("mabi", "tronco")])
    assert AlignmentLexicalInducer().induce(scene.data).concepts == []


def test_lineage_links_candidates_to_edges_and_the_producing_run() -> None:
    scene = _scene([_Link("mabi", "canoa"), _Link("mabi", "tronco")])
    output = AlignmentLexicalInducer().induce(scene.data)
    pairs = _lineage_pairs(output)
    edge_ids = {edge.id for edge in scene.data.alignment_edges}
    group_ids = {edge.segment_alignment_id for edge in scene.data.alignment_edges}
    lexeme = output.lexemes[0]

    assert {edge.kind for edge in output.lineage_edges} == {LineageKind.DERIVED_FROM}
    assert all(edge.run_id == scene.run_id for edge in output.lineage_edges)
    assert (lexeme.id, scene.run_id) in pairs
    assert {(lexeme.id, edge_id) for edge_id in edge_ids} <= pairs
    assert {(lexeme.id, group_id) for group_id in group_ids} <= pairs
    for sense in output.senses:
        assert (sense.id, lexeme.id) in pairs
        # a sense points only at the alignment edges of its own gloss
        assert len(edge_ids & {to_id for from_id, to_id in pairs if from_id == sense.id}) == 1
        assert pairs & {(sense.id, lexeme.id)}
    for item in output.evidence_items:
        # A token-alignment item documents one alignment edge; a segment-cooccurrence item
        # documents the segment alignment group its tokens co-occur in.
        if item.kind is EvidenceKind.TOKEN_ALIGNMENT:
            contributing = edge_ids & {to_id for from_id, to_id in pairs if from_id == item.id}
            assert len(contributing) == 1
        else:
            assert item.kind is EvidenceKind.SEGMENT_COOCCURRENCE
            assert group_ids & {to_id for from_id, to_id in pairs if from_id == item.id}


def test_candidates_link_their_supporting_evidence_and_the_producing_run() -> None:
    # Global constraint 4: every Lexeme and Sense keeps a `derived_from` edge to each
    # supporting EvidenceItem and to the producing run. Sharing alignment ancestors does
    # not make an evidence item reachable as a parent.
    scene = _scene([_Link("mabi", "canoa")])
    output = AlignmentLexicalInducer().induce(scene.data)
    pairs = _lineage_pairs(output)
    lexeme = output.lexemes[0]
    sense = output.senses[0]
    evidence_ids = {item.id for item in output.evidence_items}

    assert (lexeme.id, scene.run_id) in pairs
    assert (sense.id, scene.run_id) in pairs
    assert evidence_ids <= {to_id for from_id, to_id in pairs if from_id == lexeme.id}
    # Gloss-specific: a sense derives from exactly the evidence of its own gloss, in
    # addition to its lexeme, its producing run and its own alignment edge.
    assert evidence_ids
    sense_parents = {to_id for from_id, to_id in pairs if from_id == sense.id} - {
        lexeme.id,
        scene.run_id,
    }
    assert evidence_ids <= sense_parents
    assert sense_parents - evidence_ids  # the gloss's own alignment edge still a parent


def test_sense_never_links_evidence_of_another_gloss() -> None:
    # Gloss-specific lineage stays gloss-specific: the `canoa` sense derives from nothing
    # observed only for `tronco`.
    scene = _scene([_Link("mabi", "canoa"), _Link("mabi", "tronco")])
    output = AlignmentLexicalInducer().induce(scene.data)
    pairs = _lineage_pairs(output)
    by_gloss = {sense.glosses[CONTACT_LANGUAGE][0]: sense for sense in output.senses}
    evidence_of = {
        gloss: {
            item.id for item in output.evidence_items if (item.claim or {}).get("gloss") == gloss
        }
        for gloss in by_gloss
    }
    canoa_evidence = evidence_of["canoa"]
    tronco_evidence = evidence_of["tronco"]

    assert canoa_evidence and tronco_evidence
    assert not canoa_evidence & tronco_evidence

    def evidence_parents(sense: Sense) -> set[str]:
        return {
            to_id
            for from_id, to_id in pairs
            if from_id == sense.id and to_id.startswith(f"{IdPrefix.EVIDENCE.value}_")
        }

    assert evidence_parents(by_gloss["canoa"]) == canoa_evidence
    assert evidence_parents(by_gloss["tronco"]) == tronco_evidence


def test_every_generated_identifier_uses_its_own_prefix() -> None:
    scene = _scene([_Link("wesa", "canoa")])
    output = AlignmentLexicalInducer().induce(scene.data)

    assert all(lexeme.id.startswith(f"{IdPrefix.LEXEME.value}_") for lexeme in output.lexemes)
    assert all(link.id.startswith(f"{IdPrefix.FORM_LEXEME.value}_") for link in output.form_links)
    assert all(sense.id.startswith(f"{IdPrefix.SENSE.value}_") for sense in output.senses)
    assert all(item.id.startswith(f"{IdPrefix.EVIDENCE.value}_") for item in output.evidence_items)
    assert all(edge.id.startswith(f"{IdPrefix.LINEAGE.value}_") for edge in output.lineage_edges)


def test_deterministic_regardless_of_edge_input_order() -> None:
    links = [_Link("mabi", "canoa"), _Link("mabi", "tronco"), _Link("wesa", "canoa")]
    first = _scene(links)
    second = _scene(list(reversed(links)))
    forward = AlignmentLexicalInducer().induce(first.data)
    backward = AlignmentLexicalInducer().induce(second.data)

    # Each scene mints its own ids, so compare surfaces and shapes, never raw ids.
    def surfaces(scene: _Scene, output: LexicalInductionOutput) -> tuple[list[str], list[str]]:
        by_id = {form.id: form.text for form in scene.source_forms.values()}
        return (
            sorted(by_id[lexeme.lemma_form_id or ""] for lexeme in output.lexemes),
            sorted(gloss for sense in output.senses for gloss in sense.glosses[CONTACT_LANGUAGE]),
        )

    assert surfaces(first, forward) == surfaces(second, backward)
    assert len(forward.lineage_edges) == len(backward.lineage_edges)
    assert len(forward.evidence_items) == len(backward.evidence_items)
    assert sorted(item.strength["alignment_support"] for item in forward.evidence_items) == sorted(
        item.strength["alignment_support"] for item in backward.evidence_items
    )


# --- input hygiene -----------------------------------------------------------------


def test_forms_resolve_by_text_when_the_token_carries_no_form_id() -> None:
    scene = _scene([_Link("wesa", "canoa")], link_forms=False)
    output = AlignmentLexicalInducer().induce(scene.data)

    assert len(output.lexemes) == 1
    assert output.lexemes[0].lemma_form_id == scene.source_forms["wesa"].id
    assert output.senses[0].glosses == {CONTACT_LANGUAGE: ["canoa"]}


def test_edges_missing_a_token_a_form_or_a_segment_source_are_skipped() -> None:
    scene = _scene(
        [
            _Link("wesa", "canoa"),
            _Link("kape", "tronco"),
            _Link("wera", "remar"),
        ]
    )
    # Drop the token behind the `kape` edges: an edge whose endpoint is unpinned is unused.
    data = scene.data
    dropped_id = next(
        token_id for token_id, token in data.source_tokens.items() if token.raw_surface == "kape"
    )
    data = replace(
        data,
        source_tokens={
            token_id: token
            for token_id, token in data.source_tokens.items()
            if token_id != dropped_id
        },
    )
    output = AlignmentLexicalInducer().induce(data)
    assert len(output.lexemes) == 2
    assert _glosses(output) == ["canoa", "remar"]

    # A contact form outside the pinned collection is untraceable, so its edges are unused.
    untraceable = replace(
        scene.data,
        target_forms={
            form_id: form
            for form_id, form in scene.data.target_forms.items()
            if form.text != "remar"
        },
    )
    assert [sense.glosses for sense in AlignmentLexicalInducer().induce(untraceable).senses] == [
        {CONTACT_LANGUAGE: ["canoa"]},
        {CONTACT_LANGUAGE: ["tronco"]},
    ]


def test_unknown_segment_records_no_source_and_builds_nothing_extra() -> None:
    scene = _scene([_Link("wesa", "canoa")])
    data = replace(scene.data, segments=None)
    output = AlignmentLexicalInducer().induce(data)

    assert [item.source_id for item in output.evidence_items] == [None, None]
    assert len(output.lexemes) == 1


def test_no_alignment_edges_produce_an_empty_result() -> None:
    scene = _scene([_Link("wesa", "canoa")])
    data = replace(scene.data, alignment_edges=[])
    output = AlignmentLexicalInducer().induce(data)

    assert output.lexemes == []
    assert output.form_links == []
    assert output.senses == []
    assert output.concepts == []
    assert output.evidence_items == []
    assert output.lineage_edges == []


# --- direction filter --------------------------------------------------------------


def test_only_symmetrized_edges_are_used_by_default() -> None:
    scene = _scene(
        [
            _Link("wesa", "canoa", direction=AlignmentDirection.FORWARD),
            _Link("wera", "tronco", direction=AlignmentDirection.REVERSE),
        ]
    )
    output = AlignmentLexicalInducer().induce(scene.data)

    assert output.lexemes == []
    assert output.senses == []
    assert output.evidence_items == []
    assert output.lineage_edges == []


def test_configured_directions_are_honoured() -> None:
    scene = _scene(
        [
            _Link("wesa", "canoa", direction=AlignmentDirection.FORWARD),
            _Link("wera", "remar", direction=AlignmentDirection.SYMMETRIZED),
        ]
    )
    forward_only = AlignmentLexicalInducer(directions=(AlignmentDirection.FORWARD,)).induce(
        scene.data
    )
    assert _glosses(forward_only) == ["canoa"]

    both = AlignmentLexicalInducer(
        directions=(AlignmentDirection.FORWARD, AlignmentDirection.SYMMETRIZED)
    ).induce(scene.data)
    assert _glosses(both) == ["canoa", "remar"]


def test_the_adapter_rejects_an_empty_direction_set() -> None:
    with pytest.raises(ValueError):
        AlignmentLexicalInducer(directions=())


# --- promotion semantics -----------------------------------------------------------


def test_alignment_evidence_alone_never_promotes_under_the_default_policy() -> None:
    # Two independent sources still score 0.60: alignment evidence is one component, and
    # a contact-language gloss alone never promotes target-language knowledge (ADR-0013 §3).
    scene = _scene(
        [
            _Link("wesa", "canoa", source_id=SOURCE_A),
            _Link("wera", "canoa", source_id=SOURCE_B),
        ]
    )
    output = AlignmentLexicalInducer().induce(scene.data)

    assert all(lexeme.status is LifecycleStatus.CANDIDATE for lexeme in output.lexemes)
    assert all(sense.status is LifecycleStatus.CANDIDATE for sense in output.senses)


def test_a_passing_policy_promotes_the_lexeme_to_supported_but_never_validates() -> None:
    # One form observed by two independent sources: two axes, alignment at full strength.
    # Both required kinds of one observation share the source's axis, so the score is
    # 0.30 (alignment) + 0.20 (diversity) + 0.10 (domain stability) - 0.10 (formulaic
    # source, every axis observed twice) = 0.50, which clears a 0.45 threshold.
    policy = LexicalScorePolicy(promotion_threshold=0.45)
    scene = _scene(
        [
            _Link("wesa", "canoa", source_id=SOURCE_A),
            _Link("wesa", "canoa", source_id=SOURCE_B),
        ],
        policy=policy,
    )
    output = AlignmentLexicalInducer().induce(scene.data)
    lexeme = output.lexemes[0]

    assert lexeme.status is LifecycleStatus.SUPPORTED
    assert lexeme.status is not LifecycleStatus.VALIDATED
    assert lexeme.score_breakdown is not None
    assert lexeme.score_breakdown.overall == pytest.approx(0.5)
    assert len(lexeme.score_breakdown.independence_groups) == 2


def test_no_status_is_ever_validated_under_the_most_permissive_policy() -> None:
    # Every gate open: zero threshold, one axis enough. Machine confidence still may not
    # create `validated` (AGENTS.md invariant 3; EVIDENCE-AND-CONFIDENCE.md:61-63).
    policy = LexicalScorePolicy(promotion_threshold=0.0, min_independent_sources=1)
    scene = _scene([_Link("wesa", "canoa")], policy=policy)
    output = AlignmentLexicalInducer().induce(scene.data)

    statuses = {lexeme.status for lexeme in output.lexemes}
    statuses |= {sense.status for sense in output.senses}
    assert statuses <= {LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED}
    assert statuses == {LifecycleStatus.SUPPORTED}
    assert LifecycleStatus.VALIDATED not in statuses


def test_induce_returns_the_declared_output_shape() -> None:
    scene = _scene([_Link("wesa", "canoa")])
    output = get_lexical_inducer(METHOD).induce(scene.data)

    assert isinstance(output, LexicalInductionOutput)
    assert isinstance(output.lexemes, list)
    assert isinstance(output.senses, list)
    assert isinstance(output.lineage_edges, list)
    assert isinstance(output.evidence_items, list)
    assert isinstance(output.form_links, Iterable)
    assert isinstance(output.concepts, list)
