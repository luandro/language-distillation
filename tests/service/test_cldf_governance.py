"""CLDF interchange governance contracts (WP4.10, WP4.10-CLDF-SPEC §6.2).

Import governance follows the same sequence as the wordlist path (ADR-0007); the
exporter is governed by `lineage_eligibility(..., REDISTRIBUTE_DERIVED)` over every
contributing entity, fails closed on an empty selection (D8), and never touches raw
or segment data (the raw-redistribution rule, D9). Runs against the memory and PostgreSQL
backends.

The canary scenario (§6.2.11) proves the raw-redistribution firewall structurally: a
`distill_only` source's sentences never appear in any exported file, and the export
writes no ExampleTable at all.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pycldf
import pytest

from langpipe.alignment.base import AlignmentConfig, AlignmentSide
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.cldf.exporter import CLDFExporter
from langpipe.cldf.importer import CLDFImporter
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    AuditEventType,
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    LifecycleStatus,
    LineageKind,
    Operation,
    PolicyDecision,
    ReviewDecisionKind,
    ReviewTaskType,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    SourceType,
)
from langpipe.domain.errors import (
    NoEligibleRecords,
    PolicyDenied,
    SchemaViolation,
    UnsupportedSource,
)
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.lexical import Lexeme, Sense
from langpipe.extraction.service import extract_source
from langpipe.governance.lineage_policy import lineage_eligibility
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import register_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.lexicon.service import LexicalService
from langpipe.lineage import revocation_impact
from langpipe.normalization.service import normalize_extraction
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.recalc import RecalcService
from langpipe.review.service import ReviewService
from langpipe.text.registry import VersionedRegistry
from langpipe.tokenization.service import tokenize_normalization
from tests.service.manifests import (
    record_finished_runs,
    state_counts,
    write_manifest,
    write_origin_file,
)
from tests.service.test_token_alignment_service import _Links
from tests.unit.test_cldf_interchange import _register_dataset, _validate_all

REVIEWER = "linguist"
ROLE = "community_linguist"
LANGUAGE = "qaa"
CANARY_SENTENCE = "wera kanu mabi"
PIVOT_SENTENCE = "o homem vê"
EXPORT_REPORT_SCHEMA = "cldf-export-report"
CLDF_EXPORT_TOOL = "langpipe.cldf-export"


# --- world builders ---------------------------------------------------------------------


def _revoke(ctx: AppContext, source_id: str) -> None:
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())


def _import_world(ctx: AppContext, tmp_path: Path, key: str, **kwargs: object) -> tuple[str, str]:
    """Register a wordlist CLDF source, import it, validate every lexeme and sense."""
    source_key = _register_dataset(ctx, tmp_path, key, **kwargs)
    _, induction = CLDFImporter(ctx).import_dataset(source_key)
    assert induction.run.status is RunStatus.SUCCEEDED
    _validate_all(ctx, induction.run.id)
    return source_key, induction.run.id


def _two_lexeme_world(
    ctx: AppContext, tmp_path: Path, key: str, **kwargs: object
) -> tuple[str, str, str, str]:
    """Import and validate the `maní` lexeme only; `kupa` and its senses stay candidate."""
    source_key = _register_dataset(ctx, tmp_path, key, **kwargs)
    _, induction = CLDFImporter(ctx).import_dataset(source_key)
    run_id = induction.run.id
    manii = _lexeme_by_headword(ctx, run_id, "maní")
    assert _review_one(ctx, manii, ReviewTaskType.LEMMA) is LifecycleStatus.VALIDATED
    for sense_id in _senses_of(ctx, manii):
        assert _review_one(ctx, sense_id, ReviewTaskType.LEXICAL_SENSE) is (
            LifecycleStatus.VALIDATED
        )
    RecalcService(ctx).recalculate(all_stale=True)
    kupa = _lexeme_by_headword(ctx, run_id, "kupa")
    return source_key, run_id, manii, kupa


def _review_one(ctx: AppContext, target_id: str, task_type: ReviewTaskType) -> LifecycleStatus:
    authority = ReviewAuthorityRegistry()
    authority.register(REVIEWER, ROLE, [LANGUAGE])
    review = ReviewService(
        ctx.repo, authority, clock=ctx.clock, new_id=ctx.new_id, code_revision=ctx.code_revision
    )
    task = review.create_task(target_id, task_type=task_type, required_role=ROLE)
    result = review.record_decision(task.id, ReviewDecisionKind.ACCEPT, REVIEWER, ROLE)
    assert result.target_status is not None
    return result.target_status


def _outputs_of(ctx: AppContext, run_id: str, entity: EntityType) -> list[str]:
    return sorted(
        object_id
        for object_id, role in ctx.repo.list_run_io(run_id)
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is entity
    )


def _lexeme_by_headword(ctx: AppContext, run_id: str, headword: str) -> str:
    """The lexeme whose gloss-bearing evidence claims `headword` (fixtures are unambiguous)."""
    found: list[str] = []
    for evidence_id in _outputs_of(ctx, run_id, EntityType.EVIDENCE_ITEM):
        item = ctx.repo.get_evidence(evidence_id)
        claim = item.claim or {}
        if claim.get("gloss") is not None and claim.get("headword") == headword:
            found.append(item.target_id)
    if not found:
        raise AssertionError(f"no evidence claims {headword!r}")
    return found[0]


def _senses_of(ctx: AppContext, lexeme_id: str) -> list[str]:
    return [sense.id for sense in ctx.repo.list_senses_for_lexeme(lexeme_id)]


def _ancestor_keys(ctx: AppContext, object_id: str) -> set[str]:
    return {
        ctx.repo.get_source(ancestor_id).key
        for ancestor_id, _depth in ctx.repo.ancestors(object_id)
        if ctx.repo.entity_type_of(ancestor_id) is EntityType.SOURCE
    }


def _exported_rows(directory: Path, table: str) -> list[dict[str, object]]:
    loaded = pycldf.Dataset.from_metadata(next(directory.glob("*metadata.json")))
    return [dict(row) for row in loaded[table]]


def _exported_metadata(directory: Path) -> dict[str, object]:
    return json.loads(next(directory.glob("*metadata.json")).read_text())


def _report_of_export(ctx: AppContext, run_id: str) -> dict[str, object]:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is not RunIoRole.OUTPUT:
            continue
        if ctx.repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
            continue
        artifact = ctx.repo.get_artifact(object_id)
        if artifact.schema_name == EXPORT_REPORT_SCHEMA:
            return json.loads(ctx.artifact_store.read_bytes(artifact.sha256))
    raise AssertionError("no cldf-export-report on the export run")


def _lexemes_of_source(ctx: AppContext, key: str) -> set[str]:
    return {
        lexeme.id
        for lexeme in ctx.repo.list_lexemes_by_language(LANGUAGE)
        if key in _ancestor_keys(ctx, lexeme.id)
    }


def _lexeme_with_lemma_text(ctx: AppContext, text: str) -> str | None:
    """The lexeme whose lemma Form carries ``text``, if any (Form rows are shared)."""
    for lexeme in ctx.repo.list_lexemes_by_language(LANGUAGE):
        if lexeme.lemma_form_id is None:
            continue
        if ctx.repo.get_form(lexeme.lemma_form_id).text == text:
            return lexeme.id
    return None


def _parallel_side(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    language: str,
    text: str,
    mode: str,
    *,
    allow: tuple[str, ...] = ("redistribute_derived",),
) -> tuple[AlignmentSide, str]:
    """One full pipeline side (ingest..tokenize) whose policy allows the fixture operations."""
    relative = f"texts/{key}.tsv"
    write_origin_file(tmp_path, relative, f"ref\t{language}\nT.1\t{text}\n".encode())
    data = {
        "manifest_version": 1,
        "key": key,
        "title": f"Side {key}",
        "source_type": SourceType.PARALLEL_TEXT.value,
        "languages": [language],
        "provenance": {"acquired_from": "test"},
        "acquired_at": "2026-01-01T00:00:00+00:00",
        "policy": {
            "mode": mode,
            "access_class": "public",
            "authority": "test-authority",
            "allow": list(allow),
        },
        "objects": [{"path": relative, "media_type": "text/tab-separated-values"}],
    }
    source = register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml")).source
    ingest_source(ctx, source.id)
    extraction = extract_source(ctx, source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    return AlignmentSide(source.id, language, normalization.run.id), tokenization.run.id


@dataclass(frozen=True)
class _Canary:
    export_dir: Path
    target_source: str
    pivot_source: str


def _canary_world(ctx: AppContext, tmp_path: Path, mode: str = "distill_only") -> _Canary:
    """A `distill_only` parallel chain whose segment text carries the canary sentence."""
    target_side, target_tokens = _parallel_side(
        ctx, tmp_path, "canary-target", LANGUAGE, f"{CANARY_SENTENCE}.", mode
    )
    pivot_side, pivot_tokens = _parallel_side(
        ctx, tmp_path, "canary-pivot", "por", f"{PIVOT_SENTENCE}.", mode
    )
    segment_alignment = SegmentAlignmentService(ctx).align(
        target_side, pivot_side, config=AlignmentConfig(namespace="refs")
    )
    token_alignment = TokenAlignmentService(ctx, aligners=VersionedRegistry((_Links(),))).align(
        segment_alignment.run.id,
        source_tokenization_run_id=target_tokens,
        target_tokenization_run_id=pivot_tokens,
        method="fixture@0.1.0",
        config=AlignmentConfig(namespace="refs"),
    )
    induction = LexicalService(ctx).induce_lexicon(token_alignment.run.id)
    for lexeme_id in _outputs_of(ctx, induction.run.id, EntityType.LEXEME):
        assert _review_one(ctx, lexeme_id, ReviewTaskType.LEMMA) is LifecycleStatus.VALIDATED
    for sense_id in _outputs_of(ctx, induction.run.id, EntityType.SENSE):
        assert _review_one(ctx, sense_id, ReviewTaskType.LEXICAL_SENSE) is (
            LifecycleStatus.VALIDATED
        )
    RecalcService(ctx).recalculate(all_stale=True)
    export_dir = tmp_path / "canary-out"
    CLDFExporter(ctx).export(language=LANGUAGE, output_dir=export_dir)
    return _Canary(
        export_dir=export_dir,
        target_source=target_side.source_id,
        pivot_source=pivot_side.source_id,
    )


# --- 6.2.1: import governance --------------------------------------------------------------


def test_import_governance(ctx: AppContext, tmp_path: Path) -> None:
    # An `exclude` source is never ingested: INGEST is hard-denied before any byte work.
    exclude_key = _register_dataset(ctx, tmp_path, "gov-exclude", mode="exclude", allow=())
    with pytest.raises(PolicyDenied):
        CLDFImporter(ctx).extract(exclude_key)
    exclude_source = ctx.repo.find_source_by_key(exclude_key)
    assert exclude_source is not None
    assert ctx.repo.get_source(exclude_source.id).status is SourceStatus.REGISTERED

    # An `archive_only` source is ingested but its extraction is denied: exactly one
    # audit event, no extraction run row.
    archive_key = _register_dataset(ctx, tmp_path, "gov-archive", mode="archive_only", allow=())
    archive_source = ctx.repo.find_source_by_key(archive_key)
    assert archive_source is not None
    before = state_counts(ctx)
    with pytest.raises(PolicyDenied):
        CLDFImporter(ctx).extract(archive_key)
    after = state_counts(ctx)
    # The governed ingest itself ran (archive_only allows INGEST); no extraction run row.
    assert after["processing_run"] == before["processing_run"] + 1
    for obj in ctx.repo.list_source_objects(archive_source.id):
        assert ctx.repo.list_runs_with_input(obj.id, RunStage.EXTRACTION) == []
    denials = [
        event
        for event in ctx.repo.list_audit_events()
        if event.event_type is AuditEventType.POLICY_DENIED
        and event.subject_id == archive_source.id
    ]
    assert len(denials) == 1

    # A revoked source is refused on sight: one audit event, then PolicyDenied.
    revoked_key = _register_dataset(ctx, tmp_path, "gov-revoked")
    revoked_source = ctx.repo.find_source_by_key(revoked_key)
    assert revoked_source is not None
    _revoke(ctx, revoked_source.id)
    with pytest.raises(PolicyDenied):
        CLDFImporter(ctx).extract(revoked_key)
    revocations = [
        event
        for event in ctx.repo.list_audit_events()
        if event.event_type is AuditEventType.POLICY_DENIED
        and event.subject_id == revoked_source.id
    ]
    assert len(revocations) == 1

    # A source of the wrong type has no extractor here.
    wrong_key = _register_dataset(ctx, tmp_path, "gov-wrong", source_type="parallel_text")
    with pytest.raises(UnsupportedSource):
        CLDFImporter(ctx).extract(wrong_key)


def test_import_idempotency(ctx: AppContext, tmp_path: Path) -> None:
    key = _register_dataset(ctx, tmp_path, "idem-src")
    importer = CLDFImporter(ctx)
    first = importer.extract(key)
    assert first.reused is False

    before = state_counts(ctx)
    second = importer.extract(key)
    assert second.reused is True
    assert second.run.id == first.run.id
    assert state_counts(ctx) == before


# --- 6.2.3-6.2.4: the status threshold -------------------------------------------------------


def test_default_export_validated_only(ctx: AppContext, tmp_path: Path) -> None:
    _two_lexeme_world(ctx, tmp_path, "thr-src")

    exported = tmp_path / "thr-out"
    result = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=exported)
    assert result.exported["entries"] == 1
    rows = _exported_rows(exported, "EntryTable")
    assert len(rows) == 1
    assert all("Status" not in row for row in rows)
    assert all("Status" not in row for row in _exported_rows(exported, "SenseTable"))


def test_include_supported_adds_status_column(ctx: AppContext, tmp_path: Path) -> None:
    _, _, manii, kupa = _two_lexeme_world(ctx, tmp_path, "sup-src")

    # Promote the kupa lexeme and one sense to `supported` (the machine ceiling), reject the other.
    senses = _senses_of(ctx, kupa)
    with ctx.repo.transaction():
        ctx.repo.set_sense_status(senses[0], LifecycleStatus.SUPPORTED)
        ctx.repo.set_sense_status(senses[1], LifecycleStatus.REJECTED)
    with ctx.repo.transaction():
        ctx.repo.set_lexeme_status(kupa, LifecycleStatus.SUPPORTED)
    assert ctx.repo.get_lexeme(manii).status is LifecycleStatus.VALIDATED

    exported = tmp_path / "sup-out"
    result = CLDFExporter(ctx).export(
        language=LANGUAGE, output_dir=exported, include_supported=True
    )
    assert result.exported["entries"] == 2
    entries = {str(row["ID"]): row for row in _exported_rows(exported, "EntryTable")}
    assert entries[kupa]["Status"] == "supported"
    sense_rows = _exported_rows(exported, "SenseTable")
    assert {str(row["Status"]) for row in sense_rows} <= {"validated", "supported"}
    # CANDIDATE, REJECTED and DEPRECATED never appear.
    assert len(sense_rows) == 2  # maní's sense + kupa's supported sense


# --- 6.2.5-6.2.7: eligibility over ancestry ---------------------------------------------------


def test_redistribute_default_deny_is_omitted(ctx: AppContext, tmp_path: Path) -> None:
    allowed_key, _ = _import_world(ctx, tmp_path, "elig-allow")
    denied_key, _ = _import_world(ctx, tmp_path, "elig-deny", allow=())

    exported = tmp_path / "elig-out"
    result = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=exported)
    report = _report_of_export(ctx, result.run.id)
    entries = {str(row["ID"]) for row in _exported_rows(exported, "EntryTable")}
    # Only the allowed source's lexemes survive; the default-deny pair is omitted.
    assert entries == _lexemes_of_source(ctx, allowed_key)
    assert entries.isdisjoint(_lexemes_of_source(ctx, denied_key))
    assert report["omitted"]["denied"] >= 2


def test_mixed_ancestry_most_restrictive_wins(ctx: AppContext, tmp_path: Path) -> None:
    _, run_id = _import_world(ctx, tmp_path, "mix-allow")
    denied_key, _ = _import_world(ctx, tmp_path, "mix-deny", allow=())
    denied_source = ctx.repo.find_source_by_key(denied_key)
    assert denied_source is not None
    victim = _lexeme_by_headword(ctx, run_id, "maní")

    # One extra observation from the default-deny source: the lexeme now descends from it.
    extra_run = RunRecorder(ctx).start(
        RunStage.LEXICAL_INDUCTION, "langpipe.test", {}, [denied_source.id]
    )
    now = ctx.clock()
    extra = EvidenceItem(
        id=ctx.new_id(IdPrefix.EVIDENCE),
        kind=EvidenceKind.DICTIONARY_ASSERTION,
        polarity=EvidencePolarity.SUPPORTS,
        target_id=victim,
        source_id=denied_source.id,
        run_id=extra_run.id,
        created_at=now,
    )
    with ctx.repo.transaction():
        ctx.repo.add_evidence(extra)
        for from_id, to_id in ((victim, extra.id), (extra.id, denied_source.id)):
            ctx.repo.add_lineage_edge(
                LineageEdge(
                    id=ctx.new_id(IdPrefix.LINEAGE),
                    from_id=from_id,
                    to_id=to_id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=extra_run.id,
                    created_at=now,
                )
            )
    assert lineage_eligibility(ctx.repo, victim, Operation.REDISTRIBUTE_DERIVED) is (
        PolicyDecision.DENY
    )

    exported = tmp_path / "mix-out"
    result = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=exported)
    entries = {str(row["ID"]) for row in _exported_rows(exported, "EntryTable")}
    assert victim not in entries
    assert _report_of_export(ctx, result.run.id)["omitted"]["denied"] >= 1


def test_review_required_ancestry_is_counted(ctx: AppContext, tmp_path: Path) -> None:
    allowed_key, _ = _import_world(ctx, tmp_path, "rev-allow")
    # A review_required source may be imported (explicit extract/distill allows) but its
    # `redistribute_derived` stays at its default-deny baseline requiring review.
    _import_world(
        ctx,
        tmp_path,
        "rev-review",
        mode="review_required",
        allow=("extract", "distill_lexicon"),
    )

    exported = tmp_path / "rev-out"
    result = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=exported)
    report = _report_of_export(ctx, result.run.id)
    # The review_required source's rows are omitted and counted as review_required.
    assert report["omitted"]["review_required"] >= 1
    assert report["exported"]["entries"] == 2
    entries = {str(row["ID"]) for row in _exported_rows(exported, "EntryTable")}
    assert entries == _lexemes_of_source(ctx, allowed_key)


def test_shared_lemma_form_with_denying_source_is_omitted(ctx: AppContext, tmp_path: Path) -> None:
    # A `distill_only` side with no `redistribute_derived` allow tokenizes the same
    # `wera` form before the first export: `Form` rows are shared by (language,
    # profile, text), so the lexeme's lemma Form descends from a denying source too.
    deny_side, _tokens = _parallel_side(
        ctx, tmp_path, "shared-deny", LANGUAGE, "wera", "distill_only", allow=()
    )
    # The wera row is refused at selection (§3.2 step 3) — the lemma Form is a
    # contributing entity, so the failing row is omitted instead of the whole export
    # dying in the TOCTOU re-check with a PolicyDenied. It is the fixture's only
    # entry, so its omission fails the export closed (D8).
    with pytest.raises(NoEligibleRecords):
        _canary_world(ctx, tmp_path)

    # D8: exactly one POLICY_DENIED audit event names the denying source, and nothing
    # is written — no output directory, no orphan staging dir.
    denials = [
        event
        for event in ctx.repo.list_audit_events()
        if event.event_type is AuditEventType.POLICY_DENIED
        and event.subject_id == deny_side.source_id
    ]
    assert len(denials) == 1
    assert denials[0].details == {"operation": "redistribute_derived", "decision": "deny"}
    assert not (tmp_path / "canary-out").exists()
    assert not list(tmp_path.glob(".canary-out.staging-*"))
    # The refused row still exists — it is omitted from the export, not deleted: its
    # shared lemma Form is what went ineligible.
    assert _lexeme_with_lemma_text(ctx, "wera") is not None


# --- 6.2.8: nothing eligible is fail-closed ----------------------------------------------------


def test_all_denied_fails_closed(ctx: AppContext, tmp_path: Path) -> None:
    denied_key, _ = _import_world(ctx, tmp_path, "deny-src", allow=())
    denied_source = ctx.repo.find_source_by_key(denied_key)
    assert denied_source is not None

    output = tmp_path / "deny-out"
    before = state_counts(ctx)
    with pytest.raises(NoEligibleRecords):
        CLDFExporter(ctx).export(language=LANGUAGE, output_dir=output)
    after = state_counts(ctx)

    # One POLICY_DENIED event per denying source, no run, no artifact, no output directory.
    denials = [
        event
        for event in ctx.repo.list_audit_events()
        if event.event_type is AuditEventType.POLICY_DENIED and event.subject_id == denied_source.id
    ]
    assert len(denials) == 1
    assert denials[0].details == {"operation": "redistribute_derived", "decision": "deny"}
    assert after["processing_run"] == before["processing_run"]
    assert after["artifact"] == before["artifact"]
    assert not output.exists()


# --- 6.2.9: revocation integration (WP4.9) ------------------------------------------------------


def test_revocation_omits_rows_and_impact_reaches_exports(ctx: AppContext, tmp_path: Path) -> None:
    _import_world(ctx, tmp_path, "revo-keep")
    doomed_key, _ = _import_world(ctx, tmp_path, "revo-doomed")
    doomed_source = ctx.repo.find_source_by_key(doomed_key)
    assert doomed_source is not None

    first_dir = tmp_path / "revo-1"
    first = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=first_dir)
    assert first.exported["entries"] == 4  # both sources' maní and kupa

    _revoke(ctx, doomed_source.id)

    second_dir = tmp_path / "revo-2"
    second = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=second_dir)
    report = _report_of_export(ctx, second.run.id)
    assert report["omitted"]["revoked"] >= 1
    assert report["exported"]["entries"] == 2
    entries = {str(row["ID"]) for row in _exported_rows(second_dir, "EntryTable")}
    assert entries.isdisjoint(_lexemes_of_source(ctx, doomed_key))
    # WP4.9 integration: the impact walk from the revoked source reaches every
    # published file (§3.8 lineage) — each table artifact derives from the entities
    # whose rows it contains (languages.csv from the exported lexemes), and the
    # metadata and sources.bib derive from the table artifacts.
    impact = revocation_impact(ctx.repo, doomed_source.id)
    reachable = set(impact.artifacts)
    first_report = _report_of_export(ctx, first.run.id)
    sha_by_name = {entry["name"]: entry["sha256"] for entry in first_report["files"]}  # type: ignore[index]
    sha_to_id = {artifact.sha256: artifact.id for artifact in first.files}
    for name in (
        "entries.csv",
        "languages.csv",
        "senses.csv",
        "Dictionary-metadata.json",
        "sources.bib",
    ):
        assert sha_to_id[sha_by_name[name]] in reachable, name


# --- 6.2.10: TOCTOU commit guard -----------------------------------------------------------------


def test_toctou_change_between_selection_and_commit(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_world(ctx, tmp_path, "toctou-keep")
    doomed_key, _ = _import_world(ctx, tmp_path, "toctou-doomed")
    doomed_source = ctx.repo.find_source_by_key(doomed_key)
    assert doomed_source is not None

    output = tmp_path / "toctou-out"
    finished = record_finished_runs(ctx, monkeypatch)
    original_lock = ctx.repo.lock_sources

    def revoking_lock(source_ids: object, **kwargs: object) -> None:
        original_lock(source_ids, **kwargs)  # type: ignore[arg-type]
        # The source dies while its lock is held, between selection and commit — inside
        # the exporter's own transaction, where the re-check will see it.
        ctx.repo.set_source_status(doomed_source.id, SourceStatus.REVOKED, ctx.clock())

    monkeypatch.setattr(ctx.repo, "lock_sources", revoking_lock)
    with pytest.raises(PolicyDenied):
        CLDFExporter(ctx).export(language=LANGUAGE, output_dir=output)

    assert any(run.status is RunStatus.FAILED for run in finished)
    assert not output.exists()
    assert not list(tmp_path.glob(".toctou-out.staging-*"))


# --- 6.2.11-6.2.12: the raw-redistribution firewall ---------------------------------------------


def test_distill_only_canary_never_reaches_export(ctx: AppContext, tmp_path: Path) -> None:
    canary = _canary_world(ctx, tmp_path)

    files = sorted(path for path in canary.export_dir.iterdir())
    assert files
    for path in files:
        body = path.read_text(encoding="utf-8")
        assert CANARY_SENTENCE not in body
        assert PIVOT_SENTENCE not in body
    metadata = _exported_metadata(canary.export_dir)
    table_urls = [str(table.get("url")) for table in metadata["tables"]]  # type: ignore[index]
    assert not any("example" in url.lower() for url in table_urls)


def test_export_firewall_guard(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_world(ctx, tmp_path, "fw-src")

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the exporter must not touch raw or segment data")

    monkeypatch.setattr(ctx.repo, "get_segment", boom)
    monkeypatch.setattr(ctx.repo, "get_token", boom)
    monkeypatch.setattr(ctx.repo, "list_source_objects", boom)
    monkeypatch.setattr(ctx.raw_store, "read_bytes", boom)

    exported = tmp_path / "fw-out"
    result = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=exported)
    assert result.exported["entries"] == 2
    assert exported.exists()


# --- 6.2.13: attribution -------------------------------------------------------------------------


def test_attribution_metadata_is_embedded(ctx: AppContext, tmp_path: Path) -> None:
    _register_dataset(
        ctx,
        tmp_path,
        "attr-src",
        restrictions={
            "attribution": {
                "required": True,
                "license": "CC-BY-4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "text": "Fixture corpus, CC BY 4.0",
            }
        },
    )
    source = ctx.repo.find_source_by_key("attr-src")
    assert source is not None
    _, induction = CLDFImporter(ctx).import_dataset("attr-src")
    _validate_all(ctx, induction.run.id)

    exported = tmp_path / "attr-out"
    CLDFExporter(ctx).export(language=LANGUAGE, output_dir=exported)

    metadata = _exported_metadata(exported)
    derived = metadata["prov:wasDerivedFrom"]  # type: ignore[index]
    assert any(
        entry["dc:bibliographicCitation"] == "Fixture corpus, CC BY 4.0" for entry in derived
    )
    assert any(entry["rdf:about"] == f"langpipe:source:{source.key}" for entry in derived)
    bib = (exported / "sources.bib").read_text(encoding="utf-8")
    assert source.key in bib
    for row in _exported_rows(exported, "EntryTable"):
        assert source.key in row["Source"]
    for row in _exported_rows(exported, "SenseTable"):
        assert source.key in row["Source"]


# --- 6.2.14: run records --------------------------------------------------------------------


def test_export_run_records_lineage_and_report(ctx: AppContext, tmp_path: Path) -> None:
    _import_world(ctx, tmp_path, "rec-src")

    exported = tmp_path / "rec-out"
    result = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=exported)

    # One EXPORT run, one CLDF_EXPORT artifact per file, each digest matching the bytes.
    assert result.run.stage is RunStage.EXPORT
    assert result.run.tool_name == CLDF_EXPORT_TOOL
    report = _report_of_export(ctx, result.run.id)
    by_name = {
        entry["name"]: artifact  # type: ignore[index]
        for entry in report["files"]  # type: ignore[index]
        for artifact in result.files
        if artifact.sha256 == entry["sha256"]
    }
    assert len(result.files) == len(list(exported.iterdir()))
    for name, artifact in by_name.items():
        assert artifact.kind is ArtifactKind.CLDF_EXPORT
        on_disk = (exported / name).read_bytes()
        assert sha256(on_disk).hexdigest() == artifact.sha256

    # Lineage: table artifacts derive from the entities they contain; metadata and bib
    # derive from the table artifacts (§3.8).
    def parents(artifact_id: str) -> set[str]:
        return {edge.to_id for edge in ctx.repo.list_lineage_edges(artifact_id, "out")}

    lexemes = set(_outputs_of(ctx, result.run.id, EntityType.LEXEME))
    senses = set(_outputs_of(ctx, result.run.id, EntityType.SENSE))
    concepts = set(_outputs_of(ctx, result.run.id, EntityType.CONCEPT))
    assert lexemes <= parents(by_name["entries.csv"].id)
    assert senses | concepts <= parents(by_name["senses.csv"].id)
    for name in ("entries.csv", "senses.csv", "languages.csv"):
        assert by_name[name].id in parents(by_name["Dictionary-metadata.json"].id)
        assert by_name[name].id in parents(by_name["sources.bib"].id)

    # The report carries ids, enum values and counts only — never a form or a gloss.
    report_bytes = json.dumps(report)
    for secret in ("kupa", "maní", "bowl", "container", "water", "fire", "stone"):
        assert secret not in report_bytes


# --- 6.2.15: export reuse --------------------------------------------------------------------


def test_export_reuse_and_selection_digest(ctx: AppContext, tmp_path: Path) -> None:
    _, _, manii, kupa = _two_lexeme_world(ctx, tmp_path, "reuse-src")

    first_dir = tmp_path / "reuse-1"
    first = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=first_dir)
    assert first.reused is False

    before = state_counts(ctx)
    second_dir = tmp_path / "reuse-2"
    second = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=second_dir)
    assert second.reused is True
    assert second.run.id == first.run.id
    assert state_counts(ctx) == before
    for name in (path.name for path in first_dir.iterdir()):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes(), name

    # A status flip changes the selection digest: a new run, not a reuse. The whole
    # kupa entry (lexeme and its senses) crosses the threshold together.
    del manii
    with ctx.repo.transaction():
        for sense_id in _senses_of(ctx, kupa):
            ctx.repo.set_sense_status(sense_id, LifecycleStatus.VALIDATED)
        ctx.repo.set_lexeme_status(kupa, LifecycleStatus.VALIDATED)
    third_dir = tmp_path / "reuse-3"
    third = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=third_dir)
    assert third.reused is False
    assert third.run.id != first.run.id
    assert third.exported["entries"] == 2

    # A reuse into a pre-created empty directory also succeeds: the preflight admits
    # an empty directory (§3.2 step 1), so the re-materialization must not refuse it.
    fourth_dir = tmp_path / "reuse-4"
    fourth_dir.mkdir()
    fourth = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=fourth_dir)
    assert fourth.reused is True
    assert fourth.run.id == third.run.id
    for name in (path.name for path in third_dir.iterdir()):
        assert (third_dir / name).read_bytes() == (fourth_dir / name).read_bytes(), name


# --- 6.2.15b: reuse passes the same TOCTOU guard as a fresh export ------------------------------


def _find_reusable_hook(
    exporter: CLDFExporter,
    first_run_id: str,
    change: Callable[[], None],
) -> Callable[[], object]:
    """A ``find_reusable`` stand-in that lets state change between selection and reuse."""
    original_find = exporter.recorder.find_reusable

    def hook(*args: object, **kwargs: object) -> object:
        reused = original_find(*args, **kwargs)  # type: ignore[arg-type]
        assert reused is not None
        assert reused.id == first_run_id  # type: ignore[union-attr]
        change()
        return reused

    return hook


def test_reused_export_rechecks_revocation_before_publish(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_key, _ = _import_world(ctx, tmp_path, "reuse-guard")
    source = ctx.repo.find_source_by_key(source_key)
    assert source is not None

    first_dir = tmp_path / "guard-1"
    first = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=first_dir)
    assert first.reused is False

    # A contributor is revoked after selection but while the reusable run is found:
    # the reuse must refuse before any byte is published (§3.2 step 9, §3.8).
    exporter = CLDFExporter(ctx)
    monkeypatch.setattr(
        exporter.recorder,
        "find_reusable",
        _find_reusable_hook(exporter, first.run.id, lambda: _revoke(ctx, source.id)),
    )

    before = state_counts(ctx)
    second_dir = tmp_path / "guard-2"
    with pytest.raises(PolicyDenied):
        exporter.export(language=LANGUAGE, output_dir=second_dir)
    assert not second_dir.exists()
    assert not list(tmp_path.glob(".guard-2.staging-*"))
    # A refused reuse writes nothing and never flips the historical succeeded run.
    assert ctx.repo.get_run(first.run.id).status is RunStatus.SUCCEEDED
    assert state_counts(ctx) == before


def test_reused_export_rechecks_status_flip_before_publish(
    ctx: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _import_world(ctx, tmp_path, "reuse-flip")
    first_dir = tmp_path / "flip-1"
    first = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=first_dir)
    victim = str(_report_of_export(ctx, first.run.id)["entry_ids"][0])  # type: ignore[index]

    exporter = CLDFExporter(ctx)

    def flip_status() -> None:
        with ctx.repo.transaction():
            ctx.repo.set_lexeme_status(victim, LifecycleStatus.CANDIDATE)

    monkeypatch.setattr(
        exporter.recorder,
        "find_reusable",
        _find_reusable_hook(exporter, first.run.id, flip_status),
    )

    second_dir = tmp_path / "flip-2"
    with pytest.raises(SchemaViolation):
        exporter.export(language=LANGUAGE, output_dir=second_dir)
    assert not second_dir.exists()
    assert not list(tmp_path.glob(".flip-2.staging-*"))
    assert ctx.repo.get_run(first.run.id).status is RunStatus.SUCCEEDED


# --- 6.2.15c: reuse reports the current selection's counts -------------------------------------


def test_reused_export_reports_current_omitted_counts(ctx: AppContext, tmp_path: Path) -> None:
    """A reuse must not present the original run's ``omitted`` counts as the current ones.

    The selection digest pins only the exported rows (ids, statuses, attribution), so a
    reuse can happen while rows that are *omitted* have joined since the original run —
    here a below-threshold lexeme and a validated lexeme whose sense resolves no
    headword. The report artifact stays the historical record of its own run (§3.8), but
    the result a caller and ``langpipe cldf export`` print must describe the selection
    actually made now (ADR-0016: omissions are enumerated so governance pressure stays
    visible).
    """
    source_key, induction_run, _, _ = _two_lexeme_world(ctx, tmp_path, "stale-omitted")

    first_dir = tmp_path / "stale-1"
    first = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=first_dir)
    assert first.reused is False
    stored = _report_of_export(ctx, first.run.id)
    assert first.omitted == stored["omitted"]

    # A later import left two rows behind the threshold: one candidate lexeme, and one
    # validated lexeme whose single sense descends from the same source but has no lemma
    # Form and no headword evidence. Neither changes the exported selection, so the run
    # stays reusable.
    source = ctx.repo.find_source_by_key(source_key)
    assert source is not None
    source_id = source.id
    with ctx.repo.transaction():
        ctx.repo.add_lexeme(
            Lexeme(
                id=ctx.new_id(IdPrefix.LEXEME),
                language=LANGUAGE,
                status=LifecycleStatus.CANDIDATE,
                run_id=induction_run,
                created_at=ctx.clock(),
            )
        )
        bare = Lexeme(
            id=ctx.new_id(IdPrefix.LEXEME),
            language=LANGUAGE,
            status=LifecycleStatus.VALIDATED,
            run_id=induction_run,
            created_at=ctx.clock(),
        )
        ctx.repo.add_lexeme(bare)
        sense = Sense(
            id=ctx.new_id(IdPrefix.SENSE),
            lexeme_id=bare.id,
            glosses={"por": ["sem forma"]},
            status=LifecycleStatus.VALIDATED,
            run_id=induction_run,
            created_at=ctx.clock(),
        )
        ctx.repo.add_sense(sense)
        # The lineage shape the inducer writes: lexeme → source object, sense → lexeme.
        for child, parent in ((bare.id, source_id), (sense.id, bare.id)):
            ctx.repo.add_lineage_edge(
                LineageEdge(
                    id=ctx.new_id(IdPrefix.LINEAGE),
                    from_id=child,
                    to_id=parent,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=induction_run,
                    created_at=ctx.clock(),
                )
            )

    second_dir = tmp_path / "stale-2"
    second = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=second_dir)
    assert second.reused is True
    assert second.run.id == first.run.id
    assert second.exported == first.exported
    for name in (path.name for path in first_dir.iterdir()):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes(), name

    # The current selection omits one more below-threshold lexeme and one more bare form.
    assert second.omitted["status_below_threshold"] == first.omitted["status_below_threshold"] + 1
    assert second.omitted["no_form"] == first.omitted["no_form"] + 1
    # The reused run's own report still records what the original run counted.
    assert _report_of_export(ctx, second.run.id)["omitted"] == stored["omitted"]


# --- 6.2.16: output directory safety -----------------------------------------------------------


def test_non_empty_output_directory_is_refused(ctx: AppContext, tmp_path: Path) -> None:
    _import_world(ctx, tmp_path, "safety-src")

    output = tmp_path / "safety-out"
    output.mkdir()
    (output / "occupied.txt").write_text("do not merge", encoding="utf-8")
    before = state_counts(ctx)

    with pytest.raises(SchemaViolation):
        CLDFExporter(ctx).export(language=LANGUAGE, output_dir=output)

    assert state_counts(ctx) == before
    assert (output / "occupied.txt").exists()


# --- 6.2.18: reuse re-derives the current access class -----------------------------------------


def test_reused_export_rederives_current_access_class(ctx: AppContext, tmp_path: Path) -> None:
    from sqlalchemy import text

    source_key, _ = _import_world(ctx, tmp_path, "reuse-access-class")
    first_dir = tmp_path / "access-1"
    first = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=first_dir)
    assert first.reused is False
    assert first.access_class is AccessClass.PUBLIC
    assert all(f.access_class is AccessClass.PUBLIC for f in first.files)
    assert first.report.access_class is AccessClass.PUBLIC

    # The contributing source's policy tightens without changing permissions,
    # attribution or selected rows.
    source = ctx.repo.find_source_by_key(source_key)
    assert source is not None
    with ctx.repo.transaction():
        if hasattr(ctx.repo, "_writer"):
            session = ctx.repo._writer()
            session.execute(
                text("ALTER TABLE source_policy DISABLE TRIGGER trg_source_policy_forbid_mutation")
            )
            session.execute(
                text("UPDATE source_policy SET access_class = :ac WHERE id = :id"),
                {"ac": AccessClass.COMMUNITY.value, "id": source.policy_id},
            )
            session.execute(
                text("ALTER TABLE source_policy ENABLE TRIGGER trg_source_policy_forbid_mutation")
            )
        else:
            policy = ctx.repo.get_policy(source.policy_id)
            ctx.repo._state.policies[source.policy_id] = policy.model_copy(
                update={"access_class": AccessClass.COMMUNITY}
            )

    second_dir = tmp_path / "access-2"
    second = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=second_dir)
    assert second.reused is True
    assert second.run.id == first.run.id
    assert second.access_class is AccessClass.COMMUNITY
    assert all(f.access_class is AccessClass.COMMUNITY for f in second.files)
    assert second.report.access_class is AccessClass.COMMUNITY

    # The historical artifacts in the repository keep their original access class.
    assert ctx.repo.get_artifact(first.report.id).access_class is AccessClass.PUBLIC
    assert ctx.repo.get_artifact(first.files[0].id).access_class is AccessClass.PUBLIC


# --- WP5.14: Truthful omission of stale dependents (C-2) -------------------------------------


def test_cldf_export_report_schema_version_2(ctx: AppContext, tmp_path: Path) -> None:
    """The export report artifact carries schema_version=2 (Invariant 11, WP5.14)."""
    _two_lexeme_world(ctx, tmp_path, "schema-v2-src")
    RecalcService(ctx).recalculate(all_stale=True)
    out = tmp_path / "schema-v2-out"
    res = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=out)
    report_dict = _report_of_export(ctx, res.run.id)
    assert report_dict["schema"] == "cldf-export-report"
    assert report_dict["schema_version"] == 2
    artifact = ctx.repo.get_artifact(res.report.id)
    assert artifact.schema_version == 2


def test_unresolved_stale_sense_omitted_and_recalculation_includes_it(
    ctx: AppContext, tmp_path: Path
) -> None:
    """An unresolved stale sense is omitted from CLDF export, and included after recalculation."""
    source_key, induction_run, _, _ = _two_lexeme_world(ctx, tmp_path, "truthful-stale")

    # Pick one lexeme and give it two validated senses
    lexemes = [
        lex
        for lex in ctx.repo.list_lexemes_by_language(LANGUAGE)
        if lex.status is LifecycleStatus.VALIDATED
    ]
    assert len(lexemes) >= 1
    target_lex = lexemes[0]
    existing_senses = ctx.repo.list_senses_for_lexeme(target_lex.id)
    assert len(existing_senses) >= 1
    sense_a = existing_senses[0]

    # Add a second validated sense to target_lex, but flag it as stale_dependent
    with ctx.repo.transaction():
        sense_b = Sense(
            id=ctx.new_id(IdPrefix.SENSE),
            lexeme_id=target_lex.id,
            glosses={"por": ["segundo sentido"]},
            status=LifecycleStatus.VALIDATED,
            run_id=induction_run,
            created_at=ctx.clock(),
        )
        ctx.repo.add_sense(sense_b)
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=sense_b.id,
                to_id=target_lex.id,
                kind=LineageKind.DERIVED_FROM,
                run_id=induction_run,
                created_at=ctx.clock(),
            )
        )
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=sense_b.id,
                to_id=target_lex.id,
                kind=LineageKind.STALE_DEPENDENT,
                run_id=induction_run,
                created_at=ctx.clock(),
            )
        )

    # Export: sense_b has an unresolved stale flag, so it must be omitted
    out_1 = tmp_path / "stale-omitted-1"
    res_1 = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=out_1)
    assert res_1.omitted["stale_dependent"] == 1
    # Check senses.csv: sense_a is present, sense_b is absent
    senses_csv = (out_1 / "senses.csv").read_text(encoding="utf-8")
    assert sense_a.id in senses_csv
    assert sense_b.id not in senses_csv

    # Recalculate sense_b
    recalc = RecalcService(ctx).recalculate([sense_b.id])
    assert recalc.recalculated_ids == (sense_b.id,)

    # Re-export to out_2: sense_b is no longer stale, so both senses are exported
    out_2 = tmp_path / "stale-omitted-2"
    res_2 = CLDFExporter(ctx).export(language=LANGUAGE, output_dir=out_2)
    assert res_2.omitted["stale_dependent"] == 0
    senses_csv_2 = (out_2 / "senses.csv").read_text(encoding="utf-8")
    assert sense_a.id in senses_csv_2
    assert sense_b.id in senses_csv_2


def test_sole_sense_stale_causes_no_exportable_sense_and_no_eligible_records(
    ctx: AppContext, tmp_path: Path
) -> None:
    """When a lexeme's only sense is stale, the lexeme has no exportable senses."""
    source_key = _register_dataset(ctx, tmp_path, "sole-stale")
    _, induction = CLDFImporter(ctx).import_dataset(source_key)
    run_id = induction.run.id
    manii = _lexeme_by_headword(ctx, run_id, "maní")
    assert _review_one(ctx, manii, ReviewTaskType.LEMMA) is LifecycleStatus.VALIDATED
    for sense_id in _senses_of(ctx, manii):
        assert _review_one(ctx, sense_id, ReviewTaskType.LEXICAL_SENSE) is (
            LifecycleStatus.VALIDATED
        )
    # manii was reviewed, which flagged all its senses as stale_dependent.
    # Because RecalcService was NOT run, all senses remain stale and are omitted,
    # leaving 0 exportable senses, which raises NoEligibleRecords.
    out = tmp_path / "sole-stale-out"
    with pytest.raises(NoEligibleRecords):
        CLDFExporter(ctx).export(language=LANGUAGE, output_dir=out)
