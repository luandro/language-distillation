"""``langpipe scriptureearth manifest``: build a manifest for a hand-acquired package (WP2.12).

The adapter does not download, register or ingest. This command scans a local directory and writes
a standard manifest that the operator then feeds to the M1 ``source add`` path. Policy and rights
are optional records (ADR-0025); when omitted, registration applies the repository default. Nothing
is invented here and no file contents are printed.
"""

from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from langpipe.cli.context import guarded
from langpipe.domain.errors import SchemaViolation
from langpipe.domain.models.source import PolicySpec, Provenance
from langpipe.ingestion.adapters.scriptureearth import (
    MANIFEST_FILENAME,
    build_manifest,
    scan_package,
    write_manifest,
)

scriptureearth_app = typer.Typer(no_args_is_help=True)


def _load_policy(path: Path) -> PolicySpec:
    try:
        return PolicySpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, yaml.YAMLError, ValidationError):
        raise SchemaViolation() from None


def _parse_acquired_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise SchemaViolation() from None
    if parsed.tzinfo is None:
        raise SchemaViolation()
    return parsed


@scriptureearth_app.command("manifest")
@guarded
def manifest(
    package_dir: Path,
    key: Annotated[str, typer.Option("--key")],
    language: Annotated[str, typer.Option("--language")],
    acquired_from: Annotated[str, typer.Option("--acquired-from")],
    acquired_at: Annotated[str, typer.Option("--acquired-at")],
    policy: Annotated[Path | None, typer.Option("--policy")] = None,
    rights_holder: Annotated[str | None, typer.Option("--rights-holder")] = None,
    include_timing: Annotated[bool, typer.Option("--include-timing")] = False,
) -> None:
    """Build a ScriptureEarth manifest. ``--policy`` and ``--rights-holder`` are records:
    omit them and the manifest gets the repository default policy / no rights holder
    (ADR-0025)."""
    pkg = scan_package(package_dir)
    try:
        provenance = Provenance(acquired_from=acquired_from, rights_holder=rights_holder)
    except ValidationError:
        raise SchemaViolation() from None
    try:
        source_manifest = build_manifest(
            pkg,
            key=key,
            language=language,
            policy=_load_policy(policy) if policy is not None else None,
            provenance=provenance,
            acquired_at=_parse_acquired_at(acquired_at),
            include_timing=include_timing,
        )
    except (ValidationError, ValueError):
        raise SchemaViolation() from None
    path = package_dir / MANIFEST_FILENAME
    write_manifest(source_manifest, path)
    typer.echo(
        f"manifest_path={path} usfm={len(pkg.usfm_files)} timing={len(pkg.timing_files)} "
        f"pkf_ignored={len(pkg.pkf_files)}"
    )
