"""Shared Repository contract for M5 IGT observations and the morphology graph (WP5.4, ADR-0017).

Runs once per backend via `repo_backend` (in-memory and PostgreSQL). Both backends agree on
the relational contract: object-registry bookkeeping, foreign-key parents, natural-key
uniqueness, ordered listings, atomic status updates and the transaction guard. Data is
synthetic: identifiers and placeholder strings only, never source content.
"""

import hashlib
import itertools
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from langpipe.domain.enums import (
    AnalysisKind,
    EntityType,
    FeatureAssignmentBasis,
    FormBasis,
    IgtFormat,
    IgtParseStatus,
    LifecycleStatus,
    RunStage,
    RunStatus,
    SpanRepresentation,
)
from langpipe.domain.errors import ImmutableViolation, InvalidLineage, NotFound, SchemaViolation
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.igt import IgtMorph, IGTObservation, IgtTierLine, IgtWord
from langpipe.domain.models.morphology import (
    Allomorph,
    Feature,
    MorphAnalysis,
    Morpheme,
    MorphSegment,
    MorphSegmentFeature,
    ScoreBreakdown,
)
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.domain.models.run import ProcessingRun
from langpipe.domain.models.source import Source, SourceObject, SourcePolicy
from langpipe.morphology.spans import segmentation_signature
from langpipe.storage.repository import Repository
from tests.contract.builders import (
    NOW,
    make_policy,
    make_run,
    make_segment,
    make_source,
    make_source_object,
    make_token,
    unique_run_key,
)

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SURFACE = "mabi-ku"
_KEYS = itertools.count()


def _at(seconds: int) -> datetime:
    """Distinct deterministic created_at values, so ordering assertions are exact."""
    return BASE + timedelta(seconds=seconds)


def _fixed_id(prefix: str, discriminator: str) -> str:
    """A syntactically valid identifier with a caller-chosen ULID body (identical backend rows)."""
    assert len(discriminator) == 1 and discriminator.isdigit()
    return f"{prefix}_{discriminator}{('0' * 25)}"


def _identity(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@dataclass
class Substrate:
    """Committed governance and observation lineage every M5 entity hangs from."""

    reg_run: ProcessingRun
    igt_run: ProcessingRun
    tok_run: ProcessingRun
    morph_run: ProcessingRun
    policy: SourcePolicy
    source: Source
    source_object: SourceObject
    segment: Segment
    token: TokenOccurrence


def _substrate(repo: Repository) -> Substrate:
    reg_run = make_run(
        stage=RunStage.SOURCE_REGISTRATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"morph-reg-{next(_KEYS)}"),
    )
    policy = make_policy()
    source = make_source(policy, reg_run.id, key=f"morph-src-{next(_KEYS)}")
    source_object = make_source_object(source, reg_run.id)
    igt_run = make_run(
        stage=RunStage.IGT_IMPORT,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"morph-igt-{next(_KEYS)}"),
    )
    segment = make_segment(source, source_object, igt_run)
    tok_run = make_run(
        stage=RunStage.TOKENIZATION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"morph-tok-{next(_KEYS)}"),
    )
    token = make_token(segment, tok_run, surface=SURFACE)
    morph_run = make_run(
        stage=RunStage.MORPHOLOGY_INDUCTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"morph-run-{next(_KEYS)}"),
    )
    with repo.transaction():
        repo.add_run(reg_run)
        repo.add_policy(policy)
        repo.add_source(source)
        repo.add_source_object(source_object)
        repo.add_run(igt_run)
        repo.add_segment(segment)
        repo.add_run(tok_run)
        repo.add_token(token)
        repo.add_run(morph_run)
    return Substrate(
        reg_run=reg_run,
        igt_run=igt_run,
        tok_run=tok_run,
        morph_run=morph_run,
        policy=policy,
        source=source,
        source_object=source_object,
        segment=segment,
        token=token,
    )


def _observation(sub: Substrate, ordinal: int, **overrides: object) -> IGTObservation:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.IGT_OBSERVATION),
        "source_id": sub.source.id,
        "source_object_id": sub.source_object.id,
        "run_id": sub.igt_run.id,
        "segment_id": sub.segment.id,
        "record_ordinal": ordinal,
        "format": IgtFormat.TOOLBOX,
        "locator": {"line": ordinal + 1},
        "tiers": [IgtTierLine(marker="\\lx", line_number=ordinal + 1, raw="placeholder")],
        "words": [
            IgtWord(
                ordinal=0,
                text=SURFACE,
                morphs=[
                    IgtMorph(ordinal=0, text="mabi"),
                    IgtMorph(ordinal=1, text="ku", boundary_before="-", gloss="ku"),
                ],
            )
        ],
        "translations": {"por": ["placeholder"]},
        "parse_status": IgtParseStatus.OK,
        "diagnostics": [],
        "created_at": _at(ordinal + 20),
    }
    values.update(overrides)
    return IGTObservation.model_validate(values)


def _feature(run_id: str, index: int, label: str, **overrides: object) -> Feature:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.FEATURE),
        "namespace": "local:mzr",
        "label": label,
        "definition": f"synthetic definition {index}",
        "defined_by": "synthetic-profile",
        "run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return Feature.model_validate(values)


def _morpheme(run_id: str, index: int, label: str, **overrides: object) -> Morpheme:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.MORPHEME),
        "language": "mzr",
        "role": "root",
        "canonical_form": label,
        "form_basis": FormBasis.SURFACE,
        "glosses": {"por": [label]},
        "gloss_labels": [],
        "identity_key": _identity(f"{label}"),
        "status": LifecycleStatus.CANDIDATE,
        "run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return Morpheme.model_validate(values)


def _allomorph(
    morpheme_id: str, run_id: str, index: int, form: str, **overrides: object
) -> Allomorph:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.ALLOMORPH),
        "morpheme_id": morpheme_id,
        "form": form,
        "is_zero": form == "",
        "form_basis": FormBasis.SURFACE,
        "conditioning": "unknown",
        "status": LifecycleStatus.CANDIDATE,
        "run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return Allomorph.model_validate(values)


def _stem_and_zero(analysis_id: str, stem: Morpheme) -> list[MorphSegment]:
    """Stem segment plus the zero slot between the boundary mark and the suffix."""
    return [
        MorphSegment(
            id=new_id(IdPrefix.MORPH_SEGMENT),
            analysis_id=analysis_id,
            ordinal=0,
            start=0,
            end=4,
            surface=SURFACE[0:4],
            morpheme_id=stem.id,
            created_at=_at(30),
        ),
        MorphSegment(
            id=new_id(IdPrefix.MORPH_SEGMENT),
            analysis_id=analysis_id,
            ordinal=1,
            start=4,
            end=4,
            is_zero=True,
            surface="",
            created_at=_at(30),
        ),
    ]


def _suffix_segment(
    analysis_id: str, suffix: Morpheme, suffix_allomorph: Allomorph | None
) -> MorphSegment:
    return MorphSegment(
        id=new_id(IdPrefix.MORPH_SEGMENT),
        analysis_id=analysis_id,
        ordinal=2,
        start=5,
        end=7,
        surface=SURFACE[5:7],
        morpheme_id=suffix.id,
        allomorph_id=None if suffix_allomorph is None else suffix_allomorph.id,
        created_at=_at(30),
    )


def _segments_for(
    analysis_id: str, stem: Morpheme, suffix: Morpheme, suffix_allomorph: Allomorph | None
) -> list[MorphSegment]:
    """The canonical three-piece segmentation of SURFACE: stem, zero slot, suffix."""
    return [
        *_stem_and_zero(analysis_id, stem),
        _suffix_segment(analysis_id, suffix, suffix_allomorph),
    ]


def _whole_surface_segment(analysis_id: str) -> MorphSegment:
    return MorphSegment(
        id=new_id(IdPrefix.MORPH_SEGMENT),
        analysis_id=analysis_id,
        ordinal=0,
        start=0,
        end=len(SURFACE),
        surface=SURFACE,
        created_at=_at(31),
    )


def _analysis(
    token_id: str,
    run_id: str,
    segments: list[MorphSegment],
    index: int,
    analysis_id: str | None = None,
    **overrides: object,
) -> MorphAnalysis:
    values: dict[str, object] = {
        "id": analysis_id or new_id(IdPrefix.MORPH_ANALYSIS),
        "target_token_id": token_id,
        "analysis_kind": AnalysisKind.SEGMENTED,
        "method": "synthetic@0.1.0",
        "span_representation": SpanRepresentation.RAW,
        "surface": SURFACE,
        "signature": segmentation_signature(AnalysisKind.SEGMENTED, segments),
        "status": LifecycleStatus.CANDIDATE,
        "run_id": run_id,
        "created_at": _at(index),
    }
    values.update(overrides)
    return MorphAnalysis.model_validate(values)


def _assignment(segment_id: str, feature_id: str, index: int) -> MorphSegmentFeature:
    return MorphSegmentFeature(
        segment_id=segment_id,
        feature_id=feature_id,
        basis=FeatureAssignmentBasis.IGT_GLOSS,
        created_at=_at(index),
    )


@dataclass
class MorphWorld:
    """Committed substrate plus one full morphology graph over the shared token."""

    substrate: Substrate
    observation: IGTObservation
    features: list[Feature] = field(default_factory=list)
    morphemes: list[Morpheme] = field(default_factory=list)
    allomorph: Allomorph | None = None
    zero_allomorph: Allomorph | None = None
    analysis: MorphAnalysis | None = None
    segments: list[MorphSegment] = field(default_factory=list)
    assignments: list[MorphSegmentFeature] = field(default_factory=list)


def _morph_world(repo: Repository) -> MorphWorld:
    sub = _substrate(repo)
    observation = _observation(sub, 0)
    pst = _feature(
        sub.morph_run.id, 9, "Pst", id=_fixed_id(IdPrefix.FEATURE.value, "5"), namespace="local:mzr"
    )
    person = _feature(sub.morph_run.id, 9, "3sg", id=_fixed_id(IdPrefix.FEATURE.value, "9"))
    stem = _morpheme(sub.morph_run.id, 10, "mabi")
    suffix = _morpheme(
        sub.morph_run.id, 11, "ku", role="inflectional_affix", gloss_labels=["3SG", "PST"]
    )
    suffix_allomorph = _allomorph(suffix.id, sub.morph_run.id, 12, "ku")
    zero_allomorph = _allomorph(stem.id, sub.morph_run.id, 12, "")
    analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
    segments = _segments_for(analysis_id, stem, suffix, suffix_allomorph)
    analysis = _analysis(sub.token.id, sub.morph_run.id, segments, 13, analysis_id=analysis_id)
    assignments = [
        _assignment(segments[0].id, pst.id, 14),
        _assignment(segments[0].id, person.id, 14),
    ]
    with repo.transaction():
        repo.add_igt_observation(observation)
        repo.add_feature(pst)
        repo.add_feature(person)
        repo.add_morpheme(stem)
        repo.add_morpheme(suffix)
        repo.add_allomorph(suffix_allomorph)
        repo.add_allomorph(zero_allomorph)
        repo.add_morph_analysis(analysis, segments, assignments)
    return MorphWorld(
        substrate=sub,
        observation=observation,
        features=[pst, person],
        morphemes=[stem, suffix],
        allomorph=suffix_allomorph,
        zero_allomorph=zero_allomorph,
        analysis=analysis,
        segments=segments,
        assignments=assignments,
    )


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def repo_backend(request: pytest.FixtureRequest) -> Iterator[Repository]:
    if request.param == "memory":
        from langpipe.storage.memory import InMemoryRepository

        yield InMemoryRepository()
        return
    yield request.getfixturevalue("pg_repository")


@pytest.fixture
def world(repo_backend: Repository) -> MorphWorld:
    return _morph_world(repo_backend)


# --- transaction guard ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda repo, world: repo.add_igt_observation(world.observation),
        lambda repo, world: repo.add_feature(world.features[0]),
        lambda repo, world: repo.add_morpheme(world.morphemes[0]),
        lambda repo, world: repo.add_allomorph(world.allomorph),
        lambda repo, world: repo.add_morph_analysis(world.analysis, world.segments),
        lambda repo, world: repo.set_morpheme_status(
            world.morphemes[0].id, LifecycleStatus.SUPPORTED
        ),
        lambda repo, world: repo.set_allomorph_status(
            world.allomorph.id, LifecycleStatus.SUPPORTED
        ),
        lambda repo, world: repo.set_morph_analysis_status(
            world.analysis.id, LifecycleStatus.REJECTED
        ),
        lambda repo, world: repo.get_morpheme_for_update(world.morphemes[0].id),
        lambda repo, world: repo.get_morph_analysis_for_update(world.analysis.id),
    ],
)
def test_morphology_write_requires_transaction(repo_backend: Repository, call: object) -> None:
    committed = _morph_world(repo_backend)
    with pytest.raises(RuntimeError, match="write outside transaction"):
        call(repo_backend, committed)  # type: ignore[operator]


# --- IGT observations (append-only) -------------------------------------------------------------


def test_igt_observation_round_trip(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)

    assert repo_backend.get_igt_observation(world.observation.id) == world.observation
    assert repo_backend.list_igt_observations_for_run(world.substrate.igt_run.id) == [
        world.observation
    ]
    assert repo_backend.list_igt_observations_for_object(world.substrate.source_object.id) == [
        world.observation
    ]
    assert repo_backend.entity_type_of(world.observation.id) is EntityType.IGT_OBSERVATION
    assert repo_backend.count(EntityType.IGT_OBSERVATION) == 1


def test_igt_observations_are_ordered_by_record_ordinal_then_id(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    # The (run, source_object, record_ordinal) natural key forces the ordinal tie onto
    # observations from two different runs over the same object.
    second_run = make_run(
        stage=RunStage.IGT_IMPORT,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"morph-igt2-{next(_KEYS)}"),
    )
    late_id = _observation(sub, 1, id=_fixed_id(IdPrefix.IGT_OBSERVATION.value, "9"))
    early_id = _observation(
        sub, 1, id=_fixed_id(IdPrefix.IGT_OBSERVATION.value, "5"), run_id=second_run.id
    )
    first = _observation(sub, 0, id=_fixed_id(IdPrefix.IGT_OBSERVATION.value, "3"))
    with repo_backend.transaction():
        repo_backend.add_run(second_run)
        repo_backend.add_igt_observation(late_id)
        repo_backend.add_igt_observation(early_id)
        repo_backend.add_igt_observation(first)

    # Insertion order decides nothing: (record_ordinal, id) governs.
    assert repo_backend.list_igt_observations_for_object(sub.source_object.id) == [
        first,
        early_id,
        late_id,
    ]
    assert repo_backend.list_igt_observations_for_run(sub.igt_run.id) == [first, late_id]
    assert repo_backend.list_igt_observations_for_run(second_run.id) == [early_id]


def test_igt_observation_uniqueness_and_lineage(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    observation = _observation(sub, 0)
    with repo_backend.transaction():
        repo_backend.add_igt_observation(observation)

    # Same (run, source_object, record_ordinal) under a fresh identifier is refused.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_igt_observation(_observation(sub, 0))
    # The same identifier under a fresh ordinal is an attempt to rewrite an existing object.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_igt_observation(_observation(sub, 1, id=observation.id))
    # Every lineage parent must exist before the observation is stored.
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_igt_observation(_observation(sub, 2, source_id=new_id(IdPrefix.SOURCE)))
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_igt_observation(
            _observation(sub, 2, source_object_id=new_id(IdPrefix.SOURCE_OBJECT))
        )
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_igt_observation(_observation(sub, 2, run_id=new_id(IdPrefix.RUN)))
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_igt_observation(_observation(sub, 2, segment_id=new_id(IdPrefix.SEGMENT)))
    assert repo_backend.count(EntityType.IGT_OBSERVATION) == 1


def test_unknown_igt_identifiers_raise_not_found(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    with pytest.raises(NotFound):
        repo_backend.get_igt_observation(new_id(IdPrefix.IGT_OBSERVATION))
    assert repo_backend.list_igt_observations_for_run(world.substrate.tok_run.id) == []
    assert repo_backend.list_igt_observations_for_object(new_id(IdPrefix.SOURCE_OBJECT)) == []


# --- feature vocabulary (idempotent) -------------------------------------------------------------


def test_add_feature_is_idempotent_on_natural_key(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    pst = _feature(sub.morph_run.id, 9, "Pst", id=_fixed_id(IdPrefix.FEATURE.value, "5"))
    with repo_backend.transaction():
        repo_backend.add_feature(pst)

    # Same (namespace, label) under a fresh identifier: the stored row is returned, not an error.
    again = _feature(sub.morph_run.id, 10, "Pst")
    with repo_backend.transaction():
        returned = repo_backend.add_feature(again)

    assert returned == pst
    assert repo_backend.get_feature(pst.id) == pst
    with pytest.raises(NotFound):
        repo_backend.get_feature(again.id)
    assert repo_backend.entity_type_of(again.id) is None
    assert repo_backend.count(EntityType.FEATURE) == 1


def test_add_feature_same_identifier_new_natural_key_refused(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    pst = _feature(sub.morph_run.id, 9, "Pst", id=_fixed_id(IdPrefix.FEATURE.value, "5"))
    with repo_backend.transaction():
        repo_backend.add_feature(pst)
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_feature(_feature(sub.morph_run.id, 10, "3sg", id=pst.id))
    assert repo_backend.count(EntityType.FEATURE) == 1


def test_feature_missing_run_rejected(repo_backend: Repository) -> None:
    _substrate(repo_backend)
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_feature(_feature(new_id(IdPrefix.RUN), 9, "Pst"))
    assert repo_backend.count(EntityType.FEATURE) == 0


def test_feature_lookups_and_listing_order(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    pst = _feature(sub.morph_run.id, 9, "Pst", id=_fixed_id(IdPrefix.FEATURE.value, "5"))
    three_sg = _feature(sub.morph_run.id, 9, "3sg", id=_fixed_id(IdPrefix.FEATURE.value, "9"))
    other = _feature(sub.morph_run.id, 10, "Acc", namespace="unimorph")
    with repo_backend.transaction():
        repo_backend.add_feature(pst)
        repo_backend.add_feature(three_sg)
        repo_backend.add_feature(other)

    assert repo_backend.get_feature_by_label("local:mzr", "Pst") == pst
    assert repo_backend.get_feature_by_label("local:mzr", "nope") is None
    # Ordered by (namespace, label, id): digits sort before uppercase letters.
    assert repo_backend.list_features() == [three_sg, pst, other]
    assert repo_backend.list_features(namespace="local:mzr") == [three_sg, pst]
    assert repo_backend.list_features(namespace="ud") == []


# --- morphemes ------------------------------------------------------------------------------------


def test_morpheme_round_trip_and_uniqueness(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    stem, suffix = world.morphemes

    assert repo_backend.get_morpheme(stem.id) == stem
    assert repo_backend.entity_type_of(stem.id) is EntityType.MORPHEME
    assert repo_backend.list_morphemes_for_run(world.substrate.morph_run.id) == [stem, suffix]

    # Same (run, identity_key) under a fresh identifier is refused.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_morpheme(
            _morpheme(world.substrate.morph_run.id, 40, "mabi", id=new_id(IdPrefix.MORPHEME))
        )
    # The same identifier is an attempt to rewrite an existing object.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_morpheme(_morpheme(world.substrate.morph_run.id, 41, "ku", id=stem.id))
    # A missing producing run is a lineage error.
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_morpheme(_morpheme(new_id(IdPrefix.RUN), 42, "xuxu"))
    assert repo_backend.count(EntityType.MORPHEME) == 2


def test_list_morphemes_for_run_ordered_by_created_then_id(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    later = _morpheme(sub.morph_run.id, 50, "late", id=_fixed_id(IdPrefix.MORPHEME.value, "9"))
    before_it = _morpheme(sub.morph_run.id, 49, "early", id=_fixed_id(IdPrefix.MORPHEME.value, "5"))
    with repo_backend.transaction():
        repo_backend.add_morpheme(later)
        repo_backend.add_morpheme(before_it)

    assert repo_backend.list_morphemes_for_run(sub.morph_run.id) == [before_it, later]


def test_set_morpheme_status_is_atomic_and_returned(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    breakdown = ScoreBreakdown(
        policy_version="morph-v1",
        overall=0.75,
        components={"igt_support": 2.0, "boundary_mark_support": 1.0},
        penalties={},
        independence_groups=["igt"],
    )

    with repo_backend.transaction():
        morpheme = repo_backend.set_morpheme_status(
            world.morphemes[0].id, LifecycleStatus.SUPPORTED, breakdown
        )
        assert morpheme.status is LifecycleStatus.SUPPORTED
        assert morpheme.score_breakdown == breakdown
        # Visible inside the open transaction...
        assert repo_backend.get_morpheme(world.morphemes[0].id) == morpheme

    # ...and committed after it.
    assert repo_backend.get_morpheme(world.morphemes[0].id) == morpheme


def test_set_morpheme_status_without_breakdown_stores_none(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    breakdown = ScoreBreakdown(
        policy_version="morph-v1",
        overall=0.75,
        components={"igt_support": 2.0, "boundary_mark_support": 1.0},
        penalties={},
        independence_groups=["igt"],
    )
    with repo_backend.transaction():
        morpheme = repo_backend.set_morpheme_status(
            world.morphemes[0].id, LifecycleStatus.SUPPORTED, breakdown
        )
        assert morpheme.score_breakdown == breakdown
    # Omitting the breakdown is not "leave as stored": it stores None, matching M4's
    # set_lexeme_status semantics.
    with repo_backend.transaction():
        morpheme = repo_backend.set_morpheme_status(
            world.morphemes[0].id, LifecycleStatus.SUPPORTED
        )
        assert morpheme.status is LifecycleStatus.SUPPORTED
        assert morpheme.score_breakdown is None
    assert repo_backend.get_morpheme(world.morphemes[0].id).score_breakdown is None


def test_set_morpheme_status_missing_raises_not_found(repo_backend: Repository) -> None:
    _morph_world(repo_backend)
    with pytest.raises(NotFound), repo_backend.transaction():
        repo_backend.set_morpheme_status(new_id(IdPrefix.MORPHEME), LifecycleStatus.SUPPORTED)


# --- allomorphs ---------------------------------------------------------------------------------


def test_allomorph_listing_uniqueness_and_lineage(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    stem, suffix = world.morphemes

    # The allomorphs round-trip through their morphemes' listings.
    assert repo_backend.list_allomorphs_for_morpheme(stem.id) == [world.zero_allomorph]
    assert repo_backend.list_allomorphs_for_morpheme(suffix.id) == [world.allomorph]
    assert repo_backend.entity_type_of(world.allomorph.id) is EntityType.ALLOMORPH

    # Same (morpheme, form) under a fresh identifier is refused.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_allomorph(_allomorph(suffix.id, world.substrate.morph_run.id, 40, "ku"))
    # Two zero allomorphs of one morpheme share the empty form, so they collide too.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_allomorph(_allomorph(stem.id, world.substrate.morph_run.id, 41, ""))
    # The same identifier is an attempt to rewrite an existing object.
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_allomorph(
            _allomorph(stem.id, world.substrate.morph_run.id, 42, "mabi", id=world.allomorph.id)
        )
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_allomorph(
            _allomorph(new_id(IdPrefix.MORPHEME), world.substrate.morph_run.id, 43, "x")
        )
    with pytest.raises(InvalidLineage), repo_backend.transaction():
        repo_backend.add_allomorph(_allomorph(stem.id, new_id(IdPrefix.RUN), 44, "mabi-x"))
    assert repo_backend.count(EntityType.ALLOMORPH) == 2


def test_allomorphs_are_ordered_by_created_then_id(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    stem = _morpheme(sub.morph_run.id, 45, "stem")
    first = _allomorph(
        stem.id, sub.morph_run.id, 46, "a", id=_fixed_id(IdPrefix.ALLOMORPH.value, "5")
    )
    second = _allomorph(
        stem.id, sub.morph_run.id, 46, "b", id=_fixed_id(IdPrefix.ALLOMORPH.value, "9")
    )
    with repo_backend.transaction():
        repo_backend.add_morpheme(stem)
        repo_backend.add_allomorph(second)
        repo_backend.add_allomorph(first)

    assert repo_backend.list_allomorphs_for_morpheme(stem.id) == [first, second]


def test_set_allomorph_status_is_atomic_and_missing_raises_not_found(
    repo_backend: Repository,
) -> None:
    world = _morph_world(repo_backend)
    with repo_backend.transaction():
        allomorph = repo_backend.set_allomorph_status(world.allomorph.id, LifecycleStatus.SUPPORTED)
        assert allomorph.status is LifecycleStatus.SUPPORTED
        assert repo_backend.list_allomorphs_for_morpheme(world.morphemes[1].id) == [allomorph]
    assert repo_backend.list_allomorphs_for_morpheme(world.morphemes[1].id) == [allomorph]
    with pytest.raises(NotFound), repo_backend.transaction():
        repo_backend.set_allomorph_status(new_id(IdPrefix.ALLOMORPH), LifecycleStatus.REJECTED)


# --- morph analyses, segments and features ----------------------------------------------------


def test_morph_analysis_round_trip(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)

    assert repo_backend.get_morph_analysis(world.analysis.id) == world.analysis
    assert repo_backend.list_morph_segments(world.analysis.id) == world.segments
    assert repo_backend.list_segment_features(world.segments[0].id) == world.assignments
    assert repo_backend.list_morph_segments(new_id(IdPrefix.MORPH_ANALYSIS)) == []
    assert repo_backend.list_segment_features(new_id(IdPrefix.MORPH_SEGMENT)) == []
    assert repo_backend.entity_type_of(world.analysis.id) is EntityType.MORPH_ANALYSIS
    assert repo_backend.entity_type_of(world.segments[1].id) is EntityType.MORPH_SEGMENT
    assert repo_backend.count(EntityType.MORPH_ANALYSIS) == 1
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 3


def test_morph_analysis_listings_are_ordered(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    sub = world.substrate
    # A competing whole-surface analysis of the same token in the same run: distinct signature.
    competing_id = _fixed_id(IdPrefix.MORPH_ANALYSIS.value, "9")
    competing_segments = [_whole_surface_segment(competing_id)]
    competing = _analysis(
        sub.token.id, sub.morph_run.id, competing_segments, 14, analysis_id=competing_id
    )
    # An earlier analysis of the same token from a second run: (created_at, id) ordering.
    earlier_run = make_run(
        stage=RunStage.MORPHOLOGY_INDUCTION,
        status=RunStatus.SUCCEEDED,
        finished_at=NOW,
        run_key=unique_run_key(f"morph-run2-{next(_KEYS)}"),
    )
    earlier_id = _fixed_id(IdPrefix.MORPH_ANALYSIS.value, "5")
    earlier_segments = [_whole_surface_segment(earlier_id)]
    earlier_analysis = _analysis(
        sub.token.id, earlier_run.id, earlier_segments, 12, analysis_id=earlier_id
    )
    with repo_backend.transaction():
        repo_backend.add_run(earlier_run)
        repo_backend.add_morph_analysis(competing, competing_segments)
        repo_backend.add_morph_analysis(earlier_analysis, earlier_segments)

    # Insertion order decides nothing: (created_at, id) governs.
    assert repo_backend.list_morph_analyses_for_token(sub.token.id) == [
        earlier_analysis,
        world.analysis,
        competing,
    ]
    assert repo_backend.list_morph_analyses_for_run(sub.morph_run.id) == [
        world.analysis,
        competing,
    ]
    # Only the world analysis links a morpheme; the competitors carry none.
    assert repo_backend.list_analyses_linking_morpheme(world.morphemes[0].id) == [world.analysis]
    assert repo_backend.list_analyses_linking_morpheme(world.morphemes[1].id) == [world.analysis]
    assert repo_backend.list_analyses_linking_morpheme(new_id(IdPrefix.MORPHEME)) == []


def test_list_analyses_linking_morpheme_deduplicates_multi_segment_links(
    repo_backend: Repository,
) -> None:
    """When one analysis has multiple segments linking the SAME morpheme (e.g. reduplication),
    list_analyses_linking_morpheme must return that analysis exactly once (testing distinct)."""
    sub = _substrate(repo_backend)
    redup_surface = "mabi-mabi"
    redup_token = make_token(sub.segment, sub.tok_run, ordinal=10, surface=redup_surface)
    stem = _morpheme(sub.morph_run.id, 90, "mabi")
    with repo_backend.transaction():
        repo_backend.add_token(redup_token)
        repo_backend.add_morpheme(stem)

    analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
    segments = [
        MorphSegment(
            id=new_id(IdPrefix.MORPH_SEGMENT),
            analysis_id=analysis_id,
            ordinal=0,
            start=0,
            end=4,
            surface="mabi",
            morpheme_id=stem.id,
            created_at=_at(91),
        ),
        MorphSegment(
            id=new_id(IdPrefix.MORPH_SEGMENT),
            analysis_id=analysis_id,
            ordinal=1,
            start=5,
            end=9,
            surface="mabi",
            morpheme_id=stem.id,
            created_at=_at(91),
        ),
    ]
    analysis = _analysis(
        redup_token.id,
        sub.morph_run.id,
        segments,
        92,
        analysis_id=analysis_id,
        surface=redup_surface,
    )
    with repo_backend.transaction():
        repo_backend.add_morph_analysis(analysis, segments)

    linked = repo_backend.list_analyses_linking_morpheme(stem.id)
    assert linked == [analysis]


def test_morph_analysis_lineage_and_schema_guards(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    stem = _morpheme(sub.morph_run.id, 10, "mabi")
    suffix = _morpheme(sub.morph_run.id, 11, "ku")
    pst = _feature(sub.morph_run.id, 9, "Pst")
    # An allomorph of the stem, used below to prove that a segment cannot borrow an
    # allomorph belonging to a different morpheme.
    stem_allomorph = _allomorph(stem.id, sub.morph_run.id, 12, "mabi")
    with repo_backend.transaction():
        repo_backend.add_morpheme(stem)
        repo_backend.add_morpheme(suffix)
        repo_backend.add_feature(pst)
        repo_backend.add_allomorph(stem_allomorph)

    def valid_pair() -> tuple[MorphAnalysis, list[MorphSegment]]:
        analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
        segments = _segments_for(analysis_id, stem, suffix, None)
        analysis = _analysis(sub.token.id, sub.morph_run.id, segments, 13, analysis_id=analysis_id)
        return analysis, segments

    def attempt(
        analysis: MorphAnalysis | None = None,
        segments: list[MorphSegment] | None = None,
        assignments: list[MorphSegmentFeature] | None = None,
    ) -> None:
        if analysis is None or segments is None:
            analysis, segments = valid_pair()
        if assignments is None:
            assignments = [_assignment(segments[0].id, pst.id, 14)]
        with repo_backend.transaction():
            repo_backend.add_morph_analysis(
                analysis, segments, assignments, boundary_marks=("-", "=")
            )

    # Missing target token.
    missing_id = new_id(IdPrefix.MORPH_ANALYSIS)
    missing_segments = _segments_for(missing_id, stem, suffix, None)
    with pytest.raises(InvalidLineage):
        attempt(
            analysis=_analysis(
                new_id(IdPrefix.TOKEN),
                sub.morph_run.id,
                missing_segments,
                13,
                analysis_id=missing_id,
            ),
            segments=missing_segments,
        )
    # Surface mismatch against the token's raw surface.
    mismatch_id = new_id(IdPrefix.MORPH_ANALYSIS)
    mismatch_segments = _segments_for(mismatch_id, stem, suffix, None)
    with pytest.raises(SchemaViolation):
        attempt(
            analysis=_analysis(
                sub.token.id,
                sub.morph_run.id,
                mismatch_segments,
                13,
                analysis_id=mismatch_id,
                surface="mismat",
            ),
            segments=mismatch_segments,
        )
    # Dangling morpheme reference on a segment.
    dangling_id = new_id(IdPrefix.MORPH_ANALYSIS)
    dangling_segments = _segments_for(dangling_id, stem, suffix, None)
    dangling_segments[0] = dangling_segments[0].model_copy(
        update={"morpheme_id": new_id(IdPrefix.MORPHEME)}
    )
    with pytest.raises(InvalidLineage):
        attempt(
            analysis=_analysis(
                sub.token.id, sub.morph_run.id, dangling_segments, 13, analysis_id=dangling_id
            ),
            segments=dangling_segments,
        )
    # Dangling allomorph reference on a segment.
    allo_id = new_id(IdPrefix.MORPH_ANALYSIS)
    allo_segments = _segments_for(allo_id, stem, suffix, None)
    allo_segments[2] = allo_segments[2].model_copy(
        update={"allomorph_id": new_id(IdPrefix.ALLOMORPH)}
    )
    with pytest.raises(InvalidLineage):
        attempt(
            analysis=_analysis(
                sub.token.id, sub.morph_run.id, allo_segments, 13, analysis_id=allo_id
            ),
            segments=allo_segments,
        )
    # An existing allomorph that belongs to a different morpheme is equally refused:
    # otherwise `list_analyses_linking_morpheme(suffix)` and
    # `list_allomorphs_for_morpheme(suffix)` would disagree about the same analysis.
    foreign_id = new_id(IdPrefix.MORPH_ANALYSIS)
    foreign_segments = _segments_for(foreign_id, stem, suffix, None)
    foreign_segments[2] = foreign_segments[2].model_copy(update={"allomorph_id": stem_allomorph.id})
    with pytest.raises(InvalidLineage):
        attempt(
            analysis=_analysis(
                sub.token.id, sub.morph_run.id, foreign_segments, 13, analysis_id=foreign_id
            ),
            segments=foreign_segments,
        )
    # Dangling feature reference on an assignment.
    feature_id = new_id(IdPrefix.MORPH_ANALYSIS)
    feature_segments = _segments_for(feature_id, stem, suffix, None)
    feature_analysis = _analysis(
        sub.token.id, sub.morph_run.id, feature_segments, 13, analysis_id=feature_id
    )
    with pytest.raises(InvalidLineage):
        attempt(
            feature_analysis,
            feature_segments,
            [_assignment(feature_segments[0].id, new_id(IdPrefix.FEATURE), 14)],
        )
    # An assignment may only ride on a segment of the analysis being written.
    outside_id = new_id(IdPrefix.MORPH_ANALYSIS)
    outside_segments = _segments_for(outside_id, stem, suffix, None)
    outside_analysis = _analysis(
        sub.token.id, sub.morph_run.id, outside_segments, 13, analysis_id=outside_id
    )
    with pytest.raises(InvalidLineage):
        attempt(
            outside_analysis,
            outside_segments,
            [_assignment(new_id(IdPrefix.MORPH_SEGMENT), pst.id, 14)],
        )
    # Signature pinned to the segmentation: a re-signed analysis is a schema violation.
    sig_id = new_id(IdPrefix.MORPH_ANALYSIS)
    sig_segments = _segments_for(sig_id, stem, suffix, None)
    sig_analysis = _analysis(sub.token.id, sub.morph_run.id, sig_segments, 13, analysis_id=sig_id)
    with pytest.raises(SchemaViolation):
        attempt(sig_analysis.model_copy(update={"signature": "0" * 64}), sig_segments)
    # Uncovered code points beyond the profile boundary marks break the segmentation contract.
    gap_id = new_id(IdPrefix.MORPH_ANALYSIS)
    gap_segments = _segments_for(gap_id, stem, suffix, None)[:1]
    with pytest.raises(SchemaViolation):
        attempt(
            analysis=_analysis(
                sub.token.id, sub.morph_run.id, gap_segments, 13, analysis_id=gap_id
            ),
            segments=gap_segments,
        )
    # An unsegmented analysis never links a morpheme.
    unseg_id = new_id(IdPrefix.MORPH_ANALYSIS)
    unseg_segment = MorphSegment(
        id=new_id(IdPrefix.MORPH_SEGMENT),
        analysis_id=unseg_id,
        ordinal=0,
        start=0,
        end=len(SURFACE),
        surface=SURFACE,
        morpheme_id=stem.id,
        created_at=_at(30),
    )
    unseg_analysis = _analysis(
        sub.token.id,
        sub.morph_run.id,
        [unseg_segment],
        13,
        analysis_id=unseg_id,
        analysis_kind=AnalysisKind.UNSEGMENTED,
        abstention="insufficient_evidence",
    )
    with pytest.raises(SchemaViolation):
        attempt(unseg_analysis, [unseg_segment])

    # None of the failed attempts left a row behind.
    assert repo_backend.count(EntityType.MORPH_ANALYSIS) == 0
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 0


def test_span_representation_is_derived_from_the_token(repo_backend: Repository) -> None:
    """ADR-0017 §3: spans index the normalized surface when present, else the raw one."""
    sub = _substrate(repo_backend)
    stem = _morpheme(sub.morph_run.id, 10, "mabi")
    suffix = _morpheme(sub.morph_run.id, 11, "ku")
    with repo_backend.transaction():
        repo_backend.add_morpheme(stem)
        repo_backend.add_morpheme(suffix)
        # The substrate token is raw-only; this sibling token also carries a normalized
        # surface (identical string, so only the representation differs).
        normalized_token = make_token(
            sub.segment, sub.tok_run, surface=SURFACE, normalized_surface=SURFACE, ordinal=1
        )
        repo_backend.add_token(normalized_token)

    def pair(
        token_id: str, representation: SpanRepresentation, index: int
    ) -> tuple[MorphAnalysis, list[MorphSegment]]:
        analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
        segments = _segments_for(analysis_id, stem, suffix, None)
        analysis = _analysis(
            token_id,
            sub.morph_run.id,
            segments,
            index,
            analysis_id=analysis_id,
            span_representation=representation,
        )
        return analysis, segments

    # A normalized token is indexed through its normalized surface: a RAW analysis over
    # it is refused even when the two strings happen to agree.
    raw_analysis, raw_segments = pair(normalized_token.id, SpanRepresentation.RAW, 70)
    with pytest.raises(SchemaViolation), repo_backend.transaction():
        repo_backend.add_morph_analysis(raw_analysis, raw_segments)
    # The same token through its normalized surface is accepted.
    norm_analysis, norm_segments = pair(normalized_token.id, SpanRepresentation.NORMALIZED, 71)
    with repo_backend.transaction():
        repo_backend.add_morph_analysis(norm_analysis, norm_segments)
    assert repo_backend.count(EntityType.MORPH_ANALYSIS) == 1
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 3
    # A token without a normalized surface has nothing for a NORMALIZED analysis to index.
    raw_only_analysis, raw_only_segments = pair(sub.token.id, SpanRepresentation.NORMALIZED, 72)
    with pytest.raises(SchemaViolation), repo_backend.transaction():
        repo_backend.add_morph_analysis(raw_only_analysis, raw_only_segments)
    assert repo_backend.count(EntityType.MORPH_ANALYSIS) == 1
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 3


def test_failed_morph_analysis_insert_leaves_zero_rows(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    sub = world.substrate
    # A second analysis with the first one's natural key (token, run, signature).
    duplicate_id = new_id(IdPrefix.MORPH_ANALYSIS)
    duplicate_segments = _segments_for(duplicate_id, world.morphemes[0], world.morphemes[1], None)
    duplicate = _analysis(
        sub.token.id, sub.morph_run.id, duplicate_segments, 50, analysis_id=duplicate_id
    )

    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_morph_analysis(
            duplicate,
            duplicate_segments,
            [_assignment(duplicate_segments[0].id, world.features[0].id, 51)],
        )

    # The failed write left nothing behind: no analysis, no segments, no assignments, no registry.
    assert repo_backend.entity_type_of(duplicate_id) is None
    assert repo_backend.get_morph_analysis(world.analysis.id) == world.analysis
    assert repo_backend.count(EntityType.MORPH_ANALYSIS) == 1
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 3
    assert repo_backend.list_morph_segments(duplicate_id) == []
    assert repo_backend.list_segment_features(duplicate_segments[0].id) == []
    assert repo_backend.list_segment_features(world.segments[0].id) == world.assignments


def test_rollback_discards_morphology_writes(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    stem = _morpheme(sub.morph_run.id, 10, "mabi")
    analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
    segments = [*_stem_and_zero(analysis_id, stem), _suffix_segment(analysis_id, stem, None)]
    analysis = _analysis(sub.token.id, sub.morph_run.id, segments, 13, analysis_id=analysis_id)

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom), repo_backend.transaction():
        repo_backend.add_morpheme(stem)
        repo_backend.add_morph_analysis(analysis, segments)
        assert repo_backend.get_morph_analysis(analysis.id) == analysis
        raise _Boom

    assert repo_backend.entity_type_of(stem.id) is None
    assert repo_backend.entity_type_of(analysis.id) is None
    assert repo_backend.entity_type_of(segments[0].id) is None
    assert repo_backend.count(EntityType.MORPHEME) == 0
    assert repo_backend.count(EntityType.MORPH_ANALYSIS) == 0
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 0
    assert repo_backend.list_morph_segments(analysis.id) == []


def test_set_morph_analysis_status_is_atomic_and_returned(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    breakdown = ScoreBreakdown(
        policy_version="morph-v1",
        overall=0.5,
        components={"igt_support": 1.0},
        penalties={},
        independence_groups=["igt"],
    )

    with repo_backend.transaction():
        analysis = repo_backend.set_morph_analysis_status(
            world.analysis.id, LifecycleStatus.SUPPORTED, breakdown
        )
        assert analysis.status is LifecycleStatus.SUPPORTED
        assert analysis.score_breakdown == breakdown
        assert repo_backend.get_morph_analysis(world.analysis.id) == analysis
    assert repo_backend.get_morph_analysis(world.analysis.id) == analysis

    with pytest.raises(NotFound), repo_backend.transaction():
        repo_backend.set_morph_analysis_status(
            new_id(IdPrefix.MORPH_ANALYSIS), LifecycleStatus.REJECTED
        )


# --- duplicates, locks and copies --------------------------------------------------------------


def test_duplicate_morph_analysis_natural_key_refused(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    sub = world.substrate
    # Same (token, run) as the world analysis and the same segmentation payload, so the
    # same signature: only the fresh identifier differs.
    collision_id = new_id(IdPrefix.MORPH_ANALYSIS)
    collision_segments = _segments_for(collision_id, world.morphemes[0], world.morphemes[1], None)
    collision = _analysis(
        sub.token.id, sub.morph_run.id, collision_segments, 60, analysis_id=collision_id
    )
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_morph_analysis(collision, collision_segments)
    assert repo_backend.count(EntityType.MORPH_ANALYSIS) == 1
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 3


def test_duplicate_segment_identifiers_refused(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    stem = _morpheme(sub.morph_run.id, 10, "mabi")
    suffix = _morpheme(sub.morph_run.id, 11, "ku")
    with repo_backend.transaction():
        repo_backend.add_morpheme(stem)
        repo_backend.add_morpheme(suffix)
    analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
    analysis = _analysis(
        sub.token.id,
        sub.morph_run.id,
        _segments_for(analysis_id, stem, suffix, None),
        61,
        analysis_id=analysis_id,
    )
    # Duplicate identifier inside one batch: ordinals stay contiguous, so only the
    # identifier collision fires.
    dup_id_segments = _segments_for(analysis_id, stem, suffix, None)
    dup_id_segments[2] = dup_id_segments[2].model_copy(update={"id": dup_id_segments[0].id})
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_morph_analysis(analysis, dup_id_segments)
    # Reusing a committed segment of another analysis is caught by the ownership check first.
    world = _morph_world(repo_backend)
    recycled_id = new_id(IdPrefix.MORPH_ANALYSIS)
    with pytest.raises(SchemaViolation), repo_backend.transaction():
        repo_backend.add_morph_analysis(
            _analysis(
                world.substrate.token.id,
                world.substrate.morph_run.id,
                [world.segments[0]],
                62,
                analysis_id=recycled_id,
            ),
            [world.segments[0]],
        )
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 3


def test_duplicate_segment_feature_assignment_refused(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    stem = _morpheme(sub.morph_run.id, 10, "mabi")
    suffix = _morpheme(sub.morph_run.id, 11, "ku")
    feature = _feature(sub.morph_run.id, 9, "Pst")
    with repo_backend.transaction():
        repo_backend.add_morpheme(stem)
        repo_backend.add_morpheme(suffix)
        repo_backend.add_feature(feature)
    analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
    segments = _segments_for(analysis_id, stem, suffix, None)
    analysis = _analysis(sub.token.id, sub.morph_run.id, segments, 73, analysis_id=analysis_id)
    # The same (segment, feature) pair twice in one batch: the PostgreSQL composite
    # primary key would refuse it at flush, so both backends refuse it eagerly and
    # the whole write stays all-or-nothing.
    duplicated = [
        _assignment(segments[0].id, feature.id, 74),
        _assignment(segments[0].id, feature.id, 74),
    ]
    with pytest.raises(ImmutableViolation), repo_backend.transaction():
        repo_backend.add_morph_analysis(analysis, segments, duplicated)
    assert repo_backend.count(EntityType.MORPH_ANALYSIS) == 0
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 0


def test_non_contiguous_ordinals_are_schema_violations(repo_backend: Repository) -> None:
    sub = _substrate(repo_backend)
    stem = _morpheme(sub.morph_run.id, 10, "mabi")
    suffix = _morpheme(sub.morph_run.id, 11, "ku")
    with repo_backend.transaction():
        repo_backend.add_morpheme(stem)
        repo_backend.add_morpheme(suffix)
    gap_id = new_id(IdPrefix.MORPH_ANALYSIS)
    full = _segments_for(gap_id, stem, suffix, None)
    gapped = [full[0], full[2]]
    with pytest.raises(SchemaViolation), repo_backend.transaction():
        repo_backend.add_morph_analysis(
            _analysis(sub.token.id, sub.morph_run.id, gapped, 63, analysis_id=gap_id), gapped
        )
    assert repo_backend.count(EntityType.MORPH_SEGMENT) == 0


def test_locked_reads_require_transaction_and_existence(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    with pytest.raises(RuntimeError, match="write outside transaction"):
        repo_backend.get_morpheme_for_update(world.morphemes[0].id)
    with pytest.raises(RuntimeError, match="write outside transaction"):
        repo_backend.get_morph_analysis_for_update(world.analysis.id)
    with pytest.raises(NotFound), repo_backend.transaction():
        repo_backend.get_morpheme_for_update(new_id(IdPrefix.MORPHEME))
    with pytest.raises(NotFound), repo_backend.transaction():
        repo_backend.get_morph_analysis_for_update(new_id(IdPrefix.MORPH_ANALYSIS))
    with repo_backend.transaction():
        assert repo_backend.get_morpheme_for_update(world.morphemes[0].id) == world.morphemes[0]
        assert repo_backend.get_morph_analysis_for_update(world.analysis.id) == world.analysis


def test_morphology_returns_defensive_copies(repo_backend: Repository) -> None:
    world = _morph_world(repo_backend)
    breakdown = ScoreBreakdown(
        policy_version="morph-v1",
        overall=0.5,
        components={"igt_support": 1.0},
        penalties={},
        independence_groups=["igt"],
    )
    with repo_backend.transaction():
        stored = repo_backend.set_morpheme_status(
            world.morphemes[0].id, LifecycleStatus.SUPPORTED, breakdown
        )
    # `stored` is the caller's own object; only the stored and listed copies must stay clean.
    stored.glosses["injected"] = ["leak"]
    listed = repo_backend.list_morphemes_for_run(world.substrate.morph_run.id)
    listed[0].glosses["injected"] = ["leak"]

    assert repo_backend.get_morpheme(world.morphemes[0].id).glosses == {"por": ["mabi"]}
    assert repo_backend.get_morpheme(world.morphemes[0].id).score_breakdown == breakdown
    assert repo_backend.list_morphemes_for_run(world.substrate.morph_run.id)[0].glosses == {
        "por": ["mabi"]
    }
    assert repo_backend.get_morpheme(world.morphemes[0].id).status is LifecycleStatus.SUPPORTED
