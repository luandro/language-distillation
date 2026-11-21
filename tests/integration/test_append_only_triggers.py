"""Append-only and run-state enforcement in PostgreSQL (ADR-0009). Requires PostgreSQL.

Rows are inserted with raw SQL so the database rules are tested without any app code.
Test data contains only synthetic identifiers and placeholder text.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from langpipe.domain.enums import EntityType
from langpipe.domain.ids import IdPrefix, new_id
from tests.integration.test_alignment_constraints import seed_valid_group

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

NOW = datetime(2026, 1, 1, tzinfo=UTC)
RESTRICT_VIOLATION = "23001"
CHECK_VIOLATION = "23514"
ZERO_HASH = "0" * 64


def _registry(conn: Connection, entity: EntityType, prefix: IdPrefix) -> str:
    object_id = new_id(prefix)
    conn.execute(
        text(
            "INSERT INTO object_registry (id, entity_type, created_at) "
            "VALUES (:id, :entity_type, :now)"
        ),
        {"id": object_id, "entity_type": entity.value, "now": NOW},
    )
    return object_id


def _run(
    conn: Connection,
    status: str = "running",
    finished_at: datetime | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> str:
    run_id = _registry(conn, EntityType.PROCESSING_RUN, IdPrefix.RUN)
    conn.execute(
        text(
            "INSERT INTO processing_run (id, stage, tool_name, tool_version, config, "
            "config_hash, code_revision, run_key, random_seed, status, started_at, "
            "finished_at, error_type, error_message) VALUES (:id, 'source_registration', "
            "'test-tool', '0.0.0', '{}'::jsonb, :hash, 'rev-test', :hash, NULL, :status, "
            ":now, :finished_at, :error_type, :error_message)"
        ),
        {
            "id": run_id,
            "hash": ZERO_HASH,
            "status": status,
            "now": NOW,
            "finished_at": finished_at,
            "error_type": error_type,
            "error_message": error_message,
        },
    )
    return run_id


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
            "'other', '{mzr}'::text[], '{}'::jsonb, :policy_id, :now, 'registered', "
            "'{}'::text[], '{}'::text[], :hash, :run_id, :now, :now)"
        ),
        {
            "id": source_id,
            "key": f"synthetic-{source_id[-8:].lower()}",
            "policy_id": policy_id,
            "run_id": run_id,
            "hash": ZERO_HASH,
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
        {"id": object_id, "source_id": source_id, "hash": ZERO_HASH, "run_id": run_id, "now": NOW},
    )
    return object_id


def _segment(conn: Connection, source_id: str, source_object_id: str, run_id: str) -> str:
    segment_id = _registry(conn, EntityType.SEGMENT, IdPrefix.SEGMENT)
    conn.execute(
        text(
            "INSERT INTO segment (id, source_id, source_object_id, run_id, ordinal, language, "
            "locator, raw_text, normalized_text, normalization_profile, status, created_at) "
            "VALUES (:id, :source_id, :source_object_id, :run_id, 0, 'mzr', '{}'::jsonb, "
            "'synthetic', NULL, NULL, 'ok', :now)"
        ),
        {
            "id": segment_id,
            "source_id": source_id,
            "source_object_id": source_object_id,
            "run_id": run_id,
            "now": NOW,
        },
    )
    return segment_id


def _token(conn: Connection, segment_id: str, run_id: str, raw_start: int | None) -> str:
    token_id = _registry(conn, EntityType.TOKEN_OCCURRENCE, IdPrefix.TOKEN)
    conn.execute(
        text(
            "INSERT INTO token_occurrence (id, segment_id, run_id, ordinal, raw_surface, "
            "normalized_surface, raw_start, raw_end, norm_start, norm_end, tokenizer, "
            "form_id, created_at) VALUES (:id, :segment_id, :run_id, 0, 'synthetic', NULL, "
            ":raw_start, NULL, NULL, NULL, 'test-tokenizer', NULL, :now)"
        ),
        {
            "id": token_id,
            "segment_id": segment_id,
            "run_id": run_id,
            "raw_start": raw_start,
            "now": NOW,
        },
    )
    return token_id


def _seed_graph(engine: Engine) -> dict[str, str]:
    with engine.begin() as conn:
        run_id = _run(conn, status="succeeded", finished_at=NOW)
        policy_id = _policy(conn)
        source_id = _source(conn, run_id, policy_id)
        source_object_id = _source_object(conn, source_id, run_id)
        segment_id = _segment(conn, source_id, source_object_id, run_id)
        token_id = _token(conn, segment_id, run_id, raw_start=None)
    return {
        "run": run_id,
        "source": source_id,
        "source_object": source_object_id,
        "segment": segment_id,
        "token": token_id,
    }


def _expect_sqlstate(
    engine: Engine, statement: str, params: dict[str, object], sqlstate: str
) -> None:
    with pytest.raises(DBAPIError) as excinfo, engine.begin() as conn:
        conn.execute(text(statement), params)
    assert excinfo.value.orig is not None
    assert excinfo.value.orig.sqlstate == sqlstate


def test_source_object_update_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "UPDATE source_object SET size_bytes = 4 WHERE id = :id",
        {"id": ids["source_object"]},
        RESTRICT_VIOLATION,
    )


def test_raw_blob_update_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO raw_blob (sha256, size_bytes, storage_backend, stored_at, "
                "ingestion_run_id) VALUES (:hash, 3, 'local', :now, :run_id)"
            ),
            {"hash": ZERO_HASH, "now": NOW, "run_id": ids["run"]},
        )
    _expect_sqlstate(
        migrated_engine,
        "UPDATE raw_blob SET size_bytes = 4 WHERE sha256 = :hash",
        {"hash": ZERO_HASH},
        RESTRICT_VIOLATION,
    )


def test_token_occurrence_update_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "UPDATE token_occurrence SET raw_surface = 'changed' WHERE id = :id",
        {"id": ids["token"]},
        RESTRICT_VIOLATION,
    )


def test_member_update_delete_rejected(migrated_engine: Engine) -> None:
    ids = seed_valid_group(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "UPDATE segment_alignment_member SET position = 5 WHERE alignment_id = :id",
        {"id": ids["alignment"]},
        RESTRICT_VIOLATION,
    )
    _expect_sqlstate(
        migrated_engine,
        "DELETE FROM segment_alignment_member WHERE alignment_id = :id",
        {"id": ids["alignment"]},
        RESTRICT_VIOLATION,
    )


def test_segment_alignment_update_delete_rejected(migrated_engine: Engine) -> None:
    ids = seed_valid_group(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "UPDATE segment_alignment SET score = 0.5 WHERE id = :id",
        {"id": ids["alignment"]},
        RESTRICT_VIOLATION,
    )
    _expect_sqlstate(
        migrated_engine,
        "DELETE FROM segment_alignment WHERE id = :id",
        {"id": ids["alignment"]},
        RESTRICT_VIOLATION,
    )


def test_token_alignment_edge_update_delete_rejected(migrated_engine: Engine) -> None:
    ids = seed_valid_group(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "UPDATE token_alignment_edge SET score = 0.5 WHERE id = :id",
        {"id": ids["edge"]},
        RESTRICT_VIOLATION,
    )
    _expect_sqlstate(
        migrated_engine,
        "DELETE FROM token_alignment_edge WHERE id = :id",
        {"id": ids["edge"]},
        RESTRICT_VIOLATION,
    )


def test_segment_delete_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "DELETE FROM segment WHERE id = :id",
        {"id": ids["segment"]},
        RESTRICT_VIOLATION,
    )


def test_lineage_edge_update_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    with migrated_engine.begin() as conn:
        lineage_id = new_id(IdPrefix.LINEAGE)
        conn.execute(
            text(
                "INSERT INTO lineage_edge (id, from_id, to_id, kind, run_id, created_at) "
                "VALUES (:id, :from_id, :to_id, 'extracted_from', :run_id, :now)"
            ),
            {
                "id": lineage_id,
                "from_id": ids["segment"],
                "to_id": ids["source_object"],
                "run_id": ids["run"],
                "now": NOW,
            },
        )
    _expect_sqlstate(
        migrated_engine,
        "UPDATE lineage_edge SET kind = 'derived_from' WHERE id = :id",
        {"id": lineage_id},
        RESTRICT_VIOLATION,
    )


def test_source_title_update_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "UPDATE source SET title = 'Changed' WHERE id = :id",
        {"id": ids["source"]},
        RESTRICT_VIOLATION,
    )


def test_source_status_update_allowed(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(
            text("UPDATE source SET status = 'ingested', updated_at = :now WHERE id = :id"),
            {"now": datetime(2026, 2, 1, tzinfo=UTC), "id": ids["source"]},
        )
        status = conn.execute(
            text("SELECT status FROM source WHERE id = :id"), {"id": ids["source"]}
        ).scalar_one()
    assert status == "ingested"


def test_source_delete_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "DELETE FROM source WHERE id = :id",
        {"id": ids["source"]},
        RESTRICT_VIOLATION,
    )


def test_finished_run_update_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    _expect_sqlstate(
        migrated_engine,
        "UPDATE processing_run SET status = 'failed', error_type = 'x' WHERE id = :id",
        {"id": ids["run"]},
        RESTRICT_VIOLATION,
    )


def test_running_run_can_finish_once(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        run_id = _run(conn)
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE processing_run SET status = 'succeeded', finished_at = :now WHERE id = :id"
            ),
            {"now": NOW, "id": run_id},
        )
    _expect_sqlstate(
        migrated_engine,
        "UPDATE processing_run SET status = 'failed', finished_at = :now, error_type = 'x' "
        "WHERE id = :id",
        {"now": NOW, "id": run_id},
        RESTRICT_VIOLATION,
    )


def test_half_specified_token_offsets_rejected(migrated_engine: Engine) -> None:
    ids = _seed_graph(migrated_engine)
    with pytest.raises(IntegrityError) as excinfo, migrated_engine.begin() as conn:
        token_id = _registry(conn, EntityType.TOKEN_OCCURRENCE, IdPrefix.TOKEN)
        conn.execute(
            text(
                "INSERT INTO token_occurrence (id, segment_id, run_id, ordinal, raw_surface, "
                "normalized_surface, raw_start, raw_end, norm_start, norm_end, tokenizer, "
                "form_id, created_at) VALUES (:id, :segment_id, :run_id, 1, 'synthetic', NULL, "
                "4, NULL, NULL, NULL, 'test-tokenizer', NULL, :now)"
            ),
            {"id": token_id, "segment_id": ids["segment"], "run_id": ids["run"], "now": NOW},
        )
    assert excinfo.value.orig is not None
    assert excinfo.value.orig.sqlstate == CHECK_VIOLATION


@pytest.mark.parametrize(
    ("status", "finished", "error_type"),
    [
        ("succeeded", False, None),
        ("failed", True, None),
        ("failed", False, "synthetic_error"),
        ("running", True, None),
        ("succeeded", True, "synthetic_error"),
    ],
)
def test_terminal_run_requires_finished_at_and_valid_error_fields(
    migrated_engine: Engine, status: str, finished: bool, error_type: str | None
) -> None:
    with pytest.raises(IntegrityError) as excinfo, migrated_engine.begin() as conn:
        _run(
            conn,
            status=status,
            finished_at=NOW if finished else None,
            error_type=error_type,
        )
    assert excinfo.value.orig is not None
    assert excinfo.value.orig.sqlstate == CHECK_VIOLATION
