"""WP2.12: ScriptureEarth package adapter (manifest builder). Synthetic tmp dirs only."""

import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from langpipe.domain.enums import AccessClass, Operation, PolicyMode, SourceType
from langpipe.domain.errors import SchemaViolation, SourceConflict, UnsupportedSource
from langpipe.domain.models.source import PolicySpec, Provenance, SourceManifest
from langpipe.ingestion.adapters.scriptureearth import (
    SE_MEDIA_TIMING,
    SE_MEDIA_USFM,
    ScriptureEarthPackage,
    build_manifest,
    scan_package,
    write_manifest,
)
from langpipe.ingestion.registration import load_manifest

ACQUIRED_FROM = "https://www.scriptureearth.org/00por.php?iso=mzr"
ACQUIRED_AT = datetime(2026, 1, 1, tzinfo=UTC)
MANIFEST_NAME = "langpipe-manifest.yaml"


def _package(tmp_path: Path, *relative_paths: str) -> Path:
    root = tmp_path / "pkg"
    root.mkdir()
    for rel in relative_paths:
        file = root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("\\id RUT\n", encoding="utf-8")
    return root


def _policy() -> PolicySpec:
    return PolicySpec(
        mode=PolicyMode.DISTILL_ONLY,
        access_class=AccessClass.COMMUNITY,
        authority="Marubo governance authority (test)",
        allow=[
            Operation.ALIGN,
            Operation.DISTILL_LEXICON,
            Operation.DISTILL_MORPHOLOGY,
            Operation.AUDIO_ALIGN,
        ],
        deny=[
            Operation.SYNTHETIC_GENERATION_SUPPORT,
            Operation.THIRD_PARTY_API,
            Operation.CLOUD_PROCESSING,
            Operation.REDISTRIBUTE_RAW,
            Operation.REDISTRIBUTE_DERIVED,
        ],
    )


def _provenance(rights_holder: str | None = "Marubo community") -> Provenance:
    return Provenance(acquired_from=ACQUIRED_FROM, rights_holder=rights_holder)


def _build(root: Path, **overrides: object) -> SourceManifest:
    kwargs: dict[str, object] = {
        "key": "se-mzr",
        "language": "mzr",
        "policy": _policy(),
        "provenance": _provenance(),
        "acquired_at": ACQUIRED_AT,
    }
    kwargs.update(overrides)
    return build_manifest(scan_package(root), **kwargs)  # type: ignore[arg-type]


def _relative_paths(pkg: ScriptureEarthPackage) -> list[str]:
    return [p.relative_to(pkg.root).as_posix() for p in pkg.usfm_files]


def test_scan_finds_usfm_timing_pkf_sorted(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        "a.usfm",
        "b.sfm",
        "sub/c.SFM",
        "timing/C01-ACT.timing.txt",
        "z.pkf",
        "readme.txt",
    )

    pkg = scan_package(root)

    assert _relative_paths(pkg) == ["a.usfm", "b.sfm", "sub/c.SFM"]
    assert [p.name for p in pkg.timing_files] == ["C01-ACT.timing.txt"]
    assert [p.name for p in pkg.pkf_files] == ["z.pkf"]
    assert pkg.root == root


def test_scan_does_not_follow_symlinks(tmp_path: Path) -> None:
    root = _package(tmp_path, "real.usfm", "real_dir/d.usfm")
    (root / "link.usfm").symlink_to(root / "real.usfm")
    (root / "linked").symlink_to(root / "real_dir", target_is_directory=True)

    pkg = scan_package(root)

    assert _relative_paths(pkg) == ["real.usfm", "real_dir/d.usfm"]


def test_pkf_only_package_unsupported(tmp_path: Path) -> None:
    root = _package(tmp_path, "only.pkf", "also.pkf")

    with pytest.raises(UnsupportedSource) as excinfo:
        scan_package(root)

    assert excinfo.value.reason == "pkf_not_supported"


def test_no_usfm_and_no_pkf_is_no_usfm_files(tmp_path: Path) -> None:
    root = _package(tmp_path, "notes.txt")

    with pytest.raises(UnsupportedSource) as excinfo:
        scan_package(root)

    assert excinfo.value.reason == "no_usfm_files"


def test_manifest_validates_and_roundtrips_through_load_manifest(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm", "sub/b.sfm")
    manifest = _build(root)

    path = root / MANIFEST_NAME
    write_manifest(manifest, path)

    assert load_manifest(path) == manifest


def test_manifest_fields(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm")
    manifest = _build(root)

    assert manifest.manifest_version == 1
    assert manifest.source_type is SourceType.PUBLICATION
    assert manifest.languages == ["mzr"]
    assert manifest.domains == ["religious"]
    assert manifest.registers == ["religious"]
    assert manifest.title == "ScriptureEarth mzr"
    assert [o.media_type for o in manifest.objects] == [SE_MEDIA_USFM]
    assert manifest.objects[0].access_class is None


def test_manifest_title_override(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm")
    manifest = _build(root, title="Marubo New Testament")

    assert manifest.title == "Marubo New Testament"


def test_manifest_paths_relative_and_inside_root(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm", "sub/deeper/b.sfm")
    manifest = _build(root, include_timing=True)
    resolved_root = root.resolve()

    for obj in manifest.objects:
        assert not obj.path.startswith("/")
        assert "\\" not in obj.path
        assert ".." not in obj.path.split("/")
        assert (root / obj.path).resolve().is_relative_to(resolved_root)


def test_timing_files_excluded_by_default(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm", "C01-ACT.timing.txt")

    default = _build(root)
    assert [o.media_type for o in default.objects] == [SE_MEDIA_USFM]

    with_timing = _build(root, include_timing=True)
    media_types = [o.media_type for o in with_timing.objects]
    assert SE_MEDIA_TIMING in media_types
    assert media_types == [SE_MEDIA_TIMING, SE_MEDIA_USFM]


def test_rights_holder_is_optional(tmp_path: Path) -> None:
    # ADR-0025: ownership is a record, not a manifest-build gate.
    root = _package(tmp_path, "a.usfm")

    manifest = _build(root, provenance=_provenance(rights_holder=None))

    assert manifest.provenance.rights_holder is None


@pytest.mark.parametrize(
    "acquired_from",
    [
        "http://www.scriptureearth.org/x",
        "https://scriptureearth.org/x",
        "https://www.scriptureearth.org:8443/x",
        "https://www.scriptureearth.org:abc/x",
        "https://www.scriptureearth.org:65536/x",
        "https://[www.scriptureearth.org/x",
        "https://user:pass@www.scriptureearth.org/x",
        "https://example.org/x",
    ],
)
def test_acquired_from_must_be_scriptureearth_https(tmp_path: Path, acquired_from: str) -> None:
    root = _package(tmp_path, "a.usfm")
    provenance = Provenance(acquired_from=acquired_from, rights_holder="Marubo community")

    with pytest.raises(SchemaViolation):
        _build(root, provenance=provenance)


def test_acquired_from_default_port_allowed(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm")
    provenance = Provenance(
        acquired_from="https://www.scriptureearth.org:443/00por.php?iso=mzr",
        rights_holder="Marubo community",
    )

    manifest = _build(root, provenance=provenance)

    assert manifest.provenance.rights_holder == "Marubo community"


def test_write_manifest_refuses_conflicting_overwrite(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm")
    path = root / MANIFEST_NAME
    manifest = _build(root)
    write_manifest(manifest, path)
    original = path.read_text(encoding="utf-8")

    write_manifest(manifest, path)
    assert path.read_text(encoding="utf-8") == original

    different = _build(root, title="Some other title")
    with pytest.raises(SourceConflict):
        write_manifest(different, path)
    assert path.read_text(encoding="utf-8") == original


def test_adapter_never_opens_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", _boom)

    root = _package(tmp_path, "a.usfm", "C01-ACT.timing.txt")
    manifest = _build(root, include_timing=True)
    write_manifest(manifest, root / MANIFEST_NAME)

    assert load_manifest(root / MANIFEST_NAME) == manifest


def test_scan_package_rejects_symlink_root(tmp_path: Path) -> None:
    real_target = _package(tmp_path, "a.usfm")
    link_root = tmp_path / "link_pkg"
    link_root.symlink_to(real_target)

    with pytest.raises(UnsupportedSource) as err:
        scan_package(link_root)
    assert err.value.reason == "no_usfm_files"


def test_write_manifest_refuses_dangling_symlink_destination(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm")
    manifest = _build(root)
    dest = root / MANIFEST_NAME
    outside = tmp_path / "outside.yaml"
    dest.symlink_to(outside)

    with pytest.raises(SourceConflict):
        write_manifest(manifest, dest)

    assert not outside.exists()
    assert dest.is_symlink()


def test_write_manifest_refuses_existing_file_symlink_destination(tmp_path: Path) -> None:
    root = _package(tmp_path, "a.usfm")
    manifest = _build(root)
    dest = root / MANIFEST_NAME
    outside = tmp_path / "outside.yaml"
    outside.write_text("existing content", encoding="utf-8")
    dest.symlink_to(outside)

    with pytest.raises(SourceConflict):
        write_manifest(manifest, dest)

    assert outside.read_text(encoding="utf-8") == "existing content"
    assert dest.is_symlink()
