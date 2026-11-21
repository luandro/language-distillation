"""SQLAlchemy 2 ORM mirror of the M1 relational schema (ADR-0009, ADR-0011, ADR-0013).

CHECK constraints, triggers and the migration's literal enum tuples live only in
`migrations/versions/0001_m1_evidence_substrate.py`, `0003_m3_alignment.py`,
`0004_m4_lexical_and_review.py` and `0006_m5_igt_and_morphology.py`. This module mirrors
nullability, server defaults, UNIQUE constraints and indexes so `compare_metadata` reports
no drift.
"""

from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ObjectRegistry(Base):
    __tablename__ = "object_registry"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourcePolicy(Base):
    __tablename__ = "source_policy"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    mode: Mapped[str] = mapped_column(Text)
    access_class: Mapped[str] = mapped_column(Text)
    authority: Mapped[str] = mapped_column(Text)
    allow: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    deny: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    restrictions: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    policy_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProcessingRun(Base):
    __tablename__ = "processing_run"
    __table_args__ = (
        Index(
            "ux_run_key_succeeded",
            "run_key",
            unique=True,
            postgresql_where=sql_text("status = 'succeeded'"),
        ),
        Index("ix_processing_run_run_key", "run_key"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    stage: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(Text)
    tool_version: Mapped[str] = mapped_column(Text)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    config_hash: Mapped[str] = mapped_column(CHAR(64))
    code_revision: Mapped[str] = mapped_column(Text)
    run_key: Mapped[str] = mapped_column(CHAR(64))
    random_seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (UniqueConstraint("key", name="uq_source_key"),)

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    key: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    policy_id: Mapped[str] = mapped_column(Text, ForeignKey("source_policy.id"))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    domains: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    registers: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=sql_text("'{}'::text[]")
    )
    manifest_sha256: Mapped[str] = mapped_column(CHAR(64))
    registration_run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceObject(Base):
    __tablename__ = "source_object"
    __table_args__ = (
        UniqueConstraint("source_id", "original_path", name="uq_source_object_source_path"),
        Index("ix_source_object_sha256", "sha256"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("source.id"))
    original_path: Mapped[str] = mapped_column(Text)
    origin_uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(Text)
    access_class: Mapped[str] = mapped_column(Text)
    registration_run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RawBlob(Base):
    __tablename__ = "raw_blob"

    sha256: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_backend: Mapped[str] = mapped_column(Text)
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingestion_run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))


class ProcessingRunIo(Base):
    __tablename__ = "processing_run_io"

    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"), primary_key=True)
    object_id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)


class Artifact(Base):
    __tablename__ = "artifact"

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    kind: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    access_class: Mapped[str] = mapped_column(Text)
    schema_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Segment(Base):
    __tablename__ = "segment"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "source_object_id", "ordinal", name="uq_segment_run_object_ordinal"
        ),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("source.id"))
    source_object_id: Mapped[str] = mapped_column(Text, ForeignKey("source_object.id"))
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(CHAR(3))
    locator: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Form(Base):
    __tablename__ = "form"
    __table_args__ = (
        UniqueConstraint(
            "language", "orthography_profile", "text", name="uq_form_language_profile_text"
        ),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    language: Mapped[str] = mapped_column(CHAR(3))
    orthography_profile: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TokenOccurrence(Base):
    __tablename__ = "token_occurrence"
    __table_args__ = (
        UniqueConstraint("run_id", "segment_id", "ordinal", name="uq_token_run_segment_ordinal"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    segment_id: Mapped[str] = mapped_column(Text, ForeignKey("segment.id"))
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    raw_surface: Mapped[str] = mapped_column(Text)
    normalized_surface: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    norm_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    norm_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokenizer: Mapped[str] = mapped_column(Text)
    form_id: Mapped[str | None] = mapped_column(Text, ForeignKey("form.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SegmentAlignment(Base):
    __tablename__ = "segment_alignment"
    __table_args__ = (
        UniqueConstraint("run_id", "group_key", name="uq_segment_alignment_run_group_key"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    method: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_scores: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    group_key: Mapped[str] = mapped_column(CHAR(64))
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    authorization_basis_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("artifact.id"), nullable=True
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("segment_alignment.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Storage-internal DB-owned marker (ADR-0011 §8): trg_segment_alignment_stamp_creation
    # stamps the full epoch-aware top-level transaction identity that the member guard's
    # publication-immutability check compares against. Not domain metadata; not exposed by
    # the public model/API — clients cannot set or change it.
    creating_txid: Mapped[int] = mapped_column(BigInteger)


class SegmentAlignmentMember(Base):
    __tablename__ = "segment_alignment_member"
    __table_args__ = (
        UniqueConstraint(
            "alignment_id", "segment_id", name="uq_segment_alignment_member_alignment_segment"
        ),
        Index("ix_segment_alignment_member_segment_id", "segment_id"),
    )

    alignment_id: Mapped[str] = mapped_column(
        Text, ForeignKey("segment_alignment.id"), primary_key=True
    )
    side: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[str] = mapped_column(Text, ForeignKey("segment.id"))


class TokenAlignmentEdge(Base):
    __tablename__ = "token_alignment_edge"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "segment_alignment_id",
            "source_token_id",
            "target_token_id",
            "direction",
            "symmetrization",
            name="uq_token_alignment_edge_natural_key",
        ),
        Index("ix_token_alignment_edge_run_id", "run_id"),
        Index("ix_token_alignment_edge_segment_alignment_id", "segment_alignment_id"),
        Index("ix_token_alignment_edge_source_token_id", "source_token_id"),
        Index("ix_token_alignment_edge_target_token_id", "target_token_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    segment_alignment_id: Mapped[str] = mapped_column(Text, ForeignKey("segment_alignment.id"))
    source_token_id: Mapped[str] = mapped_column(Text, ForeignKey("token_occurrence.id"))
    target_token_id: Mapped[str] = mapped_column(Text, ForeignKey("token_occurrence.id"))
    direction: Mapped[str] = mapped_column(Text)
    algorithm: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_scores: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    symmetrization: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvidenceItem(Base):
    __tablename__ = "evidence_item"
    __table_args__ = (Index("ix_evidence_item_target_id", "target_id"),)

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    polarity: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"))
    claim: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    source_id: Mapped[str | None] = mapped_column(Text, ForeignKey("source.id"), nullable=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    strength: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    policy_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    independence_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    register: Mapped[str | None] = mapped_column(Text, nullable=True)
    extensions: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LineageEdge(Base):
    __tablename__ = "lineage_edge"
    __table_args__ = (
        UniqueConstraint("from_id", "to_id", "kind", name="uq_lineage_from_to_kind"),
        Index("ix_lineage_edge_from_id", "from_id"),
        Index("ix_lineage_edge_to_id", "to_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    from_id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"))
    to_id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"))
    kind: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Concept(Base):
    """A semantic referent, `local` by default with optional external mapping (ADR-0013 §1)."""

    __tablename__ = "concept"

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    concept_type: Mapped[str] = mapped_column(Text, server_default=sql_text("'local'"))
    canonical_label: Mapped[str] = mapped_column(Text)
    concepticon_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_urn: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Lexeme(Base):
    """An induced or curated lexical unit. No paradigms, slots or feature bundles (ADR-0013)."""

    __tablename__ = "lexeme"
    __table_args__ = (
        Index("ix_lexeme_language", "language"),
        Index("ix_lexeme_lemma_form_id", "lemma_form_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    language: Mapped[str] = mapped_column(Text)
    lemma_form_id: Mapped[str | None] = mapped_column(Text, ForeignKey("form.id"), nullable=True)
    pos: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    register: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_breakdown: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FormLexeme(Base):
    """Append-only many-to-many join between orthographic forms and lexical hypotheses."""

    __tablename__ = "form_lexeme"
    __table_args__ = (
        UniqueConstraint("form_id", "lexeme_id", name="ux_form_lexeme_pair"),
        Index("ix_form_lexeme_form_id", "form_id"),
        Index("ix_form_lexeme_lexeme_id", "lexeme_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    form_id: Mapped[str] = mapped_column(Text, ForeignKey("form.id"))
    lexeme_id: Mapped[str] = mapped_column(Text, ForeignKey("lexeme.id"))
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Sense(Base):
    """One meaning hypothesis of a lexeme (ADR-0013 §1)."""

    __tablename__ = "sense"
    __table_args__ = (
        Index("ix_sense_lexeme_id", "lexeme_id"),
        Index("ix_sense_concept_id", "concept_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    lexeme_id: Mapped[str] = mapped_column(Text, ForeignKey("lexeme.id"))
    glosses: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    concept_id: Mapped[str | None] = mapped_column(Text, ForeignKey("concept.id"), nullable=True)
    status: Mapped[str] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    register: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_breakdown: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewTask(Base):
    """One queued human review request about a candidate object (ADR-0013 §4-5)."""

    __tablename__ = "review_task"
    __table_args__ = (
        Index("ix_review_task_status_priority", "status", "priority"),
        Index("ix_review_task_target_id", "target_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    task_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"))
    target_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_item_ids: Mapped[list[str]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    required_role: Mapped[str] = mapped_column(Text)
    priority: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    creator_run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    status: Mapped[str] = mapped_column(Text, server_default=sql_text("'open'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewDecision(Base):
    """An immutable reviewer disposition for one review task (ADR-0013 §5)."""

    __tablename__ = "review_decision"
    __table_args__ = (
        Index("ix_review_decision_task_id", "task_id"),
        Index("ix_review_decision_target_id", "target_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    task_id: Mapped[str] = mapped_column(Text, ForeignKey("review_task.id"))
    target_id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"))
    decision: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[str] = mapped_column(Text)
    reviewer_role: Mapped[str] = mapped_column(Text)
    superseding_object_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("object_registry.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceUseApproval(Base):
    """A governance steward's grant/withdraw decision on one source operation (ADR-0018)."""

    __tablename__ = "source_use_approval"
    __table_args__ = (
        Index(
            "ix_source_use_approval_source_op_created",
            "source_id",
            "operation",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("source.id"))
    operation: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    approver_id: Mapped[str] = mapped_column(Text)
    approver_role: Mapped[str] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IGTObservation(Base):
    """A verbatim interlinear record parsed from a source object (ADR-0017 §1-3).

    Observation, never inference: `tiers` preserves the source record as parsed; all
    morphological claims live in the hypothesis tables.
    """

    __tablename__ = "igt_observation"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "source_object_id", "record_ordinal", name="uq_igt_observation_record"
        ),
        Index("ix_igt_observation_source_id", "source_id"),
        Index("ix_igt_observation_segment_id", "segment_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("source.id"))
    source_object_id: Mapped[str] = mapped_column(Text, ForeignKey("source_object.id"))
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    segment_id: Mapped[str | None] = mapped_column(Text, ForeignKey("segment.id"), nullable=True)
    record_ordinal: Mapped[int] = mapped_column(Integer)
    record_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    tiers: Mapped[list[object]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    words: Mapped[list[object]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    translations: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    parse_status: Mapped[str] = mapped_column(Text)
    diagnostics: Mapped[list[object]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Feature(Base):
    """A morphosyntactic feature definition, namespaced to its vocabulary (ADR-0017 §4)."""

    __tablename__ = "feature"
    __table_args__ = (UniqueConstraint("namespace", "label", name="uq_feature_namespace_label"),)

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    namespace: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    definition: Mapped[str] = mapped_column(Text)
    defined_by: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Morpheme(Base):
    """A morph hypothesis: canonical form, role and glosses under the lifecycle (ADR-0017 §5)."""

    __tablename__ = "morpheme"
    __table_args__ = (
        UniqueConstraint("run_id", "identity_key", name="uq_morpheme_run_identity_key"),
        Index("ix_morpheme_language", "language"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    language: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    canonical_form: Mapped[str | None] = mapped_column(Text, nullable=True)
    form_basis: Mapped[str] = mapped_column(Text)
    glosses: Mapped[dict[str, object]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    gloss_labels: Mapped[list[object]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    identity_key: Mapped[str] = mapped_column(CHAR(64))
    status: Mapped[str] = mapped_column(Text)
    score_breakdown: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Allomorph(Base):
    """A contextual variant of a morpheme, possibly zero (ADR-0017 §5)."""

    __tablename__ = "allomorph"
    __table_args__ = (
        UniqueConstraint("morpheme_id", "form", name="uq_allomorph_morpheme_form"),
        Index("ix_allomorph_morpheme_id", "morpheme_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    morpheme_id: Mapped[str] = mapped_column(Text, ForeignKey("morpheme.id"))
    form: Mapped[str] = mapped_column(Text)
    is_zero: Mapped[bool] = mapped_column(Boolean, server_default=false())
    form_basis: Mapped[str] = mapped_column(Text)
    conditioning: Mapped[str] = mapped_column(Text)
    conditioning_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MorphAnalysis(Base):
    """One segmentation hypothesis for one token occurrence (ADR-0017 §6).

    Competing analyses are distinct rows keyed by `signature`; there is no winner column.
    """

    __tablename__ = "morph_analysis"
    __table_args__ = (
        UniqueConstraint(
            "target_token_id", "run_id", "signature", name="uq_morph_analysis_signature"
        ),
        Index("ix_morph_analysis_target_token_id", "target_token_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    target_token_id: Mapped[str] = mapped_column(Text, ForeignKey("token_occurrence.id"))
    analysis_kind: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    span_representation: Mapped[str] = mapped_column(Text)
    surface: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(CHAR(64))
    abstention: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text)
    score_breakdown: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("processing_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MorphSegment(Base):
    """One morph position within an analysis; append-only observation of the hypothesis
    structure (ADR-0017 §6)."""

    __tablename__ = "morph_segment"
    __table_args__ = (
        UniqueConstraint("analysis_id", "ordinal", name="uq_morph_segment_analysis_ordinal"),
        Index("ix_morph_segment_analysis_id", "analysis_id"),
        Index("ix_morph_segment_morpheme_id", "morpheme_id"),
    )

    id: Mapped[str] = mapped_column(Text, ForeignKey("object_registry.id"), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(Text, ForeignKey("morph_analysis.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    is_zero: Mapped[bool] = mapped_column(Boolean, server_default=false())
    surface: Mapped[str] = mapped_column(Text)
    morpheme_id: Mapped[str | None] = mapped_column(Text, ForeignKey("morpheme.id"), nullable=True)
    allomorph_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("allomorph.id"), nullable=True
    )
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_gloss: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MorphSegmentFeature(Base):
    """Append-only assignment of a feature to a morph segment (ADR-0017 §6)."""

    __tablename__ = "morph_segment_feature"

    segment_id: Mapped[str] = mapped_column(Text, ForeignKey("morph_segment.id"), primary_key=True)
    feature_id: Mapped[str] = mapped_column(Text, ForeignKey("feature.id"), primary_key=True)
    basis: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
