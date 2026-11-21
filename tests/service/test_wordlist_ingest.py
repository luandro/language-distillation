"""Governed wordlist extraction (M4-PLAN §6 WP4.6, ADR-0007).

`WordlistExtractor` is the one place a wordlist becomes hypotheses: it requires a registered
`Source` of type `WORDLIST` owned by that source, ingests under `Operation.INGEST` before any
origin work, and gates, reads and decodes under `Operation.EXTRACT`. The pure adapter
(`lexicon.adapters.wordlist`) owns every linguistic decision and is covered in
`tests/unit/test_wordlist_adapter.py`; these tests cover the governance sequence, the
immutability of the raw bytes and the recorded run's lineage, against both the memory and
PostgreSQL backends (run sequentially).

Governed cases (ADR-0007 §6/§7 and M4-PLAN §3):

- a `direct` wordlist is ingested and extracted; its run pins the objects it read and links
  its report artifact to them;
- an `exclude` manifest never registers objects, so no origin is hashed at all (ADR-0007 §7);
- `archive_only` is preserved by INGEST and refused by EXTRACT: bytes stored, content never
  decoded;
- `restricted` and `review_required` deny EXTRACT before any byte is read;
- a revoked source is denied on INGEST and never re-ingested;
- a store whose content no longer matches the registered sha256 fails integrity;
- the stored bytes are the bytes the adapter induced from, and no source content is logged
  or written into the report, on either the success or a failure path.
"""

import json
import logging
import os
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AuditEventType,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    PolicyMode,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    SourceType,
)
from langpipe.domain.errors import HashMismatch, PolicyDenied, SchemaViolation, UnsupportedSource
from langpipe.domain.hashing import canonical_json, sha256_bytes
from langpipe.ingest.wordlist import WordlistExtractionResult, WordlistExtractor
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.lexicon.adapters.wordlist import WordlistFormatError
from langpipe.lexicon.base import LexicalInductionOutput
from tests.service.manifests import (
    manifest_data,
    spy_all_io,
    state_counts,
    write_manifest,
    write_origin_file,
)

GOLDEN_SOURCES = Path(__file__).resolve().parents[1] / "golden" / "fixture" / "sources"
WORDLIST = GOLDEN_SOURCES / "03-wordlist" / "wordlist.tsv"
TSV = "text/tab-separated-values"
SENTINEL_HEADWORD = "SENTINELHEADWORD"
SENTINEL_GLOSS = "SENTINELGLOSS"

WORDLIST_BYTES = (
    "qaa\tpor\tnote\n"
    "kanu\thomem\n"
    f"{SENTINEL_HEADWORD}\t{SENTINEL_GLOSS}\n"
    "mabi\tcanoa; tronco\ttwo candidate senses\n"
    "rumi\tpajé\tdomain-specific (ritual/traditional)\n"
).encode()


def _wordlist_source(
    ctx: AppContext,
    tmp_path: Path,
    key: str,
    *,
    mode: str = "direct",
    access_class: str = "public",
    languages: tuple[str, ...] = ("qaa", "por"),
    body: bytes = WORDLIST_BYTES,
) -> RegistrationResult:
    relative = f"{key}/wordlist.tsv"
    write_origin_file(tmp_path, relative, body)
    data = manifest_data(
        key=key,
        mode=mode,
        access_class=access_class,
        objects=[{"path": relative, "media_type": TSV}],
    )
    data["source_type"] = SourceType.WORDLIST.value
    data["languages"] = list(languages)
    return register_source(ctx, write_manifest(tmp_path, data, name=f"{key}.yaml"))


def _extract(ctx: AppContext, source_ref: str, **kwargs: str) -> WordlistExtractionResult:
    return WordlistExtractor(ctx).extract(source_ref, **kwargs)


def _headwords(result: WordlistExtractionResult) -> list[str]:
    return sorted(str(item.claim["headword"]) for item in result.induction.evidence_items)


def _rewrite_mode(ctx: AppContext, registered: RegistrationResult, mode: str) -> None:
    """Change one registered policy's mode, as an operator recording a governance change."""
    policy = ctx.repo.get_policy(registered.source.policy_id)
    with ctx.repo.transaction():
        ctx.repo.add_policy(policy.model_copy(update={"mode": PolicyMode(mode)}))


# --- allowed ----------------------------------------------------------------------


def test_allowed_wordlist_source_ingests_and_extracts(ctx: AppContext, tmp_path: Path) -> None:
    registered = _wordlist_source(ctx, tmp_path, "wl-allowed")

    result = _extract(ctx, registered.source.key)

    assert result.reused is False
    assert result.run.stage is RunStage.EXTRACTION
    assert result.run.status is RunStatus.SUCCEEDED
    assert ctx.repo.get_source(registered.source.id).status is SourceStatus.INGESTED
    # One lexeme per headword, `mabi` with two senses (Phenomenon 2) and `rumi` keeping its
    # domain tag (Phenomenon 9). Every hypothesis stays `candidate` (Invariant 3).
    assert _headwords(result) == [SENTINEL_HEADWORD, "kanu", "mabi", "mabi", "rumi"]
    assert len(result.induction.lexemes) == 4
    assert len(result.induction.senses) == 5
    assert [sense.domain for sense in result.induction.senses if sense.domain] == [
        "ritual/traditional"
    ]
    assert {lexeme.status for lexeme in result.induction.lexemes} <= {"candidate", "supported"}
    assert result.induction.concepts == []


def test_the_run_pins_the_source_objects_and_links_the_report(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _wordlist_source(ctx, tmp_path, "wl-pinned")

    result = _extract(ctx, registered.source.key)
    objects = ctx.repo.list_source_objects(registered.source.id)
    io = dict(ctx.repo.list_run_io(result.run.id))

    assert {obj for obj, role in io.items() if role is RunIoRole.INPUT} == {
        obj.id for obj in objects
    }
    assert result.report is not None
    assert io[result.report.id] is RunIoRole.OUTPUT
    # The report artifact is derived from the objects it read (AGENTS.md invariant 4).
    edges = ctx.repo.list_lineage_edges(result.report.id, "out")
    assert edges
    assert all(edge.kind is LineageKind.DERIVED_FROM for edge in edges)
    assert all(edge.run_id == result.run.id for edge in edges)
    assert {edge.to_id for edge in edges} == {obj.id for obj in objects}


def test_the_golden_wordlist_fixture_extracts(ctx: AppContext) -> None:
    registered = register_source(ctx, WORDLIST.parent / "manifest.yaml")

    result = _extract(ctx, registered.source.key)

    assert _headwords(result) == ["kanu", "mabi", "mabi", "rumi"]
    assert len(result.induction.lexemes) == 3
    assert len(result.induction.senses) == 4


def test_a_normal_mzr_wordlist_uses_the_header_target_column(
    ctx: AppContext, tmp_path: Path
) -> None:
    # The target column is named by its language tag, not by position (Gate 22 §2).
    registered = _wordlist_source(
        ctx, tmp_path, "wl-mzr", languages=("mzr", "por"), body=b"mzr\tpor\nkanu\thomem\n"
    )

    result = _extract(ctx, registered.source.id)

    assert [lexeme.language for lexeme in result.induction.lexemes] == ["mzr"]
    assert result.induction.senses[0].glosses == {"por": ["homem"]}


def test_a_header_relabelling_the_contact_column_refuses_before_any_hypothesis(
    ctx: AppContext, tmp_path: Path
) -> None:
    # `por` declares the first column Portuguese and `note` declares the only other column
    # a note column, so no column can carry `mzr` headwords: the governed entry point
    # refuses before any lexical output exists (Invariants 8 and 9; ADR-0013 §1). The
    # started run records the failure and pins no input, so no later stage can consume it.
    registered = _wordlist_source(
        ctx,
        tmp_path,
        "wl-header-refusal",
        languages=("mzr", "por"),
        body=b"por\tnote\nhomem\tremarks\n",
    )
    ingest_source(ctx, registered.source.id)
    before = state_counts(ctx)

    with pytest.raises(WordlistFormatError) as failure:
        _extract(ctx, registered.source.id)

    assert failure.value.code == WordlistFormatError.HEADER_INVALID
    assert not _extraction_runs(ctx, registered.source.id)
    # Only the failed extraction run row is written: no input pin, no report artifact, no
    # lineage edge and no lexical record of any kind.
    assert state_counts(ctx) == {**before, "processing_run": before["processing_run"] + 1}


def test_an_explicit_target_language_must_be_a_source_language(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _wordlist_source(ctx, tmp_path, "wl-lang")

    with pytest.raises(SchemaViolation):
        _extract(ctx, registered.source.id, target_language="xxx")

    with pytest.raises(SchemaViolation):
        _extract(ctx, registered.source.id, contact_language="qaa")


def test_the_same_inputs_and_config_reuse_the_succeeded_run(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _wordlist_source(ctx, tmp_path, "wl-reuse")

    first = _extract(ctx, registered.source.id)
    second = _extract(ctx, registered.source.id)

    assert first.reused is False
    assert second.reused is True
    assert second.run.id == first.run.id
    assert second.report is not None
    assert second.report.id == first.report.id
    # The reused run reproduces the same hypotheses: generated ids and timestamps differ
    # (a fresh clock and id factory), so compare the semantic content only.
    assert _digest(second.induction) == _digest(first.induction)


def _digest(induction: LexicalInductionOutput) -> list:
    """Id-independent semantic digest of one induction output."""
    return [
        sorted((lexeme.language, str(lexeme.status)) for lexeme in induction.lexemes),
        sorted(
            (canonical_json(sense.glosses), sense.domain, str(sense.status))
            for sense in induction.senses
        ),
        sorted(
            (
                str(item.claim.get("headword")),
                str(item.claim.get("gloss")),
                item.kind,
                item.polarity,
                item.source_id,
                canonical_json(item.strength),
                item.independence_group,
                item.domain,
            )
            for item in induction.evidence_items
        ),
        len(induction.lineage_edges),
    ]


# --- denials ----------------------------------------------------------------------


def test_exclude_registration_never_hashes_an_origin(ctx: AppContext, tmp_path: Path) -> None:
    # ADR-0007 §7: an `exclude` manifest records metadata only, so no origin is resolved,
    # read or hashed, and no byte work can happen later.
    write_origin_file(tmp_path, "wl-excluded/wordlist.tsv", WORDLIST_BYTES)
    data = manifest_data(key="wl-excluded", mode="exclude", objects=[])
    data["source_type"] = SourceType.WORDLIST.value
    data["languages"] = ["qaa", "por"]

    registered = register_source(ctx, write_manifest(tmp_path, data, name="wl-excluded.yaml"))

    assert registered.objects == ()
    assert ctx.repo.get_raw_blob(sha256_bytes(WORDLIST_BYTES)) is None


def test_exclude_source_denies_ingestion_without_storing_bytes(
    ctx: AppContext, tmp_path: Path
) -> None:
    # An `exclude` source registered with objects (as an earlier stage may have recorded
    # them) is refused by the INGEST gate before any origin read: no stored object, no blob
    # and one POLICY_DENIED audit event.
    registered = _wordlist_source(
        ctx, tmp_path, "wl-excl-obj", mode="exclude", access_class="highly_restricted"
    )
    # Registration under `exclude` records metadata only, so its objects were never hashed;
    # re-register the same body under a permissive policy to prove the gate still refuses.
    assert registered.objects == ()
    before = state_counts(ctx)

    with spy_all_io(ctx) as mocks, pytest.raises(PolicyDenied):
        _extract(ctx, registered.source.id)

    # The INGEST gate precedes origin work: no store method and no file open is called.
    assert all(mock.call_count == 0 for mock in mocks)
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    events = [event for event in ctx.repo.list_audit_events() if event.run_id is None]
    assert [event.event_type for event in events] == [AuditEventType.POLICY_DENIED]
    assert events[0].subject_id == registered.source.id
    assert events[0].details == {
        "operation": Operation.INGEST.value,
        "decision": PolicyDecision.DENY.value,
    }


def test_archive_only_preserves_bytes_but_denies_extraction(
    ctx: AppContext, tmp_path: Path
) -> None:
    # ADR-0007 §6: `archive_only` allows INGEST (preserve) and hard-denies EXTRACT, so the
    # bytes exist in the immutable store while the content is never read or decoded.
    registered = _wordlist_source(ctx, tmp_path, "wl-archive", mode="archive_only")
    ingest_source(ctx, registered.source.id)
    before = state_counts(ctx)

    # Only the extraction's own reads are spied: ingestion already ran, so a store read
    # inside the block belongs to the refused extraction and nothing else.
    with spy_all_io(ctx) as mocks, pytest.raises(PolicyDenied):
        _extract(ctx, registered.source.id)

    object_ = ctx.repo.list_source_objects(registered.source.id)[0]
    blob = ctx.repo.get_raw_blob(object_.sha256)
    assert blob is not None and blob.sha256 == object_.sha256
    assert ctx.raw_store.read_bytes(object_.sha256) == WORDLIST_BYTES
    assert all(mock.call_count == 0 for mock in mocks)
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    # The extraction stage itself never ran: no extraction run exists for this source.
    assert not _extraction_runs(ctx, registered.source.id)


def _extraction_runs(ctx: AppContext, source_id: str) -> list:
    """Every EXTRACTION-stage run that consumed one of this source's objects."""
    found: list = []
    object_ids = {obj.id for obj in ctx.repo.list_source_objects(source_id)}
    for object_id in object_ids:
        for run in ctx.repo.list_runs_with_input(object_id, RunStage.EXTRACTION):
            if run not in found:
                found.append(run)
    return found


def test_restricted_source_denies_extraction_before_decoding(
    ctx: AppContext, tmp_path: Path
) -> None:
    # `restricted` allows INGEST, default-denies READ_RAW and EXTRACT: the content is
    # stored, never read and never turned into a hypothesis.
    registered = _wordlist_source(
        ctx, tmp_path, "wl-restricted", mode="restricted", access_class="restricted"
    )
    # INGEST always precedes origin work, so it is done here and the denial is measured
    # against the state ingestion already produced.
    ingest_source(ctx, registered.source.id)
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied) as failure:
        _extract(ctx, registered.source.id)

    assert failure.value.source_id == registered.source.id
    assert failure.value.operation is Operation.EXTRACT
    assert failure.value.decision is PolicyDecision.DENY
    # One audit event and nothing else: no extraction run, no artifact, no lineage edge and
    # no byte read of the stored object.
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    assert not _extraction_runs(ctx, registered.source.id)


def test_review_required_source_denies_extraction(ctx: AppContext, tmp_path: Path) -> None:
    registered = _wordlist_source(
        ctx, tmp_path, "wl-review", mode="review_required", access_class="community"
    )
    ingest_source(ctx, registered.source.id)
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied) as failure:
        _extract(ctx, registered.source.id)

    assert failure.value.decision is PolicyDecision.REVIEW_REQUIRED
    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    assert not _extraction_runs(ctx, registered.source.id)


def test_revoked_source_denies_ingestion_and_is_never_reingested(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _wordlist_source(ctx, tmp_path, "wl-revoked")
    _revoke(ctx, registered.source.id)
    before = state_counts(ctx)

    with pytest.raises(PolicyDenied):
        _extract(ctx, registered.source.id)

    assert state_counts(ctx) == {**before, "audit": before["audit"] + 1}
    # A revoked source stays revoked: no ingestion run, no new blob, no status change.
    assert ctx.repo.get_source(registered.source.id).status is SourceStatus.REVOKED
    assert ctx.repo.count_raw_blobs() == before["blobs"]


def test_a_non_wordlist_source_is_unsupported(ctx: AppContext, tmp_path: Path) -> None:
    write_origin_file(tmp_path, "texts/a.txt", b"kanu\n")
    data = manifest_data(
        key="not-a-wordlist", objects=[{"path": "texts/a.txt", "media_type": "text/plain"}]
    )
    data["source_type"] = SourceType.MONOLINGUAL_TEXT.value
    data["languages"] = ["qaa"]
    registered = register_source(ctx, write_manifest(tmp_path, data, name="not-a-wordlist.yaml"))
    before = state_counts(ctx)

    with pytest.raises(UnsupportedSource):
        _extract(ctx, registered.source.id)

    assert state_counts(ctx) == before


def _revoke(ctx: AppContext, source_id: str) -> None:
    with ctx.repo.transaction():
        ctx.repo.set_source_status(source_id, SourceStatus.REVOKED, ctx.clock())


# --- integrity and immutability ---------------------------------------------------


def test_a_mismatched_stored_digest_fails_integrity(ctx: AppContext, tmp_path: Path) -> None:
    # Rewriting the immutable store breaks the registered sha256: the extraction fails with
    # the typed integrity error and never decodes the tampered content.
    registered = _wordlist_source(ctx, tmp_path, "wl-mismatch")
    object_ = ctx.repo.list_source_objects(registered.source.id)[0]
    # INGEST is this extractor's first step, so the store is populated before the tamper.
    ingest_source(ctx, registered.source.id)
    tampered = b"qaa\tpor\ntampered\tstore\n"
    path = ctx.raw_store.path_for(object_.sha256)
    os.chmod(path, 0o644)
    path.write_bytes(tampered)

    with pytest.raises(HashMismatch):
        _extract(ctx, registered.source.id)

    assert object_.sha256 == sha256_bytes(WORDLIST_BYTES)
    assert path.read_bytes() == tampered
    # No extraction run was written: the failure precedes every semantic write.
    assert not _extraction_runs(ctx, registered.source.id)


def test_raw_bytes_remain_unchanged_and_are_never_logged(
    ctx: AppContext, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The bytes the adapter induced from are exactly the registered object's bytes, and
    # neither the success path nor a failure path logs or reports source content.
    caplog.set_level(logging.DEBUG, logger="langpipe")
    registered = _wordlist_source(ctx, tmp_path, "wl-raw")
    object_ = ctx.repo.list_source_objects(registered.source.id)[0]

    result = _extract(ctx, registered.source.id)

    ctx.raw_store.verify(object_.sha256)
    assert ctx.raw_store.read_bytes(object_.sha256) == WORDLIST_BYTES
    payload = json.loads(ctx.artifact_store.read_bytes(result.report.sha256))
    assert payload["objects"][0]["sha256"] == object_.sha256
    assert payload["objects"][0]["size_bytes"] == len(WORDLIST_BYTES)
    for output in (caplog.text, json.dumps(payload)):
        assert SENTINEL_HEADWORD not in output
        assert SENTINEL_GLOSS not in output
    # A denied extraction logs identifiers and the decision only. `qaa` names the target
    # language, so it can never also name a translation language (Invariant 9).
    with pytest.raises(SchemaViolation):
        _extract(ctx, registered.source.id, contact_language="qaa")
    assert SENTINEL_HEADWORD not in caplog.text
    assert SENTINEL_GLOSS not in caplog.text


def test_the_report_carries_only_identifiers_digests_and_counts(
    ctx: AppContext, tmp_path: Path
) -> None:
    registered = _wordlist_source(ctx, tmp_path, "wl-report")

    result = _extract(ctx, registered.source.key)

    payload = json.loads(ctx.artifact_store.read_bytes(result.report.sha256))
    assert payload["schema"] == "wordlist-extraction-report"
    assert payload["source_id"] == registered.source.id
    assert payload["run_id"] == result.run.id
    assert payload["target_language"] == "qaa"
    assert payload["contact_language"] == "por"
    assert payload["totals"] == {
        "lexemes": 4,
        "senses": 5,
        "form_links": 0,
        "evidence_items": 5,
        "lineage_edges": 33,
    }
    assert set(payload) == {
        "schema",
        "schema_version",
        "source_id",
        "run_id",
        "target_language",
        "contact_language",
        "objects",
        "totals",
    }


def test_the_report_artifact_is_classified_and_sized(ctx: AppContext, tmp_path: Path) -> None:
    registered = _wordlist_source(ctx, tmp_path, "wl-artifact")

    result = _extract(ctx, registered.source.key)

    stored = ctx.artifact_store.read_bytes(result.report.sha256)
    assert result.report.media_type == "application/json"
    assert result.report.schema_name == "wordlist-extraction-report"
    assert result.report.schema_version == 1
    assert result.report.size_bytes == len(stored)
    assert result.report.access_class == "public"
    assert ctx.repo.entity_type_of(result.report.id) is EntityType.ARTIFACT
