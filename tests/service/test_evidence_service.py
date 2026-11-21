from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    LineageKind,
    RunIoRole,
    RunStage,
)
from langpipe.domain.errors import InvalidLineage, PolicyDenied
from langpipe.domain.models.evidence import EvidenceItem
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.lineage.evidence import EvidenceService
from langpipe.lineage.impact import impact_of
from langpipe.segmentation.recorder import ObservationRecorder, SegmentInput, TokenInput
from tests.service.manifests import (
    manifest_data,
    raise_on,
    state_counts,
    write_manifest,
    write_origin_file,
)

LANGUAGE = "mzr"


def _register(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    *,
    deny: list[str] | None = None,
) -> RegistrationResult:
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, b"origin bytes\n")
    overrides = {"deny": deny} if deny else {}
    data = manifest_data(
        key=key,
        objects=[{"path": relative, "media_type": "text/plain"}],
        **overrides,
    )
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _run(ctx: AppContext, stage: RunStage, input_ids: list[str]) -> str:
    return RunRecorder(ctx).start(stage, "langpipe.test", {}, input_ids).id


def _observations(
    ctx: AppContext, tmp_path: Path, key: str, text: str
) -> tuple[str, Segment, TokenOccurrence]:
    """Register a source and record one segment with one token. Returns (source, segment, token)."""
    registered = _register(ctx, tmp_path, key)
    sobj = registered.objects[0]
    recorder = ObservationRecorder(ctx.repo, ctx.clock, ctx.new_id)
    extraction = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    segment = recorder.record_segments(
        run_id=extraction,
        source_object_id=sobj.id,
        segments=[SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text=text)],
    )[0]
    tokenization = _run(ctx, RunStage.TOKENIZATION, [segment.id])
    token = recorder.record_tokens(
        run_id=tokenization,
        segment_id=segment.id,
        tokenizer="whitespace@1",
        orthography_profile="mzr-orth@1",
        tokens=[TokenInput(0, text, 0, len(text), None)],
    )[0]
    return registered.source.id, segment, token


def _form_observation(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    text: str,
    *,
    deny: list[str] | None = None,
) -> TokenOccurrence:
    """Register a source; record one segment and one token whose Form that segment attests."""
    registered = _register(ctx, tmp_path, key, deny=deny)
    sobj = registered.objects[0]
    recorder = ObservationRecorder(ctx.repo, ctx.clock, ctx.new_id)
    extraction = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    segment = recorder.record_segments(
        run_id=extraction,
        source_object_id=sobj.id,
        segments=[SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text=text)],
    )[0]
    tokenization = _run(ctx, RunStage.TOKENIZATION, [segment.id])
    return recorder.record_tokens(
        run_id=tokenization,
        segment_id=segment.id,
        tokenizer="whitespace@1",
        orthography_profile="mzr-orth@1",
        tokens=[TokenInput(0, text, 0, len(text), text)],
    )[0]


def _service(ctx: AppContext) -> EvidenceService:
    return EvidenceService(ctx.repo, ctx.clock, ctx.new_id)


def _add(ctx: AppContext, run_id: str, target_id: str, derived_from: list[str]) -> EvidenceItem:
    return _service(ctx).add_evidence(
        run_id=run_id,
        kind=EvidenceKind.MANUAL_ANNOTATION,
        polarity=EvidencePolarity.SUPPORTS,
        target_id=target_id,
        derived_from=derived_from,
    )


def test_evidence_requires_derivation(ctx: AppContext, tmp_path: Path) -> None:
    _, _, token = _observations(ctx, tmp_path, "derive-src", "alpha")
    run_id = _run(ctx, RunStage.MANUAL_ANNOTATION, [token.id])
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        _add(ctx, run_id, token.id, derived_from=[])

    assert state_counts(ctx) == before


def test_evidence_denied_ancestor_creates_no_rows(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "denied-src", deny=["human_review"])
    sobj = registered.objects[0]
    extraction = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    segment = ObservationRecorder(ctx.repo, ctx.clock, ctx.new_id).record_segments(
        run_id=extraction,
        source_object_id=sobj.id,
        segments=[SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="alpha")],
    )[0]
    run_id = _run(ctx, RunStage.MANUAL_ANNOTATION, [segment.id])
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        _add(ctx, run_id, segment.id, derived_from=[segment.id])

    assert state_counts(ctx) == before


def test_evidence_rejects_non_manual_run(ctx: AppContext, tmp_path: Path) -> None:
    _, _, token = _observations(ctx, tmp_path, "stage-src", "alpha")
    run_id = _run(ctx, RunStage.EXTRACTION, [token.id])
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        _add(ctx, run_id, token.id, derived_from=[token.id])

    assert state_counts(ctx) == before


def test_add_evidence_writes_edges_and_run_io(ctx: AppContext, tmp_path: Path) -> None:
    _, _, token = _observations(ctx, tmp_path, "add-src", "alpha")
    run_id = _run(ctx, RunStage.MANUAL_ANNOTATION, [token.id])

    item = _add(ctx, run_id, token.id, derived_from=[token.id])

    assert item.target_id == token.id
    assert item.run_id == run_id
    edges = ctx.repo.list_lineage_edges(item.id, "out")
    assert [(e.to_id, e.kind) for e in edges] == [(token.id, LineageKind.DERIVED_FROM)]
    run_io = set(ctx.repo.list_run_io(run_id))
    assert (token.id, RunIoRole.INPUT) in run_io
    assert (item.id, RunIoRole.OUTPUT) in run_io


def test_supersede_is_atomic_without_nested_transactions(ctx: AppContext, tmp_path: Path) -> None:
    _, _, token = _observations(ctx, tmp_path, "atomic-src", "alpha")
    run_id = _run(ctx, RunStage.MANUAL_ANNOTATION, [token.id])
    old = _add(ctx, run_id, token.id, derived_from=[token.id])
    before = state_counts(ctx)

    # Fail the supersedes edge after the new evidence row is written; the whole call must roll back.
    with (
        raise_on(
            ctx.repo,
            "add_lineage_edge",
            InvalidLineage(),
            when=lambda args: args[0].kind is LineageKind.SUPERSEDES,
        ),
        pytest.raises(InvalidLineage),
    ):
        _service(ctx).supersede_evidence(
            run_id=run_id,
            old_id=old.id,
            kind=EvidenceKind.MANUAL_ANNOTATION,
            polarity=EvidencePolarity.CONTRADICTS,
            target_id=token.id,
            derived_from=[token.id],
        )
    assert state_counts(ctx) == before

    replacement = _service(ctx).supersede_evidence(
        run_id=run_id,
        old_id=old.id,
        kind=EvidenceKind.MANUAL_ANNOTATION,
        polarity=EvidencePolarity.CONTRADICTS,
        target_id=token.id,
        derived_from=[token.id],
    )

    supersedes = ctx.repo.list_lineage_edges(replacement.id, "out")
    assert [(e.to_id, e.kind) for e in supersedes if e.kind is LineageKind.SUPERSEDES] == [
        (old.id, LineageKind.SUPERSEDES)
    ]
    assert ctx.repo.get_evidence(old.id) == old


def test_superseding_evidence_leaves_tokens_unchanged(ctx: AppContext, tmp_path: Path) -> None:
    _, _, token = _observations(ctx, tmp_path, "tokens-src", "alpha")
    run_id = _run(ctx, RunStage.MANUAL_ANNOTATION, [token.id])
    old = _add(ctx, run_id, token.id, derived_from=[token.id])
    tokens_before = ctx.repo.list_tokens(token.segment_id)

    _service(ctx).supersede_evidence(
        run_id=run_id,
        old_id=old.id,
        kind=EvidenceKind.MANUAL_ANNOTATION,
        polarity=EvidencePolarity.SUPPORTS,
        target_id=token.id,
        derived_from=[token.id],
    )

    assert ctx.repo.list_tokens(token.segment_id) == tokens_before


def test_supersede_rejects_target_mismatch(ctx: AppContext, tmp_path: Path) -> None:
    _, segment, token = _observations(ctx, tmp_path, "mismatch-src", "alpha")
    run_id = _run(ctx, RunStage.MANUAL_ANNOTATION, [token.id])
    old = _add(ctx, run_id, token.id, derived_from=[token.id])
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        _service(ctx).supersede_evidence(
            run_id=run_id,
            old_id=old.id,
            kind=EvidenceKind.MANUAL_ANNOTATION,
            polarity=EvidencePolarity.SUPPORTS,
            target_id=segment.id,
            derived_from=[segment.id],
        )

    assert state_counts(ctx) == before


def test_supersede_denied_ancestor_of_old_evidence_creates_no_rows(
    ctx: AppContext, tmp_path: Path
) -> None:
    allowed = _form_observation(ctx, tmp_path, "sup-allowed", "kanu")
    assert allowed.form_id is not None
    run_id = _run(ctx, RunStage.MANUAL_ANNOTATION, [allowed.id])
    old = _service(ctx).add_evidence(
        run_id=run_id,
        kind=EvidenceKind.MANUAL_ANNOTATION,
        polarity=EvidencePolarity.SUPPORTS,
        target_id=allowed.id,
        derived_from=[allowed.id, allowed.form_id],
    )
    # A second source denying human review attests the same Form after the old evidence exists.
    _form_observation(ctx, tmp_path, "sup-denied", "kanu", deny=["human_review"])
    before = state_counts(ctx)
    run_io_before = ctx.repo.list_run_io(run_id)
    old_edges_before = ctx.repo.list_lineage_edges(old.id, "out")

    # The replacement's own target and derivation come only from the allowed source.
    with pytest.raises(PolicyDenied):
        _service(ctx).supersede_evidence(
            run_id=run_id,
            old_id=old.id,
            kind=EvidenceKind.MANUAL_ANNOTATION,
            polarity=EvidencePolarity.CONTRADICTS,
            target_id=allowed.id,
            derived_from=[allowed.id],
        )

    assert state_counts(ctx) == before
    assert ctx.repo.list_run_io(run_id) == run_io_before
    assert ctx.repo.get_evidence(old.id) == old
    assert ctx.repo.list_lineage_edges(old.id, "out") == old_edges_before


def test_impact_of_source_reaches_tokens_and_evidence(ctx: AppContext, tmp_path: Path) -> None:
    source_id, _, token = _observations(ctx, tmp_path, "impact-src", "alpha")
    run_id = _run(ctx, RunStage.MANUAL_ANNOTATION, [token.id])
    item = _add(ctx, run_id, token.id, derived_from=[token.id])

    impact = impact_of(ctx.repo, source_id)

    found = {entry.object_id: entry for entry in impact}
    assert found[token.id].entity_type is EntityType.TOKEN_OCCURRENCE
    assert found[item.id].entity_type is EntityType.EVIDENCE_ITEM
    assert found[token.id].depth < found[item.id].depth
    assert [(entry.depth, entry.object_id) for entry in impact] == sorted(
        (entry.depth, entry.object_id) for entry in impact
    )
