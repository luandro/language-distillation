"""Integration tests for morphology benchmark harness service (M5 WP5.11, Gate 40, ADR-0019).

Verifies:
- Evaluation of multiple induction runs against derived/held-out MorphGold v1.
- Report artifact `morphology-benchmark-report` v1 with ArtifactKind.BENCHMARK_REPORT.
- Leakage guard: refuses with BenchmarkLeakage when gold record is an ancestor of the inventory.
- Governance: EVALUATION allowed on all ancestor sources; PolicyDenied on revoked sources.
- Idempotent rerun returns reused run.
- CLI: `langpipe morph benchmark` command execution.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    ArtifactKind,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import BenchmarkLeakage, InvalidLineage, PolicyDenied
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.run import ProcessingRun
from langpipe.evaluation.morphology_service import (
    REPORT_SCHEMA,
    evaluate_morphology_benchmark,
)
from langpipe.igt.service import extract_igt
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.morphology.service import (
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
    source_type: str = "igt",
    languages: list[str] | None = None,
    access_class: str = "public",
) -> tuple[str, str, str]:
    langs = languages or ["qaa", "por"]
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
    else:
        from langpipe.extraction.service import extract_source

        extract_res = extract_source(ctx, reg.source.id)

    norm_res = normalize_extraction(ctx, extract_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)
    return reg.source.id, extract_res.run.id, tok_res.run.id


def test_morphology_benchmark_happy_path(ctx: AppContext, tmp_path: Path) -> None:
    # 1. Setup IGT pipeline
    src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-bench-src",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    # 2. Build non-leaky inventory by excluding IGT-2
    assert_res = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=["IGT-2"],
    )
    clean_inv_id = assert_res.run.id

    # 3. Induce baseline runs over the tokens
    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )
    bpe_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="bpe_char@0.1.0",
    )
    proj_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="igt_projection@0.1.0",
        inventory_run_id=clean_inv_id,
    )

    eval_runs = [unsegmented_res.run.id, bpe_res.run.id, proj_res.run.id]

    # 4. Run benchmark against held-out gold IGT-2
    summary = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=eval_runs,
        gold=igt_run_id,
        refs=["IGT-2"],
    )

    assert summary.run.status is RunStatus.SUCCEEDED
    assert summary.report.kind is ArtifactKind.BENCHMARK_REPORT
    assert not summary.reused

    # Check metrics
    assert "unsegmented@0.1.0" in summary.metrics
    assert "bpe_char@0.1.0" in summary.metrics
    assert "igt_projection@0.1.0" in summary.metrics

    # Check report payload
    content = json.loads(ctx.artifact_store.read_bytes(summary.report.sha256).decode("utf-8"))
    assert content["schema"] == REPORT_SCHEMA
    assert content["schema_version"] == 1
    assert content["gold_items"] > 0
    assert "not_run" in content
    assert content["not_run"]["morfessor_baseline"] == "optional_extra_absent"
    assert content["not_run"]["flatcat"] == "not_available"

    # 5. Idempotent reuse check
    rerun = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=eval_runs,
        gold=igt_run_id,
        refs=["IGT-2"],
    )
    assert rerun.reused
    assert rerun.run.id == summary.run.id
    assert rerun.report.id == summary.report.id


def test_morphology_benchmark_leakage_guard(ctx: AppContext, tmp_path: Path) -> None:
    # 1. Setup IGT pipeline
    src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-leak-src",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    # 2. Build LEAKY inventory that DOES include IGT-2 (exclude_refs is empty)
    leaky_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=[],
    )
    leaky_inv_id = leaky_assert.run.id

    # 3. Induce projection with leaky inventory
    leaky_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="igt_projection@0.1.0",
        inventory_run_id=leaky_inv_id,
    )

    # 4. Evaluating leaky_proj against gold IGT-2 MUST refuse with BenchmarkLeakage
    with pytest.raises(BenchmarkLeakage) as exc_info:
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[leaky_proj.run.id],
            gold=igt_run_id,
            refs=["IGT-2"],
        )
    assert "leaked" in str(exc_info.value).lower()


def test_morphology_benchmark_governance_denial(ctx: AppContext, tmp_path: Path) -> None:
    # Setup pipeline with restricted mode
    src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-gov-src",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )

    # Revoke the source so Operation.EVALUATION is denied
    with ctx.repo.transaction():
        ctx.repo.set_source_status(src_id, SourceStatus.REVOKED, at=ctx.clock())

    with pytest.raises(PolicyDenied):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[unsegmented_res.run.id],
            gold=igt_run_id,
            refs=["IGT-2"],
        )


def test_morphology_benchmark_segment_locator_selector(ctx: AppContext, tmp_path: Path) -> None:
    from langpipe.domain.enums import RunIoRole
    from langpipe.domain.models.morphology import MorphGold

    src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-loc-src",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )

    tok_run = ctx.repo.get_run(tok_run_id)
    input_seg_ids = [
        obj_id for obj_id, role in ctx.repo.list_run_io(tok_run.id) if role == RunIoRole.INPUT
    ]
    first_seg = ctx.repo.get_segment(input_seg_ids[0])
    seg_tokens = [t for t in ctx.repo.list_tokens(first_seg.id) if t.run_id == tok_run_id]

    gold = MorphGold(
        gold_id="test-gold-locator",
        language="qaa",
        items=[
            {
                "selector": {
                    "segment_locator": first_seg.locator,
                    "token_ordinal": seg_tokens[0].ordinal,
                },
                "segments": [[0, len(seg_tokens[0].raw_surface)]],
            }
        ],
        provenance={"test": True},
    )

    summary = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unsegmented_res.run.id],
        gold=gold,
    )
    assert summary.run.status is RunStatus.SUCCEEDED
    assert summary.metrics["unsegmented@0.1.0"].exact_accuracy == 1.0
    assert summary.metrics["unsegmented@0.1.0"].abstention_rate == 1.0


def test_morphology_benchmark_segment_locator_leakage_guard(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: gold selector using segment_locator rejects a leaky inventory
    and accepts a held-out one.
    """
    from langpipe.domain.enums import RunIoRole
    from langpipe.domain.models.morphology import MorphGold

    _src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-loc-leak",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    tok_run = ctx.repo.get_run(tok_run_id)
    input_seg_ids = [
        obj_id for obj_id, role in ctx.repo.list_run_io(tok_run.id) if role == RunIoRole.INPUT
    ]
    # Find segment for IGT-2
    igt2_seg = None
    for s_id in input_seg_ids:
        s = ctx.repo.get_segment(s_id)
        if s.locator.get("igt_ref") == "IGT-2":
            igt2_seg = s
            break
    assert igt2_seg is not None
    seg_tokens = [t for t in ctx.repo.list_tokens(igt2_seg.id) if t.run_id == tok_run_id]

    gold = MorphGold(
        gold_id="test-gold-locator-leak",
        language="qaa",
        items=[
            {
                "selector": {
                    "segment_locator": igt2_seg.locator,
                    "token_ordinal": seg_tokens[0].ordinal,
                },
                "segments": [[0, len(seg_tokens[0].raw_surface)]],
            }
        ],
        provenance={"test": True},
    )

    # 1. Leaky inventory that includes IGT-2
    leaky_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=[],
    )
    leaky_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="igt_projection@0.1.0",
        inventory_run_id=leaky_assert.run.id,
    )

    with pytest.raises(BenchmarkLeakage) as exc_info:
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[leaky_proj.run.id],
            gold=gold,
        )
    assert "leaked" in str(exc_info.value).lower()

    # 2. Held-out inventory that excludes IGT-2
    clean_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=["IGT-2"],
    )
    clean_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="igt_projection@0.1.0",
        inventory_run_id=clean_assert.run.id,
    )

    clean_summary = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[clean_proj.run.id],
        gold=gold,
    )
    assert clean_summary.run.status is RunStatus.SUCCEEDED


def test_morphology_benchmark_exclusion_by_ordinal_and_obs_id(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: assertion and benchmark leakage guard support exclusion by ordinal and obs ID."""
    _src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-excl-ord",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    igt_obs = ctx.repo.list_igt_observations_for_run(igt_run_id)
    igt2 = next(o for o in igt_obs if o.record_ref == "IGT-2")

    # 1. Exclusion by ordinal string "1" (IGT-2 has ordinal 1)
    clean_ord_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=["1"],
    )
    clean_ord_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="igt_projection@0.1.0",
        inventory_run_id=clean_ord_assert.run.id,
    )
    res_ord = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[clean_ord_proj.run.id],
        gold=igt_run_id,
        refs=["IGT-2"],
    )
    assert res_ord.run.status is RunStatus.SUCCEEDED

    # 2. Exclusion by observation ID igt2.id
    clean_id_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=[igt2.id],
    )
    clean_id_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="igt_projection@0.1.0",
        inventory_run_id=clean_id_assert.run.id,
    )
    res_id = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[clean_id_proj.run.id],
        gold=igt_run_id,
        refs=["IGT-2"],
    )
    assert res_id.run.status is RunStatus.SUCCEEDED

    # 3. Excluding ordinal "0" (IGT-1) leaves IGT-2 active, so evaluating against IGT-2 MUST fail
    leaky_ord_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run_id,
        igt_extract_run_id=igt_run_id,
        exclude_refs=["0"],
    )
    leaky_ord_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="igt_projection@0.1.0",
        inventory_run_id=leaky_ord_assert.run.id,
    )
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[leaky_ord_proj.run.id],
            gold=igt_run_id,
            refs=["IGT-2"],
        )


def test_morphology_benchmark_colliding_refs_across_distinct_sources(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: identical record refs/ordinals across distinct sources do not cause
    false leakage.
    """
    _src_a, igt_a, tok_a = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-src-a",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    _src_b, igt_b, tok_b = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-src-b",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    # Inventory B built from source B with no exclusions (has IGT-2 and ordinal 1 active)
    inv_b = assert_igt(
        ctx,
        tokenization_run_id=tok_b,
        igt_extract_run_id=igt_b,
        exclude_refs=[],
    )
    # Model evaluated on tok_a with inventory B
    proj_a_with_b = induce_morphology(
        ctx,
        tokenization_run_id=tok_a,
        method="igt_projection@0.1.0",
        inventory_run_id=inv_b.run.id,
    )

    # Benchmark against gold from Source A (igt_a, ref IGT-2).
    # Even though Source B also has ref IGT-2 and ordinal 1, it is from a different source!
    res = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[proj_a_with_b.run.id],
        gold=igt_a,
        refs=["IGT-2"],
    )
    assert res.run.status is RunStatus.SUCCEEDED


def test_morphology_benchmark_same_source_ref_ordinal_no_collision(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: record reference and ordinal namespaces do not collide within one source."""
    toolbox_data = b"""\\ref 1
\\tx ab
\\mr a -b
\\mg A -B

\\ref foo
\\tx cd
\\mr c -d
\\mg C -D
"""
    _src, igt_run, tok_run = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-collision",
        toolbox_data,
        source_type="igt",
        languages=["qaa", "por"],
    )

    # Record 0 has ref="1", ord=0
    # Record 1 has ref="foo", ord=1
    # Build inventory that excludes Record 1 (ref "foo"), leaving Record 0 active.
    clean_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run,
        igt_extract_run_id=igt_run,
        exclude_refs=["foo"],
    )
    clean_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="igt_projection@0.1.0",
        inventory_run_id=clean_assert.run.id,
    )

    # Benchmark against gold for Record 1 (ref "foo", ordinal 1).
    # Active inventory has Record 0 (ref "1", ordinal 0).
    # "ref:1" must not collide with "ord:1".
    res = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[clean_proj.run.id],
        gold=igt_run,
        refs=["foo"],
    )
    assert res.run.status is RunStatus.SUCCEEDED

    # Negative control: evaluating against Record 1 with an inventory that did not exclude it
    leaky_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run,
        igt_extract_run_id=igt_run,
        exclude_refs=[],
    )
    leaky_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="igt_projection@0.1.0",
        inventory_run_id=leaky_assert.run.id,
    )
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[leaky_proj.run.id],
            gold=igt_run,
            refs=["foo"],
        )


def test_morphology_benchmark_gold_structural_validation() -> None:
    """Gate 40: MorphGold rejects empty items, invalid selectors, and malformed spans."""
    import json

    import jsonschema
    from pydantic import ValidationError

    from langpipe.domain.models.morphology import (
        MorphGold,
        MorphGoldItem,
        MorphGoldSelector,
    )

    # 1. Rejects empty items
    with pytest.raises(ValidationError, match="at least 1 item|must not be empty"):
        MorphGold(gold_id="g1", language="qaa", items=[], provenance={})

    # 2. Rejects selector without observation_id, igt_ref, record_ref, record_ordinal, etc.
    with pytest.raises(ValidationError, match="selector must specify"):
        MorphGold(
            gold_id="g1",
            language="qaa",
            items=[{"selector": {}, "segments": [[0, 2]]}],
            provenance={},
        )

    # 3. Rejects inverted or malformed segment spans
    with pytest.raises(ValidationError, match="invalid segment span offsets"):
        MorphGold(
            gold_id="g1",
            language="qaa",
            items=[{"selector": {"igt_ref": "1"}, "segments": [[5, 2]]}],
            provenance={},
        )

    # 4. Rejects item with missing or empty segments
    with pytest.raises(ValidationError, match="segments"):
        MorphGold(
            gold_id="g1",
            language="qaa",
            items=[{"selector": {"igt_ref": "1"}}],
            provenance={},
        )
    with pytest.raises(ValidationError, match="segments"):
        MorphGold(
            gold_id="g1",
            language="qaa",
            items=[{"selector": {"igt_ref": "1"}, "segments": []}],
            provenance={},
        )

    # 5. Rejects inverted root_span
    with pytest.raises(ValidationError, match="invalid root span offsets"):
        MorphGold(
            gold_id="g1",
            language="qaa",
            items=[{"selector": {"igt_ref": "1"}, "segments": [[0, 2]], "root_span": [2, 1]}],
            provenance={},
        )

    # 6. Rejects malformed affix_spans
    with pytest.raises(ValidationError, match="invalid affix span offsets"):
        MorphGold(
            gold_id="g1",
            language="qaa",
            items=[{"selector": {"igt_ref": "1"}, "segments": [[0, 2]], "affix_spans": [[2, 1]]}],
            provenance={},
        )

    # 7. Rejects spans exceeding surface length
    with pytest.raises(ValidationError, match="exceeds surface length"):
        MorphGold(
            gold_id="g1",
            language="qaa",
            items=[
                {
                    "selector": {"igt_ref": "1"},
                    "surface": "abc",
                    "segments": [[0, 5]],
                }
            ],
            provenance={},
        )

    # 8. Stores validated MorphGoldItem and normalizes coerced values
    gold = MorphGold(
        gold_id="g1",
        language="qaa",
        items=[
            {
                "selector": {"igt_ref": "1", "word_ordinal": "3"},
                "surface": "abcd",
                "segments": [[0, 2], [2, 4]],
                "affix_spans": [[2, 4]],
                "root_span": [0, 2],
            }
        ],
        provenance={"note": "valid"},
    )
    assert isinstance(gold.items[0], MorphGoldItem)
    assert isinstance(gold.items[0].selector, MorphGoldSelector)
    assert gold.items[0].selector.word_ordinal == 3
    assert isinstance(gold.items[0].selector.word_ordinal, int)
    assert gold.items[0]["segments"] == [[0, 2], [2, 4]]
    assert gold.items[0]["selector"]["word_ordinal"] == 3

    # 9. Validates schema compliance
    schema_path = Path("schemas/morph-gold.v1.schema.json")
    if schema_path.exists():
        schema = json.loads(schema_path.read_text())
        # Valid instance conforms to schema
        jsonschema.validate(gold.model_dump(), schema)

        # Schema rejects empty items
        invalid_empty = {"gold_id": "g1", "language": "qaa", "items": [], "provenance": {}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_empty, schema)

        # Schema rejects items without segments
        invalid_no_seg = {
            "gold_id": "g1",
            "language": "qaa",
            "items": [{"selector": {"igt_ref": "1"}}],
            "provenance": {},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_no_seg, schema)

        # Schema rejects empty selector
        invalid_empty_sel = {
            "gold_id": "g1",
            "language": "qaa",
            "items": [{"selector": {}, "segments": [[0, 2]]}],
            "provenance": {},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_empty_sel, schema)

        # Schema rejects spans of length != 2
        invalid_short_span = {
            "gold_id": "g1",
            "language": "qaa",
            "items": [{"selector": {"igt_ref": "1"}, "segments": [[2]]}],
            "provenance": {},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_short_span, schema)

        invalid_long_span = {
            "gold_id": "g1",
            "language": "qaa",
            "items": [{"selector": {"igt_ref": "1"}, "segments": [[0, 1, 2]]}],
            "provenance": {},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_long_span, schema)

        # Schema rejects negative offset
        invalid_neg_span = {
            "gold_id": "g1",
            "language": "qaa",
            "items": [{"selector": {"igt_ref": "1"}, "segments": [[-1, 2]]}],
            "provenance": {},
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid_neg_span, schema)

        # Schema and model reject unusable or mixed-invalid selectors (null, empty string,
        # whitespace-only, empty locator, negative ordinal, mixed valid+invalid, empty selector)
        for bad_sel in [
            {"igt_ref": None},
            {},
            {"word_ordinal": 0},
            {"igt_ref": ""},
            {"igt_ref": "   "},
            {"segment_locator": {}},
            {"record_ordinal": -1},
            {"igt_ref": "ok", "record_ordinal": -1},
            {"igt_ref": "ok", "segment_locator": {}},
        ]:
            with pytest.raises((ValidationError, ValueError)):
                MorphGold(
                    gold_id="g1",
                    language="qaa",
                    items=[{"selector": bad_sel, "segments": [[0, 2]]}],
                    provenance={},
                )
            bad_data = {
                "gold_id": "g1",
                "language": "qaa",
                "items": [{"selector": bad_sel, "segments": [[0, 2]]}],
                "provenance": {},
            }
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(bad_data, schema)

        # Valid selectors accepted by both model and schema
        for good_sel in [
            {"igt_ref": "ok"},
            {"record_ordinal": 0},
            {"segment_locator": {"page": 1}},
            {"igt_ref": "ok", "record_ordinal": 0},
        ]:
            MorphGold(
                gold_id="g1",
                language="qaa",
                items=[{"selector": good_sel, "segments": [[0, 2]]}],
                provenance={},
            )
            good_data = {
                "gold_id": "g1",
                "language": "qaa",
                "items": [{"selector": good_sel, "segments": [[0, 2]]}],
                "provenance": {},
            }
            jsonschema.validate(good_data, schema)


def test_morphology_benchmark_ambiguous_ref_rejected_and_explicit_kind_resolved(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: ambiguous numeric refs are rejected; explicit ref: and ord: kinds resolve."""
    from langpipe.evaluation.morphology import gold_from_igt

    toolbox_data = b"""\\ref 1
\\tx ab
\\mr a -b
\\mg A -B

\\ref foo
\\tx cd
\\mr c -d
\\mg C -D
"""
    _src, igt_run, tok_run = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-ambig",
        toolbox_data,
        source_type="igt",
        languages=["qaa", "por"],
    )

    # In this dataset:
    # Record 0 has ref="1", ord=0
    # Record 1 has ref="foo", ord=1
    # Asking for "1" matches Record 0 by record_ref and Record 1 by record_ordinal -> AMBIGUOUS!
    with pytest.raises(ValueError, match="Ambiguous reference '1'"):
        gold_from_igt(ctx.repo, igt_run, ["1"], "qaa")

    # Explicit "ref:1" resolves strictly to Record 0 (surface "ab")
    gold_ref = gold_from_igt(ctx.repo, igt_run, ["ref:1"], "qaa")
    assert len(gold_ref.items) == 1
    assert gold_ref.items[0].surface == "ab"
    assert gold_ref.items[0].selector.record_ref == "1"

    # Explicit "ord:1" resolves strictly to Record 1 (surface "cd")
    gold_ord = gold_from_igt(ctx.repo, igt_run, ["ord:1"], "qaa")
    assert len(gold_ord.items) == 1
    assert gold_ord.items[0].surface == "cd"
    assert gold_ord.items[0].selector.record_ordinal == 1

    # End-to-end benchmark run with explicit kinds:
    clean_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run,
        igt_extract_run_id=igt_run,
        exclude_refs=["foo"],
    )
    clean_proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="igt_projection@0.1.0",
        inventory_run_id=clean_assert.run.id,
    )

    # Benchmark against gold_ord (Record 1): active inventory has Record 0 ("ref:1"), no leak!
    res = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[clean_proj.run.id],
        gold=gold_ord,
    )
    assert res.run.status is RunStatus.SUCCEEDED

    # Evaluating against gold_ref (Record 0) leaks because clean_proj included Record 0!
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[clean_proj.run.id],
            gold=gold_ref,
        )


def test_morphology_benchmark_explicit_kinds_map_tokens_and_evaluate_metrics(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: manual gold items with explicit kinds map tokens and score segmented metrics."""
    from langpipe.domain.models.morphology import MorphGold

    _src, igt_run, tok_run = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-kinds-map",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    clean_assert = assert_igt(
        ctx,
        tokenization_run_id=tok_run,
        igt_extract_run_id=igt_run,
        exclude_refs=["IGT-2"],
    )
    proj = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="igt_projection@0.1.0",
        inventory_run_id=clean_assert.run.id,
        language="qaa",
    )

    # Find the actual observation for Record 1 (ref "IGT-2", ordinal 1, surface "wesa-ra")
    obs_list = ctx.repo.list_igt_observations_for_run(igt_run)
    obs_igt2 = next(o for o in obs_list if o.record_ref == "IGT-2")

    # Construct MorphGold manually with NO observation_id, testing:
    # 1. "ord:1" (Record 1 ordinal)
    # 2. "ref:IGT-2" (Record 1 ref)
    # 3. f"id:{obs_igt2.id}" (Record 1 observation id)
    # 4. record_ref="IGT-2"
    # 5. record_ordinal=1
    selectors = [
        {"igt_ref": "ord:1", "word_ordinal": 0},
        {"igt_ref": "ref:IGT-2", "word_ordinal": 0},
        {"igt_ref": f"id:{obs_igt2.id}", "word_ordinal": 0},
        {"record_ref": "IGT-2", "word_ordinal": 0},
        {"record_ordinal": 1, "word_ordinal": 0},
    ]

    for sel in selectors:
        # Segmented gold standard: "wesa" [0, 4] and "-ra" [5, 7]
        # Discriminating test: unmapped tokens fallback to whole-surface [0, 7]
        # and fail exact match against segmented gold.
        manual_gold = MorphGold(
            gold_id="manual-test-gold",
            language="qaa",
            items=[
                {
                    "selector": sel,
                    "surface": "wesa-ra",
                    "segments": [[0, 4], [5, 7]],
                }
            ],
            provenance={"igt_extract_run_id": igt_run},
        )
        res = evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[proj.run.id],
            gold=manual_gold,
        )
        assert res.run.status is RunStatus.SUCCEEDED
        art = res.report
        assert art is not None
        payload = json.loads(ctx.artifact_store.read_bytes(art.sha256))
        proj_report = payload["metrics"]["igt_projection@0.1.0"]
        # Proves token was mapped and scored against segmented prediction
        assert proj_report["coverage"] == 1.0
        assert proj_report["abstention_rate"] == 0.0
        assert proj_report["exact_accuracy"] == 1.0
        assert proj_report["boundary_f1"] == 1.0
        assert res.metrics["igt_projection@0.1.0"].coverage == 1.0
        assert res.metrics["igt_projection@0.1.0"].abstention_rate == 0.0
        assert res.metrics["igt_projection@0.1.0"].exact_accuracy == 1.0
        assert res.metrics["igt_projection@0.1.0"].boundary_f1 == 1.0


def test_morphology_benchmark_token_mapping_scopes_source_and_rejects_cross_source_collision(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: token mapping scopes to observation source and rejects ambiguous matches."""
    from langpipe.domain.models.morphology import MorphGold
    from langpipe.domain.models.observation import Segment, TokenOccurrence

    # Source 1: "col-src-1", record "IGT-1", surface "mabi-ki"
    tb_1 = b"\\ref IGT-1\n\\tx mabi-ki\n\\mr mabi -ki\n\\mg canoe-ERG\n"
    src_1, igt_run_1, tok_1 = _setup_pipeline(ctx, tmp_path, "col-src-1", tb_1)

    # Source 2: "col-src-2", record "IGT-1" (overlapping ref/ord), surface "wesa-ra"
    tb_2 = b"\\ref IGT-1\n\\tx wesa-ra\n\\mr wesa -ra\n\\mg go-NEG\n"
    src_2, igt_run_2, tok_2 = _setup_pipeline(ctx, tmp_path, "col-src-2", tb_2)

    # Retrieve normalized segments for each source
    seg_1 = [
        ctx.repo.get_segment(inp_id)
        for inp_id, role in ctx.repo.list_run_io(tok_1)
        if role is RunIoRole.INPUT
    ][0]
    seg_2 = [
        ctx.repo.get_segment(inp_id)
        for inp_id, role in ctx.repo.list_run_io(tok_2)
        if role is RunIoRole.INPUT
    ][0]

    # Create joint tokenization run where seg_2 (from Source 2) is listed FIRST
    cfg_joint: dict[str, Any] = {"tokenizers": {"qaa": "whitespace_punct@0.1.0"}}
    hash_joint = config_hash(cfg_joint)
    rk_joint = ProcessingRun.compute_run_key(
        RunStage.TOKENIZATION,
        "langpipe.tokenize",
        "0.1.0",
        hash_joint,
        [seg_2.id, seg_1.id],
    )
    joint_tok_run = ProcessingRun(
        id=ctx.new_id(IdPrefix.RUN),
        stage=RunStage.TOKENIZATION,
        tool_name="langpipe.tokenize",
        tool_version="0.1.0",
        config=cfg_joint,
        config_hash=hash_joint,
        code_revision=ctx.code_revision,
        run_key=rk_joint,
        status=RunStatus.SUCCEEDED,
        started_at=ctx.clock(),
        finished_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_run(joint_tok_run)
        # Reversed order: Source 2 segment first, then Source 1 segment
        ctx.repo.add_run_io(joint_tok_run.id, seg_2.id, RunIoRole.INPUT)
        ctx.repo.add_run_io(joint_tok_run.id, seg_1.id, RunIoRole.INPUT)

        # Add token occurrences for both segments under joint_tok_run
        tok_wesa = TokenOccurrence(
            id=ctx.new_id(IdPrefix.TOKEN),
            segment_id=seg_2.id,
            run_id=joint_tok_run.id,
            ordinal=0,
            raw_surface="wesa-ra",
            tokenizer="whitespace_punct@0.1.0",
            created_at=ctx.clock(),
        )
        tok_mabi = TokenOccurrence(
            id=ctx.new_id(IdPrefix.TOKEN),
            segment_id=seg_1.id,
            run_id=joint_tok_run.id,
            ordinal=0,
            raw_surface="mabi-ki",
            tokenizer="whitespace_punct@0.1.0",
            created_at=ctx.clock(),
        )
        ctx.repo.add_token(tok_wesa)
        ctx.repo.add_token(tok_mabi)

    # Induce baseline unsegmented morphology over joint_tok_run
    unseg = induce_morphology(
        ctx,
        tokenization_run_id=joint_tok_run.id,
        method="unsegmented@0.1.0",
        language="qaa",
    )

    # Gold targeting Source 1 IGT-1 ("mabi-ki")
    gold_src1 = MorphGold(
        gold_id="src1-gold",
        language="qaa",
        items=[
            {
                "selector": {"igt_ref": "ref:IGT-1", "word_ordinal": 0},
                "surface": "mabi-ki",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run_1},
    )

    res = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unseg.run.id],
        gold=gold_src1,
    )
    assert res.run.status is RunStatus.SUCCEEDED
    # Scoping ensured tok_mabi (Source 1) was mapped, not tok_wesa (Source 2),
    # so exact match succeeded against "mabi-ki" [0, 7].
    met = res.metrics["unsegmented@0.1.0"]
    assert met.exact_accuracy == 1.0

    # Ambiguity check with competing tokens and analyses:
    # Duplicate segment with identical locator in the SAME source
    seg_1_dup = Segment(
        id=ctx.new_id(IdPrefix.SEGMENT),
        source_id=src_1,
        source_object_id=seg_1.source_object_id,
        run_id=seg_1.run_id,
        ordinal=99,
        language="qaa",
        locator=dict(seg_1.locator),
        raw_text="mabi-ki-dup",
        created_at=ctx.clock(),
    )
    cfg_ambig: dict[str, Any] = {"tokenizers": {"qaa": "whitespace_punct@0.1.0"}}
    hash_ambig = config_hash(cfg_ambig)
    rk_ambig = ProcessingRun.compute_run_key(
        RunStage.TOKENIZATION,
        "langpipe.tokenize",
        "0.1.0",
        hash_ambig,
        [seg_1.id, seg_1_dup.id],
    )
    ambig_tok_run = ProcessingRun(
        id=ctx.new_id(IdPrefix.RUN),
        stage=RunStage.TOKENIZATION,
        tool_name="langpipe.tokenize",
        tool_version="0.1.0",
        config=cfg_ambig,
        config_hash=hash_ambig,
        code_revision=ctx.code_revision,
        run_key=rk_ambig,
        status=RunStatus.SUCCEEDED,
        started_at=ctx.clock(),
        finished_at=ctx.clock(),
    )
    # Competing tokens under ambig_tok_run for both candidate segments
    tok_ambig_1 = TokenOccurrence(
        id=ctx.new_id(IdPrefix.TOKEN),
        segment_id=seg_1.id,
        run_id=ambig_tok_run.id,
        ordinal=0,
        raw_surface="mabi-ki",
        tokenizer="whitespace_punct@0.1.0",
        created_at=ctx.clock(),
    )
    tok_ambig_2 = TokenOccurrence(
        id=ctx.new_id(IdPrefix.TOKEN),
        segment_id=seg_1_dup.id,
        run_id=ambig_tok_run.id,
        ordinal=0,
        raw_surface="mabi-ki-dup",
        tokenizer="whitespace_punct@0.1.0",
        created_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_segment(seg_1_dup)
        ctx.repo.add_run(ambig_tok_run)
        ctx.repo.add_run_io(ambig_tok_run.id, seg_1.id, RunIoRole.INPUT)
        ctx.repo.add_run_io(ambig_tok_run.id, seg_1_dup.id, RunIoRole.INPUT)
        ctx.repo.add_token(tok_ambig_1)
        ctx.repo.add_token(tok_ambig_2)

    # Induce morphology over both tokens so competing analyses exist
    ambig_unseg = induce_morphology(
        ctx,
        tokenization_run_id=ambig_tok_run.id,
        method="unsegmented@0.1.0",
        language="qaa",
    )

    # 1. Pure locator selector: ambiguous locator matches both seg_1 and seg_1_dup
    gold_loc_ambig = MorphGold(
        gold_id="loc-ambig-gold",
        language="qaa",
        items=[
            {
                "selector": {"segment_locator": dict(seg_1.locator), "token_ordinal": 0},
                "surface": "mabi-ki",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run_1},
    )
    res_loc = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[ambig_unseg.run.id],
        gold=gold_loc_ambig,
    )
    met_loc = res_loc.metrics["unsegmented@0.1.0"]
    # Truly discriminating: competing tokens had analyses, but ambiguous locator is rejected
    assert met_loc.abstention_rate == 1.0
    assert met_loc.coverage == 0.0

    # 2. Mixed observation + locator selector: ambiguous locator must NOT fall through
    gold_mixed_ambig = MorphGold(
        gold_id="mixed-ambig-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "igt_ref": "ref:IGT-1",
                    "segment_locator": dict(seg_1.locator),
                    "token_ordinal": 0,
                },
                "surface": "mabi-ki",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run_1},
    )
    res_mixed = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[ambig_unseg.run.id],
        gold=gold_mixed_ambig,
    )
    met_mixed = res_mixed.metrics["unsegmented@0.1.0"]
    assert met_mixed.abstention_rate == 1.0
    assert met_mixed.coverage == 0.0

    # 3. Duplicate observations in same source: record_ref occurs twice
    tb_dup_obs = (
        b"\\ref IGT-DUP\n\\tx mabi-ki\n\\mr mabi -ki\n\\mg canoe-ERG\n\n"
        b"\\ref IGT-DUP\n\\tx wesa-ra\n\\mr wesa -ra\n\\mg go-NEG\n"
    )
    src_dup, igt_dup, tok_dup = _setup_pipeline(ctx, tmp_path, "dup-obs-src", tb_dup_obs)
    unseg_dup = induce_morphology(
        ctx,
        tokenization_run_id=tok_dup,
        method="unsegmented@0.1.0",
        language="qaa",
    )
    gold_obs_dup = MorphGold(
        gold_id="obs-dup-gold",
        language="qaa",
        items=[
            {
                "selector": {"record_ref": "IGT-DUP", "word_ordinal": 0},
                "surface": "mabi-ki",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_dup},
    )
    res_obs_dup = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unseg_dup.run.id],
        gold=gold_obs_dup,
    )
    met_obs = res_obs_dup.metrics["unsegmented@0.1.0"]
    assert met_obs.abstention_rate == 1.0
    assert met_obs.coverage == 0.0


def test_morphology_benchmark_conflicting_selector_constraints_and_same_object_records(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: conflicting selector constraints and same-object cross-record mismatches reject."""
    from langpipe.domain.models.morphology import MorphGold

    _src, igt_run, tok_run = _setup_pipeline(
        ctx,
        tmp_path,
        "conflict-sel-src",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    # Inventory holding out both IGT-1 and IGT-2 for clean conflict evaluation
    assert_clean = assert_igt(
        ctx,
        tokenization_run_id=tok_run,
        igt_extract_run_id=igt_run,
        exclude_refs=["IGT-1", "IGT-2"],
    )
    # Discriminating segmented model: igt_projection yields coverage=1.0 when mapped
    proj_clean = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="igt_projection@0.1.0",
        inventory_run_id=assert_clean.run.id,
        language="qaa",
    )
    obs_list = ctx.repo.list_igt_observations_for_run(igt_run)
    obs_igt1 = next(o for o in obs_list if o.record_ref == "IGT-1")
    obs_igt2 = next(o for o in obs_list if o.record_ref == "IGT-2")

    # 1. Conflicting selector: record_ref says IGT-1, locator says IGT-2
    gold_conflict = MorphGold(
        gold_id="conflict-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "record_ref": "IGT-1",
                    "segment_locator": {"igt_ref": "IGT-2"},
                    "token_ordinal": 0,
                },
                "surface": "wesa-ra",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run},
    )
    res_conflict = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[proj_clean.run.id],
        gold=gold_conflict,
    )
    met_conflict = res_conflict.metrics["igt_projection@0.1.0"]
    assert met_conflict.abstention_rate == 1.0
    assert met_conflict.coverage == 0.0

    # 2. Same-object different-record mismatch: observation_id is IGT-2, locator is IGT-1
    gold_same_obj = MorphGold(
        gold_id="same-obj-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "observation_id": obs_igt2.id,
                    "segment_locator": {"igt_ref": "IGT-1"},
                    "token_ordinal": 0,
                },
                "surface": "mabi-ki",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run},
    )
    res_same_obj = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[proj_clean.run.id],
        gold=gold_same_obj,
    )
    met_same_obj = res_same_obj.metrics["igt_projection@0.1.0"]
    assert met_same_obj.abstention_rate == 1.0
    assert met_same_obj.coverage == 0.0

    # 3. Explicit observation_id with matching locator but conflicting record_ref
    # (obs_igt2 is IGT-2, locator matches IGT-2, but record_ref says IGT-1)
    gold_obs_conflict = MorphGold(
        gold_id="obs-conflict-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "observation_id": obs_igt2.id,
                    "segment_locator": {"igt_ref": "IGT-2"},
                    "record_ref": "IGT-1",
                    "token_ordinal": 0,
                },
                "surface": "wesa-ra",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run},
    )
    res_obs_conflict = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[proj_clean.run.id],
        gold=gold_obs_conflict,
    )
    met_obs_conflict = res_obs_conflict.metrics["igt_projection@0.1.0"]
    assert met_obs_conflict.abstention_rate == 1.0
    assert met_obs_conflict.coverage == 0.0

    # 4. Contradictory selector leakage: observation_id is IGT-1 (held out from assert_leaky),
    # but segment_locator matches IGT-2 (which leaked into assert_leaky inventory).
    # Leakage guard independently collects locator-matched IGT-2 and raises BenchmarkLeakage!
    assert_leaky = assert_igt(
        ctx,
        tokenization_run_id=tok_run,
        igt_extract_run_id=igt_run,
        exclude_refs=["IGT-1"],
    )
    proj_leaky = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="igt_projection@0.1.0",
        inventory_run_id=assert_leaky.run.id,
        language="qaa",
    )
    gold_locator_leak = MorphGold(
        gold_id="loc-leak-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "observation_id": obs_igt1.id,
                    "segment_locator": {"igt_ref": "IGT-2"},
                    "token_ordinal": 0,
                },
                "surface": "wesa-ra",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run},
    )
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[proj_leaky.run.id],
            gold=gold_locator_leak,
        )

    # 5. Contradictory selector without source_key or provenance:
    # observation_id is IGT-1 (held out), but record_ref is IGT-2 (in inventory).
    # Provenance is empty. Leakage guard discovers source via observation_id,
    # independently collects record_ref="IGT-2" in that source, and raises BenchmarkLeakage!
    gold_rec_leak = MorphGold(
        gold_id="rec-leak-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "observation_id": obs_igt1.id,
                    "record_ref": "IGT-2",
                    "token_ordinal": 0,
                },
                "surface": "wesa-ra",
                "segments": [[0, 7]],
            }
        ],
        provenance={},
    )
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[proj_leaky.run.id],
            gold=gold_rec_leak,
        )

    # 6. Conflicting source_key does not hide locator match from leakage guard:
    # Selector specifies source_key="conflict-sel-src" but segment_locator matching IGT-2:
    # Leakage guard independently collects locator match and raises BenchmarkLeakage!
    gold_src_loc_leak = MorphGold(
        gold_id="src-loc-leak-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "source_key": "conflict-sel-src",
                    "segment_locator": {"igt_ref": "IGT-2"},
                    "token_ordinal": 0,
                },
                "surface": "wesa-ra",
                "segments": [[0, 7]],
            }
        ],
        provenance={},
    )
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[proj_leaky.run.id],
            gold=gold_src_loc_leak,
        )

    # 7. Cross-source igt_ref with id: prefix in another source triggers leakage:
    # Selector specifies source_key="conflict-sel-src" but igt_ref="id:<obs_igt2.id>"
    # (where obs_igt2 is in assert_leaky inventory).
    # Leakage guard resolves id: independently across sources and raises BenchmarkLeakage!
    gold_id_leak = MorphGold(
        gold_id="id-leak-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "source_key": "conflict-sel-src",
                    "igt_ref": f"id:{obs_igt2.id}",
                    "token_ordinal": 0,
                },
                "surface": "wesa-ra",
                "segments": [[0, 7]],
            }
        ],
        provenance={},
    )
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[proj_leaky.run.id],
            gold=gold_id_leak,
        )

    # 8. Cross-source igt_ref with UNPREFIXED observation ID triggers leakage:
    # Selector specifies source_key="conflict-sel-src" but igt_ref="<obs_igt2.id>" (no id: prefix)
    # Leakage guard resolves unprefixed ID independently across sources and raises BenchmarkLeakage!
    gold_unprefixed_id_leak = MorphGold(
        gold_id="unprefixed-id-leak-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "source_key": "conflict-sel-src",
                    "igt_ref": str(obs_igt2.id),
                    "token_ordinal": 0,
                },
                "surface": "wesa-ra",
                "segments": [[0, 7]],
            }
        ],
        provenance={},
    )
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[proj_leaky.run.id],
            gold=gold_unprefixed_id_leak,
        )


def test_morphology_benchmark_leakage_under_ambiguous_locators(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: ambiguous locators preserve all candidate observations for leakage guard."""
    from langpipe.domain.models.morphology import MorphGold

    # Two sources sharing record_ref "IGT-SHARED"
    tb_1 = b"\\ref IGT-SHARED\n\\tx mabi-ki\n\\mr mabi -ki\n\\mg canoe-ERG\n"
    src_1, igt_1, tok_1 = _setup_pipeline(ctx, tmp_path, "ambig-leak-1", tb_1)
    tb_2 = b"\\ref IGT-SHARED\n\\tx wesa-ra\n\\mr wesa -ra\n\\mg go-NEG\n"
    src_2, igt_2, tok_2 = _setup_pipeline(ctx, tmp_path, "ambig-leak-2", tb_2)

    # Inventory created from Source 1
    assert_run = assert_igt(
        ctx,
        tokenization_run_id=tok_1,
        igt_extract_run_id=igt_1,
    )

    # Joint tokenization run taking inputs from both Source 1 and Source 2
    seg_1 = [
        ctx.repo.get_segment(inp_id)
        for inp_id, role in ctx.repo.list_run_io(tok_1)
        if role is RunIoRole.INPUT
    ][0]
    seg_2 = [
        ctx.repo.get_segment(inp_id)
        for inp_id, role in ctx.repo.list_run_io(tok_2)
        if role is RunIoRole.INPUT
    ][0]

    cfg_joint: dict[str, Any] = {"tokenizers": {"qaa": "whitespace_punct@0.1.0"}}
    hash_joint = config_hash(cfg_joint)
    rk_joint = ProcessingRun.compute_run_key(
        RunStage.TOKENIZATION,
        "langpipe.tokenize",
        "0.1.0",
        hash_joint,
        [seg_1.id, seg_2.id],
    )
    joint_tok = ProcessingRun(
        id=ctx.new_id(IdPrefix.RUN),
        stage=RunStage.TOKENIZATION,
        tool_name="langpipe.tokenize",
        tool_version="0.1.0",
        config=cfg_joint,
        config_hash=hash_joint,
        code_revision=ctx.code_revision,
        run_key=rk_joint,
        status=RunStatus.SUCCEEDED,
        started_at=ctx.clock(),
        finished_at=ctx.clock(),
    )
    with ctx.repo.transaction():
        ctx.repo.add_run(joint_tok)
        ctx.repo.add_run_io(joint_tok.id, seg_1.id, RunIoRole.INPUT)
        ctx.repo.add_run_io(joint_tok.id, seg_2.id, RunIoRole.INPUT)

    # Projection model over joint tokenization run using Source 1 inventory
    proj = induce_morphology(
        ctx,
        tokenization_run_id=joint_tok.id,
        method="igt_projection@0.1.0",
        inventory_run_id=assert_run.run.id,
        language="qaa",
    )

    # Gold specifies ambiguous locator {"igt_ref": "IGT-SHARED"} without source_key
    gold_ambig_leak = MorphGold(
        gold_id="ambig-leak-gold",
        language="qaa",
        items=[
            {
                "selector": {"segment_locator": {"igt_ref": "IGT-SHARED"}, "token_ordinal": 0},
                "surface": "mabi-ki",
                "segments": [[0, 7]],
            }
        ],
        provenance={},
    )
    # Even though locator matches multiple segments, leakage guard preserves Source 1
    # observation and catches the leak against the inventory!
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[proj.run.id],
            gold=gold_ambig_leak,
        )


def test_morphology_benchmark_multiple_methods_sharing_input_segment(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: multiple evaluated methods sharing input segments deduplicate
    without false ambiguity.
    """
    from langpipe.domain.models.morphology import MorphGold

    _src, igt_run, tok_run = _setup_pipeline(
        ctx,
        tmp_path,
        "shared-seg-src",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    unseg1 = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="unsegmented@0.1.0",
        language="qaa",
    )
    unseg2 = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="bpe_char@0.1.0",
        language="qaa",
    )
    # Both methods evaluated together sharing the exact same tok_run input segments
    gold_shared = MorphGold(
        gold_id="shared-gold",
        language="qaa",
        items=[
            {
                "selector": {"segment_locator": {"igt_ref": "IGT-2"}, "token_ordinal": 0},
                "surface": "wesa-ra",
                "segments": [[0, 7]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run},
    )
    res = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unseg1.run.id, unseg2.run.id],
        gold=gold_shared,
    )
    assert res.run.status is RunStatus.SUCCEEDED
    # Segment was deduplicated across runs, resolving uniquely
    assert res.metrics["unsegmented@0.1.0"].exact_accuracy == 1.0
    assert res.metrics["bpe_char@0.1.0"].exact_accuracy == 1.0
    assert res.metrics["bpe_char@0.1.0"].abstention_rate == 1.0


def test_morphology_benchmark_gold_digest_pins_identity_and_provenance(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: gold_digest pins gold_id, language, and provenance alongside items."""
    from langpipe.domain.models.morphology import MorphGold
    from langpipe.evaluation.morphology import gold_from_igt

    _, igt_run, tok_run = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-digest-pin",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="unsegmented@0.1.0",
    )

    base_gold = gold_from_igt(ctx.repo, igt_run, ["IGT-2"], "qaa")
    gold_v1 = MorphGold(
        gold_id="gold-v1",
        language="qaa",
        items=base_gold.items,
        provenance={"version": "1"},
    )
    gold_v2 = MorphGold(
        gold_id="gold-v2",
        language="qaa",
        items=base_gold.items,
        provenance={"version": "2"},
    )

    summary1 = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unsegmented_res.run.id],
        gold=gold_v1,
    )
    summary2 = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unsegmented_res.run.id],
        gold=gold_v2,
    )

    raw1 = ctx.artifact_store.read_bytes(summary1.report.sha256)
    assert raw1 is not None
    payload1 = json.loads(raw1.decode("utf-8"))

    raw2 = ctx.artifact_store.read_bytes(summary2.report.sha256)
    assert raw2 is not None
    payload2 = json.loads(raw2.decode("utf-8"))

    assert payload1["gold_digest"] != payload2["gold_digest"]
    assert summary1.run.id != summary2.run.id


def test_morphology_benchmark_gold_from_igt_missing_ref_fails_closed(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: gold_from_igt fails closed when any requested reference is missing."""
    from langpipe.domain.errors import NotFound
    from langpipe.evaluation.morphology import gold_from_igt

    _, igt_run, _ = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-missing-ref",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    # 1. Partially missing refs
    with pytest.raises(NotFound, match=r"missing_refs=\['DOES_NOT_EXIST'\]"):
        gold_from_igt(ctx.repo, igt_run, ["IGT-2", "DOES_NOT_EXIST"], "qaa")

    # 2. All missing refs
    with pytest.raises(NotFound, match=r"missing_refs=\['ALL_MISSING'\]"):
        gold_from_igt(ctx.repo, igt_run, ["ALL_MISSING"], "qaa")


def test_morphology_benchmark_governance_denial_from_gold_provenance(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: preflight discovers and locks sources from gold provenance igt_extract_run_id."""
    from langpipe.domain.models.morphology import MorphGold

    # Source A for evaluated induction
    _, _, tok_run_id_a = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-gov-a",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id_a,
        method="unsegmented@0.1.0",
    )

    # Source B for gold IGT extraction
    src_id_b, igt_run_id_b, _ = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-gov-b",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    # Gold supplied as MorphGold with provenance pointing to igt_run_id_b
    gold = MorphGold(
        gold_id="test-gold-prov",
        language="qaa",
        items=[
            {
                "selector": {
                    "igt_ref": "IGT-2",
                    "word_ordinal": 0,
                },
                "surface": "test",
                "segments": [[0, 4]],
            }
        ],
        provenance={"igt_extract_run_id": igt_run_id_b},
    )

    # Revoke Source B only
    with ctx.repo.transaction():
        ctx.repo.set_source_status(src_id_b, SourceStatus.REVOKED, at=ctx.clock())

    # Must be denied because Source B is required by gold provenance
    with pytest.raises(PolicyDenied):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[unsegmented_res.run.id],
            gold=gold,
        )


def test_morphology_benchmark_governance_denial_from_contradictory_selector_sources(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: governance preflight checks every referenced source in selector
    even if contradictory.
    """
    from langpipe.domain.models.morphology import MorphGold

    # Source A (clean)
    _, igt_run_a, tok_run_a = _setup_pipeline(
        ctx,
        tmp_path,
        "gov-src-a",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_a,
        method="unsegmented@0.1.0",
    )
    obs_list = ctx.repo.list_igt_observations_for_run(igt_run_a)
    obs_a = obs_list[0]

    # Source B (revoked)
    src_id_b, igt_run_b, _ = _setup_pipeline(
        ctx,
        tmp_path,
        "gov-src-b",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    with ctx.repo.transaction():
        ctx.repo.set_source_status(src_id_b, SourceStatus.REVOKED, at=ctx.clock())

    # Gold names observation from clean Source A but also specifies source_key="gov-src-b"
    gold_contradictory_gov = MorphGold(
        gold_id="contradictory-gov-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "source_key": "gov-src-b",
                    "observation_id": obs_a.id,
                    "token_ordinal": 0,
                },
                "surface": "mabi-ki",
                "segments": [[0, 7]],
            }
        ],
        provenance={},
    )
    # Preflight must discover revoked Source B and refuse before processing
    with pytest.raises(PolicyDenied):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[unsegmented_res.run.id],
            gold=gold_contradictory_gov,
        )

    # Gold specifies clean source_key="gov-src-a" but igt_ref has UNPREFIXED ID
    # from revoked Source B
    obs_b_list = ctx.repo.list_igt_observations_for_run(igt_run_b)
    obs_b = obs_b_list[0]
    gold_unprefixed_id_gov = MorphGold(
        gold_id="unprefixed-id-gov-gold",
        language="qaa",
        items=[
            {
                "selector": {
                    "source_key": "gov-src-a",
                    "igt_ref": str(obs_b.id),
                    "token_ordinal": 0,
                },
                "surface": "mabi-ki",
                "segments": [[0, 7]],
            }
        ],
        provenance={},
    )
    with pytest.raises(PolicyDenied):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[unsegmented_res.run.id],
            gold=gold_unprefixed_id_gov,
        )


def test_morphology_benchmark_reuse_governance_revocation(ctx: AppContext, tmp_path: Path) -> None:
    """Gate 40: locked governance check prevents reuse if source is revoked after initial run."""
    src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-reuse-gov",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )

    # First evaluation succeeds and records benchmark run
    summary1 = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unsegmented_res.run.id],
        gold=igt_run_id,
        refs=["IGT-2"],
    )
    assert summary1.reused is False

    # Now revoke source
    with ctx.repo.transaction():
        ctx.repo.set_source_status(src_id, SourceStatus.REVOKED, at=ctx.clock())

    # Rerun must hit locked governance check on reuse path and raise PolicyDenied
    with pytest.raises(PolicyDenied):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[unsegmented_res.run.id],
            gold=igt_run_id,
            refs=["IGT-2"],
        )


def test_morphology_benchmark_rejects_duplicate_methods(ctx: AppContext, tmp_path: Path) -> None:
    """Gate 40: distinct runs of the same method are refused in either input order."""
    _src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-dup-method",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    _src_id2, _igt2, tok_run_id2 = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-dup-method-2",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    unsegmented_res1 = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )
    unsegmented_res2 = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id2,
        method="unsegmented@0.1.0",
    )
    assert unsegmented_res1.run.id != unsegmented_res2.run.id

    # Test forward order
    with pytest.raises(InvalidLineage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[unsegmented_res1.run.id, unsegmented_res2.run.id],
            gold=igt_run_id,
            refs=["IGT-2"],
        )

    # Test reversed order
    with pytest.raises(InvalidLineage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[unsegmented_res2.run.id, unsegmented_res1.run.id],
            gold=igt_run_id,
            refs=["IGT-2"],
        )


def test_morphology_benchmark_run_order_invariance_and_reuse(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: run order does not affect metrics; reversed order reuses report."""
    _src_id, igt_run_id, tok_run_id = _setup_pipeline(
        ctx,
        tmp_path,
        "igt-order-invariance",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )

    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="unsegmented@0.1.0",
    )
    bpe_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run_id,
        method="bpe_char@0.1.0",
    )

    # First evaluation: [unsegmented, bpe_char]
    summary1 = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unsegmented_res.run.id, bpe_res.run.id],
        gold=igt_run_id,
        refs=["IGT-2"],
    )
    assert summary1.reused is False
    assert list(summary1.metrics.keys()) == ["bpe_char@0.1.0", "unsegmented@0.1.0"]

    # Second evaluation in reversed order: [bpe_char, unsegmented]
    summary2 = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[bpe_res.run.id, unsegmented_res.run.id],
        gold=igt_run_id,
        refs=["IGT-2"],
    )
    assert summary2.reused is True
    assert summary2.run.id == summary1.run.id
    assert summary2.report.id == summary1.report.id
    assert list(summary2.metrics.keys()) == list(summary1.metrics.keys())

    # Full metrics comparison across all metrics
    assert summary1.metrics == summary2.metrics
    for m in ["bpe_char@0.1.0", "unsegmented@0.1.0"]:
        assert summary1.metrics[m].to_dict() == summary2.metrics[m].to_dict()

    # Inspect persisted report payload for canonical sorted evaluated_run_ids and methods
    raw1 = ctx.artifact_store.read_bytes(summary1.report.sha256)
    assert raw1 is not None
    payload1 = json.loads(raw1.decode("utf-8"))

    raw2 = ctx.artifact_store.read_bytes(summary2.report.sha256)
    assert raw2 is not None
    payload2 = json.loads(raw2.decode("utf-8"))

    assert payload1 == payload2
    assert payload1["evaluated_run_ids"] == sorted([unsegmented_res.run.id, bpe_res.run.id])
    assert payload1["methods"] == ["bpe_char@0.1.0", "unsegmented@0.1.0"]


def test_morphology_benchmark_leakage_scopes_source_object_for_overlapping_ordinals(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: leakage matching scopes to source-object identity so overlapping ordinals
    and record references across distinct source objects in the same source do not trigger
    false leakage.
    """
    from langpipe.domain.models.morphology import MorphGold, MorphGoldItem, MorphGoldSelector
    from langpipe.evaluation.morphology import gold_from_igt
    from langpipe.ingestion.ingest import ingest_source
    from langpipe.ingestion.registration import register_source

    key = "multi-obj-src"
    rel1 = "texts/multi_1.dat"
    rel2 = "texts/multi_2.dat"
    # Both files use the SAME record_ref "SHARED-REF", so both ordinals (0) and references overlap
    write_origin_file(
        tmp_path,
        rel1,
        b"\\ref SHARED-REF\n\\tx mabi-ki\n\\mr mabi -ki\n\\mg canoe-ERG\n",
    )
    write_origin_file(
        tmp_path,
        rel2,
        b"\\ref SHARED-REF\n\\tx wesa-ra\n\\mr wesa -ra\n\\mg go-NEG\n",
    )
    data = manifest_data(
        key=key,
        mode="direct",
        access_class="public",
        objects=[
            {"path": rel1, "media_type": "text/plain"},
            {"path": rel2, "media_type": "text/plain"},
        ],
    )
    data["source_type"] = "igt"
    data["languages"] = ["qaa", "por"]
    reg = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    ingest_source(ctx, reg.source.id)
    extract_res = extract_igt(ctx, reg.source.id)
    norm_res = normalize_extraction(ctx, extract_res.run.id)
    tok_res = tokenize_normalization(ctx, norm_res.run.id)

    # Get observations: obj1 has ordinal 0 and SHARED-REF, obj2 has ordinal 0 and SHARED-REF
    obs_list = ctx.repo.list_igt_observations_for_run(extract_res.run.id)
    assert len(obs_list) == 2
    obj_ids = {o.source_object_id for o in obs_list}
    assert len(obj_ids) == 2
    obs1, obs2 = obs_list[0], obs_list[1]
    assert obs1.record_ordinal == 0 and obs2.record_ordinal == 0
    assert obs1.record_ref == "SHARED-REF" and obs2.record_ref == "SHARED-REF"
    assert obs1.source_object_id != obs2.source_object_id

    # Create assertion run holding out obs1 by its ID (obs2 remains active in inventory)
    assert_clean = assert_igt(
        ctx,
        tokenization_run_id=tok_res.run.id,
        igt_extract_run_id=extract_res.run.id,
        exclude_refs=[obs1.id],
    )

    # 1. Custom gold specifies obs1 (held out), with record_ref and record_ordinal
    gold_item = MorphGoldItem(
        selector=MorphGoldSelector(
            observation_id=obs1.id,
            record_ref="SHARED-REF",
            record_ordinal=0,
            token_ordinal=0,
        ),
        surface="mabi-ki",
        segments=[[0, 4], [4, 7]],
    )
    gold = MorphGold(
        gold_id="multi-obj-gold",
        language="qaa",
        items=[gold_item],
        provenance={"igt_extract_run_id": extract_res.run.id},
    )

    # Clean run excludes obs1; active inventory has obs2 (sharing ref SHARED-REF and ordinal 0).
    # Benchmark must NOT falsely report leakage due to overlapping ref or ordinal!
    summary = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[assert_clean.run.id],
        gold=gold,
    )
    assert summary is not None

    # 2. Derived gold via gold_from_igt (populates observation_id, record_ref, record_ordinal)
    # Evaluated through igt_projection model over clean inventory
    gold_derived = gold_from_igt(ctx.repo, extract_res.run.id, [obs1.id], "qaa")
    proj_clean = induce_morphology(
        ctx,
        tokenization_run_id=tok_res.run.id,
        method="igt_projection@0.1.0",
        inventory_run_id=assert_clean.run.id,
        language="qaa",
    )
    summary_proj = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[proj_clean.run.id],
        gold=gold_derived,
    )
    assert summary_proj is not None

    # But if evaluated run includes obs1, leakage guard MUST catch it!
    assert_leaky = assert_igt(
        ctx,
        tokenization_run_id=tok_res.run.id,
        igt_extract_run_id=extract_res.run.id,
    )
    with pytest.raises(BenchmarkLeakage):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[assert_leaky.run.id],
            gold=gold,
        )


def test_morphology_benchmark_id_only_igt_ref_scoring_and_mapping(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: an ID-only igt_ref (prefixed 'id:<id>' or unprefixed '<id>') seeds the scoring
    candidate pool and successfully maps to token/analysis instead of unsegmented missing
    prediction. Cross-namespace collision between unprefixed ID and record_ref is rejected.
    """
    from langpipe.domain.models.morphology import MorphGold, MorphGoldItem, MorphGoldSelector

    _, igt_run, tok_run = _setup_pipeline(
        ctx,
        tmp_path,
        "id-scoring-src",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    bpe_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="bpe_char@0.1.0",
    )
    obs_list = ctx.repo.list_igt_observations_for_run(igt_run)
    obs = next(o for o in obs_list if o.record_ref == "IGT-2")
    w0 = obs.words[0]

    # 1. Prefixed ID: igt_ref="id:<obs.id>" without observation_id, provenance, or source_key
    gold_prefixed = MorphGold(
        gold_id="prefixed-id-gold",
        language="qaa",
        items=[
            MorphGoldItem(
                selector=MorphGoldSelector(
                    igt_ref=f"id:{obs.id}",
                    word_ordinal=0,
                ),
                surface=w0.text,
                segments=[[0, len(w0.text)]],
            )
        ],
        provenance={},
    )
    summary_pref = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[bpe_res.run.id],
        gold=gold_prefixed,
    )
    assert summary_pref is not None
    m_pref = summary_pref.metrics["bpe_char@0.1.0"]
    assert m_pref.mean_distinct_signatures_per_token == 1.0
    assert m_pref.exact_accuracy == 1.0

    # 2. Unprefixed ID: igt_ref="<obs.id>" without observation_id, provenance, or source_key
    gold_unprefixed = MorphGold(
        gold_id="unprefixed-id-gold",
        language="qaa",
        items=[
            MorphGoldItem(
                selector=MorphGoldSelector(
                    igt_ref=str(obs.id),
                    word_ordinal=0,
                ),
                surface=w0.text,
                segments=[[0, len(w0.text)]],
            )
        ],
        provenance={},
    )
    summary_unpref = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[bpe_res.run.id],
        gold=gold_unprefixed,
    )
    assert summary_unpref is not None
    m_unpref = summary_unpref.metrics["bpe_char@0.1.0"]
    assert m_unpref.mean_distinct_signatures_per_token == 1.0
    assert m_unpref.exact_accuracy == 1.0

    # 3. Cross-namespace collision: another observation has record_ref matching obs.id
    coll_tb = f"\\ref {obs.id}\n\\tx mabi-ki\n\\mr mabi -ki\n\\mg canoe-ERG\n".encode()
    _, igt_coll_run, tok_coll_run = _setup_pipeline(
        ctx,
        tmp_path,
        "collision-src",
        coll_tb,
        source_type="igt",
        languages=["qaa", "por"],
    )
    unseg_coll = induce_morphology(
        ctx,
        tokenization_run_id=tok_coll_run,
        method="unsegmented@0.1.0",
    )
    # When evaluated together across runs, unprefixed igt_ref matches obs.id (ID) AND
    # coll_obs.record_ref (record_ref). It must raise ValueError on ambiguous namespace collision!
    with pytest.raises(ValueError, match="matches multiple record namespaces"):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[bpe_res.run.id, unseg_coll.run.id],
            gold=gold_unprefixed,
        )

    # Cross-namespace collision must ALSO be caught when provenance specifies
    # igt_extract_run_id:
    gold_unprefixed_with_prov = MorphGold(
        gold_id="unprefixed-id-prov-gold",
        language="qaa",
        items=[
            MorphGoldItem(
                selector=MorphGoldSelector(
                    igt_ref=str(obs.id),
                    word_ordinal=0,
                ),
                surface=w0.text,
                segments=[[0, len(w0.text)]],
            )
        ],
        provenance={"igt_extract_run_id": igt_run},
    )
    with pytest.raises(ValueError, match="matches multiple record namespaces"):
        evaluate_morphology_benchmark(
            ctx,
            evaluated_run_ids=[bpe_res.run.id, unseg_coll.run.id],
            gold=gold_unprefixed_with_prov,
        )

    # But explicit prefixed igt_ref="id:<obs.id>" disambiguates to ID namespace and succeeds,
    # both without and with provenance present:
    summary_disambig = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[bpe_res.run.id, unseg_coll.run.id],
        gold=gold_prefixed,
    )
    assert summary_disambig is not None

    gold_prefixed_with_prov = MorphGold(
        gold_id="prefixed-id-prov-gold",
        language="qaa",
        items=[
            MorphGoldItem(
                selector=MorphGoldSelector(
                    igt_ref=f"id:{obs.id}",
                    word_ordinal=0,
                ),
                surface=w0.text,
                segments=[[0, len(w0.text)]],
            )
        ],
        provenance={"igt_extract_run_id": igt_run},
    )
    summary_disambig_prov = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[bpe_res.run.id, unseg_coll.run.id],
        gold=gold_prefixed_with_prov,
    )
    assert summary_disambig_prov is not None


def test_morphology_benchmark_gold_item_without_surface_unmapped_does_not_crash(
    ctx: AppContext, tmp_path: Path
) -> None:
    """Gate 40: a valid gold item without surface and with unresolved selector
    does not crash with TypeError, but counts missing analysis as unsegmented prediction.
    """
    from langpipe.domain.models.morphology import MorphGold, MorphGoldItem, MorphGoldSelector

    _, igt_run, tok_run = _setup_pipeline(
        ctx,
        tmp_path,
        "no-surf-src",
        SAMPLE_TOOLBOX.read_bytes(),
        source_type="igt",
        languages=["qaa", "por"],
    )
    unsegmented_res = induce_morphology(
        ctx,
        tokenization_run_id=tok_run,
        method="unsegmented@0.1.0",
    )

    # Gold item has surface=None, 1 segment [0, 4], and unmapped selector
    gold_item = MorphGoldItem(
        selector=MorphGoldSelector(
            source_key="no-surf-src",
            record_ref="NONEXISTENT-RECORD-REF",
        ),
        surface=None,
        segments=[[0, 4]],
    )
    gold = MorphGold(
        gold_id="no-surf-gold",
        language="qaa",
        items=[gold_item],
        provenance={},
    )

    # Must complete cleanly without TypeError in metrics computation
    summary = evaluate_morphology_benchmark(
        ctx,
        evaluated_run_ids=[unsegmented_res.run.id],
        gold=gold,
    )
    assert summary is not None
    m = summary.metrics["unsegmented@0.1.0"]
    assert m.abstention_rate == 1.0
    assert m.coverage == 0.0
    assert m.exact_accuracy == 1.0  # unsegmented prediction [0, 4] matches unsegmented gold [0, 4]
