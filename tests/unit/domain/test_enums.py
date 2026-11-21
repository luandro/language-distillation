from enum import Enum

import pytest

from langpipe.domain.enums import (
    AccessClass,
    AlignmentDirection,
    AlignmentMode,
    AlignmentStatus,
    ArtifactKind,
    AuditEventType,
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    LifecycleStatus,
    LineageKind,
    Operation,
    PolicyDecision,
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
    ValidationBasisKind,
    access_rank,
    most_restrictive,
)

EXPECTED_VALUES: dict[type[Enum], list[str]] = {
    PolicyMode: [
        "direct",
        "distill_only",
        "review_required",
        "restricted",
        "archive_only",
        "exclude",
    ],
    Operation: [
        "ingest",
        "read_raw",
        "extract",
        "normalize",
        "align",
        "distill_lexicon",
        "distill_morphology",
        "distill_grammar",
        "audio_align",
        "human_review",
        "third_party_api",
        "cloud_processing",
        "redistribute_raw",
        "redistribute_derived",
        "direct_training",
        "synthetic_generation_support",
        "evaluation",
    ],
    PolicyDecision: ["allow", "review_required", "deny"],
    AccessClass: ["public", "community", "restricted", "highly_restricted"],
    SourceType: [
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
    ],
    SourceStatus: ["registered", "ingested", "revoked"],
    RunStage: [
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
    ],
    RunStatus: ["running", "succeeded", "failed"],
    RunIoRole: ["input", "output"],
    ArtifactKind: [
        "ingest_report",
        "extraction_snapshot",
        "alignment_file",
        "cldf_export",
        "benchmark_report",
        "dataset",
        "other",
        "extraction_report",
        "extraction_error",
        "normalization_report",
        "tokenization_report",
    ],
    SegmentStatus: ["ok", "normalization_failed"],
    SpanRepresentation: ["raw", "normalized"],
    AlignmentMode: ["canonical", "heuristic", "experimental"],
    AlignmentStatus: ["structural", "inferred", "candidate", "approved", "rejected"],
    AlignmentDirection: ["forward", "reverse", "symmetrized"],
    Symmetrization: ["none", "intersection", "union"],
    EvidenceKind: [
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
    ],
    EvidencePolarity: ["supports", "contradicts", "context_only"],
    LineageKind: [
        "derived_from",
        "generated_from",
        "normalized_from",
        "extracted_from",
        "imported_from",
        "supersedes",
        "stale_dependent",
        # M5-PLAN WP5.2: completed-recalculation record (C-2, WP5.14).
        "recalculated",
    ],
    LifecycleStatus: ["candidate", "supported", "validated", "rejected", "deprecated"],
    ValidationBasisKind: ["authorized_reviewer", "authoritative_import", "editorial_decision"],
    ReviewTaskType: [
        "lexical_sense",
        "lemma",
        "morphology_segmentation",
        "morpheme_function",
        "grammar_construction",
        "register_domain",
        "alignment_spotcheck",
        "governance_export",
        "pronunciation",
    ],
    ReviewDecisionKind: ["accept", "reject", "modify", "uncertain", "defer"],
    EntityType: [
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
        "lexeme",
        "sense",
        "concept",
        "form_lexeme",
        "review_task",
        "review_decision",
        # M5-PLAN WP5.2: IGT observation and morphology graph (ADR-0017).
        "igt_observation",
        "feature",
        "morpheme",
        "allomorph",
        "morph_analysis",
        "morph_segment",
        "source_use_approval",
    ],
    AuditEventType: [
        "policy_created",
        "source_registered",
        "raw_ingested",
        "policy_denied",
        # M5-PLAN WP5.2: source-use approval audit trail (ADR-0018).
        "source_use_approved",
        "source_use_withdrawn",
    ],
}


@pytest.mark.parametrize("enum_cls", list(EXPECTED_VALUES))
def test_enum_values_are_frozen(enum_cls: type[Enum]) -> None:
    assert [member.value for member in enum_cls] == EXPECTED_VALUES[enum_cls]


M1_ARTIFACT_KINDS = [
    "ingest_report",
    "extraction_snapshot",
    "alignment_file",
    "cldf_export",
    "benchmark_report",
    "dataset",
    "other",
]


def test_artifact_kind_values_are_append_only() -> None:
    # M1 values keep their order; M2 may only append (ADR-0010, WP2.1).
    assert [member.value for member in ArtifactKind][: len(M1_ARTIFACT_KINDS)] == M1_ARTIFACT_KINDS


M1_LINEAGE_KINDS = [
    "derived_from",
    "generated_from",
    "normalized_from",
    "extracted_from",
    "imported_from",
    "supersedes",
]


def test_lineage_kind_values_are_append_only() -> None:
    # M1 values keep their order; the review service appends `stale_dependent` only
    # (M4-PLAN C10, ADR-0014), with migration 0005 extending the CHECK constraint.
    assert [member.value for member in LineageKind][: len(M1_LINEAGE_KINDS)] == M1_LINEAGE_KINDS


def test_all_enums_are_string_enums() -> None:
    for enum_cls in EXPECTED_VALUES:
        assert all(isinstance(member.value, str) for member in enum_cls)


def test_access_rank_order() -> None:
    assert [access_rank(a) for a in AccessClass] == [0, 1, 2, 3]


def test_most_restrictive() -> None:
    assert most_restrictive([AccessClass.PUBLIC, AccessClass.RESTRICTED]) is AccessClass.RESTRICTED
    assert (
        most_restrictive([AccessClass.HIGHLY_RESTRICTED, AccessClass.COMMUNITY, AccessClass.PUBLIC])
        is AccessClass.HIGHLY_RESTRICTED
    )
    assert most_restrictive([AccessClass.COMMUNITY]) is AccessClass.COMMUNITY


def test_most_restrictive_rejects_empty() -> None:
    with pytest.raises(ValueError):
        most_restrictive([])
