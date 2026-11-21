"""Migration round trip and ORM/migration metadata parity (ADR-0009). Requires PostgreSQL."""

from collections.abc import Callable

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from langpipe.domain.enums import AccessClass, ArtifactKind, RunStage
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.run import Artifact
from langpipe.storage.db.repository import PostgresRepository
from langpipe.storage.db.tables import Base
from tests.contract.builders import NOW, SHA_A, make_run
from tests.fixtures.db import alembic_config
from tests.integration.test_alignment_constraints import seed_valid_group

pytestmark = pytest.mark.integration


def _public_tables(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        return {row[0] for row in rows}


def test_upgrade_downgrade_upgrade(migrated_engine: Engine, clean_db: None, pg_url: str) -> None:
    # Destructive downgrade runs on the isolated empty state `clean_db` provides, never on the
    # populated shared database (0002 refuses to drop kinds that rows still use).
    config = alembic_config(pg_url)

    command.downgrade(config, "base")
    assert _public_tables(migrated_engine) == {"alembic_version"}

    command.upgrade(config, "head")
    assert _public_tables(migrated_engine) == set(Base.metadata.tables) | {"alembic_version"}


def test_metadata_matches_migration(migrated_engine: Engine) -> None:
    # `migrated_engine` is at head (M4 in this milestone), so the ORM mirror must match
    # the 0004 schema exactly: tables, columns, types, nullability, server defaults,
    # unique constraints and indexes.
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={"compare_type": True, "compare_server_default": True},
        )
        differences = compare_metadata(context, Base.metadata)
    assert differences == []


def test_m4_tables_are_in_metadata(migrated_engine: Engine) -> None:
    # 0004 added the M4 tables to the ORM mirror; they must be registered for
    # `clean_db` truncation and for the parity comparison above.
    assert set(M4_TABLES) <= set(Base.metadata.tables)


M1_HEAD = "0001_m1_evidence_substrate"
M1_ARTIFACT_KINDS = (
    "ingest_report",
    "extraction_snapshot",
    "alignment_file",
    "cldf_export",
    "benchmark_report",
    "dataset",
    "other",
)
M2_ARTIFACT_KINDS = (
    "extraction_report",
    "extraction_error",
    "normalization_report",
    "tokenization_report",
)


def _artifact_kind_check(engine: Engine) -> str:
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": "ck_artifact_kind"},
        ).scalar_one()
    return str(definition)


def test_migration_0002_upgrade_downgrade_roundtrip(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    # Same isolation rule: the 0002 roundtrip may only run against empty schema state.
    config = alembic_config(pg_url)

    command.downgrade(config, M1_HEAD)
    m1_check = _artifact_kind_check(migrated_engine)
    assert all(f"'{kind}'" in m1_check for kind in M1_ARTIFACT_KINDS)
    assert not any(f"'{kind}'" in m1_check for kind in M2_ARTIFACT_KINDS)

    command.upgrade(config, "head")
    m2_check = _artifact_kind_check(migrated_engine)
    assert all(f"'{kind}'" in m2_check for kind in M1_ARTIFACT_KINDS + M2_ARTIFACT_KINDS)


def test_downgrade_0002_refuses_when_new_artifact_kinds_exist(
    pg_repository: PostgresRepository, migrated_engine: Engine, pg_url: str
) -> None:
    run = make_run(stage=RunStage.EXTRACTION)
    artifact = Artifact(
        id=new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.EXTRACTION_REPORT,
        media_type="application/json",
        sha256=SHA_A,
        size_bytes=2,
        access_class=AccessClass.PUBLIC,
        created_at=NOW,
    )
    with pg_repository.transaction():
        pg_repository.add_run(run)
        pg_repository.add_artifact(artifact)

    with pytest.raises(RuntimeError, match="M2 artifact kinds"):
        command.downgrade(alembic_config(pg_url), M1_HEAD)

    assert "'extraction_report'" in _artifact_kind_check(migrated_engine)
    assert pg_repository.get_artifact(artifact.id) == artifact


M2_HEAD = "0002_m2_text_processing"
M3_HEAD = "0003_m3_alignment"
M4_HEAD = "0004_m4_lexical_and_review"

M3_TABLES = ("segment_alignment", "segment_alignment_member", "token_alignment_edge")
M3_TRIGGERS = (
    "trg_segment_alignment_forbid_mutation",
    "trg_segment_alignment_member_forbid_mutation",
    "trg_token_alignment_edge_forbid_mutation",
    "trg_segment_alignment_stamp_creation",
    "trg_segment_alignment_group_guard",
    "trg_segment_alignment_member_guard",
    "trg_token_alignment_edge_guard",
)
# 0003-owned trigger functions; all must be gone after a downgrade so the next upgrade
# does not collide with surviving definitions.
M3_FUNCTIONS = (
    "langpipe_segment_alignment_stamp_creation",
    "langpipe_segment_alignment_group_guard",
    "langpipe_segment_alignment_member_guard",
    "langpipe_token_alignment_edge_guard",
    "langpipe_validate_segment_alignment_group",
    "langpipe_alignment_selected_sides",
)


def _entity_type_check(engine: Engine) -> str:
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": "ck_object_registry_entity_type"},
        ).scalar_one()
    return str(definition)


def _m3_triggers(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE event_object_table IN :tables"
            ).bindparams(bindparam("tables", expanding=True)),
            {"tables": list(M3_TABLES)},
        )
        return {row[0] for row in rows}


def _surviving_functions(engine: Engine, names: tuple[str, ...]) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT proname FROM pg_proc WHERE proname IN :names").bindparams(
                bindparam("names", expanding=True)
            ),
            {"names": list(names)},
        )
        return {row[0] for row in rows}


def test_m3_metadata_parity(migrated_engine: Engine) -> None:
    # 0003 added the M3 tables to the ORM mirror; compare_metadata must still report no drift.
    assert set(M3_TABLES) <= set(Base.metadata.tables)
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={"compare_type": True, "compare_server_default": True},
        )
        differences = compare_metadata(context, Base.metadata)
        marker = conn.execute(
            text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'segment_alignment' AND column_name = 'creating_txid'"
            )
        ).one()
    assert differences == []
    # The DB-owned creation marker is mirrored as an ordinary NOT NULL bigint column
    # (ADR-0011 §8): internal storage bookkeeping, not domain metadata.
    assert marker == ("bigint", "NO")


def test_m3_empty_roundtrip(migrated_engine: Engine, clean_db: None, pg_url: str) -> None:
    # Empty 0002->0003->0002->0003 is mandatory (M3-PLAN §5.3); destructive downgrades only
    # run on the isolated empty state `clean_db` provides.
    config = alembic_config(pg_url)

    command.downgrade(config, M2_HEAD)
    assert not (set(M3_TABLES) & _public_tables(migrated_engine))
    assert "'segment_alignment'" not in _entity_type_check(migrated_engine)
    assert _m3_triggers(migrated_engine) == set()
    assert _surviving_functions(migrated_engine, M3_FUNCTIONS) == set()

    command.upgrade(config, "head")
    assert set(M3_TABLES) <= _public_tables(migrated_engine)
    assert "'segment_alignment'" in _entity_type_check(migrated_engine)
    assert "'token_alignment_edge'" in _entity_type_check(migrated_engine)
    # Append-only trigger on each M3 table, the creation-stamp trigger and the three
    # deferred guard triggers.
    assert _m3_triggers(migrated_engine) == set(M3_TRIGGERS)
    assert _surviving_functions(migrated_engine, M3_FUNCTIONS) == set(M3_FUNCTIONS)

    command.downgrade(config, M2_HEAD)
    command.upgrade(config, "head")
    assert set(M3_TABLES) <= _public_tables(migrated_engine)
    assert _m3_triggers(migrated_engine) == set(M3_TRIGGERS)


def test_m3_downgrade_refuses_any_alignment_data(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    ids = seed_valid_group(migrated_engine)

    with pytest.raises(RuntimeError, match="refused"):
        command.downgrade(alembic_config(pg_url), M2_HEAD)

    # Refusal runs before any DDL and is transactional: schema and rows survive untouched.
    assert set(M3_TABLES) <= _public_tables(migrated_engine)
    with migrated_engine.connect() as conn:
        for table, expected in (
            ("segment_alignment", 1),
            ("segment_alignment_member", 2),
            ("token_alignment_edge", 1),
        ):
            count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            assert count == expected, table
        edge = conn.execute(
            text("SELECT id FROM token_alignment_edge WHERE id = :id"), {"id": ids["edge"]}
        ).scalar_one()
    assert edge == ids["edge"]


@pytest.mark.parametrize(
    ("entity_type", "prefix"),
    [
        ("segment_alignment", IdPrefix.SEGMENT_ALIGNMENT),
        ("token_alignment_edge", IdPrefix.TOKEN_ALIGNMENT),
    ],
)
def test_m3_registry_reference_blocks_downgrade(
    migrated_engine: Engine, clean_db: None, pg_url: str, entity_type: str, prefix: IdPrefix
) -> None:
    # A registry entry alone blocks the downgrade: run I/O and lineage rows foreign-key
    # object_registry, so none can reference an M3 object without one of these entries.
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO object_registry (id, entity_type, created_at) "
                "VALUES (:id, :entity_type, :now)"
            ),
            {"id": new_id(prefix), "entity_type": entity_type, "now": NOW},
        )

    with pytest.raises(RuntimeError, match="refused"):
        command.downgrade(alembic_config(pg_url), M2_HEAD)

    assert set(M3_TABLES) <= _public_tables(migrated_engine)
    assert f"'{entity_type}'" in _entity_type_check(migrated_engine)


M4_TABLES = (
    "concept",
    "lexeme",
    "form_lexeme",
    "sense",
    "review_task",
    "review_decision",
)
# Append-only immutability triggers on the M4 tables (ADR-0013 §1/§5).
M4_IMMUTABLE_TABLES = ("form_lexeme", "review_decision")
# 0004-owned entity types appended to ck_object_registry_entity_type.
M4_ENTITY_TYPES = (
    "concept",
    "lexeme",
    "form_lexeme",
    "sense",
    "review_task",
    "review_decision",
)
M4_TASK_TYPES = (
    "lexical_sense",
    "lemma",
    "morphology_segmentation",
    "morpheme_function",
    "grammar_construction",
    "register_domain",
    "alignment_spotcheck",
    "governance_export",
    "pronunciation",
)
M4_DECISIONS = ("accept", "reject", "modify", "uncertain", "defer")
M4_LIFECYCLE_STATUSES = ("candidate", "supported", "validated", "rejected", "deprecated")
M4_TASK_STATUSES = ("open", "in_review", "resolved", "cancelled")
M4_LEXEME_INDEXES = ("ix_lexeme_language", "ix_lexeme_lemma_form_id")
M4_FORM_LEXEME_INDEXES = ("ix_form_lexeme_form_id", "ix_form_lexeme_lexeme_id")
M4_SENSE_INDEXES = ("ix_sense_lexeme_id", "ix_sense_concept_id")
M4_REVIEW_TASK_INDEXES = ("ix_review_task_status_priority", "ix_review_task_target_id")
M4_REVIEW_DECISION_INDEXES = ("ix_review_decision_task_id", "ix_review_decision_target_id")

# CHECK constraint name -> allowed values asserted in the roundtrip test.
M4_CHECK_VALUES: dict[str, tuple[str, ...]] = {
    "ck_lexeme_status": M4_LIFECYCLE_STATUSES,
    "ck_sense_status": M4_LIFECYCLE_STATUSES,
    "ck_review_task_task_type": M4_TASK_TYPES,
    "ck_review_task_status": M4_TASK_STATUSES,
    "ck_review_decision_decision": M4_DECISIONS,
}


def _m4_triggers(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE event_object_table IN :tables"
            ).bindparams(bindparam("tables", expanding=True)),
            {"tables": list(M4_IMMUTABLE_TABLES)},
        )
        return {row[0] for row in rows}


def _index_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t"),
            {"t": table},
        )
        return {row[0] for row in rows}


def _check_constraint(engine: Engine, name: str) -> str:
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": name},
        ).scalar_one_or_none()
    assert definition is not None, name
    return str(definition)


def _column_default(engine: Engine, table: str, column: str) -> str | None:
    with engine.connect() as conn:
        default = conn.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar_one_or_none()
    return None if default is None else str(default)


def _unique_constraint(engine: Engine, table: str, name: str) -> str:
    with engine.connect() as conn:
        definition = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": name},
        ).scalar_one_or_none()
    assert definition is not None, name
    return str(definition)


def test_m4_empty_roundtrip(migrated_engine: Engine, clean_db: None, pg_url: str) -> None:
    # Empty M3->M4->M3->M4 is mandatory (M4-PLAN §WP4.2); destructive downgrades only run on
    # the isolated empty state `clean_db` provides.
    config = alembic_config(pg_url)

    command.downgrade(config, M3_HEAD)
    assert not set(M4_TABLES) & _public_tables(migrated_engine)
    assert "'concept'" not in _entity_type_check(migrated_engine)
    assert _m4_triggers(migrated_engine) == set()
    # M3 evidence survives the M4 downgrade untouched.
    assert set(M3_TABLES) <= _public_tables(migrated_engine)

    command.upgrade(config, "head")
    assert set(M4_TABLES) <= _public_tables(migrated_engine)
    # Append-only trigger on each immutable M4 table and no other trigger on them.
    assert _m4_triggers(migrated_engine) == {
        f"trg_{table}_forbid_mutation" for table in M4_IMMUTABLE_TABLES
    }
    for entity_type in M4_ENTITY_TYPES:
        assert f"'{entity_type}'" in _entity_type_check(migrated_engine)
    # Indexes, the form/lexeme unique constraint and the lifecycle CHECK values.
    assert set(M4_LEXEME_INDEXES) <= _index_names(migrated_engine, "lexeme")
    assert set(M4_FORM_LEXEME_INDEXES) <= _index_names(migrated_engine, "form_lexeme")
    assert set(M4_SENSE_INDEXES) <= _index_names(migrated_engine, "sense")
    assert set(M4_REVIEW_TASK_INDEXES) <= _index_names(migrated_engine, "review_task")
    assert set(M4_REVIEW_DECISION_INDEXES) <= _index_names(migrated_engine, "review_decision")
    assert (
        _unique_constraint(migrated_engine, "form_lexeme", "ux_form_lexeme_pair")
        == "UNIQUE (form_id, lexeme_id)"
    )
    for check, values in M4_CHECK_VALUES.items():
        definition = _check_constraint(migrated_engine, check)
        assert all(f"'{value}'" in definition for value in values)
    assert _column_default(migrated_engine, "review_task", "status") == "'open'::text"
    assert _column_default(migrated_engine, "concept", "concept_type") == "'local'::text"

    command.downgrade(config, M3_HEAD)
    command.upgrade(config, "head")
    assert set(M4_TABLES) <= _public_tables(migrated_engine)
    assert _m4_triggers(migrated_engine) == {
        f"trg_{table}_forbid_mutation" for table in M4_IMMUTABLE_TABLES
    }
    for entity_type in M4_ENTITY_TYPES:
        assert f"'{entity_type}'" in _entity_type_check(migrated_engine)


def _seed_lexical_row(engine: Engine) -> str:
    """One committed concept row with its registry entry and a succeeded run."""
    concept_id = new_id(IdPrefix.CONCEPT)
    run_id = new_id(IdPrefix.RUN)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO object_registry (id, entity_type, created_at) "
                "VALUES (:id, 'concept', :now)"
            ),
            {"id": concept_id, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO object_registry (id, entity_type, created_at) "
                "VALUES (:id, 'processing_run', :now)"
            ),
            {"id": run_id, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO processing_run (id, stage, tool_name, tool_version, config, "
                "config_hash, code_revision, run_key, random_seed, status, started_at, "
                "finished_at, error_type, error_message) VALUES (:id, 'lexical_induction', "
                "'test-tool', '0.0.0', '{}'::jsonb, :hash, 'rev-test', :hash, NULL, "
                "'succeeded', :now, :now, NULL, NULL)"
            ),
            {"id": run_id, "hash": SHA_A, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO concept (id, concept_type, canonical_label, concepticon_id, "
                "external_urn, run_id, created_at) VALUES (:id, 'local', 'canoa', NULL, NULL, "
                ":run_id, :now)"
            ),
            {"id": concept_id, "run_id": run_id, "now": NOW},
        )
    return concept_id


def test_m4_downgrade_refuses_any_lexical_data(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    concept_id = _seed_lexical_row(migrated_engine)

    with pytest.raises(RuntimeError, match="refused"):
        command.downgrade(alembic_config(pg_url), M3_HEAD)

    # Refusal runs before any DDL and is transactional: schema and rows survive untouched.
    assert set(M4_TABLES) <= _public_tables(migrated_engine)
    with migrated_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM concept")).scalar_one()
        survived = conn.execute(
            text("SELECT id FROM concept WHERE id = :id"), {"id": concept_id}
        ).scalar_one()
    assert count == 1
    assert survived == concept_id


def test_m4_downgrade_refuses_review_task_rows(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    task_id = new_id(IdPrefix.REVIEW_TASK)
    run_id = new_id(IdPrefix.RUN)
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO object_registry (id, entity_type, created_at) "
                "VALUES (:id, 'review_task', :now)"
            ),
            {"id": task_id, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO object_registry (id, entity_type, created_at) "
                "VALUES (:id, 'processing_run', :now)"
            ),
            {"id": run_id, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO processing_run (id, stage, tool_name, tool_version, config, "
                "config_hash, code_revision, run_key, random_seed, status, started_at, "
                "finished_at, error_type, error_message) VALUES (:id, 'lexical_induction', "
                "'test-tool', '0.0.0', '{}'::jsonb, :hash, 'rev-test', :hash, NULL, "
                "'succeeded', :now, :now, NULL, NULL)"
            ),
            {"id": run_id, "hash": SHA_A, "now": NOW},
        )
        conn.execute(
            text(
                "INSERT INTO review_task (id, task_type, target_id, target_version, "
                "evidence_item_ids, required_role, priority, reason, creator_run_id, status, "
                "created_at) VALUES (:id, 'lexical_sense', :target_id, NULL, '[]'::jsonb, "
                "'community_linguist', 1.5, 'synthetic reason', :run_id, 'open', :now)"
            ),
            {"id": task_id, "target_id": task_id, "run_id": run_id, "now": NOW},
        )

    with pytest.raises(RuntimeError, match="refused"):
        command.downgrade(alembic_config(pg_url), M3_HEAD)

    assert set(M4_TABLES) <= _public_tables(migrated_engine)


@pytest.mark.parametrize(
    ("entity_type", "prefix"),
    [
        ("concept", IdPrefix.CONCEPT),
        ("lexeme", IdPrefix.LEXEME),
        ("sense", IdPrefix.SENSE),
        ("review_task", IdPrefix.REVIEW_TASK),
        ("review_decision", IdPrefix.REVIEW_DECISION),
        ("form_lexeme", IdPrefix.FORM_LEXEME),
    ],
)
def test_m4_registry_reference_blocks_downgrade(
    migrated_engine: Engine,
    clean_db: None,
    pg_url: str,
    entity_type: str,
    prefix: IdPrefix,
) -> None:
    # A registry entry alone blocks the downgrade: lineage_edge and evidence_item rows
    # foreign-key object_registry, so none can reference an M4 object without one of
    # these entries (ADR-0013 §1).
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO object_registry (id, entity_type, created_at) "
                "VALUES (:id, :entity_type, :now)"
            ),
            {"id": new_id(prefix), "entity_type": entity_type, "now": NOW},
        )

    with pytest.raises(RuntimeError, match="refused"):
        command.downgrade(alembic_config(pg_url), M3_HEAD)

    assert set(M4_TABLES) <= _public_tables(migrated_engine)
    assert f"'{entity_type}'" in _entity_type_check(migrated_engine)


RESTRICT_VIOLATION = "23001"
CHECK_VIOLATION = "23514"


def _succeeded_run(conn: Connection, run_id: str) -> None:
    """Register and commit one succeeded lexical_induction run."""
    conn.execute(
        text(
            "INSERT INTO object_registry (id, entity_type, created_at) "
            "VALUES (:id, 'processing_run', :now)"
        ),
        {"id": run_id, "now": NOW},
    )
    conn.execute(
        text(
            "INSERT INTO processing_run (id, stage, tool_name, tool_version, config, "
            "config_hash, code_revision, run_key, random_seed, status, started_at, "
            "finished_at, error_type, error_message) VALUES (:id, 'lexical_induction', "
            "'test-tool', '0.0.0', '{}'::jsonb, :hash, 'rev-test', :hash, NULL, "
            "'succeeded', :now, :now, NULL, NULL)"
        ),
        {"id": run_id, "hash": SHA_A, "now": NOW},
    )


def _register(conn: Connection, object_id: str, entity_type: str) -> None:
    conn.execute(
        text(
            "INSERT INTO object_registry (id, entity_type, created_at) "
            "VALUES (:id, :entity_type, :now)"
        ),
        {"id": object_id, "entity_type": entity_type, "now": NOW},
    )


def _seed_form_lexeme(engine: Engine) -> dict[str, str]:
    """One committed form_lexeme link with its lexeme, form, registry entries and run."""
    run_id = new_id(IdPrefix.RUN)
    lexeme_id = new_id(IdPrefix.LEXEME)
    link_id = new_id(IdPrefix.FORM_LEXEME)
    form_id = new_id(IdPrefix.FORM)
    with engine.begin() as conn:
        _succeeded_run(conn, run_id)
        _register(conn, form_id, "form")
        conn.execute(
            text(
                "INSERT INTO form (id, language, orthography_profile, text, run_id, created_at) "
                "VALUES (:id, 'mzr', 'default', 'wesa', :run_id, :now)"
            ),
            {"id": form_id, "run_id": run_id, "now": NOW},
        )
        _register(conn, lexeme_id, "lexeme")
        conn.execute(
            text(
                "INSERT INTO lexeme (id, language, lemma_form_id, pos, status, register, "
                "domain, score_breakdown, run_id, created_at) VALUES (:id, 'mzr', :form_id, "
                "'noun', 'candidate', NULL, NULL, NULL, :run_id, :now)"
            ),
            {"id": lexeme_id, "form_id": form_id, "run_id": run_id, "now": NOW},
        )
        _register(conn, link_id, "form_lexeme")
        conn.execute(
            text(
                "INSERT INTO form_lexeme (id, form_id, lexeme_id, role, run_id, created_at) "
                "VALUES (:id, :form_id, :lexeme_id, 'primary_lemma', :run_id, :now)"
            ),
            {
                "id": link_id,
                "form_id": form_id,
                "lexeme_id": lexeme_id,
                "run_id": run_id,
                "now": NOW,
            },
        )
    return {"run": run_id, "lexeme": lexeme_id, "form": form_id, "link": link_id}


def _seed_review_decision(engine: Engine) -> dict[str, str]:
    """One committed review_decision with its task, target registry entries and run."""
    run_id = new_id(IdPrefix.RUN)
    task_id = new_id(IdPrefix.REVIEW_TASK)
    decision_id = new_id(IdPrefix.REVIEW_DECISION)
    target_id = new_id(IdPrefix.LEXEME)
    with engine.begin() as conn:
        _succeeded_run(conn, run_id)
        _register(conn, target_id, "lexeme")
        _register(conn, task_id, "review_task")
        conn.execute(
            text(
                "INSERT INTO review_task (id, task_type, target_id, target_version, "
                "evidence_item_ids, required_role, priority, reason, creator_run_id, status, "
                "created_at) VALUES (:id, 'lexical_sense', :target_id, NULL, '[]'::jsonb, "
                "'community_linguist', 1.5, 'synthetic reason', :run_id, 'open', :now)"
            ),
            {"id": task_id, "target_id": target_id, "run_id": run_id, "now": NOW},
        )
        _register(conn, decision_id, "review_decision")
        conn.execute(
            text(
                "INSERT INTO review_decision (id, task_id, target_id, decision, reviewer_id, "
                "reviewer_role, superseding_object_id, notes, created_at) VALUES (:id, :task_id, "
                ":target_id, 'accept', 'rev_00000000000000000000000000', 'community_linguist', "
                "NULL, NULL, :now)"
            ),
            {"id": decision_id, "task_id": task_id, "target_id": target_id, "now": NOW},
        )
    return {"run": run_id, "task": task_id, "decision": decision_id, "target": target_id}


def _row(engine: Engine, table: str, object_id: str) -> tuple[object, ...]:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT * FROM {table} WHERE id = :id"), {"id": object_id}).one()


def _expect_mutation_rejected(engine: Engine, statement: str, table: str, object_id: str) -> None:
    """A mutation on an append-only table must fail with the trigger's SQLSTATE, and the
    savepoint recovery must leave the row exactly as it was (Invariant: append-only)."""
    before = _row(engine, table, object_id)
    with pytest.raises(DBAPIError) as excinfo, engine.begin() as conn:
        nested = conn.begin_nested()
        try:
            conn.execute(text(statement), {"id": object_id})
        finally:
            # ROLLBACK TO SAVEPOINT: the failed statement aborts the transaction, so the
            # row is recoverable only inside a savepoint.
            nested.rollback()
    assert excinfo.value.orig is not None
    assert excinfo.value.orig.sqlstate == RESTRICT_VIOLATION
    assert "append-only" in str(excinfo.value.orig)
    assert _row(engine, table, object_id) == before


def test_m4_form_lexeme_update_rejected(migrated_engine: Engine, clean_db: None) -> None:
    ids = _seed_form_lexeme(migrated_engine)
    _expect_mutation_rejected(
        migrated_engine,
        "UPDATE form_lexeme SET role = 'variant' WHERE id = :id",
        "form_lexeme",
        ids["link"],
    )


def test_m4_form_lexeme_delete_rejected(migrated_engine: Engine, clean_db: None) -> None:
    ids = _seed_form_lexeme(migrated_engine)
    _expect_mutation_rejected(
        migrated_engine, "DELETE FROM form_lexeme WHERE id = :id", "form_lexeme", ids["link"]
    )


def test_m4_review_decision_update_rejected(migrated_engine: Engine, clean_db: None) -> None:
    ids = _seed_review_decision(migrated_engine)
    _expect_mutation_rejected(
        migrated_engine,
        "UPDATE review_decision SET notes = 'changed' WHERE id = :id",
        "review_decision",
        ids["decision"],
    )


def test_m4_review_decision_delete_rejected(migrated_engine: Engine, clean_db: None) -> None:
    ids = _seed_review_decision(migrated_engine)
    _expect_mutation_rejected(
        migrated_engine,
        "DELETE FROM review_decision WHERE id = :id",
        "review_decision",
        ids["decision"],
    )


def test_m4_append_only_survives_downgrade_upgrade(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    # Coverage after a downgrade/re-upgrade: the empty roundtrip recreates the M4 schema, so
    # a disabled, stale or duplicated trigger cannot pass the roundtrip unnoticed. The rows
    # are seeded after the re-upgrade because the downgrade itself refuses populated M4
    # tables (Invariant: lineage-bearing rows are never silently dropped).
    config = alembic_config(pg_url)
    command.downgrade(config, M3_HEAD)
    command.upgrade(config, "head")
    ids = _seed_form_lexeme(migrated_engine)
    _expect_mutation_rejected(
        migrated_engine,
        "UPDATE form_lexeme SET role = 'variant' WHERE id = :id",
        "form_lexeme",
        ids["link"],
    )


def test_m4_custom_concept_type_persists(migrated_engine: Engine, clean_db: None) -> None:
    # `concept_type` is an open string in the domain model (any nonempty text), so the
    # schema must not narrow it with a CHECK vocabulary; only the local default is fixed.
    run_id = new_id(IdPrefix.RUN)
    concept_id = new_id(IdPrefix.CONCEPT)
    with migrated_engine.begin() as conn:
        _succeeded_run(conn, run_id)
        _register(conn, concept_id, "concept")
        conn.execute(
            text(
                "INSERT INTO concept (id, concept_type, canonical_label, concepticon_id, "
                "external_urn, run_id, created_at) VALUES (:id, 'community_defined', "
                "'synthetic', NULL, NULL, :run_id, :now)"
            ),
            {"id": concept_id, "run_id": run_id, "now": NOW},
        )
    with migrated_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT concept_type FROM concept WHERE id = :id"), {"id": concept_id}
        ).scalar_one()
    assert stored == "community_defined"


def test_m4_concept_type_has_no_check(migrated_engine: Engine, clean_db: None) -> None:
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'concept'::regclass AND contype = 'c'"
            )
        )
        names = {row[0] for row in rows}
    assert "ck_concept_concept_type" not in names


def _m3_snapshot(engine: Engine) -> dict[str, list[tuple[object, ...]]]:
    """Row snapshots of the M3 evidence tables plus their registry and run references."""
    tables = (
        "source",
        "source_object",
        "processing_run",
        "segment",
        "token_occurrence",
        "form",
        "segment_alignment",
        "segment_alignment_member",
        "token_alignment_edge",
        "object_registry",
        "source_policy",
    )
    snapshot: dict[str, list[tuple[object, ...]]] = {}
    with engine.connect() as conn:
        for table in tables:
            rows = conn.execute(text(f"SELECT * FROM {table} ORDER BY 1")).mappings().all()
            snapshot[table] = [tuple(row.values()) for row in rows]
    return snapshot


def test_m4_downgrade_preserves_m3_data(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    # Populated M3 evidence must survive a 0004->0003->0004 roundtrip byte for byte; the M4
    # tables stay empty so the destructive downgrade is permitted.
    ids = seed_valid_group(migrated_engine)
    before = _m3_snapshot(migrated_engine)
    config = alembic_config(pg_url)

    command.downgrade(config, M3_HEAD)
    assert not set(M4_TABLES) & _public_tables(migrated_engine)
    assert _m3_snapshot(migrated_engine) == before

    command.upgrade(config, "head")
    assert set(M4_TABLES) <= _public_tables(migrated_engine)
    assert _m3_snapshot(migrated_engine) == before
    assert ids["edge"]


M5_HEAD = "0006_m5_igt_and_morphology"

M5_TABLES = (
    "source_use_approval",
    "igt_observation",
    "feature",
    "morpheme",
    "allomorph",
    "morph_analysis",
    "morph_segment",
    "morph_segment_feature",
)
# Append-only immutability triggers (ADR-0017: observations are never rewritten).
M5_APPEND_ONLY_TABLES = (
    "source_use_approval",
    "igt_observation",
    "feature",
    "morph_segment",
    "morph_segment_feature",
)
# Hypothesis tables: `langpipe_hypothesis_guard` allows only status/score_breakdown changes.
M5_HYPOTHESIS_TABLES = ("morpheme", "allomorph", "morph_analysis")
M5_ENTITY_TYPES = (
    "igt_observation",
    "feature",
    "morpheme",
    "allomorph",
    "morph_analysis",
    "morph_segment",
    "source_use_approval",
)
M5_FUNCTIONS = ("langpipe_hypothesis_guard",)


def test_m5_tables_are_in_metadata(migrated_engine: Engine) -> None:
    # 0006 added the M5 tables to the ORM mirror; they must be registered for `clean_db`
    # truncation and for the parity comparison above.
    assert set(M5_TABLES) <= set(Base.metadata.tables)


def _lineage_kind_check(engine: Engine) -> str:
    return _check_constraint(engine, "ck_lineage_edge_kind")


def _audit_event_check(engine: Engine) -> str:
    return _check_constraint(engine, "ck_audit_event_event_type")


def _m5_triggers(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE event_object_table IN :tables"
            ).bindparams(bindparam("tables", expanding=True)),
            {"tables": list(M5_APPEND_ONLY_TABLES + M5_HYPOTHESIS_TABLES)},
        )
        return {row[0] for row in rows}


def _expected_m5_triggers() -> set[str]:
    return {f"trg_{table}_forbid_mutation" for table in M5_APPEND_ONLY_TABLES} | {
        f"trg_{table}_guard" for table in M5_HYPOTHESIS_TABLES
    }


def _m5_check_names(engine: Engine) -> set[str]:
    """CHECK constraint names 0006 defines on the M5 tables — the coverage baseline the
    rejection probes in `test_migration_0006_checks_reject_invalid_values` must match."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "WHERE con.contype = 'c' AND rel.relname IN :tables"
            ).bindparams(bindparam("tables", expanding=True)),
            {"tables": list(M5_TABLES)},
        )
        return {row[0] for row in rows}


def test_migration_0006_upgrade_downgrade_roundtrip(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    # Same isolation rule as 0003/0004: the destructive roundtrip runs only on the isolated
    # empty state `clean_db` provides.
    config = alembic_config(pg_url)

    command.downgrade(config, M4_HEAD)
    assert not set(M5_TABLES) & _public_tables(migrated_engine)
    for entity_type in M5_ENTITY_TYPES:
        assert f"'{entity_type}'" not in _entity_type_check(migrated_engine)
    assert "'recalculated'" not in _lineage_kind_check(migrated_engine)
    for event_type in ("source_use_approved", "source_use_withdrawn"):
        assert f"'{event_type}'" not in _audit_event_check(migrated_engine)
    assert _m5_triggers(migrated_engine) == set()
    assert _surviving_functions(migrated_engine, M5_FUNCTIONS) == set()
    # M4 evidence survives the M5 downgrade untouched.
    assert set(M4_TABLES) <= _public_tables(migrated_engine)

    command.upgrade(config, M5_HEAD)
    assert set(M5_TABLES) <= _public_tables(migrated_engine)
    for entity_type in M5_ENTITY_TYPES:
        assert f"'{entity_type}'" in _entity_type_check(migrated_engine)
    assert "'recalculated'" in _lineage_kind_check(migrated_engine)
    for event_type in ("source_use_approved", "source_use_withdrawn"):
        assert f"'{event_type}'" in _audit_event_check(migrated_engine)
    assert _m5_triggers(migrated_engine) == _expected_m5_triggers()
    assert _surviving_functions(migrated_engine, M5_FUNCTIONS) == set(M5_FUNCTIONS)
    # Immutable-observation JSONB columns carry their verbatim defaults.
    assert _column_default(migrated_engine, "igt_observation", "locator") == "'{}'::jsonb"
    assert _column_default(migrated_engine, "igt_observation", "tiers") == "'[]'::jsonb"
    assert _column_default(migrated_engine, "igt_observation", "words") == "'[]'::jsonb"
    assert _column_default(migrated_engine, "igt_observation", "translations") == "'{}'::jsonb"
    assert _column_default(migrated_engine, "igt_observation", "diagnostics") == "'[]'::jsonb"
    assert _column_default(migrated_engine, "morpheme", "glosses") == "'{}'::jsonb"
    assert _column_default(migrated_engine, "morpheme", "gloss_labels") == "'[]'::jsonb"
    assert _column_default(migrated_engine, "allomorph", "is_zero") == "false"
    assert _column_default(migrated_engine, "morph_segment", "is_zero") == "false"

    command.downgrade(config, M4_HEAD)
    command.upgrade(config, M5_HEAD)
    assert set(M5_TABLES) <= _public_tables(migrated_engine)
    assert _m5_triggers(migrated_engine) == _expected_m5_triggers()


def _seed_m5_base(engine: Engine) -> dict[str, str]:
    """One committed base chain (no M5 row yet): registry entries, policy, source, source
    object, segment, token occurrence and a succeeded run."""
    run_id = new_id(IdPrefix.RUN)
    policy_id = new_id(IdPrefix.POLICY)
    source_id = new_id(IdPrefix.SOURCE)
    object_id = new_id(IdPrefix.SOURCE_OBJECT)
    segment_id = new_id(IdPrefix.SEGMENT)
    token_id = new_id(IdPrefix.TOKEN)
    morpheme_id = new_id(IdPrefix.MORPHEME)
    allomorph_id = new_id(IdPrefix.ALLOMORPH)
    analysis_id = new_id(IdPrefix.MORPH_ANALYSIS)
    mseg_id = new_id(IdPrefix.MORPH_SEGMENT)
    feature_id = new_id(IdPrefix.FEATURE)
    approval_id = new_id(IdPrefix.SOURCE_USE_APPROVAL)
    with engine.begin() as conn:
        _succeeded_run(conn, run_id)
        conn.execute(
            text(
                "INSERT INTO source_policy (id, mode, access_class, authority, allow, deny, "
                "restrictions, policy_version, created_at) VALUES (:id, 'direct', 'public', "
                "'test-authority', '{}'::text[], '{}'::text[], '{}'::jsonb, 1, :now)"
            ),
            {"id": policy_id, "now": NOW},
        )
        _register(conn, source_id, "source")
        conn.execute(
            text(
                "INSERT INTO source (id, key, title, source_type, languages, provenance, "
                "policy_id, acquired_at, status, domains, registers, manifest_sha256, "
                "registration_run_id, created_at, updated_at) VALUES (:id, 'synthetic-m5', "
                "'Synthetic', 'igt', '{}'::text[], '{}'::jsonb, :policy_id, :now, 'registered', "
                "'{}'::text[], '{}'::text[], :hash, :run_id, :now, :now)"
            ),
            {
                "id": source_id,
                "policy_id": policy_id,
                "run_id": run_id,
                "hash": SHA_A,
                "now": NOW,
            },
        )
        _register(conn, object_id, "source_object")
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
                "hash": SHA_A,
                "run_id": run_id,
                "now": NOW,
            },
        )
        _register(conn, segment_id, "segment")
        conn.execute(
            text(
                "INSERT INTO segment (id, source_id, source_object_id, run_id, ordinal, "
                "language, locator, raw_text, normalized_text, normalization_profile, status, "
                "created_at) VALUES (:id, :source_id, :object_id, :run_id, 0, 'mzr', "
                "'{}'::jsonb, 'synthetic', NULL, NULL, 'ok', :now)"
            ),
            {
                "id": segment_id,
                "source_id": source_id,
                "object_id": object_id,
                "run_id": run_id,
                "now": NOW,
            },
        )
        _register(conn, token_id, "token_occurrence")
        conn.execute(
            text(
                "INSERT INTO token_occurrence (id, segment_id, run_id, ordinal, raw_surface, "
                "normalized_surface, raw_start, raw_end, norm_start, norm_end, tokenizer, "
                "form_id, created_at) VALUES (:id, :segment_id, :run_id, 0, 'synthetic', NULL, "
                "NULL, NULL, NULL, NULL, 'test-tokenizer', NULL, :now)"
            ),
            {"id": token_id, "segment_id": segment_id, "run_id": run_id, "now": NOW},
        )
        token2_id = new_id(IdPrefix.TOKEN)
        _register(conn, token2_id, "token_occurrence")
        conn.execute(
            text(
                "INSERT INTO token_occurrence (id, segment_id, run_id, ordinal, raw_surface, "
                "normalized_surface, raw_start, raw_end, norm_start, norm_end, tokenizer, "
                "form_id, created_at) VALUES (:id, :segment_id, :run_id, 1, 'ra', NULL, "
                "NULL, NULL, NULL, NULL, 'test-tokenizer', NULL, :now)"
            ),
            {"id": token2_id, "segment_id": segment_id, "run_id": run_id, "now": NOW},
        )
    return {
        "run": run_id,
        "policy": policy_id,
        "source": source_id,
        "source_object": object_id,
        "segment": segment_id,
        "token": token_id,
        "token2": token2_id,
        "morpheme": morpheme_id,
        "allomorph": allomorph_id,
        "analysis": analysis_id,
        "mseg": mseg_id,
        "feature": feature_id,
        "approval": approval_id,
    }


def _insert_approval(conn: Connection, ids: dict[str, str]) -> None:
    _register(conn, ids["approval"], "source_use_approval")
    conn.execute(
        text(
            "INSERT INTO source_use_approval (id, source_id, operation, action, approver_id, "
            "approver_role, basis, run_id, created_at) VALUES (:id, :source_id, 'read_raw', "
            "'grant', 'steward_1', 'governance_steward', 'community consent on file', "
            ":run_id, :now)"
        ),
        {"id": ids["approval"], "source_id": ids["source"], "run_id": ids["run"], "now": NOW},
    )


def _insert_igt_observation(conn: Connection, ids: dict[str, str]) -> None:
    igt_id = new_id(IdPrefix.IGT_OBSERVATION)
    conn.execute(
        text(
            "INSERT INTO object_registry (id, entity_type, created_at) "
            "VALUES (:id, 'igt_observation', :now)"
        ),
        {"id": igt_id, "now": NOW},
    )
    conn.execute(
        text(
            "INSERT INTO igt_observation (id, source_id, source_object_id, run_id, segment_id, "
            "record_ordinal, record_ref, format, locator, tiers, words, translations, "
            "parse_status, diagnostics, created_at) VALUES (:id, :source_id, :object_id, "
            ":run_id, :segment_id, 0, NULL, 'toolbox', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, "
            "'{}'::jsonb, 'ok', '[]'::jsonb, :now)"
        ),
        {
            "id": igt_id,
            "source_id": ids["source"],
            "object_id": ids["source_object"],
            "run_id": ids["run"],
            "segment_id": ids["segment"],
            "now": NOW,
        },
    )


def _insert_feature(conn: Connection, ids: dict[str, str]) -> None:
    _register(conn, ids["feature"], "feature")
    conn.execute(
        text(
            "INSERT INTO feature (id, namespace, label, definition, defined_by, run_id, "
            "created_at) VALUES (:id, 'unimorph', 'N', 'noun class', 'unimorph', :run_id, :now)"
        ),
        {"id": ids["feature"], "run_id": ids["run"], "now": NOW},
    )


def _insert_morpheme(conn: Connection, ids: dict[str, str]) -> None:
    _register(conn, ids["morpheme"], "morpheme")
    conn.execute(
        text(
            "INSERT INTO morpheme (id, language, role, canonical_form, form_basis, glosses, "
            "gloss_labels, identity_key, status, score_breakdown, run_id, created_at) "
            "VALUES (:id, 'mzr', 'root', 'synthetic', 'surface', '{}'::jsonb, '[]'::jsonb, "
            ":key, 'candidate', NULL, :run_id, :now)"
        ),
        {"id": ids["morpheme"], "key": SHA_A, "run_id": ids["run"], "now": NOW},
    )


def _insert_allomorph(conn: Connection, ids: dict[str, str]) -> None:
    _register(conn, ids["allomorph"], "allomorph")
    conn.execute(
        text(
            "INSERT INTO allomorph (id, morpheme_id, form, is_zero, form_basis, conditioning, "
            "conditioning_note, status, run_id, created_at) VALUES (:id, :morpheme_id, "
            "'variant', false, 'surface', 'phonological', NULL, 'candidate', :run_id, :now)"
        ),
        {"id": ids["allomorph"], "morpheme_id": ids["morpheme"], "run_id": ids["run"], "now": NOW},
    )


def _insert_analysis(conn: Connection, ids: dict[str, str]) -> None:
    _register(conn, ids["analysis"], "morph_analysis")
    conn.execute(
        text(
            "INSERT INTO morph_analysis (id, target_token_id, analysis_kind, method, "
            "span_representation, surface, signature, abstention, status, score_breakdown, "
            "run_id, created_at) VALUES (:id, :token_id, 'segmented', 'test-method', 'raw', "
            "'synthetic', :key, NULL, 'candidate', NULL, :run_id, :now)"
        ),
        {
            "id": ids["analysis"],
            "token_id": ids["token"],
            "key": SHA_A,
            "run_id": ids["run"],
            "now": NOW,
        },
    )


def _insert_morph_segment(conn: Connection, ids: dict[str, str]) -> None:
    _register(conn, ids["mseg"], "morph_segment")
    conn.execute(
        text(
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) "
            "VALUES (:id, :analysis_id, 0, 0, 9, false, 'synthetic', :morpheme_id, "
            ":allomorph_id, 'root', NULL, :now)"
        ),
        {
            "id": ids["mseg"],
            "analysis_id": ids["analysis"],
            "morpheme_id": ids["morpheme"],
            "allomorph_id": ids["allomorph"],
            "now": NOW,
        },
    )


def _insert_morph_segment_feature(conn: Connection, ids: dict[str, str]) -> None:
    conn.execute(
        text(
            "INSERT INTO morph_segment_feature (segment_id, feature_id, basis, created_at) "
            "VALUES (:segment_id, :feature_id, 'igt_gloss', :now)"
        ),
        {"segment_id": ids["mseg"], "feature_id": ids["feature"], "now": NOW},
    )


_INSERT_M5: dict[str, Callable[[Connection, dict[str, str]], None]] = {
    "source_use_approval": _insert_approval,
    "igt_observation": _insert_igt_observation,
    "feature": _insert_feature,
    "morpheme": _insert_morpheme,
    "allomorph": _insert_allomorph,
    "morph_analysis": _insert_analysis,
    "morph_segment": _insert_morph_segment,
    "morph_segment_feature": _insert_morph_segment_feature,
}

# The M5 rows each table's row insert depends on, in dependency order.
_M5_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "source_use_approval": (),
    "igt_observation": (),
    "feature": (),
    "morpheme": (),
    "allomorph": ("morpheme",),
    "morph_analysis": (),
    "morph_segment": ("morpheme", "allomorph", "morph_analysis"),
    "morph_segment_feature": (
        "morpheme",
        "allomorph",
        "morph_analysis",
        "morph_segment",
        "feature",
    ),
}


def _seed_m5_row(engine: Engine, table: str) -> dict[str, str]:
    """Committed base rows plus exactly the M5 row for `table` (with prerequisites)."""
    ids = _seed_m5_base(engine)
    with engine.begin() as conn:
        for prerequisite in _M5_PREREQUISITES[table]:
            _INSERT_M5[prerequisite](conn, ids)
        _INSERT_M5[table](conn, ids)
    return ids


def _seed_m5_world(engine: Engine) -> dict[str, str]:
    """One committed row in every M5 table."""
    ids = _seed_m5_base(engine)
    with engine.begin() as conn:
        for table in M5_TABLES:
            _INSERT_M5[table](conn, ids)
    return ids


def _m5_state_snapshot(engine: Engine) -> dict[str, object]:
    """Everything a refused downgrade must leave untouched: migration revision, M5 row
    counts, registry entries, M5 triggers and the CHECK vocabularies 0006 replaces."""
    checks = {
        "entity_type_check": _entity_type_check(engine),
        "lineage_kind_check": _lineage_kind_check(engine),
        "audit_event_check": _audit_event_check(engine),
    }
    triggers = _m5_triggers(engine)
    with engine.connect() as conn:
        return {
            "revision": conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
            "registry": conn.execute(
                text("SELECT id, entity_type FROM object_registry ORDER BY id")
            ).all(),
            "m5_rows": {
                table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in M5_TABLES
            },
            "triggers": triggers,
            **checks,
        }


@pytest.mark.parametrize("table", M5_TABLES)
def test_m5_row_blocks_downgrade(
    migrated_engine: Engine, clean_db: None, pg_url: str, table: str
) -> None:
    _seed_m5_row(migrated_engine, table)
    before = _m5_state_snapshot(migrated_engine)

    # The refusal scan runs dependent-first, so the error names exactly the table under
    # test: removing that table's count check fails this probe.
    with pytest.raises(RuntimeError, match=f"rows survive in {table}$"):
        command.downgrade(alembic_config(pg_url), M4_HEAD)

    # Refusal runs before any DDL and is transactional: revision, rows, registry entries,
    # triggers and CHECK vocabularies are all exactly as before.
    assert _m5_state_snapshot(migrated_engine) == before


@pytest.mark.parametrize(
    ("entity_type", "prefix"),
    [
        ("igt_observation", IdPrefix.IGT_OBSERVATION),
        ("feature", IdPrefix.FEATURE),
        ("morpheme", IdPrefix.MORPHEME),
        ("allomorph", IdPrefix.ALLOMORPH),
        ("morph_analysis", IdPrefix.MORPH_ANALYSIS),
        ("morph_segment", IdPrefix.MORPH_SEGMENT),
        ("source_use_approval", IdPrefix.SOURCE_USE_APPROVAL),
    ],
)
def test_m5_registry_reference_blocks_downgrade(
    migrated_engine: Engine,
    clean_db: None,
    pg_url: str,
    entity_type: str,
    prefix: IdPrefix,
) -> None:
    # A registry entry alone blocks the downgrade: every M5 table foreign-keys
    # object_registry, so no M5 row can exist without one of these entries (ADR-0009).
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO object_registry (id, entity_type, created_at) "
                "VALUES (:id, :entity_type, :now)"
            ),
            {"id": new_id(prefix), "entity_type": entity_type, "now": NOW},
        )

    before = _m5_state_snapshot(migrated_engine)
    with pytest.raises(RuntimeError, match="M5 registry entries survive$"):
        command.downgrade(alembic_config(pg_url), M4_HEAD)

    assert _m5_state_snapshot(migrated_engine) == before
    assert f"'{entity_type}'" in _entity_type_check(migrated_engine)


def test_m5_recalculated_edge_blocks_downgrade(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    run_id = new_id(IdPrefix.RUN)
    from_id = new_id(IdPrefix.FORM)
    to_id = new_id(IdPrefix.LEXEME)
    with migrated_engine.begin() as conn:
        _succeeded_run(conn, run_id)
        _register(conn, from_id, "form")
        _register(conn, to_id, "lexeme")
        conn.execute(
            text(
                "INSERT INTO lineage_edge (id, from_id, to_id, kind, run_id, created_at) "
                "VALUES (:id, :from_id, :to_id, 'recalculated', :run_id, :now)"
            ),
            {
                "id": new_id(IdPrefix.LINEAGE),
                "from_id": from_id,
                "to_id": to_id,
                "run_id": run_id,
                "now": NOW,
            },
        )

    before = _m5_state_snapshot(migrated_engine)
    with pytest.raises(RuntimeError, match="recalculated lineage edges survive$"):
        command.downgrade(alembic_config(pg_url), M4_HEAD)

    assert _m5_state_snapshot(migrated_engine) == before
    assert "'recalculated'" in _lineage_kind_check(migrated_engine)


def test_m5_approval_audit_event_blocks_downgrade(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_event (id, event_type, actor, subject_id, run_id, details, "
                "occurred_at) VALUES (:id, 'source_use_approved', 'steward_1', NULL, NULL, "
                "'{}'::jsonb, :now)"
            ),
            {"id": new_id(IdPrefix.AUDIT), "now": NOW},
        )

    before = _m5_state_snapshot(migrated_engine)
    with pytest.raises(RuntimeError, match="M5 audit events survive$"):
        command.downgrade(alembic_config(pg_url), M4_HEAD)

    assert _m5_state_snapshot(migrated_engine) == before
    assert "'source_use_approved'" in _audit_event_check(migrated_engine)


def _expect_check_violation(
    engine: Engine, statement: str, params: dict[str, object], check: str
) -> None:
    """The statement must fail on exactly the named CHECK constraint, and the savepoint
    recovery must leave the transaction usable (one probe per constraint)."""
    with pytest.raises(DBAPIError) as excinfo, engine.begin() as conn:
        nested = conn.begin_nested()
        try:
            conn.execute(text(statement), params)
        finally:
            nested.rollback()
    assert excinfo.value.orig is not None
    assert excinfo.value.orig.sqlstate == CHECK_VIOLATION, statement
    assert check in str(excinfo.value.orig), statement


def test_migration_0006_checks_reject_invalid_values(
    migrated_engine: Engine, clean_db: None
) -> None:
    ids = _seed_m5_world(migrated_engine)
    now = NOW
    # (invalid INSERT, the CHECK constraint that must reject it)
    cases: list[tuple[str, str]] = [
        (
            "INSERT INTO source_use_approval (id, source_id, operation, action, approver_id, "
            "approver_role, basis, run_id, created_at) VALUES (:id, :source, 'teleport', "
            "'grant', 'steward', 'governance_steward', 'basis', :run, :now)",
            "ck_source_use_approval_operation",
        ),
        (
            "INSERT INTO source_use_approval (id, source_id, operation, action, approver_id, "
            "approver_role, basis, run_id, created_at) VALUES (:id, :source, 'read_raw', "
            "'revoke', 'steward', 'governance_steward', 'basis', :run, :now)",
            "ck_source_use_approval_action",
        ),
        (
            "INSERT INTO source_use_approval (id, source_id, operation, action, approver_id, "
            "approver_role, basis, run_id, created_at) VALUES (:id, :source, 'read_raw', "
            "'grant', ' ', 'governance_steward', 'basis', :run, :now)",
            "ck_source_use_approval_approver_id",
        ),
        (
            "INSERT INTO source_use_approval (id, source_id, operation, action, approver_id, "
            "approver_role, basis, run_id, created_at) VALUES (:id, :source, 'read_raw', "
            "'grant', 'steward', '  ', 'basis', :run, :now)",
            "ck_source_use_approval_approver_role",
        ),
        (
            "INSERT INTO source_use_approval (id, source_id, operation, action, approver_id, "
            "approver_role, basis, run_id, created_at) VALUES (:id, :source, 'read_raw', "
            "'grant', 'steward', 'governance_steward', '  ', :run, :now)",
            "ck_source_use_approval_basis",
        ),
        (
            "INSERT INTO source_use_approval (id, source_id, operation, action, approver_id, "
            "approver_role, basis, run_id, created_at) VALUES ('sua_short', :source, "
            "'read_raw', 'grant', 'steward', 'governance_steward', 'basis', :run, :now)",
            "ck_source_use_approval_id",
        ),
        (
            "INSERT INTO igt_observation (id, source_id, source_object_id, run_id, segment_id, "
            "record_ordinal, record_ref, format, locator, tiers, words, translations, "
            "parse_status, diagnostics, created_at) VALUES ('igt_short', :source, :object, :run, "
            "NULL, 1, NULL, 'toolbox', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, "
            "'ok', '[]'::jsonb, :now)",
            "ck_igt_observation_id",
        ),
        (
            "INSERT INTO igt_observation (id, source_id, source_object_id, run_id, segment_id, "
            "record_ordinal, record_ref, format, locator, tiers, words, translations, "
            "parse_status, diagnostics, created_at) VALUES (:igt_id, :source, :object, :run, "
            "NULL, 1, NULL, 'excel', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, "
            "'ok', '[]'::jsonb, :now)",
            "ck_igt_observation_format",
        ),
        (
            "INSERT INTO igt_observation (id, source_id, source_object_id, run_id, segment_id, "
            "record_ordinal, record_ref, format, locator, tiers, words, translations, "
            "parse_status, diagnostics, created_at) VALUES (:igt_id, :source, :object, :run, "
            "NULL, 2, NULL, 'toolbox', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, "
            "'maybe', '[]'::jsonb, :now)",
            "ck_igt_observation_parse_status",
        ),
        (
            "INSERT INTO igt_observation (id, source_id, source_object_id, run_id, segment_id, "
            "record_ordinal, record_ref, format, locator, tiers, words, translations, "
            "parse_status, diagnostics, created_at) VALUES (:igt_id, :source, :object, :run, "
            "NULL, -1, NULL, 'toolbox', '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, "
            "'ok', '[]'::jsonb, :now)",
            "ck_igt_observation_record_ordinal",
        ),
        (
            "INSERT INTO feature (id, namespace, label, definition, defined_by, run_id, "
            "created_at) VALUES (:feat_id, 'universal', 'N', 'noun class', 'unimorph', :run, :now)",
            "ck_feature_namespace",
        ),
        (
            "INSERT INTO feature (id, namespace, label, definition, defined_by, run_id, "
            "created_at) VALUES (:feat_id, 'unimorph', '  ', 'noun class', 'unimorph', :run, :now)",
            "ck_feature_label",
        ),
        (
            "INSERT INTO feature (id, namespace, label, definition, defined_by, run_id, "
            "created_at) VALUES (:feat_id, 'unimorph', 'Adj', ' ', 'unimorph', :run, :now)",
            "ck_feature_definition",
        ),
        (
            "INSERT INTO feature (id, namespace, label, definition, defined_by, run_id, "
            "created_at) VALUES ('feat_short', 'unimorph', 'Adj', 'adjective class', "
            "'unimorph', :run, :now)",
            "ck_feature_id",
        ),
        (
            "INSERT INTO morpheme (id, language, role, canonical_form, form_basis, glosses, "
            "gloss_labels, identity_key, status, score_breakdown, run_id, created_at) "
            "VALUES (:morph_id, 'mzr', 'suffix', 'synthetic', 'surface', '{}'::jsonb, "
            "'[]'::jsonb, :key2, 'candidate', NULL, :run, :now)",
            "ck_morpheme_role",
        ),
        (
            "INSERT INTO morpheme (id, language, role, canonical_form, form_basis, glosses, "
            "gloss_labels, identity_key, status, score_breakdown, run_id, created_at) "
            "VALUES (:morph_id, 'MRZ', 'root', 'synthetic', 'surface', '{}'::jsonb, "
            "'[]'::jsonb, :key2, 'candidate', NULL, :run, :now)",
            "ck_morpheme_language",
        ),
        (
            "INSERT INTO morpheme (id, language, role, canonical_form, form_basis, glosses, "
            "gloss_labels, identity_key, status, score_breakdown, run_id, created_at) "
            "VALUES (:morph_id, 'mzr', 'root', 'synthetic', 'guessed', '{}'::jsonb, "
            "'[]'::jsonb, :key2, 'candidate', NULL, :run, :now)",
            "ck_morpheme_form_basis",
        ),
        (
            "INSERT INTO morpheme (id, language, role, canonical_form, form_basis, glosses, "
            "gloss_labels, identity_key, status, score_breakdown, run_id, created_at) "
            "VALUES (:morph_id, 'mzr', 'root', 'synthetic', 'surface', '{}'::jsonb, "
            "'[]'::jsonb, :key2, 'imagined', NULL, :run, :now)",
            "ck_morpheme_status",
        ),
        (
            "INSERT INTO morpheme (id, language, role, canonical_form, form_basis, glosses, "
            "gloss_labels, identity_key, status, score_breakdown, run_id, created_at) "
            "VALUES ('morph_short', 'mzr', 'root', 'synthetic', 'surface', '{}'::jsonb, "
            "'[]'::jsonb, :key2, 'candidate', NULL, :run, :now)",
            "ck_morpheme_id",
        ),
        (
            "INSERT INTO allomorph (id, morpheme_id, form, is_zero, form_basis, conditioning, "
            "conditioning_note, status, run_id, created_at) VALUES (:allo_id, :morpheme, "
            "'variant', false, 'surface', 'magical', NULL, 'candidate', :run, :now)",
            "ck_allomorph_conditioning",
        ),
        (
            "INSERT INTO allomorph (id, morpheme_id, form, is_zero, form_basis, conditioning, "
            "conditioning_note, status, run_id, created_at) VALUES (:allo_id, :morpheme, "
            "'', false, 'surface', 'phonological', NULL, 'candidate', :run, :now)",
            "ck_allomorph_form_or_zero",
        ),
        (
            "INSERT INTO allomorph (id, morpheme_id, form, is_zero, form_basis, conditioning, "
            "conditioning_note, status, run_id, created_at) VALUES (:allo_id, :morpheme, "
            "'variant', false, 'guessed', 'phonological', NULL, 'candidate', :run, :now)",
            "ck_allomorph_form_basis",
        ),
        (
            "INSERT INTO allomorph (id, morpheme_id, form, is_zero, form_basis, conditioning, "
            "conditioning_note, status, run_id, created_at) VALUES (:allo_id, :morpheme, "
            "'variant', false, 'surface', 'phonological', NULL, 'imagined', :run, :now)",
            "ck_allomorph_status",
        ),
        (
            "INSERT INTO allomorph (id, morpheme_id, form, is_zero, form_basis, conditioning, "
            "conditioning_note, status, run_id, created_at) VALUES ('allo_short', :morpheme, "
            "'probe-form', false, 'surface', 'phonological', NULL, 'candidate', :run, :now)",
            "ck_allomorph_id",
        ),
        (
            "INSERT INTO morph_analysis (id, target_token_id, analysis_kind, method, "
            "span_representation, surface, signature, abstention, status, score_breakdown, "
            "run_id, created_at) VALUES (:ma_id, :token, 'segmented', 'test-method', 'unparsed', "
            "'synthetic', :key3, NULL, 'candidate', NULL, :run, :now)",
            "ck_morph_analysis_span_representation",
        ),
        (
            "INSERT INTO morph_analysis (id, target_token_id, analysis_kind, method, "
            "span_representation, surface, signature, abstention, status, score_breakdown, "
            "run_id, created_at) VALUES (:ma_id, :token, 'partially_segmented', 'test-method', "
            "'raw', 'synthetic', :key3, NULL, 'candidate', NULL, :run, :now)",
            "ck_morph_analysis_analysis_kind",
        ),
        (
            "INSERT INTO morph_analysis (id, target_token_id, analysis_kind, method, "
            "span_representation, surface, signature, abstention, status, score_breakdown, "
            "run_id, created_at) VALUES (:ma_id, :token, 'segmented', 'test-method', 'raw', "
            "'synthetic', :key3, 'nobody_knows', 'candidate', NULL, :run, :now)",
            "ck_morph_analysis_abstention",
        ),
        (
            "INSERT INTO morph_analysis (id, target_token_id, analysis_kind, method, "
            "span_representation, surface, signature, abstention, status, score_breakdown, "
            "run_id, created_at) VALUES (:ma_id, :token, 'segmented', 'test-method', 'raw', "
            "'synthetic', :key3, NULL, 'imagined', NULL, :run, :now)",
            "ck_morph_analysis_status",
        ),
        (
            "INSERT INTO morph_analysis (id, target_token_id, analysis_kind, method, "
            "span_representation, surface, signature, abstention, status, score_breakdown, "
            "run_id, created_at) VALUES ('ma_short', :token, 'segmented', 'test-method', "
            "'raw', 'synthetic', :key3, NULL, 'candidate', NULL, :run, :now)",
            "ck_morph_analysis_id",
        ),
        (
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) VALUES "
            "(:mseg_id, :analysis, 2, 5, 4, true, 'synthetic', :morpheme, :allomorph, 'root', "
            "NULL, :now)",
            "ck_morph_segment_start_le_end",
        ),
        (
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) VALUES "
            "(:mseg_id, :analysis, 2, 4, 4, false, 'synthetic', :morpheme, :allomorph, 'root', "
            "NULL, :now)",
            "ck_morph_segment_span_or_zero",
        ),
        (
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) VALUES "
            "(:mseg_id, :analysis, 2, 0, 4, false, 'synthetic', NULL, :allomorph, 'root', "
            "NULL, :now)",
            "ck_morph_segment_allomorph_requires_morpheme",
        ),
        (
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) VALUES "
            "(:mseg_id, :analysis, 2, 0, 4, false, 'synthetic', :morpheme, NULL, 'suffix', "
            "NULL, :now)",
            "ck_morph_segment_role",
        ),
        (
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) VALUES "
            "(:mseg_id, :analysis, -1, 0, 4, false, 'synthetic', :morpheme, NULL, 'root', "
            "NULL, :now)",
            "ck_morph_segment_ordinal",
        ),
        (
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) VALUES "
            "('mseg_short', :analysis, 2, 0, 4, false, 'synthetic', :morpheme, NULL, 'root', "
            "NULL, :now)",
            "ck_morph_segment_id",
        ),
        (
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) VALUES "
            "(:mseg_id, :analysis, 2, -1, 4, false, 'synthetic', :morpheme, NULL, 'root', "
            "NULL, :now)",
            "ck_morph_segment_start",
        ),
        (
            # "end" < 0 with start >= 0 unavoidably co-violates ck_morph_segment_start_le_end;
            # PostgreSQL 16 tests CHECKs in alphabetical name order (CREATE TABLE docs);
            # ck_morph_segment_end precedes ck_morph_segment_start_le_end, so this is exact.
            'INSERT INTO morph_segment (id, analysis_id, ordinal, start, "end", is_zero, '
            "surface, morpheme_id, allomorph_id, role, source_gloss, created_at) VALUES "
            "(:mseg_id, :analysis, 2, 0, -1, false, 'synthetic', :morpheme, NULL, 'root', "
            "NULL, :now)",
            "ck_morph_segment_end",
        ),
        (
            "WITH fresh AS ("
            "INSERT INTO feature (id, namespace, label, definition, defined_by, run_id, "
            "created_at) VALUES (:feat_id, 'unimorph', 'Adj', 'adjective class', 'unimorph', "
            ":run, :now) RETURNING id) "
            "INSERT INTO morph_segment_feature (segment_id, feature_id, basis, created_at) "
            "SELECT :mseg, id, 'vibes', :now FROM fresh",
            "ck_morph_segment_feature_basis",
        ),
    ]
    params_base: dict[str, object] = {
        "source": ids["source"],
        "object": ids["source_object"],
        "run": ids["run"],
        "token": ids["token"],
        "morpheme": ids["morpheme"],
        "allomorph": ids["allomorph"],
        "analysis": ids["analysis"],
        "mseg": ids["mseg"],
        "feature": ids["feature"],
        # Distinct 64-char identity/signature values so no probe collides with the world
        # rows' natural keys: the only reason a probe may fail is the CHECK under test.
        "key2": "0123456789abcdef" * 4,
        "key3": "fedcba9876543210" * 4,
        "now": now,
    }
    for statement, check in cases:
        # Fresh ids per probe: a rejected INSERT consumes nothing, but the accepted world
        # rows must never collide with a probe's natural keys (uq_feature_namespace_label).
        params = {
            **params_base,
            "id": new_id(IdPrefix.SOURCE_USE_APPROVAL),
            "igt_id": new_id(IdPrefix.IGT_OBSERVATION),
            "feat_id": new_id(IdPrefix.FEATURE),
            "morph_id": new_id(IdPrefix.MORPHEME),
            "allo_id": new_id(IdPrefix.ALLOMORPH),
            "ma_id": new_id(IdPrefix.MORPH_ANALYSIS),
            "mseg_id": new_id(IdPrefix.MORPH_SEGMENT),
        }
        _expect_check_violation(migrated_engine, statement, params, check)
    # Coverage: every CHECK constraint the migration defines on the M5 tables must appear
    # in `cases` — a CHECK without rejection evidence fails this test.
    assert _m5_check_names(migrated_engine) == {check for _, check in cases}


def test_migration_0006_triggers_prevent_mutation(migrated_engine: Engine, clean_db: None) -> None:
    ids = _seed_m5_world(migrated_engine)
    with migrated_engine.connect() as conn:
        igt_id = conn.execute(
            text("SELECT id FROM igt_observation ORDER BY id LIMIT 1")
        ).scalar_one()
        msf = conn.execute(
            text("SELECT segment_id, feature_id FROM morph_segment_feature LIMIT 1")
        ).one()
    mutations: list[tuple[str, dict[str, object], str, str]] = [
        (
            "UPDATE source_use_approval SET basis = 'changed' WHERE id = :approval_id",
            {"approval_id": ids["approval"]},
            "source_use_approval",
            "SELECT * FROM source_use_approval WHERE id = :approval_id",
        ),
        (
            "UPDATE igt_observation SET parse_status = 'unparsed' WHERE id = :igt_id",
            {"igt_id": igt_id},
            "igt_observation",
            "SELECT * FROM igt_observation WHERE id = :igt_id",
        ),
        (
            "UPDATE feature SET definition = 'changed' WHERE id = :feature_id",
            {"feature_id": ids["feature"]},
            "feature",
            "SELECT * FROM feature WHERE id = :feature_id",
        ),
        (
            "UPDATE morph_segment SET surface = 'changed' WHERE id = :mseg_id",
            {"mseg_id": ids["mseg"]},
            "morph_segment",
            "SELECT * FROM morph_segment WHERE id = :mseg_id",
        ),
        (
            "UPDATE morph_segment_feature SET basis = 'adapter' "
            "WHERE segment_id = :sf_segment AND feature_id = :sf_feature",
            {"sf_segment": msf.segment_id, "sf_feature": msf.feature_id},
            "morph_segment_feature",
            "SELECT * FROM morph_segment_feature "
            "WHERE segment_id = :sf_segment AND feature_id = :sf_feature",
        ),
        (
            "DELETE FROM source_use_approval WHERE id = :approval_id",
            {"approval_id": ids["approval"]},
            "source_use_approval",
            "SELECT * FROM source_use_approval WHERE id = :approval_id",
        ),
        (
            "DELETE FROM igt_observation WHERE id = :igt_id",
            {"igt_id": igt_id},
            "igt_observation",
            "SELECT * FROM igt_observation WHERE id = :igt_id",
        ),
        (
            "DELETE FROM feature WHERE id = :feature_id",
            {"feature_id": ids["feature"]},
            "feature",
            "SELECT * FROM feature WHERE id = :feature_id",
        ),
        (
            "DELETE FROM morph_segment WHERE id = :mseg_id",
            {"mseg_id": ids["mseg"]},
            "morph_segment",
            "SELECT * FROM morph_segment WHERE id = :mseg_id",
        ),
        (
            "DELETE FROM morph_segment_feature "
            "WHERE segment_id = :sf_segment AND feature_id = :sf_feature",
            {"sf_segment": msf.segment_id, "sf_feature": msf.feature_id},
            "morph_segment_feature",
            "SELECT * FROM morph_segment_feature "
            "WHERE segment_id = :sf_segment AND feature_id = :sf_feature",
        ),
    ]
    for statement, params, table, probe in mutations:
        with migrated_engine.connect() as conn:
            before = conn.execute(text(probe), params).all()
        with pytest.raises(DBAPIError) as excinfo, migrated_engine.begin() as conn:
            nested = conn.begin_nested()
            try:
                conn.execute(text(statement), params)
            finally:
                nested.rollback()
        assert excinfo.value.orig is not None, table
        assert excinfo.value.orig.sqlstate == RESTRICT_VIOLATION, table
        assert "append-only" in str(excinfo.value.orig), table
        with migrated_engine.connect() as conn:
            after = conn.execute(text(probe), params).all()
        assert after == before, table


def _expect_hypothesis_guard_rejected(
    engine: Engine, statement: str, params: dict[str, object]
) -> None:
    with pytest.raises(DBAPIError) as excinfo, engine.begin() as conn:
        nested = conn.begin_nested()
        try:
            conn.execute(text(statement), params)
        finally:
            nested.rollback()
    assert excinfo.value.orig is not None
    assert excinfo.value.orig.sqlstate == RESTRICT_VIOLATION
    assert "hypothesis" in str(excinfo.value.orig)


def test_migration_0006_hypothesis_guard(migrated_engine: Engine, clean_db: None) -> None:
    ids = _seed_m5_world(migrated_engine)
    # Lifecycle promotion through status, with and without a score breakdown, is allowed.
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE morpheme SET status = 'supported', score_breakdown = :breakdown "
                "WHERE id = :id"
            ),
            {"breakdown": '{"overall": 0.5}', "id": ids["morpheme"]},
        )
        conn.execute(
            text("UPDATE allomorph SET status = 'rejected' WHERE id = :id"),
            {"id": ids["allomorph"]},
        )
        conn.execute(
            text("UPDATE morph_analysis SET status = 'supported' WHERE id = :id"),
            {"id": ids["analysis"]},
        )
    with migrated_engine.connect() as conn:
        breakdown = conn.execute(
            text("SELECT score_breakdown FROM morpheme WHERE id = :id"), {"id": ids["morpheme"]}
        ).scalar_one()
    assert breakdown == {"overall": 0.5}

    # Any other column change is refused — including `method` and `target_token_id`,
    # the identity columns of an analysis.
    _expect_hypothesis_guard_rejected(
        migrated_engine,
        "UPDATE morpheme SET canonical_form = 'changed' WHERE id = :id",
        {"id": ids["morpheme"]},
    )
    _expect_hypothesis_guard_rejected(
        migrated_engine,
        "UPDATE allomorph SET form = 'changed' WHERE id = :id",
        {"id": ids["allomorph"]},
    )
    _expect_hypothesis_guard_rejected(
        migrated_engine,
        "UPDATE morph_analysis SET method = 'changed' WHERE id = :id",
        {"id": ids["analysis"]},
    )
    _expect_hypothesis_guard_rejected(
        migrated_engine,
        "UPDATE morph_analysis SET target_token_id = :other WHERE id = :id",
        {"id": ids["analysis"], "other": ids["token2"]},
    )

    # Deletion is refused on every hypothesis table.
    for statement, params in (
        ("DELETE FROM morpheme WHERE id = :id", {"id": ids["morpheme"]}),
        ("DELETE FROM allomorph WHERE id = :id", {"id": ids["allomorph"]}),
        ("DELETE FROM morph_analysis WHERE id = :id", {"id": ids["analysis"]}),
    ):
        _expect_hypothesis_guard_rejected(migrated_engine, statement, params)


def test_migration_0006_empty_downgrade_succeeds(
    migrated_engine: Engine, clean_db: None, pg_url: str
) -> None:
    # After the refusal tests' rows are gone the downgrade must go through: the refusal
    # logic cannot have latched onto anything but real rows.
    config = alembic_config(pg_url)
    command.downgrade(config, M4_HEAD)
    assert not set(M5_TABLES) & _public_tables(migrated_engine)
    command.upgrade(config, M5_HEAD)
    assert set(M5_TABLES) <= _public_tables(migrated_engine)
