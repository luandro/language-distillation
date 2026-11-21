from typing import ClassVar

from langpipe.domain.enums import Operation, PolicyDecision, RunStage


class LangpipeError(Exception):
    exit_code: ClassVar[int] = 1


class PolicyDenied(LangpipeError):
    exit_code: ClassVar[int] = 3

    def __init__(self, source_id: str, operation: Operation, decision: PolicyDecision) -> None:
        self.source_id = source_id
        self.operation = operation
        self.decision = decision
        super().__init__(
            f"policy denied: source={source_id} operation={operation.value} "
            f"decision={decision.value}"
        )


class SchemaViolation(LangpipeError):
    exit_code: ClassVar[int] = 4

    def __init__(self) -> None:
        super().__init__("schema violation")


class PolicyConflict(SchemaViolation):
    exit_code: ClassVar[int] = 4

    def __init__(self) -> None:
        LangpipeError.__init__(self, "policy conflict")


class HashMismatch(LangpipeError):
    exit_code: ClassVar[int] = 5

    def __init__(self, sha256_expected: str, sha256_actual: str | None) -> None:
        self.sha256_expected = sha256_expected
        self.sha256_actual = sha256_actual
        super().__init__(
            f"hash mismatch: expected={sha256_expected} actual={sha256_actual or 'none'}"
        )


class SourceChanged(HashMismatch):
    exit_code: ClassVar[int] = 5


class ObjectMissing(LangpipeError):
    exit_code: ClassVar[int] = 5

    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(f"object missing: sha256={sha256}")


class SourceConflict(LangpipeError):
    exit_code: ClassVar[int] = 6

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"source conflict: key={key}")


class NotFound(LangpipeError):
    exit_code: ClassVar[int] = 7

    def __init__(self, entity_type: str, id: str) -> None:
        self.entity_type = entity_type
        self.id = id
        super().__init__(f"not found: entity={entity_type} id={id}")


class InvalidLineage(LangpipeError):
    exit_code: ClassVar[int] = 8

    def __init__(self) -> None:
        super().__init__("invalid lineage")


class InvalidTransition(LangpipeError):
    exit_code: ClassVar[int] = 8

    def __init__(self) -> None:
        super().__init__("invalid lifecycle transition")


class InvalidId(LangpipeError):
    exit_code: ClassVar[int] = 4

    def __init__(self) -> None:
        super().__init__("invalid identifier")


class ImmutableViolation(LangpipeError):
    exit_code: ClassVar[int] = 8

    def __init__(self) -> None:
        super().__init__("immutable object violation")


UNSUPPORTED_SOURCE_REASONS = frozenset(
    {"no_extractor", "igt_not_in_m2", "pkf_not_supported", "no_usfm_files", "language_ambiguous"}
)
EXTRACTION_FAILURE_CODES = frozenset(
    {
        "decode_error",
        "tsv_header_invalid",
        "tsv_language_column_unknown",
        "tsv_ragged_row",
        "usfm_missing_id",
        "usfm_verse_before_chapter",
        "usfm_unclosed_note",
        "usfm_bad_chapter",
        "usfm_bad_verse",
        # A CLDF dataset that pycldf refused to validate (WP4.10 §2.3 step 7).
        "cldf_invalid",
        # WP5.6 IGT readers (§7.6): whole-document refusals raised before parsing.
        "xml_too_large",
        "size_limit_exceeded",
        "xml_malformed",
        "xml_entity_expansion_refused",
    }
)


class UnsupportedSource(LangpipeError):
    exit_code: ClassVar[int] = 9

    def __init__(self, reason: str) -> None:
        if reason not in UNSUPPORTED_SOURCE_REASONS:
            raise ValueError("unknown unsupported-source reason code")
        self.reason = reason
        super().__init__(f"unsupported source: reason={reason}")


class SourceNotIngested(LangpipeError):
    exit_code: ClassVar[int] = 9

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        super().__init__(f"source not ingested: source={source_id}")


class ExtractionFailed(LangpipeError):
    exit_code: ClassVar[int] = 10

    def __init__(self, code: str, source_object_id: str, line: int | None) -> None:
        if code not in EXTRACTION_FAILURE_CODES:
            raise ValueError("unknown extraction failure code")
        self.code = code
        self.source_object_id = source_object_id
        self.line = line
        line_text = "none" if line is None else str(line)
        super().__init__(
            f"extraction failed: code={code} source_object={source_object_id} line={line_text}"
        )


class NormalizationFailed(LangpipeError):
    exit_code: ClassVar[int] = 10

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"normalization failed: code={code}")


class AmbiguousInput(LangpipeError):
    exit_code: ClassVar[int] = 11

    def __init__(self, stage: RunStage, count: int) -> None:
        self.stage = stage
        self.count = count
        super().__init__(f"ambiguous input: stage={stage.value} count={count}")


ALIGNMENT_FAILURE_CODES = frozenset(
    {
        "unknown_method",
        "invalid_coordinates",
        "incompatible_versification",
        "duplicate_book",
        "ambiguous_coordinates",
        "missing_tokenization",
        "incompatible_runs",
        "invalid_adapter_output",
        "backend_unavailable",
        "backend_failed",
        "backend_timeout",
        "unsupported_seed",
        "authorization_invalid",
        "invalid_gold",
    }
)


class AlignmentFailed(LangpipeError):
    exit_code: ClassVar[int] = 12

    def __init__(self, code: str) -> None:
        if code not in ALIGNMENT_FAILURE_CODES:
            raise ValueError("unknown alignment failure code")
        self.code = code
        super().__init__(f"alignment failed: code={code}")


class NoEligibleRecords(LangpipeError):
    """Nothing is eligible for export under current governance policies (WP4.10 D8).

    Fixed message, no payload: a form, a gloss or an identifier would leak what the
    steward was not allowed to export in the first place.
    """

    exit_code: ClassVar[int] = 13

    def __init__(self) -> None:
        super().__init__("no records are eligible for export under current governance policies")


class BenchmarkLeakage(LangpipeError):
    """Refusal when held-out gold data leaked into evaluated run inventory (ADR-0019)."""

    exit_code: ClassVar[int] = 14

    def __init__(self, message: str = "benchmark leakage detected") -> None:
        super().__init__(message)


class GoldAlignmentError(LangpipeError):
    """Refusal when gold morphemes cannot be aligned to word surface."""

    exit_code: ClassVar[int] = 15

    def __init__(
        self, message: str = "gold morphemes could not be aligned to word surface"
    ) -> None:
        super().__init__(message)
