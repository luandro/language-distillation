"""M3 parallel alignment evidence: segment groups, members and token edges (ADR-0011).

Revision ID: 0003_m3_alignment
Revises: 0002_m2_text_processing
Create Date: 2026-10-13

M3-PLAN §5.3/§5.4. Enum value tuples are literal copies of the domain enums; the migration
never imports application code. Append-only triggers reuse langpipe_forbid_mutation from 0001.

Selected-run contract: a producing run's config.sides is a JSON array of exactly two ordered
side descriptors {role, source_id, language, normalization_run_id, tokenization_run_id} —
roles source then target, registered sources, nonempty distinct languages; pinned runs must
be succeeded runs of the matching stage; Stage 4 leaves tokenization_run_id null while
Stage 5 requires it. Missing or malformed selection metadata fails closed.

DEFERRABLE constraint triggers validate at transaction end so a parent row may precede its
members. The group guard (parent INSERT) and the member guard (member INSERT, resolving the
parent through NEW.alignment_id) both revalidate the whole group: producing-run stage, side
descriptors, both sides nonempty, contiguous zero-based positions, and membership in the
selected normalization run and side language. The member guard additionally rejects any
INSERT whose parent row belongs to an earlier top-level transaction. Ownership is tracked by
segment_alignment.creating_txid, an internal DB-owned marker: a BEFORE INSERT trigger stamps
it with txid_current(), the full epoch-aware 64-bit top-level transaction identity, which is
constant across savepoints/subtransactions. The member guard compares the marker with
txid_current(): membership may be assembled anywhere within the creating transaction —
including inside released savepoints — while any later transaction, even after xid
wraparound, holds a different identity and fails closed, because published membership is
immutable and a later transaction cannot append even a valid-looking member the group's
committed lineage/run outputs never described. The marker is storage-internal bookkeeping,
not domain metadata: clients cannot set it (the stamp trigger overwrites any supplied value)
or change it later (the append-only trigger forbids UPDATE). The parent row is locked
FOR UPDATE during validation, so concurrent membership writes serialize on the group. The
edge guard verifies the token_alignment producing run, the side descriptors with pinned
tokenization runs, endpoint membership in the group sides, and endpoint membership in the
selected tokenization runs. CHECK constraints reject non-finite scores and invalid
status/direction combinations immediately. Downgrade refuses when any M3 rows or registry
entries survive; the checks run before any DDL, so a refusal is transactional and preserves
the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_m3_alignment"
down_revision: str | None = "0002_m2_text_processing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY_TYPES_M1 = (
    "source",
    "source_object",
    "processing_run",
    "artifact",
    "segment",
    "token_occurrence",
    "form",
    "evidence_item",
)
_ENTITY_TYPES_M3_ADDED = ("segment_alignment", "token_alignment_edge")
_ENTITY_TYPES = _ENTITY_TYPES_M1 + _ENTITY_TYPES_M3_ADDED
_ENTITY_TYPE_CHECK = "ck_object_registry_entity_type"

_ALIGNMENT_MODES = ("canonical", "heuristic", "experimental")
_ALIGNMENT_STATUSES = ("structural", "inferred", "candidate", "approved", "rejected")
_ALIGNMENT_DIRECTIONS = ("forward", "reverse", "symmetrized")
_SYMMETRIZATIONS = ("none", "intersection", "union")

_ID_PATTERN = "^{prefix}_[0-9A-HJKMNP-TV-Z]{{26}}$"

_APPEND_ONLY_TABLES = (
    "segment_alignment",
    "segment_alignment_member",
    "token_alignment_edge",
)

# NaN compares equal to itself in PostgreSQL, so <> rejects it alongside the infinities.
_FINITE_SCORE = (
    "{column} IS NULL OR ({column} <> 'NaN'::double precision "
    "AND {column} <> 'Infinity'::double precision "
    "AND {column} <> '-Infinity'::double precision)"
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _id_check(table: str, prefix: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"id ~ '{_ID_PATTERN.format(prefix=prefix)}'", name=f"ck_{table}_id")


def _enum_check(table: str, column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({_in_list(values)})", name=f"ck_{table}_{column}")


def _finite_score_check(table: str) -> sa.CheckConstraint:
    expression = _FINITE_SCORE.format(column="score")
    return sa.CheckConstraint(expression, name=f"ck_{table}_score_finite")


def _replace_entity_type_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(_ENTITY_TYPE_CHECK, "object_registry", type_="check")
    op.create_check_constraint(
        _ENTITY_TYPE_CHECK, "object_registry", f"entity_type IN ({_in_list(values)})"
    )


def _create_tables() -> None:
    op.create_table(
        "segment_alignment",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "raw_scores",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("group_key", sa.CHAR(64), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("authorization_basis_id", sa.Text(), sa.ForeignKey("artifact.id"), nullable=True),
        sa.Column("supersedes_id", sa.Text(), sa.ForeignKey("segment_alignment.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # DB-owned publication marker (see module docstring): stamped by
        # trg_segment_alignment_stamp_creation, read by the member guard. Not domain metadata.
        sa.Column("creating_txid", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("run_id", "group_key", name="uq_segment_alignment_run_group_key"),
        _id_check("segment_alignment", "sal"),
        _enum_check("segment_alignment", "mode", _ALIGNMENT_MODES),
        _enum_check("segment_alignment", "status", _ALIGNMENT_STATUSES),
        _finite_score_check("segment_alignment"),
        sa.CheckConstraint(
            "(status IN ('approved', 'rejected') "
            "AND authorization_basis_id IS NOT NULL AND supersedes_id IS NOT NULL) "
            "OR (status NOT IN ('approved', 'rejected') "
            "AND authorization_basis_id IS NULL AND supersedes_id IS NULL)",
            name="ck_segment_alignment_disposition_pair",
        ),
    )
    op.create_table(
        "segment_alignment_member",
        sa.Column(
            "alignment_id", sa.Text(), sa.ForeignKey("segment_alignment.id"), primary_key=True
        ),
        sa.Column("side", sa.Text(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("segment_id", sa.Text(), sa.ForeignKey("segment.id"), nullable=False),
        sa.CheckConstraint("side IN ('source', 'target')", name="ck_segment_alignment_member_side"),
        sa.CheckConstraint("position >= 0", name="ck_segment_alignment_member_position"),
        sa.UniqueConstraint(
            "alignment_id", "segment_id", name="uq_segment_alignment_member_alignment_segment"
        ),
    )
    op.create_index(
        "ix_segment_alignment_member_segment_id", "segment_alignment_member", ["segment_id"]
    )
    op.create_table(
        "token_alignment_edge",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column(
            "segment_alignment_id",
            sa.Text(),
            sa.ForeignKey("segment_alignment.id"),
            nullable=False,
        ),
        sa.Column(
            "source_token_id", sa.Text(), sa.ForeignKey("token_occurrence.id"), nullable=False
        ),
        sa.Column(
            "target_token_id", sa.Text(), sa.ForeignKey("token_occurrence.id"), nullable=False
        ),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "raw_scores",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("symmetrization", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "segment_alignment_id",
            "source_token_id",
            "target_token_id",
            "direction",
            "symmetrization",
            name="uq_token_alignment_edge_natural_key",
        ),
        _id_check("token_alignment_edge", "tal"),
        _enum_check("token_alignment_edge", "direction", _ALIGNMENT_DIRECTIONS),
        _enum_check("token_alignment_edge", "symmetrization", _SYMMETRIZATIONS),
        _finite_score_check("token_alignment_edge"),
        sa.CheckConstraint(
            "(direction = 'symmetrized' AND symmetrization IN ('intersection', 'union')) "
            "OR (direction IN ('forward', 'reverse') AND symmetrization = 'none')",
            name="ck_token_alignment_edge_direction_symmetrization",
        ),
    )
    op.create_index("ix_token_alignment_edge_run_id", "token_alignment_edge", ["run_id"])
    op.create_index(
        "ix_token_alignment_edge_segment_alignment_id",
        "token_alignment_edge",
        ["segment_alignment_id"],
    )
    op.create_index(
        "ix_token_alignment_edge_source_token_id", "token_alignment_edge", ["source_token_id"]
    )
    op.create_index(
        "ix_token_alignment_edge_target_token_id", "token_alignment_edge", ["target_token_id"]
    )


def _create_functions() -> None:
    # Shared selected-run contract validation (M3-PLAN §5.4, ADR-0011 §4/§5). Returns the
    # validated two-element side array so callers can enforce per-side membership.
    op.execute(
        """
        CREATE FUNCTION langpipe_alignment_selected_sides(
            p_cfg jsonb, p_require_tokenization boolean
        ) RETURNS jsonb
        LANGUAGE plpgsql AS $$
        DECLARE
            sides jsonb;
            side jsonb;
            label text;
            i int;
            pin_stage text;
            pin_status text;
        BEGIN
            IF p_cfg IS NULL OR jsonb_typeof(p_cfg -> 'sides') IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION
                    'alignment run config must record ordered source and target side descriptors'
                    USING ERRCODE = 'check_violation';
            END IF;
            sides := p_cfg -> 'sides';
            IF jsonb_array_length(sides) <> 2 THEN
                RAISE EXCEPTION
                    'alignment run config must record ordered source and target side descriptors'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF sides -> 0 ->> 'role' IS DISTINCT FROM 'source'
               OR sides -> 1 ->> 'role' IS DISTINCT FROM 'target' THEN
                RAISE EXCEPTION 'side descriptors must be ordered source then target'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF btrim(coalesce(sides -> 0 ->> 'language', '')) = ''
               OR btrim(coalesce(sides -> 1 ->> 'language', '')) = '' THEN
                RAISE EXCEPTION 'each side descriptor must record a nonempty language'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF sides -> 0 ->> 'language' = sides -> 1 ->> 'language' THEN
                RAISE EXCEPTION 'alignment sides must have distinct languages'
                    USING ERRCODE = 'check_violation';
            END IF;
            FOR i IN 0..1 LOOP
                side := sides -> i;
                label := CASE WHEN i = 0 THEN 'source' ELSE 'target' END;
                IF NOT EXISTS (SELECT 1 FROM source WHERE id = side ->> 'source_id') THEN
                    RAISE EXCEPTION '% side descriptor must reference a registered source',
                        label USING ERRCODE = 'check_violation';
                END IF;
                SELECT stage, status INTO pin_stage, pin_status
                  FROM processing_run WHERE id = side ->> 'normalization_run_id';
                IF pin_stage IS DISTINCT FROM 'normalization'
                   OR pin_status IS DISTINCT FROM 'succeeded' THEN
                    RAISE EXCEPTION
                        '% side normalization_run_id must be a succeeded normalization-stage run',
                        label USING ERRCODE = 'check_violation';
                END IF;
                IF p_require_tokenization OR side ->> 'tokenization_run_id' IS NOT NULL THEN
                    SELECT stage, status INTO pin_stage, pin_status
                      FROM processing_run WHERE id = side ->> 'tokenization_run_id';
                    IF pin_stage IS DISTINCT FROM 'tokenization'
                       OR pin_status IS DISTINCT FROM 'succeeded' THEN
                        RAISE EXCEPTION
                            '% side tokenization_run_id must be a succeeded tokenization-stage run',
                            label USING ERRCODE = 'check_violation';
                    END IF;
                END IF;
            END LOOP;
            RETURN sides;
        END;
        $$
        """
    )
    # Whole-group validation shared by the parent and member guards.
    op.execute(
        """
        CREATE FUNCTION langpipe_validate_segment_alignment_group(p_alignment_id text)
        RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            run_stage text;
            cfg jsonb;
            sides jsonb;
            side jsonb;
            label text;
            norm_run text;
            side_lang text;
            i int;
            member_count integer;
            min_position integer;
            max_position integer;
            mismatched integer;
        BEGIN
            -- Lock the parent row so concurrent membership writes serialize on the group.
            SELECT r.stage, r.config INTO run_stage, cfg
              FROM segment_alignment a
              JOIN processing_run r ON r.id = a.run_id
             WHERE a.id = p_alignment_id
               FOR UPDATE OF a;

            IF run_stage IS DISTINCT FROM 'segment_alignment' THEN
                RAISE EXCEPTION
                    'segment_alignment requires a segment_alignment-stage producing run'
                    USING ERRCODE = 'check_violation';
            END IF;

            sides := langpipe_alignment_selected_sides(cfg, false);

            FOR i IN 0..1 LOOP
                side := sides -> i;
                label := CASE WHEN i = 0 THEN 'source' ELSE 'target' END;
                norm_run := side ->> 'normalization_run_id';
                side_lang := side ->> 'language';

                SELECT count(*), min(m.position), max(m.position),
                       count(*) FILTER (
                           WHERE s.run_id <> norm_run OR s.language::text <> side_lang
                       )
                  INTO member_count, min_position, max_position, mismatched
                  FROM segment_alignment_member m
                  JOIN segment s ON s.id = m.segment_id
                 WHERE m.alignment_id = p_alignment_id AND m.side = label;

                IF member_count = 0 THEN
                    RAISE EXCEPTION 'segment_alignment requires at least one %-side member',
                        label USING ERRCODE = 'check_violation';
                END IF;
                IF min_position <> 0 OR max_position <> member_count - 1 THEN
                    RAISE EXCEPTION '%-side member positions must be contiguous and zero-based',
                        label USING ERRCODE = 'check_violation';
                END IF;
                IF mismatched <> 0 THEN
                    RAISE EXCEPTION
                        '%-side members must match the selected normalization run and language',
                        label USING ERRCODE = 'check_violation';
                END IF;
            END LOOP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION langpipe_segment_alignment_stamp_creation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- DB-owned marker: overwrite any client-supplied value. txid_current() is the
            -- full epoch-aware 64-bit top-level transaction id, constant across savepoints,
            -- so wraparound cannot alias a later transaction with the creating one.
            NEW.creating_txid := txid_current();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION langpipe_segment_alignment_group_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM langpipe_validate_segment_alignment_group(NEW.id);
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION langpipe_segment_alignment_member_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            parent_txid bigint;
        BEGIN
            PERFORM langpipe_validate_segment_alignment_group(NEW.alignment_id);
            -- Publication immutability: the group's committed lineage and run outputs
            -- describe exactly the membership of its creating top-level transaction.
            -- creating_txid is stamped at parent INSERT with the epoch-aware top-level
            -- identity, which is identical inside every savepoint of that transaction;
            -- a later transaction always observes a different identity and fails closed.
            SELECT creating_txid INTO parent_txid
              FROM segment_alignment WHERE id = NEW.alignment_id;
            IF parent_txid IS DISTINCT FROM txid_current() THEN
                RAISE EXCEPTION 'published segment_alignment membership is immutable'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION langpipe_token_alignment_edge_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            run_stage text;
            cfg jsonb;
            sides jsonb;
            token_run text;
        BEGIN
            SELECT stage, config INTO run_stage, cfg FROM processing_run WHERE id = NEW.run_id;
            IF run_stage IS DISTINCT FROM 'token_alignment' THEN
                RAISE EXCEPTION
                    'token_alignment_edge requires a token_alignment-stage producing run'
                    USING ERRCODE = 'check_violation';
            END IF;

            sides := langpipe_alignment_selected_sides(cfg, true);

            IF NOT EXISTS (
                SELECT 1
                FROM token_occurrence t
                JOIN segment_alignment_member m ON m.segment_id = t.segment_id
                WHERE t.id = NEW.source_token_id
                  AND m.alignment_id = NEW.segment_alignment_id
                  AND m.side = 'source'
            ) THEN
                RAISE EXCEPTION 'source token does not belong to the group source side'
                    USING ERRCODE = 'check_violation';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM token_occurrence t
                JOIN segment_alignment_member m ON m.segment_id = t.segment_id
                WHERE t.id = NEW.target_token_id
                  AND m.alignment_id = NEW.segment_alignment_id
                  AND m.side = 'target'
            ) THEN
                RAISE EXCEPTION 'target token does not belong to the group target side'
                    USING ERRCODE = 'check_violation';
            END IF;

            SELECT run_id INTO token_run FROM token_occurrence WHERE id = NEW.source_token_id;
            IF token_run IS DISTINCT FROM sides -> 0 ->> 'tokenization_run_id' THEN
                RAISE EXCEPTION 'source token must belong to the selected source tokenization run'
                    USING ERRCODE = 'check_violation';
            END IF;
            SELECT run_id INTO token_run FROM token_occurrence WHERE id = NEW.target_token_id;
            IF token_run IS DISTINCT FROM sides -> 1 ->> 'tokenization_run_id' THEN
                RAISE EXCEPTION 'target token must belong to the selected target tokenization run'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )


def _create_triggers() -> None:
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_forbid_mutation BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION langpipe_forbid_mutation()"
        )
    op.execute(
        "CREATE TRIGGER trg_segment_alignment_stamp_creation "
        "BEFORE INSERT ON segment_alignment "
        "FOR EACH ROW EXECUTE FUNCTION langpipe_segment_alignment_stamp_creation()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_segment_alignment_group_guard "
        "AFTER INSERT ON segment_alignment "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION langpipe_segment_alignment_group_guard()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_segment_alignment_member_guard "
        "AFTER INSERT ON segment_alignment_member "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION langpipe_segment_alignment_member_guard()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_token_alignment_edge_guard "
        "AFTER INSERT ON token_alignment_edge "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION langpipe_token_alignment_edge_guard()"
    )


def upgrade() -> None:
    _create_tables()
    _replace_entity_type_check(_ENTITY_TYPES)
    _create_functions()
    _create_triggers()


def downgrade() -> None:
    bind = op.get_bind()
    for table in _APPEND_ONLY_TABLES:
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(f"downgrade 0003 refused: {count} rows survive in {table}")
    # Registry entries alone also block the downgrade: processing_run_io and lineage_edge
    # rows foreign-key object_registry, so none can reference an M3 object without one of
    # these entries (ADR-0011 §8).
    count = bind.execute(
        sa.text(
            "SELECT count(*) FROM object_registry "
            f"WHERE entity_type IN ({_in_list(_ENTITY_TYPES_M3_ADDED)})"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(f"downgrade 0003 refused: {count} M3 registry entries survive")
    op.execute("DROP TRIGGER IF EXISTS trg_token_alignment_edge_guard ON token_alignment_edge")
    op.execute("DROP TRIGGER IF EXISTS trg_segment_alignment_group_guard ON segment_alignment")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_segment_alignment_member_guard ON segment_alignment_member"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_segment_alignment_stamp_creation ON segment_alignment")
    for table in _APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_forbid_mutation ON {table}")
    op.drop_table("token_alignment_edge")
    op.drop_table("segment_alignment_member")
    op.drop_table("segment_alignment")
    op.execute("DROP FUNCTION IF EXISTS langpipe_segment_alignment_stamp_creation()")
    op.execute("DROP FUNCTION IF EXISTS langpipe_token_alignment_edge_guard()")
    op.execute("DROP FUNCTION IF EXISTS langpipe_segment_alignment_member_guard()")
    op.execute("DROP FUNCTION IF EXISTS langpipe_segment_alignment_group_guard()")
    op.execute("DROP FUNCTION IF EXISTS langpipe_validate_segment_alignment_group(text)")
    op.execute("DROP FUNCTION IF EXISTS langpipe_alignment_selected_sides(jsonb, boolean)")
    _replace_entity_type_check(_ENTITY_TYPES_M1)
