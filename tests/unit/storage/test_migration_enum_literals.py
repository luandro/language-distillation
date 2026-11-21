"""The migration's literal CHECK value tuples must mirror the domain enums (no DB needed)."""

import importlib.util
from enum import StrEnum
from pathlib import Path
from types import ModuleType

from langpipe.domain.enums import (
    Abstention,
    AccessClass,
    AlignmentDirection,
    AlignmentMode,
    AlignmentStatus,
    AllomorphConditioning,
    AnalysisKind,
    ApprovalAction,
    ArtifactKind,
    AuditEventType,
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    FeatureAssignmentBasis,
    FormBasis,
    IgtFormat,
    IgtParseStatus,
    LifecycleStatus,
    LineageKind,
    MorphRole,
    Operation,
    PolicyMode,
    ReviewDecisionKind,
    ReviewTaskType,
    RunIoRole,
    RunStage,
    RunStatus,
    SegmentStatus,
    SourceStatus,
    SourceType,
    SpanRepresentation,
    Symmetrization,
)
from langpipe.domain.models.review import REVIEW_TASK_STATUSES

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0001_m1_evidence_substrate.py"
MIGRATION_0002_PATH = REPO_ROOT / "migrations" / "versions" / "0002_m2_text_processing.py"
MIGRATION_0003_PATH = REPO_ROOT / "migrations" / "versions" / "0003_m3_alignment.py"
MIGRATION_0004_PATH = REPO_ROOT / "migrations" / "versions" / "0004_m4_lexical_and_review.py"
MIGRATION_0005_PATH = REPO_ROOT / "migrations" / "versions" / "0005_review_stale_dependent.py"
MIGRATION_0006_PATH = REPO_ROOT / "migrations" / "versions" / "0006_m5_igt_and_morphology.py"

ENUM_TUPLES: dict[str, type[StrEnum]] = {
    "_POLICY_MODES": PolicyMode,
    "_ACCESS_CLASSES": AccessClass,
    "_SOURCE_TYPES": SourceType,
    "_SOURCE_STATUSES": SourceStatus,
    "_RUN_STAGES": RunStage,
    "_RUN_STATUSES": RunStatus,
    "_RUN_IO_ROLES": RunIoRole,
    "_SEGMENT_STATUSES": SegmentStatus,
    "_EVIDENCE_KINDS": EvidenceKind,
    "_EVIDENCE_POLARITIES": EvidencePolarity,
}

# ADR-0018 appends source_use_approved/source_use_withdrawn to AuditEventType; migrations
# 0001/0005 are immutable, so 0001 pins its historic M1 prefix and migration 0006 (WP5.3)
# owns the appended literals.
M1_AUDIT_EVENT_TYPES = tuple(member.value for member in AuditEventType)[:4]

M1_ARTIFACT_KINDS = tuple(member.value for member in ArtifactKind)[:7]
M1_ENTITY_TYPES = tuple(member.value for member in EntityType)[:8]
# `_ENTITY_TYPES_M3_ADDED` in migration 0003 (ADR-0013 appends to EntityType from M4 onward).
_ENTITY_TYPES_M3_ADDED = ("segment_alignment", "token_alignment_edge")

M3_ENUM_TUPLES: dict[str, type[StrEnum]] = {
    "_ALIGNMENT_MODES": AlignmentMode,
    "_ALIGNMENT_STATUSES": AlignmentStatus,
    "_ALIGNMENT_DIRECTIONS": AlignmentDirection,
    "_SYMMETRIZATIONS": Symmetrization,
}

# ADR-0013: M4 appends the lexical and review EntityType values; 0004 owns its own literals.
_ENTITY_TYPES_M4_ADDED = (
    "concept",
    "lexeme",
    "form_lexeme",
    "sense",
    "review_task",
    "review_decision",
)
M4_ENUM_TUPLES: dict[str, type[StrEnum]] = {
    "_LIFECYCLE_STATUSES": LifecycleStatus,
    "_TASK_TYPES": ReviewTaskType,
    "_REVIEW_DECISIONS": ReviewDecisionKind,
}


def _load_migration(path: Path = MIGRATION_PATH) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_literals_match_enums() -> None:
    module = _load_migration()
    for name, enum_cls in ENUM_TUPLES.items():
        expected = tuple(member.value for member in enum_cls)
        assert getattr(module, name) == expected, name


def test_migration_0001_artifact_kinds_are_m1_prefix() -> None:
    assert _load_migration()._ARTIFACT_KINDS == M1_ARTIFACT_KINDS


def test_migration_0001_entity_types_are_m1_prefix() -> None:
    # M3 (ADR-0011) appended segment_alignment/token_alignment_edge to EntityType; 0001 stays
    # immutable and keeps the original eight literals.
    assert _load_migration()._ENTITY_TYPES == M1_ENTITY_TYPES


def test_migration_0001_audit_event_types_are_m1_prefix() -> None:
    # M5 (ADR-0018) appends source_use_approved/source_use_withdrawn to AuditEventType; 0001
    # stays immutable and keeps the original four literals. Migration 0006 (WP5.3) owns them.
    assert _load_migration()._AUDIT_EVENT_TYPES == M1_AUDIT_EVENT_TYPES


M1_LINEAGE_KINDS = tuple(member.value for member in LineageKind)[:6]
# 0005 (ADR-0014) appends the review staleness flag to the lineage kind vocabulary.
_ENTITY_LINEAGE_KIND_M5_ADDED = ("stale_dependent",)


def test_migration_0001_lineage_kinds_are_m1_prefix() -> None:
    # M4 (ADR-0014) appended stale_dependent to LineageKind; 0001 stays immutable and
    # keeps the original six literals.
    assert _load_migration()._LINEAGE_KINDS == M1_LINEAGE_KINDS


def test_migration_0002_literals_match_enums() -> None:
    module = _load_migration(MIGRATION_0002_PATH)
    assert tuple(member.value for member in ArtifactKind) == module._ARTIFACT_KINDS
    assert module._ARTIFACT_KINDS_M1 == M1_ARTIFACT_KINDS


def test_migration_0002_does_not_import_application_code() -> None:
    source = MIGRATION_0002_PATH.read_text(encoding="utf-8")
    assert "from langpipe" not in source
    assert "import langpipe" not in source


def test_migration_0003_literals_match_enums() -> None:
    module = _load_migration(MIGRATION_0003_PATH)
    for name, enum_cls in M3_ENUM_TUPLES.items():
        expected = tuple(member.value for member in enum_cls)
        assert getattr(module, name) == expected, name
    # 0003 predates the M4 lexical and review EntityType values (ADR-0013), so it keeps
    # the M3 prefix only; M4 migration 0004 appends its own literals.
    assert module._ENTITY_TYPES == M1_ENTITY_TYPES + _ENTITY_TYPES_M3_ADDED
    assert module._ENTITY_TYPES_M1 == M1_ENTITY_TYPES
    assert module._ENTITY_TYPES_M3_ADDED == _ENTITY_TYPES_M3_ADDED
    assert _ENTITY_TYPES_M3_ADDED == ("segment_alignment", "token_alignment_edge")


def test_migration_0003_does_not_import_application_code() -> None:
    source = MIGRATION_0003_PATH.read_text(encoding="utf-8")
    assert "from langpipe" not in source
    assert "import langpipe" not in source


def test_migration_0004_does_not_import_application_code() -> None:
    source = MIGRATION_0004_PATH.read_text(encoding="utf-8")
    assert "from langpipe" not in source
    assert "import langpipe" not in source


def test_migration_0005_does_not_import_application_code() -> None:
    source = MIGRATION_0005_PATH.read_text(encoding="utf-8")
    assert "from langpipe" not in source
    assert "import langpipe" not in source


def test_migration_0005_literals_match_enums() -> None:
    module = _load_migration(MIGRATION_0005_PATH)
    # 0005 replaces ck_lineage_edge_kind in place: the 0001 prefix is kept verbatim and
    # the extended vocabulary is the domain enum as of M4.
    assert module._KINDS_0001 == M1_LINEAGE_KINDS
    assert module._KINDS_WITH_STALE_DEPENDENT == M1_LINEAGE_KINDS + _ENTITY_LINEAGE_KIND_M5_ADDED
    # `recalculated` (WP5.14) is appended to LineageKind by migration 0006 (WP5.3); 0005
    # stays immutable at its own milestone's vocabulary.
    assert tuple(member.value for member in LineageKind)[:7] == module._KINDS_WITH_STALE_DEPENDENT


# ADR-0017 appends the M5 IGT observation and morphology graph entity types to EntityType;
# migration 0006 (WP5.3) owns the appended literals.
_M5_ENTITY_TYPES_ADDED = (
    "igt_observation",
    "feature",
    "morpheme",
    "allomorph",
    "morph_analysis",
    "morph_segment",
    "source_use_approval",
)
# 0006 (WP5.14 follow-up) appends `recalculated` to the lineage kind vocabulary.
_M5_LINEAGE_KIND_ADDED = ("recalculated",)
# ADR-0018 appends the source-use approval audit events to AuditEventType.
_M5_AUDIT_EVENT_TYPES_ADDED = ("source_use_approved", "source_use_withdrawn")


def test_migration_0006_literals_match_enums() -> None:
    module = _load_migration(MIGRATION_0006_PATH)
    # 0006 replaces the object_registry/lineage_edge/audit_event CHECKs in place: the
    # extended vocabularies are the domain enums as of M5 (ADR-0017/0018).
    # `_ENTITY_TYPES` is compared as a set: 0004's immutable tuple orders the M4 additions
    # differently than the EntityType declaration (concept before lexeme), and a CHECK
    # IN-list is order-insensitive; the M5 suffix itself is order-faithful.
    assert set(member.value for member in EntityType) == set(module._ENTITY_TYPES)
    assert len(module._ENTITY_TYPES) == len(set(module._ENTITY_TYPES))
    assert tuple(member.value for member in LineageKind) == module._KINDS_0006
    assert tuple(member.value for member in AuditEventType) == module._AUDIT_EVENT_TYPES_0006
    # The prior milestones' vocabularies are kept verbatim as the base lists.
    assert (
        module._ENTITY_TYPES_M4 == M1_ENTITY_TYPES + _ENTITY_TYPES_M3_ADDED + _ENTITY_TYPES_M4_ADDED
    )
    assert module._ENTITY_TYPES_M5_ADDED == _M5_ENTITY_TYPES_ADDED
    assert module._KINDS_0005 == M1_LINEAGE_KINDS + _ENTITY_LINEAGE_KIND_M5_ADDED
    assert module._KINDS_0006 == module._KINDS_0005 + _M5_LINEAGE_KIND_ADDED
    assert module._AUDIT_EVENT_TYPES_0001 == M1_AUDIT_EVENT_TYPES
    assert module._AUDIT_EVENT_TYPES_0006 == M1_AUDIT_EVENT_TYPES + _M5_AUDIT_EVENT_TYPES_ADDED


M5_ENUM_TUPLES: dict[str, type[StrEnum]] = {
    "_APPROVAL_ACTIONS": ApprovalAction,
    "_IGT_FORMATS": IgtFormat,
    "_IGT_PARSE_STATUSES": IgtParseStatus,
    "_MORPH_ROLES": MorphRole,
    "_FORM_BASES": FormBasis,
    "_ALLOMORPH_CONDITIONINGS": AllomorphConditioning,
    "_ANALYSIS_KINDS": AnalysisKind,
    "_SPAN_REPRESENTATIONS": SpanRepresentation,
    "_ABSTENTIONS": Abstention,
    "_FEATURE_BASES": FeatureAssignmentBasis,
    "_LIFECYCLE_STATUSES": LifecycleStatus,
}
# ADR-0018 §3: the exhaustive M5 approvable-operation list (a subset of Operation).
_M5_APPROVABLE_OPERATIONS = (
    "read_raw",
    "extract",
    "normalize",
    "align",
    "distill_lexicon",
    "distill_morphology",
    "distill_grammar",
    "evaluation",
)


def test_migration_0006_table_literals_match_enums() -> None:
    module = _load_migration(MIGRATION_0006_PATH)
    for name, enum_cls in M5_ENUM_TUPLES.items():
        expected = tuple(member.value for member in enum_cls)
        assert getattr(module, name) == expected, name
    assert module._APPROVABLE_OPERATIONS == _M5_APPROVABLE_OPERATIONS
    assert set(module._APPROVABLE_OPERATIONS) <= {member.value for member in Operation}


def test_migration_0006_does_not_import_application_code() -> None:
    source = MIGRATION_0006_PATH.read_text(encoding="utf-8")
    assert "from langpipe" not in source
    assert "import langpipe" not in source


def test_migration_0004_literals_match_enums() -> None:
    module = _load_migration(MIGRATION_0004_PATH)
    for name, enum_cls in M4_ENUM_TUPLES.items():
        expected = tuple(member.value for member in enum_cls)
        assert getattr(module, name) == expected, name
    # Queue statuses are an operational tuple in review.py, not a LifecycleStatus enum:
    # only a validated object carries lifecycle status.
    assert module._REVIEW_TASK_STATUSES == REVIEW_TASK_STATUSES
    # ADR-0013 appends the lexical and review entity types to EntityType; 0004 owns them and
    # 0003 must stay at the M3 prefix.
    assert module._ENTITY_TYPES == M1_ENTITY_TYPES + _ENTITY_TYPES_M3_ADDED + _ENTITY_TYPES_M4_ADDED
    assert module._ENTITY_TYPES_M4_ADDED == _ENTITY_TYPES_M4_ADDED
    assert _load_migration(MIGRATION_0003_PATH)._ENTITY_TYPES == (
        M1_ENTITY_TYPES + _ENTITY_TYPES_M3_ADDED
    )


def test_migration_0004_concept_type_is_open() -> None:
    # `concept_type` is an open string in the domain model (ADR-0013 §1 allows local by
    # default plus optional external mappings, never an exhaustive vocabulary). A CHECK
    # vocabulary here would reject domain-valid values such as `community_defined`.
    source = MIGRATION_0004_PATH.read_text(encoding="utf-8")
    assert "_CONCEPT_TYPES" not in source
    assert "ck_concept_concept_type" not in source
    assert '_enum_check("concept", "concept_type"' not in source


def test_storage_backend_literal_is_local_only() -> None:
    assert _load_migration()._STORAGE_BACKENDS == ("local",)


def test_migration_does_not_import_application_code() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "from langpipe" not in source
    assert "import langpipe" not in source
