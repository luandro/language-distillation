"""WP3.5 alignment policy preflight: governance follows lineage and fails closed.

``ensure_alignment_allowed`` resolves Operation.ALIGN over the full source ancestry of
every alignment input before any run, adapter call or semantic row: denials, revoked
sources and inputs without source ancestry leave exactly one existing POLICY_DENIED
audit event and nothing else. The returned sorted source ids carry the combined
ancestry, so an alignment cannot open an operation that every ancestor keeps closed
(ADR-0011 §7, ADR-0025).
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from langpipe.alignment.governance import ensure_alignment_allowed
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AuditEventType,
    Operation,
    PolicyDecision,
    SourceStatus,
)
from langpipe.domain.errors import InvalidLineage, PolicyDenied
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.extraction.service import extract_source
from langpipe.governance.policy import resolve_many
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.normalization.service import normalize_extraction
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import (
    manifest_data,
    spy_all_io,
    state_counts,
    write_manifest,
    write_origin_file,
)

GOLDEN_SOURCES = Path(__file__).resolve().parents[1] / "golden" / "fixture" / "sources"
DISTILL_ONLY_SOURCE = "01-parallel-distill"
DIRECT_SOURCE = "02-educational-direct"
PLAIN = "text/plain"
ALIGN = Operation.ALIGN
DIRECT_TRAINING = Operation.DIRECT_TRAINING


@dataclass(frozen=True)
class _Pipeline:
    source_id: str
    segments: tuple[Segment, ...]
    tokens: tuple[TokenOccurrence, ...]


def _golden_pipeline(ctx: AppContext, dirname: str) -> _Pipeline:
    registered = register_source(ctx, GOLDEN_SOURCES / dirname / "manifest.yaml")
    ingest_source(ctx, registered.source.id)
    extraction = extract_source(ctx, registered.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenize_normalization(ctx, normalization.run.id)
    segments = ctx.repo.list_segments_for_run(normalization.run.id)
    tokens = tuple(token for segment in segments for token in ctx.repo.list_tokens(segment.id))
    return _Pipeline(registered.source.id, tuple(segments), tokens)


def _register_text(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    text: str,
    *,
    mode: str = "direct",
    deny: list[str] | None = None,
) -> RegistrationResult:
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, text.encode("utf-8"))
    overrides: dict[str, object] = {} if deny is None else {"deny": deny}
    data = manifest_data(
        key=key, mode=mode, objects=[{"path": relative, "media_type": PLAIN}], **overrides
    )
    data["source_type"] = "monolingual_text"
    data["languages"] = ["qaa"]
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _text_pipeline(
    ctx: AppContext, tmp_path: Path, key: str, text: str, **kwargs: object
) -> _Pipeline:
    registered = _register_text(ctx, tmp_path, key, text, **kwargs)
    ingest_source(ctx, registered.source.id)
    extraction = extract_source(ctx, registered.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    segments = ctx.repo.list_segments_for_run(normalization.run.id)
    return _Pipeline(registered.source.id, tuple(segments), ())


def _denied_details(ctx: AppContext) -> list[tuple[str, str]]:
    events = [
        event
        for event in ctx.repo.list_audit_events()
        if event.event_type is AuditEventType.POLICY_DENIED
    ]
    return [
        (event.subject_id or "", event.details["decision"])
        for event in events
        if event.details.get("operation") == ALIGN.value
    ]


def _policy_of(ctx: AppContext, source_id: str):
    return ctx.repo.get_policy(ctx.repo.get_source(source_id).policy_id)


def test_deny_either_side_blocks_alignment(ctx: AppContext, tmp_path: Path) -> None:
    allowed = _text_pipeline(ctx, tmp_path, "gov-allowed", "kanu mabi tesa")
    denied = _text_pipeline(ctx, tmp_path, "gov-denied", "wesa nawa", deny=[ALIGN.value])
    inputs = [segment.id for segment in allowed.segments] + [
        segment.id for segment in denied.segments
    ]
    before = state_counts(ctx)

    with spy_all_io(ctx) as mocks:
        with pytest.raises(PolicyDenied) as exc_info:
            ensure_alignment_allowed(ctx, inputs)
        assert all(mock.call_count == 0 for mock in mocks)

    assert exc_info.value.source_id == denied.source_id
    assert exc_info.value.operation is ALIGN
    assert exc_info.value.decision is PolicyDecision.DENY
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    assert _denied_details(ctx) == [(denied.source_id, PolicyDecision.DENY.value)]

    # Whichever order the sides are given, the denied side blocks the whole alignment.
    with pytest.raises(PolicyDenied):
        ensure_alignment_allowed(ctx, list(reversed(inputs)))


def test_review_required_denies_alignment(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register_text(ctx, tmp_path, "gov-review", "kanu mabi", mode="review_required")
    object_id = ctx.repo.list_source_objects(registered.source.id)[0].id
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied) as exc_info:
        ensure_alignment_allowed(ctx, [object_id])

    assert exc_info.value.decision is PolicyDecision.REVIEW_REQUIRED
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_exclude_denies_alignment(ctx: AppContext, tmp_path: Path) -> None:
    # Exclude-mode registration records metadata only, so the source itself is the input.
    registered = _register_text(ctx, tmp_path, "gov-exclude", "kanu mabi", mode="exclude")
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied) as exc_info:
        ensure_alignment_allowed(ctx, [registered.source.id])

    assert exc_info.value.decision is PolicyDecision.DENY
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_archive_only_denies_alignment(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register_text(ctx, tmp_path, "gov-archive", "kanu mabi", mode="archive_only")
    object_id = ctx.repo.list_source_objects(registered.source.id)[0].id
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied) as exc_info:
        ensure_alignment_allowed(ctx, [object_id])

    assert exc_info.value.decision is PolicyDecision.DENY
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_revoked_source_denies_alignment(ctx: AppContext, tmp_path: Path) -> None:
    pipeline = _text_pipeline(ctx, tmp_path, "gov-revoked", "kanu mabi tesa")
    inputs = [segment.id for segment in pipeline.segments]
    assert ensure_alignment_allowed(ctx, inputs) == (pipeline.source_id,)

    with ctx.repo.transaction():
        ctx.repo.set_source_status(pipeline.source_id, SourceStatus.REVOKED, ctx.clock())
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied) as exc_info:
        ensure_alignment_allowed(ctx, inputs)

    assert exc_info.value.source_id == pipeline.source_id
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_missing_ancestry_denies_alignment(ctx: AppContext, tmp_path: Path) -> None:
    pipeline = _text_pipeline(ctx, tmp_path, "gov-ancestry", "kanu mabi")
    # A registered object with no lineage to any source fails closed.
    orphan_id = ctx.repo.list_audit_events()[0].run_id
    assert orphan_id is not None
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied) as exc_info:
        ensure_alignment_allowed(ctx, [orphan_id, pipeline.segments[0].id])

    assert exc_info.value.decision is PolicyDecision.DENY
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}


def test_allowed_alignment_returns_sorted_sources(ctx: AppContext, tmp_path: Path) -> None:
    first = _text_pipeline(ctx, tmp_path, "gov-ok-a", "kanu mabi")
    second = _text_pipeline(ctx, tmp_path, "gov-ok-b", "wesa tesa")
    inputs = [segment.id for segment in first.segments + second.segments]
    before = state_counts(ctx)

    sources = ensure_alignment_allowed(ctx, inputs)

    assert sources == tuple(sorted((first.source_id, second.source_id)))
    assert state_counts(ctx) == before


def test_reuse_rechecks_both_sources(ctx: AppContext, tmp_path: Path) -> None:
    first = _text_pipeline(ctx, tmp_path, "gov-reuse-a", "kanu mabi")
    second = _text_pipeline(ctx, tmp_path, "gov-reuse-b", "wesa tesa")
    inputs = [segment.id for segment in first.segments + second.segments]

    # A previously allowed identical input set is not a license: both sides are
    # re-resolved on every call.
    assert ensure_alignment_allowed(ctx, inputs) == tuple(
        sorted((first.source_id, second.source_id))
    )
    with ctx.repo.transaction():
        ctx.repo.set_source_status(second.source_id, SourceStatus.REVOKED, ctx.clock())
    with pytest.raises(PolicyDenied) as exc_info:
        ensure_alignment_allowed(ctx, inputs)
    assert exc_info.value.source_id == second.source_id

    with ctx.repo.transaction():
        ctx.repo.set_source_status(second.source_id, SourceStatus.INGESTED, ctx.clock())
        ctx.repo.set_source_status(first.source_id, SourceStatus.REVOKED, ctx.clock())
    with pytest.raises(PolicyDenied) as exc_info:
        ensure_alignment_allowed(ctx, inputs)
    assert exc_info.value.source_id == first.source_id


def test_shared_form_inherits_combined_alignment_decisions(ctx: AppContext) -> None:
    distill = _golden_pipeline(ctx, DISTILL_ONLY_SOURCE)
    direct = _golden_pipeline(ctx, DIRECT_SOURCE)

    shared_forms = {
        token.form_id
        for token in (*distill.tokens, *direct.tokens)
        if token.form_id is not None and token.normalized_surface == "mabi"
    }
    assert len(shared_forms) == 1
    form_id = next(iter(shared_forms))

    # Both ancestor sources allow ALIGN, so the shared form is alignable ...
    sources = ensure_alignment_allowed(ctx, [form_id])
    assert sources == tuple(sorted((distill.source_id, direct.source_id)))

    # ... and under ADR-0025 the combined ancestry allows training. Alignment still cannot
    # open an operation that every ancestor keeps closed: raw redistribution stays denied.
    policies = [_policy_of(ctx, source_id) for source_id in sources]
    assert resolve_many(policies, DIRECT_TRAINING) is PolicyDecision.ALLOW
    assert resolve_many(policies, Operation.REDISTRIBUTE_RAW) is PolicyDecision.DENY
    assert resolve_many(policies, ALIGN) is PolicyDecision.ALLOW


def test_alignment_inputs_allow_direct_training(ctx: AppContext) -> None:
    pipeline = _golden_pipeline(ctx, DISTILL_ONLY_SOURCE)
    inputs = [segment.id for segment in pipeline.segments] + [token.id for token in pipeline.tokens]
    assert inputs

    from langpipe.governance.lineage_policy import effective_decision

    for input_id in inputs:
        assert effective_decision(ctx.repo, input_id, DIRECT_TRAINING) is PolicyDecision.ALLOW

    sources = ensure_alignment_allowed(ctx, inputs)
    assert sources == (pipeline.source_id,)
    assert resolve_many([_policy_of(ctx, pipeline.source_id)], DIRECT_TRAINING) is (
        PolicyDecision.ALLOW
    )


def test_empty_inputs_are_invalid(ctx: AppContext) -> None:
    with pytest.raises(InvalidLineage):
        ensure_alignment_allowed(ctx, [])
