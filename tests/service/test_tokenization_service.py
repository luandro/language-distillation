"""TokenizationService (M2 WP2.10): normalized segments -> tokens and forms."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType, RunStage, RunStatus
from langpipe.domain.errors import UnsupportedSource
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.extraction.service import ExtractionResult, extract_source
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.normalization.profiles import GENERIC_NORMALIZATION_PROFILES, DefaultTextProfile
from langpipe.normalization.service import (
    NormalizationResultSummary,
    normalize_extraction,
)
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.service import TokenizationSummary, tokenize_normalization
from tests.service.manifests import (
    record_finished_runs,
    state_counts,
    write_origin_file,
)
from tests.service.test_normalization_service import _write_source

GOLDEN_SOURCES = Path(__file__).resolve().parents[1] / "golden" / "fixture" / "sources"


@dataclass(frozen=True)
class _Flow:
    extraction: ExtractionResult
    normalization: NormalizationResultSummary
    tokenization: TokenizationSummary
    normalized: tuple[Segment, ...]
    tokens: tuple[TokenOccurrence, ...]


def _flow_from_extraction(ctx: AppContext, extraction: ExtractionResult) -> _Flow:
    normalization = normalize_extraction(ctx, extraction.run.id)
    normalized = tuple(ctx.repo.list_segments_for_run(normalization.run.id))
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    tokens = tuple(token for segment in normalized for token in ctx.repo.list_tokens(segment.id))
    return _Flow(extraction, normalization, tokenization, normalized, tokens)


def _golden_flow(ctx: AppContext, dirname: str) -> _Flow:
    registered = register_source(ctx, GOLDEN_SOURCES / dirname / "manifest.yaml")
    ingest_source(ctx, registered.source.key)
    return _flow_from_extraction(ctx, extract_source(ctx, registered.source.id))


def _text_flow(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    text: str,
    *,
    languages: tuple[str, ...] = ("qaa",),
) -> _Flow:
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, text.encode("utf-8"))
    registered = _write_source(
        ctx,
        tmp_path,
        key,
        [{"path": relative, "media_type": "text/plain"}],
        languages=languages,
    )
    ingest_source(ctx, registered.source.id)
    return _flow_from_extraction(ctx, extract_source(ctx, registered.source.id))


def _forms(flow: _Flow, surface: str) -> set[str]:
    return {
        token.form_id
        for token in flow.tokens
        if token.normalized_surface == surface and token.form_id is not None
    }


def test_tokenization_rerun_idempotent(ctx: AppContext) -> None:
    flow = _golden_flow(ctx, "05-monolingual")
    before = state_counts(ctx)

    second = tokenize_normalization(ctx, flow.normalization.run.id)

    assert second.reused is True
    assert second.run == flow.tokenization.run
    assert second.tokens == flow.tokenization.tokens
    assert second.forms == flow.tokenization.forms
    assert state_counts(ctx) == before


def test_token_raw_and_normalized_spans_slice_correctly(ctx: AppContext) -> None:
    flow = _golden_flow(ctx, "05-monolingual")
    nfd = [segment for segment in flow.normalized if segment.raw_text == "kanu\u0301 wesa."]
    assert len(nfd) == 1
    segment = nfd[0]
    assert segment.normalized_text == "kanú wesa."

    matched = [
        token for token in ctx.repo.list_tokens(segment.id) if token.normalized_surface == "kanú"
    ]
    assert len(matched) == 1
    token = matched[0]
    assert token.raw_span is not None and token.normalized_span is not None
    assert (token.raw_span.start, token.raw_span.end) == (0, 5)
    assert (token.normalized_span.start, token.normalized_span.end) == (0, 4)
    assert token.raw_span.slice(segment.raw_text) == "kanu\u0301"
    assert token.normalized_span.slice(segment.normalized_text) == "kanú"


def test_same_surface_across_sources_shares_form(ctx: AppContext) -> None:
    parallel = _golden_flow(ctx, "01-parallel-distill")
    monolingual = _golden_flow(ctx, "05-monolingual")
    educational = _golden_flow(ctx, "02-educational-direct")

    kanu = _forms(parallel, "kanu")
    assert kanu
    assert kanu == _forms(monolingual, "kanu")

    mabi = _forms(parallel, "mabi")
    assert mabi
    assert mabi == _forms(educational, "mabi")


def test_orthographic_variant_distinct_forms(ctx: AppContext) -> None:
    flow = _golden_flow(ctx, "05-monolingual")

    plain = _forms(flow, "kanu")
    accented = _forms(flow, "kanú")

    assert plain
    assert accented
    assert plain.isdisjoint(accented)


def test_nfd_and_nfc_attestations_share_one_form(ctx: AppContext) -> None:
    monolingual = _golden_flow(ctx, "05-monolingual")  # line 3 is NFD
    educational = _golden_flow(ctx, "02-educational-direct")  # line 2 is NFC

    nfd_forms = _forms(monolingual, "kanú")
    nfc_forms = _forms(educational, "kanú")

    assert nfd_forms
    assert nfd_forms == nfc_forms


def test_punct_tokens_have_no_form(ctx: AppContext) -> None:
    flow = _golden_flow(ctx, "05-monolingual")

    puncts = [token for token in flow.tokens if token.normalized_surface == "."]

    assert puncts
    assert all(token.form_id is None for token in puncts)


def test_hyphenated_token_single_occurrence_with_full_raw_span(ctx: AppContext) -> None:
    flow = _golden_flow(ctx, "01-parallel-distill")

    hyphenated = [token for token in flow.tokens if token.normalized_surface == "mabi-ki"]
    assert hyphenated
    for token in hyphenated:
        segment = ctx.repo.get_segment(token.segment_id)
        assert token.raw_span is not None
        assert token.raw_span.slice(segment.raw_text) == "mabi-ki"
        assert token.form_id is not None


def test_unmappable_segment_gets_no_tokens(ctx: AppContext, tmp_path: Path) -> None:
    # Hangul jamo split by the NFC chunker force the whole-segment fallback; the offset map then
    # swallows the first token's boundary (the raw span is empty), so the segment is not tokenized.
    flow = _text_flow(ctx, tmp_path, "unmap-src", "\u1100\u1161.")

    assert len(flow.normalized) == 1
    segment = flow.normalized[0]
    assert segment.normalized_text == "가."
    assert ctx.repo.list_tokens(segment.id) == []
    assert flow.tokenization.tokens == 0

    assert flow.tokenization.report is not None
    payload = json.loads(ctx.artifact_store.read_bytes(flow.tokenization.report.sha256))
    assert payload["skipped"] == [{"segment_id": segment.id, "reason": "token_span_unmappable"}]


class _DefaultTextV2(DefaultTextProfile):
    version: ClassVar[str] = "0.1.1"


def test_extraction_tokens_unchanged_after_renormalization(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow = _golden_flow(ctx, "05-monolingual")
    first_tokens = {
        token.id: token for segment in flow.normalized for token in ctx.repo.list_tokens(segment.id)
    }

    patched = VersionedRegistry((*GENERIC_NORMALIZATION_PROFILES, _DefaultTextV2()))
    monkeypatch.setattr("langpipe.normalization.service.NORMALIZATION_PROFILES", patched)
    monkeypatch.setattr("langpipe.tokenization.service.NORMALIZATION_PROFILES", patched)

    renormalized = normalize_extraction(
        ctx, flow.extraction.run.id, profiles={"qaa": "default_text@0.1.1"}
    )
    assert renormalized.run.id != flow.normalization.run.id
    tokenize_normalization(ctx, renormalized.run.id)

    after = {
        token.id: token
        for segment in ctx.repo.list_segments_for_run(flow.normalization.run.id)
        for token in ctx.repo.list_tokens(segment.id)
    }
    assert after == first_tokens


def test_retired_profile_blocks_tokenization(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = register_source(ctx, GOLDEN_SOURCES / "05-monolingual" / "manifest.yaml")
    ingest_source(ctx, registered.source.key)
    extraction = extract_source(ctx, registered.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    finished = record_finished_runs(ctx, monkeypatch)
    empty = VersionedRegistry(())
    monkeypatch.setattr("langpipe.tokenization.service.NORMALIZATION_PROFILES", empty)
    tokens_before = ctx.repo.count(EntityType.TOKEN_OCCURRENCE)

    with pytest.raises(UnsupportedSource) as info:
        tokenize_normalization(ctx, normalization.run.id)

    assert info.value.reason == "no_extractor"
    assert ctx.repo.count(EntityType.TOKEN_OCCURRENCE) == tokens_before
    failed = [run for run in finished if run.status is RunStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].stage is RunStage.TOKENIZATION
    assert ctx.repo.list_run_io(failed[0].id) == []
