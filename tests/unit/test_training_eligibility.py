"""Tests for the NLLB training data-eligibility gate."""

from __future__ import annotations

from langpipe.training.eligibility import (
    REASON_MISSING_TRACEABILITY,
    filter_eligible,
)


def test_corpus_provenance_is_eligible() -> None:
    # ADR-0025 removed the provenance blocklist: repo data is trainable.
    row = {"policy_id": "p-1", "provenance": "corpus:GEN", "source": "a", "target": "b"}
    eligible, rejected = filter_eligible([row])
    assert eligible == [row]
    assert rejected == []


def test_harvested_provenance_is_eligible() -> None:
    row = {"policy_id": "p-2", "provenance": "harvested:zenodo_1008779_cesarino_2026"}
    eligible, rejected = filter_eligible([row])
    assert eligible == [row]
    assert rejected == []


def test_distill_only_policy_id_is_eligible() -> None:
    row = {"policy_id": "pol_distill", "provenance": "corpus:JHN"}
    eligible, _rejected = filter_eligible([row])
    assert eligible == [row]


def test_row_with_only_provenance_is_eligible() -> None:
    row = {"provenance": "synthetic:curriculum"}
    eligible, rejected = filter_eligible([row])
    assert eligible == [row]
    assert rejected == []


def test_row_with_only_source_id_is_eligible() -> None:
    row = {"source_id": "src_01ABC"}
    eligible, _rejected = filter_eligible([row])
    assert eligible == [row]


def test_row_with_no_trace_id_is_rejected() -> None:
    eligible, rejected = filter_eligible([{"source": "a", "target": "b"}])
    assert eligible == []
    assert rejected[0]["rejection_reason"] == REASON_MISSING_TRACEABILITY


def test_blank_trace_ids_are_rejected() -> None:
    eligible, rejected = filter_eligible([{"policy_id": "   ", "source_id": "", "provenance": " "}])
    assert eligible == []
    assert rejected[0]["rejection_reason"] == REASON_MISSING_TRACEABILITY


def test_empty_list_returns_empty_pair() -> None:
    assert filter_eligible([]) == ([], [])


def test_rejected_rows_carry_reason_and_inputs_are_not_mutated() -> None:
    row = {"source": "a", "target": "b"}
    eligible, rejected = filter_eligible([row, {"provenance": "corpus:JHN"}])
    assert "rejection_reason" not in row
    assert len(eligible) == 1
    assert rejected[0]["rejection_reason"] == REASON_MISSING_TRACEABILITY
    # The rejected copy keeps every original field.
    assert rejected[0]["source"] == "a"
    assert rejected[0]["target"] == "b"
