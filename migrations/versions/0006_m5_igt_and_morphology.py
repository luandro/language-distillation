"""M5 IGT observation and morphology graph: tables, triggers, extended vocabularies.

Revision ID: 0006_m5_igt_and_morphology
Revises: 0005_review_stale_dependent
Create Date: 2026-10-16

ADR-0017/ADR-0018. IGT observations and morph segments are immutable observations
(append-only triggers); morphemes, allomorphs and analyses are hypotheses whose rows may
change only `status` and `score_breakdown` (`langpipe_hypothesis_guard`, same
`to_jsonb(NEW) - ... IS DISTINCT FROM` pattern as `langpipe_source_guard`). Enum value
tuples are literal copies of the domain enums; the migration never imports application
code (0004 pattern). The object_registry, lineage_edge and audit_event CHECK vocabularies
are replaced in place with the extended lists.

Downgrade refuses, before any DDL, while any M5 row, any object_registry entry of an M5
entity type, any `recalculated` lineage edge or any M5 audit event survives. The refusal
is transactional, so it leaves the schema and every row in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_m5_igt_and_morphology"
down_revision: str | None = "0005_review_stale_dependent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY_TYPES_M4 = (
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
    "concept",
    "lexeme",
    "form_lexeme",
    "sense",
    "review_task",
    "review_decision",
)
_ENTITY_TYPES_M5_ADDED = (
    "igt_observation",
    "feature",
    "morpheme",
    "allomorph",
    "morph_analysis",
    "morph_segment",
    "source_use_approval",
)
_ENTITY_TYPES = _ENTITY_TYPES_M4 + _ENTITY_TYPES_M5_ADDED
_ENTITY_TYPE_CHECK = "ck_object_registry_entity_type"

_KINDS_0005 = (
    "derived_from",
    "generated_from",
    "normalized_from",
    "extracted_from",
    "imported_from",
    "supersedes",
    "stale_dependent",
)
_KINDS_0006 = (*_KINDS_0005, "recalculated")

_AUDIT_EVENT_TYPES_0001 = ("policy_created", "source_registered", "raw_ingested", "policy_denied")
_M5_AUDIT_EVENT_TYPES_ADDED = ("source_use_approved", "source_use_withdrawn")
_AUDIT_EVENT_TYPES_0006 = (*_AUDIT_EVENT_TYPES_0001, *_M5_AUDIT_EVENT_TYPES_ADDED)

_APPROVABLE_OPERATIONS = (
    "read_raw",
    "extract",
    "normalize",
    "align",
    "distill_lexicon",
    "distill_morphology",
    "distill_grammar",
    "evaluation",
)
_APPROVAL_ACTIONS = ("grant", "withdraw")
_IGT_FORMATS = ("toolbox", "xigt")
_IGT_PARSE_STATUSES = ("ok", "tier_mismatch", "missing_tier", "unparsed")
_MORPH_ROLES = (
    "root",
    "lexical_stem",
    "derivational_affix",
    "inflectional_affix",
    "clitic",
    "reduplicant",
    "bound_lexical",
    "unknown_bound",
    "unknown",
)
_FORM_BASES = ("surface", "underlying")
_ALLOMORPH_CONDITIONINGS = ("phonological", "morphosyntactic", "lexical", "unknown")
_ANALYSIS_KINDS = ("segmented", "unsegmented")
_SPAN_REPRESENTATIONS = ("raw", "normalized")
_ABSTENTIONS = (
    "insufficient_evidence",
    "conflicting_evidence",
    "unsupported_language_or_domain",
    "human_review",
)
_FEATURE_BASES = ("igt_gloss", "adapter")
_LIFECYCLE_STATUSES = ("candidate", "supported", "validated", "rejected", "deprecated")

_ID_PATTERN = "^{prefix}_[0-9A-HJKMNP-TV-Z]{{26}}$"

_M5_TABLES = (
    "source_use_approval",
    "igt_observation",
    "feature",
    "morpheme",
    "allomorph",
    "morph_analysis",
    "morph_segment",
    "morph_segment_feature",
)
_APPEND_ONLY_TABLES = (
    "source_use_approval",
    "igt_observation",
    "feature",
    "morph_segment",
    "morph_segment_feature",
)
_HYPOTHESIS_TABLES = ("morpheme", "allomorph", "morph_analysis")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _id_check(table: str, prefix: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"id ~ '{_ID_PATTERN.format(prefix=prefix)}'", name=f"ck_{table}_id")


def _enum_check(table: str, column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({_in_list(values)})", name=f"ck_{table}_{column}")


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, expression)


def _replace_entity_type_check(values: tuple[str, ...]) -> None:
    _replace_check("object_registry", _ENTITY_TYPE_CHECK, f"entity_type IN ({_in_list(values)})")


def _jsonb_default(literal: str) -> sa.TextClause:
    return sa.text(f"'{literal}'::jsonb")


def _create_tables() -> None:
    op.create_table(
        "source_use_approval",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("approver_id", sa.Text(), nullable=False),
        sa.Column("approver_role", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("source_use_approval", "sua"),
        _enum_check("source_use_approval", "operation", _APPROVABLE_OPERATIONS),
        _enum_check("source_use_approval", "action", _APPROVAL_ACTIONS),
        sa.CheckConstraint(
            "length(trim(approver_id)) > 0", name="ck_source_use_approval_approver_id"
        ),
        sa.CheckConstraint(
            "length(trim(approver_role)) > 0", name="ck_source_use_approval_approver_role"
        ),
        sa.CheckConstraint("length(trim(basis)) > 0", name="ck_source_use_approval_basis"),
    )
    op.create_index(
        "ix_source_use_approval_source_op_created",
        "source_use_approval",
        ["source_id", "operation", "created_at"],
    )
    op.create_table(
        "igt_observation",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("source_object_id", sa.Text(), sa.ForeignKey("source_object.id"), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("segment_id", sa.Text(), sa.ForeignKey("segment.id"), nullable=True),
        sa.Column("record_ordinal", sa.Integer(), nullable=False),
        sa.Column("record_ref", sa.Text(), nullable=True),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column(
            "locator", postgresql.JSONB(), nullable=False, server_default=_jsonb_default("{}")
        ),
        sa.Column("tiers", postgresql.JSONB(), nullable=False, server_default=_jsonb_default("[]")),
        sa.Column("words", postgresql.JSONB(), nullable=False, server_default=_jsonb_default("[]")),
        sa.Column(
            "translations", postgresql.JSONB(), nullable=False, server_default=_jsonb_default("{}")
        ),
        sa.Column("parse_status", sa.Text(), nullable=False),
        sa.Column(
            "diagnostics", postgresql.JSONB(), nullable=False, server_default=_jsonb_default("[]")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("igt_observation", "igt"),
        _enum_check("igt_observation", "format", _IGT_FORMATS),
        _enum_check("igt_observation", "parse_status", _IGT_PARSE_STATUSES),
        sa.CheckConstraint("record_ordinal >= 0", name="ck_igt_observation_record_ordinal"),
        sa.UniqueConstraint(
            "run_id", "source_object_id", "record_ordinal", name="uq_igt_observation_record"
        ),
    )
    op.create_index("ix_igt_observation_source_id", "igt_observation", ["source_id"])
    op.create_index("ix_igt_observation_segment_id", "igt_observation", ["segment_id"])
    op.create_table(
        "feature",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("defined_by", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("feature", "feat"),
        sa.CheckConstraint(
            "namespace ~ '^(unimorph|ud|local:[a-z]{3})$'", name="ck_feature_namespace"
        ),
        sa.CheckConstraint("length(trim(label)) > 0", name="ck_feature_label"),
        sa.CheckConstraint("length(trim(definition)) > 0", name="ck_feature_definition"),
        sa.UniqueConstraint("namespace", "label", name="uq_feature_namespace_label"),
    )
    op.create_table(
        "morpheme",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("canonical_form", sa.Text(), nullable=True),
        sa.Column("form_basis", sa.Text(), nullable=False),
        sa.Column(
            "glosses", postgresql.JSONB(), nullable=False, server_default=_jsonb_default("{}")
        ),
        sa.Column(
            "gloss_labels", postgresql.JSONB(), nullable=False, server_default=_jsonb_default("[]")
        ),
        sa.Column("identity_key", sa.CHAR(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("morpheme", "morph"),
        _enum_check("morpheme", "role", _MORPH_ROLES),
        _enum_check("morpheme", "form_basis", _FORM_BASES),
        _enum_check("morpheme", "status", _LIFECYCLE_STATUSES),
        sa.CheckConstraint("language ~ '^[a-z]{3}$'", name="ck_morpheme_language"),
        sa.UniqueConstraint("run_id", "identity_key", name="uq_morpheme_run_identity_key"),
    )
    op.create_index("ix_morpheme_language", "morpheme", ["language"])
    op.create_table(
        "allomorph",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("morpheme_id", sa.Text(), sa.ForeignKey("morpheme.id"), nullable=False),
        sa.Column("form", sa.Text(), nullable=False),
        sa.Column("is_zero", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("form_basis", sa.Text(), nullable=False),
        sa.Column("conditioning", sa.Text(), nullable=False),
        sa.Column("conditioning_note", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("allomorph", "allo"),
        _enum_check("allomorph", "form_basis", _FORM_BASES),
        _enum_check("allomorph", "conditioning", _ALLOMORPH_CONDITIONINGS),
        _enum_check("allomorph", "status", _LIFECYCLE_STATUSES),
        sa.CheckConstraint("form <> '' OR is_zero", name="ck_allomorph_form_or_zero"),
        sa.UniqueConstraint("morpheme_id", "form", name="uq_allomorph_morpheme_form"),
    )
    op.create_index("ix_allomorph_morpheme_id", "allomorph", ["morpheme_id"])
    op.create_table(
        "morph_analysis",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column(
            "target_token_id", sa.Text(), sa.ForeignKey("token_occurrence.id"), nullable=False
        ),
        sa.Column("analysis_kind", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("span_representation", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("signature", sa.CHAR(64), nullable=False),
        sa.Column("abstention", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("morph_analysis", "ma"),
        _enum_check("morph_analysis", "analysis_kind", _ANALYSIS_KINDS),
        _enum_check("morph_analysis", "span_representation", _SPAN_REPRESENTATIONS),
        sa.CheckConstraint(
            f"abstention IS NULL OR abstention IN ({_in_list(_ABSTENTIONS)})",
            name="ck_morph_analysis_abstention",
        ),
        _enum_check("morph_analysis", "status", _LIFECYCLE_STATUSES),
        sa.UniqueConstraint(
            "target_token_id", "run_id", "signature", name="uq_morph_analysis_signature"
        ),
    )
    op.create_index("ix_morph_analysis_target_token_id", "morph_analysis", ["target_token_id"])
    op.create_table(
        "morph_segment",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("analysis_id", sa.Text(), sa.ForeignKey("morph_analysis.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("is_zero", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("morpheme_id", sa.Text(), sa.ForeignKey("morpheme.id"), nullable=True),
        sa.Column("allomorph_id", sa.Text(), sa.ForeignKey("allomorph.id"), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("source_gloss", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("morph_segment", "mseg"),
        sa.CheckConstraint(
            f"role IS NULL OR role IN ({_in_list(_MORPH_ROLES)})",
            name="ck_morph_segment_role",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_morph_segment_ordinal"),
        sa.CheckConstraint("start >= 0", name="ck_morph_segment_start"),
        sa.CheckConstraint('"end" >= 0', name="ck_morph_segment_end"),
        sa.CheckConstraint('start <= "end"', name="ck_morph_segment_start_le_end"),
        sa.CheckConstraint('start < "end" OR is_zero', name="ck_morph_segment_span_or_zero"),
        sa.CheckConstraint(
            "allomorph_id IS NULL OR morpheme_id IS NOT NULL",
            name="ck_morph_segment_allomorph_requires_morpheme",
        ),
        sa.UniqueConstraint("analysis_id", "ordinal", name="uq_morph_segment_analysis_ordinal"),
    )
    op.create_index("ix_morph_segment_analysis_id", "morph_segment", ["analysis_id"])
    op.create_index("ix_morph_segment_morpheme_id", "morph_segment", ["morpheme_id"])
    op.create_table(
        "morph_segment_feature",
        sa.Column("segment_id", sa.Text(), sa.ForeignKey("morph_segment.id"), primary_key=True),
        sa.Column("feature_id", sa.Text(), sa.ForeignKey("feature.id"), primary_key=True),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _enum_check("morph_segment_feature", "basis", _FEATURE_BASES),
    )


def _create_hypothesis_guard() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION langpipe_hypothesis_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'hypothesis rows cannot be deleted: %',
                    TG_TABLE_NAME
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF (to_jsonb(NEW) - 'status' - 'score_breakdown')
                IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'score_breakdown') THEN
                RAISE EXCEPTION 'hypothesis may change only status and score_breakdown: %',
                    TG_TABLE_NAME
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
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
    for table in _HYPOTHESIS_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_guard BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION langpipe_hypothesis_guard()"
        )


def _drop_triggers() -> None:
    for table in _APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_forbid_mutation ON {table}")
    for table in _HYPOTHESIS_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_guard ON {table}")
    op.execute("DROP FUNCTION IF EXISTS langpipe_hypothesis_guard()")


def upgrade() -> None:
    _create_hypothesis_guard()
    _create_tables()
    _replace_entity_type_check(_ENTITY_TYPES)
    _replace_check("lineage_edge", "ck_lineage_edge_kind", f"kind IN ({_in_list(_KINDS_0006)})")
    _replace_check(
        "audit_event",
        "ck_audit_event_event_type",
        f"event_type IN ({_in_list(_AUDIT_EVENT_TYPES_0006)})",
    )
    _create_triggers()


def downgrade() -> None:
    bind = op.get_bind()
    # Refusal runs before any DDL and is transactional: a refusal leaves the M5 schema and
    # every row in place (ADR-0017/0018, M5-PLAN §7.5). The scan runs dependent-first (the
    # same order as the drops below), so a refusal names the most dependent table that
    # still holds rows rather than a mere prerequisite of it.
    for table in reversed(_M5_TABLES):
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count:
            raise RuntimeError(f"downgrade 0006 refused: {count} rows survive in {table}")
    count = bind.execute(
        sa.text(
            "SELECT count(*) FROM object_registry "
            f"WHERE entity_type IN ({_in_list(_ENTITY_TYPES_M5_ADDED)})"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(f"downgrade 0006 refused: {count} M5 registry entries survive")
    count = bind.execute(
        sa.text("SELECT count(*) FROM lineage_edge WHERE kind = 'recalculated'")
    ).scalar_one()
    if count:
        raise RuntimeError(f"downgrade 0006 refused: {count} recalculated lineage edges survive")
    count = bind.execute(
        sa.text(
            "SELECT count(*) FROM audit_event "
            f"WHERE event_type IN ({_in_list(_M5_AUDIT_EVENT_TYPES_ADDED)})"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(f"downgrade 0006 refused: {count} M5 audit events survive")

    _drop_triggers()
    op.drop_table("morph_segment_feature")
    op.drop_table("morph_segment")
    op.drop_table("allomorph")
    op.drop_table("morph_analysis")
    op.drop_table("morpheme")
    op.drop_table("feature")
    op.drop_table("igt_observation")
    op.drop_table("source_use_approval")
    # Restore the 0005 vocabularies.
    _replace_entity_type_check(_ENTITY_TYPES_M4)
    _replace_check("lineage_edge", "ck_lineage_edge_kind", f"kind IN ({_in_list(_KINDS_0005)})")
    _replace_check(
        "audit_event",
        "ck_audit_event_event_type",
        f"event_type IN ({_in_list(_AUDIT_EVENT_TYPES_0001)})",
    )
