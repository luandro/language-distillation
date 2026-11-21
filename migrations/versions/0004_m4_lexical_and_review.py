"""M4 lexical evidence: concepts, lexemes, form links, senses and the review queue (ADR-0013).

Revision ID: 0004_m4_lexical_and_review
Revises: 0003_m3_alignment
Create Date: 2026-10-16

M4-PLAN §WP4.2. Enum value tuples are literal copies of the domain enums; the migration
never imports application code. Append-only triggers reuse langpipe_forbid_mutation from 0001.

Domain semantics enforced here are structural only. Lexemes and senses are hypotheses
(Invariant 2): the lifecycle CHECK admits `validated`, but nothing in this schema can set
it — only an authorized human ReviewDecision may do so at the service layer (Invariant 3).
`form_lexeme` and `review_decision` are append-only: an INSERT is the only permitted write,
so a changed opinion records a new decision and never edits one (ADR-0013 §5). `concept`
is local by default (`concept_type='local'`) with optional external mappings
(`concepticon_id`, `external_urn`). `concept_type` is an open, nonempty string: the
approved domain contract (`Concept.concept_type`) accepts any text, and neither ADR-0013
nor DOMAIN-MODEL declares an exhaustive vocabulary, so no CHECK narrows it here — only
the `local` server default is fixed.

Downgrade refuses when any M4 row or any object_registry entry of an M4 entity type
survives: lineage_edge and evidence_item rows foreign-key object_registry, so none can
reference an M4 object without one of these entries. The checks run before any DDL, so a
refusal is transactional and preserves the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_m4_lexical_and_review"
down_revision: str | None = "0003_m3_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY_TYPES_M3 = (
    "source",
    "source_object",
    "processing_run",
    "artifact",
    "segment",
    "token_occurrence",
    "form",
    "evidence_item",
    "segment_alignment",
    "token_alignment_edge",
)
_ENTITY_TYPES_M4_ADDED = (
    "concept",
    "lexeme",
    "form_lexeme",
    "sense",
    "review_task",
    "review_decision",
)
_ENTITY_TYPES = _ENTITY_TYPES_M3 + _ENTITY_TYPES_M4_ADDED
_ENTITY_TYPE_CHECK = "ck_object_registry_entity_type"

_LIFECYCLE_STATUSES = ("candidate", "supported", "validated", "rejected", "deprecated")
_TASK_TYPES = (
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
_REVIEW_TASK_STATUSES = ("open", "in_review", "resolved", "cancelled")
_REVIEW_DECISIONS = ("accept", "reject", "modify", "uncertain", "defer")

_ID_PATTERN = "^{prefix}_[0-9A-HJKMNP-TV-Z]{{26}}$"

# Append-only tables: an INSERT is the only permitted write (ADR-0013 §1/§5).
_APPEND_ONLY_TABLES = ("form_lexeme", "review_decision")

_M4_TABLES = (
    "concept",
    "lexeme",
    "form_lexeme",
    "sense",
    "review_task",
    "review_decision",
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _id_check(table: str, prefix: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"id ~ '{_ID_PATTERN.format(prefix=prefix)}'", name=f"ck_{table}_id")


def _enum_check(table: str, column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({_in_list(values)})", name=f"ck_{table}_{column}")


def _replace_entity_type_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(_ENTITY_TYPE_CHECK, "object_registry", type_="check")
    op.create_check_constraint(
        _ENTITY_TYPE_CHECK, "object_registry", f"entity_type IN ({_in_list(values)})"
    )


def _create_tables() -> None:
    op.create_table(
        "concept",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("concept_type", sa.Text(), nullable=False, server_default=sa.text("'local'")),
        sa.Column("canonical_label", sa.Text(), nullable=False),
        sa.Column("concepticon_id", sa.Text(), nullable=True),
        sa.Column("external_urn", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("concept", "cpt"),
    )
    op.create_table(
        "lexeme",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("lemma_form_id", sa.Text(), sa.ForeignKey("form.id"), nullable=True),
        sa.Column("pos", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("register", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("lexeme", "lex"),
        _enum_check("lexeme", "status", _LIFECYCLE_STATUSES),
    )
    op.create_index("ix_lexeme_language", "lexeme", ["language"])
    op.create_index("ix_lexeme_lemma_form_id", "lexeme", ["lemma_form_id"])
    op.create_table(
        "form_lexeme",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("form_id", sa.Text(), sa.ForeignKey("form.id"), nullable=False),
        sa.Column("lexeme_id", sa.Text(), sa.ForeignKey("lexeme.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("form_id", "lexeme_id", name="ux_form_lexeme_pair"),
        _id_check("form_lexeme", "flx"),
    )
    op.create_index("ix_form_lexeme_form_id", "form_lexeme", ["form_id"])
    op.create_index("ix_form_lexeme_lexeme_id", "form_lexeme", ["lexeme_id"])
    op.create_table(
        "sense",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("lexeme_id", sa.Text(), sa.ForeignKey("lexeme.id"), nullable=False),
        sa.Column(
            "glosses",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("concept_id", sa.Text(), sa.ForeignKey("concept.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("register", sa.Text(), nullable=True),
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("sense", "sense"),
        _enum_check("sense", "status", _LIFECYCLE_STATUSES),
    )
    op.create_index("ix_sense_lexeme_id", "sense", ["lexeme_id"])
    op.create_index("ix_sense_concept_id", "sense", ["concept_id"])
    op.create_table(
        "review_task",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), sa.ForeignKey("object_registry.id"), nullable=False),
        sa.Column("target_version", sa.Text(), nullable=True),
        sa.Column(
            "evidence_item_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("required_role", sa.Text(), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("creator_run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("review_task", "rtask"),
        _enum_check("review_task", "task_type", _TASK_TYPES),
        _enum_check("review_task", "status", _REVIEW_TASK_STATUSES),
    )
    op.create_index("ix_review_task_status_priority", "review_task", ["status", "priority"])
    op.create_index("ix_review_task_target_id", "review_task", ["target_id"])
    op.create_table(
        "review_decision",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("review_task.id"), nullable=False),
        sa.Column("target_id", sa.Text(), sa.ForeignKey("object_registry.id"), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Text(), nullable=False),
        sa.Column("reviewer_role", sa.Text(), nullable=False),
        sa.Column(
            "superseding_object_id",
            sa.Text(),
            sa.ForeignKey("object_registry.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("review_decision", "rdec"),
        _enum_check("review_decision", "decision", _REVIEW_DECISIONS),
    )
    op.create_index("ix_review_decision_task_id", "review_decision", ["task_id"])
    op.create_index("ix_review_decision_target_id", "review_decision", ["target_id"])


def _create_triggers() -> None:
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_forbid_mutation BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION langpipe_forbid_mutation()"
        )


def upgrade() -> None:
    _create_tables()
    _replace_entity_type_check(_ENTITY_TYPES)
    _create_triggers()


def downgrade() -> None:
    bind = op.get_bind()
    # Refusal runs before any DDL and is transactional: a refusal leaves the M4 schema and
    # every row in place (ADR-0013 §1/§5, M4-PLAN §WP4.2).
    for table in _M4_TABLES:
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(f"downgrade 0004 refused: {count} rows survive in {table}")
    # Registry entries alone also block the downgrade: lineage_edge and evidence_item rows
    # foreign-key object_registry, so none can reference an M4 object without one of these.
    count = bind.execute(
        sa.text(
            "SELECT count(*) FROM object_registry "
            f"WHERE entity_type IN ({_in_list(_ENTITY_TYPES_M4_ADDED)})"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(f"downgrade 0004 refused: {count} M4 registry entries survive")
    for table in _APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_forbid_mutation ON {table}")
    op.drop_table("review_decision")
    op.drop_table("review_task")
    op.drop_table("sense")
    op.drop_table("form_lexeme")
    op.drop_table("lexeme")
    op.drop_table("concept")
    _replace_entity_type_check(_ENTITY_TYPES_M3)
