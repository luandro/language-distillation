"""CLI `scriptureearth manifest`: build a manifest for a hand-acquired package (WP2.12/2.13)."""

from pathlib import Path

import yaml
from typer.testing import CliRunner

from langpipe.cli.app import app
from langpipe.domain.enums import PolicyMode, SourceType
from langpipe.ingestion.adapters.scriptureearth import MANIFEST_FILENAME
from langpipe.ingestion.registration import load_manifest

ACQUIRED_FROM = "https://www.scriptureearth.org/00por.php?iso=mzr"
ACQUIRED_AT = "2026-01-01T00:00:00+00:00"
POLICY = {
    "mode": "distill_only",
    "access_class": "community",
    "authority": "test-authority",
    "allow": ["align", "distill_lexicon", "distill_morphology"],
    "deny": [
        "synthetic_generation_support",
        "third_party_api",
        "cloud_processing",
        "redistribute_raw",
        "redistribute_derived",
    ],
}


def _fields(line: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line.split())


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    (package / "usfm").mkdir(parents=True)
    (package / "usfm" / "GEN.usfm").write_text(
        "\\id GEN\n\\c 1\n\\v 1 In the beginning.\n", encoding="utf-8"
    )
    (package / "GEN.timing.txt").write_text("0\t1\n", encoding="utf-8")
    return package


def _policy_file(tmp_path: Path) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(POLICY, sort_keys=False), encoding="utf-8")
    return path


def test_scriptureearth_manifest_command_writes_valid_manifest(tmp_path: Path) -> None:
    package = _package(tmp_path)
    policy = _policy_file(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "scriptureearth",
            "manifest",
            str(package),
            "--key",
            "se-mzr",
            "--language",
            "mzr",
            "--policy",
            str(policy),
            "--acquired-from",
            ACQUIRED_FROM,
            "--rights-holder",
            "Example holder",
            "--acquired-at",
            ACQUIRED_AT,
            "--include-timing",
        ],
    )

    assert result.exit_code == 0, result.output
    fields = _fields(result.stdout.strip())
    manifest_path = Path(fields["manifest_path"])
    assert manifest_path == package / MANIFEST_FILENAME
    assert fields["usfm"] == "1"
    assert fields["timing"] == "1"
    assert fields["pkf_ignored"] == "0"

    loaded = load_manifest(manifest_path)
    assert loaded.key == "se-mzr"
    assert loaded.source_type is SourceType.PUBLICATION
    assert loaded.languages == ["mzr"]
    assert loaded.policy.mode is PolicyMode.DISTILL_ONLY
    assert loaded.provenance.rights_holder == "Example holder"
    assert [obj.path for obj in loaded.objects] == ["GEN.timing.txt", "usfm/GEN.usfm"]


def test_scriptureearth_manifest_policy_and_rights_are_optional(tmp_path: Path) -> None:
    # ADR-0025: policy and rights holder are records, not required gates.
    runner = CliRunner()

    def invoke(case: str, extra: list[str]) -> object:
        case_dir = tmp_path / case
        package = _package(case_dir)
        _policy_file(case_dir)
        common = [
            "scriptureearth",
            "manifest",
            str(package),
            "--key",
            "se-mzr",
            "--language",
            "mzr",
            "--acquired-from",
            ACQUIRED_FROM,
            "--acquired-at",
            ACQUIRED_AT,
        ]
        return runner.invoke(app, [*common, *extra])

    no_policy = invoke("no-policy", ["--rights-holder", "Example holder"])
    assert no_policy.exit_code == 0
    loaded = load_manifest(tmp_path / "no-policy" / "package" / MANIFEST_FILENAME)
    assert loaded.policy is None
    assert loaded.resolved_policy.mode is PolicyMode.DIRECT

    no_rights = invoke("no-rights", ["--policy", str(tmp_path / "no-rights" / "policy.yaml")])
    assert no_rights.exit_code == 0
    loaded = load_manifest(tmp_path / "no-rights" / "package" / MANIFEST_FILENAME)
    assert loaded.provenance.rights_holder is None

    empty_rights = invoke(
        "empty-rights",
        ["--policy", str(tmp_path / "empty-rights" / "policy.yaml"), "--rights-holder", ""],
    )
    assert empty_rights.exit_code == 0
    loaded = load_manifest(tmp_path / "empty-rights" / "package" / MANIFEST_FILENAME)
    assert loaded.provenance.rights_holder is None
