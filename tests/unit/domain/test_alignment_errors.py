import pytest

from langpipe.domain.errors import ALIGNMENT_FAILURE_CODES, AlignmentFailed, LangpipeError

EXPECTED_CODES = {
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


def test_alignment_failed_exit_code_is_twelve() -> None:
    assert AlignmentFailed.exit_code == 12
    assert issubclass(AlignmentFailed, LangpipeError)


def test_alignment_failure_allowlist_is_frozen_and_exact() -> None:
    assert isinstance(ALIGNMENT_FAILURE_CODES, frozenset)
    assert ALIGNMENT_FAILURE_CODES == EXPECTED_CODES


def test_alignment_error_never_echoes_payload() -> None:
    for code in sorted(ALIGNMENT_FAILURE_CODES):
        error = AlignmentFailed(code)
        assert str(error) == f"alignment failed: code={code}"
        assert error.code == code
    # Free text, exception details and user content cannot enter the message:
    # the only constructor argument is a code validated against the allowlist.
    with pytest.raises(ValueError):
        AlignmentFailed("Connection to db.example.com failed: password=hunter2")
    with pytest.raises(ValueError):
        AlignmentFailed("")


def test_alignment_error_has_no_message_parameter() -> None:
    error = AlignmentFailed("backend_failed")
    with pytest.raises(TypeError):
        AlignmentFailed("backend_failed", "stderr: SEGRET native output")  # type: ignore[misc]
    assert "SEGRET" not in str(error)
