"""M3 alignment table guards exercised with direct SQL, bypassing repositories (ADR-0011 §8).

DEFERRABLE constraint triggers on the parent, on members and on token edges verify at commit:
the producing-run stage; the ordered side-descriptor selection contract of M3-PLAN §5.4
(pinned succeeded normalization/tokenization runs per side, roles source then target,
registered sources, nonempty distinct languages); group completeness; contiguous zero-based
membership; membership in the selected normalization run and side language; token endpoint
membership in the group sides and in the selected tokenization runs. Group membership is
immutable once published: membership may be assembled anywhere within the creating top-level
transaction — including inside released savepoints — but a member INSERT in a later
transaction is rejected even when the extension would otherwise validate. Missing or
malformed selection metadata fails closed. Immediate CHECK constraints reject non-finite
scores and invalid enum combinations. Test data contains only synthetic identifiers and
placeholder text.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from langpipe.domain.enums import EntityType
from langpipe.domain.ids import IdPrefix, new_id

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CHECK_VIOLATION = "23514"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _registry(conn: Connection, entity_type: EntityType, prefix: IdPrefix) -> str:
    object_id = new_id(prefix)
    conn.execute(
        text(
            "INSERT INTO object_registry (id, entity_type, created_at) "
            "VALUES (:id, :entity_type, :now)"
        ),
        {"id": object_id, "entity_type": entity_type.value, "now": NOW},
    )
    return object_id


def _run(conn: Connection, stage: str, config: dict[str, object] | None = None) -> str:
    run_id = _registry(conn, EntityType.PROCESSING_RUN, IdPrefix.RUN)
    conn.execute(
        text(
            "INSERT INTO processing_run (id, stage, tool_name, tool_version, config, "
            "config_hash, code_revision, run_key, random_seed, status, started_at, "
            "finished_at, error_type, error_message) VALUES (:id, :stage, 'test-tool', "
            "'0.0.0', CAST(:config AS jsonb), :hash, 'rev-test', :hash, NULL, 'succeeded', "
            ":now, :now, NULL, NULL)"
        ),
        {
            "id": run_id,
            "stage": stage,
            "config": json.dumps(config or {}),
            "hash": _hash(run_id),
            "now": NOW,
        },
    )
    return run_id


def _sides_config(
    source_id: str,
    src_norm_run: str,
    tgt_norm_run: str,
    *,
    src_language: str = "mzr",
    tgt_language: str = "por",
    src_tok_run: str | None = None,
    tgt_tok_run: str | None = None,
) -> dict[str, object]:
    """Ordered side descriptors exactly as M3-PLAN §5.4 records them in the run config."""
    return {
        "sides": [
            {
                "role": "source",
                "source_id": source_id,
                "language": src_language,
                "normalization_run_id": src_norm_run,
                "tokenization_run_id": src_tok_run,
            },
            {
                "role": "target",
                "source_id": source_id,
                "language": tgt_language,
                "normalization_run_id": tgt_norm_run,
                "tokenization_run_id": tgt_tok_run,
            },
        ]
    }


def _policy(conn: Connection) -> str:
    policy_id = new_id(IdPrefix.POLICY)
    conn.execute(
        text(
            "INSERT INTO source_policy (id, mode, access_class, authority, allow, deny, "
            "restrictions, policy_version, created_at) VALUES (:id, 'direct', 'public', "
            "'test-authority', '{}'::text[], '{}'::text[], '{}'::jsonb, 1, :now)"
        ),
        {"id": policy_id, "now": NOW},
    )
    return policy_id


def _source(conn: Connection, run_id: str, policy_id: str) -> str:
    source_id = _registry(conn, EntityType.SOURCE, IdPrefix.SOURCE)
    conn.execute(
        text(
            "INSERT INTO source (id, key, title, source_type, languages, provenance, "
            "policy_id, acquired_at, status, domains, registers, manifest_sha256, "
            "registration_run_id, created_at, updated_at) VALUES (:id, :key, 'Synthetic', "
            "'other', '{mzr,por}'::text[], '{}'::jsonb, :policy_id, :now, 'registered', "
            "'{}'::text[], '{}'::text[], :hash, :run_id, :now, :now)"
        ),
        {
            "id": source_id,
            "key": f"synthetic-{source_id[-8:].lower()}",
            "policy_id": policy_id,
            "run_id": run_id,
            "hash": _hash(source_id),
            "now": NOW,
        },
    )
    return source_id


def _source_object(conn: Connection, source_id: str, run_id: str) -> str:
    object_id = _registry(conn, EntityType.SOURCE_OBJECT, IdPrefix.SOURCE_OBJECT)
    conn.execute(
        text(
            "INSERT INTO source_object (id, source_id, original_path, origin_uri, sha256, "
            "size_bytes, media_type, access_class, registration_run_id, created_at) "
            "VALUES (:id, :source_id, 'synthetic.txt', 'file:///synthetic.txt', :hash, 3, "
            "'text/plain', 'public', :run_id, :now)"
        ),
        {
            "id": object_id,
            "source_id": source_id,
            "hash": _hash(object_id),
            "run_id": run_id,
            "now": NOW,
        },
    )
    return object_id


def _segment(
    conn: Connection,
    source_id: str,
    source_object_id: str,
    run_id: str,
    *,
    language: str,
    ordinal: int = 0,
) -> str:
    segment_id = _registry(conn, EntityType.SEGMENT, IdPrefix.SEGMENT)
    conn.execute(
        text(
            "INSERT INTO segment (id, source_id, source_object_id, run_id, ordinal, language, "
            "locator, raw_text, normalized_text, normalization_profile, status, created_at) "
            "VALUES (:id, :source_id, :source_object_id, :run_id, :ordinal, :language, "
            "'{}'::jsonb, 'synthetic', NULL, NULL, 'ok', :now)"
        ),
        {
            "id": segment_id,
            "source_id": source_id,
            "source_object_id": source_object_id,
            "run_id": run_id,
            "ordinal": ordinal,
            "language": language,
            "now": NOW,
        },
    )
    return segment_id


def _token(conn: Connection, segment_id: str, run_id: str, *, ordinal: int = 0) -> str:
    token_id = _registry(conn, EntityType.TOKEN_OCCURRENCE, IdPrefix.TOKEN)
    conn.execute(
        text(
            "INSERT INTO token_occurrence (id, segment_id, run_id, ordinal, raw_surface, "
            "normalized_surface, raw_start, raw_end, norm_start, norm_end, tokenizer, "
            "form_id, created_at) VALUES (:id, :segment_id, :run_id, :ordinal, 'synthetic', "
            "NULL, NULL, NULL, NULL, NULL, 'test-tokenizer', NULL, :now)"
        ),
        {
            "id": token_id,
            "segment_id": segment_id,
            "run_id": run_id,
            "ordinal": ordinal,
            "now": NOW,
        },
    )
    return token_id


def _alignment(
    conn: Connection,
    run_id: str,
    *,
    status: str = "structural",
    mode: str = "canonical",
    score_sql: str = "NULL",
) -> str:
    alignment_id = _registry(conn, EntityType.SEGMENT_ALIGNMENT, IdPrefix.SEGMENT_ALIGNMENT)
    conn.execute(
        text(
            "INSERT INTO segment_alignment (id, method, mode, status, score, raw_scores, "
            "group_key, run_id, authorization_basis_id, supersedes_id, created_at) "
            f"VALUES (:id, 'canonical_locator@0.1.0', :mode, :status, {score_sql}, "
            "'{}'::jsonb, :group_key, :run_id, NULL, NULL, :now)"
        ),
        {
            "id": alignment_id,
            "mode": mode,
            "status": status,
            "group_key": _hash(alignment_id),
            "run_id": run_id,
            "now": NOW,
        },
    )
    return alignment_id


def _member(conn: Connection, alignment_id: str, side: str, position: int, segment_id: str) -> None:
    conn.execute(
        text(
            "INSERT INTO segment_alignment_member (alignment_id, side, position, segment_id) "
            "VALUES (:alignment_id, :side, :position, :segment_id)"
        ),
        {
            "alignment_id": alignment_id,
            "side": side,
            "position": position,
            "segment_id": segment_id,
        },
    )


def _edge(
    conn: Connection,
    run_id: str,
    alignment_id: str,
    source_token_id: str,
    target_token_id: str,
    *,
    direction: str = "symmetrized",
    symmetrization: str = "intersection",
    score_sql: str = "NULL",
) -> str:
    edge_id = _registry(conn, EntityType.TOKEN_ALIGNMENT_EDGE, IdPrefix.TOKEN_ALIGNMENT)
    conn.execute(
        text(
            "INSERT INTO token_alignment_edge (id, segment_alignment_id, source_token_id, "
            "target_token_id, direction, algorithm, score, raw_scores, symmetrization, "
            f"run_id, created_at) VALUES (:id, :alignment_id, :source_token_id, "
            f":target_token_id, :direction, 'eflomal@0.1.0', {score_sql}, '{{}}'::jsonb, "
            ":symmetrization, :run_id, :now)"
        ),
        {
            "id": edge_id,
            "alignment_id": alignment_id,
            "source_token_id": source_token_id,
            "target_token_id": target_token_id,
            "direction": direction,
            "symmetrization": symmetrization,
            "run_id": run_id,
            "now": NOW,
        },
    )
    return edge_id


def _seed_segment_world(conn: Connection) -> dict[str, str]:
    """One registered bilingual source plus one succeeded normalization run and mzr/por
    segment per side; callers add the alignment run, alignment row and members."""
    registration_run = _run(conn, "source_registration")
    src_norm_run = _run(conn, "normalization")
    tgt_norm_run = _run(conn, "normalization")
    policy_id = _policy(conn)
    source_id = _source(conn, registration_run, policy_id)
    source_object_id = _source_object(conn, source_id, registration_run)
    src_segment = _segment(conn, source_id, source_object_id, src_norm_run, language="mzr")
    tgt_segment = _segment(conn, source_id, source_object_id, tgt_norm_run, language="por")
    return {
        "registration_run": registration_run,
        "src_norm_run": src_norm_run,
        "tgt_norm_run": tgt_norm_run,
        "source": source_id,
        "source_object": source_object_id,
        "src_segment": src_segment,
        "tgt_segment": tgt_segment,
    }


def _align_run(conn: Connection, world: dict[str, str], **config: object) -> str:
    """A segment_alignment-stage run whose config pins the world's selected runs."""
    if not config:
        config = _sides_config(world["source"], world["src_norm_run"], world["tgt_norm_run"])
    return _run(conn, "segment_alignment", config)


def seed_valid_group(engine: Engine) -> dict[str, str]:
    """Commit one valid mzr:por 1:1 group with selected runs, a token per side and one
    symmetrized edge.

    Shared with the migration and append-only test modules: it is the smallest committed
    state that exercises every deferred M3 guard with genuine M3 inputs — segments from
    succeeded normalization runs, one tokenization run per side, and explicit §5.4 selection
    metadata in both the segment_alignment and token_alignment run configs.
    """
    with engine.begin() as conn:
        registration_run = _run(conn, "source_registration")
        policy_id = _policy(conn)
        source_id = _source(conn, registration_run, policy_id)
        source_object_id = _source_object(conn, source_id, registration_run)
        src_norm_run = _run(conn, "normalization")
        tgt_norm_run = _run(conn, "normalization")
        src_tok_run = _run(conn, "tokenization")
        tgt_tok_run = _run(conn, "tokenization")
        align_run = _run(
            conn,
            "segment_alignment",
            _sides_config(source_id, src_norm_run, tgt_norm_run),
        )
        token_run = _run(
            conn,
            "token_alignment",
            _sides_config(
                source_id,
                src_norm_run,
                tgt_norm_run,
                src_tok_run=src_tok_run,
                tgt_tok_run=tgt_tok_run,
            ),
        )
        src_segment = _segment(conn, source_id, source_object_id, src_norm_run, language="mzr")
        tgt_segment = _segment(conn, source_id, source_object_id, tgt_norm_run, language="por")
        alignment_id = _alignment(conn, align_run)
        _member(conn, alignment_id, "source", 0, src_segment)
        _member(conn, alignment_id, "target", 0, tgt_segment)
        src_token = _token(conn, src_segment, src_tok_run)
        tgt_token = _token(conn, tgt_segment, tgt_tok_run)
        edge_id = _edge(conn, token_run, alignment_id, src_token, tgt_token)
    return {
        "registration_run": registration_run,
        "src_norm_run": src_norm_run,
        "tgt_norm_run": tgt_norm_run,
        "src_tok_run": src_tok_run,
        "tgt_tok_run": tgt_tok_run,
        "align_run": align_run,
        "token_run": token_run,
        "source": source_id,
        "source_object": source_object_id,
        "src_segment": src_segment,
        "tgt_segment": tgt_segment,
        "alignment": alignment_id,
        "src_token": src_token,
        "tgt_token": tgt_token,
        "edge": edge_id,
    }


def _committed_group(engine: Engine) -> dict[str, str]:
    """A committed 1:1 group without tokens/edges: Stage 4 evidence for Stage 5 tests."""
    with engine.begin() as conn:
        world = _seed_segment_world(conn)
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        _member(conn, alignment_id, "source", 0, world["src_segment"])
        _member(conn, alignment_id, "target", 0, world["tgt_segment"])
    return {**world, "align_run": align_run, "alignment": alignment_id}


def _member_rows(engine: Engine, alignment_id: str) -> list[tuple[str, int]]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT side, position FROM segment_alignment_member "
                    "WHERE alignment_id = :id ORDER BY side, position"
                ),
                {"id": alignment_id},
            ).all()
        )


def _expect_violation(
    engine: Engine,
    build: Callable[[Connection], None],
    *,
    message_contains: str | None = None,
    sqlstate: str = CHECK_VIOLATION,
) -> None:
    # Deferred constraint triggers fail the COMMIT inside engine.begin(); immediate CHECK
    # constraints fail the INSERT/UPDATE. SQLAlchemy wraps both as DBAPIError. Matching the
    # guard message proves the intended guard rejected the row, not an unrelated FK/unique.
    with pytest.raises(DBAPIError) as excinfo, engine.begin() as conn:
        build(conn)
    orig = excinfo.value.orig if excinfo.value.orig is not None else excinfo.value
    assert getattr(orig, "sqlstate", None) == sqlstate, repr(excinfo.value)
    if message_contains is not None:
        assert message_contains in str(orig), str(orig)


def test_valid_group_and_edges_commit(migrated_engine: Engine) -> None:
    ids = seed_valid_group(migrated_engine)
    assert _member_rows(migrated_engine, ids["alignment"]) == [("source", 0), ("target", 0)]
    with migrated_engine.connect() as conn:
        edges = conn.execute(text("SELECT count(*) FROM token_alignment_edge")).scalar_one()
    assert edges == 1


def test_nm_group_commits_in_one_transaction(migrated_engine: Engine) -> None:
    def build(conn: Connection) -> str:
        world = _seed_segment_world(conn)
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        for position in (0, 1):
            segment = _segment(
                conn,
                world["source"],
                world["source_object"],
                world["src_norm_run"],
                language="mzr",
                ordinal=position + 10,
            )
            _member(conn, alignment_id, "source", position, segment)
        for position in (0, 1, 2):
            segment = _segment(
                conn,
                world["source"],
                world["source_object"],
                world["tgt_norm_run"],
                language="por",
                ordinal=position + 20,
            )
            _member(conn, alignment_id, "target", position, segment)
        return alignment_id

    with migrated_engine.begin() as conn:
        alignment_id = build(conn)
    assert _member_rows(migrated_engine, alignment_id) == [
        ("source", 0),
        ("source", 1),
        ("target", 0),
        ("target", 1),
        ("target", 2),
    ]


def test_group_inside_released_savepoint_commits(migrated_engine: Engine) -> None:
    # G4_r2 P1: a complete valid group created inside a savepoint that is then RELEASEd must
    # commit. Membership ownership is the creating top-level transaction, so savepoint
    # boundaries must not matter — only later transactions are foreign.
    with migrated_engine.begin() as conn:
        nested = conn.begin_nested()
        world = _seed_segment_world(conn)
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        _member(conn, alignment_id, "source", 0, world["src_segment"])
        _member(conn, alignment_id, "target", 0, world["tgt_segment"])
        nested.commit()  # RELEASE SAVEPOINT
    assert _member_rows(migrated_engine, alignment_id) == [("source", 0), ("target", 0)]


def test_savepoint_parent_then_outer_members_commits(migrated_engine: Engine) -> None:
    # The parent (with its registry and producing run) is created inside a released
    # savepoint; the members join afterwards in the outer transaction.
    with migrated_engine.begin() as conn:
        world = _seed_segment_world(conn)
        nested = conn.begin_nested()
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        nested.commit()
        _member(conn, alignment_id, "source", 0, world["src_segment"])
        _member(conn, alignment_id, "target", 0, world["tgt_segment"])
    assert _member_rows(migrated_engine, alignment_id) == [("source", 0), ("target", 0)]


def test_top_level_parent_with_members_in_savepoints_commits(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        world = _seed_segment_world(conn)
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        with conn.begin_nested():
            _member(conn, alignment_id, "source", 0, world["src_segment"])
        with conn.begin_nested():
            _member(conn, alignment_id, "target", 0, world["tgt_segment"])
    assert _member_rows(migrated_engine, alignment_id) == [("source", 0), ("target", 0)]


@pytest.mark.parametrize(
    ("missing_side", "message"),
    [
        ("both", "at least one source-side member"),
        ("source", "at least one source-side member"),
        ("target", "at least one target-side member"),
    ],
)
def test_empty_group_commit_rejected(
    migrated_engine: Engine, missing_side: str, message: str
) -> None:
    def build(conn: Connection) -> None:
        world = _seed_segment_world(conn)
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        if missing_side not in ("source", "both"):
            _member(conn, alignment_id, "source", 0, world["src_segment"])
        if missing_side not in ("target", "both"):
            _member(conn, alignment_id, "target", 0, world["tgt_segment"])

    _expect_violation(migrated_engine, build, message_contains=message)


@pytest.mark.parametrize(
    ("side", "positions"),
    [("source", (0, 2)), ("source", (1,)), ("target", (0, 2)), ("target", (1,))],
)
def test_noncontiguous_positions_rejected(
    migrated_engine: Engine, side: str, positions: tuple[int, ...]
) -> None:
    def build(conn: Connection) -> None:
        world = _seed_segment_world(conn)
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        # The opposite side stays contiguous; `side` gets exactly `positions`.
        prefix = "src" if side == "source" else "tgt"
        other_prefix = "tgt" if side == "source" else "src"
        other_side = "target" if side == "source" else "source"
        _member(conn, alignment_id, other_side, 0, world[f"{other_prefix}_segment"])
        for position in positions:
            # Ordinal stays unique per segment run (the world already used 0); the member
            # position under test is what must be noncontiguous.
            segment = _segment(
                conn,
                world["source"],
                world["source_object"],
                world[f"{prefix}_norm_run"],
                language="mzr" if side == "source" else "por",
                ordinal=position + 10,
            )
            _member(conn, alignment_id, side, position, segment)

    _expect_violation(
        migrated_engine,
        build,
        message_contains=f"{side}-side member positions must be contiguous and zero-based",
    )


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("same_language_both_sides", "alignment sides must have distinct languages"),
        (
            "mixed_language_in_side",
            "source-side members must match the selected normalization run",
        ),
        ("mixed_run_in_side", "source-side members must match the selected normalization run"),
        ("wrong_stage", "segment_alignment-stage producing run"),
    ],
)
def test_wrong_language_or_run_rejected(
    migrated_engine: Engine, scenario: str, message: str
) -> None:
    def build(conn: Connection) -> None:
        world = _seed_segment_world(conn)
        if scenario == "same_language_both_sides":
            # Both side descriptors declare mzr and both member segments match, so the
            # rejection must come from the distinct-language rule, not membership.
            config = _sides_config(
                world["source"],
                world["src_norm_run"],
                world["tgt_norm_run"],
                tgt_language="mzr",
            )
            align_run = _align_run(conn, world, **config)
            alignment_id = _alignment(conn, align_run)
            tgt = _segment(
                conn,
                world["source"],
                world["source_object"],
                world["tgt_norm_run"],
                language="mzr",
                ordinal=5,
            )
            _member(conn, alignment_id, "source", 0, world["src_segment"])
            _member(conn, alignment_id, "target", 0, tgt)
            return
        if scenario == "wrong_stage":
            # The producing run is not a segment_alignment run.
            wrong_stage_run = _run(
                conn,
                "extraction",
                _sides_config(world["source"], world["src_norm_run"], world["tgt_norm_run"]),
            )
            alignment_id = _alignment(conn, wrong_stage_run)
            _member(conn, alignment_id, "source", 0, world["src_segment"])
            _member(conn, alignment_id, "target", 0, world["tgt_segment"])
            return
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        if scenario == "mixed_language_in_side":
            extra = _segment(
                conn,
                world["source"],
                world["source_object"],
                world["src_norm_run"],
                language="por",
                ordinal=1,
            )
            _member(conn, alignment_id, "source", 0, world["src_segment"])
            _member(conn, alignment_id, "source", 1, extra)
            _member(conn, alignment_id, "target", 0, world["tgt_segment"])
        elif scenario == "mixed_run_in_side":
            other_norm = _run(conn, "normalization")
            extra = _segment(
                conn,
                world["source"],
                world["source_object"],
                other_norm,
                language="mzr",
                ordinal=1,
            )
            _member(conn, alignment_id, "source", 0, world["src_segment"])
            _member(conn, alignment_id, "source", 1, extra)
            _member(conn, alignment_id, "target", 0, world["tgt_segment"])

    _expect_violation(migrated_engine, build, message_contains=message)


def test_unselected_normalization_generation_rejected(migrated_engine: Engine) -> None:
    # Homogeneous generations are not enough: the members' run must be the pinned one.
    def build(conn: Connection) -> None:
        world = _seed_segment_world(conn)
        other_norm = _run(conn, "normalization")
        config = _sides_config(world["source"], other_norm, world["tgt_norm_run"])
        align_run = _run(conn, "segment_alignment", config)
        alignment_id = _alignment(conn, align_run)
        _member(conn, alignment_id, "source", 0, world["src_segment"])
        _member(conn, alignment_id, "target", 0, world["tgt_segment"])

    _expect_violation(
        migrated_engine,
        build,
        message_contains=("source-side members must match the selected normalization run"),
    )


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        (
            "raw_extraction_segments",
            "source-side members must match the selected normalization run",
        ),
        (
            "extraction_run_pinned_as_normalization",
            "source side normalization_run_id must be a succeeded normalization-stage run",
        ),
    ],
)
def test_extraction_stage_segments_rejected(
    migrated_engine: Engine, scenario: str, message: str
) -> None:
    def build(conn: Connection) -> None:
        world = _seed_segment_world(conn)
        if scenario == "extraction_run_pinned_as_normalization":
            extraction_run = _run(conn, "extraction")
            config = _sides_config(world["source"], extraction_run, world["tgt_norm_run"])
            align_run = _run(conn, "segment_alignment", config)
            member_segment = _segment(
                conn, world["source"], world["source_object"], extraction_run, language="mzr"
            )
        else:  # raw_extraction_segments: pinned run is a real normalization run.
            align_run = _align_run(conn, world)
            extraction_run = _run(conn, "extraction")
            member_segment = _segment(
                conn, world["source"], world["source_object"], extraction_run, language="mzr"
            )
        alignment_id = _alignment(conn, align_run)
        _member(conn, alignment_id, "source", 0, member_segment)
        _member(conn, alignment_id, "target", 0, world["tgt_segment"])

    _expect_violation(migrated_engine, build, message_contains=message)


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        (
            "group_run_empty_config",
            "alignment run config must record ordered source and target side descriptors",
        ),
        ("group_run_sides_unordered", "side descriptors must be ordered source then target"),
        (
            "group_run_normalization_pin_missing",
            "source side normalization_run_id must be a succeeded normalization-stage run",
        ),
        (
            "edge_run_empty_config",
            "alignment run config must record ordered source and target side descriptors",
        ),
        (
            "edge_run_tokenization_pin_missing",
            "tokenization_run_id must be a succeeded tokenization-stage run",
        ),
    ],
)
def test_missing_selection_metadata_rejected(
    migrated_engine: Engine, scenario: str, message: str
) -> None:
    def build_group(conn: Connection) -> str:
        world = _seed_segment_world(conn)
        if scenario == "group_run_empty_config":
            align_run = _run(conn, "segment_alignment")
        elif scenario == "group_run_sides_unordered":
            config = _sides_config(world["source"], world["src_norm_run"], world["tgt_norm_run"])
            align_run = _run(conn, "segment_alignment", {"sides": list(reversed(config["sides"]))})
        else:  # group_run_normalization_pin_missing
            config = _sides_config(world["source"], world["src_norm_run"], world["tgt_norm_run"])
            config["sides"][0]["normalization_run_id"] = None  # type: ignore[index]
            align_run = _run(conn, "segment_alignment", config)
        alignment_id = _alignment(conn, align_run)
        _member(conn, alignment_id, "source", 0, world["src_segment"])
        _member(conn, alignment_id, "target", 0, world["tgt_segment"])
        return alignment_id

    if scenario.startswith("edge_"):
        base = _committed_group(migrated_engine)

        def build(conn: Connection) -> None:
            src_tok_run = _run(conn, "tokenization")
            tgt_tok_run = _run(conn, "tokenization")
            if scenario == "edge_run_empty_config":
                token_run = _run(conn, "token_alignment")
            else:  # edge_run_tokenization_pin_missing
                token_run = _run(
                    conn,
                    "token_alignment",
                    _sides_config(
                        base["source"],
                        base["src_norm_run"],
                        base["tgt_norm_run"],
                        src_tok_run=src_tok_run,
                    ),
                )
            src_token = _token(conn, base["src_segment"], src_tok_run)
            tgt_token = _token(conn, base["tgt_segment"], tgt_tok_run)
            _edge(conn, token_run, base["alignment"], src_token, tgt_token)

        _expect_violation(migrated_engine, build, message_contains=message)
    else:
        _expect_violation(migrated_engine, build_group, message_contains=message)


@pytest.mark.parametrize("side", ["source", "target"])
def test_edge_unselected_tokenization_generation_rejected(
    migrated_engine: Engine, side: str
) -> None:
    base = _committed_group(migrated_engine)

    def build(conn: Connection) -> None:
        src_tok_run = _run(conn, "tokenization")
        tgt_tok_run = _run(conn, "tokenization")
        wrong_generation = _run(conn, "tokenization")
        token_run = _run(
            conn,
            "token_alignment",
            _sides_config(
                base["source"],
                base["src_norm_run"],
                base["tgt_norm_run"],
                src_tok_run=src_tok_run,
                tgt_tok_run=tgt_tok_run,
            ),
        )
        src_token = _token(
            conn,
            base["src_segment"],
            wrong_generation if side == "source" else src_tok_run,
        )
        tgt_token = _token(
            conn,
            base["tgt_segment"],
            wrong_generation if side == "target" else tgt_tok_run,
        )
        _edge(conn, token_run, base["alignment"], src_token, tgt_token)

    _expect_violation(
        migrated_engine,
        build,
        message_contains=(f"{side} token must belong to the selected {side} tokenization run"),
    )


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("source_token_outside_group", "source token does not belong to the group source side"),
        ("swapped_endpoint", "source token does not belong to the group source side"),
        (
            "wrong_stage",
            "token_alignment_edge requires a token_alignment-stage producing run",
        ),
    ],
)
def test_edge_wrong_group_endpoint_rejected(
    migrated_engine: Engine, scenario: str, message: str
) -> None:
    def build(conn: Connection) -> None:
        world = _seed_segment_world(conn)
        align_run = _align_run(conn, world)
        alignment_id = _alignment(conn, align_run)
        _member(conn, alignment_id, "source", 0, world["src_segment"])
        _member(conn, alignment_id, "target", 0, world["tgt_segment"])
        src_tok_run = _run(conn, "tokenization")
        tgt_tok_run = _run(conn, "tokenization")
        token_run = _run(
            conn,
            "token_alignment",
            _sides_config(
                world["source"],
                world["src_norm_run"],
                world["tgt_norm_run"],
                src_tok_run=src_tok_run,
                tgt_tok_run=tgt_tok_run,
            ),
        )
        src_token = _token(conn, world["src_segment"], src_tok_run)
        tgt_token = _token(conn, world["tgt_segment"], tgt_tok_run)
        if scenario == "source_token_outside_group":
            outside = _segment(
                conn,
                world["source"],
                world["source_object"],
                world["src_norm_run"],
                language="mzr",
                ordinal=7,
            )
            outside_token = _token(conn, outside, src_tok_run, ordinal=1)
            _edge(conn, token_run, alignment_id, outside_token, tgt_token)
        elif scenario == "swapped_endpoint":
            _edge(conn, token_run, alignment_id, tgt_token, tgt_token)
        else:  # wrong_stage: the producing run is not a token_alignment run.
            _edge(conn, align_run, alignment_id, src_token, tgt_token)

    _expect_violation(migrated_engine, build, message_contains=message)


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("gap_position", "source-side member positions must be contiguous and zero-based"),
        ("mixed_language", "source-side members must match the selected normalization run"),
        ("mixed_run", "source-side members must match the selected normalization run"),
        ("valid_extension", "published segment_alignment membership is immutable"),
    ],
)
def test_published_group_membership_expansion_rejected(
    migrated_engine: Engine, scenario: str, message: str
) -> None:
    # Regression for the member-INSERT hole: a committed group is published evidence whose
    # lineage/run outputs describe exactly its committed membership. Any later-transaction
    # member INSERT must fail — including one that would revalidate cleanly.
    ids = seed_valid_group(migrated_engine)

    def build(conn: Connection) -> None:
        segment_run = (
            _run(conn, "normalization") if scenario == "mixed_run" else ids["src_norm_run"]
        )
        segment = _segment(
            conn,
            ids["source"],
            ids["source_object"],
            segment_run,
            language="por" if scenario == "mixed_language" else "mzr",
            ordinal=30,
        )
        _member(conn, ids["alignment"], "source", 9 if scenario == "gap_position" else 1, segment)

    _expect_violation(migrated_engine, build, message_contains=message)
    # The rejected expansion left the published membership untouched.
    assert _member_rows(migrated_engine, ids["alignment"]) == [("source", 0), ("target", 0)]


@pytest.mark.parametrize(
    ("table", "insert"),
    [
        (
            "segment_alignment",
            "INSERT INTO segment_alignment (id, method, mode, status, score, raw_scores, "
            "group_key, run_id, authorization_basis_id, supersedes_id, created_at) "
            "VALUES (:id, 'canonical_locator@0.1.0', 'canonical', 'structural', "
            "CAST(:score AS double precision), '{}'::jsonb, :group_key, :run_id, NULL, NULL, "
            ":now)",
        ),
        (
            "token_alignment_edge",
            "INSERT INTO token_alignment_edge (id, segment_alignment_id, source_token_id, "
            "target_token_id, direction, algorithm, score, raw_scores, symmetrization, "
            "run_id, created_at) VALUES (:id, :alignment_id, :source_token_id, "
            ":target_token_id, 'symmetrized', 'eflomal@0.1.0', "
            "CAST(:score AS double precision), '{}'::jsonb, 'intersection', :run_id, :now)",
        ),
    ],
)
@pytest.mark.parametrize("score", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_score_rejected(
    migrated_engine: Engine, table: str, insert: str, score: str
) -> None:
    def build(conn: Connection) -> None:
        if table == "segment_alignment":
            # The finite-score CHECK is immediate, so the row fails at INSERT; no members
            # are needed (the deferred group guard would never run).
            align_run = _run(conn, "segment_alignment")
            alignment_id = _registry(conn, EntityType.SEGMENT_ALIGNMENT, IdPrefix.SEGMENT_ALIGNMENT)
            params = {
                "id": alignment_id,
                "score": score,
                "group_key": _hash(alignment_id),
                "run_id": align_run,
                "now": NOW,
            }
        else:
            ids = seed_valid_group(migrated_engine)
            edge_id = _registry(conn, EntityType.TOKEN_ALIGNMENT_EDGE, IdPrefix.TOKEN_ALIGNMENT)
            params = {
                "id": edge_id,
                "alignment_id": ids["alignment"],
                "source_token_id": ids["src_token"],
                "target_token_id": ids["tgt_token"],
                "score": score,
                "run_id": _run(conn, "token_alignment"),
                "now": NOW,
            }
        conn.execute(text(insert), params)

    _expect_violation(migrated_engine, build)


def test_invalid_enum_combinations_rejected(migrated_engine: Engine) -> None:
    def approved_without_basis(conn: Connection) -> None:
        # The disposition CHECK is immediate: approved without basis/predecessor fails at
        # INSERT, before any deferred group validation could apply.
        align_run = _run(conn, "segment_alignment")
        _alignment(conn, align_run, status="approved")

    _expect_violation(migrated_engine, approved_without_basis)

    ids = seed_valid_group(migrated_engine)

    def symmetrized_without_set(conn: Connection) -> None:
        _edge(
            conn,
            ids["token_run"],
            ids["alignment"],
            ids["src_token"],
            ids["tgt_token"],
            direction="symmetrized",
            symmetrization="none",
        )

    _expect_violation(migrated_engine, symmetrized_without_set)

    def directional_with_set(conn: Connection) -> None:
        _edge(
            conn,
            ids["token_run"],
            ids["alignment"],
            ids["src_token"],
            ids["tgt_token"],
            direction="forward",
            symmetrization="intersection",
        )

    _expect_violation(migrated_engine, directional_with_set)
