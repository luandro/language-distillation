"""Shared Repository behaviour for M3 alignment evidence (WP3.3, M3-PLAN §5.3).

Runs once per backend via the `repo` fixture. Group members are inserted internally by
`add_segment_alignment`; both backends validate the §5.4 selection contract eagerly, so a
repository-mediated write never depends on the deferred database guards. Test data is
synthetic: identifiers and placeholder text only.
"""

import itertools
import threading
from dataclasses import dataclass
from typing import Any

import pytest

from langpipe.domain.enums import (
    AlignmentStatus,
    EntityType,
    LineageKind,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import (
    AlignmentFailed,
    ImmutableViolation,
    InvalidLineage,
    NotFound,
    SchemaViolation,
)
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.domain.models.run import ProcessingRun
from langpipe.domain.models.source import Source, SourceObject
from langpipe.storage.repository import Repository
from tests.contract.builders import (
    NOW,
    alignment_sides_config,
    make_artifact,
    make_policy,
    make_run,
    make_segment,
    make_segment_alignment,
    make_source,
    make_source_object,
    make_token,
    make_token_alignment_edge,
    unique_run_key,
)

_KEYS = itertools.count()


def _key(label: str) -> str:
    return unique_run_key(f"{label}-{next(_KEYS)}")


@dataclass
class AlignmentWorld:
    """Committed substrate: pinned succeeded runs, two segment sides, tokens per side."""

    source: Source
    source_object: SourceObject
    src_norm_run: ProcessingRun
    tgt_norm_run: ProcessingRun
    src_segments: list[Segment]
    tgt_segments: list[Segment]
    align_run: ProcessingRun
    src_tok_run: ProcessingRun
    tgt_tok_run: ProcessingRun
    token_run: ProcessingRun
    src_tokens: list[TokenOccurrence]
    tgt_tokens: list[TokenOccurrence]


def _alignment_world(
    repo: Repository, *, source_segments: int = 2, target_segments: int = 1
) -> AlignmentWorld:
    policy = make_policy()
    registration = make_run(stage=RunStage.SOURCE_REGISTRATION, run_key=_key("reg"))

    def _succeeded(stage: RunStage, label: str) -> ProcessingRun:
        return make_run(
            stage=stage, status=RunStatus.SUCCEEDED, finished_at=NOW, run_key=_key(label)
        )

    src_norm_run = _succeeded(RunStage.NORMALIZATION, "n0")
    tgt_norm_run = _succeeded(RunStage.NORMALIZATION, "n1")
    src_tok_run = _succeeded(RunStage.TOKENIZATION, "t0")
    tgt_tok_run = _succeeded(RunStage.TOKENIZATION, "t1")
    source = make_source(policy, registration.id)
    source_object = make_source_object(source, registration.id)
    src_segments = [
        make_segment(source, source_object, src_norm_run, ordinal=i, language="mzr")
        for i in range(source_segments)
    ]
    tgt_segments = [
        make_segment(source, source_object, tgt_norm_run, ordinal=i, language="por")
        for i in range(target_segments)
    ]
    align_run = make_run(
        stage=RunStage.SEGMENT_ALIGNMENT,
        config=alignment_sides_config(source.id, src_norm_run.id, tgt_norm_run.id),
        run_key=_key("sal"),
    )
    token_run = make_run(
        stage=RunStage.TOKEN_ALIGNMENT,
        config=alignment_sides_config(
            source.id,
            src_norm_run.id,
            tgt_norm_run.id,
            source_tokenization_run_id=src_tok_run.id,
            target_tokenization_run_id=tgt_tok_run.id,
        ),
        run_key=_key("tal"),
    )
    src_tokens = [make_token(segment, src_tok_run, ordinal=0) for segment in src_segments]
    tgt_tokens = [make_token(segment, tgt_tok_run, ordinal=0) for segment in tgt_segments]
    with repo.transaction():
        repo.add_policy(policy)
        repo.add_run(registration)
        repo.add_source(source)
        repo.add_source_object(source_object)
        for run in (src_norm_run, tgt_norm_run, src_tok_run, tgt_tok_run, align_run, token_run):
            repo.add_run(run)
        for segment in [*src_segments, *tgt_segments]:
            repo.add_segment(segment)
        for token in [*src_tokens, *tgt_tokens]:
            repo.add_token(token)
    return AlignmentWorld(
        source=source,
        source_object=source_object,
        src_norm_run=src_norm_run,
        tgt_norm_run=tgt_norm_run,
        src_segments=src_segments,
        tgt_segments=tgt_segments,
        align_run=align_run,
        src_tok_run=src_tok_run,
        tgt_tok_run=tgt_tok_run,
        token_run=token_run,
        src_tokens=src_tokens,
        tgt_tokens=tgt_tokens,
    )


class _Boom(Exception):
    pass


def _derived(run: ProcessingRun, from_id: str, to_id: str) -> LineageEdge:
    return LineageEdge(
        id=new_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run.id,
        created_at=NOW,
    )


def _by_depth(pairs: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return sorted(pairs, key=lambda item: (item[1], item[0]))


# --- writes are transaction-gated ----------------------------------------------------------


def test_write_requires_transaction(repo: Repository) -> None:
    world = _alignment_world(repo)
    alignment = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    )
    edge = make_token_alignment_edge(
        world.token_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
    )
    with pytest.raises(RuntimeError, match="write outside transaction"):
        repo.add_segment_alignment(alignment)
    with pytest.raises(RuntimeError, match="write outside transaction"):
        repo.add_token_alignment_edge(edge)
    with pytest.raises(RuntimeError, match="write outside transaction"):
        repo.lock_sources([world.source.id])


# --- ordered membership roundtrip ----------------------------------------------------------


def test_group_roundtrip_order(repo: Repository) -> None:
    world = _alignment_world(repo)
    # Membership order is the caller's tuple order (document/source order), not id order:
    # use the second-then-first source segment on purpose.
    ordered_source = [world.src_segments[1], world.src_segments[0]]
    alignment = make_segment_alignment(world.align_run, ordered_source, world.tgt_segments)
    alignment = alignment.model_copy(update={"group_key": "0" * 64})
    with repo.transaction():
        repo.add_segment_alignment(alignment)

    stored = repo.get_segment_alignment(alignment.id)
    assert stored == alignment
    assert stored.source_segment_ids == (ordered_source[0].id, ordered_source[1].id)
    assert stored.target_segment_ids == (world.tgt_segments[0].id,)

    with pytest.raises(NotFound):
        repo.get_segment_alignment(new_id(IdPrefix.SEGMENT_ALIGNMENT))

    other = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    ).model_copy(update={"group_key": "f" * 64})
    with repo.transaction():
        repo.add_segment_alignment(other)

    listed = repo.list_segment_alignments_for_run(world.align_run.id)
    assert [item.id for item in listed] == [alignment.id, other.id]
    assert repo.list_segment_alignments_for_run(new_id(IdPrefix.RUN)) == []


# --- natural uniqueness ---------------------------------------------------------------------


def test_duplicate_natural_key_rejected(repo: Repository) -> None:
    world = _alignment_world(repo)
    alignment = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    )
    with repo.transaction():
        repo.add_segment_alignment(alignment)
    # Same (run_id, group_key) under a fresh identifier.
    clash = make_segment_alignment(
        world.align_run, [world.src_segments[1]], world.tgt_segments[:1]
    ).model_copy(update={"group_key": alignment.group_key})
    with pytest.raises(ImmutableViolation), repo.transaction():
        repo.add_segment_alignment(clash)
    # Same identifier under a fresh group key.
    relabeled = alignment.model_copy(update={"group_key": "e" * 64})
    with pytest.raises(ImmutableViolation), repo.transaction():
        repo.add_segment_alignment(relabeled)

    edge = make_token_alignment_edge(
        world.token_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
    )
    with repo.transaction():
        repo.add_token_alignment_edge(edge)
    duplicate_edge = make_token_alignment_edge(
        world.token_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
    )
    with pytest.raises(ImmutableViolation), repo.transaction():
        repo.add_token_alignment_edge(duplicate_edge)
    assert repo.get_token_alignment_edge(edge.id) == edge
    assert repo.list_token_alignment_edges_for_run(world.token_run.id) == [edge]


# --- eager reference validation ---------------------------------------------------------------


def test_foreign_member_and_edge_rejected(repo: Repository) -> None:
    world = _alignment_world(repo)

    missing_segment = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    ).model_copy(update={"source_segment_ids": (new_id(IdPrefix.SEGMENT),)})
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_segment_alignment(missing_segment)

    other_norm = make_run(
        stage=RunStage.NORMALIZATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=_key("n9"),
    )
    foreign_run_segment = make_segment(
        world.source, world.source_object, other_norm, ordinal=9, language="mzr"
    )
    with repo.transaction():
        repo.add_run(other_norm)
        repo.add_segment(foreign_run_segment)
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_segment_alignment(
            make_segment_alignment(world.align_run, [foreign_run_segment], world.tgt_segments[:1])
        )

    wrong_language = make_segment(
        world.source, world.source_object, world.src_norm_run, ordinal=9, language="por"
    )
    with repo.transaction():
        repo.add_segment(wrong_language)
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_segment_alignment(
            make_segment_alignment(world.align_run, [wrong_language], world.tgt_segments[:1])
        )

    wrong_stage = make_run(stage=RunStage.EXTRACTION, run_key=_key("x"))
    with repo.transaction():
        repo.add_run(wrong_stage)
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_segment_alignment(
            make_segment_alignment(wrong_stage, world.src_segments[:1], world.tgt_segments[:1])
        )
    missing_run = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    ).model_copy(update={"run_id": new_id(IdPrefix.RUN)})
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_segment_alignment(missing_run)
    malformed_config = make_run(
        stage=RunStage.SEGMENT_ALIGNMENT, config={"batch": 1}, run_key=_key("mc")
    )
    with repo.transaction():
        repo.add_run(malformed_config)
    with pytest.raises(SchemaViolation), repo.transaction():
        repo.add_segment_alignment(
            make_segment_alignment(malformed_config, world.src_segments[:1], world.tgt_segments[:1])
        )

    alignment = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    )
    with repo.transaction():
        repo.add_segment_alignment(alignment)

    missing_alignment = make_token_alignment_edge(
        world.token_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
    ).model_copy(update={"segment_alignment_id": new_id(IdPrefix.SEGMENT_ALIGNMENT)})
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_token_alignment_edge(missing_alignment)

    outside = make_segment(
        world.source, world.source_object, world.src_norm_run, ordinal=8, language="mzr"
    )
    outside_token = make_token(outside, world.src_tok_run, ordinal=0)
    with repo.transaction():
        repo.add_segment(outside)
        repo.add_token(outside_token)
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_token_alignment_edge(
            make_token_alignment_edge(
                world.token_run, alignment, outside_token, world.tgt_tokens[0]
            )
        )

    other_tok = make_run(
        stage=RunStage.TOKENIZATION, status=RunStatus.SUCCEEDED, finished_at=NOW, run_key=_key("t9")
    )
    unselected_token = make_token(world.src_segments[0], other_tok, ordinal=5)
    with repo.transaction():
        repo.add_run(other_tok)
        repo.add_token(unselected_token)
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_token_alignment_edge(
            make_token_alignment_edge(
                world.token_run, alignment, unselected_token, world.tgt_tokens[0]
            )
        )

    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_token_alignment_edge(
            make_token_alignment_edge(
                world.align_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
            )
        )
    missing_token_run = make_token_alignment_edge(
        world.token_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
    ).model_copy(update={"run_id": new_id(IdPrefix.RUN)})
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_token_alignment_edge(missing_token_run)

    # Nothing above persisted rejected evidence.
    assert repo.count(EntityType.SEGMENT_ALIGNMENT) == 1
    assert repo.count(EntityType.TOKEN_ALIGNMENT_EDGE) == 0
    assert repo.get_segment_alignment(alignment.id) == alignment


# --- disposition references (approved/rejected successors) ------------------------------------


def test_disposition_references_required_and_validated(repo: Repository) -> None:
    # Three source segments yield four distinct member sets, hence four distinct natural
    # group keys inside one run.
    world = _alignment_world(repo, source_segments=3)
    predecessor = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    )
    with repo.transaction():
        repo.add_segment_alignment(predecessor)
    basis = make_artifact(world.align_run)
    with repo.transaction():
        repo.add_artifact(basis)

    # Each missing reference is rejected independently while the other reference is real.
    missing_basis = make_segment_alignment(
        world.align_run,
        world.src_segments[1:2],
        world.tgt_segments[:1],
        status=AlignmentStatus.APPROVED,
        authorization_basis_id=new_id(IdPrefix.ARTIFACT),
        supersedes_id=predecessor.id,
    )
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_segment_alignment(missing_basis)

    missing_predecessor = make_segment_alignment(
        world.align_run,
        world.src_segments[2:3],
        world.tgt_segments[:1],
        status=AlignmentStatus.REJECTED,
        authorization_basis_id=basis.id,
        supersedes_id=new_id(IdPrefix.SEGMENT_ALIGNMENT),
    )
    with pytest.raises(InvalidLineage), repo.transaction():
        repo.add_segment_alignment(missing_predecessor)

    # Failed writes leave no parent, registry, list or natural-key entries behind.
    with pytest.raises(NotFound):
        repo.get_segment_alignment(missing_basis.id)
    with pytest.raises(NotFound):
        repo.get_segment_alignment(missing_predecessor.id)
    assert repo.entity_type_of(missing_basis.id) is None
    assert repo.entity_type_of(missing_predecessor.id) is None
    assert [item.id for item in repo.list_segment_alignments_for_run(world.align_run.id)] == [
        predecessor.id
    ]
    reuse_basis_group = make_segment_alignment(
        world.align_run, world.src_segments[1:2], world.tgt_segments[:1]
    )
    reuse_predecessor_group = make_segment_alignment(
        world.align_run, world.src_segments[2:3], world.tgt_segments[:1]
    )
    with repo.transaction():
        repo.add_segment_alignment(reuse_basis_group)
        repo.add_segment_alignment(reuse_predecessor_group)

    # A successor carrying only real references commits on both backends.
    successor = make_segment_alignment(
        world.align_run,
        world.src_segments[:2],
        world.tgt_segments[:1],
        status=AlignmentStatus.APPROVED,
        authorization_basis_id=basis.id,
        supersedes_id=predecessor.id,
    )
    with repo.transaction():
        repo.add_segment_alignment(successor)
    assert repo.get_segment_alignment(successor.id) == successor
    assert repo.entity_type_of(successor.id) is EntityType.SEGMENT_ALIGNMENT
    assert repo.count(EntityType.SEGMENT_ALIGNMENT) == 4


# --- optional tokenization pins ---------------------------------------------------------------

# Present-but-malformed values must be rejected eagerly: silently dropping them to an
# omitted pin made the backends disagree (memory committed, PostgreSQL's deferred
# selected-sides guard rejected the same write).
_OMITTED = object()
_PIN_CASES = [
    pytest.param(42, 0, id="int-source"),
    pytest.param(True, 0, id="true-source"),
    pytest.param(False, 0, id="false-source"),
    pytest.param(["run_x"], 0, id="array-source"),
    pytest.param({"id": "run_x"}, 0, id="object-source"),
    pytest.param("", 0, id="empty-string-source"),
    pytest.param(42, 1, id="int-target"),
]


def _side_config(
    world: AlignmentWorld, *, stage5: bool, pin: object, side_index: int
) -> dict[str, Any]:
    config = alignment_sides_config(
        world.source.id,
        world.src_norm_run.id,
        world.tgt_norm_run.id,
        source_tokenization_run_id=world.src_tok_run.id if stage5 else None,
        target_tokenization_run_id=world.tgt_tok_run.id if stage5 else None,
    )
    side = config["sides"][side_index]
    if pin is _OMITTED:
        del side["tokenization_run_id"]
    else:
        side["tokenization_run_id"] = pin
    return config


@pytest.mark.parametrize(("pin", "side_index"), _PIN_CASES)
def test_stage4_rejects_malformed_tokenization_pins(
    repo: Repository, pin: object, side_index: int
) -> None:
    world = _alignment_world(repo)
    run = make_run(
        stage=RunStage.SEGMENT_ALIGNMENT,
        config=_side_config(world, stage5=False, pin=pin, side_index=side_index),
        run_key=_key("m4"),
    )
    with repo.transaction():
        repo.add_run(run)
    alignment = make_segment_alignment(run, world.src_segments[:1], world.tgt_segments[:1])
    with pytest.raises(SchemaViolation), repo.transaction():
        repo.add_segment_alignment(alignment)
    with pytest.raises(NotFound):
        repo.get_segment_alignment(alignment.id)
    assert repo.entity_type_of(alignment.id) is None
    assert repo.list_segment_alignments_for_run(run.id) == []


@pytest.mark.parametrize(
    "pin", [pytest.param(None, id="null"), pytest.param(_OMITTED, id="omitted")]
)
def test_stage4_allows_omitted_or_null_tokenization_pins(repo: Repository, pin: object) -> None:
    world = _alignment_world(repo)
    run = make_run(
        stage=RunStage.SEGMENT_ALIGNMENT,
        config=_side_config(world, stage5=False, pin=pin, side_index=0),
        run_key=_key("s4"),
    )
    with repo.transaction():
        repo.add_run(run)
    alignment = make_segment_alignment(run, world.src_segments[:1], world.tgt_segments[:1])
    with repo.transaction():
        repo.add_segment_alignment(alignment)
    assert repo.get_segment_alignment(alignment.id) == alignment


@pytest.mark.parametrize(("pin", "side_index"), _PIN_CASES)
def test_stage5_rejects_malformed_tokenization_pins(
    repo: Repository, pin: object, side_index: int
) -> None:
    world = _alignment_world(repo)
    run = make_run(
        stage=RunStage.TOKEN_ALIGNMENT,
        config=_side_config(world, stage5=True, pin=pin, side_index=side_index),
        run_key=_key("m5"),
    )
    with repo.transaction():
        repo.add_run(run)
    alignment = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    )
    with repo.transaction():
        repo.add_segment_alignment(alignment)
    edge = make_token_alignment_edge(run, alignment, world.src_tokens[0], world.tgt_tokens[0])
    with pytest.raises(SchemaViolation), repo.transaction():
        repo.add_token_alignment_edge(edge)
    with pytest.raises(NotFound):
        repo.get_token_alignment_edge(edge.id)
    assert repo.entity_type_of(edge.id) is None
    assert repo.list_token_alignment_edges_for_run(run.id) == []


@pytest.mark.parametrize(
    "pin", [pytest.param(None, id="null"), pytest.param(_OMITTED, id="omitted")]
)
def test_stage5_requires_a_present_tokenization_pin(repo: Repository, pin: object) -> None:
    # Stage 5 pins are required: an absent or explicitly null pin is a schema violation,
    # never a silently dropped one. The positive control is a nonempty string pin.
    world = _alignment_world(repo)
    run = make_run(
        stage=RunStage.TOKEN_ALIGNMENT,
        config=_side_config(world, stage5=True, pin=pin, side_index=0),
        run_key=_key("s5"),
    )
    with repo.transaction():
        repo.add_run(run)
    alignment = make_segment_alignment(
        world.align_run, world.src_segments[:1], world.tgt_segments[:1]
    )
    with repo.transaction():
        repo.add_segment_alignment(alignment)
    edge = make_token_alignment_edge(run, alignment, world.src_tokens[0], world.tgt_tokens[0])
    with pytest.raises(SchemaViolation), repo.transaction():
        repo.add_token_alignment_edge(edge)
    with pytest.raises(NotFound):
        repo.get_token_alignment_edge(edge.id)

    control = make_token_alignment_edge(
        world.token_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
    )
    with repo.transaction():
        repo.add_token_alignment_edge(control)
    assert repo.get_token_alignment_edge(control.id) == control


# --- atomic rollback ------------------------------------------------------------------------


def test_rollback_removes_rows_registry_indexes_and_members(repo: Repository) -> None:
    world = _alignment_world(repo)  # committed substrate stays behind
    alignment = make_segment_alignment(world.align_run, world.src_segments, world.tgt_segments)
    edge = make_token_alignment_edge(
        world.token_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
    )
    with pytest.raises(_Boom), repo.transaction():
        repo.add_segment_alignment(alignment)
        repo.add_token_alignment_edge(edge)
        # Visible inside the open transaction...
        assert repo.get_segment_alignment(alignment.id) == alignment
        assert repo.get_token_alignment_edge(edge.id) == edge
        raise _Boom

    # ...and gone after rollback, together with registry rows and list indexes.
    with pytest.raises(NotFound):
        repo.get_segment_alignment(alignment.id)
    with pytest.raises(NotFound):
        repo.get_token_alignment_edge(edge.id)
    assert repo.entity_type_of(alignment.id) is None
    assert repo.entity_type_of(edge.id) is None
    assert repo.count(EntityType.SEGMENT_ALIGNMENT) == 0
    assert repo.count(EntityType.TOKEN_ALIGNMENT_EDGE) == 0
    assert repo.list_segment_alignments_for_run(world.align_run.id) == []
    assert repo.list_token_alignment_edges_for_run(world.token_run.id) == []
    assert repo.count_lineage_edges() == 0

    # The rolled-back indexes no longer hold the identifiers or natural keys, so the very
    # same alignment and edge can be stored again.
    with repo.transaction():
        repo.add_segment_alignment(alignment)
        repo.add_token_alignment_edge(edge)
    assert repo.get_segment_alignment(alignment.id) == alignment
    assert repo.get_token_alignment_edge(edge.id) == edge


# --- defensive copies ------------------------------------------------------------------------


def test_defensive_copies(repo: Repository) -> None:
    world = _alignment_world(repo)
    alignment = make_segment_alignment(
        world.align_run, world.src_segments, world.tgt_segments, raw_scores={"coordinate": 1.0}
    )
    edge = make_token_alignment_edge(
        world.token_run, alignment, world.src_tokens[0], world.tgt_tokens[0]
    )
    with repo.transaction():
        repo.add_segment_alignment(alignment)
        repo.add_token_alignment_edge(edge)

    alignment.raw_scores["injected"] = 2.0
    edge.raw_scores["injected"] = 2.0
    stored_alignment = repo.get_segment_alignment(alignment.id)
    stored_edge = repo.get_token_alignment_edge(edge.id)
    stored_alignment.raw_scores["mutated"] = 3.0
    stored_edge.raw_scores["mutated"] = 3.0
    listed = repo.list_segment_alignments_for_run(world.align_run.id)
    listed_edges = repo.list_token_alignment_edges_for_run(world.token_run.id)
    listed[0].raw_scores["mutated"] = 4.0
    listed_edges[0].raw_scores["mutated"] = 4.0

    assert repo.get_segment_alignment(alignment.id).raw_scores == {"coordinate": 1.0}
    assert repo.get_token_alignment_edge(edge.id).raw_scores == {}
    assert repo.list_segment_alignments_for_run(world.align_run.id)[0].raw_scores == {
        "coordinate": 1.0
    }
    assert repo.list_token_alignment_edges_for_run(world.token_run.id)[0].raw_scores == {}


# --- exact lineage graph ---------------------------------------------------------------------


def test_member_endpoint_ancestry_exact(repo: Repository) -> None:
    world = _alignment_world(repo)
    alignment = make_segment_alignment(world.align_run, world.src_segments, world.tgt_segments)
    src_token = world.src_tokens[0]
    tgt_token = world.tgt_tokens[0]
    edge = make_token_alignment_edge(world.token_run, alignment, src_token, tgt_token)
    member_edges = [
        _derived(world.align_run, alignment.id, segment.id)
        for segment in [*world.src_segments, *world.tgt_segments]
    ]
    with repo.transaction():
        repo.add_segment_alignment(alignment)
        repo.add_token_alignment_edge(edge)
        for lineage_edge in member_edges:
            repo.add_lineage_edge(lineage_edge)
        repo.add_lineage_edge(_derived(world.token_run, edge.id, alignment.id))
        repo.add_lineage_edge(_derived(world.token_run, edge.id, src_token.id))
        repo.add_lineage_edge(_derived(world.token_run, edge.id, tgt_token.id))

    # sal -> each member segment exactly once; no sal -> sal Cartesian product.
    assert repo.ancestors(alignment.id) == _by_depth(
        [(segment.id, 1) for segment in [*world.src_segments, *world.tgt_segments]]
    )
    # tal -> sal also makes the edge a depth-2 descendant of every member segment.
    assert repo.descendants(world.src_segments[0].id) == _by_depth(
        [(alignment.id, 1), (edge.id, 2)]
    )
    assert repo.descendants(world.tgt_segments[0].id) == _by_depth(
        [(alignment.id, 1), (edge.id, 2)]
    )

    # tal -> sal plus both endpoint tokens; members appear once more through the sal hop.
    assert repo.ancestors(edge.id) == _by_depth(
        [
            (alignment.id, 1),
            (src_token.id, 1),
            (tgt_token.id, 1),
            *[(segment.id, 2) for segment in [*world.src_segments, *world.tgt_segments]],
        ]
    )
    expected_edges = len(member_edges) + 3
    assert repo.count_lineage_edges() == expected_edges
    assert repo.entity_type_of(alignment.id) is EntityType.SEGMENT_ALIGNMENT
    assert repo.entity_type_of(edge.id) is EntityType.TOKEN_ALIGNMENT_EDGE


# --- competing runs --------------------------------------------------------------------------


def test_competing_runs_coexist(repo: Repository) -> None:
    world = _alignment_world(repo)
    other_align_run = make_run(
        stage=RunStage.SEGMENT_ALIGNMENT,
        config=alignment_sides_config(
            world.source.id, world.src_norm_run.id, world.tgt_norm_run.id
        ),
        run_key=_key("sal2"),
    )
    with repo.transaction():
        repo.add_run(other_align_run)

    first = make_segment_alignment(world.align_run, world.src_segments[:1], world.tgt_segments[:1])
    # Same segment participates again, in a different run, under the same group key:
    # uniqueness is per run (uq_segment_alignment_run_group_key), never per segment.
    second = make_segment_alignment(
        other_align_run, world.src_segments[:1], world.tgt_segments[:1]
    ).model_copy(update={"group_key": first.group_key})
    with repo.transaction():
        repo.add_segment_alignment(first)
        repo.add_segment_alignment(second)

    assert [item.id for item in repo.list_segment_alignments_for_run(world.align_run.id)] == [
        first.id
    ]
    assert [item.id for item in repo.list_segment_alignments_for_run(other_align_run.id)] == [
        second.id
    ]
    assert repo.get_segment_alignment(first.id).source_segment_ids == first.source_segment_ids


# --- scoped request locks --------------------------------------------------------------------


def test_alignment_lock_scoped_per_request_key(repo: Repository) -> None:
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with repo.alignment_lock("request-a", timeout_seconds=10):
            held.set()
            release.wait(timeout=10)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert held.wait(timeout=10)
        # A different request key is never blocked by the held one.
        with repo.alignment_lock("request-b", timeout_seconds=2):
            pass
        # The held key blocks bounded acquisition: backend_timeout, never an unbounded wait.
        with (
            pytest.raises(AlignmentFailed) as excinfo,
            repo.alignment_lock("request-a", timeout_seconds=0.2),
        ):
            pass
        assert excinfo.value.code == "backend_timeout"
    finally:
        release.set()
        thread.join(timeout=10)
        assert not thread.is_alive()
    # Once released, the key is available again.
    with repo.alignment_lock("request-a", timeout_seconds=2):
        pass


def test_alignment_lock_rejects_zero_timeout(repo: Repository) -> None:
    with (
        pytest.raises(ValueError, match="positive"),
        repo.alignment_lock("request-a", timeout_seconds=0),
    ):
        pass


def test_lock_sources_requires_existing_sources(repo: Repository) -> None:
    world = _alignment_world(repo)
    with repo.transaction():
        repo.lock_sources([world.source.id])
    missing = new_id(IdPrefix.SOURCE)
    with pytest.raises(NotFound), repo.transaction():
        repo.lock_sources([world.source.id, missing])
    # Locking is read-only bookkeeping: the source is untouched either way.
    assert repo.get_source(world.source.id).status is SourceStatus.REGISTERED


def test_lock_sources_rejects_nonpositive_timeout(repo: Repository) -> None:
    world = _alignment_world(repo)
    with pytest.raises(ValueError, match="positive"), repo.transaction():
        repo.lock_sources([world.source.id], timeout_seconds=0)
