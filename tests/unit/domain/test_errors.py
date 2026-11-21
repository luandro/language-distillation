import pytest

from langpipe.domain import errors
from langpipe.domain.enums import Operation, PolicyDecision, RunStage
from langpipe.domain.errors import (
    AmbiguousInput,
    ExtractionFailed,
    HashMismatch,
    ImmutableViolation,
    InvalidId,
    InvalidLineage,
    InvalidTransition,
    LangpipeError,
    NormalizationFailed,
    NotFound,
    ObjectMissing,
    PolicyConflict,
    PolicyDenied,
    SchemaViolation,
    SourceChanged,
    SourceConflict,
    SourceNotIngested,
    UnsupportedSource,
)

EXPECTED_EXIT_CODES: dict[type[LangpipeError], int] = {
    LangpipeError: 1,
    PolicyDenied: 3,
    SchemaViolation: 4,
    PolicyConflict: 4,
    HashMismatch: 5,
    SourceChanged: 5,
    ObjectMissing: 5,
    SourceConflict: 6,
    NotFound: 7,
    InvalidLineage: 8,
    InvalidTransition: 8,
    InvalidId: 4,
    ImmutableViolation: 8,
    UnsupportedSource: 9,
    SourceNotIngested: 9,
    ExtractionFailed: 10,
    NormalizationFailed: 10,
    AmbiguousInput: 11,
}


def test_exit_codes() -> None:
    for error_cls, code in EXPECTED_EXIT_CODES.items():
        assert error_cls.exit_code == code, error_cls.__name__


def test_all_errors_subclass_langpipe_error() -> None:
    for name in dir(errors):
        obj = getattr(errors, name)
        if isinstance(obj, type) and issubclass(obj, Exception) and obj is not Exception:
            assert issubclass(obj, LangpipeError), name


def test_policy_denied_message_contains_only_ids_and_enums() -> None:
    error = PolicyDenied(
        "src_01M4Q2CBK756EX2Y10QTP6SXM4", Operation.DIRECT_TRAINING, PolicyDecision.DENY
    )
    assert str(error) == (
        "policy denied: source=src_01M4Q2CBK756EX2Y10QTP6SXM4 "
        "operation=direct_training decision=deny"
    )
    assert error.source_id == "src_01M4Q2CBK756EX2Y10QTP6SXM4"
    assert error.operation is Operation.DIRECT_TRAINING
    assert error.decision is PolicyDecision.DENY


def test_hash_mismatch_message_contains_only_hashes() -> None:
    expected = "a" * 64
    error = HashMismatch(expected, None)
    assert str(error) == f"hash mismatch: expected={expected} actual=none"
    assert error.sha256_expected == expected
    assert error.sha256_actual is None


def test_source_changed_is_hash_mismatch() -> None:
    error = SourceChanged("a" * 64, "b" * 64)
    assert isinstance(error, HashMismatch)
    assert error.exit_code == 5


def test_not_found_and_conflict_messages() -> None:
    assert str(NotFound("source", "src_x")) == "not found: entity=source id=src_x"
    assert str(SourceConflict("key-1")) == "source conflict: key=key-1"
    assert str(ObjectMissing("c" * 64)) == f"object missing: sha256={'c' * 64}"


def test_policy_conflict_is_schema_violation() -> None:
    assert isinstance(PolicyConflict(), SchemaViolation)


def test_new_errors_have_safe_messages() -> None:
    assert str(UnsupportedSource("no_extractor")) == "unsupported source: reason=no_extractor"
    assert str(SourceNotIngested("src_x")) == "source not ingested: source=src_x"
    assert (
        str(ExtractionFailed("decode_error", "sobj_x", 3))
        == "extraction failed: code=decode_error source_object=sobj_x line=3"
    )
    assert (
        str(ExtractionFailed("usfm_bad_verse", "sobj_x", None))
        == "extraction failed: code=usfm_bad_verse source_object=sobj_x line=none"
    )
    assert str(NormalizationFailed("rule_failed")) == "normalization failed: code=rule_failed"
    assert (
        str(AmbiguousInput(RunStage.EXTRACTION, 2)) == "ambiguous input: stage=extraction count=2"
    )


def test_unsupported_source_rejects_unknown_reason() -> None:
    with pytest.raises(ValueError):
        UnsupportedSource("free text with the source's own words")


def test_extraction_failed_rejects_unknown_code() -> None:
    with pytest.raises(ValueError):
        ExtractionFailed("free text", "sobj_x", None)
