from collections.abc import Iterable
from enum import StrEnum


class PolicyMode(StrEnum):
    DIRECT = "direct"
    DISTILL_ONLY = "distill_only"
    REVIEW_REQUIRED = "review_required"
    RESTRICTED = "restricted"
    ARCHIVE_ONLY = "archive_only"
    EXCLUDE = "exclude"


class Operation(StrEnum):
    INGEST = "ingest"
    READ_RAW = "read_raw"
    EXTRACT = "extract"
    NORMALIZE = "normalize"
    ALIGN = "align"
    DISTILL_LEXICON = "distill_lexicon"
    DISTILL_MORPHOLOGY = "distill_morphology"
    DISTILL_GRAMMAR = "distill_grammar"
    AUDIO_ALIGN = "audio_align"
    HUMAN_REVIEW = "human_review"
    THIRD_PARTY_API = "third_party_api"
    CLOUD_PROCESSING = "cloud_processing"
    REDISTRIBUTE_RAW = "redistribute_raw"
    REDISTRIBUTE_DERIVED = "redistribute_derived"
    DIRECT_TRAINING = "direct_training"
    SYNTHETIC_GENERATION_SUPPORT = "synthetic_generation_support"
    EVALUATION = "evaluation"


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    REVIEW_REQUIRED = "review_required"
    DENY = "deny"


class AccessClass(StrEnum):
    PUBLIC = "public"
    COMMUNITY = "community"
    RESTRICTED = "restricted"
    HIGHLY_RESTRICTED = "highly_restricted"


_ACCESS_RANK: dict[AccessClass, int] = {
    AccessClass.PUBLIC: 0,
    AccessClass.COMMUNITY: 1,
    AccessClass.RESTRICTED: 2,
    AccessClass.HIGHLY_RESTRICTED: 3,
}


def access_rank(access_class: AccessClass) -> int:
    return _ACCESS_RANK[access_class]


def most_restrictive(classes: Iterable[AccessClass]) -> AccessClass:
    ranked = list(classes)
    if not ranked:
        raise ValueError("most_restrictive requires at least one access class")
    return max(ranked, key=access_rank)


class SourceType(StrEnum):
    PARALLEL_TEXT = "parallel_text"
    EDUCATIONAL_PUBLICATION = "educational_publication"
    PUBLICATION = "publication"
    DICTIONARY = "dictionary"
    WORDLIST = "wordlist"
    GRAMMAR_DESCRIPTION = "grammar_description"
    IGT = "igt"
    MONOLINGUAL_TEXT = "monolingual_text"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER = "other"


class SourceStatus(StrEnum):
    REGISTERED = "registered"
    INGESTED = "ingested"
    REVOKED = "revoked"


class RunStage(StrEnum):
    SOURCE_REGISTRATION = "source_registration"
    RAW_INGESTION = "raw_ingestion"
    EXTRACTION = "extraction"
    NORMALIZATION = "normalization"
    TOKENIZATION = "tokenization"
    SEGMENT_ALIGNMENT = "segment_alignment"
    TOKEN_ALIGNMENT = "token_alignment"
    LEXICAL_INDUCTION = "lexical_induction"
    IGT_IMPORT = "igt_import"
    MORPHOLOGY_INDUCTION = "morphology_induction"
    GRAMMAR_EXTRACTION = "grammar_extraction"
    HUMAN_REVIEW = "human_review"
    MANUAL_ANNOTATION = "manual_annotation"
    EXPORT = "export"
    EVALUATION = "evaluation"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunIoRole(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class ArtifactKind(StrEnum):
    INGEST_REPORT = "ingest_report"
    EXTRACTION_SNAPSHOT = "extraction_snapshot"
    ALIGNMENT_FILE = "alignment_file"
    CLDF_EXPORT = "cldf_export"
    BENCHMARK_REPORT = "benchmark_report"
    DATASET = "dataset"
    OTHER = "other"
    EXTRACTION_REPORT = "extraction_report"
    EXTRACTION_ERROR = "extraction_error"
    NORMALIZATION_REPORT = "normalization_report"
    TOKENIZATION_REPORT = "tokenization_report"


class SegmentStatus(StrEnum):
    OK = "ok"
    NORMALIZATION_FAILED = "normalization_failed"


class SpanRepresentation(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"


class AlignmentMode(StrEnum):
    CANONICAL = "canonical"
    HEURISTIC = "heuristic"
    EXPERIMENTAL = "experimental"


class AlignmentStatus(StrEnum):
    # Operational evidence disposition, never linguistic validation (ADR-0011 §2).
    STRUCTURAL = "structural"
    INFERRED = "inferred"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"


class AlignmentDirection(StrEnum):
    FORWARD = "forward"
    REVERSE = "reverse"
    SYMMETRIZED = "symmetrized"


class Symmetrization(StrEnum):
    NONE = "none"
    INTERSECTION = "intersection"
    UNION = "union"


class EvidenceKind(StrEnum):
    DICTIONARY_ASSERTION = "dictionary_assertion"
    TOKEN_ALIGNMENT = "token_alignment"
    SEGMENT_COOCCURRENCE = "segment_cooccurrence"
    IGT_ASSERTION = "igt_assertion"
    GRAMMAR_DESCRIPTION = "grammar_description"
    SPEAKER_REVIEW = "speaker_review"
    MORPHOLOGY_INDUCTION = "morphology_induction"
    RELATED_LANGUAGE_COMPARISON = "related_language_comparison"
    MONOLINGUAL_DISTRIBUTION = "monolingual_distribution"
    MANUAL_ANNOTATION = "manual_annotation"


class EvidencePolarity(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT_ONLY = "context_only"


class LineageKind(StrEnum):
    DERIVED_FROM = "derived_from"
    GENERATED_FROM = "generated_from"
    NORMALIZED_FROM = "normalized_from"
    EXTRACTED_FROM = "extracted_from"
    IMPORTED_FROM = "imported_from"
    SUPERSEDES = "supersedes"
    # Child -> parent flag written by the review service: `to_id` was decided by an
    # authorized review, so `from_id` (a directly dependent record) needs recalculation
    # (M4-PLAN C10, ADR-0014). Full cascading recalculation remains future work.
    STALE_DEPENDENT = "stale_dependent"
    # Parent -> child record of a completed recalculation (M5-PLAN C-2, WP5.14).
    RECALCULATED = "recalculated"


class LifecycleStatus(StrEnum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    VALIDATED = "validated"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


class ValidationBasisKind(StrEnum):
    AUTHORIZED_REVIEWER = "authorized_reviewer"
    AUTHORITATIVE_IMPORT = "authoritative_import"
    EDITORIAL_DECISION = "editorial_decision"


class ReviewTaskType(StrEnum):
    """Queue task kinds (§REVIEW-WORKFLOW.md). M4 services generate lexical types only."""

    LEXICAL_SENSE = "lexical_sense"
    LEMMA = "lemma"
    MORPHOLOGY_SEGMENTATION = "morphology_segmentation"
    MORPHEME_FUNCTION = "morpheme_function"
    GRAMMAR_CONSTRUCTION = "grammar_construction"
    REGISTER_DOMAIN = "register_domain"
    ALIGNMENT_SPOTCHECK = "alignment_spotcheck"
    GOVERNANCE_EXPORT = "governance_export"
    PRONUNCIATION = "pronunciation"


class ReviewDecisionKind(StrEnum):
    """Allowed reviewer dispositions (§REVIEW-WORKFLOW.md). Decisions are immutable."""

    ACCEPT = "accept"
    REJECT = "reject"
    MODIFY = "modify"
    UNCERTAIN = "uncertain"
    DEFER = "defer"


class EntityType(StrEnum):
    SOURCE = "source"
    SOURCE_OBJECT = "source_object"
    PROCESSING_RUN = "processing_run"
    ARTIFACT = "artifact"
    SEGMENT = "segment"
    TOKEN_OCCURRENCE = "token_occurrence"
    FORM = "form"
    EVIDENCE_ITEM = "evidence_item"
    SEGMENT_ALIGNMENT = "segment_alignment"
    TOKEN_ALIGNMENT_EDGE = "token_alignment_edge"
    # M4 lexical evidence and review queue entities (ADR-0013):
    LEXEME = "lexeme"
    SENSE = "sense"
    CONCEPT = "concept"
    FORM_LEXEME = "form_lexeme"
    REVIEW_TASK = "review_task"
    REVIEW_DECISION = "review_decision"
    # M5 IGT observation and morphology graph entities (ADR-0017):
    IGT_OBSERVATION = "igt_observation"
    FEATURE = "feature"
    MORPHEME = "morpheme"
    ALLOMORPH = "allomorph"
    MORPH_ANALYSIS = "morph_analysis"
    MORPH_SEGMENT = "morph_segment"
    SOURCE_USE_APPROVAL = "source_use_approval"


class AuditEventType(StrEnum):
    POLICY_CREATED = "policy_created"
    SOURCE_REGISTERED = "source_registered"
    RAW_INGESTED = "raw_ingested"
    POLICY_DENIED = "policy_denied"
    # Source-use approval audit trail (ADR-0018 §1); `run_id` names the writing run.
    SOURCE_USE_APPROVED = "source_use_approved"
    SOURCE_USE_WITHDRAWN = "source_use_withdrawn"


# M5 IGT and morphology vocabulary (M5-PLAN §6 WP5.2; ADR-0017). Generic names on
# purpose: no language-specific value may appear here (scope fence, ADR-0017).


class MorphRole(StrEnum):
    ROOT = "root"
    LEXICAL_STEM = "lexical_stem"
    DERIVATIONAL_AFFIX = "derivational_affix"
    INFLECTIONAL_AFFIX = "inflectional_affix"
    CLITIC = "clitic"
    REDUPLICANT = "reduplicant"
    BOUND_LEXICAL = "bound_lexical"
    UNKNOWN_BOUND = "unknown_bound"
    UNKNOWN = "unknown"


class AnalysisKind(StrEnum):
    SEGMENTED = "segmented"
    UNSEGMENTED = "unsegmented"


class AllomorphConditioning(StrEnum):
    PHONOLOGICAL = "phonological"
    MORPHOSYNTACTIC = "morphosyntactic"
    LEXICAL = "lexical"
    UNKNOWN = "unknown"


class FormBasis(StrEnum):
    SURFACE = "surface"
    UNDERLYING = "underlying"


class Abstention(StrEnum):
    """Abstention reasons (EVIDENCE-AND-CONFIDENCE.md §Abstention)."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    UNSUPPORTED_LANGUAGE_OR_DOMAIN = "unsupported_language_or_domain"
    HUMAN_REVIEW = "human_review"


class IgtFormat(StrEnum):
    TOOLBOX = "toolbox"
    XIGT = "xigt"


class IgtParseStatus(StrEnum):
    OK = "ok"
    TIER_MISMATCH = "tier_mismatch"
    MISSING_TIER = "missing_tier"
    UNPARSED = "unparsed"


class FeatureAssignmentBasis(StrEnum):
    IGT_GLOSS = "igt_gloss"
    ADAPTER = "adapter"


class ApprovalAction(StrEnum):
    GRANT = "grant"
    WITHDRAW = "withdraw"
