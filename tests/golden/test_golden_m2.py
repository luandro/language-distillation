"""M2 golden fixture: synthetic corpus through extraction, normalization and tokenization.

Runs on both backends through the ``ctx`` fixture (docs/GOLDEN-FIXTURE.md). Expected M2 snapshots
live in ``expected/m2/``; the M1 snapshots in ``expected/m1/`` must stay byte-for-byte unchanged.
"""

import difflib
import json
import os
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType
from langpipe.domain.errors import ExtractionFailed, PolicyDenied, UnsupportedSource
from langpipe.extraction.registry import EXTRACTORS
from langpipe.extraction.service import extract_source
from langpipe.ingestion.ingest import IngestResult, ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.languages.base import LANGUAGE_PROFILES, NORMALIZATION_PROFILES, TOKENIZERS
from langpipe.normalization.service import normalize_extraction
from langpipe.tokenization.service import tokenize_normalization
from tests.golden.normalize import (
    M2SourceState,
    check_form_identity,
    m2_form_identity,
    normalize_m2_snapshot,
    normalize_snapshot,
)
from tests.service.manifests import manifest_data, state_counts, write_manifest, write_origin_file

GOLDEN_DIR = Path(__file__).parent
FIXTURE_SOURCES = GOLDEN_DIR / "fixture" / "sources"
EXPECTED_DIR = GOLDEN_DIR / "expected" / "m2"
M1_EXPECTED_DIR = GOLDEN_DIR / "expected" / "m1"
UPDATE_ENV = "LANGPIPE_UPDATE_GOLDEN"
UPDATE_MESSAGE = "golden files rewritten; review the diff and commit intentionally"

EXTRACTABLE_DIRS = (
    "01-parallel-distill",
    "02-educational-direct",
    "05-monolingual",
)
INGESTED_DIRS = (
    "01-parallel-distill",
    "02-educational-direct",
    "03-wordlist",
    "04-igt",
    "05-monolingual",
)
MALFORMED_DIR = "03-wordlist"
DENIED_DIRS = ("04-igt", "06-excluded")
EXCLUDED_DIR = "06-excluded"


def _run_m1(ctx: AppContext) -> tuple[list[RegistrationResult], list[IngestResult]]:
    """Registration plus ingestion only, in the M1 fixture order."""
    registrations: list[RegistrationResult] = []
    ingestions: list[IngestResult] = []
    for dirname in INGESTED_DIRS:
        registration = register_source(ctx, FIXTURE_SOURCES / dirname / "manifest.yaml")
        registrations.append(registration)
        ingestions.append(ingest_source(ctx, registration.source.key))
    registrations.append(register_source(ctx, FIXTURE_SOURCES / EXCLUDED_DIR / "manifest.yaml"))
    return registrations, ingestions


def _run_m2(
    ctx: AppContext,
) -> tuple[dict[str, RegistrationResult], dict[str, IngestResult], list[M2SourceState]]:
    registrations = {
        dirname: register_source(ctx, FIXTURE_SOURCES / dirname / "manifest.yaml")
        for dirname in INGESTED_DIRS
    }
    registrations[EXCLUDED_DIR] = register_source(
        ctx, FIXTURE_SOURCES / EXCLUDED_DIR / "manifest.yaml"
    )
    ingestions = {
        dirname: ingest_source(ctx, registrations[dirname].source.key) for dirname in INGESTED_DIRS
    }

    states: list[M2SourceState] = []
    for dirname in EXTRACTABLE_DIRS:
        registration = registrations[dirname]
        extraction = extract_source(ctx, registration.source.id)
        normalization = normalize_extraction(ctx, extraction.run.id)
        tokenization = tokenize_normalization(ctx, normalization.run.id)
        states.append(
            M2SourceState(
                key=dirname,
                registration=registration,
                ingestion=ingestions[dirname],
                extraction=extraction,
                normalization=normalization,
                tokenization=tokenization,
            )
        )
    return registrations, ingestions, states


def _diff(name: str, expected: object, actual: object) -> str:
    before = json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    after = json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    return "\n".join(
        difflib.unified_diff(
            before, after, f"expected/m2/{name}.json", f"actual/m2/{name}.json", lineterm=""
        )
    )


def _write_expected(snapshot: dict[str, object]) -> None:
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    for name, value in snapshot.items():
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (EXPECTED_DIR / f"{name}.json").write_text(text, encoding="utf-8")


def test_golden_m2_snapshot(ctx: AppContext) -> None:
    _, _, states = _run_m2(ctx)
    snapshot = normalize_m2_snapshot(ctx, states)

    if os.environ.get(UPDATE_ENV) == "1":
        _write_expected(snapshot)
        pytest.fail(UPDATE_MESSAGE)

    for name, actual in snapshot.items():
        expected = json.loads((EXPECTED_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert actual == expected, _diff(name, expected, actual)


def test_golden_m2_rerun_creates_no_duplicates(ctx: AppContext) -> None:
    _, _, first_states = _run_m2(ctx)
    before = normalize_m2_snapshot(ctx, first_states)
    counts_before = state_counts(ctx)

    second_registrations, second_ingestions, second_states = _run_m2(ctx)

    assert all(item.reused for item in second_registrations.values())
    assert all(item.reused for item in second_ingestions.values())
    assert all(
        state.extraction.reused and state.normalization.reused and state.tokenization.reused
        for state in second_states
    )
    assert normalize_m2_snapshot(ctx, second_states) == before
    assert state_counts(ctx) == counts_before


def test_golden_m2_form_identity(ctx: AppContext) -> None:
    _, _, states = _run_m2(ctx)
    keys_to_ids = m2_form_identity(ctx, states)

    assert ctx.repo.count(EntityType.FORM) == 25
    assert len(keys_to_ids) == 25
    assert all(len(ids) == 1 for ids in keys_to_ids.values())

    profile = "default_text@0.1.0"

    def form_id(text: str) -> str:
        ids = keys_to_ids[("qaa", profile, text)]
        assert len(ids) == 1
        return next(iter(ids))

    kanu = form_id("kanu")
    kanu_acute = form_id("kanú")
    mabi = form_id("mabi")
    assert len({kanu, kanu_acute, mabi}) == 3

    attestations: dict[str, set[str]] = {}
    for state in states:
        for segment in ctx.repo.list_segments_for_run(state.normalization.run.id):
            for token in ctx.repo.list_tokens(segment.id):
                if token.form_id is not None:
                    attestations.setdefault(token.form_id, set()).add(state.key)

    assert attestations[kanu] == {"01-parallel-distill", "05-monolingual"}
    assert attestations[mabi] == {
        "01-parallel-distill",
        "02-educational-direct",
        "05-monolingual",
    }
    assert attestations[kanu_acute] == {"02-educational-direct", "05-monolingual"}

    # The NFD line in 05 shares the NFC Form created from 02's precomposed kanú.
    nfd = [
        token
        for state in states
        for segment in ctx.repo.list_segments_for_run(state.normalization.run.id)
        for token in ctx.repo.list_tokens(segment.id)
        if token.normalized_surface == "kanú" and token.raw_surface != token.normalized_surface
    ]
    assert nfd, "the NFD kanú token must exist"
    assert all(token.form_id == kanu_acute for token in nfd)


def test_form_identity_rejects_two_ids_for_one_key() -> None:
    key = ("qaa", "default_text@0.1.0", "kanu")
    with pytest.raises(AssertionError):
        check_form_identity([(key, "form:one"), (key, "form:two")], form_count=2)


def test_form_identity_rejects_count_mismatch() -> None:
    key = ("qaa", "default_text@0.1.0", "kanu")
    with pytest.raises(AssertionError):
        check_form_identity([(key, "form:one")], form_count=2)


def test_golden_m2_wordlist_03_is_malformed(ctx: AppContext) -> None:
    # WP2.3 pins golden 03 as a ragged row (test_tsv_golden_wordlist_03_is_malformed_row_two).
    # Its bytes stay unmodified because M1 golden pins the object sha256, so 03 cannot enter the
    # M2 pipeline; WP2.14's "01, 02, 03, 05" list conflicts with the merged WP2.3 behavior.
    registrations, _, _ = _run_m2(ctx)
    with pytest.raises(ExtractionFailed) as info:
        extract_source(ctx, registrations[MALFORMED_DIR].source.id)

    assert info.value.code == "tsv_ragged_row"


def test_golden_m2_denied_sources(ctx: AppContext) -> None:
    # review_required (04) and exclude (06) block extraction before any format selection.
    registrations, _, _ = _run_m2(ctx)
    for dirname in DENIED_DIRS:
        with pytest.raises(PolicyDenied):
            extract_source(ctx, registrations[dirname].source.id)


def test_golden_m2_igt_source_is_unsupported(ctx: AppContext, tmp_path: Path) -> None:
    # An EXTRACT-allowed synthetic IGT source still has no M2 extractor; an override cannot lift it.
    write_origin_file(tmp_path, "igt.txt", b"\\id QAA\n\\c 1\n\\v 1 kanu mabi\n")
    data = manifest_data(
        key="igt-allowed",
        mode="direct",
        objects=[{"path": "igt.txt", "media_type": "text/plain"}],
    )
    data["source_type"] = "igt"
    data["languages"] = ["qaa"]
    registered = register_source(ctx, write_manifest(tmp_path, data))
    ingest_source(ctx, registered.source.key)

    with pytest.raises(UnsupportedSource) as info:
        extract_source(ctx, registered.source.id, extractor="tsv@0.1.0")

    assert info.value.reason == "no_extractor"


def test_golden_m2_m1_snapshot_unchanged(ctx: AppContext) -> None:
    registrations, ingestions = _run_m1(ctx)
    snapshot = normalize_snapshot(ctx, registrations, ingestions)

    for name, actual in snapshot.items():
        expected = json.loads((M1_EXPECTED_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert actual == expected, _diff(name, expected, actual)


def test_registered_component_versions_are_pinned() -> None:
    # A behavior change requires a version bump: editing this list is the deliberate step.
    assert EXTRACTORS.names() == [
        "plain_lines@0.1.0",
        "tsv@0.1.0",
        "tsv_sentences@0.1.0",
        "usfm@0.1.0",
    ]
    assert NORMALIZATION_PROFILES.names() == [
        "default_text@0.1.0",
        "marubo_standard@0.1.0",
        "unicode_nfc@1.0.0",
    ]
    assert TOKENIZERS.names() == ["marubo_pilot@0.1.0", "whitespace_punct@0.1.0"]
    assert sorted(LANGUAGE_PROFILES) == ["mzr"]
    profile = LANGUAGE_PROFILES["mzr"]
    assert (
        profile.language,
        profile.name,
        profile.version,
        profile.normalization,
        profile.tokenizer,
    ) == ("mzr", "mzr_pilot", "0.1.0", "marubo_standard@0.1.0", "marubo_pilot@0.1.0")
