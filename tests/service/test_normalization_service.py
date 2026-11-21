"""NormalizationService (M2 WP2.10): extracted raw segments -> derived normalized segments."""

import json
from pathlib import Path
from typing import ClassVar

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AuditEventType,
    EntityType,
    LineageKind,
    RunIoRole,
    RunStage,
    RunStatus,
    SegmentStatus,
    SourceStatus,
)
from langpipe.domain.errors import AmbiguousInput, PolicyDenied, SchemaViolation
from langpipe.extraction.plain_lines import PlainLinesExtractor
from langpipe.extraction.service import ExtractionResult, extract_source
from langpipe.extraction.tsv import TsvExtractor
from langpipe.extraction.usfm import UsfmExtractor
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.normalization.base import NormalizationResult
from langpipe.normalization.profiles import GENERIC_NORMALIZATION_PROFILES, DefaultTextProfile
from langpipe.normalization.service import (
    NormalizationResultSummary,
    normalize_extraction,
    select_extraction_run,
)
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.base import TokenOutput
from langpipe.tokenization.service import TokenizationSummary, tokenize_normalization
from langpipe.tokenization.whitespace_punct import WhitespacePunctTokenizer
from tests.service.manifests import (
    manifest_data,
    raise_on,
    record_finished_runs,
    state_counts,
    write_manifest,
    write_origin_file,
)

GOLDEN_SOURCES = Path(__file__).resolve().parents[1] / "golden" / "fixture" / "sources"
PLAIN = "text/plain"
EXTRACTABLE_GOLDEN = (
    "01-parallel-distill",
    "02-educational-direct",
    "05-monolingual",
)


def _write_source(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    objects: list[dict[str, object]],
    *,
    mode: str = "direct",
    source_type: str = "monolingual_text",
    languages: tuple[str, ...] = ("qaa",),
    allow: list[str] | None = None,
    deny: list[str] | None = None,
) -> RegistrationResult:
    overrides: dict[str, object] = {}
    if allow is not None:
        overrides["allow"] = allow
    if deny is not None:
        overrides["deny"] = deny
    data = manifest_data(key=key, mode=mode, objects=objects, **overrides)
    data["source_type"] = source_type
    data["languages"] = list(languages)
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _extract_golden(ctx: AppContext, dirname: str) -> tuple[RegistrationResult, ExtractionResult]:
    registered = register_source(ctx, GOLDEN_SOURCES / dirname / "manifest.yaml")
    ingest_source(ctx, registered.source.key)
    return registered, extract_source(ctx, registered.source.id)


def _extract_text(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    text: str,
    *,
    mode: str = "direct",
    languages: tuple[str, ...] = ("qaa",),
    allow: list[str] | None = None,
    deny: list[str] | None = None,
) -> tuple[RegistrationResult, ExtractionResult]:
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, text.encode("utf-8"))
    registered = _write_source(
        ctx,
        tmp_path,
        key,
        [{"path": relative, "media_type": PLAIN}],
        mode=mode,
        languages=languages,
        allow=allow,
        deny=deny,
    )
    ingest_source(ctx, registered.source.id)
    return registered, extract_source(ctx, registered.source.id)


def test_normalization_and_tokenization_failure_finish_run_without_outputs(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, extraction = _extract_text(ctx, tmp_path, "fail-norm", "kanu mabi")
    finished = record_finished_runs(ctx, monkeypatch)
    segments_before = ctx.repo.count(EntityType.SEGMENT)

    with (
        raise_on(ctx.artifact_store, "put_bytes", SchemaViolation()),
        pytest.raises(SchemaViolation),
    ):
        normalize_extraction(ctx, extraction.run.id)

    failed = [run for run in finished if run.status is RunStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].stage is RunStage.NORMALIZATION
    assert ctx.repo.count(EntityType.SEGMENT) == segments_before
    assert ctx.repo.list_segments_for_run(failed[0].id) == []
    assert ctx.repo.list_run_io(failed[0].id) == []

    summary = normalize_extraction(ctx, extraction.run.id)
    finished.clear()
    tokens_before = ctx.repo.count(EntityType.TOKEN_OCCURRENCE)

    with (
        raise_on(ctx.artifact_store, "put_bytes", SchemaViolation()),
        pytest.raises(SchemaViolation),
    ):
        tokenize_normalization(ctx, summary.run.id)

    failed = [run for run in finished if run.status is RunStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].stage is RunStage.TOKENIZATION
    assert ctx.repo.count(EntityType.TOKEN_OCCURRENCE) == tokens_before
    assert ctx.repo.list_run_io(failed[0].id) == []


def test_empty_and_all_failed_runs_keep_source_identity_and_policy_gate(
    ctx: AppContext, tmp_path: Path
) -> None:
    # Empty extraction output: ancestry comes from the extraction run inputs, so the gate fires.
    _, empty = _extract_text(ctx, tmp_path, "empty-src", "", deny=["normalize"])
    assert ctx.repo.list_segments_for_run(empty.run.id) == []
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        normalize_extraction(ctx, empty.run.id)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}

    # All segments fail normalization: identity is kept and tokenization still yields no tokens.
    _, extraction = _extract_text(ctx, tmp_path, "failed-src", "\ufffd\n\ufffd")
    summary = normalize_extraction(ctx, extraction.run.id)

    assert summary.segments == 2
    assert summary.failed == 2
    token_summary = tokenize_normalization(ctx, summary.run.id)
    assert token_summary.tokens == 0
    assert token_summary.skipped_failed_segments == 2


@pytest.mark.parametrize("dirname", EXTRACTABLE_GOLDEN)
def test_normalized_segment_raw_text_identical_to_extracted(ctx: AppContext, dirname: str) -> None:
    _, extraction = _extract_golden(ctx, dirname)
    raw = {segment.id: segment for segment in ctx.repo.list_segments_for_run(extraction.run.id)}

    summary = normalize_extraction(ctx, extraction.run.id)

    normalized = ctx.repo.list_segments_for_run(summary.run.id)
    assert normalized
    for segment in normalized:
        parents = [
            edge.to_id
            for edge in ctx.repo.list_lineage_edges(segment.id, "out")
            if edge.kind is LineageKind.NORMALIZED_FROM
        ]
        assert len(parents) == 1
        assert segment.raw_text == raw[parents[0]].raw_text


def test_normalization_creates_normalized_from_edges_and_run_io(ctx: AppContext) -> None:
    _, extraction = _extract_golden(ctx, "01-parallel-distill")
    raw = ctx.repo.list_segments_for_run(extraction.run.id)

    summary = normalize_extraction(ctx, extraction.run.id)

    normalized = ctx.repo.list_segments_for_run(summary.run.id)
    assert len(normalized) == len(raw) == 8
    for segment in normalized:
        edges = ctx.repo.list_lineage_edges(segment.id, "out")
        assert len(edges) == 1
        edge = edges[0]
        assert edge.kind is LineageKind.NORMALIZED_FROM
        assert edge.run_id == summary.run.id
    run_io = set(ctx.repo.list_run_io(summary.run.id))
    for segment in raw:
        assert (segment.id, RunIoRole.INPUT) in run_io
    for segment in normalized:
        assert (segment.id, RunIoRole.OUTPUT) in run_io
    assert summary.report is not None
    assert (summary.report.id, RunIoRole.OUTPUT) in run_io

    artifact_edges = ctx.repo.list_lineage_edges(summary.report.id, "out")
    assert {edge.to_id for edge in artifact_edges} == {segment.id for segment in normalized}
    assert all(edge.kind is LineageKind.DERIVED_FROM for edge in artifact_edges)
    assert all(edge.run_id == summary.run.id for edge in artifact_edges)


def test_normalization_failed_segment_status_and_report_code(
    ctx: AppContext, tmp_path: Path
) -> None:
    _, extraction = _extract_text(ctx, tmp_path, "fffd-src", "\ufffd")

    summary = normalize_extraction(ctx, extraction.run.id)

    assert summary.segments == 1
    assert summary.failed == 1
    segments = ctx.repo.list_segments_for_run(summary.run.id)
    assert len(segments) == 1
    segment = segments[0]
    assert segment.status is SegmentStatus.NORMALIZATION_FAILED
    assert segment.normalized_text is None
    assert segment.normalization_profile is None
    assert segment.raw_text == "\ufffd"

    assert summary.report is not None
    payload = json.loads(ctx.artifact_store.read_bytes(summary.report.sha256))
    assert payload["failure_codes"] == {"replacement_char": 1}
    assert payload["segments"][0]["status"] == "normalization_failed"
    assert payload["segments"][0]["raw_segment_id"] != segment.id


def test_normalization_rerun_idempotent(ctx: AppContext) -> None:
    _, extraction = _extract_golden(ctx, "05-monolingual")
    first = normalize_extraction(ctx, extraction.run.id)
    before = state_counts(ctx)

    second = normalize_extraction(ctx, extraction.run.id)

    assert isinstance(second, NormalizationResultSummary)
    assert second.reused is True
    assert second.run == first.run
    assert second.segments == first.segments
    assert second.failed == first.failed
    assert second.report == first.report
    assert state_counts(ctx) == before


class _DefaultTextV2(DefaultTextProfile):
    version: ClassVar[str] = "0.1.1"


def test_profile_version_change_creates_new_run_leaves_old_rows(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, extraction = _extract_golden(ctx, "05-monolingual")
    first = normalize_extraction(ctx, extraction.run.id)

    patched = VersionedRegistry((*GENERIC_NORMALIZATION_PROFILES, _DefaultTextV2()))
    monkeypatch.setattr("langpipe.normalization.service.NORMALIZATION_PROFILES", patched)

    second = normalize_extraction(ctx, extraction.run.id, profiles={"qaa": "default_text@0.1.1"})

    assert second.reused is False
    assert second.run.id != first.run.id
    assert len(ctx.repo.list_segments_for_run(first.run.id)) == first.segments
    assert len(ctx.repo.list_segments_for_run(second.run.id)) == second.segments
    assert all(
        segment.normalization_profile == "default_text@0.1.0"
        for segment in ctx.repo.list_segments_for_run(first.run.id)
    )
    assert all(
        segment.normalization_profile == "default_text@0.1.1"
        for segment in ctx.repo.list_segments_for_run(second.run.id)
    )


class _TsvV2(TsvExtractor):
    version: ClassVar[str] = "0.1.1"


def test_select_extraction_run_ambiguous_raises(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered, first = _extract_golden(ctx, "01-parallel-distill")

    patched = VersionedRegistry((TsvExtractor(), PlainLinesExtractor(), UsfmExtractor(), _TsvV2()))
    monkeypatch.setattr("langpipe.extraction.service.EXTRACTORS", patched)
    extract_source(ctx, registered.source.id, extractor="tsv@0.1.1")

    with pytest.raises(AmbiguousInput) as info:
        select_extraction_run(ctx, registered.source, None)

    assert info.value.stage is RunStage.EXTRACTION
    assert info.value.count == 2
    assert select_extraction_run(ctx, registered.source, first.run.id) == first.run


def test_normalize_denied_for_review_required_source_writes_nothing(
    ctx: AppContext, tmp_path: Path
) -> None:
    # review_required denies NORMALIZE by default; allowing only EXTRACT lets the raw rows exist.
    _, extraction = _extract_text(
        ctx, tmp_path, "review-src", "kanu mabi", mode="review_required", allow=["extract"]
    )
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        normalize_extraction(ctx, extraction.run.id)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    assert ctx.repo.list_segments_for_run(extraction.run.id)


class _BoomProfile(DefaultTextProfile):
    """Fails if any pure normalization work runs: the policy gate must precede it."""

    def normalize(self, raw: str) -> NormalizationResult:
        raise AssertionError("normalization pure work ran before the policy gate")


class _BoomTokenizer(WhitespacePunctTokenizer):
    """Fails if any pure tokenization work runs: the policy gate must precede it."""

    def tokenize(self, normalized: str) -> tuple[TokenOutput, ...]:
        raise AssertionError("tokenizer pure work ran before the policy gate")


def _revoke(ctx: AppContext, source_id: str) -> None:
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())


def _denial_only_audit(ctx: AppContext, before: dict[str, int]) -> None:
    new_events = ctx.repo.list_audit_events()[before["audit"] :]
    assert len(new_events) == 1
    assert new_events[0].event_type is AuditEventType.POLICY_DENIED


def _patch_tokenization_spies(monkeypatch: pytest.MonkeyPatch) -> None:
    # Any pure work on the denial path would raise, so the test only ever sees PolicyDenied.
    monkeypatch.setattr(
        "langpipe.tokenization.service.NORMALIZATION_PROFILES",
        VersionedRegistry((_BoomProfile(),)),
    )
    monkeypatch.setattr(
        "langpipe.tokenization.service.TOKENIZERS",
        VersionedRegistry((_BoomTokenizer(),)),
    )


def _extract_kind(
    ctx: AppContext, tmp_path: Path, kind: str
) -> tuple[RegistrationResult, ExtractionResult]:
    if kind == "empty":
        return _extract_text(ctx, tmp_path, "kind-empty", "")
    if kind == "all-failed":
        return _extract_text(ctx, tmp_path, "kind-failed", "\ufffd\n\ufffd")
    return _extract_text(ctx, tmp_path, "kind-nonempty", "kanu mabi")


def test_empty_sources_keep_distinct_run_identity_and_reuse(
    ctx: AppContext, tmp_path: Path
) -> None:
    # Two independently registered, allowed sources that extract zero segments must still produce
    # distinct normalization and tokenization runs; repeating an invocation reuses its own run.
    _, extraction_a = _extract_text(ctx, tmp_path, "empty-alpha", "")
    _, extraction_b = _extract_text(ctx, tmp_path, "empty-beta", "")
    assert extraction_a.run.id != extraction_b.run.id
    assert ctx.repo.list_segments_for_run(extraction_a.run.id) == []
    assert ctx.repo.list_segments_for_run(extraction_b.run.id) == []

    normalization_a = normalize_extraction(ctx, extraction_a.run.id)
    normalization_b = normalize_extraction(ctx, extraction_b.run.id)

    assert normalization_a.reused is False and normalization_b.reused is False
    assert normalization_a.run.id != normalization_b.run.id
    assert normalization_a.run.config["extraction_run_id"] == extraction_a.run.id
    assert normalization_b.run.config["extraction_run_id"] == extraction_b.run.id
    assert normalization_a.segments == normalization_b.segments == 0
    assert normalization_a.failed == normalization_b.failed == 0
    assert ctx.repo.list_segments_for_run(normalization_a.run.id) == []
    assert ctx.repo.list_segments_for_run(normalization_b.run.id) == []

    tokenization_a = tokenize_normalization(ctx, normalization_a.run.id)
    tokenization_b = tokenize_normalization(ctx, normalization_b.run.id)

    assert tokenization_a.reused is False and tokenization_b.reused is False
    assert tokenization_a.run.id != tokenization_b.run.id
    assert tokenization_a.run.config["normalization_run_id"] == normalization_a.run.id
    assert tokenization_b.run.config["normalization_run_id"] == normalization_b.run.id
    assert tokenization_a.tokens == tokenization_b.tokens == 0
    assert tokenization_a.forms == tokenization_b.forms == 0
    assert tokenization_a.skipped_failed_segments == tokenization_b.skipped_failed_segments == 0

    before = state_counts(ctx)
    normalization_a2 = normalize_extraction(ctx, extraction_a.run.id)
    normalization_b2 = normalize_extraction(ctx, extraction_b.run.id)
    tokenization_a2 = tokenize_normalization(ctx, normalization_a.run.id)
    tokenization_b2 = tokenize_normalization(ctx, normalization_b.run.id)

    assert normalization_a2.reused is True and normalization_a2.run == normalization_a.run
    assert normalization_b2.reused is True and normalization_b2.run == normalization_b.run
    assert normalization_a2.segments == normalization_a2.failed == 0
    assert normalization_b2.segments == normalization_b2.failed == 0
    assert normalization_a2.report == normalization_a.report
    assert normalization_b2.report == normalization_b.report
    assert tokenization_a2.reused is True and tokenization_a2.run == tokenization_a.run
    assert tokenization_b2.reused is True and tokenization_b2.run == tokenization_b.run
    assert tokenization_a2.report == tokenization_a.report
    assert tokenization_b2.report == tokenization_b.report
    assert (
        tokenization_a2.tokens
        == tokenization_a2.forms
        == tokenization_a2.skipped_failed_segments
        == 0
    )
    assert (
        tokenization_b2.tokens
        == tokenization_b2.forms
        == tokenization_b2.skipped_failed_segments
        == 0
    )
    assert state_counts(ctx) == before


@pytest.mark.parametrize("kind", ["nonempty", "empty", "all-failed"])
def test_normalization_denied_before_work_and_before_reuse(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    # A revocation after outputs exist must deny and must not fall through to the reuse return.
    _, extraction = _extract_kind(ctx, tmp_path, kind)
    established = normalize_extraction(ctx, extraction.run.id)
    if kind == "empty":
        assert established.segments == 0
    elif kind == "all-failed":
        assert established.failed == 2
    else:
        assert established.segments == 1 and established.failed == 0

    _revoke(ctx, extraction.source.id)
    before = state_counts(ctx)
    monkeypatch.setattr(
        "langpipe.normalization.service.NORMALIZATION_PROFILES",
        VersionedRegistry((_BoomProfile(),)),
    )

    with (
        raise_on(ctx.artifact_store, "put_bytes", AssertionError("artifact storage before gate")),
        pytest.raises(PolicyDenied),
    ):
        normalize_extraction(ctx, extraction.run.id)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    _denial_only_audit(ctx, before)


@pytest.mark.parametrize("kind", ["nonempty", "empty", "all-failed"])
def test_tokenization_denied_before_first_run(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _, extraction = _extract_kind(ctx, tmp_path, kind)
    normalization = normalize_extraction(ctx, extraction.run.id)

    _revoke(ctx, extraction.source.id)
    before = state_counts(ctx)
    _patch_tokenization_spies(monkeypatch)

    with (
        raise_on(ctx.artifact_store, "put_bytes", AssertionError("artifact storage before gate")),
        pytest.raises(PolicyDenied),
    ):
        tokenize_normalization(ctx, normalization.run.id)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    _denial_only_audit(ctx, before)


@pytest.mark.parametrize("kind", ["nonempty", "empty", "all-failed"])
def test_tokenization_denied_after_succeeded_run_is_not_reused(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _, extraction = _extract_kind(ctx, tmp_path, kind)
    normalization = normalize_extraction(ctx, extraction.run.id)
    first = tokenize_normalization(ctx, normalization.run.id)
    assert first.reused is False

    _revoke(ctx, extraction.source.id)
    before = state_counts(ctx)
    _patch_tokenization_spies(monkeypatch)

    with (
        raise_on(ctx.artifact_store, "put_bytes", AssertionError("artifact storage before gate")),
        pytest.raises(PolicyDenied),
    ):
        tokenize_normalization(ctx, normalization.run.id)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    _denial_only_audit(ctx, before)
    # The gate precedes the reuse return: the succeeded run is still there, untouched.
    assert ctx.repo.get_run(first.run.id) == first.run


def test_all_failed_tokenization_inputs_skips_and_reuse(ctx: AppContext, tmp_path: Path) -> None:
    _, extraction = _extract_text(ctx, tmp_path, "failed-all", "\ufffd\n\ufffd")
    normalization = normalize_extraction(ctx, extraction.run.id)
    assert normalization.segments == 2 and normalization.failed == 2
    failed_ids = {segment.id for segment in ctx.repo.list_segments_for_run(normalization.run.id)}
    assert len(failed_ids) == 2

    summary = tokenize_normalization(ctx, normalization.run.id)

    assert isinstance(summary, TokenizationSummary)
    assert summary.tokens == 0
    assert summary.forms == 0
    assert summary.skipped_failed_segments == 2
    assert summary.run.config["normalization_run_id"] == normalization.run.id
    run_inputs = {
        object_id
        for object_id, role in ctx.repo.list_run_io(summary.run.id)
        if role is RunIoRole.INPUT
    }
    assert failed_ids <= run_inputs

    assert summary.report is not None
    payload = json.loads(ctx.artifact_store.read_bytes(summary.report.sha256))
    assert {row["segment_id"] for row in payload["skipped"]} == failed_ids
    assert all(row["reason"] == "normalization_failed" for row in payload["skipped"])
    assert payload["totals"]["tokens"] == 0
    assert payload["totals"]["skipped"] == 2

    before = state_counts(ctx)
    second = tokenize_normalization(ctx, normalization.run.id)
    assert second.reused is True
    assert second.run == summary.run
    assert second.tokens == 0
    assert second.skipped_failed_segments == 2
    assert second.report == summary.report
    assert state_counts(ctx) == before
