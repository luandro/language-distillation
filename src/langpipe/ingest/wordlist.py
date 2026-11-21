"""Governed wordlist ingestion and extraction (M4-PLAN §6 WP4.6, ADR-0007).

A wordlist is a *governed source*, not a file: it must be a registered `Source` of type
``WORDLIST`` whose objects the source owns, its bytes must be sha256-verified and copied
into the immutable raw store under `Operation.INGEST`, and its content must be decoded only
under `Operation.EXTRACT`. This module is the one place that sequence is enforced for
wordlists; it delegates each step to the machinery that already owns it
(`ingestion.ingest`, `governance.policy`, `ingestion.runs`) rather than duplicating a
second policy gate.

Order is part of the contract:

1. resolve the source and require `SourceType.WORDLIST` — metadata only, no byte work;
2. `Operation.INGEST` gate and work (ADR-0007 §1): a denial stores nothing, so an
   ``exclude`` source is never hashed and never ingested, while an ``archive_only`` source
   is preserved and only its extraction is refused;
3. `Operation.EXTRACT` gate: a non-allow decision, like a revoked source, writes one
   ``POLICY_DENIED`` audit event and raises before a single byte is read or decoded, and
   before any semantic row exists;
4. read the raw bytes back through the store, verified against the registered sha256;
5. parse and induce through the *pure* adapter (`lexicon.adapters.wordlist`), which owns
   every linguistic decision and never sees governance;
6. persist a succeeded extraction run with its pinned inputs, its report artifact and its
   `derived_from` lineage, so Stage 6 (WP4.7) can require and pin this run.

Nothing here writes a hypothesis's lifecycle status, mints a `Concept`, or persists
lexical rows: `Lexeme`/`Sense` persistence belongs to the Stage 6 induction service
(WP4.7), which consumes this run. Reports carry identifiers, digests and counts only — never
a headword, a gloss or any other source content (M2 E10; AGENTS.md invariant 1).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

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
from langpipe.domain.errors import PolicyDenied, UnsupportedSource
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
from langpipe.lexicon.base import LexicalInducer, LexicalInductionInput, LexicalInductionOutput
from langpipe.lexicon.registry import get_lexical_inducer
from langpipe.logging import log_event

WORDLIST_EXTRACT_TOOL = "langpipe.wordlist-extract"
REPORT_SCHEMA = "wordlist-extraction-report"
REPORT_SCHEMA_VERSION = 1
COUNT_FIELD = "count"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WordlistExtractionResult:
    """One governed wordlist extraction: its run and the candidate hypotheses it produced.

    `induction` is the pure adapter's output over the bytes just read — candidate `Lexeme`s,
    `Sense`s, `dictionary_assertion` `EvidenceItem`s and `derived_from` lineage edges — so a
    caller (Stage 6, WP4.7) persists hypotheses without re-reading the raw store. It is not
    a persisted record of this run: the run, its report artifact and the lineage edges are.
    """

    source: Source
    run: ProcessingRun
    induction: LexicalInductionOutput
    report: Artifact | None
    reused: bool


class WordlistExtractor:
    """Governs one registered wordlist source into candidate lexical hypotheses."""

    name: ClassVar[str] = "wordlist_tabular"
    version: ClassVar[str] = "0.1.0"

    def __init__(self, ctx: AppContext, *, inducer: LexicalInducer | None = None) -> None:
        self.ctx = ctx
        self.inducer: LexicalInducer = (
            inducer if inducer is not None else get_lexical_inducer("wordlist_tabular@0.1.0")
        )
        self.recorder = RunRecorder(ctx)

    def extract(
        self,
        source_ref: str,
        *,
        target_language: str | None = None,
        contact_language: str | None = None,
    ) -> WordlistExtractionResult:
        """Extract one wordlist source under ADR-0007; the module docstring fixes the order."""
        ctx = self.ctx
        source = resolve_source(ctx, source_ref)
        if source.source_type is not SourceType.WORDLIST:
            # Only a wordlist has this extractor; any other source type is unsupported here.
            raise UnsupportedSource("no_extractor")
        if source.status is SourceStatus.REVOKED:
            # A revoked source is never re-ingested: fail closed before any byte work.
            _record_denial(ctx, source.id, Operation.INGEST, PolicyDecision.DENY)
            raise PolicyDenied(source.id, Operation.INGEST, PolicyDecision.DENY)

        # INGEST precedes origin work: the gate, the sha256 check and the immutable copy all
        # live in `ingest_source`, so a denial here leaves no stored object and no blob row.
        ingest_source(ctx, source.id)

        objects = list(ctx.repo.list_source_objects(source.id))
        if not objects:
            raise UnsupportedSource("no_extractor")
        target, contact = _resolve_languages(source, target_language, contact_language)

        # EXTRACT precedes reading or decoding raw content, and precedes any semantic write.
        _require_extract_allowed(ctx, source.id)

        access_class = most_restrictive(obj.access_class for obj in objects)
        config: dict[str, JsonValue] = {
            "target_language": target,
            "contact_language": contact,
            "method": self.inducer.method_id,
        }
        input_ids = [obj.id for obj in objects]
        reusable = self.recorder.find_reusable(
            RunStage.EXTRACTION, WORDLIST_EXTRACT_TOOL, config, input_ids
        )
        if reusable is not None:
            # Identical inputs and configuration: the succeeded run and its induction are
            # reproduced without writing a second run or a second report.
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
                    induction = _read_and_induce(
                        self.inducer, ctx, source, objects, target, contact, reusable.id
                    )
            except PolicyDenied as error:
                _record_denial(ctx, source.id, Operation.EXTRACT, error.decision)
                raise
            return WordlistExtractionResult(
                source=source,
                run=reusable,
                induction=induction,
                report=_report_of(ctx, reusable.id),
                reused=True,
            )

        run = self.recorder.start(RunStage.EXTRACTION, WORDLIST_EXTRACT_TOOL, config, input_ids)
        try:
            # Parsing and induction stay pure: each object is read and verified
            # under the source lock and the adapter turns those bytes into hypotheses.
            with ctx.repo.transaction():
                ctx.repo.lock_sources([source.id])
                source = ctx.repo.get_source(source.id)
                decision = resolve(effective_policy(ctx.repo, source), Operation.EXTRACT)
                if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                    raise PolicyDenied(source.id, Operation.EXTRACT, decision)
                induction = _read_and_induce(
                    self.inducer, ctx, source, objects, target, contact, run.id
                )
                report = _store_report(
                    ctx, run, source, objects, target, contact, induction, access_class
                )
                ctx.repo.add_artifact(report)
                ctx.repo.add_run_io(run.id, report.id, RunIoRole.OUTPUT)
                for obj in objects:
                    ctx.repo.add_run_io(run.id, obj.id, RunIoRole.INPUT)
                    ctx.repo.add_lineage_edge(_edge(ctx, report.id, obj.id, run.id))
                succeeded = self.recorder.succeed(run.id)
        except BaseException as error:
            if isinstance(error, PolicyDenied):
                _record_denial(ctx, source.id, Operation.EXTRACT, error.decision)
            self.recorder.fail(run.id, error)
            raise

        log_event(
            logger,
            "wordlist.extraction.succeeded",
            source_id=source.id,
            run_id=run.id,
            objects=len(objects),
            **{COUNT_FIELD: len(induction.lexemes)},
        )
        return WordlistExtractionResult(
            source=source,
            run=succeeded,
            induction=induction,
            report=report,
            reused=False,
        )


def _read_and_induce(
    inducer: LexicalInducer,
    ctx: AppContext,
    source: Source,
    objects: Sequence[SourceObject],
    target_language: str,
    contact_language: str,
    run_id: str,
) -> LexicalInductionOutput:
    """Read each object's verified bytes and induce over the merged output.

    Each object pins its own `source_object_id`, so every hypothesis and evidence item names
    the object a reviewer can check against the raw store; `run_id` is the extraction run the
    hypotheses descend from (AGENTS.md invariant 4). The outputs are merged in registered
    object order, which keeps the result independent of dict, filesystem or database order.
    """
    induction = LexicalInductionOutput()
    for obj in objects:
        output = inducer.induce(
            LexicalInductionInput(
                run_id=run_id,
                target_language=target_language,
                contact_language=contact_language,
                data=_read_verified(ctx, obj),
                source_id=source.id,
                source_object_id=obj.id,
            )
        )
        induction = _merged(induction, output)
    return induction


def _merged(
    first: LexicalInductionOutput, second: LexicalInductionOutput
) -> LexicalInductionOutput:
    return LexicalInductionOutput(
        lexemes=[*first.lexemes, *second.lexemes],
        form_links=[*first.form_links, *second.form_links],
        senses=[*first.senses, *second.senses],
        concepts=[*first.concepts, *second.concepts],
        evidence_items=[*first.evidence_items, *second.evidence_items],
        lineage_edges=[*first.lineage_edges, *second.lineage_edges],
    )


def _edge(ctx: AppContext, from_id: str, to_id: str, run_id: str) -> LineageEdge:
    return LineageEdge(
        id=ctx.new_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run_id,
        created_at=ctx.clock(),
    )


def _report_payload(
    source: Source,
    run: ProcessingRun,
    objects: Sequence[SourceObject],
    target_language: str,
    contact_language: str,
    induction: LexicalInductionOutput,
) -> dict[str, object]:
    # Identifiers, digests and counts only: a headword, a gloss or a note is never written.
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "source_id": source.id,
        "run_id": run.id,
        "target_language": target_language,
        "contact_language": contact_language,
        "objects": [
            {"source_object_id": obj.id, "sha256": obj.sha256, "size_bytes": obj.size_bytes}
            for obj in objects
        ],
        "totals": {
            "lexemes": len(induction.lexemes),
            "senses": len(induction.senses),
            "form_links": len(induction.form_links),
            "evidence_items": len(induction.evidence_items),
            "lineage_edges": len(induction.lineage_edges),
        },
    }


def _store_report(
    ctx: AppContext,
    run: ProcessingRun,
    source: Source,
    objects: Sequence[SourceObject],
    target_language: str,
    contact_language: str,
    induction: LexicalInductionOutput,
    access_class: AccessClass,
) -> Artifact:
    stored = ctx.artifact_store.put_bytes(
        canonical_json(
            _report_payload(source, run, objects, target_language, contact_language, induction)
        ).encode("utf-8")
    )
    return Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.EXTRACTION_REPORT,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=access_class,
        schema_name=REPORT_SCHEMA,
        schema_version=REPORT_SCHEMA_VERSION,
        created_at=ctx.clock(),
    )


def _report_of(ctx: AppContext, run_id: str) -> Artifact | None:
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT:
            return ctx.repo.get_artifact(object_id)
    return None


__all__ = [
    "REPORT_SCHEMA",
    "REPORT_SCHEMA_VERSION",
    "WORDLIST_EXTRACT_TOOL",
    "WordlistExtractionResult",
    "WordlistExtractor",
]
