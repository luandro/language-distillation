"""Integration tests for `igt_projection@0.1.0` morphology service (M5 WP5.10, Gate 39).

Contracts under test:
- Preconditions: succeeded tokenization run and inventory run; DISTILL_MORPHOLOGY allowed;
  non-succeeded input run raises `InvalidLineage`.
- Inventory filtering: morphemes/allomorphs excluding rejected/deprecated.
- Boundary splitting and affix stripping on text tokens against inventory bound allomorphs.
- Honest abstention for unmatched tokens.
- Analysis persistence: MorphAnalysis, MorphSegment, EvidenceItem, LineageEdge.
- Artifact report: `morphology-induction-report` v1 with method `igt_projection@0.1.0`,
  abstention counts, status counts (never validated).
- Idempotent reuse: identical config and inputs return reused run.
- Governance: revoking ancestor source raises `PolicyDenied` and records denial audit event.
"""

import json
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AnalysisKind,
    ArtifactKind,
    AuditEventType,
    EvidencePolarity,
    LifecycleStatus,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import InvalidLineage, PolicyDenied
from langpipe.igt.service import extract_igt
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.morphology.service import (
    REPORT_SCHEMA,
    REPORT_SCHEMA_VERSION,
    MorphologyInductionResult,
    assert_igt,
    induce_morphology,
)
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


def _setup_pipeline(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    text_content: bytes,
    *,
    source_type: str = "monolingual_text",
    languages: list[str] | None = None,
    access_class: str = "public",
) -> tuple[str, str, str]:
    """Register, ingest, extract, normalize, and tokenize a source."""
    langs = languages or ["qaa"]
    relative = f"texts/{key}.dat"
    write_origin_file(tmp_path, relative, text_content)
    data = manifest_data(
        key=key,
        mode="direct",
        access_class=access_class,
        objects=[{"path": relative, "media_type": "text/plain"}],
    )
    data["source_type"] = source_type
    data["languages"] = langs
    reg = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    ingest_source(ctx, reg.source.id)

    if source_type == "igt":
        extract_res = extract_igt(ctx, reg.source.id)
        extract_run_id = extract_res.run.id
    else:
        from langpipe.extraction.service import extract_source

        extract_res = extract_source(ctx, reg.source.id)
        extract_run_id = extract_res.run.id

    norm_res = normalize_extraction(ctx, extract_run_id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)
    return reg.source.id, extract_run_id, tok_res.run.id


def test_igt_projection_happy_path(ctx: AppContext, tmp_path: Path) -> None:
    # 1. Setup IGT source and assert IGT morphology to create inventory
    igt_src_id, igt_run_id, igt_tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-proj-inv",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    igt_assert_res = assert_igt(
        ctx,
        tokenization_run_id=igt_tok_run_id,
        igt_extract_run_id=igt_run_id,
    )
    inv_run_id = igt_assert_res.run.id
    assert igt_assert_res.run.status is RunStatus.SUCCEEDED

    # 2. Setup text source with target words to project on:
    # 'wesara' (suffix stripping: wesa + ra), 'foora' (unknown stem + ra), 'unknownword' (abstains)
    text_content = b"wesara foora unknownword mabi-ki\n"
    text_src_id, text_ext_run_id, text_tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "text-target",
        text_content,
        source_type="monolingual_text",
        languages=["qaa"],
    )

    # 3. Induce morphology via igt_projection
    res = induce_morphology(
        ctx,
        tokenization_run_id=text_tok_run_id,
        method="igt_projection",
        inventory_run_id=inv_run_id,
        language="qaa",
    )

    assert isinstance(res, MorphologyInductionResult)
    assert res.reused is False
    assert res.run.stage is RunStage.MORPHOLOGY_INDUCTION
    assert res.run.status is RunStatus.SUCCEEDED
    assert res.run.tool_name == "langpipe.morph-induce"
    assert res.run.config.get("method") == "igt_projection@0.1.0"
    assert res.run.config.get("inventory_run_id") == inv_run_id

    # Verify analyses generated for segmented words and abstentions for unsegmented
    assert res.totals["analyses"] >= 3
    assert res.abstention_counts.get("insufficient_evidence", 0) >= 1

    # Verify report artifact
    assert res.report is not None
    assert res.report.kind is ArtifactKind.OTHER
    report_bytes = ctx.artifact_store.read_bytes(res.report.sha256)
    report_data = json.loads(report_bytes.decode("utf-8"))
    assert report_data["schema"] == REPORT_SCHEMA
    assert report_data["schema_version"] == REPORT_SCHEMA_VERSION
    assert report_data["method"] == "igt_projection@0.1.0"
    assert report_data["inventory_run_id"] == inv_run_id

    # Invariant: VALIDATED status never appears in status_counts
    assert "validated" not in report_data["status_counts"]
    for status_str in report_data["status_counts"]:
        assert status_str != LifecycleStatus.VALIDATED.value

    # Verify DB analyses
    analyses = ctx.repo.list_morph_analyses_for_run(res.run.id)
    assert len(analyses) == res.totals["analyses"]
    for ana in analyses:
        assert ana.analysis_kind is AnalysisKind.SEGMENTED
        assert ana.status in (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED)
        assert ana.status is not LifecycleStatus.VALIDATED
        assert ana.method == "igt_projection@0.1.0"

        # Check segments
        segs = ctx.repo.list_morph_segments(ana.id)
        assert len(segs) >= 2

        # Check evidence
        evi_list = ctx.repo.list_evidence_for_target(ana.id)
        assert len(evi_list) >= 1
        sup = [e for e in evi_list if e.polarity is EvidencePolarity.SUPPORTS]
        assert len(sup) >= 1
        assert sup[0].independence_group == f"inventory:{inv_run_id}"

    # Verify lineage edges exist to tokenization and inventory runs
    run_inputs = ctx.repo.list_run_io(res.run.id)
    input_ids = {item_id for item_id, role in run_inputs}
    assert text_tok_run_id in input_ids
    assert inv_run_id in input_ids


def test_igt_projection_idempotent_reuse(ctx: AppContext, tmp_path: Path) -> None:
    _, igt_run_id, igt_tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-reuse-inv",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    igt_assert_res = assert_igt(
        ctx,
        tokenization_run_id=igt_tok_run_id,
        igt_extract_run_id=igt_run_id,
    )
    inv_run_id = igt_assert_res.run.id

    _, _, text_tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "text-reuse",
        b"wesara mabi-ki\n",
        source_type="monolingual_text",
        languages=["qaa"],
    )

    res1 = induce_morphology(
        ctx,
        tokenization_run_id=text_tok_run_id,
        method="igt_projection",
        inventory_run_id=inv_run_id,
        language="qaa",
    )
    assert res1.reused is False

    res2 = induce_morphology(
        ctx,
        tokenization_run_id=text_tok_run_id,
        method="igt_projection",
        inventory_run_id=inv_run_id,
        language="qaa",
    )
    assert res2.reused is True
    assert res2.run.id == res1.run.id
    assert res2.totals == res1.totals


def test_igt_projection_precondition_invalid_lineage(ctx: AppContext, tmp_path: Path) -> None:
    _, _, text_tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "text-invalid",
        b"wesara\n",
        source_type="monolingual_text",
        languages=["qaa"],
    )

    # Calling with non-succeeded / non-existent inventory run raises InvalidLineage
    fake_run_id = "run_01M5FAKE000000000000000000"
    with pytest.raises(InvalidLineage):
        induce_morphology(
            ctx,
            tokenization_run_id=text_tok_run_id,
            method="igt_projection",
            inventory_run_id=fake_run_id,
            language="qaa",
        )


def test_igt_projection_policy_denial_on_revoked_source(ctx: AppContext, tmp_path: Path) -> None:
    igt_src_id, igt_run_id, igt_tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-gov-inv",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    igt_assert_res = assert_igt(
        ctx,
        tokenization_run_id=igt_tok_run_id,
        igt_extract_run_id=igt_run_id,
    )
    inv_run_id = igt_assert_res.run.id

    text_src_id, _, text_tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "text-gov",
        b"wesara\n",
        source_type="monolingual_text",
        languages=["qaa"],
    )

    # Revoke the inventory source
    with ctx.repo.transaction():
        ctx.repo.set_source_status(igt_src_id, SourceStatus.REVOKED, at=ctx.clock())

    # Attempting projection over inventory derived from revoked source must fail with PolicyDenied
    with pytest.raises(PolicyDenied) as exc_info:
        induce_morphology(
            ctx,
            tokenization_run_id=text_tok_run_id,
            method="igt_projection",
            inventory_run_id=inv_run_id,
            language="qaa",
        )
    assert exc_info.value.source_id == igt_src_id

    # Verify denial audit event recorded
    denials = [
        e
        for e in ctx.repo.list_audit_events()
        if e.event_type is AuditEventType.POLICY_DENIED and e.subject_id == igt_src_id
    ]
    assert len(denials) >= 1
    assert denials[-1].details.get("operation") == "distill_morphology"
