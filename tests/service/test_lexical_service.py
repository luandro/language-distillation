"""Stage 6 lexical induction service contracts (WP4.7).

`LexicalService` turns one succeeded Stage 5 token-alignment run or wordlist extraction
run into persisted candidate `Lexeme`/`Sense` hypotheses inside one atomic Stage 6 run.
These tests cover both input modes, idempotent rerun reuse, governance denial and
ineligible inputs, on both the memory and PostgreSQL backends (run sequentially).
"""

import itertools
import threading
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from langpipe.alignment.base import (
    AlignmentConfig,
    AlignmentSide,
    BackendMetadata,
    TokenBatchOutput,
    TokenLinks,
)
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    ArtifactKind,
    AuditEventType,
    EntityType,
    LifecycleStatus,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    SourceType,
)
from langpipe.domain.errors import AmbiguousInput, NotFound, PolicyDenied, SchemaViolation
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.observation import Form
from langpipe.domain.models.run import AuditEvent
from langpipe.extraction.service import extract_source
from langpipe.ingest.wordlist import WordlistExtractor
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.lexicon.registry import UnsupportedMethod
from langpipe.lexicon.scoring import DEFAULT_POLICY, POLICY_VERSION, LexicalScorePolicy
from langpipe.lexicon.service import REPORT_SCHEMA, LexicalInductionResult, LexicalService
from langpipe.normalization.service import normalize_extraction
from langpipe.storage.db.repository import PostgresRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import manifest_data, write_manifest, write_origin_file
from tests.service.test_token_alignment_service import _Links, _ready

TSV = "text/tab-separated-values"

WORDLIST_BYTES = (
    "qaa\tpor\tnote\n"
    "kanu\thomem\n"
    "mabi\tcanoa; tronco\ttwo candidate senses\n"
    "rumi\tpajé\tdomain-specific (ritual/traditional)\n"
).encode()


def _token_aligned(ctx: AppContext, tmp_path: Path) -> str:
    """A succeeded Stage 5 token-alignment run over one aligned segment pair."""
    a, b, segment = _ready(ctx, tmp_path)
    out = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    return out.run.id


def _wordlist_run(ctx: AppContext, tmp_path: Path, key: str):
    relative = f"{key}/wordlist.tsv"
    write_origin_file(tmp_path, relative, WORDLIST_BYTES)
    data = manifest_data(key=key, objects=[{"path": relative, "media_type": TSV}])
    data["source_type"] = SourceType.WORDLIST.value
    data["languages"] = ["qaa", "por"]
    registered = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    return WordlistExtractor(ctx).extract(registered.source.key)


def _plain_extraction_run(ctx: AppContext, tmp_path: Path, key: str) -> str:
    """A succeeded Stage 3 extraction run that is not a wordlist extraction."""
    relative = f"{key}/text.tsv"
    write_origin_file(tmp_path, relative, b"ref\tqaa\nT.1\tkanu mabi\n")
    data = manifest_data(key=key, objects=[{"path": relative, "media_type": TSV}])
    data["languages"] = ["qaa"]
    registered = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))
    ingest_source(ctx, registered.source.id)
    return extract_source(ctx, registered.source.id).run.id


def _outputs(ctx: AppContext, run_id: str, entity_type: EntityType) -> list[str]:
    return [
        object_id
        for object_id, role in ctx.repo.list_run_io(run_id)
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is entity_type
    ]


def _inputs(ctx: AppContext, run_id: str) -> set[str]:
    return {
        object_id for object_id, role in ctx.repo.list_run_io(run_id) if role is RunIoRole.INPUT
    }


def _run_sources(ctx: AppContext, run_id: str) -> list[str]:
    return sorted(
        object_id
        for object_id in _inputs(ctx, run_id)
        if ctx.repo.entity_type_of(object_id) is EntityType.SOURCE
    )


class _EmptyLinks(_Links):
    name = "fixture-empty"

    def align(self, groups, config):
        return TokenBatchOutput(
            tuple(TokenLinks(g.alignment_id, (), ()) for g in groups),
            BackendMetadata("0.1.0", None, {}, False),
        )


def _empty_aligned(ctx: AppContext, tmp_path: Path) -> str:
    """A succeeded Stage 5 token-alignment run that produced zero edges."""
    a, b, segment = _ready(ctx, tmp_path)
    out = TokenAlignmentService(ctx, aligners=VersionedRegistry((_EmptyLinks(),))).align(
        segment.run.id,
        source_tokenization_run_id=a.tokenization_run_id,
        target_tokenization_run_id=b.tokenization_run_id,
        method="fixture-empty@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    return out.run.id


def _lexical_baseline(ctx: AppContext) -> dict[EntityType, int]:
    return {entity: ctx.repo.count(entity) for entity in EntityType}


def _deny_events(ctx: AppContext) -> list[AuditEvent]:
    return [
        event
        for event in ctx.repo.list_audit_events()
        if event.event_type is AuditEventType.POLICY_DENIED
    ]


def _context_over(engine: Engine, tmp_path: Path) -> AppContext:
    """A second application context over the shared PostgreSQL state and stores."""
    ticks = itertools.count()
    return AppContext(
        repo=PostgresRepository(engine),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=next(ticks)),
        new_id=new_id,
        actor="test-actor",
        code_revision="test-rev",
    )


def test_induction_when_both_sides_share_normalization_run(ctx: AppContext, tmp_path: Path) -> None:
    relative = "shared/shared.tsv"
    write_origin_file(tmp_path, relative, b"ref\tqaa\tpor\nT.1\tkanu mabi\tO homem\n")
    data = manifest_data(key="shared-bilingual", objects=[{"path": relative, "media_type": TSV}])
    data["languages"] = ["qaa", "por"]
    registered = register_source(ctx, write_manifest(tmp_path, data, name="shared-bilingual.yaml"))
    ingest_source(ctx, registered.source.id)
    extraction = extract_source(ctx, registered.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    source_side = AlignmentSide(registered.source.id, "qaa", normalization.run.id)
    target_side = AlignmentSide(registered.source.id, "por", normalization.run.id)
    assert source_side.normalization_run_id == target_side.normalization_run_id
    segment = SegmentAlignmentService(ctx).align(
        source_side, target_side, config=AlignmentConfig(namespace="refs")
    )
    aligned = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment.run.id,
        source_tokenization_run_id=tokenization.run.id,
        target_tokenization_run_id=tokenization.run.id,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    result = LexicalService(ctx).induce_lexicon(
        aligned.run.id, target_language="qaa", contact_language="por"
    )
    lexeme_ids = _outputs(ctx, result.run.id, EntityType.LEXEME)
    sense_ids = _outputs(ctx, result.run.id, EntityType.SENSE)
    assert lexeme_ids and sense_ids
    assert all(ctx.repo.get_lexeme(item).language == "qaa" for item in lexeme_ids)
    assert any(ctx.repo.get_sense(item).glosses.get("por") for item in sense_ids)


def test_induction_from_token_alignment(ctx: AppContext, tmp_path: Path) -> None:
    alignment_run = _token_aligned(ctx, tmp_path)
    result = LexicalService(ctx).induce_lexicon(alignment_run)

    assert result.reused is False
    assert result.run.stage is RunStage.LEXICAL_INDUCTION
    assert result.run.status is RunStatus.SUCCEEDED
    assert result.lexemes == 1
    assert result.senses == 1
    assert result.evidence_items == 2
    assert result.form_links == 1
    # Machine confidence never validates (AGENTS.md invariant 3): candidate at most.
    assert set(result.status_counts) <= {"candidate", "supported"}
    assert "validated" not in result.status_counts

    lexeme_ids = _outputs(ctx, result.run.id, EntityType.LEXEME)
    assert len(lexeme_ids) == result.lexemes
    lexeme = ctx.repo.get_lexeme(lexeme_ids[0])
    assert lexeme.language == "qaa"
    assert lexeme.status is LifecycleStatus.CANDIDATE

    sense_ids = _outputs(ctx, result.run.id, EntityType.SENSE)
    sense = ctx.repo.get_sense(sense_ids[0])
    assert sense.lexeme_id == lexeme.id
    # The contact form is a meaning hypothesis, never a target-language form.
    assert sense.glosses == {"por": ["O"]}

    evidence_ids = _outputs(ctx, result.run.id, EntityType.EVIDENCE_ITEM)
    targets = {ctx.repo.get_evidence(item).target_id for item in evidence_ids}
    assert targets == {lexeme.id}
    lineage_targets = {edge.to_id for edge in ctx.repo.list_lineage_edges(lexeme.id, "out")}
    assert result.run.id in lineage_targets
    assert set(evidence_ids) <= lineage_targets

    assert result.report.kind is ArtifactKind.OTHER
    assert result.report.schema_name == REPORT_SCHEMA
    assert result.report.schema_version == 1

    # The input run is pinned as a run input.
    assert alignment_run in _inputs(ctx, result.run.id)


def test_induction_from_wordlist_run(ctx: AppContext, tmp_path: Path) -> None:
    extraction = _wordlist_run(ctx, tmp_path, "wl-svc-a")
    result = LexicalService(ctx).induce_lexicon(extraction.run.id, method="wordlist_tabular@0.1.0")

    assert result.reused is False
    assert result.run.stage is RunStage.LEXICAL_INDUCTION
    assert result.run.status is RunStatus.SUCCEEDED
    # kanu, mabi, rumi: one lexeme per headword however many senses it carries.
    assert result.lexemes == 3
    assert result.senses == 4
    assert result.evidence_items == 4
    assert set(result.status_counts) <= {"candidate", "supported"}

    lexeme_ids = _outputs(ctx, result.run.id, EntityType.LEXEME)
    headwords: dict[str, str] = {}
    for lexeme_id in lexeme_ids:
        evidence = ctx.repo.list_evidence_for_target(lexeme_id)
        assert evidence
        headwords[lexeme_id] = str(evidence[0].claim["headword"])
    assert sorted(headwords.values()) == ["kanu", "mabi", "rumi"]
    by_headword = {headword: lexeme_id for lexeme_id, headword in headwords.items()}

    # Phenomenon 2 preserved: one lexeme, two meaning hypotheses.
    mabi_senses = ctx.repo.list_senses_for_lexeme(by_headword["mabi"])
    assert sorted(gloss for sense in mabi_senses for gloss in sense.glosses["por"]) == [
        "canoa",
        "tronco",
    ]
    # Phenomenon 9 preserved: the row's register note is a domain tag on the sense.
    rumi_senses = ctx.repo.list_senses_for_lexeme(by_headword["rumi"])
    assert rumi_senses[0].domain == "ritual/traditional"

    assert extraction.run.id in _inputs(ctx, result.run.id)


def test_idempotent_rerun_reuses_run(ctx: AppContext, tmp_path: Path) -> None:
    alignment_run = _token_aligned(ctx, tmp_path)
    service = LexicalService(ctx)
    first = service.induce_lexicon(alignment_run)

    before_runs = ctx.repo.count_runs()
    before = {entity: ctx.repo.count(entity) for entity in EntityType}
    before_edges = ctx.repo.count_lineage_edges()

    second = service.induce_lexicon(alignment_run)

    assert second.reused is True
    assert second.run.id == first.run.id
    assert second.lexemes == first.lexemes
    assert second.senses == first.senses
    assert second.evidence_items == first.evidence_items
    assert ctx.repo.count_runs() == before_runs
    assert ctx.repo.count_lineage_edges() == before_edges
    for entity, count in before.items():
        assert ctx.repo.count(entity) == count


def test_revoked_source_denied(ctx: AppContext, tmp_path: Path) -> None:
    alignment_run = _token_aligned(ctx, tmp_path)
    source_id = next(
        object_id
        for object_id, _role in ctx.repo.list_run_io(alignment_run)
        if ctx.repo.entity_type_of(object_id) is EntityType.SOURCE
    )
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())

    with pytest.raises(PolicyDenied) as excinfo:
        LexicalService(ctx).induce_lexicon(alignment_run)

    assert excinfo.value.source_id == source_id
    assert excinfo.value.operation is Operation.DISTILL_LEXICON
    assert excinfo.value.decision is PolicyDecision.DENY
    denials = [
        event
        for event in ctx.repo.list_audit_events()
        if event.event_type is AuditEventType.POLICY_DENIED
    ]
    assert len(denials) == 1
    assert denials[0].subject_id == source_id
    assert ctx.repo.count(EntityType.LEXEME) == 0


def test_ineligible_input_runs(ctx: AppContext, tmp_path: Path) -> None:
    a, _b, segment = _ready(ctx, tmp_path)
    alignment_run = _token_aligned(ctx, tmp_path)
    service = LexicalService(ctx)

    with pytest.raises(NotFound):
        service.induce_lexicon("run_00000000000000000000000000")

    recorder = RunRecorder(ctx)
    running = recorder.start(RunStage.TOKEN_ALIGNMENT, "langpipe.test", {}, [alignment_run])
    with pytest.raises(AmbiguousInput):
        service.induce_lexicon(running.id)
    failed = recorder.fail(running.id, RuntimeError("test failure"))
    with pytest.raises(AmbiguousInput):
        service.induce_lexicon(failed.id)

    # A succeeded run of any other stage is ineligible.
    with pytest.raises(SchemaViolation):
        service.induce_lexicon(a.tokenization_run_id)
    # Right stage, wrong tool: a plain extraction run is not a wordlist extraction.
    plain_extraction = _plain_extraction_run(ctx, tmp_path, "plain-svc")
    with pytest.raises(SchemaViolation):
        service.induce_lexicon(plain_extraction)


def test_unknown_method_is_refused(ctx: AppContext, tmp_path: Path) -> None:
    alignment_run = _token_aligned(ctx, tmp_path)
    with pytest.raises(UnsupportedMethod):
        LexicalService(ctx).induce_lexicon(alignment_run, method="wordlist_tabular@9.9.9")


def test_explicit_language_conflict_is_refused(ctx: AppContext, tmp_path: Path) -> None:
    extraction = _wordlist_run(ctx, tmp_path, "wl-svc-c")
    with pytest.raises(SchemaViolation):
        LexicalService(ctx).induce_lexicon(
            extraction.run.id, method="wordlist_tabular@0.1.0", target_language="mzr"
        )


def test_scoring_policy_is_pinned_in_run_identity(ctx: AppContext, tmp_path: Path) -> None:
    """The effective policy is part of run identity: equal settings reuse, changed settings
    create a different run with its own scores and statuses (Gate 23 fix 1; ADR-0008)."""
    extraction = _wordlist_run(ctx, tmp_path, "wl-policy")
    service = LexicalService(ctx)
    runs_before = ctx.repo.count_runs()

    default = service.induce_lexicon(extraction.run.id, method="wordlist_tabular@0.1.0")
    # The resolved policy — defaults included — is persisted in the canonical run config.
    assert default.run.config["policy_version"] == POLICY_VERSION
    assert default.run.config["policy"] == asdict(DEFAULT_POLICY)

    # An explicit policy equal to the resolved default is the same run: reuse.
    explicit_default = service.induce_lexicon(
        extraction.run.id, method="wordlist_tabular@0.1.0", policy=LexicalScorePolicy()
    )
    assert explicit_default.reused is True
    assert explicit_default.run.id == default.run.id

    # Changed settings must never silently reuse the previous results.
    lenient = LexicalScorePolicy(promotion_threshold=0.0, min_independent_sources=1)
    changed = service.induce_lexicon(
        extraction.run.id, method="wordlist_tabular@0.1.0", policy=lenient
    )
    assert changed.reused is False
    assert changed.run.id != default.run.id
    assert changed.run.config["policy"] == asdict(lenient)
    assert default.status_counts == {"candidate": 7}
    assert changed.status_counts == {"supported": 7}

    # The changed run is itself the reusable one under its own settings.
    again = service.induce_lexicon(
        extraction.run.id, method="wordlist_tabular@0.1.0", policy=lenient
    )
    assert again.reused is True
    assert again.run.id == changed.run.id
    # Exactly the two distinct inductions exist; the equal-policy reruns reused them.
    assert ctx.repo.count_runs() == runs_before + 2


def test_method_input_mismatch_refused_without_writes(ctx: AppContext, tmp_path: Path) -> None:
    """A method whose family does not match the pinned evidence is refused before any run
    row, preflight or reuse decision (Gate 23 fix 2)."""
    alignment_run = _token_aligned(ctx, tmp_path)
    wordlist = _wordlist_run(ctx, tmp_path, "wl-mismatch")
    service = LexicalService(ctx)
    runs_before = ctx.repo.count_runs()
    baseline = _lexical_baseline(ctx)

    # Alignment evidence requires the alignment inducer; the wordlist inducer is refused.
    with pytest.raises(SchemaViolation):
        service.induce_lexicon(alignment_run, method="wordlist_tabular@0.1.0")
    # Wordlist evidence requires the wordlist inducer: the alignment default must not
    # silently succeed with zero results.
    with pytest.raises(SchemaViolation):
        service.induce_lexicon(wordlist.run.id)

    assert ctx.repo.count_runs() == runs_before
    for entity, count in baseline.items():
        assert ctx.repo.count(entity) == count


def test_empty_alignment_run_succeeds_with_source_lineage(ctx: AppContext, tmp_path: Path) -> None:
    """A genuinely empty governed alignment induces a succeeded zero-total run whose report
    still carries complete source lineage, and is reused like any other (Gate 23 fix 3)."""
    alignment_run = _empty_aligned(ctx, tmp_path)
    service = LexicalService(ctx)
    result = service.induce_lexicon(alignment_run)

    assert result.reused is False
    assert result.run.status is RunStatus.SUCCEEDED
    assert result.run.config["policy_version"] == POLICY_VERSION
    assert (
        result.lexemes,
        result.senses,
        result.concepts,
        result.form_links,
        result.evidence_items,
    ) == (0, 0, 0, 0, 0)
    assert result.status_counts == {}
    assert result.report.schema_name == REPORT_SCHEMA

    # The report descends from exactly the governed sources of both pinned sides even
    # though no alignment edge named a contributing object.
    sources = set(_run_sources(ctx, alignment_run))
    assert len(sources) == 2
    report_ancestors = {
        object_id
        for object_id, _depth in ctx.repo.ancestors(result.report.id)
        if ctx.repo.entity_type_of(object_id) is EntityType.SOURCE
    }
    assert report_ancestors == sources

    second = service.induce_lexicon(alignment_run)
    assert second.reused is True
    assert second.run.id == result.run.id
    assert ctx.repo.count(EntityType.LEXEME) == 0


def test_empty_alignment_run_blocks_on_revoked_side_source(ctx: AppContext, tmp_path: Path) -> None:
    """A denied/revoked side source blocks the first execution of an empty alignment run."""
    alignment_run = _empty_aligned(ctx, tmp_path)
    source_id = _run_sources(ctx, alignment_run)[0]
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())

    runs_before = ctx.repo.count_runs()
    with pytest.raises(PolicyDenied) as excinfo:
        LexicalService(ctx).induce_lexicon(alignment_run)

    assert excinfo.value.source_id == source_id
    assert excinfo.value.decision is PolicyDecision.DENY
    assert len(_deny_events(ctx)) == 1
    # The preflight refused: no run row was ever created.
    assert ctx.repo.count_runs() == runs_before
    assert ctx.repo.count(EntityType.LEXEME) == 0


def test_empty_alignment_run_blocks_reuse_after_revocation(ctx: AppContext, tmp_path: Path) -> None:
    """Revocation after a succeeded empty run blocks its reuse under the same locks."""
    alignment_run = _empty_aligned(ctx, tmp_path)
    service = LexicalService(ctx)
    service.induce_lexicon(alignment_run)
    runs_after_first = ctx.repo.count_runs()
    denials_before = len(_deny_events(ctx))

    source_id = _run_sources(ctx, alignment_run)[1]
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())

    baseline = _lexical_baseline(ctx)
    with pytest.raises(PolicyDenied) as excinfo:
        service.induce_lexicon(alignment_run)

    assert excinfo.value.source_id == source_id
    assert len(_deny_events(ctx)) == denials_before + 1
    # The reuse refusal wrote nothing: no new run, no new entities.
    assert ctx.repo.count_runs() == runs_after_first
    assert ctx.repo.count(EntityType.LEXEME) == 0
    assert _lexical_baseline(ctx) == baseline


def test_locked_recheck_denies_revoked_between_preflight_and_lock(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source revoked after the preflight read it is still caught by the recheck under
    the sorted locks, and the failed run is redacted."""
    alignment_run = _token_aligned(ctx, tmp_path)
    source_id = _run_sources(ctx, alignment_run)[0]
    service = LexicalService(ctx)
    repo = ctx.repo
    real_lock, real_get_source = repo.lock_sources, repo.get_source
    real_add_run = repo.add_run
    started: list[str] = []
    locked = False

    def lock_sources(source_ids, **kwargs):
        nonlocal locked
        locked = True
        return real_lock(source_ids, **kwargs)

    def get_source(fetched_id: str):
        source = real_get_source(fetched_id)
        if locked and fetched_id == source_id:
            # The row was revoked after the preflight read it.
            return source.model_copy(update={"status": SourceStatus.REVOKED})
        return source

    def add_run(run):
        started.append(run.id)
        return real_add_run(run)

    monkeypatch.setattr(repo, "lock_sources", lock_sources)
    monkeypatch.setattr(repo, "get_source", get_source)
    monkeypatch.setattr(repo, "add_run", add_run)
    runs_before = ctx.repo.count_runs()
    baseline = _lexical_baseline(ctx)

    with pytest.raises(PolicyDenied) as excinfo:
        service.induce_lexicon(alignment_run)

    assert excinfo.value.source_id == source_id
    assert len(_deny_events(ctx)) == 1
    # The preflight passed, so a run was started; the locked recheck failed it closed.
    assert ctx.repo.count_runs() == runs_before + 1
    failed_run = repo.get_run(started[0])
    assert failed_run.status is RunStatus.FAILED
    assert failed_run.error_type == "PolicyDenied"
    assert failed_run.error_message is None
    # Only the redacted run row was written; nothing semantic survived.
    after = _lexical_baseline(ctx)
    after[EntityType.PROCESSING_RUN] = baseline[EntityType.PROCESSING_RUN]
    assert after == baseline


def test_persistence_failure_rolls_back_and_redacts(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure mid-persist leaves no lexical, evidence, lineage or report metadata and
    records only the exception type on the FAILED run; the failed run is never reused."""
    alignment_run = _token_aligned(ctx, tmp_path)
    service = LexicalService(ctx)
    repo = ctx.repo
    real_add_run = repo.add_run
    started: list[str] = []

    def add_run(run):
        started.append(run.id)
        return real_add_run(run)

    def add_evidence(item):
        raise RuntimeError("injected persistence failure")

    monkeypatch.setattr(repo, "add_run", add_run)
    monkeypatch.setattr(repo, "add_evidence", add_evidence)
    runs_before = ctx.repo.count_runs()
    baseline = _lexical_baseline(ctx)
    edges_before = ctx.repo.count_lineage_edges()

    with pytest.raises(RuntimeError):
        service.induce_lexicon(alignment_run)
    monkeypatch.undo()

    failed_run = repo.get_run(started[0])
    assert failed_run.status is RunStatus.FAILED
    assert failed_run.error_type == "RuntimeError"
    assert failed_run.error_message is None
    # Nothing semantic survived: identical entity counts apart from the redacted run
    # row itself, no lineage, no run I/O.
    after = _lexical_baseline(ctx)
    after[EntityType.PROCESSING_RUN] = baseline[EntityType.PROCESSING_RUN]
    assert after == baseline
    assert ctx.repo.count_runs() == runs_before + 1
    assert ctx.repo.count_lineage_edges() == edges_before
    assert not _inputs(ctx, failed_run.id)
    assert not _outputs(ctx, failed_run.id, EntityType.LEXEME)

    # The failed run is not reusable: a retry produces a fresh succeeded run.
    second = service.induce_lexicon(alignment_run)
    assert second.reused is False
    assert second.run.id != failed_run.id
    assert second.run.status is RunStatus.SUCCEEDED


def test_form_reconstruction_mismatch_fails_closed(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolved form whose persisted id disagrees with the token's pinned form id fails
    closed and rolls back; another form's id is never silently accepted."""
    alignment_run = _token_aligned(ctx, tmp_path)
    service = LexicalService(ctx)
    repo = ctx.repo
    with repo.transaction():
        decoy = repo.get_or_create_form(
            Form(
                id=ctx.new_id(IdPrefix.FORM),
                language="zzz",
                orthography_profile="decoy-profile@0.1.0",
                text="decoy",
                run_id=alignment_run,
                created_at=ctx.clock(),
            )
        )
    real_add_run = repo.add_run
    started: list[str] = []

    def add_run(run):
        started.append(run.id)
        return real_add_run(run)

    def get_or_create_form(form):
        return decoy  # every reconstruction probe resolves to a foreign form id

    monkeypatch.setattr(repo, "add_run", add_run)
    monkeypatch.setattr(repo, "get_or_create_form", get_or_create_form)
    runs_before = ctx.repo.count_runs()
    baseline = _lexical_baseline(ctx)
    edges_before = ctx.repo.count_lineage_edges()

    with pytest.raises(SchemaViolation):
        service.induce_lexicon(alignment_run)
    monkeypatch.undo()

    failed_run = repo.get_run(started[0])
    assert failed_run.status is RunStatus.FAILED
    assert failed_run.error_type == "SchemaViolation"
    assert failed_run.error_message is None
    after = _lexical_baseline(ctx)
    after[EntityType.PROCESSING_RUN] = baseline[EntityType.PROCESSING_RUN]
    assert after == baseline
    assert ctx.repo.count_runs() == runs_before + 1
    assert ctx.repo.count_lineage_edges() == edges_before


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
def test_identical_concurrent_requests_reuse_one_run(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    """Two identical requests racing on the same request key produce exactly one run and
    one induction's writes.

    The in-memory backend is single-caller by construction (its request lock refuses a
    caller arriving mid-transaction), so the race runs against PostgreSQL: two contexts
    over one database contend on the same advisory request lock, and the succeeded-run
    unique index backs the serialization.
    """
    contexts = [_context_over(migrated_engine, tmp_path) for _ in range(2)]
    alignment_run = _token_aligned(contexts[0], tmp_path)
    repo = contexts[0].repo
    runs_before = repo.count_runs()
    results: list[LexicalInductionResult] = []
    start = threading.Barrier(2)

    def worker(context: AppContext) -> None:
        start.wait()
        results.append(LexicalService(context).induce_lexicon(alignment_run))

    threads = [threading.Thread(target=worker, args=(context,)) for context in contexts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60.0)
    assert not any(thread.is_alive() for thread in threads)

    assert len(results) == 2
    first, second = results
    assert first.run.id == second.run.id
    assert sorted(result.reused for result in results) == [False, True]
    assert repo.count_runs() == runs_before + 1
    # Exactly one induction's writes: no duplicates from the racing calls.
    assert repo.count(EntityType.LEXEME) == first.lexemes
    assert repo.count(EntityType.SENSE) == first.senses
    assert repo.count(EntityType.EVIDENCE_ITEM) == first.evidence_items
