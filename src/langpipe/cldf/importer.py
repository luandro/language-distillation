"""Governed CLDF import: extraction into a lexical snapshot (WP4.10 §2, ADR-0003).

A CLDF dataset is a *governed source*, not a directory: it must be a registered
`Source` of type ``WORDLIST`` or ``DICTIONARY`` listing every dataset file, ingested
into the immutable raw store under `Operation.INGEST` and decoded only under
`Operation.EXTRACT` (ADR-0007), exactly like the wordlist path whose sequence and
helpers this module reuses (`ingest.governed`).

Order is part of the contract (WP4.10-CLDF-SPEC §2.3):

1. resolve the source and require the type; a revoked source is one audit event then
   `PolicyDenied`;
2. `ingest_source` under `Operation.INGEST` — a denial stores nothing;
3. structural check, metadata only: exactly one object named ``*metadata.json``;
4. the `Operation.EXTRACT` gate (one `POLICY_DENIED` audit event, nothing written);
5. materialize every registered object, sha256-verified, into a fresh temp directory —
   pycldf only ever sees this copy;
6. containment: every table ``url`` (and ``dc:source``) must resolve inside the temp
   directory to a registered relative path; ``..``, absolute paths, URL schemes and
   parser-active indirection — external ``tableSchema``/``dialect`` strings, any
   ``@base`` override — are refused before any parser runs, so pycldf never fetches
   anything;
7. ``Dataset.from_metadata`` restricted to the ``Wordlist`` and ``Dictionary`` modules,
   then ``ds.validate()`` — a failure is a typed `ExtractionFailed` carrying the
   exception *type* only;
8. normalize into the ``cldf-lexical-snapshot`` v1 payload — the only thing Stage 6
   reads, so pycldf never runs inside Stage 6;
9. persist snapshot and IDs-only report artifacts, run I/O and lineage in one
   transaction;
10. idempotent reruns reuse the succeeded run without writing anything.

The snapshot carries no upstream status: nothing imported is ever above `CANDIDATE`
before scoring (Invariant 3), and a related-language form never becomes a target
lexeme (Invariant 8). Reports carry identifiers and counts only, never a headword or
a gloss (M2 E10; AGENTS.md invariant 1).
"""

from __future__ import annotations

import json
import logging
import posixpath
import re
import tempfile
import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from pydantic import JsonValue

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    SourceStatus,
    SourceType,
    most_restrictive,
)
from langpipe.domain.errors import (
    ExtractionFailed,
    InvalidLineage,
    PolicyDenied,
    SchemaViolation,
    UnsupportedSource,
)
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import Artifact, ProcessingRun
from langpipe.domain.models.source import Source, SourceObject
from langpipe.governance import effective_policy
from langpipe.governance.policy import resolve
from langpipe.ingest.governed import (
    _read_verified,
    _record_denial,
    _require_extract_allowed,
    _resolve_languages,
)
from langpipe.ingestion.ingest import ingest_source, resolve_source
from langpipe.ingestion.runs import RunRecorder
from langpipe.lexicon.scoring import LexicalScorePolicy
from langpipe.logging import log_event

if TYPE_CHECKING:
    # A type-only import: `lexicon.service` imports this module at runtime.
    from langpipe.lexicon.service import LexicalInductionResult

CLDF_EXTRACT_TOOL = "langpipe.cldf-extract"
SNAPSHOT_SCHEMA = "cldf-lexical-snapshot"
SNAPSHOT_SCHEMA_VERSION = 1
REPORT_SCHEMA = "cldf-extraction-report"
REPORT_SCHEMA_VERSION = 1

# Table types the M4 snapshot imports; every other table is counted, not read (§2.4).
_IMPORTED_TABLES = ("FormTable", "EntryTable", "SenseTable", "ParameterTable", "LanguageTable")

_ISO3 = re.compile(r"^[a-z]{3}$")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CLDFExtractionResult:
    """One governed CLDF extraction: its run and the artifacts Stage 6 consumes.

    `snapshot` is the stored ``cldf-lexical-snapshot`` artifact — the normalized rows
    pycldf produced once, so the induction stage never imports pycldf. `reused` marks
    an idempotent rerun whose artifacts are returned without reading a byte again.
    """

    source: Source
    run: ProcessingRun
    snapshot: Artifact
    report: Artifact
    reused: bool


def check_containment(
    metadata: Mapping[str, Any], registered: Collection[str], *, base_path: str = ""
) -> None:
    """Refuse anything that escapes — or re-points the parser away from — the copy.

    A table ``url`` (or ``dc:source``) must be a bare relative POSIX path that,
    resolved against the metadata object's registered directory (``base_path``), names
    one of the registered object paths: ``..`` segments, absolute paths and any URL
    scheme raise `SchemaViolation`. Parser-active indirection is refused before any
    pycldf/csvw object is constructed: a string-valued ``tableSchema`` or ``dialect``
    makes the csvw parser fetch that URL during ``Dataset.from_metadata`` (§2.3 step 6:
    pycldf MUST NOT fetch anything over the network), and an ``@base`` override — at
    group, table or schema level, or through ``@context`` — re-points even registered
    relative urls outside the materialized copy. Inline schemas are the supported
    contract; unsupported indirection fails closed (WP4.10-CLDF-SPEC §2.3 step 6).
    """
    # Both are inherited TableGroup properties, so the group level is parsed too.
    for table in (metadata, *metadata.get("tables", [])):
        if not isinstance(table, Mapping):
            continue
        for key in ("tableSchema", "dialect"):
            value = table.get(key)
            if value is not None and not isinstance(value, Mapping):
                raise SchemaViolation()
    _reject_base_override(metadata)
    urls: list[Any] = [
        table.get("url") for table in metadata.get("tables", []) if isinstance(table, Mapping)
    ]
    if metadata.get("dc:source") is not None:
        urls.append(metadata["dc:source"])
    for url in urls:
        _require_contained(url, set(registered), base_path)


def _reject_base_override(node: Any) -> None:
    """`@base` anywhere in the metadata is an unsupported base override — fail closed."""
    if isinstance(node, Mapping):
        if "@base" in node:
            raise SchemaViolation()
        for value in node.values():
            _reject_base_override(value)
    elif isinstance(node, list):
        for item in node:
            _reject_base_override(item)


def _require_contained(url: Any, registered: set[str], base_path: str) -> None:
    if not isinstance(url, str) or not url:
        raise SchemaViolation()
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        raise SchemaViolation()
    path = parts.path
    if path.startswith("/") or "\\" in path or ".." in PurePosixPath(path).parts:
        raise SchemaViolation()
    # pycldf resolves table urls against the metadata file's directory.
    resolved = posixpath.normpath(posixpath.join(base_path, path))
    if resolved not in registered:
        raise SchemaViolation()


def snapshot_from_dataset(ds: Any, target_language: str, contact_language: str) -> dict[str, Any]:
    """Normalize one validated CLDF dataset into the canonical snapshot payload. Pure.

    Wordlist `FormTable` rows become ``form`` records, Dictionary `EntryTable` and
    `SenseTable` rows become ``entry`` and ``sense`` records, and `ParameterTable` rows
    become ``parameter`` records — sorted by ``(table_path, ID)`` and NFC-normalized.
    Rows whose resolved language is not `target_language` are skipped and counted, never
    turned into target records (Invariant 8); an unmappable language is counted
    separately; empty forms, headwords and descriptions are skipped and counted, never
    repaired. Upstream status or validation columns are ignored: the snapshot carries no
    status at all (Invariant 3). Tables outside the M4 import set are counted under
    ``ignored_tables``, never read. ``contact_language`` is carried verbatim so the
    snapshot is self-describing for Stage 6.
    """
    language_map = _language_map(ds)
    rows: list[dict[str, Any]] = []
    skipped = {"other_language": 0, "unmapped_language": 0, "empty_form": 0}
    kept_entries: set[str] = set()
    dropped_entries: dict[str, str] = {}

    form_path = _table_path(ds, "FormTable")
    if form_path is not None:
        for row in ds["FormTable"]:
            language = _resolve_language(_text(row.get("Language_ID")), language_map)
            form = _nfc(_text(row.get("Form")) or _text(row.get("Value")))
            if language is None:
                skipped["unmapped_language"] += 1
            elif language != target_language:
                skipped["other_language"] += 1
            elif not form.strip():
                skipped["empty_form"] += 1
            else:
                rows.append(
                    {
                        "kind": "form",
                        "row_id": _text(row.get("ID")),
                        "table_path": form_path,
                        "language": language,
                        "form": form,
                        "parameter_id": _optional(row.get("Parameter_ID")),
                        "cldf_sources": _sources(row),
                    }
                )

    parameter_path = _table_path(ds, "ParameterTable")
    if parameter_path is not None:
        for row in ds["ParameterTable"]:
            rows.append(
                {
                    "kind": "parameter",
                    "row_id": _text(row.get("ID")),
                    "table_path": parameter_path,
                    "id": _text(row.get("ID")),
                    "name": _nfc(_text(row.get("Name"))),
                    "concepticon_id": _optional(row.get("Concepticon_ID")),
                }
            )

    entry_path = _table_path(ds, "EntryTable")
    if entry_path is not None:
        for row in ds["EntryTable"]:
            row_id = _text(row.get("ID"))
            language = _resolve_language(_text(row.get("Language_ID")), language_map)
            headword = _nfc(_text(row.get("Headword")))
            if language is None:
                dropped_entries[row_id] = "unmapped_language"
                skipped["unmapped_language"] += 1
            elif language != target_language:
                dropped_entries[row_id] = "other_language"
                skipped["other_language"] += 1
            elif not headword.strip():
                dropped_entries[row_id] = "empty_form"
                skipped["empty_form"] += 1
            else:
                kept_entries.add(row_id)
                rows.append(
                    {
                        "kind": "entry",
                        "row_id": row_id,
                        "table_path": entry_path,
                        "language": language,
                        "headword": headword,
                        "pos": _optional(row.get("Part_Of_Speech")),
                        "cldf_sources": _sources(row),
                    }
                )

    sense_path = _table_path(ds, "SenseTable")
    if sense_path is not None:
        for row in ds["SenseTable"]:
            entry_id = _text(row.get("Entry_ID"))
            description = _nfc(_text(row.get("Description")))
            if entry_id not in kept_entries:
                # The sense follows its entry out, counted under the entry's reason.
                skipped[dropped_entries.get(entry_id, "other_language")] += 1
            elif not description.strip():
                skipped["empty_form"] += 1
            else:
                rows.append(
                    {
                        "kind": "sense",
                        "row_id": _text(row.get("ID")),
                        "table_path": sense_path,
                        "entry_id": entry_id,
                        "description": description,
                        "cldf_sources": _sources(row),
                    }
                )

    imported_paths = {path for path in map(lambda t: _table_path(ds, t), _IMPORTED_TABLES) if path}
    ignored_tables = sum(1 for table in ds.tables if str(table.url) not in imported_paths)
    return {
        "schema": SNAPSHOT_SCHEMA,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "target_language": target_language,
        "contact_language": contact_language,
        "rows": sorted(rows, key=lambda record: (record["table_path"], record["row_id"])),
        "counts": {"skipped": skipped, "ignored_tables": ignored_tables},
    }


class CLDFImporter:
    """Governs one registered CLDF source into a lexical snapshot artifact."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.recorder = RunRecorder(ctx)

    def extract(
        self,
        source_ref: str,
        *,
        target_language: str | None = None,
        contact_language: str | None = None,
    ) -> CLDFExtractionResult:
        """Extract one CLDF source under ADR-0007; the module docstring fixes the order."""
        ctx = self.ctx
        source = resolve_source(ctx, source_ref)
        if source.source_type not in (SourceType.WORDLIST, SourceType.DICTIONARY):
            # Only wordlists and dictionaries have this extractor (D5).
            raise UnsupportedSource("no_extractor")
        if source.status is SourceStatus.REVOKED:
            # A revoked source is never re-ingested: fail closed before any byte work.
            _record_denial(ctx, source.id, Operation.INGEST, PolicyDecision.DENY)
            raise PolicyDenied(source.id, Operation.INGEST, PolicyDecision.DENY)

        # INGEST precedes origin work: the gate, the sha256 check and the immutable copy
        # all live in `ingest_source`, so a denial leaves no stored object and no blob.
        ingest_source(ctx, source.id)

        objects = list(ctx.repo.list_source_objects(source.id))
        metadata_objects = [obj for obj in objects if obj.original_path.endswith("metadata.json")]
        if len(metadata_objects) != 1:
            # A CLDF dataset is exactly one metadata file plus its tables (§2.3 step 3).
            raise SchemaViolation()
        metadata_object = metadata_objects[0]

        target, contact = _resolve_languages(source, target_language, contact_language)
        # EXTRACT precedes reading or decoding raw content, and precedes any write.
        _require_extract_allowed(ctx, source.id)

        config: dict[str, JsonValue] = {
            "target_language": target,
            "contact_language": contact,
            "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
            "pycldf_major_minor": _pycldf_major_minor(),
        }
        input_ids = [obj.id for obj in objects]
        reusable = self.recorder.find_reusable(
            RunStage.EXTRACTION, CLDF_EXTRACT_TOOL, config, input_ids
        )
        if reusable is not None:
            # Identical inputs and configuration: return the stored artifacts, untouched.
            try:
                with ctx.repo.transaction():
                    ctx.repo.lock_sources([source.id])
                    source = ctx.repo.get_source(source.id)
                    decision = resolve(effective_policy(ctx.repo, source), Operation.EXTRACT)
                    if (
                        source.status is SourceStatus.REVOKED
                        or decision is not PolicyDecision.ALLOW
                    ):
                        raise PolicyDenied(source.id, Operation.EXTRACT, decision)
            except PolicyDenied as error:
                _record_denial(ctx, source.id, Operation.EXTRACT, error.decision)
                raise
            return CLDFExtractionResult(
                source=source,
                run=reusable,
                snapshot=_artifact_of(ctx, reusable.id, SNAPSHOT_SCHEMA),
                report=_artifact_of(ctx, reusable.id, REPORT_SCHEMA),
                reused=True,
            )

        run = self.recorder.start(RunStage.EXTRACTION, CLDF_EXTRACT_TOOL, config, input_ids)
        try:
            with ctx.repo.transaction():
                ctx.repo.lock_sources([source.id])
                source = ctx.repo.get_source(source.id)
                decision = resolve(effective_policy(ctx.repo, source), Operation.EXTRACT)
                if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                    raise PolicyDenied(source.id, Operation.EXTRACT, decision)
                payload = self._snapshot_payload(source, objects, metadata_object, target, contact)
                access = most_restrictive(obj.access_class for obj in objects)
                snapshot_artifact = _store_json(
                    ctx,
                    run,
                    kind=ArtifactKind.EXTRACTION_SNAPSHOT,
                    schema_name=SNAPSHOT_SCHEMA,
                    schema_version=SNAPSHOT_SCHEMA_VERSION,
                    payload=payload,
                    access_class=access,
                )
                report_artifact = _store_json(
                    ctx,
                    run,
                    kind=ArtifactKind.EXTRACTION_REPORT,
                    schema_name=REPORT_SCHEMA,
                    schema_version=REPORT_SCHEMA_VERSION,
                    payload=_report_payload(source, run, objects, metadata_object, payload),
                    access_class=access,
                )
                ctx.repo.add_artifact(snapshot_artifact)
                ctx.repo.add_artifact(report_artifact)
                for artifact in (snapshot_artifact, report_artifact):
                    ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
                    for obj in objects:
                        ctx.repo.add_run_io(run.id, obj.id, RunIoRole.INPUT)
                        ctx.repo.add_lineage_edge(_edge(ctx, artifact.id, obj.id, run.id))
                succeeded = self.recorder.succeed(run.id)
        except BaseException as error:
            if isinstance(error, PolicyDenied):
                _record_denial(ctx, source.id, Operation.EXTRACT, error.decision)
            # Only the exception type is persisted; messages may carry restricted content.
            self.recorder.fail(run.id, error)
            raise

        log_event(
            logger,
            "cldf.extraction.succeeded",
            source_id=source.id,
            run_id=run.id,
            objects=len(objects),
            count=len(payload["rows"]),
        )
        return CLDFExtractionResult(
            source=source,
            run=succeeded,
            snapshot=snapshot_artifact,
            report=report_artifact,
            reused=False,
        )

    def import_dataset(
        self,
        source_ref: str,
        *,
        target_language: str | None = None,
        contact_language: str | None = None,
        policy: LexicalScorePolicy | None = None,
    ) -> tuple[CLDFExtractionResult, LexicalInductionResult]:
        """`extract()` then Stage 6 over the snapshot with the ``cldf_lexical`` inducer."""
        extraction = self.extract(
            source_ref, target_language=target_language, contact_language=contact_language
        )
        # Imported lazily: `lexicon.service` imports this module's tool constant.
        from langpipe.lexicon.service import LexicalService

        induction = LexicalService(self.ctx).induce_lexicon(
            extraction.run.id, method="cldf_lexical@0.1.0", policy=policy
        )
        return extraction, induction

    def _snapshot_payload(
        self,
        source: Source,
        objects: list[SourceObject],
        metadata_object: SourceObject,
        target: str,
        contact: str,
    ) -> dict[str, Any]:
        """Materialize, contain, parse, validate and normalize; pycldf sees only the copy."""
        ctx = self.ctx
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for obj in objects:
                # Every object is verified against its registered digest before use.
                data = _read_verified(ctx, obj)
                materialized = tmp_dir / obj.original_path
                materialized.parent.mkdir(parents=True, exist_ok=True)
                materialized.write_bytes(data)
            metadata = json.loads(_read_verified(ctx, metadata_object))
            registered_paths = {obj.original_path for obj in objects}
            # Table urls are relative to the metadata file; resolve them into the
            # registered object-path space so lineage can name each row's CSV object.
            base = posixpath.dirname(metadata_object.original_path)
            check_containment(metadata, registered_paths, base_path=base)

            import pycldf

            dataset = pycldf.Dataset.from_metadata(tmp_dir / metadata_object.original_path)
            if dataset.module not in ("Wordlist", "Dictionary"):
                raise UnsupportedSource("no_extractor")
            # The parser must agree with the independent checker: with every base
            # override refused, each table url the parser resolved lands on a
            # registered object path — never a fetch target or an out-of-store read.
            for table in dataset.tables:
                resolved = posixpath.normpath(posixpath.join(base, str(table.url)))
                if resolved not in registered_paths:
                    raise SchemaViolation()
            try:
                dataset.validate()
            except Exception as error:
                raise ExtractionFailed("cldf_invalid", metadata_object.id, None) from error

            payload = snapshot_from_dataset(dataset, target, contact)
            paths = {obj.original_path: obj.id for obj in objects}
            payload["source_key"] = source.key
            table_objects: dict[str, str] = {}
            for table_type in _IMPORTED_TABLES:
                table_path = _table_path(dataset, table_type)
                if table_path is None:
                    continue
                resolved = posixpath.normpath(posixpath.join(base, table_path))
                object_id = paths.get(resolved)
                if object_id is None:
                    raise SchemaViolation()
                table_objects[table_path] = object_id
            payload["table_objects"] = table_objects
            return payload


def _pycldf_major_minor() -> str:
    import pycldf

    match = re.match(r"\d+\.\d+", pycldf.__version__)
    return match.group(0) if match else "unknown"


def _table_path(ds: Any, table_type: str) -> str | None:
    return str(ds[table_type].url) if table_type in ds else None


def _language_map(ds: Any) -> dict[str, str | None]:
    """`LanguageTable`'s ``Language_ID → ISO639P3code`` mapping, codes optional."""
    if "LanguageTable" not in ds:
        return {}
    return {_text(row.get("ID")): _optional(row.get("ISO639P3code")) for row in ds["LanguageTable"]}


def _resolve_language(language_id: str, language_map: Mapping[str, str | None]) -> str | None:
    # Without a LanguageTable the Language_ID must itself be a 3-letter code (§2.4).
    if language_id in language_map:
        return language_map[language_id]
    return language_id if _ISO3.fullmatch(language_id) else None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _sources(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("Source") or []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def _edge(ctx: AppContext, from_id: str, to_id: str, run_id: str) -> LineageEdge:
    return LineageEdge(
        id=ctx.new_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run_id,
        created_at=ctx.clock(),
    )


def _store_json(
    ctx: AppContext,
    run: ProcessingRun,
    *,
    kind: ArtifactKind,
    schema_name: str,
    schema_version: int,
    payload: dict[str, Any],
    access_class: AccessClass,
) -> Artifact:
    stored = ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
    return Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=kind,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=access_class,
        schema_name=schema_name,
        schema_version=schema_version,
        created_at=ctx.clock(),
    )


def _report_payload(
    source: Source,
    run: ProcessingRun,
    objects: list[SourceObject],
    metadata_object: SourceObject,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    # Identifiers, digests and counts only: a headword or a gloss is never written.
    counts = payload["counts"]
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "source_id": source.id,
        "run_id": run.id,
        "target_language": payload["target_language"],
        "contact_language": payload["contact_language"],
        "metadata_object_id": metadata_object.id,
        "objects": [
            {"source_object_id": obj.id, "sha256": obj.sha256, "size_bytes": obj.size_bytes}
            for obj in objects
        ],
        "rows": len(payload["rows"]),
        "skipped": dict(counts["skipped"]),
        "ignored_tables": counts["ignored_tables"],
    }


def _artifact_of(ctx: AppContext, run_id: str, schema_name: str) -> Artifact:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is not RunIoRole.OUTPUT:
            continue
        if ctx.repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
            continue
        artifact = ctx.repo.get_artifact(object_id)
        if artifact.schema_name == schema_name:
            return artifact
    raise InvalidLineage()


__all__ = [
    "CLDF_EXTRACT_TOOL",
    "CLDFExtractionResult",
    "CLDFImporter",
    "REPORT_SCHEMA",
    "REPORT_SCHEMA_VERSION",
    "SNAPSHOT_SCHEMA",
    "SNAPSHOT_SCHEMA_VERSION",
    "check_containment",
    "snapshot_from_dataset",
]
