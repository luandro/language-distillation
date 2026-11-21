"""M1 golden fixture: synthetic corpus through registration and ingestion (docs/GOLDEN-FIXTURE.md).

Runs on both backends through the `ctx` fixture. Snapshot files live in expected/m1/.
"""

import difflib
import json
import os
import unicodedata
from pathlib import Path

import pytest

from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType, Operation, PolicyDecision, PolicyMode
from langpipe.domain.errors import PolicyDenied
from langpipe.governance.policy import resolve
from langpipe.ingestion.ingest import IngestResult, ingest_source
from langpipe.ingestion.registration import RegistrationResult, register_source
from langpipe.lineage.impact import impact_of
from tests.golden.normalize import normalize_snapshot
from tests.service.manifests import state_counts

GOLDEN_DIR = Path(__file__).parent
FIXTURE_SOURCES = GOLDEN_DIR / "fixture" / "sources"
EXPECTED_DIR = GOLDEN_DIR / "expected" / "m1"
UPDATE_ENV = "LANGPIPE_UPDATE_GOLDEN"
UPDATE_MESSAGE = "golden files rewritten; review the diff and commit intentionally"
INGESTED_DIRS = (
    "01-parallel-distill",
    "02-educational-direct",
    "03-wordlist",
    "04-igt",
    "05-monolingual",
)
EXCLUDED_DIR = "06-excluded"
ALL_KEYS = (*INGESTED_DIRS, EXCLUDED_DIR)


def _run_fixture(ctx: AppContext) -> tuple[list[RegistrationResult], list[IngestResult]]:
    registrations: list[RegistrationResult] = []
    ingestions: list[IngestResult] = []
    for dirname in INGESTED_DIRS:
        registration = register_source(ctx, FIXTURE_SOURCES / dirname / "manifest.yaml")
        registrations.append(registration)
        ingestions.append(ingest_source(ctx, registration.source.key))
    registrations.append(register_source(ctx, FIXTURE_SOURCES / EXCLUDED_DIR / "manifest.yaml"))
    return registrations, ingestions


def _by_key(
    registrations: list[RegistrationResult], ingestions: list[IngestResult]
) -> tuple[dict[str, RegistrationResult], dict[str, IngestResult]]:
    return (
        {item.source.key: item for item in registrations},
        {item.source.key: item for item in ingestions},
    )


def _diff(name: str, expected: object, actual: object) -> str:
    before = json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    after = json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
    return "\n".join(
        difflib.unified_diff(
            before, after, f"expected/m1/{name}.json", f"actual/m1/{name}.json", lineterm=""
        )
    )


def _write_expected(snapshot: dict[str, object]) -> None:
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    for name, value in snapshot.items():
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (EXPECTED_DIR / f"{name}.json").write_text(text, encoding="utf-8")


def test_golden_m1_snapshot(ctx: AppContext) -> None:
    registrations, ingestions = _run_fixture(ctx)
    snapshot = normalize_snapshot(ctx, registrations, ingestions)

    if os.environ.get(UPDATE_ENV) == "1":
        _write_expected(snapshot)
        pytest.fail(UPDATE_MESSAGE)

    for name, actual in snapshot.items():
        expected = json.loads((EXPECTED_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert actual == expected, _diff(name, expected, actual)


def test_golden_m1_rerun_creates_no_duplicates(ctx: AppContext) -> None:
    first_registrations, first_ingestions = _run_fixture(ctx)
    before = normalize_snapshot(ctx, first_registrations, first_ingestions)
    counts_before = state_counts(ctx)

    second_registrations, second_ingestions = _run_fixture(ctx)

    assert all(item.reused for item in second_registrations)
    assert all(item.reused for item in second_ingestions)
    assert normalize_snapshot(ctx, second_registrations, second_ingestions) == before
    assert state_counts(ctx) == counts_before


def test_golden_distill_only_source_is_trainable_but_not_redistributable(ctx: AppContext) -> None:
    # ADR-0025: distill_only no longer blocks training; raw redistribution stays closed.
    registrations, ingestions = _run_fixture(ctx)
    by_key, _ = _by_key(registrations, ingestions)
    policy = ctx.repo.get_policy(by_key["01-parallel-distill"].source.policy_id)

    assert by_key["01-parallel-distill"].policy.mode is PolicyMode.DISTILL_ONLY
    assert resolve(policy, Operation.DIRECT_TRAINING) is PolicyDecision.ALLOW
    assert resolve(policy, Operation.REDISTRIBUTE_RAW) is PolicyDecision.DENY

    eligibility = normalize_snapshot(ctx, registrations, ingestions)["eligibility"]
    assert isinstance(eligibility, dict)
    assert eligibility["src:01-parallel-distill"] == {
        "direct_training": "allow",
        "synthetic_generation_support": "allow",
        "third_party_api": "deny",
    }
    assert set(eligibility) == {f"src:{key}" for key in ALL_KEYS}


def test_golden_excluded_source_not_ingested(ctx: AppContext) -> None:
    registration = register_source(ctx, FIXTURE_SOURCES / EXCLUDED_DIR / "manifest.yaml")
    runs_after_registration = ctx.repo.count_runs()

    assert registration.policy.mode is PolicyMode.EXCLUDE
    assert registration.objects == ()
    with pytest.raises(PolicyDenied):
        ingest_source(ctx, EXCLUDED_DIR)

    assert ctx.repo.count(EntityType.SOURCE_OBJECT) == 0
    assert ctx.repo.count_raw_blobs() == 0
    assert ctx.repo.count_runs() == runs_after_registration


def test_golden_lineage_impact_from_source(ctx: AppContext) -> None:
    registrations, ingestions = _run_fixture(ctx)
    by_key, ingested = _by_key(registrations, ingestions)
    source = by_key["01-parallel-distill"].source
    report = ingested["01-parallel-distill"].report
    assert report is not None

    expected = {(obj.id, EntityType.SOURCE_OBJECT) for obj in by_key["01-parallel-distill"].objects}
    expected.add((report.id, EntityType.ARTIFACT))
    impact = {(entry.object_id, entry.entity_type) for entry in impact_of(ctx.repo, source.id)}

    assert impact == expected


def test_golden_fixture_text_normalization() -> None:
    # Every fixture file is NFC except the one deliberate NFD line in 05-monolingual (for M2).
    nfd_lines = []
    for path in sorted(FIXTURE_SOURCES.rglob("*")):
        if not path.is_file() or path.suffix == ".yaml":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not unicodedata.is_normalized("NFC", line):
                nfd_lines.append(path.relative_to(FIXTURE_SOURCES).as_posix())
    assert nfd_lines == ["05-monolingual/text.txt"]
