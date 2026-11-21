"""M1 evidence substrate: registry, governance, runs, raw objects, segments, tokens, lineage.

Revision ID: 0001_m1_evidence_substrate
Revises:
Create Date: 2026-10-11

ADR-0009. Enum value tuples are literal copies of the domain enums; the migration never imports
application code. Triggers enforce append-only rows, source changes limited to status/updated_at,
and run finish-once semantics.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_m1_evidence_substrate"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY_TYPES = (
    "source",
    "source_object",
    "processing_run",
    "artifact",
    "segment",
    "token_occurrence",
    "form",
    "evidence_item",
)
_POLICY_MODES = (
    "direct",
    "distill_only",
    "review_required",
    "restricted",
    "archive_only",
    "exclude",
)
_ACCESS_CLASSES = ("public", "community", "restricted", "highly_restricted")
_SOURCE_TYPES = (
    "parallel_text",
    "educational_publication",
    "publication",
    "dictionary",
    "wordlist",
    "grammar_description",
    "igt",
    "monolingual_text",
    "audio",
    "video",
    "other",
)
_SOURCE_STATUSES = ("registered", "ingested", "revoked")
_RUN_STAGES = (
    "source_registration",
    "raw_ingestion",
    "extraction",
    "normalization",
    "tokenization",
    "segment_alignment",
    "token_alignment",
    "lexical_induction",
    "igt_import",
    "morphology_induction",
    "grammar_extraction",
    "human_review",
    "manual_annotation",
    "export",
    "evaluation",
)
_RUN_STATUSES = ("running", "succeeded", "failed")
_RUN_IO_ROLES = ("input", "output")
_ARTIFACT_KINDS = (
    "ingest_report",
    "extraction_snapshot",
    "alignment_file",
    "cldf_export",
    "benchmark_report",
    "dataset",
    "other",
)
_SEGMENT_STATUSES = ("ok", "normalization_failed")
_EVIDENCE_KINDS = (
    "dictionary_assertion",
    "token_alignment",
    "segment_cooccurrence",
    "igt_assertion",
    "grammar_description",
    "speaker_review",
    "morphology_induction",
    "related_language_comparison",
    "monolingual_distribution",
    "manual_annotation",
)
_EVIDENCE_POLARITIES = ("supports", "contradicts", "context_only")
_LINEAGE_KINDS = (
    "derived_from",
    "generated_from",
    "normalized_from",
    "extracted_from",
    "imported_from",
    "supersedes",
)
_AUDIT_EVENT_TYPES = ("policy_created", "source_registered", "raw_ingested", "policy_denied")
_STORAGE_BACKENDS = ("local",)

_ID_PATTERN = "^{prefix}_[0-9A-HJKMNP-TV-Z]{{26}}$"
_REGISTRY_ID_PATTERN = "^[a-z]+_[0-9A-HJKMNP-TV-Z]{26}$"

_APPEND_ONLY_TABLES = (
    "object_registry",
    "source_policy",
    "source_object",
    "raw_blob",
    "processing_run_io",
    "artifact",
    "segment",
    "form",
    "token_occurrence",
    "evidence_item",
    "lineage_edge",
    "audit_event",
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _id_check(table: str, prefix: str | None) -> sa.CheckConstraint:
    pattern = _REGISTRY_ID_PATTERN if prefix is None else _ID_PATTERN.format(prefix=prefix)
    return sa.CheckConstraint(f"id ~ '{pattern}'", name=f"ck_{table}_id")


def _enum_check(table: str, column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({_in_list(values)})", name=f"ck_{table}_{column}")


def _create_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION langpipe_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'append-only table: %', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION langpipe_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'source rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF (to_jsonb(NEW) - 'status' - 'updated_at')
                IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'updated_at') THEN
                RAISE EXCEPTION 'source may change only status and updated_at'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION langpipe_run_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'processing_run rows cannot be deleted'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.status <> 'running' OR NEW.status = 'running' THEN
                RAISE EXCEPTION 'processing_run may finish only once, from running'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF (to_jsonb(NEW) - 'status' - 'finished_at' - 'error_type' - 'error_message')
                IS DISTINCT FROM
                (to_jsonb(OLD) - 'status' - 'finished_at' - 'error_type' - 'error_message') THEN
                RAISE EXCEPTION 'processing_run may change only status and finish fields'
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
    op.execute(
        "CREATE TRIGGER trg_source_guard BEFORE UPDATE OR DELETE ON source "
        "FOR EACH ROW EXECUTE FUNCTION langpipe_source_guard()"
    )
    op.execute(
        "CREATE TRIGGER trg_processing_run_guard BEFORE UPDATE OR DELETE ON processing_run "
        "FOR EACH ROW EXECUTE FUNCTION langpipe_run_guard()"
    )


def _create_registry_and_governance() -> None:
    op.create_table(
        "object_registry",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("object_registry", None),
        _enum_check("object_registry", "entity_type", _ENTITY_TYPES),
    )
    op.create_table(
        "source_policy",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("access_class", sa.Text(), nullable=False),
        sa.Column("authority", sa.Text(), nullable=False),
        sa.Column(
            "allow",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "deny",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "restrictions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("source_policy", "pol"),
        _enum_check("source_policy", "mode", _POLICY_MODES),
        _enum_check("source_policy", "access_class", _ACCESS_CLASSES),
        sa.CheckConstraint("policy_version >= 1", name="ck_source_policy_policy_version"),
    )
    op.create_table(
        "processing_run",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("config_hash", sa.CHAR(64), nullable=False),
        sa.Column("code_revision", sa.Text(), nullable=False),
        sa.Column("run_key", sa.CHAR(64), nullable=False),
        sa.Column("random_seed", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _id_check("processing_run", "run"),
        _enum_check("processing_run", "stage", _RUN_STAGES),
        _enum_check("processing_run", "status", _RUN_STATUSES),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND error_type IS NULL "
            "AND error_message IS NULL) "
            "OR (status = 'succeeded' AND finished_at IS NOT NULL AND error_type IS NULL "
            "AND error_message IS NULL) "
            "OR (status = 'failed' AND finished_at IS NOT NULL AND error_type IS NOT NULL)",
            name="ck_processing_run_terminal_fields",
        ),
    )
    op.create_index(
        "ux_run_key_succeeded",
        "processing_run",
        ["run_key"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )
    op.create_index("ix_processing_run_run_key", "processing_run", ["run_key"])
    op.create_table(
        "source",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("policy_id", sa.Text(), sa.ForeignKey("source_policy.id"), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "domains",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "registers",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("manifest_sha256", sa.CHAR(64), nullable=False),
        sa.Column(
            "registration_run_id",
            sa.Text(),
            sa.ForeignKey("processing_run.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_source_key"),
        _id_check("source", "src"),
        _enum_check("source", "source_type", _SOURCE_TYPES),
        _enum_check("source", "status", _SOURCE_STATUSES),
    )


def _create_objects_and_raw() -> None:
    op.create_table(
        "source_object",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("original_path", sa.Text(), nullable=False),
        sa.Column("origin_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("access_class", sa.Text(), nullable=False),
        sa.Column(
            "registration_run_id",
            sa.Text(),
            sa.ForeignKey("processing_run.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "original_path", name="uq_source_object_source_path"),
        _id_check("source_object", "sobj"),
        _enum_check("source_object", "access_class", _ACCESS_CLASSES),
        sa.CheckConstraint("size_bytes >= 0", name="ck_source_object_size_bytes"),
    )
    op.create_index("ix_source_object_sha256", "source_object", ["sha256"])
    op.create_table(
        "raw_blob",
        sa.Column("sha256", sa.CHAR(64), primary_key=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_backend", sa.Text(), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingestion_run_id",
            sa.Text(),
            sa.ForeignKey("processing_run.id"),
            nullable=False,
        ),
        _enum_check("raw_blob", "storage_backend", _STORAGE_BACKENDS),
        sa.CheckConstraint("size_bytes >= 0", name="ck_raw_blob_size_bytes"),
    )
    op.create_table(
        "processing_run_io",
        sa.Column(
            "run_id",
            sa.Text(),
            sa.ForeignKey("processing_run.id"),
            primary_key=True,
        ),
        sa.Column(
            "object_id",
            sa.Text(),
            sa.ForeignKey("object_registry.id"),
            primary_key=True,
        ),
        sa.Column("role", sa.Text(), primary_key=True),
        _enum_check("processing_run_io", "role", _RUN_IO_ROLES),
    )
    op.create_table(
        "artifact",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("access_class", sa.Text(), nullable=False),
        sa.Column("schema_name", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("artifact", "artifact"),
        _enum_check("artifact", "kind", _ARTIFACT_KINDS),
        _enum_check("artifact", "access_class", _ACCESS_CLASSES),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifact_size_bytes"),
    )


def _create_segments_tokens_evidence() -> None:
    op.create_table(
        "segment",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column(
            "source_object_id",
            sa.Text(),
            sa.ForeignKey("source_object.id"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("language", sa.CHAR(3), nullable=False),
        sa.Column(
            "locator",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("normalization_profile", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id", "source_object_id", "ordinal", name="uq_segment_run_object_ordinal"
        ),
        _id_check("segment", "seg"),
        _enum_check("segment", "status", _SEGMENT_STATUSES),
        sa.CheckConstraint("ordinal >= 0", name="ck_segment_ordinal"),
        sa.CheckConstraint(
            "(normalized_text IS NULL) = (normalization_profile IS NULL)",
            name="ck_segment_normalization_pair",
        ),
    )
    op.create_table(
        "form",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("language", sa.CHAR(3), nullable=False),
        sa.Column("orthography_profile", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "language", "orthography_profile", "text", name="uq_form_language_profile_text"
        ),
        _id_check("form", "form"),
    )
    op.create_table(
        "token_occurrence",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("segment_id", sa.Text(), sa.ForeignKey("segment.id"), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("raw_surface", sa.Text(), nullable=False),
        sa.Column("normalized_surface", sa.Text(), nullable=True),
        sa.Column("raw_start", sa.Integer(), nullable=True),
        sa.Column("raw_end", sa.Integer(), nullable=True),
        sa.Column("norm_start", sa.Integer(), nullable=True),
        sa.Column("norm_end", sa.Integer(), nullable=True),
        sa.Column("tokenizer", sa.Text(), nullable=False),
        sa.Column("form_id", sa.Text(), sa.ForeignKey("form.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "segment_id", "ordinal", name="uq_token_run_segment_ordinal"),
        _id_check("token_occurrence", "tok"),
        sa.CheckConstraint("ordinal >= 0", name="ck_token_occurrence_ordinal"),
        sa.CheckConstraint(
            "(raw_start IS NULL) = (raw_end IS NULL)",
            name="ck_token_occurrence_raw_pair",
        ),
        sa.CheckConstraint(
            "raw_start IS NULL OR (raw_start >= 0 AND raw_end >= raw_start)",
            name="ck_token_occurrence_raw_range",
        ),
        sa.CheckConstraint(
            "(norm_start IS NULL) = (norm_end IS NULL)",
            name="ck_token_occurrence_norm_pair",
        ),
        sa.CheckConstraint(
            "norm_start IS NULL OR (norm_start >= 0 AND norm_end >= norm_start)",
            name="ck_token_occurrence_norm_range",
        ),
    )
    op.create_table(
        "evidence_item",
        sa.Column("id", sa.Text(), sa.ForeignKey("object_registry.id"), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("polarity", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), sa.ForeignKey("object_registry.id"), nullable=False),
        sa.Column("claim", postgresql.JSONB(), nullable=True),
        sa.Column("source_id", sa.Text(), sa.ForeignKey("source.id"), nullable=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column(
            "strength",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("policy_version", sa.Text(), nullable=True),
        sa.Column("independence_group", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("register", sa.Text(), nullable=True),
        sa.Column(
            "extensions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("evidence_item", "ev"),
        _enum_check("evidence_item", "kind", _EVIDENCE_KINDS),
        _enum_check("evidence_item", "polarity", _EVIDENCE_POLARITIES),
    )
    op.create_index("ix_evidence_item_target_id", "evidence_item", ["target_id"])


def _create_lineage_and_audit() -> None:
    op.create_table(
        "lineage_edge",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("from_id", sa.Text(), sa.ForeignKey("object_registry.id"), nullable=False),
        sa.Column("to_id", sa.Text(), sa.ForeignKey("object_registry.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("processing_run.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("from_id", "to_id", "kind", name="uq_lineage_from_to_kind"),
        _id_check("lineage_edge", "lin"),
        _enum_check("lineage_edge", "kind", _LINEAGE_KINDS),
        sa.CheckConstraint("from_id <> to_id", name="ck_lineage_edge_no_self"),
    )
    op.create_index("ix_lineage_edge_from_id", "lineage_edge", ["from_id"])
    op.create_index("ix_lineage_edge_to_id", "lineage_edge", ["to_id"])
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _id_check("audit_event", "aud"),
        _enum_check("audit_event", "event_type", _AUDIT_EVENT_TYPES),
    )


def upgrade() -> None:
    _create_registry_and_governance()
    _create_objects_and_raw()
    _create_segments_tokens_evidence()
    _create_lineage_and_audit()
    _create_functions()
    _create_triggers()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_processing_run_guard ON processing_run")
    op.execute("DROP TRIGGER IF EXISTS trg_source_guard ON source")
    for table in _APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_forbid_mutation ON {table}")
    for table in (
        "audit_event",
        "lineage_edge",
        "evidence_item",
        "token_occurrence",
        "form",
        "segment",
        "artifact",
        "processing_run_io",
        "raw_blob",
        "source_object",
        "source",
        "processing_run",
        "source_policy",
        "object_registry",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS langpipe_run_guard()")
    op.execute("DROP FUNCTION IF EXISTS langpipe_source_guard()")
    op.execute("DROP FUNCTION IF EXISTS langpipe_forbid_mutation()")
