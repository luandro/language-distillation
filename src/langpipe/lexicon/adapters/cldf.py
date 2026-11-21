"""Pure CLDF lexical induction adapter ``cldf_lexical@0.1.0`` (WP4.10 §2.5, ADR-0013).

Turns one ``cldf-lexical-snapshot`` v1 payload — never pycldf, never the raw store —
into candidate lexical hypotheses. The mapping is aligned with
``wordlist_tabular@0.1.0`` so the two import paths agree:

* **Wordlist:** one `Lexeme` per distinct target form; each row is one `Sense` glossed
  with its parameter name in the contact language and linked to the `Concept` of that
  parameter — a recorded upstream claim (``concept_type="cldf_parameter"``, carrying the
  upstream Concepticon id and a source-scoped ``external_urn``), never a concept minted
  from a gloss.
* **Dictionary:** one `Lexeme` per `EntryTable` row, so homonymous entries stay
  separate (Invariant 7); each `SenseTable` row is one `Sense`; ``pos`` is copied from
  ``Part_Of_Speech`` because it is an observed upstream assertion, not an invention.
* ``lemma_form_id`` is never set: the surface lives in the evidence claim (``headword``),
  which is the single lookup the exporter performs (WP4.10-CLDF-SPEC §3.4).
* One ``dictionary_assertion`` `EvidenceItem` per row, `SUPPORTS`, whose claim carries
  the headword, the gloss (when the row has one) and the CLDF locator.
* Lineage follows the wordlist pattern: evidence to its row's CSV object, lexemes and
  senses to their run, row objects and evidence, concepts to the ParameterTable object.
* Status comes from the `LexicalScorePolicy` — `supported` at most, never `validated`
  (Invariant 3).

Governance is not this adapter's decision: the governed entry point (`cldf.importer`)
read the snapshot from the verified artifact store under `Operation.EXTRACT`, and
Stage 6 (`lexicon.service`) re-checks `Operation.DISTILL_LEXICON` before persisting.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Final

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LineageKind
from langpipe.domain.errors import SchemaViolation
from langpipe.domain.ids import IdFactory, IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.lexical import Concept, Lexeme, Sense
from langpipe.lexicon.adapters.wordlist import _build, _promote
from langpipe.lexicon.base import LexicalInductionInput, LexicalInductionOutput
from langpipe.lexicon.scoring import DEFAULT_POLICY, DICTIONARY_SUPPORT, LexicalScorePolicy

METHOD_ID: str = "cldf_lexical@0.1.0"

# The snapshot schema this adapter reads; anything else is a caller error.
_SNAPSHOT_SCHEMA: Final = "cldf-lexical-snapshot"
_SNAPSHOT_VERSION: Final = 1


def _default_id(prefix: IdPrefix) -> str:
    return new_id(prefix)


def _required(value: str | None, field: str) -> str:
    """A pinned provenance reference the CLDF adapter cannot induce without (Invariant 4)."""
    if value is None:
        raise ValueError(f"a cldf induction pins {field}")
    return value


class CLDFLexicalInducer:
    """Induces candidate lexical hypotheses from one governed CLDF snapshot."""

    name: ClassVar[str] = "cldf_lexical"
    version: ClassVar[str] = "0.1.0"
    method_id: ClassVar[str] = METHOD_ID

    def __init__(
        self,
        *,
        policy: LexicalScorePolicy | None = None,
        new_id: IdFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy if policy is not None else DEFAULT_POLICY
        self._new_id: IdFactory = new_id if new_id is not None else _default_id
        self._clock: Callable[[], datetime] = (
            clock if clock is not None else lambda: datetime.now(UTC)
        )

    def induce(self, input: LexicalInductionInput) -> LexicalInductionOutput:
        source_id = _required(input.source_id, "source_id")
        source_object_id = _required(input.source_object_id, "source_object_id")
        snapshot = _parse_snapshot(input.data)

        policy = input.policy if input.policy is not None else self.policy
        now = self._clock()
        independence_group = input.independence_group or source_id
        rows: list[dict[str, Any]] = snapshot["rows"]

        if any(row["kind"] == "form" for row in rows):
            return _induce_wordlist(
                snapshot,
                source_id,
                source_object_id,
                input,
                policy,
                independence_group,
                now,
                self._new_id,
            )
        if any(row["kind"] == "entry" for row in rows):
            return _induce_dictionary(
                snapshot,
                source_id,
                source_object_id,
                input,
                policy,
                independence_group,
                now,
                self._new_id,
            )
        # An empty snapshot (every row skipped upstream) induces nothing, deterministically.
        return LexicalInductionOutput()


# --- wordlist datasets ------------------------------------------------------------------


def _induce_wordlist(
    snapshot: Mapping[str, Any],
    source_id: str,
    source_object_id: str,
    input: LexicalInductionInput,
    policy: LexicalScorePolicy,
    independence_group: str,
    now: datetime,
    next_id: IdFactory,
) -> LexicalInductionOutput:
    """One lexeme per distinct form, one sense and one assertion per row (§2.5)."""
    rows: list[dict[str, Any]] = snapshot["rows"]
    objects: Mapping[str, str] = snapshot["table_objects"]
    source_key = str(snapshot.get("source_key") or source_id)
    parameters = {row["id"]: row for row in rows if row["kind"] == "parameter"}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["kind"] == "form":
            grouped.setdefault(str(row["form"]), []).append(row)

    # One concept per referenced parameter, created on first use with its own lineage
    # edge to the ParameterTable object: a recorded claim, never a minted one.
    concepts: dict[str, Concept] = {}
    concept_edges: list[LineageEdge] = []

    def concept_for(parameter_id: str) -> Concept | None:
        parameter = parameters.get(parameter_id)
        if parameter is None:
            return None
        if parameter_id not in concepts:
            label = str(parameter["name"]).strip() or parameter_id
            concepts[parameter_id] = _build(
                Concept,
                id=next_id(IdPrefix.CONCEPT),
                concept_type="cldf_parameter",
                canonical_label=label,
                concepticon_id=parameter["concepticon_id"],
                external_urn=f"cldf:{source_key}:parameter:{parameter_id}",
                run_id=input.run_id,
                created_at=now,
            )
            concept_edges.append(
                _edge(
                    concepts[parameter_id].id,
                    _row_object(objects, parameter),
                    input.run_id,
                    now,
                    next_id,
                )
            )
        return concepts[parameter_id]

    output = LexicalInductionOutput()
    for headword in sorted(grouped):
        group = sorted(grouped[headword], key=lambda row: str(row["row_id"]))
        # One headword is one lexeme however many rows observe it; the lexeme is built
        # first so every row's assertion can target it, then promoted on their support.
        lexeme = _build(
            Lexeme,
            id=next_id(IdPrefix.LEXEME),
            language=input.target_language,
            run_id=input.run_id,
            created_at=now,
        )
        row_evidence = [
            _evidence(
                row,
                headword,
                _gloss_of(row, parameters),
                lexeme.id,
                source_id,
                independence_group,
                input.run_id,
                now,
                next_id,
            )
            for row in group
        ]
        lexeme = _promote(lexeme, policy, row_evidence, input.target_language)
        output.lexemes.append(lexeme)
        output.evidence_items.extend(row_evidence)
        # The wordlist lineage pattern: run, the metadata object, the row objects, evidence.
        for parent in (
            input.run_id,
            source_object_id,
            *(_row_object(objects, row) for row in group),
            *(item.id for item in row_evidence),
        ):
            output.lineage_edges.append(_edge(lexeme.id, parent, input.run_id, now, next_id))
        for row, item in zip(group, row_evidence, strict=True):
            output.lineage_edges.append(
                _edge(item.id, _row_object(objects, row), input.run_id, now, next_id)
            )

        for row, item in zip(group, row_evidence, strict=True):
            gloss = _gloss_of(row, parameters)
            concept = None
            if row["parameter_id"]:
                concept = concept_for(str(row["parameter_id"]))
            glosses: dict[str, list[str]] = {input.contact_language: [gloss]} if gloss else {}
            sense = _promote(
                _build(
                    Sense,
                    id=next_id(IdPrefix.SENSE),
                    lexeme_id=lexeme.id,
                    glosses=glosses,
                    concept_id=concept.id if concept is not None else None,
                    run_id=input.run_id,
                    created_at=now,
                ),
                policy,
                [item],
                input.target_language,
            )
            output.senses.append(sense)
            for parent in (input.run_id, lexeme.id, item.id):
                output.lineage_edges.append(_edge(sense.id, parent, input.run_id, now, next_id))

    output.concepts.extend(concepts.values())
    output.lineage_edges.extend(concept_edges)
    return output


# --- dictionary datasets ------------------------------------------------------------------


def _induce_dictionary(
    snapshot: Mapping[str, Any],
    source_id: str,
    source_object_id: str,
    input: LexicalInductionInput,
    policy: LexicalScorePolicy,
    independence_group: str,
    now: datetime,
    next_id: IdFactory,
) -> LexicalInductionOutput:
    """One lexeme per EntryTable row, one sense and one assertion per SenseTable row."""
    rows: list[dict[str, Any]] = snapshot["rows"]
    objects: Mapping[str, str] = snapshot["table_objects"]
    entries = [row for row in rows if row["kind"] == "entry"]
    senses: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["kind"] == "sense":
            senses.setdefault(str(row["entry_id"]), []).append(row)

    output = LexicalInductionOutput()
    for entry in entries:
        entry_id = str(entry["row_id"])
        headword = str(entry["headword"])
        lexeme = _build(
            Lexeme,
            id=next_id(IdPrefix.LEXEME),
            language=input.target_language,
            # `pos` is an observed upstream assertion, copied verbatim (§2.5).
            pos=entry["pos"],
            run_id=input.run_id,
            created_at=now,
        )
        entry_evidence = _evidence(
            entry,
            headword,
            None,
            lexeme.id,
            source_id,
            independence_group,
            input.run_id,
            now,
            next_id,
        )
        # Sense ids are minted before their assertions so each assertion targets its
        # sense from the start, exactly as the entry assertion targets the lexeme.
        sense_ids = [next_id(IdPrefix.SENSE) for _ in senses.get(entry_id, [])]
        sense_rows = sorted(senses.get(entry_id, []), key=lambda row: str(row["row_id"]))
        sense_evidence = [
            _evidence(
                sense_row,
                headword,
                str(sense_row["description"]),
                sense_id,
                source_id,
                independence_group,
                input.run_id,
                now,
                next_id,
            )
            for sense_row, sense_id in zip(sense_rows, sense_ids, strict=True)
        ]
        lexeme = _promote(lexeme, policy, [entry_evidence, *sense_evidence], input.target_language)
        output.lexemes.append(lexeme)
        output.evidence_items.append(entry_evidence)
        # The same lineage pattern: run, the metadata object, the row object, evidence.
        for parent in (input.run_id, source_object_id, _row_object(objects, entry)):
            output.lineage_edges.append(_edge(lexeme.id, parent, input.run_id, now, next_id))
        output.lineage_edges.append(
            _edge(entry_evidence.id, _row_object(objects, entry), input.run_id, now, next_id)
        )

        for sense_row, sense_id, item in zip(sense_rows, sense_ids, sense_evidence, strict=True):
            sense = _promote(
                _build(
                    Sense,
                    id=sense_id,
                    lexeme_id=lexeme.id,
                    glosses={input.contact_language: [str(sense_row["description"])]},
                    run_id=input.run_id,
                    created_at=now,
                ),
                policy,
                [item],
                input.target_language,
            )
            output.senses.append(sense)
            output.evidence_items.append(item)
            for parent in (input.run_id, lexeme.id, item.id):
                output.lineage_edges.append(_edge(sense.id, parent, input.run_id, now, next_id))
            output.lineage_edges.append(
                _edge(item.id, _row_object(objects, sense_row), input.run_id, now, next_id)
            )
    return output


# --- shared helpers ------------------------------------------------------------------------


def _parse_snapshot(data: bytes) -> dict[str, Any]:
    """Decode and shape-check one snapshot payload; anything else is a caller error."""
    try:
        snapshot = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SchemaViolation() from error
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema") != _SNAPSHOT_SCHEMA
        or snapshot.get("schema_version") != _SNAPSHOT_VERSION
        or not isinstance(snapshot.get("rows"), list)
        or not isinstance(snapshot.get("table_objects"), dict)
    ):
        raise SchemaViolation()
    return snapshot


def _row_object(objects: Mapping[str, str], row: Mapping[str, Any]) -> str:
    """The registered `SourceObject` a snapshot row's CSV came from (lineage names it)."""
    object_id = objects.get(str(row["table_path"]))
    if object_id is None:
        # A snapshot whose rows name no registered object has no provenance: refuse.
        raise SchemaViolation()
    return object_id


def _gloss_of(row: Mapping[str, Any], parameters: Mapping[str, Mapping[str, Any]]) -> str | None:
    """The parameter name a wordlist row is glossed with; ``None`` when it names none."""
    parameter_id = row.get("parameter_id")
    if not parameter_id:
        return None
    parameter = parameters.get(str(parameter_id))
    if parameter is None:
        return None
    name = str(parameter["name"]).strip()
    return name or None


def _evidence(
    row: Mapping[str, Any],
    headword: str,
    gloss: str | None,
    target_id: str,
    source_id: str,
    independence_group: str,
    run_id: str,
    now: datetime,
    next_id: IdFactory,
) -> EvidenceItem:
    """The dictionary assertion this row makes about its target (§2.5).

    `target_id` is the lexeme for wordlist rows and dictionary entry rows, and the
    sense for dictionary sense rows; the claim key is ``headword`` in every case, so
    the exporter resolves a headword with one lookup.
    """
    claim: dict[str, Any] = {
        "headword": headword,
        "cldf_row_id": str(row["row_id"]),
        "cldf_table": str(row["table_path"]),
        "cldf_sources": list(row.get("cldf_sources") or []),
    }
    if gloss is not None:
        claim["gloss"] = gloss
    return _build(
        EvidenceItem,
        id=next_id(IdPrefix.EVIDENCE),
        kind=EvidenceKind.DICTIONARY_ASSERTION,
        polarity=EvidencePolarity.SUPPORTS,
        target_id=target_id,
        claim=claim,
        source_id=source_id,
        run_id=run_id,
        strength={DICTIONARY_SUPPORT: 1.0},
        independence_group=independence_group,
        created_at=now,
    )


def _edge(
    from_id: str,
    to_id: str,
    run_id: str,
    now: datetime,
    next_id: IdFactory,
) -> LineageEdge:
    return _build(
        LineageEdge,
        id=next_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=LineageKind.DERIVED_FROM,
        run_id=run_id,
        created_at=now,
    )


__all__ = ["METHOD_ID", "CLDFLexicalInducer"]
