"""Governed CLDF export: eligible lexical knowledge out as a Dictionary (WP4.10 §3).

The exporter publishes derived knowledge, so every row is governed twice: at selection,
where a row survives only if `lineage_eligibility(..., REDISTRIBUTE_DERIVED)` is
`ALLOW` for **every** entity contributing to it — the lexeme, each surviving sense, its
concept, and the lemma Form or headword evidence supplying the row's form (D7 —
`REVIEW_REQUIRED` counts as not eligible) — and again at commit, where the re-check
runs under `lock_sources` over the complete contributor union so a revocation or status
flip between selection and publish aborts the export (the TOCTOU guard). An
idempotent rerun passes the same guard before its stored files are republished.
Nothing eligible is fail-closed (D8): one `POLICY_DENIED` audit event per
denying source, then `NoEligibleRecords`, with no run, no artifact and no output
directory.

The raw-redistribution firewall is structural, not a filter (D9, §3.5): M4 writes no
ExampleTable, and this module never imports or calls `raw_store`, `get_segment`,
`get_token`, `list_source_objects` or any extraction module — the form text comes from
a lemma `Form` observation or a `headword` evidence claim (§3.4) and nothing else.

Output is byte-deterministic for a given selection: rows sorted by our ids, the
metadata carries no timestamps, and the run's config pins a ``selection_digest`` — the
sha256 of the sorted ``(id, status)`` pairs plus the attribution payload — so a status
flip or a changed license produces a new run even though the input ids are the same.
Files are written to a staging directory and renamed into place only after the run
commits, so a crash leaves at most an orphan staging dir and never a published but
unrecorded export. Logs, reports and CLI output carry ids and counts only.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from langpipe.app_context import AppContext
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
    PolicyMode,
    RunIoRole,
    RunStage,
    most_restrictive,
)
from langpipe.domain.errors import InvalidLineage, NoEligibleRecords, PolicyDenied, SchemaViolation
from langpipe.domain.hashing import canonical_json, sha256_bytes
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.lexical import Lexeme, Sense
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.domain.models.source import SourcePolicy
from langpipe.governance import EffectivePolicy, effective_policy
from langpipe.governance.lineage_policy import (
    ancestor_source_ids,
    lineage_eligibility,
    revoked_ancestor_ids,
)
from langpipe.ingestion.runs import RunRecorder
from langpipe.languages.base import LANGUAGE_PROFILES
from langpipe.logging import log_event
from langpipe.review.recalc import is_stale

CLDF_EXPORT_TOOL = "langpipe.cldf-export"
EXPORT_REPORT_SCHEMA = "cldf-export-report"
EXPORT_REPORT_SCHEMA_VERSION = 2
EXPORTER_VERSION = "0.1.0"
DATASET_MODULE = "Dictionary"
# schema_name of every exported file artifact (WP4.10-CLDF-SPEC §3.8).
EXPORT_SCHEMA_NAME = "cldf-dictionary"

_METADATA_NAME = "Dictionary-metadata.json"
_BIB_NAME = "sources.bib"
_MEDIA_TYPES = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".bib": "application/x-bibtex",
}

_THRESHOLD_VALIDATED = frozenset({LifecycleStatus.VALIDATED})
_THRESHOLD_SUPPORTED = frozenset({LifecycleStatus.VALIDATED, LifecycleStatus.SUPPORTED})

# Omission reasons, fixed order (§3.3); the report always carries every key.
_OMISSION_REASONS = (
    "status_below_threshold",
    "denied",
    "review_required",
    "revoked",
    "no_form",
    "ambiguous_form",
    "no_exportable_sense",
    "stale_dependent",
)

# rdfs:comment emitted when the dataset-level license is omitted (§3.6).
_LICENSES_VARY = "Licenses vary by contributing source; see prov:wasDerivedFrom."

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportSense:
    """One exported sense row, resolved and governed: ids and emitted fields only."""

    id: str
    description: str
    glosses_json: str
    concept_label: str | None
    concepticon_id: str | None
    domain: str | None
    register: str | None
    status: LifecycleStatus
    sources: tuple[str, ...]


@dataclass(frozen=True)
class ExportEntry:
    """One exported entry row and the sense rows under it (homonyms stay separate)."""

    id: str
    headword: str
    pos: str | None
    status: LifecycleStatus
    sources: tuple[str, ...]
    senses: tuple[ExportSense, ...]


@dataclass(frozen=True)
class CLDFExportResult:
    """One governed export: its run, the written files and what a caller reports.

    ``exported`` and ``omitted`` describe the selection *this* call made. For a reused
    run they are recomputed against the current state — a row that joined or fell away
    since the original run is counted — while ``report`` stays that run's stored
    artifact, the historical record of what it wrote (§3.8).
    """

    run: ProcessingRun
    output_dir: Path
    files: tuple[Artifact, ...]
    report: Artifact
    exported: dict[str, int]
    omitted: dict[str, int]
    reused: bool
    access_class: AccessClass


# --- pure builders (unit-tested directly) ---------------------------------------------


def build_rows(
    language: str, entries: Sequence[ExportEntry], *, include_supported: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The EntryTable and SenseTable rows, sorted by our ids (§3.7).

    The ``Status`` column exists only when ``include_supported``; ``Glosses`` is the
    full ``{lang: [..]}`` map as a JSON string so no gloss language is lost in the
    joined ``Description``.
    """
    entry_rows: list[dict[str, Any]] = []
    sense_rows: list[dict[str, Any]] = []
    for entry in sorted(entries, key=lambda item: item.id):
        row: dict[str, Any] = {
            "ID": entry.id,
            "Language_ID": language,
            "Headword": entry.headword,
            "Part_Of_Speech": entry.pos,
            "Source": list(entry.sources),
        }
        if include_supported:
            row["Status"] = entry.status.value
        entry_rows.append(row)
        for sense in sorted(entry.senses, key=lambda item: item.id):
            sense_row: dict[str, Any] = {
                "ID": sense.id,
                "Entry_ID": entry.id,
                "Description": sense.description,
                "Glosses": sense.glosses_json,
                "Concept_Label": sense.concept_label,
                "Concepticon_ID": sense.concepticon_id,
                "Domain": sense.domain,
                "Register": sense.register,
                "Source": list(sense.sources),
            }
            if include_supported:
                sense_row["Status"] = sense.status.value
            sense_rows.append(sense_row)
    return entry_rows, sense_rows


def resolve_headword(
    lexeme: Lexeme,
    senses: Sequence[Sense],
    *,
    get_form: Callable[[str], Any],
    evidence_for: Callable[[str], Sequence[Any]],
    allowed: Callable[[str], bool],
) -> tuple[str | None, str]:
    """Where the exported form text comes from — and why it cannot be prose (§3.4).

    Order is fixed and there is no other path: the lexeme's ``lemma_form_id`` (a lexical
    form observation) wins — the caller has already refused rows whose Form is not
    ``ALLOW`` (§3.2 step 3), and never falls back past it; otherwise the single distinct
    NFC ``headword`` claimed by eligible `DICTIONARY_ASSERTION` evidence targeting the
    lexeme or one of its exported senses. Two distinct headwords are ambiguity, never a
    choice (``ambiguous_form``); none is ``no_form``. Any other claim key is never read.
    """
    if lexeme.lemma_form_id is not None:
        form = get_form(lexeme.lemma_form_id)
        if form is not None:
            return str(form.text), "ok"
    headwords: set[str] = set()
    targets = {lexeme.id, *(sense.id for sense in senses)}
    for target in targets:
        for item in evidence_for(target):
            if item.kind is not EvidenceKind.DICTIONARY_ASSERTION:
                continue
            if item.polarity is not EvidencePolarity.SUPPORTS or not allowed(item.id):
                continue
            claim = item.claim or {}
            if "headword" in claim:
                headwords.add(unicodedata.normalize("NFC", str(claim["headword"])))
    if not headwords:
        return None, "no_form"
    if len(headwords) > 1:
        return None, "ambiguous_form"
    return next(iter(headwords)), "ok"


def build_attribution(
    sources: Sequence[tuple[Any, SourcePolicy | EffectivePolicy]],
) -> dict[str, Any]:
    """The attribution metadata every export carries (§3.6, D10).

    Reads the ``restrictions["attribution"]`` convention off each contributing source's
    policy — no schema migration — and builds the ``prov:wasDerivedFrom`` objects, the
    dataset-level ``dc:license`` (only when every source declares the same license) and
    the ``sources.bib`` entries. Fail closed: a source that requires attribution but
    lacks its text or license refuses the whole export. `Provenance.notes`,
    ``acquired_from`` paths and internal authority fields are never emitted.
    """
    ordered = sorted(sources, key=lambda pair: str(pair[0].key))
    prov: list[dict[str, Any]] = []
    bib: list[dict[str, Any]] = []
    declared: list[str | None] = []
    for source, policy in ordered:
        restrictions = policy.restrictions.get("attribution")
        attribution = restrictions if isinstance(restrictions, dict) else {}
        required = attribution.get("required") is True
        text = _optional_text(attribution.get("text"))
        license_id = _optional_text(attribution.get("license"))
        license_url = _optional_text(attribution.get("license_url"))
        if required and (text is None or license_id is None):
            # Attribution is never silently dropped (§3.6 fail closed).
            raise SchemaViolation()
        license_ref = license_url or license_id
        declared.append(license_ref)
        entry: dict[str, Any] = {
            "rdf:about": f"langpipe:source:{source.key}",
            "dc:title": source.title,
        }
        if license_ref is not None:
            entry["dc:license"] = license_ref
        rights_holder = getattr(source.provenance, "rights_holder", None)
        if rights_holder:
            entry["dc:rightsHolder"] = rights_holder
        if text is not None:
            entry["dc:bibliographicCitation"] = text
        prov.append(entry)
        bib.append(
            {
                "key": str(source.key),
                "title": source.title,
                "note": text,
                "howpublished": license_ref,
            }
        )
    shared = declared[0] if declared and all(item == declared[0] for item in declared) else None
    return {
        "prov": prov,
        "dc_license": shared,
        "rdfs_comment": None if shared is not None else _LICENSES_VARY,
        "bib": bib,
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# --- selection -------------------------------------------------------------------------


@dataclass(frozen=True)
class _Selection:
    """One governed selection: the rows it keeps and everything a caller must know.

    ``statused`` and ``eligibility_ids`` are what the TOCTOU re-check re-runs under the
    source locks; ``denying`` are the sources a fail-closed export would report.
    ``headword_ids`` are the consumed lemma Forms / headword evidence items: they are
    entry-table lineage parents, so revocation impact from their sources reaches the
    published artifacts.
    """

    entries: tuple[ExportEntry, ...]
    exported: dict[str, int]
    omitted: dict[str, int]
    contributing: tuple[str, ...]
    access_class: AccessClass
    denying: tuple[tuple[str, PolicyDecision], ...]
    input_ids: tuple[str, ...]
    concept_ids: tuple[str, ...]
    headword_ids: tuple[str, ...]
    statused: tuple[tuple[str, LifecycleStatus], ...]
    eligibility_ids: tuple[str, ...]


class CLDFExporter:
    """Publishes eligible lexical knowledge of one language as a CLDF Dictionary."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.recorder = RunRecorder(ctx)
        # Set per export from the selection's most restrictive contributing policy (§3.8).
        self._access: AccessClass = AccessClass.RESTRICTED

    def export(
        self, *, language: str, output_dir: Path, include_supported: bool = False
    ) -> CLDFExportResult:
        """Export one language under the governance pipeline; the docstrings fix the order."""
        ctx = self.ctx
        repo = ctx.repo
        _preflight_output_dir(output_dir)
        output_dir.parent.mkdir(parents=True, exist_ok=True)

        threshold = _THRESHOLD_SUPPORTED if include_supported else _THRESHOLD_VALIDATED
        selection = self._select(language, threshold)
        if not selection.entries:
            # D8: fail closed — one audit event per denying source, nothing else written.
            for source_id, decision in selection.denying:
                self._record_denial(source_id, decision)
            raise NoEligibleRecords()
        # The access class every export artifact inherits (§3.8).
        self._access = selection.access_class

        policies = {
            source_id: effective_policy(repo, source_id) for source_id in selection.contributing
        }
        attribution = build_attribution(
            [
                (repo.get_source(source_id), policies[source_id])
                for source_id in selection.contributing
            ]
        )
        config: dict[str, JsonValue] = {
            "language": language,
            "include_supported": include_supported,
            "exporter_version": EXPORTER_VERSION,
            "dataset_module": DATASET_MODULE,
            "selection_digest": _selection_digest(selection, attribution),
        }
        reusable = self.recorder.find_reusable(
            RunStage.EXPORT, CLDF_EXPORT_TOOL, config, selection.input_ids
        )
        if reusable is not None:
            # Byte-identical selection: re-materialize the stored files, write no rows —
            # under the same TOCTOU guard as a fresh export (§3.2 step 9).
            return self._reuse(reusable, output_dir, selection)

        run = self.recorder.start(RunStage.EXPORT, CLDF_EXPORT_TOOL, config, selection.input_ids)
        staging = output_dir.parent / f".{output_dir.name}.staging-{run.id}"
        try:
            self._write_dataset(
                staging, language, selection.entries, attribution, include_supported
            )
            _validate_dataset(staging)
            with repo.transaction():
                # The TOCTOU guard: sources locked, then every decision and status
                # re-checked. A change aborts the export before anything is published.
                repo.lock_sources(sorted(selection.contributing))
                self._recheck(selection)
                artifacts = tuple(
                    self._store_file(run.id, path) for path in sorted(staging.iterdir())
                )
                with_name = {
                    path.name: artifact
                    for path, artifact in zip(sorted(staging.iterdir()), artifacts, strict=True)
                }
                report = self._store_report(run, selection, with_name)
                self._persist(run, selection, artifacts, report, with_name)
                succeeded = self.recorder.succeed(run.id)
        except BaseException as error:
            # Only the exception type is persisted; messages may carry restricted content.
            self.recorder.fail(run.id, error)
            shutil.rmtree(staging, ignore_errors=True)
            raise

        if output_dir.is_dir():
            # The preflight admitted an empty directory only; rename replaces it.
            output_dir.rmdir()
        os.replace(staging, output_dir)
        log_event(
            logger,
            "cldf.export.succeeded",
            run_id=run.id,
            count=selection.exported["entries"],
        )
        return CLDFExportResult(
            run=succeeded,
            output_dir=output_dir,
            files=artifacts,
            report=report,
            exported=dict(selection.exported),
            omitted=dict(selection.omitted),
            reused=False,
            access_class=selection.access_class,
        )

    # --- selection -------------------------------------------------------------------------

    def _select(self, language: str, threshold: frozenset[LifecycleStatus]) -> _Selection:
        """Select, filter and assemble; every candidate row is governed per entity (D7)."""
        repo = self.ctx.repo
        eligibility: dict[str, PolicyDecision] = {}

        def decision_of(object_id: str) -> PolicyDecision:
            if object_id not in eligibility:
                eligibility[object_id] = lineage_eligibility(
                    repo, object_id, Operation.REDISTRIBUTE_DERIVED
                )
            return eligibility[object_id]

        def reason_of(object_id: str) -> str:
            if revoked_ancestor_ids(repo, object_id):
                return "revoked"
            if decision_of(object_id) is PolicyDecision.REVIEW_REQUIRED:
                return "review_required"
            if self._mode_review_required(object_id):
                return "review_required"
            return "denied"

        def ineligible(object_id: str) -> str | None:
            return None if decision_of(object_id) is PolicyDecision.ALLOW else reason_of(object_id)

        omitted = {reason: 0 for reason in _OMISSION_REASONS}
        denying: dict[str, PolicyDecision] = {}

        def note_denial(object_id: str) -> None:
            for source_id in self._source_ids_of(object_id):
                decision = lineage_eligibility(repo, source_id, Operation.REDISTRIBUTE_DERIVED)
                if decision is not PolicyDecision.ALLOW:
                    denying[source_id] = decision

        entries: list[ExportEntry] = []
        statused: list[tuple[str, LifecycleStatus]] = []
        eligibility_ids: set[str] = set()
        contributing: set[str] = set()
        input_ids: set[str] = set()
        concept_ids: set[str] = set()
        headword_ids: set[str] = set()
        sense_count = 0

        for lexeme in repo.list_lexemes_by_language(language):
            if lexeme.status not in threshold:
                omitted["status_below_threshold"] += 1
                continue
            if self._stale_dependent(lexeme.id):
                omitted["stale_dependent"] += 1
                continue
            kept: list[Sense] = []
            for sense in repo.list_senses_for_lexeme(lexeme.id):
                if sense.status not in threshold:
                    omitted["status_below_threshold"] += 1
                    continue
                kept.append(sense)

            reason = ineligible(lexeme.id)
            if reason is not None:
                # The entry inherits its lexeme's refusal: a bare form is never a row.
                omitted[reason] += 1
                note_denial(lexeme.id)
                continue
            governed: list[Sense] = []
            for sense in kept:
                if self._stale_dependent(sense.id):
                    omitted["stale_dependent"] += 1
                    continue
                sense_reason = ineligible(sense.id)
                failed_id = sense.id
                if sense_reason is None and sense.concept_id is not None:
                    # A sense whose concept is ineligible cannot be a row: the row
                    # would carry the concept's label and its obligations.
                    sense_reason = ineligible(sense.concept_id)
                    failed_id = sense.concept_id
                if sense_reason is not None:
                    omitted[sense_reason] += 1
                    note_denial(failed_id)
                    continue
                governed.append(sense)
            if not governed:
                # Zero exportable senses: a bare form with no meaning is noise (§3.2.4).
                omitted["no_exportable_sense"] += 1
                continue

            form_id = lexeme.lemma_form_id
            if form_id is not None and decision_of(form_id) is not PolicyDecision.ALLOW:
                # The lemma Form is a contributing entity (§3.2 step 3): a failing form
                # omits the row. Evidence headwords are never a substitute — they would
                # name a different text source than the lemma (§3.4).
                omitted[reason_of(form_id)] += 1
                note_denial(form_id)
                continue

            headword, reason = resolve_headword(
                lexeme,
                governed,
                get_form=repo.get_form,
                evidence_for=repo.list_evidence_for_target,
                allowed=lambda object_id: decision_of(object_id) is PolicyDecision.ALLOW,
            )
            if headword is None:
                # resolve_headword returns None only with an omission reason (§3.4).
                omitted[reason] += 1
                continue

            entry_senses: list[ExportSense] = []
            headword_sources: set[str] = set()
            if lexeme.lemma_form_id is not None:
                headword_sources.add(lexeme.lemma_form_id)
            else:
                for target in (lexeme.id, *(sense.id for sense in governed)):
                    for item in repo.list_evidence_for_target(target):
                        if (
                            item.kind is EvidenceKind.DICTIONARY_ASSERTION
                            and item.polarity is EvidencePolarity.SUPPORTS
                            and decision_of(item.id) is PolicyDecision.ALLOW
                            and (item.claim or {}).get("headword") is not None
                        ):
                            headword_sources.add(item.id)
            # Every actual contributor is governed (§3.2 steps 3/6): the lemma Form or
            # the evidence supplying the headword contributes alongside the lexeme, and
            # a surviving sense can carry sources of its own that nothing else reaches.
            entry_contributors = set(ancestor_source_ids(repo, lexeme.id))
            for headword_id in headword_sources:
                entry_contributors.update(ancestor_source_ids(repo, headword_id))
            contributing.update(entry_contributors)
            headword_ids.update(headword_sources)
            entry_sources = tuple(
                sorted(repo.get_source(source_id).key for source_id in entry_contributors)
            )
            for sense in governed:
                contributing.update(ancestor_source_ids(repo, sense.id))
                concept = None if sense.concept_id is None else repo.get_concept(sense.concept_id)
                sense_sources = self._source_keys_of(
                    sense.id,
                    extra=(() if concept is None else ancestor_source_ids(repo, concept.id)),
                )
                if concept is not None:
                    contributing.update(ancestor_source_ids(repo, concept.id))
                entry_senses.append(
                    ExportSense(
                        id=sense.id,
                        description=_description_of(sense),
                        glosses_json=canonical_json(sense.glosses),
                        concept_label=None if concept is None else concept.canonical_label,
                        concepticon_id=None if concept is None else concept.concepticon_id,
                        domain=sense.domain,
                        register=sense.register,
                        status=sense.status,
                        sources=sense_sources,
                    )
                )
                input_ids.add(sense.id)
                statused.append((sense.id, sense.status))
                eligibility_ids.add(sense.id)
                if concept is not None:
                    input_ids.add(concept.id)
                    concept_ids.add(concept.id)
                    eligibility_ids.add(concept.id)
            eligibility_ids.add(lexeme.id)
            eligibility_ids.update(headword_sources)
            input_ids.add(lexeme.id)
            statused.append((lexeme.id, lexeme.status))
            entries.append(
                ExportEntry(
                    id=lexeme.id,
                    headword=headword,
                    pos=lexeme.pos,
                    status=lexeme.status,
                    sources=entry_sources,
                    senses=tuple(entry_senses),
                )
            )
            sense_count += len(entry_senses)

        exported = {
            "entries": len(entries),
            "senses": sense_count,
            "languages": 1 if entries else 0,
            "sources": len(contributing),
        }
        contributing_ids = sorted(contributing)
        access = (
            most_restrictive(effective_policy(repo, s).access_class for s in contributing_ids)
            if contributing_ids
            else AccessClass.RESTRICTED
        )
        return _Selection(
            entries=tuple(entries),
            exported=exported,
            omitted=omitted,
            contributing=tuple(contributing_ids),
            access_class=access,
            denying=tuple(sorted(denying.items())),
            input_ids=tuple(sorted(input_ids)),
            concept_ids=tuple(sorted(concept_ids)),
            headword_ids=tuple(sorted(headword_ids)),
            statused=tuple(statused),
            eligibility_ids=tuple(sorted(eligibility_ids)),
        )

    def _mode_review_required(self, object_id: str) -> bool:
        """True when any governing source's mode is `review_required` (§6.2.7)."""
        repo = self.ctx.repo
        for source_id in self._source_ids_of(object_id):
            policy = effective_policy(repo, source_id)
            if policy.mode is PolicyMode.REVIEW_REQUIRED:
                return True
        return False

    def _source_ids_of(self, object_id: str) -> tuple[str, ...]:
        repo = self.ctx.repo
        source_ids = set(ancestor_source_ids(repo, object_id))
        if repo.entity_type_of(object_id) is EntityType.SOURCE:
            source_ids.add(object_id)
        return tuple(sorted(source_ids))

    def _source_keys_of(self, object_id: str, *, extra: Sequence[str] = ()) -> tuple[str, ...]:
        repo = self.ctx.repo
        keys = {
            repo.get_source(source_id).key
            for source_id in (*extra, *ancestor_source_ids(repo, object_id))
        }
        return tuple(sorted(keys))

    def _stale_dependent(self, object_id: str) -> bool:
        return is_stale(self.ctx.repo, object_id)

    # --- writing, validation, commit ---------------------------------------------------------

    def _write_dataset(
        self,
        staging: Path,
        language: str,
        entries: tuple[ExportEntry, ...],
        attribution: Mapping[str, Any],
        include_supported: bool,
    ) -> None:
        """Write the Dictionary into the staging directory (§3.2 step 7, §3.7)."""
        import pycldf
        from pycldf.sources import Source

        def TEXT(name: str) -> dict[str, str]:
            return {"name": name, "datatype": "string"}

        SOURCE_COLUMN = {
            "name": "Source",
            "datatype": "string",
            "separator": ";",
            "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#source",
        }
        ds = pycldf.Dictionary.in_dir(staging)
        ds.add_component("LanguageTable")
        ds.add_columns("EntryTable", SOURCE_COLUMN)
        sense_columns = [
            SOURCE_COLUMN,
            TEXT("Glosses"),
            TEXT("Concept_Label"),
            TEXT("Concepticon_ID"),
            TEXT("Domain"),
            TEXT("Register"),
        ]
        if include_supported:
            ds.add_columns("EntryTable", TEXT("Status"))
            sense_columns.append(TEXT("Status"))
        ds.add_columns("SenseTable", *sense_columns)
        for bib in attribution["bib"]:
            fields: dict[str, str] = {"title": str(bib["title"])}
            if bib["note"]:
                fields["note"] = str(bib["note"])
            if bib["howpublished"]:
                fields["howpublished"] = str(bib["howpublished"])
            ds.add_sources(Source("misc", str(bib["key"]), **fields))
        if attribution["dc_license"] is not None:
            ds.properties["dc:license"] = attribution["dc_license"]
        if attribution["rdfs_comment"] is not None:
            ds.properties["rdfs:comment"] = attribution["rdfs_comment"]
        ds.properties["prov:wasDerivedFrom"] = list(attribution["prov"])
        entry_rows, sense_rows = build_rows(language, entries, include_supported=include_supported)
        profile = LANGUAGE_PROFILES.get(language)
        ds.write(
            EntryTable=entry_rows,
            SenseTable=sense_rows,
            LanguageTable=[
                {
                    "ID": language,
                    "ISO639P3code": language,
                    "Name": None if profile is None else profile.name,
                }
            ],
        )

    def _store_file(self, run_id: str, path: Path) -> Artifact:
        stored = self.ctx.artifact_store.put_file(path)
        return Artifact(
            id=self.ctx.new_id(IdPrefix.ARTIFACT),
            run_id=run_id,
            kind=ArtifactKind.CLDF_EXPORT,
            media_type=_MEDIA_TYPES[path.suffix],
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            access_class=self._access,
            schema_name=EXPORT_SCHEMA_NAME,
            schema_version=1,
            created_at=self.ctx.clock(),
        )

    def _store_report(
        self, run: ProcessingRun, selection: _Selection, with_name: Mapping[str, Artifact]
    ) -> Artifact:
        payload = {
            "schema": EXPORT_REPORT_SCHEMA,
            "schema_version": EXPORT_REPORT_SCHEMA_VERSION,
            "run_id": run.id,
            "exporter_version": EXPORTER_VERSION,
            "dataset_module": DATASET_MODULE,
            "exported": dict(selection.exported),
            "omitted": dict(selection.omitted),
            "entry_ids": [entry.id for entry in selection.entries],
            "sense_ids": [sense.id for entry in selection.entries for sense in entry.senses],
            "source_ids": list(selection.contributing),
            "files": [
                {"name": name, "sha256": artifact.sha256, "size_bytes": artifact.size_bytes}
                for name, artifact in sorted(with_name.items())
            ],
        }
        stored = self.ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
        return Artifact(
            id=self.ctx.new_id(IdPrefix.ARTIFACT),
            run_id=run.id,
            kind=ArtifactKind.OTHER,
            media_type="application/json",
            sha256=stored.sha256,
            size_bytes=stored.size_bytes,
            access_class=self._access,
            schema_name=EXPORT_REPORT_SCHEMA,
            schema_version=EXPORT_REPORT_SCHEMA_VERSION,
            created_at=self.ctx.clock(),
        )

    def _persist(
        self,
        run: ProcessingRun,
        selection: _Selection,
        artifacts: tuple[Artifact, ...],
        report: Artifact,
        with_name: Mapping[str, Artifact],
    ) -> None:
        """Run I/O and lineage in the commit transaction (§3.8).

        Each table artifact derives from every entity whose rows it contains — entries
        and the language row from their lexemes and the consumed headword entities
        (lemma Form or headword evidence), senses from their senses and concepts — and
        the metadata JSON and ``sources.bib`` artifacts derive from the table
        artifacts. This is the path a WP4.9 revocation walk follows back from an
        export; ``languages.csv`` derives from the exported lexemes because the
        language row exists only because those entries exist, and the entry table
        names its headword suppliers, so their sources reach the published bytes too.
        The export report derives from every file artifact it lists, so revoking a
        contributing source also reaches the report.
        """
        repo = self.ctx.repo
        for artifact in (*artifacts, report):
            repo.add_artifact(artifact)
            repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
        for object_id in selection.input_ids:
            repo.add_run_io(run.id, object_id, RunIoRole.INPUT)
        now = self.ctx.clock()
        table_names = ("entries.csv", "languages.csv", "senses.csv")
        sense_ids = [sense.id for entry in selection.entries for sense in entry.senses]
        entry_ids = [entry.id for entry in selection.entries]
        for name in table_names:
            table_artifact = with_name.get(name)
            if table_artifact is None:
                continue
            if name == "senses.csv":
                parents = [*sense_ids, *selection.concept_ids]
            elif name == "entries.csv":
                parents = [*entry_ids, *selection.headword_ids]
            else:  # languages.csv: the language row exists because the entries do.
                parents = entry_ids
            for parent_id in sorted(set(parents)):
                repo.add_lineage_edge(_edge(self.ctx, table_artifact.id, parent_id, run.id, now))
        for name in (_METADATA_NAME, _BIB_NAME):
            wrapper = with_name.get(name)
            if wrapper is None:
                continue
            for table_name in table_names:
                table = with_name.get(table_name)
                if table is not None:
                    repo.add_lineage_edge(_edge(self.ctx, wrapper.id, table.id, run.id, now))
        report_tables = [
            with_name[name]
            for name in (*table_names, _METADATA_NAME, _BIB_NAME)
            if name in with_name
        ]
        for table in report_tables:
            repo.add_lineage_edge(_edge(self.ctx, report.id, table.id, run.id, now))

    def _recheck(self, selection: _Selection) -> None:
        """Re-run eligibility and the status check under the source locks (§3.2 step 9)."""
        repo = self.ctx.repo
        for object_id, status in selection.statused:
            entity = repo.entity_type_of(object_id)
            if entity is EntityType.LEXEME:
                current = repo.get_lexeme(object_id).status
            elif entity is EntityType.SENSE:
                current = repo.get_sense(object_id).status
            else:  # pragma: no cover - statused only ever names lexemes and senses
                raise SchemaViolation()
            if current is not status:
                raise SchemaViolation()
        for object_id in selection.eligibility_ids:
            decision = lineage_eligibility(repo, object_id, Operation.REDISTRIBUTE_DERIVED)
            if decision is not PolicyDecision.ALLOW:
                raise PolicyDenied(object_id, Operation.REDISTRIBUTE_DERIVED, decision)

    def _reuse(
        self, run: ProcessingRun, output_dir: Path, selection: _Selection
    ) -> CLDFExportResult:
        """Re-materialize a reused run's verified files; no new rows are written (§3.8).

        The TOCTOU guard applies to reuse exactly as to a fresh export: the files are
        staged first, then the contributing sources are locked and every eligibility
        and status decision re-checked — only a passing guard publishes the staged
        bytes. A refusal exposes nothing (an absent ``output_dir`` stays absent, an
        admitted empty one stays empty) and marks nothing FAILED: the reused run is a
        historical record of an export that already succeeded.

        The stored report's ``exported``/``omitted`` counts were computed at the
        original run and must not be reported as current: the digest pins the exported
        rows, not the rows that were left out, so a below-threshold, ineligible or
        stale row can appear afterwards (ADR-0016 enumerates omissions so governance
        pressure stays visible). The counts returned here come from the selection just
        made — which the digest proves exports the bytes these files carry — while the
        report artifact itself stays that run's historical record.
        """
        repo = self.ctx.repo
        report = _report_artifact_of(self.ctx, run.id)
        payload = json.loads(self.ctx.artifact_store.read_bytes(report.sha256))
        by_sha = {
            artifact.sha256: artifact
            for object_id, role in self.ctx.repo.list_run_io(run.id)
            if role is RunIoRole.OUTPUT
            and self.ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT
            for artifact in [self.ctx.repo.get_artifact(object_id)]
        }
        staging = output_dir.parent / f".{output_dir.name}.staging-{run.id}"
        # A crashed earlier attempt may have left an orphan staging dir; never publish
        # leftovers alongside the re-materialized files.
        shutil.rmtree(staging, ignore_errors=True)
        try:
            staging.mkdir(parents=True)
            files: list[Artifact] = []
            for entry in payload["files"]:
                self.ctx.artifact_store.verify(entry["sha256"])
                data = self.ctx.artifact_store.read_bytes(entry["sha256"])
                (staging / entry["name"]).write_bytes(data)
                artifact = by_sha.get(entry["sha256"])
                if artifact is not None:
                    files.append(artifact)
            with repo.transaction():
                repo.lock_sources(sorted(selection.contributing))
                self._recheck(selection)
                # The current, most restrictive access class over the contributing
                # sources — re-derived under the lock, since a policy may have changed
                # since the original run. Return values carry it; the historical
                # artifacts in the repo are never rewritten (§3.8).
                current_access = (
                    most_restrictive(
                        effective_policy(repo, s).access_class for s in selection.contributing
                    )
                    if selection.contributing
                    else AccessClass.RESTRICTED
                )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        if output_dir.is_dir():
            # The preflight admitted an empty directory only; rename replaces it.
            output_dir.rmdir()
        os.replace(staging, output_dir)
        current_files = tuple(
            artifact.model_copy(update={"access_class": current_access}) for artifact in files
        )
        current_report = report.model_copy(update={"access_class": current_access})
        return CLDFExportResult(
            run=run,
            output_dir=output_dir,
            files=current_files,
            report=current_report,
            # Counted from the selection just made, never from the stored payload (§3.8).
            exported=dict(selection.exported),
            omitted=dict(selection.omitted),
            reused=True,
            access_class=current_access,
        )

    def _record_denial(self, source_id: str, decision: PolicyDecision) -> None:
        # Mirrors the M2 denial events: identifiers and enum values only, never content.
        with self.ctx.repo.transaction():
            self.ctx.repo.add_audit_event(
                AuditEvent(
                    id=self.ctx.new_id(IdPrefix.AUDIT),
                    event_type=AuditEventType.POLICY_DENIED,
                    actor=self.ctx.actor,
                    subject_id=source_id,
                    run_id=None,
                    details={
                        "operation": Operation.REDISTRIBUTE_DERIVED.value,
                        "decision": decision.value,
                    },
                    occurred_at=self.ctx.clock(),
                )
            )
        log_event(
            logger,
            "policy.denied",
            level=logging.WARNING,
            source_id=source_id,
            operation=Operation.REDISTRIBUTE_DERIVED.value,
            decision=decision.value,
        )


# --- helpers --------------------------------------------------------------------------


def _preflight_output_dir(output_dir: Path) -> None:
    """`output_dir` must not exist, or must be an empty directory (§3.2 step 1)."""
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise SchemaViolation()


def _selection_digest(selection: _Selection, attribution: Mapping[str, Any]) -> str:
    """The sha256 pinning run identity: sorted (id, status) pairs plus attribution (§3.8)."""
    payload = {
        "selection": sorted([entry.id, entry.status.value] for entry in selection.entries)
        + sorted(
            [sense.id, sense.status.value] for entry in selection.entries for sense in entry.senses
        ),
        "attribution": {
            "prov": list(attribution["prov"]),
            "dc_license": attribution["dc_license"],
        },
    }
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _validate_dataset(staging: Path) -> None:
    """The staged dataset must pass pycldf validation before anything is committed."""
    import pycldf

    try:
        valid = pycldf.Dataset.from_metadata(staging / _METADATA_NAME).validate()
    except Exception as error:
        # The pycldf message may quote row content; the typed error carries none of it.
        raise SchemaViolation() from error
    if valid is not True:
        raise SchemaViolation()


def _description_of(sense: Sense) -> str:
    """The contact-language glosses joined with '; ', using the sorted first language."""
    for language in sorted(sense.glosses):
        glosses = sense.glosses[language]
        if glosses:
            return "; ".join(glosses)
    return ""


def _edge(ctx: AppContext, from_id: str, to_id: str, run_id: str, now: Any) -> LineageEdge:
    return LineageEdge(
        id=ctx.new_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run_id,
        created_at=now,
    )


def _report_artifact_of(ctx: AppContext, run_id: str) -> Artifact:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is not RunIoRole.OUTPUT:
            continue
        if ctx.repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
            continue
        artifact = ctx.repo.get_artifact(object_id)
        if artifact.schema_name == EXPORT_REPORT_SCHEMA:
            return artifact
    raise InvalidLineage()


__all__ = [
    "CLDF_EXPORT_TOOL",
    "CLDFExportResult",
    "CLDFExporter",
    "EXPORT_REPORT_SCHEMA",
    "EXPORTER_VERSION",
    "ExportEntry",
    "ExportSense",
    "build_attribution",
    "build_rows",
    "resolve_headword",
]
