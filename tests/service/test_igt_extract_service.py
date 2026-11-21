"""Stage 7a integration tests: `IgtExtractService` (M5 WP5.7, Gate 36).

Contracts under test:
- Governance: `READ_RAW` and `EXTRACT` via `effective_policy` under sorted source row locks;
  denial records `POLICY_DENIED`, no run.
- Reads verified raw bytes; resolves reader by media type (`text/plain` -> `toolbox_igt@0.1.0`,
  `application/xml`/`text/xml` -> `xigt_xml@0.1.0`) or explicit `--reader`.
- Persists per record: one `IGTObservation` and, when a text tier exists, one `Segment`;
  the observation references the segment. Lineage: segment and observation `extracted_from`
  the source object.
- Run: `RunStage.EXTRACTION`, tool `langpipe.igt-extract`, config pins reader + profile + languages;
  idempotent reuse by config/input hash; whole-run rollback on failure.
- Report `igt-extraction-report` v1 (`EXTRACTION_REPORT`): schema, schema_version, run_id,
  readers, source_object_ids, records, parse_status_counts, segments, words, morphs,
  unknown_marker_counts. IDs/counts only.
- Chain proof: M2 `normalize_extraction` + `tokenize_normalization` accept the run and
  produce tokens for IGT segments.
"""

import json
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    ArtifactKind,
    AuditEventType,
    IgtParseStatus,
    LineageKind,
    RunStage,
    RunStatus,
)
from langpipe.domain.errors import (
    PolicyDenied,
    SchemaViolation,
    SourceNotIngested,
    UnsupportedSource,
)
from langpipe.igt.service import IgtExtractResult, IgtExtractService, extract_igt
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.normalization.service import normalize_extraction
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import (
    manifest_data,
    write_manifest,
    write_origin_file,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "igt"
SAMPLE_TOOLBOX = FIXTURES / "toolbox_sample.txt"
SAMPLE_XIGT = FIXTURES / "sample.xigt.xml"
SAMPLE_MISSING = FIXTURES / "toolbox_missing_text.txt"


def _setup_source(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    fixture_path: Path,
    media_type: str = "text/plain",
    *,
    mode: str = "direct",
    languages: list[str] | None = None,
    access_class: str = "public",
) -> RegistrationResult:
    relative = f"texts/{key}.dat"
    write_origin_file(tmp_path, relative, fixture_path.read_bytes())
    data = manifest_data(
        key=key,
        mode=mode,
        access_class=access_class,
        objects=[{"path": relative, "media_type": media_type}],
    )
    data["source_type"] = "igt"
    data["languages"] = languages or ["qaa", "por"]
    reg = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    return reg


def test_igt_extract_toolbox_happy_path(ctx: AppContext, tmp_path: Path) -> None:
    reg = _setup_source(ctx, tmp_path, "tb-happy", SAMPLE_TOOLBOX, "text/plain")
    ingest_source(ctx, reg.source.id)

    service = IgtExtractService(ctx)
    res = service.extract(reg.source.id)

    assert isinstance(res, IgtExtractResult)
    assert res.reused is False
    assert res.records == 4
    assert res.segments == 4
    assert res.words == 6
    assert res.morphs == 11
    assert res.run.stage is RunStage.EXTRACTION
    assert res.run.status is RunStatus.SUCCEEDED
    assert res.report is not None
    assert res.report.kind is ArtifactKind.EXTRACTION_REPORT

    # Verify observations in repository
    observations = ctx.repo.list_igt_observations_for_run(res.run.id)
    assert len(observations) == 4
    for obs in observations:
        assert obs.source_id == reg.source.id
        assert obs.run_id == res.run.id
        assert obs.segment_id is not None

    # Verify segments in repository
    segments = ctx.repo.list_segments_for_run(res.run.id)
    assert len(segments) == 4
    assert [s.language for s in segments] == ["qaa"] * 4

    # Verify lineage edges (EXTRACTED_FROM from obs and seg to source object)
    obj = ctx.repo.list_source_objects(reg.source.id)[0]
    edges = ctx.repo.list_lineage_edges(obj.id, "in")
    run_edges = [e for e in edges if e.run_id == res.run.id]
    # 4 observations + 4 segments + 1 report artifact = 9 lineage edges to the source object
    assert len(run_edges) == 9
    assert all(
        e.kind is LineageKind.EXTRACTED_FROM for e in run_edges if e.from_id != res.report.id
    )

    # Verify report artifact content
    report_bytes = ctx.artifact_store.read_bytes(res.report.sha256)
    report_data = json.loads(report_bytes.decode("utf-8"))
    assert report_data["schema"] == "igt-extraction-report"
    assert report_data["schema_version"] == 1
    assert report_data["records"] == 4
    assert report_data["segments"] == 4
    assert report_data["words"] == 6
    assert report_data["morphs"] == 11
    assert "unknown_marker:\\x" in report_data["unknown_marker_counts"]
    assert report_data["unknown_marker_counts"]["unknown_marker:\\x"] == 1


def test_igt_extract_xigt_xml_happy_path(ctx: AppContext, tmp_path: Path) -> None:
    reg = _setup_source(ctx, tmp_path, "xigt-happy", SAMPLE_XIGT, "application/xml")
    ingest_source(ctx, reg.source.id)

    res = extract_igt(ctx, reg.source.id)
    assert res.records == 1
    assert res.segments == 1
    assert res.words == 2
    assert res.morphs == 3
    assert res.reused is False

    obs = ctx.repo.list_igt_observations_for_run(res.run.id)[0]
    assert obs.record_ref == "i1"
    assert obs.translations == {"por": ["A canoa foi ao rio."]}


def test_igt_extract_missing_text_tier_creates_no_segment(ctx: AppContext, tmp_path: Path) -> None:
    reg = _setup_source(ctx, tmp_path, "missing-tx", SAMPLE_MISSING, "text/plain")
    ingest_source(ctx, reg.source.id)

    res = extract_igt(ctx, reg.source.id)
    assert res.records == 1
    assert res.segments == 0
    assert res.words == 0

    obs = ctx.repo.list_igt_observations_for_run(res.run.id)[0]
    assert obs.segment_id is None
    assert obs.parse_status is IgtParseStatus.MISSING_TIER
    assert ctx.repo.list_segments_for_run(res.run.id) == []


def test_igt_extract_idempotent_reuse(ctx: AppContext, tmp_path: Path) -> None:
    reg = _setup_source(ctx, tmp_path, "tb-reuse", SAMPLE_TOOLBOX, "text/plain")
    ingest_source(ctx, reg.source.id)

    first = extract_igt(ctx, reg.source.id)
    assert first.reused is False

    second = extract_igt(ctx, reg.source.id)
    assert second.reused is True
    assert second.run.id == first.run.id
    assert second.records == first.records
    assert second.segments == first.segments
    assert second.words == first.words
    assert second.morphs == first.morphs


def test_igt_extract_policy_denial_writes_audit_event_and_no_run(
    ctx: AppContext, tmp_path: Path
) -> None:
    reg = _setup_source(
        ctx, tmp_path, "denied-igt", SAMPLE_TOOLBOX, "text/plain", mode="review_required"
    )
    ingest_source(ctx, reg.source.id)

    with pytest.raises(PolicyDenied):
        extract_igt(ctx, reg.source.id)

    # No runs created
    runs = [
        r
        for r in (
            ctx.repo.list_runs_for_source(reg.source.id)
            if hasattr(ctx.repo, "list_runs_for_source")
            else []
        )
        if r.stage is RunStage.EXTRACTION
    ]
    assert runs == []

    # One POLICY_DENIED audit event written
    events = [
        e
        for e in ctx.repo.list_audit_events()
        if e.subject_id == reg.source.id and e.event_type is AuditEventType.POLICY_DENIED
    ]
    assert len(events) >= 1


def test_igt_extract_source_not_ingested_raises(ctx: AppContext, tmp_path: Path) -> None:
    reg = _setup_source(ctx, tmp_path, "uningested", SAMPLE_TOOLBOX, "text/plain")
    # Not ingested
    with pytest.raises(SourceNotIngested):
        extract_igt(ctx, reg.source.id)


def test_igt_extract_invalid_language_override_raises(ctx: AppContext, tmp_path: Path) -> None:
    reg = _setup_source(ctx, tmp_path, "bad-lang", SAMPLE_TOOLBOX, "text/plain")
    ingest_source(ctx, reg.source.id)

    with pytest.raises(SchemaViolation):
        extract_igt(ctx, reg.source.id, language="xyz")


def test_igt_extract_unsupported_media_type_raises(ctx: AppContext, tmp_path: Path) -> None:
    reg = _setup_source(ctx, tmp_path, "unsupported-media", SAMPLE_TOOLBOX, "audio/wav")
    ingest_source(ctx, reg.source.id)

    with pytest.raises(UnsupportedSource):
        extract_igt(ctx, reg.source.id)


def test_igt_extract_chain_proof_normalize_and_tokenize(ctx: AppContext, tmp_path: Path) -> None:
    """Prove the downstream chain: M2 normalize and tokenize accept the IGT extraction run."""
    reg = _setup_source(ctx, tmp_path, "chain-proof", SAMPLE_TOOLBOX, "text/plain")
    ingest_source(ctx, reg.source.id)

    igt_res = extract_igt(ctx, reg.source.id)
    assert igt_res.segments == 4

    # Normalize the IGT extraction run
    norm_res = normalize_extraction(ctx, igt_res.run.id)
    assert norm_res.run.stage is RunStage.NORMALIZATION
    assert norm_res.run.status is RunStatus.SUCCEEDED
    assert norm_res.segments == 4
    assert norm_res.failed == 0

    # Tokenize the normalized segments
    tok_res = tokenize_normalization(ctx, norm_res.run.id)
    assert tok_res.run.stage is RunStage.TOKENIZATION
    assert tok_res.run.status is RunStatus.SUCCEEDED
    assert tok_res.tokens > 0


def test_igt_extract_config_pins_profile(ctx: AppContext, tmp_path: Path) -> None:
    reg = _setup_source(ctx, tmp_path, "profile-pin", SAMPLE_TOOLBOX, "text/plain")
    ingest_source(ctx, reg.source.id)

    res = extract_igt(ctx, reg.source.id)
    assert "profile" in res.run.config
    assert res.run.config["profile"] == "generic@0.1.0"


def test_igt_extract_unknown_marker_sanitization(ctx: AppContext, tmp_path: Path) -> None:
    content = (
        b"\\ref 001\n"
        b"\\tx test word\n"
        b"\\sensitivetextsecret line content\n"
        b"\\ama short word line\n"
        b"\\x valid_unknown\n"
    )
    fix_path = tmp_path / "sanitize_marker.txt"
    fix_path.write_bytes(content)
    reg = _setup_source(ctx, tmp_path, "sanitize-marker", fix_path, "text/plain")
    ingest_source(ctx, reg.source.id)

    res = extract_igt(ctx, reg.source.id)
    report_bytes = ctx.artifact_store.read_bytes(res.report.sha256)
    report_data = json.loads(report_bytes.decode("utf-8"))

    unknown_counts = report_data["unknown_marker_counts"]
    assert "unknown_marker:\\x" in unknown_counts
    assert "unknown_marker:UNKNOWN" in unknown_counts
    assert unknown_counts["unknown_marker:UNKNOWN"] == 2
    assert "unknown_marker:\\ama" not in unknown_counts
    assert "unknown_marker:\\sensitivetextsecret" not in unknown_counts
    assert not any("ama" in k or "sensitivetextsecret" in k for k in unknown_counts)


def test_igt_extract_text_tier_preservation(ctx: AppContext, tmp_path: Path) -> None:
    content = (
        b"\\ref 001\n"
        b"\\tx First line of text,\n"
        b" continuation line here.\n"
        b"\\mb first line of text continuation line here\n"
        b"\\ge first line of text continuation line here\n"
    )
    fix_path = tmp_path / "preserve_text.txt"
    fix_path.write_bytes(content)
    reg = _setup_source(ctx, tmp_path, "preserve-text", fix_path, "text/plain")
    ingest_source(ctx, reg.source.id)

    res = extract_igt(ctx, reg.source.id)
    segments = ctx.repo.list_segments_for_run(res.run.id)
    assert len(segments) == 1
    assert segments[0].raw_text == "First line of text,\n continuation line here."


def test_igt_extract_late_failure_marks_run_failed(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = _setup_source(ctx, tmp_path, "late-fail", SAMPLE_TOOLBOX, "text/plain")
    ingest_source(ctx, reg.source.id)

    def _failing_store_report(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected late failure during report creation")

    monkeypatch.setattr("langpipe.igt.service._store_report", _failing_store_report)

    failed_before = ctx.repo.count_runs(RunStatus.FAILED)
    with pytest.raises(RuntimeError, match="injected late failure"):
        extract_igt(ctx, reg.source.id)

    assert ctx.repo.count_runs(RunStatus.FAILED) == failed_before + 1


def test_igt_extract_post_succeed_failure_does_not_call_fail(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = _setup_source(ctx, tmp_path, "post-succeed-fail", SAMPLE_TOOLBOX, "text/plain")
    ingest_source(ctx, reg.source.id)

    def _failing_log_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected logging failure after commit")

    monkeypatch.setattr("langpipe.igt.service.log_event", _failing_log_event)

    succeeded_before = ctx.repo.count_runs(RunStatus.SUCCEEDED)
    failed_before = ctx.repo.count_runs(RunStatus.FAILED)
    with pytest.raises(RuntimeError, match="injected logging failure after commit"):
        extract_igt(ctx, reg.source.id)

    # Run remains SUCCEEDED in repository; no FAILED run created, no ImmutableViolation
    assert ctx.repo.count_runs(RunStatus.SUCCEEDED) == succeeded_before + 1
    assert ctx.repo.count_runs(RunStatus.FAILED) == failed_before
