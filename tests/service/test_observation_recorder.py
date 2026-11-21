from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    EntityType,
    LineageKind,
    RunIoRole,
    RunStage,
    SegmentStatus,
)
from langpipe.domain.errors import InvalidLineage, PolicyDenied, SchemaViolation
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.lineage.impact import impact_of
from langpipe.segmentation.recorder import (
    NormalizedSegmentInput,
    ObservationRecorder,
    SegmentInput,
    TokenInput,
)
from tests.service.manifests import (
    manifest_data,
    state_counts,
    write_manifest,
    write_origin_file,
)

LANGUAGE = "mzr"
TOKENIZER = "whitespace@1"
PROFILE = "mzr-orth@1"


def _register(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    *,
    mode: str = "direct",
    deny: list[str] | None = None,
) -> RegistrationResult:
    relative = f"texts/{key}.txt"
    write_origin_file(tmp_path, relative, b"origin bytes\n")
    overrides = {"deny": deny} if deny else {}
    data = manifest_data(
        key=key,
        mode=mode,
        objects=[{"path": relative, "media_type": "text/plain"}],
        **overrides,
    )
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _run(ctx: AppContext, stage: RunStage, input_ids: list[str]) -> str:
    return RunRecorder(ctx).start(stage, "langpipe.test", {}, input_ids).id


def _recorder(ctx: AppContext) -> ObservationRecorder:
    return ObservationRecorder(ctx.repo, ctx.clock, ctx.new_id)


def _segment(ctx: AppContext, tmp_path: Path, key: str, text: str) -> tuple[str, Segment]:
    """Register a source, run extraction and record one segment. Returns (source id, segment)."""
    registered = _register(ctx, tmp_path, key)
    sobj = registered.objects[0]
    run_id = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    segments = _recorder(ctx).record_segments(
        run_id=run_id,
        source_object_id=sobj.id,
        segments=[SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text=text)],
    )
    return registered.source.id, segments[0]


def _normalized_segment(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    text: str,
    normalized_text: str | None = None,
) -> tuple[str, Segment]:
    """Register a source, extract one raw segment, then record one normalized segment."""
    source_id, raw = _segment(ctx, tmp_path, key, text)
    run_id = _run(ctx, RunStage.NORMALIZATION, [raw.id])
    normalized = _recorder(ctx).record_normalized_segments(
        run_id=run_id,
        normalization_profile=PROFILE,
        items=[
            NormalizedSegmentInput(
                raw_segment_id=raw.id,
                normalized_text=text if normalized_text is None else normalized_text,
                failed=False,
            )
        ],
    )[0]
    return source_id, normalized


def _tokenize(
    ctx: AppContext,
    segment: Segment,
    tokens: list[TokenInput],
) -> list[TokenOccurrence]:
    run_id = _run(ctx, RunStage.TOKENIZATION, [segment.id])
    return _recorder(ctx).record_tokens(
        run_id=run_id,
        segment_id=segment.id,
        tokenizer=TOKENIZER,
        orthography_profile=PROFILE,
        tokens=tokens,
    )


def _tokenize_normalized(
    ctx: AppContext,
    segment: Segment,
    tokens: list[TokenInput],
) -> list[TokenOccurrence]:
    run_id = _run(ctx, RunStage.TOKENIZATION, [segment.id])
    return _recorder(ctx).record_normalized_tokens(
        run_id=run_id,
        segment_id=segment.id,
        tokenizer=TOKENIZER,
        orthography_profile=PROFILE,
        tokens=tokens,
    )


def test_extract_denied_for_archive_only_creates_nothing(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "archive-src", mode="archive_only")
    sobj = registered.objects[0]
    run_id = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        _recorder(ctx).record_segments(
            run_id=run_id,
            source_object_id=sobj.id,
            segments=[SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="alpha")],
        )

    assert state_counts(ctx) == before
    assert ctx.repo.list_run_io(run_id) == []
    assert ctx.repo.list_segments(sobj.id) == []


def test_record_segments_creates_edges_and_run_io(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "seg-src")
    sobj = registered.objects[0]
    run_id = _run(ctx, RunStage.EXTRACTION, [sobj.id])

    segments = _recorder(ctx).record_segments(
        run_id=run_id,
        source_object_id=sobj.id,
        segments=[
            SegmentInput(ordinal=0, language=LANGUAGE, locator={"line": 1}, raw_text="alpha"),
            SegmentInput(ordinal=1, language=LANGUAGE, locator={"line": 2}, raw_text="beta"),
        ],
    )

    assert [s.ordinal for s in segments] == [0, 1]
    for segment in segments:
        assert segment.source_id == registered.source.id
        assert segment.source_object_id == sobj.id
        assert segment.run_id == run_id
        assert segment.normalized_text is None
        edges = ctx.repo.list_lineage_edges(segment.id, "out")
        assert [(e.to_id, e.kind) for e in edges] == [(sobj.id, LineageKind.EXTRACTED_FROM)]
    run_io = set(ctx.repo.list_run_io(run_id))
    assert (sobj.id, RunIoRole.INPUT) in run_io
    assert {(s.id, RunIoRole.OUTPUT) for s in segments} <= run_io


def test_record_segments_rejects_duplicate_ordinals_atomically(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _register(ctx, tmp_path, "dup-src")
    sobj = registered.objects[0]
    run_id = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    before = state_counts(ctx)

    with pytest.raises(SchemaViolation):
        _recorder(ctx).record_segments(
            run_id=run_id,
            source_object_id=sobj.id,
            segments=[
                SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="alpha"),
                SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="beta"),
            ],
        )

    assert state_counts(ctx) == before


def test_record_tokens_rejects_span_mismatch_atomically(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "span-src", "alpha beta")
    run_id = _run(ctx, RunStage.TOKENIZATION, [segment.id])  # the run row exists before the write
    before = state_counts(ctx)

    with pytest.raises(SchemaViolation):
        _recorder(ctx).record_tokens(
            run_id=run_id,
            segment_id=segment.id,
            tokenizer=TOKENIZER,
            orthography_profile=PROFILE,
            tokens=[
                TokenInput(0, "alpha", 0, 5, None),
                # The surface "bet" does not match raw_text[6:10] == "beta".
                TokenInput(1, "bet", 6, 10, None),
            ],
        )

    assert state_counts(ctx) == before
    assert ctx.repo.list_run_io(run_id) == []
    assert ctx.repo.list_tokens(segment.id) == []


def test_record_tokens_rejects_half_specified_span(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "half-src", "alpha")

    with pytest.raises(SchemaViolation):
        _tokenize(ctx, segment, [TokenInput(0, "alpha", 0, None, None)])

    assert ctx.repo.list_tokens(segment.id) == []


def test_record_tokens_rejects_non_nfc_form_text(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "nfc-src", "kanu")
    decomposed = "kanú"  # combining acute accent, not NFC

    with pytest.raises(SchemaViolation):
        _tokenize(ctx, segment, [TokenInput(0, "kanu", 0, 4, decomposed)])

    assert ctx.repo.count(EntityType.FORM) == 0


def test_record_tokens_creates_token_form_and_lineage(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "tok-src", "kanu ti")
    run_id = _run(ctx, RunStage.TOKENIZATION, [segment.id])

    tokens = _recorder(ctx).record_tokens(
        run_id=run_id,
        segment_id=segment.id,
        tokenizer=TOKENIZER,
        orthography_profile=PROFILE,
        tokens=[
            TokenInput(0, "kanu", 0, 4, "kanu"),
            TokenInput(1, "ti", 5, 7, None),
        ],
    )

    assert [t.ordinal for t in tokens] == [0, 1]
    form_id = tokens[0].form_id
    assert form_id is not None
    assert tokens[1].form_id is None
    form_edges = ctx.repo.list_lineage_edges(form_id, "out")
    assert [(e.to_id, e.kind) for e in form_edges] == [(segment.id, LineageKind.DERIVED_FROM)]
    token_edges = ctx.repo.list_lineage_edges(tokens[1].id, "out")
    assert [(e.to_id, e.kind) for e in token_edges] == [(segment.id, LineageKind.DERIVED_FROM)]
    run_io = set(ctx.repo.list_run_io(run_id))
    assert (segment.id, RunIoRole.INPUT) in run_io
    assert {(t.id, RunIoRole.OUTPUT) for t in tokens} <= run_io
    assert (form_id, RunIoRole.OUTPUT) in run_io


def test_same_form_text_reuses_form(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "reuse-src", "kanu kanu")

    tokens = _tokenize(
        ctx,
        segment,
        [
            TokenInput(0, "kanu", 0, 4, "kanu"),
            TokenInput(1, "kanu", 5, 9, "kanu"),
        ],
    )

    assert tokens[0].form_id is not None
    assert tokens[0].form_id == tokens[1].form_id
    assert ctx.repo.count(EntityType.FORM) == 1


def test_orthographic_variant_creates_distinct_forms(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "variant-src", "kanu kanú")

    tokens = _tokenize(
        ctx,
        segment,
        [
            TokenInput(0, "kanu", 0, 4, "kanu"),
            TokenInput(1, "kanú", 5, 9, "kanú"),
        ],
    )

    assert tokens[0].form_id is not None
    assert tokens[1].form_id is not None
    assert tokens[0].form_id != tokens[1].form_id
    assert ctx.repo.count(EntityType.FORM) == 2


def test_shared_form_retains_lineage_to_each_source(ctx: AppContext, tmp_path: Path) -> None:
    source_a, segment_a = _normalized_segment(ctx, tmp_path, "shared-a", "kanu")
    source_b, segment_b = _normalized_segment(ctx, tmp_path, "shared-b", "kanu")
    run_a = _run(ctx, RunStage.TOKENIZATION, [segment_a.id])
    run_b = _run(ctx, RunStage.TOKENIZATION, [segment_b.id])

    first = _recorder(ctx).record_tokens(
        run_id=run_a,
        segment_id=segment_a.id,
        tokenizer=TOKENIZER,
        orthography_profile=PROFILE,
        tokens=[TokenInput(0, "kanu", 0, 4, "kanu")],
    )[0]
    second = _recorder(ctx).record_tokens(
        run_id=run_b,
        segment_id=segment_b.id,
        tokenizer=TOKENIZER,
        orthography_profile=PROFILE,
        tokens=[TokenInput(0, "kanu", 0, 4, "kanu")],
    )[0]

    form_id = first.form_id
    assert form_id is not None
    assert second.form_id == form_id
    form_edges = ctx.repo.list_lineage_edges(form_id, "out")
    assert {e.to_id for e in form_edges} == {segment_a.id, segment_b.id}
    # The creating run keeps its output; the reusing run also lists the reused Form as output.
    assert (form_id, RunIoRole.OUTPUT) in set(ctx.repo.list_run_io(run_a))
    assert (form_id, RunIoRole.OUTPUT) in set(ctx.repo.list_run_io(run_b))
    assert form_id in {entry.object_id for entry in impact_of(ctx.repo, source_a)}
    assert form_id in {entry.object_id for entry in impact_of(ctx.repo, source_b)}


def test_unit_of_work_rolls_back_all_objects_on_late_failure(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _register(ctx, tmp_path, "uow-src")
    sobj = registered.objects[0]
    run_id = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    recorder = _recorder(ctx)
    before = state_counts(ctx)

    with pytest.raises(SchemaViolation), recorder.unit_of_work():
        recorder.record_segments(
            run_id=run_id,
            source_object_id=sobj.id,
            segments=[SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="alpha")],
        )
        # The second call raises: duplicate ordinals. The first call's writes must roll back.
        recorder.record_segments(
            run_id=run_id,
            source_object_id=sobj.id,
            segments=[
                SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="beta"),
                SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="gamma"),
            ],
        )

    assert state_counts(ctx) == before
    assert ctx.repo.list_run_io(run_id) == []
    assert ctx.repo.list_segments(sobj.id) == []


def test_unit_of_work_commits_all_objects_on_success(ctx: AppContext, tmp_path: Path) -> None:
    registered = _register(ctx, tmp_path, "uow-commit")
    sobj = registered.objects[0]
    run_id = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    recorder = _recorder(ctx)

    with recorder.unit_of_work():
        first = recorder.record_segments(
            run_id=run_id,
            source_object_id=sobj.id,
            segments=[SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="alpha")],
        )
        second = recorder.record_segments(
            run_id=run_id,
            source_object_id=sobj.id,
            segments=[SegmentInput(ordinal=1, language=LANGUAGE, locator={}, raw_text="beta")],
        )

    assert len(first) == 1
    assert len(second) == 1
    assert [s.ordinal for s in ctx.repo.list_segments(sobj.id)] == [0, 1]


def test_unit_of_work_nesting_raises(ctx: AppContext, tmp_path: Path) -> None:
    recorder = _recorder(ctx)

    with recorder.unit_of_work(), pytest.raises(RuntimeError), recorder.unit_of_work():
        pass


def test_record_normalized_segments_copies_raw_text_exactly(
    ctx: AppContext, tmp_path: Path
) -> None:
    source_id, raw = _segment(ctx, tmp_path, "norm-copy", "alpha beta")
    run_id = _run(ctx, RunStage.NORMALIZATION, [raw.id])

    normalized = _recorder(ctx).record_normalized_segments(
        run_id=run_id,
        normalization_profile=PROFILE,
        items=[
            NormalizedSegmentInput(
                raw_segment_id=raw.id, normalized_text="alpha  beta", failed=False
            )
        ],
    )

    assert len(normalized) == 1
    segment = normalized[0]
    assert segment.raw_text == "alpha beta"
    assert segment.locator == raw.locator
    assert segment.language == raw.language
    assert segment.source_id == source_id
    assert segment.source_object_id == raw.source_object_id
    assert segment.ordinal == raw.ordinal
    assert segment.normalized_text == "alpha  beta"
    assert segment.normalization_profile == PROFILE
    assert segment.status is SegmentStatus.OK
    # The raw parent is never mutated.
    assert ctx.repo.get_segment(raw.id) == raw
    edges = ctx.repo.list_lineage_edges(segment.id, "out")
    assert [(e.to_id, e.kind) for e in edges] == [(raw.id, LineageKind.NORMALIZED_FROM)]
    run_io = set(ctx.repo.list_run_io(run_id))
    assert (raw.id, RunIoRole.INPUT) in run_io
    assert (segment.id, RunIoRole.OUTPUT) in run_io


def test_record_normalized_segments_failed_has_status_and_no_text(
    ctx: AppContext, tmp_path: Path
) -> None:
    _, raw = _segment(ctx, tmp_path, "norm-failed", "alpha")
    run_id = _run(ctx, RunStage.NORMALIZATION, [raw.id])

    segment = _recorder(ctx).record_normalized_segments(
        run_id=run_id,
        normalization_profile=PROFILE,
        items=[NormalizedSegmentInput(raw_segment_id=raw.id, normalized_text=None, failed=True)],
    )[0]

    assert segment.status is SegmentStatus.NORMALIZATION_FAILED
    assert segment.normalized_text is None
    assert segment.normalization_profile is None
    assert segment.raw_text == "alpha"
    edges = ctx.repo.list_lineage_edges(segment.id, "out")
    assert [(e.to_id, e.kind) for e in edges] == [(raw.id, LineageKind.NORMALIZED_FROM)]


def test_record_normalized_segments_rejects_already_normalized_input(
    ctx: AppContext, tmp_path: Path
) -> None:
    _, normalized = _normalized_segment(ctx, tmp_path, "norm-twice", "alpha")
    run_id = _run(ctx, RunStage.NORMALIZATION, [normalized.id])
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        _recorder(ctx).record_normalized_segments(
            run_id=run_id,
            normalization_profile=PROFILE,
            items=[
                NormalizedSegmentInput(
                    raw_segment_id=normalized.id, normalized_text="alpha", failed=False
                )
            ],
        )

    assert state_counts(ctx) == before


def test_record_normalized_segments_rejects_failed_parent(ctx: AppContext, tmp_path: Path) -> None:
    _, raw = _segment(ctx, tmp_path, "norm-fparent", "alpha")
    first_run = _run(ctx, RunStage.NORMALIZATION, [raw.id])
    failed = _recorder(ctx).record_normalized_segments(
        run_id=first_run,
        normalization_profile=PROFILE,
        items=[NormalizedSegmentInput(raw_segment_id=raw.id, normalized_text=None, failed=True)],
    )[0]
    run_id = _run(ctx, RunStage.NORMALIZATION, [failed.id])
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        _recorder(ctx).record_normalized_segments(
            run_id=run_id,
            normalization_profile=PROFILE,
            items=[
                NormalizedSegmentInput(
                    raw_segment_id=failed.id, normalized_text="alpha", failed=False
                )
            ],
        )

    assert state_counts(ctx) == before


def test_record_normalized_segments_rejects_non_normalization_run(
    ctx: AppContext, tmp_path: Path
) -> None:
    _, raw = _segment(ctx, tmp_path, "norm-wrongrun", "alpha")
    run_id = _run(ctx, RunStage.EXTRACTION, [raw.id])
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        _recorder(ctx).record_normalized_segments(
            run_id=run_id,
            normalization_profile=PROFILE,
            items=[
                NormalizedSegmentInput(raw_segment_id=raw.id, normalized_text="alpha", failed=False)
            ],
        )

    assert state_counts(ctx) == before


def test_record_normalized_segments_denied_source_writes_nothing(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _register(ctx, tmp_path, "norm-denied", deny=["normalize"])
    sobj = registered.objects[0]
    extraction = _run(ctx, RunStage.EXTRACTION, [sobj.id])
    raw = _recorder(ctx).record_segments(
        run_id=extraction,
        source_object_id=sobj.id,
        segments=[SegmentInput(ordinal=0, language=LANGUAGE, locator={}, raw_text="alpha")],
    )[0]
    run_id = _run(ctx, RunStage.NORMALIZATION, [raw.id])
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        _recorder(ctx).record_normalized_segments(
            run_id=run_id,
            normalization_profile=PROFILE,
            items=[
                NormalizedSegmentInput(raw_segment_id=raw.id, normalized_text="alpha", failed=False)
            ],
        )

    assert state_counts(ctx) == before
    assert ctx.repo.list_run_io(run_id) == []


def test_record_tokens_rejects_raw_segment(ctx: AppContext, tmp_path: Path) -> None:
    # M2 strict entry point: a raw (un-normalized) segment is not tokenizable.
    _, raw = _segment(ctx, tmp_path, "tok-raw", "alpha")
    run_id = _run(ctx, RunStage.TOKENIZATION, [raw.id])
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        _recorder(ctx).record_normalized_tokens(
            run_id=run_id,
            segment_id=raw.id,
            tokenizer=TOKENIZER,
            orthography_profile=PROFILE,
            tokens=[TokenInput(0, "alpha", 0, 5, None)],
        )

    assert state_counts(ctx) == before
    assert ctx.repo.list_tokens(raw.id) == []


def test_record_tokens_rejects_failed_segment(ctx: AppContext, tmp_path: Path) -> None:
    _, raw = _segment(ctx, tmp_path, "tok-failed", "alpha")
    normalization = _run(ctx, RunStage.NORMALIZATION, [raw.id])
    failed = _recorder(ctx).record_normalized_segments(
        run_id=normalization,
        normalization_profile=PROFILE,
        items=[NormalizedSegmentInput(raw_segment_id=raw.id, normalized_text=None, failed=True)],
    )[0]
    run_id = _run(ctx, RunStage.TOKENIZATION, [failed.id])
    before = state_counts(ctx)

    with pytest.raises(InvalidLineage):
        _recorder(ctx).record_tokens(
            run_id=run_id,
            segment_id=failed.id,
            tokenizer=TOKENIZER,
            orthography_profile=PROFILE,
            tokens=[TokenInput(0, "alpha", 0, 5, None)],
        )

    assert state_counts(ctx) == before


def test_record_tokens_rejects_profile_mismatch(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "profile-src", "alpha")
    run_id = _run(ctx, RunStage.TOKENIZATION, [segment.id])
    before = state_counts(ctx)

    with pytest.raises(SchemaViolation):
        _recorder(ctx).record_tokens(
            run_id=run_id,
            segment_id=segment.id,
            tokenizer=TOKENIZER,
            orthography_profile="other-orth@1",
            tokens=[TokenInput(0, "alpha", 0, 5, None)],
        )

    assert state_counts(ctx) == before


def test_record_tokens_checks_normalized_span(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "norm-span", "alpha beta")
    run_id = _run(ctx, RunStage.TOKENIZATION, [segment.id])
    before = state_counts(ctx)

    with pytest.raises(SchemaViolation):
        _recorder(ctx).record_tokens(
            run_id=run_id,
            segment_id=segment.id,
            tokenizer=TOKENIZER,
            orthography_profile=PROFILE,
            tokens=[
                TokenInput(0, "alpha", 0, 5, None, "alpha", 0, 5),
                # normalized_surface "beta" does not match normalized_text[0:5] == "alpha".
                TokenInput(1, "beta", 6, 10, None, "beta", 0, 5),
            ],
        )

    assert state_counts(ctx) == before
    assert ctx.repo.list_run_io(run_id) == []
    assert ctx.repo.list_tokens(segment.id) == []


def test_record_tokens_rejects_half_specified_normalized_span(
    ctx: AppContext, tmp_path: Path
) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "norm-half", "alpha")

    with pytest.raises(SchemaViolation):
        _tokenize_normalized(
            ctx,
            segment,
            [TokenInput(0, "alpha", 0, 5, None, "alpha", 0, None)],
        )

    assert ctx.repo.list_tokens(segment.id) == []


def test_record_tokens_checks_form_text_matches_normalized_surface(
    ctx: AppContext, tmp_path: Path
) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "norm-form", "alpha")
    run_id = _run(ctx, RunStage.TOKENIZATION, [segment.id])
    before = state_counts(ctx)

    with pytest.raises(SchemaViolation):
        _recorder(ctx).record_normalized_tokens(
            run_id=run_id,
            segment_id=segment.id,
            tokenizer=TOKENIZER,
            orthography_profile=PROFILE,
            tokens=[TokenInput(0, "alpha", 0, 5, "different", "alpha", 0, 5)],
        )

    assert state_counts(ctx) == before


def test_record_normalized_tokens_records_normalized_spans(ctx: AppContext, tmp_path: Path) -> None:
    _, segment = _normalized_segment(ctx, tmp_path, "norm-tok", "alpha beta")
    assert segment.normalized_text is not None

    tokens = _tokenize_normalized(
        ctx,
        segment,
        [
            TokenInput(0, "alpha", 0, 5, "alpha", "alpha", 0, 5),
            TokenInput(1, "beta", 6, 10, "beta", "beta", 6, 10),
        ],
    )

    assert [t.normalized_surface for t in tokens] == ["alpha", "beta"]
    assert [
        t.normalized_span.slice(segment.normalized_text) for t in tokens if t.normalized_span
    ] == [
        "alpha",
        "beta",
    ]
    assert all(t.form_id is not None for t in tokens)
