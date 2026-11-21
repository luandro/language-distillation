"""Atomic Stage 6 lexical induction service (M4-PLAN §6 WP4.7, ADR-0013).

`LexicalService` turns one *succeeded* predecessor run into persisted candidate lexical
knowledge inside one Stage 6 `ProcessingRun`. Three input modes exist, and everything else
is refused:

* a Stage 5 token-alignment run feeds `AlignmentLexicalInducer` over its `TokenAlignmentEdge`s,
  the `TokenOccurrence`s they name, their `Form`s and their `Segment`s;
* a wordlist extraction run (`langpipe.wordlist-extract`, WP4.6) feeds `WordlistAdapter`
  over the exact bytes read back from the immutable raw store, one pinned object at a time;
* a CLDF extraction run (`langpipe.cldf-extract`, WP4.10) feeds `CLDFLexicalInducer`
  over the run's verified ``cldf-lexical-snapshot`` artifact, so pycldf never runs in
  Stage 6.

Invariants this service owns (AGENTS.md; M4-PLAN §3):

* **Governance precedes any write.** `Operation.DISTILL_LEXICON` is checked over the full
  source ancestry of every contributing object before a run key is computed, and re-checked
  under sorted `lock_sources` inside the semantic transaction. A revoked source or a
  non-allow decision writes exactly one `POLICY_DENIED` audit event and raises
  `PolicyDenied` — nothing else is persisted.
* **Idempotent reruns reuse the succeeded run.** The run key pins stage, tool, method,
  resolved languages, the input run and the fully resolved scoring policy (defaults
  included, ADR-0008); a second identical call returns the existing run with
  `reused=True` and writes nothing, guarded by the same request lock the M3 alignment
  service uses so two concurrent calls cannot double-create.
* **Hypotheses, never truth.** The adapters' output is persisted as produced: the scoring
  policy grants `supported` at most and nothing here ever writes `validated`
  (AGENTS.md invariant 3). Contact-language glosses land in `Sense.glosses`, never as
  target-language forms (invariants 8 and 9).
* **Atomicity.** Entities, run I/O, lineage and the `lexical-induction-report` v1 artifact
  commit in one transaction; on any failure the run is marked `FAILED` with the exception
  *type* only — messages may carry restricted content and are never persisted.

Reports carry identifiers, enum values and counts only, never a headword, a gloss or any
other source content (M2 E10; AGENTS.md invariant 1).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace

from pydantic import JsonValue

from langpipe.app_context import AppContext
from langpipe.cldf.importer import CLDF_EXTRACT_TOOL, SNAPSHOT_SCHEMA
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    AuditEventType,
    EntityType,
    LifecycleStatus,
    LineageKind,
    Operation,
    PolicyDecision,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
    most_restrictive,
)
from langpipe.domain.errors import (
    AmbiguousInput,
    InvalidLineage,
    ObjectMissing,
    PolicyDenied,
    SchemaViolation,
)
from langpipe.domain.hashing import canonical_json, config_hash
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import Form, Segment, TokenOccurrence
from langpipe.domain.models.run import Artifact, AuditEvent, ProcessingRun
from langpipe.domain.models.source import SourceObject
from langpipe.governance import effective_policy as get_effective_policy
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.ingest.wordlist import WORDLIST_EXTRACT_TOOL
from langpipe.ingestion.runs import TOOL_VERSION, RunRecorder
from langpipe.lexicon.base import LexicalInducer, LexicalInductionInput, LexicalInductionOutput
from langpipe.lexicon.registry import (
    METHOD_ALIGNMENT_COOCCURRENCE,
    METHOD_CLDF_LEXICAL,
    METHOD_WORDLIST_TABULAR,
    get_lexical_inducer,
)
from langpipe.lexicon.scoring import DEFAULT_POLICY, POLICY_VERSION, LexicalScorePolicy
from langpipe.logging import log_event
from langpipe.storage.repository import alignment_side_descriptors

_TOOL = "langpipe.lexicon-induce"
REPORT_SCHEMA = "lexical-induction-report"
REPORT_SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)

# Fixed mode labels for the report payload; identifiers and codes only.
_ALIGNMENT_MODE = "token_alignment"
_WORDLIST_MODE = "wordlist"
_CLDF_MODE = "cldf"

# The inducer family each input mode requires. A mismatch is invalid input and is
# refused before any preflight, run row or reuse decision: wordlist evidence never
# feeds the alignment inducer, and alignment edges never feed the wordlist adapter.
_MODE_METHODS = {
    _ALIGNMENT_MODE: METHOD_ALIGNMENT_COOCCURRENCE,
    _WORDLIST_MODE: METHOD_WORDLIST_TABULAR,
    _CLDF_MODE: METHOD_CLDF_LEXICAL,
}


@dataclass(frozen=True)
class LexicalInductionResult:
    """One Stage 6 induction: its run, the counts a caller reports and the report artifact.

    `reused` marks an idempotent rerun: a succeeded run with identical inputs and
    configuration already existed and nothing was written twice. `status_counts` covers
    the run's lexemes and senses combined; a machine policy grants `supported` at most,
    so `validated` never appears here (AGENTS.md invariant 3).
    """

    run: ProcessingRun
    reused: bool
    lexemes: int
    senses: int
    concepts: int
    form_links: int
    evidence_items: int
    report: Artifact
    status_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _Plan:
    """One resolved induction mode: its languages, governing sources and pinned inputs.

    `sources` are the sorted ancestor sources `Operation.DISTILL_LEXICON` was verified
    against and the ids `lock_sources` takes; `object_ids` are the contributing objects the
    run pins as inputs and the report derives from. `build_inputs` defers the pure input
    assembly — for the alignment mode, form resolution through the repository — into the
    semantic transaction that persists the run.
    """

    mode: str
    input_run_id: str
    target_language: str
    contact_language: str
    sources: tuple[str, ...]
    object_ids: tuple[str, ...]
    build_inputs: Callable[[str], Sequence[LexicalInductionInput]]


class LexicalService:
    """Orchestrates Stage 6 lexical induction over governed predecessor runs."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.recorder = RunRecorder(ctx)

    def induce_lexicon(
        self,
        input_run_id: str,
        *,
        method: str = "alignment_cooccurrence@0.1.0",
        target_language: str | None = None,
        contact_language: str | None = None,
        policy: LexicalScorePolicy | None = None,
    ) -> LexicalInductionResult:
        """Induce candidate lexical knowledge from one succeeded predecessor run."""
        inducer = get_lexical_inducer(method)
        input_run = self.ctx.repo.get_run(input_run_id)
        if input_run.status is not RunStatus.SUCCEEDED:
            # Only a finished, succeeded run pins evidence an induction may consume.
            raise AmbiguousInput(input_run.stage, 1)
        if input_run.stage is RunStage.TOKEN_ALIGNMENT:
            mode = _ALIGNMENT_MODE
        elif (
            input_run.stage is RunStage.EXTRACTION and input_run.tool_name == WORDLIST_EXTRACT_TOOL
        ):
            mode = _WORDLIST_MODE
        elif input_run.stage is RunStage.EXTRACTION and input_run.tool_name == CLDF_EXTRACT_TOOL:
            mode = _CLDF_MODE
        else:
            # Neither alignment, wordlist nor CLDF evidence: refused, never improvised.
            # (The `UnsupportedSource` reasons are fixed and carry no code for this refusal.)
            raise SchemaViolation()
        # The method family must match the evidence the input pins; refused before any
        # preflight, run row or reuse decision.
        if inducer.method_id.rsplit("@", 1)[0] != _MODE_METHODS[mode]:
            raise SchemaViolation()
        if mode is _ALIGNMENT_MODE:
            plan = self._alignment_plan(input_run, target_language, contact_language)
        elif mode is _WORDLIST_MODE:
            plan = self._wordlist_plan(input_run, target_language, contact_language)
        else:
            plan = self._cldf_plan(input_run, target_language, contact_language)
        return self._execute(input_run, inducer, plan, policy)

    # --- mode resolution ------------------------------------------------------------------

    def _alignment_plan(
        self, input_run: ProcessingRun, target_language: str | None, contact_language: str | None
    ) -> _Plan:
        """Resolve the alignment mode: sides, objects, sources and the deferred input build."""
        repo = self.ctx.repo
        source_side, contact_side = alignment_side_descriptors(
            input_run.config, require_tokenization=True
        )
        # The sides pin both languages; an explicit caller value may agree, never relabel.
        target = _agree(target_language, source_side.language)
        contact = _agree(contact_language, contact_side.language)

        edges = repo.list_token_alignment_edges_for_run(input_run.id)
        tokens: dict[str, TokenOccurrence] = {
            token_id: repo.get_token(token_id)
            for edge in edges
            for token_id in (edge.source_token_id, edge.target_token_id)
        }
        segments: dict[str, Segment] = {
            token.segment_id: repo.get_segment(token.segment_id) for token in tokens.values()
        }
        object_ids = sorted({edge.id for edge in edges} | set(tokens) | set(segments))
        if not object_ids:
            # A genuinely empty alignment names no contributing object. The predecessor
            # still pinned exactly what it consumed — its inputs and its two side
            # sources (the M3 service pins the same ids) — so resolve the contributing
            # objects from there: the run locks the sources it would have consumed and
            # the report carries complete source lineage. Inputs without source ancestry
            # (the pinned predecessor runs) contribute nothing and are skipped; objects
            # that resolve to no source at all still fail closed below.
            pinned = {
                object_id
                for object_id, role in repo.list_run_io(input_run.id)
                if role is RunIoRole.INPUT
            } | {source_side.source_id, contact_side.source_id}
            object_ids = sorted(
                object_id
                for object_id in pinned
                if repo.entity_type_of(object_id) is EntityType.SOURCE
                or ancestor_source_ids(repo, object_id)
            )
        sources = _ensure_lexicon_allowed(self.ctx, object_ids)

        def build(run_id: str) -> Sequence[LexicalInductionInput]:
            # A token's side is the side its segment was normalized on: the segment's run
            # is that side's normalization run. The adapter re-checks every language on the
            # resolved `Form`, so a mis-pinned form is dropped there rather than trusted.
            source_tokens: dict[str, TokenOccurrence] = {}
            contact_tokens: dict[str, TokenOccurrence] = {}
            for token_id, token in tokens.items():
                segment = segments[token.segment_id]
                if (
                    segment.run_id == source_side.normalization_run_id
                    and segment.language == source_side.language
                ):
                    source_tokens[token_id] = token
                elif (
                    segment.run_id == contact_side.normalization_run_id
                    and segment.language == contact_side.language
                ):
                    contact_tokens[token_id] = token
                else:
                    raise SchemaViolation()
            return [
                LexicalInductionInput(
                    run_id=run_id,
                    target_language=target,
                    contact_language=contact,
                    alignment_edges=edges,
                    source_tokens=source_tokens,
                    target_tokens=contact_tokens,
                    source_forms=self._forms(source_tokens, segments),
                    target_forms=self._forms(contact_tokens, segments),
                    segments=segments,
                )
            ]

        return _Plan(
            mode=_ALIGNMENT_MODE,
            input_run_id=input_run.id,
            target_language=target,
            contact_language=contact,
            sources=sources,
            object_ids=tuple(object_ids),
            build_inputs=build,
        )

    def _wordlist_plan(
        self, input_run: ProcessingRun, target_language: str | None, contact_language: str | None
    ) -> _Plan:
        """Resolve the wordlist mode: the extraction run's objects, sources and languages."""
        repo = self.ctx.repo
        objects = [
            repo.get_source_object(object_id)
            for object_id, role in repo.list_run_io(input_run.id)
            if role is RunIoRole.INPUT
            and repo.entity_type_of(object_id) is EntityType.SOURCE_OBJECT
        ]
        if not objects:
            raise SchemaViolation()
        run_target = input_run.config.get("target_language")
        run_contact = input_run.config.get("contact_language")
        if not isinstance(run_target, str) or not isinstance(run_contact, str):
            raise SchemaViolation()
        # The extraction run pinned the languages its hypotheses were decoded under; an
        # explicit caller value may agree, never relabel (Invariant 8/9 hygiene).
        target = _agree(target_language, run_target)
        contact = _agree(contact_language, run_contact)
        object_ids = sorted({obj.id for obj in objects})
        sources = _ensure_lexicon_allowed(self.ctx, object_ids)

        def build(run_id: str) -> Sequence[LexicalInductionInput]:
            # One input per object, each pinning its own `source_object_id`, merged in
            # registered object order — the same shape the governed extractor reads with.
            return [
                LexicalInductionInput(
                    run_id=run_id,
                    target_language=target,
                    contact_language=contact,
                    data=self._read_verified(obj),
                    source_id=obj.source_id,
                    source_object_id=obj.id,
                )
                for obj in objects
            ]

        return _Plan(
            mode=_WORDLIST_MODE,
            input_run_id=input_run.id,
            target_language=target,
            contact_language=contact,
            sources=sources,
            object_ids=tuple(object_ids),
            build_inputs=build,
        )

    def _cldf_plan(
        self, input_run: ProcessingRun, target_language: str | None, contact_language: str | None
    ) -> _Plan:
        """Resolve the CLDF mode: the extraction run's objects and its snapshot artifact.

        The snapshot is the run's ``cldf-lexical-snapshot`` OUTPUT artifact, so pycldf
        never runs inside Stage 6: the single input carries the artifact's verified
        bytes, the metadata object pins `source_object_id`, and governance is checked
        over the full ancestry of every contributing object exactly as for wordlists.
        """
        repo = self.ctx.repo
        objects = [
            repo.get_source_object(object_id)
            for object_id, role in repo.list_run_io(input_run.id)
            if role is RunIoRole.INPUT
            and repo.entity_type_of(object_id) is EntityType.SOURCE_OBJECT
        ]
        if not objects:
            raise SchemaViolation()
        metadata_objects = [obj for obj in objects if obj.original_path.endswith("metadata.json")]
        if len(metadata_objects) != 1:
            raise SchemaViolation()
        run_target = input_run.config.get("target_language")
        run_contact = input_run.config.get("contact_language")
        if not isinstance(run_target, str) or not isinstance(run_contact, str):
            raise SchemaViolation()
        # The extraction run pinned the languages its rows were normalized under; an
        # explicit caller value may agree, never relabel (Invariants 8 and 9).
        target = _agree(target_language, run_target)
        contact = _agree(contact_language, run_contact)
        snapshot = _snapshot_artifact_of(self.ctx, input_run.id)
        object_ids = sorted({obj.id for obj in objects})
        sources = _ensure_lexicon_allowed(self.ctx, object_ids)
        metadata_object = metadata_objects[0]

        def build(run_id: str) -> Sequence[LexicalInductionInput]:
            # One input whose `data` is the snapshot artifact's bytes, verified then read.
            self.ctx.artifact_store.verify(snapshot.sha256)
            data = self.ctx.artifact_store.read_bytes(snapshot.sha256)
            return [
                LexicalInductionInput(
                    run_id=run_id,
                    target_language=target,
                    contact_language=contact,
                    data=data,
                    source_id=metadata_object.source_id,
                    source_object_id=metadata_object.id,
                )
            ]

        return _Plan(
            mode=_CLDF_MODE,
            input_run_id=input_run.id,
            target_language=target,
            contact_language=contact,
            sources=sources,
            object_ids=tuple(object_ids),
            build_inputs=build,
        )

    def _read_verified(self, obj: SourceObject) -> bytes:
        """Read one object's raw bytes after its blob row and stored digest both check out."""
        if self.ctx.repo.get_raw_blob(obj.sha256) is None:
            raise ObjectMissing(obj.sha256)
        self.ctx.raw_store.verify(obj.sha256)
        return self.ctx.raw_store.read_bytes(obj.sha256)

    def _forms(
        self, tokens: Mapping[str, TokenOccurrence], segments: Mapping[str, Segment]
    ) -> dict[str, Form]:
        """Resolve the persisted `Form` of every token on one side that carries one.

        The repository exposes no read by form id, so the form is resolved through the
        natural key `(language, orthography_profile, text)` the tokenization stage pinned:
        a token's form text is its normalized surface, its language its segment's and its
        profile the segment's normalization profile. `get_or_create_form` returns the
        existing row for that key; a returned id that is not the token's `form_id` means
        the reconstruction guessed wrong, so it fails closed — the probe row it may have
        created rolls back with the surrounding transaction. A token without a `form_id`
        (punctuation, numbers) is simply absent: the adapter resolves those by surface or
        drops the edge, and never makes one a lemma.
        """
        forms: dict[str, Form] = {}
        for token in tokens.values():
            if token.form_id is None or token.form_id in forms:
                continue
            segment = segments[token.segment_id]
            if segment.normalization_profile is None:
                raise SchemaViolation()
            probe = Form(
                id=self.ctx.new_id(IdPrefix.FORM),
                language=segment.language,
                orthography_profile=segment.normalization_profile,
                text=token.normalized_surface or token.raw_surface,
                run_id=token.run_id,
                created_at=self.ctx.clock(),
            )
            form = self.ctx.repo.get_or_create_form(probe)
            if form.id != token.form_id:
                raise SchemaViolation()
            forms[form.id] = form
        return forms

    # --- execution -------------------------------------------------------------------------

    def _execute(
        self,
        input_run: ProcessingRun,
        inducer: LexicalInducer,
        plan: _Plan,
        policy: LexicalScorePolicy | None,
    ) -> LexicalInductionResult:
        ctx = self.ctx
        repo = ctx.repo
        # The public policy argument changes scoring and promotion, so the effective
        # policy — defaults resolved, version included — is part of run identity (ADR-0008):
        # equal effective settings reuse, changed settings create a different run.
        effective_policy = policy if policy is not None else DEFAULT_POLICY
        config: dict[str, JsonValue] = {
            "method": inducer.method_id,
            "input_run_id": input_run.id,
            "target_language": plan.target_language,
            "contact_language": plan.contact_language,
            "policy_version": POLICY_VERSION,
            "policy": asdict(effective_policy),
        }
        inputs = [input_run.id]
        # The run key is also the concurrency key, so two identical calls race to one run.
        request_key = ProcessingRun.compute_run_key(
            RunStage.LEXICAL_INDUCTION, _TOOL, TOOL_VERSION, config_hash(config), inputs
        )
        with repo.alignment_lock(request_key):
            reusable = self.recorder.find_reusable(
                RunStage.LEXICAL_INDUCTION, _TOOL, config, inputs
            )
            if reusable is not None:
                try:
                    with repo.transaction():
                        repo.lock_sources(plan.sources)
                        self._require_allowed(plan.sources)
                except PolicyDenied as exc:
                    _record_denial(ctx, exc.source_id, exc.decision)
                    raise
                return self._summary(reusable, True)

            run = self.recorder.start(RunStage.LEXICAL_INDUCTION, _TOOL, config, inputs)
            try:
                with repo.transaction():
                    repo.lock_sources(plan.sources)
                    self._require_allowed(plan.sources)
                    output = _induce(inducer, plan, run.id, effective_policy)
                    self._persist(run.id, input_run.id, plan, output)
                    status_counts = _status_counts(output)
                    access = most_restrictive(
                        get_effective_policy(repo, s).access_class for s in plan.sources
                    )
                    _store_report(ctx, run, plan, inducer.method_id, output, status_counts, access)
                    succeeded = self.recorder.succeed(run.id)
            except BaseException as exc:
                if isinstance(exc, PolicyDenied):
                    _record_denial(ctx, exc.source_id, exc.decision)
                # Only the exception type is persisted; messages may carry restricted content.
                self.recorder.fail(run.id, exc)
                raise
            log_event(
                logger,
                "lexicon.induction.succeeded",
                run_id=run.id,
                count=len(output.lexemes),
            )
            return self._summary(succeeded, False)

    def _require_allowed(self, sources: Sequence[str]) -> None:
        """Re-check every locked source: only `allow` decisions on live sources proceed."""
        for source_id in sources:
            source = self.ctx.repo.get_source(source_id)
            decision = effective_decision(self.ctx.repo, source_id, Operation.DISTILL_LEXICON)
            if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
                if source.status is SourceStatus.REVOKED and decision is PolicyDecision.ALLOW:
                    decision = PolicyDecision.DENY
                raise PolicyDenied(source_id, Operation.DISTILL_LEXICON, decision)

    def _persist(
        self, run_id: str, input_run_id: str, plan: _Plan, output: LexicalInductionOutput
    ) -> None:
        """Register the induced entities, their run I/O and the inputs the run pinned.

        Registration order follows the references: a sense names its lexeme, an evidence
        item its target and a lineage edge both of its endpoints. `add_lineage_edge` is
        idempotent per (from, to, kind), so a repeated derivation never doubles.
        """
        repo = self.ctx.repo
        for concept in output.concepts:
            repo.add_concept(concept)
        for lexeme in output.lexemes:
            repo.add_lexeme(lexeme)
        for link in output.form_links:
            repo.add_form_lexeme_link(link)
        for sense in output.senses:
            repo.add_sense(sense)
        for item in output.evidence_items:
            repo.add_evidence(item)
        for edge in output.lineage_edges:
            repo.add_lineage_edge(edge)
        for object_id in (input_run_id, *plan.object_ids):
            repo.add_run_io(run_id, object_id, RunIoRole.INPUT)
        for output_id in (
            *(lexeme.id for lexeme in output.lexemes),
            *(link.id for link in output.form_links),
            *(sense.id for sense in output.senses),
            *(concept.id for concept in output.concepts),
            *(item.id for item in output.evidence_items),
        ):
            repo.add_run_io(run_id, output_id, RunIoRole.OUTPUT)

    def _summary(self, run: ProcessingRun, reused: bool) -> LexicalInductionResult:
        """Count the run's outputs from its persisted run I/O, fresh or reused alike."""
        repo = self.ctx.repo
        lexemes = senses = concepts = form_links = evidence = 0
        status_counts: dict[str, int] = {}
        report: Artifact | None = None
        for object_id, role in repo.list_run_io(run.id):
            if role is not RunIoRole.OUTPUT:
                continue
            entity = repo.entity_type_of(object_id)
            if entity is EntityType.LEXEME:
                lexemes += 1
                _count(status_counts, repo.get_lexeme(object_id).status)
            elif entity is EntityType.SENSE:
                senses += 1
                _count(status_counts, repo.get_sense(object_id).status)
            elif entity is EntityType.CONCEPT:
                concepts += 1
            elif entity is EntityType.FORM_LEXEME:
                form_links += 1
            elif entity is EntityType.EVIDENCE_ITEM:
                evidence += 1
            elif entity is EntityType.ARTIFACT:
                report = repo.get_artifact(object_id)
        if report is None:
            # A succeeded induction without its report is a broken run, never a summary.
            raise InvalidLineage()
        return LexicalInductionResult(
            run=run,
            reused=reused,
            lexemes=lexemes,
            senses=senses,
            concepts=concepts,
            form_links=form_links,
            evidence_items=evidence,
            report=report,
            status_counts=dict(sorted(status_counts.items())),
        )


# --- helpers --------------------------------------------------------------------------


def _induce(
    inducer: LexicalInducer,
    plan: _Plan,
    run_id: str,
    policy: LexicalScorePolicy,
) -> LexicalInductionOutput:
    """Run the resolved inducer over every pinned input, merging the outputs in order.

    Induction is pure: it reads the pinned objects and the verified raw bytes and writes
    nothing, so it runs inside the semantic transaction without extending what that
    transaction protects. Every input carries the same resolved policy the run key pins.
    """
    output = LexicalInductionOutput()
    for item in plan.build_inputs(run_id):
        output = _merged(output, inducer.induce(replace(item, policy=policy)))
    return output


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


def _status_counts(output: LexicalInductionOutput) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in [lexeme.status for lexeme in output.lexemes] + [
        sense.status for sense in output.senses
    ]:
        _count(counts, status)
    return counts


def _count(counts: dict[str, int], status: LifecycleStatus) -> None:
    key = status.value
    counts[key] = counts.get(key, 0) + 1


def _store_report(
    ctx: AppContext,
    run: ProcessingRun,
    plan: _Plan,
    method_id: str,
    output: LexicalInductionOutput,
    status_counts: Mapping[str, int],
    access: AccessClass,
) -> Artifact:
    """Serialize, store and register the ``lexical-induction-report`` v1 artifact.

    The payload carries identifiers, enum values and counts only: a headword, a gloss or
    any other source content never enters a report (M2 E10; AGENTS.md invariant 1). The
    artifact derives from every contributing object, so a lineage walk from the report
    reaches the evidence the induction consumed.
    """
    payload: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run.id,
        "input_run_id": plan.input_run_id,
        "method": method_id,
        "mode": plan.mode,
        "target_language": plan.target_language,
        "contact_language": plan.contact_language,
        "totals": {
            "lexemes": len(output.lexemes),
            "form_links": len(output.form_links),
            "senses": len(output.senses),
            "concepts": len(output.concepts),
            "evidence_items": len(output.evidence_items),
            "lineage_edges": len(output.lineage_edges),
        },
        "status_counts": dict(sorted(status_counts.items())),
    }
    stored = ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
    artifact = Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.OTHER,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=access,
        schema_name=REPORT_SCHEMA,
        schema_version=REPORT_SCHEMA_VERSION,
        created_at=ctx.clock(),
    )
    ctx.repo.add_artifact(artifact)
    ctx.repo.add_run_io(run.id, artifact.id, RunIoRole.OUTPUT)
    now = ctx.clock()
    for object_id in plan.object_ids:
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=artifact.id,
                to_id=object_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=now,
            )
        )
    return artifact


def _agree(explicit: str | None, resolved: str) -> str:
    """The caller's explicit language may agree with the pinned one, never relabel it."""
    if explicit is not None and explicit != resolved:
        raise SchemaViolation()
    return resolved


def _snapshot_artifact_of(ctx: AppContext, run_id: str) -> Artifact:
    """The ``cldf-lexical-snapshot`` OUTPUT artifact of one CLDF extraction run.

    A succeeded extraction without its snapshot is a broken run, never an inducible
    input (WP4.10 §2.6).
    """
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is not RunIoRole.OUTPUT:
            continue
        if ctx.repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
            continue
        artifact = ctx.repo.get_artifact(object_id)
        if artifact.schema_name == SNAPSHOT_SCHEMA:
            return artifact
    raise InvalidLineage()


def _ensure_lexicon_allowed(ctx: AppContext, input_ids: Sequence[str]) -> tuple[str, ...]:
    """Check `Operation.DISTILL_LEXICON` over the full ancestry of every input.

    Returns the sorted governing source ids, so the caller can lock exactly what was
    verified. Raises `PolicyDenied` — with exactly one `POLICY_DENIED` audit event — for
    the first revoked source, non-allow decision, or input without source ancestry, in
    sorted id order. An induction never launders a restriction through an upstream run.
    """
    if not input_ids:
        raise InvalidLineage()
    repo = ctx.repo
    sources: set[str] = set()
    missing: list[str] = []
    for input_id in sorted(set(input_ids)):
        ancestors = set(ancestor_source_ids(repo, input_id))
        if repo.entity_type_of(input_id) is EntityType.SOURCE:
            ancestors.add(input_id)
        if not ancestors:
            missing.append(input_id)
        sources.update(ancestors)

    # An input with no governing source is not inducible evidence; fail closed first.
    for input_id in missing:
        decision = PolicyDecision.DENY
        _record_denial(ctx, input_id, decision)
        raise PolicyDenied(input_id, Operation.DISTILL_LEXICON, decision)

    for source_id in sorted(sources):
        source = repo.get_source(source_id)
        decision = effective_decision(repo, source_id, Operation.DISTILL_LEXICON)
        if source.status is SourceStatus.REVOKED and decision is PolicyDecision.ALLOW:
            # Revocation is the operative denial: record it as one, not as `allow`.
            decision = PolicyDecision.DENY
        if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
            _record_denial(ctx, source_id, decision)
            raise PolicyDenied(source_id, Operation.DISTILL_LEXICON, decision)
    return tuple(sorted(sources))


def _record_denial(ctx: AppContext, subject_id: str, decision: PolicyDecision) -> None:
    # Mirrors the M2/M3 denial events: identifiers and enum values only, never content.
    with ctx.repo.transaction():
        ctx.repo.add_audit_event(
            AuditEvent(
                id=ctx.new_id(IdPrefix.AUDIT),
                event_type=AuditEventType.POLICY_DENIED,
                actor=ctx.actor,
                subject_id=subject_id,
                run_id=None,
                details={
                    "operation": Operation.DISTILL_LEXICON.value,
                    "decision": decision.value,
                },
                occurred_at=ctx.clock(),
            )
        )
    fields: dict[str, str | int | bool | None] = {
        "operation": Operation.DISTILL_LEXICON.value,
        "decision": decision.value,
    }
    # source_id log fields must be source ids; a missing-ancestry subject may be any
    # registered object, so its id is not echoed there.
    if ctx.repo.entity_type_of(subject_id) is EntityType.SOURCE:
        fields["source_id"] = subject_id
    log_event(logger, "policy.denied", level=logging.WARNING, **fields)


__all__ = [
    "REPORT_SCHEMA",
    "REPORT_SCHEMA_VERSION",
    "LexicalInductionResult",
    "LexicalService",
]
