"""ScriptureEarth package adapter: inspect a hand-acquired directory and build a manifest.

The adapter never downloads, registers or ingests. It scans a local directory the operator
acquired by hand and writes a standard ``SourceManifest`` YAML; the operator then runs the
M1 ``source add``/``source ingest`` path unchanged. Policy is operator-supplied, never invented
here (WP2.12).
"""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from langpipe.domain.enums import SourceType
from langpipe.domain.errors import SchemaViolation, SourceConflict, UnsupportedSource
from langpipe.domain.models.source import ObjectSpec, PolicySpec, Provenance, SourceManifest

SE_MEDIA_USFM = "text/x-usfm"
SE_MEDIA_TIMING = "text/x-sab-timing"
MANIFEST_FILENAME = "langpipe-manifest.yaml"
_ACQUIRED_FROM_HOST = "www.scriptureearth.org"
_USFM_SUFFIXES = frozenset({".usfm", ".sfm"})


@dataclass(frozen=True)
class ScriptureEarthPackage:
    root: Path
    usfm_files: tuple[Path, ...]
    timing_files: tuple[Path, ...]
    pkf_files: tuple[Path, ...]


def scan_package(root: Path) -> ScriptureEarthPackage:
    """Recursively scan ``root`` for USFM, timing and Proskomma files.

    USFM files (``*.usfm``/``*.sfm``, case-insensitive) are required; a package with only
    ``.pkf`` files raises ``UnsupportedSource("pkf_not_supported")`` and one with neither
    raises ``UnsupportedSource("no_usfm_files")``. Symlinks are not followed and paths are
    sorted by their relative POSIX path.
    """
    if root.is_symlink():
        raise UnsupportedSource("no_usfm_files")
    usfm: list[Path] = []
    timing: list[Path] = []
    pkf: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if not (Path(dirpath) / name).is_symlink())
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            suffix = path.suffix.lower()
            if suffix in _USFM_SUFFIXES:
                usfm.append(path)
            elif name.lower().endswith(".timing.txt"):
                timing.append(path)
            elif suffix == ".pkf":
                pkf.append(path)

    if not usfm:
        if pkf:
            raise UnsupportedSource("pkf_not_supported")
        raise UnsupportedSource("no_usfm_files")

    usfm.sort(key=lambda path: path.relative_to(root).as_posix())
    timing.sort(key=lambda path: path.relative_to(root).as_posix())
    pkf.sort(key=lambda path: path.relative_to(root).as_posix())
    return ScriptureEarthPackage(
        root=root,
        usfm_files=tuple(usfm),
        timing_files=tuple(timing),
        pkf_files=tuple(pkf),
    )


def build_manifest(
    pkg: ScriptureEarthPackage,
    *,
    key: str,
    language: str,
    policy: PolicySpec | None,
    provenance: Provenance,
    acquired_at: datetime,
    include_timing: bool = False,
    title: str | None = None,
) -> SourceManifest:
    """Build a standard ``SourceManifest`` for a scanned ScriptureEarth package.

    ``provenance`` is validated here: ``acquired_from`` must be an ``https`` URL on
    ``www.scriptureearth.org`` (no credentials, no non-default port). A missing rights holder
    is allowed and recorded as absent (ADR-0025: licences and ownership are metadata, not
    gates). The policy is never invented by this code: ``None`` leaves the manifest without a
    policy, so registration applies the repository default.
    """
    _check_provenance(provenance)

    objects: list[ObjectSpec] = [
        ObjectSpec(path=path.relative_to(pkg.root).as_posix(), media_type=SE_MEDIA_USFM)
        for path in pkg.usfm_files
    ]
    if include_timing:
        objects.extend(
            ObjectSpec(path=path.relative_to(pkg.root).as_posix(), media_type=SE_MEDIA_TIMING)
            for path in pkg.timing_files
        )
    objects.sort(key=lambda spec: spec.path)

    return SourceManifest(
        manifest_version=1,
        key=key,
        title=title if title else f"ScriptureEarth {language}",
        source_type=SourceType.PUBLICATION,
        languages=[language],
        provenance=provenance,
        acquired_at=acquired_at,
        domains=["religious"],
        registers=["religious"],
        policy=policy,
        objects=objects,
    )


def write_manifest(m: SourceManifest, path: Path) -> None:
    """Write ``m`` as canonical YAML; refuse to overwrite a different existing file.

    Writing the same manifest again is a no-op. A different existing file raises
    ``SourceConflict`` so a reviewed manifest is never silently replaced. Symlinks
    (including dangling ones) are refused with ``SourceConflict``.
    """
    if path.is_symlink():
        raise SourceConflict(m.key)
    text = yaml.safe_dump(m.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    try:
        # Exclusive creation prevents race conditions and following symlinks
        with path.open("x", encoding="utf-8") as f:
            f.write(text)
        return
    except FileExistsError:
        pass

    try:
        existing = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise SourceConflict(m.key) from None
    if existing != text:
        raise SourceConflict(m.key)


def _check_provenance(provenance: Provenance) -> None:
    # ADR-0025: a missing rights holder is recorded as unknown, not rejected.
    _check_acquired_from(provenance.acquired_from)


def _check_acquired_from(uri: str) -> None:
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        raise SchemaViolation() from None
    if parts.scheme != "https":
        raise SchemaViolation()
    if parts.hostname != _ACQUIRED_FROM_HOST:
        raise SchemaViolation()
    if parts.username is not None or parts.password is not None:
        raise SchemaViolation()
    if port not in (None, 443):
        raise SchemaViolation()
