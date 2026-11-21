"""Projects the M1 golden state into ID-free, machine-independent JSON-ready rows.

Labels are stable for the synthetic fixture: sources `src:<key>`, objects `sobj:<key>/<path>`,
runs `run:<stage>:<key>`, artifacts `artifact:ingest_report:<key>` and policies `pol:<key>`.
Lineage and audit rows are labelled from their endpoints and subjects.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import JsonValue

from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType, Operation
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import Segment, Span, TokenOccurrence
from langpipe.domain.models.run import Artifact, ProcessingRun
from langpipe.domain.models.source import SourceObject
from langpipe.extraction.service import ExtractionResult
from langpipe.governance.policy import resolve
from langpipe.ingestion.ingest import IngestResult
from langpipe.ingestion.registration import RegistrationResult
from langpipe.normalization.service import NormalizationResultSummary
from langpipe.tokenization.service import TokenizationSummary

# Decisions recorded per source; each is a trainable or redistribution-sensitive use.
ELIGIBILITY_OPERATIONS: tuple[Operation, ...] = (
    Operation.DIRECT_TRAINING,
    Operation.SYNTHETIC_GENERATION_SUPPORT,
    Operation.THIRD_PARTY_API,
)
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_IDENTIFIER = re.compile(r"^[a-z]+_[0-9A-HJKMNP-TV-Z]{26}$")


def normalize_snapshot(
    ctx: AppContext,
    registrations: Sequence[RegistrationResult],
    ingestions: Sequence[IngestResult],
) -> dict[str, JsonValue]:
    """Returns one JSON-ready value per expected file: sources, source_objects, runs, ..."""
    sources = [ctx.repo.get_source(item.source.id) for item in registrations]
    policies = {source.id: ctx.repo.get_policy(source.policy_id) for source in sources}
    objects = [ctx.repo.get_source_object(obj.id) for item in registrations for obj in item.objects]
    run_ids = [item.run.id for item in registrations] + [item.run.id for item in ingestions]
    runs = [ctx.repo.get_run(run_id) for run_id in dict.fromkeys(run_ids)]
    artifacts = [
        ctx.repo.get_artifact(item.report.id) for item in ingestions if item.report is not None
    ]
    edges = _lineage_edges(ctx, [obj.id for obj in objects] + [art.id for art in artifacts])
    audit = ctx.repo.list_audit_events()

    labels = _labels(registrations, ingestions)
    for edge in edges:
        labels[edge.id] = f"lin:{labels[edge.from_id]}:{edge.kind.value}:{labels[edge.to_id]}"
    for event in audit:
        subject = labels[event.subject_id] if event.subject_id is not None else "none"
        labels[event.id] = f"aud:{subject}:{event.event_type.value}"

    return {
        "sources": _rows([source.model_dump(mode="json") for source in sources], labels),
        "source_objects": _rows(
            [_object_row(obj, labels[obj.source_id].removeprefix("src:")) for obj in objects],
            labels,
        ),
        "runs": _rows([_run_row(run) for run in runs], labels),
        "artifacts": _rows([_artifact_row(art) for art in artifacts], labels),
        "lineage": _rows([edge.model_dump(mode="json") for edge in edges], labels),
        "audit": _rows([event.model_dump(mode="json") for event in audit], labels),
        "eligibility": {
            labels[source.id]: {
                operation.value: resolve(policies[source.id], operation).value
                for operation in ELIGIBILITY_OPERATIONS
            }
            for source in sources
        },
    }


def _labels(
    registrations: Sequence[RegistrationResult], ingestions: Sequence[IngestResult]
) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in registrations:
        key = item.source.key
        labels[item.source.id] = f"src:{key}"
        labels[item.policy.id] = f"pol:{key}"
        labels[item.run.id] = f"run:{item.run.stage.value}:{key}"
        for obj in item.objects:
            labels[obj.id] = f"sobj:{key}/{obj.original_path}"
    for item in ingestions:
        key = item.source.key
        labels[item.run.id] = f"run:{item.run.stage.value}:{key}"
        if item.report is not None:
            labels[item.report.id] = f"artifact:ingest_report:{key}"
    return labels


def _lineage_edges(ctx: AppContext, node_ids: Sequence[str]) -> list[LineageEdge]:
    # Every edge leaves a source object or an artifact, so outgoing edges cover the whole graph.
    edges: dict[str, LineageEdge] = {}
    for node_id in node_ids:
        for edge in ctx.repo.list_lineage_edges(node_id, "out"):
            edges[edge.id] = edge
    return list(edges.values())


def _object_row(obj: SourceObject, source_key: str) -> dict[str, Any]:
    row = obj.model_dump(mode="json")
    # Machine paths must not affect expectations: the origin is rewritten to a fixture label.
    row["origin_uri"] = f"fixture:{source_key}/{obj.original_path}"
    return row


def _run_row(run: ProcessingRun) -> dict[str, Any]:
    row = run.model_dump(mode="json")
    row["code_revision"] = "<rev>"
    row["tool_version"] = "<ver>"
    row["config_hash"] = "<hash>"
    row["run_key"] = "<hash>"
    return row


def _artifact_row(artifact: Artifact) -> dict[str, Any]:
    row = artifact.model_dump(mode="json")
    # The ingest report embeds per-run identifiers, so its digest is not stable across runs.
    row["sha256"] = "<hash>"
    return row


def _rows(rows: Sequence[dict[str, Any]], labels: Mapping[str, str]) -> list[JsonValue]:
    """Relabels identifiers and timestamps, then sorts the rows by their label."""
    relabelled = [_relabel(row, labels) for row in rows]
    return sorted(relabelled, key=lambda row: str(row["id"]))


def _relabel(value: Any, labels: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        # Keys are relabelled too: run configs key extractors by source-object id.
        return {_relabel(key, labels): _relabel(item, labels) for key, item in value.items()}
    if isinstance(value, list):
        return [_relabel(item, labels) for item in value]
    if isinstance(value, str):
        if value in labels:
            return labels[value]
        if _TIMESTAMP.match(value):
            return "<ts>"
        if _IDENTIFIER.fullmatch(value):
            raise AssertionError("unlabelled identifier reached the golden snapshot")
    return value


# --- M2 text-processing projection ---
#
# The M2 golden pipeline (WP2.14) registers and ingests every fixture source, then extracts,
# normalizes and tokenizes four of them. Projection labels follow M1 conventions:
#   runs        run:<stage>:<key>
#   artifacts   artifact:<schema>:<key>   (schema = extraction_report | normalization_report | ...)
#   raw segs    seg:<key>/raw/<ordinal>
#   norm segs   seg:<key>/norm/<ordinal>
#   tokens      tok:<key>/norm<ordinal>/<token ordinal>
#   forms       form:<language>/<profile>/<text>
# A form's attesting sources come from the source of every segment whose tokens carry its id; the
# stable label is the (language, profile, text) natural key. `source` on a segment is the owning
# Source and `object` is the SourceObject; both are recorded because lineage is per object.

_REPORT_SCHEMAS = ("extraction-report", "normalization-report", "tokenization-report")


@dataclass(frozen=True)
class M2SourceState:
    """One fixture source driven through extract -> normalize -> tokenize."""

    key: str
    registration: RegistrationResult
    ingestion: IngestResult
    extraction: ExtractionResult
    normalization: NormalizationResultSummary
    tokenization: TokenizationSummary


# A Form is projected by its (language, normalization_profile, normalized_surface) natural key, and
# rows sharing that label are merged. Two distinct Form IDs under one key would collapse silently,
# so identity is asserted on the raw IDs before any label is applied.
FormNaturalKey = tuple[str, str, str]


def check_form_identity(
    observations: Sequence[tuple[FormNaturalKey, str]],
    form_count: int,
) -> dict[FormNaturalKey, set[str]]:
    """Assert one Form ID per natural key and one key per Form ID; return key -> IDs.

    ``form_count`` is ``Repository.count(EntityType.FORM)``; requiring it to equal both the distinct
    keys and the distinct referenced IDs rejects an orphan or duplicate Form row. The message uses
    counts and IDs only, never form text.
    """
    keys_to_ids: dict[FormNaturalKey, set[str]] = {}
    ids_to_keys: dict[str, set[FormNaturalKey]] = {}
    for key, form_id in observations:
        keys_to_ids.setdefault(key, set()).add(form_id)
        ids_to_keys.setdefault(form_id, set()).add(key)
    duplicate_keys = {key: sorted(ids) for key, ids in keys_to_ids.items() if len(ids) > 1}
    duplicate_ids = {
        form_id: sorted(keys) for form_id, keys in ids_to_keys.items() if len(keys) > 1
    }
    if duplicate_keys or duplicate_ids:
        raise AssertionError(
            "form identity violated before projection: "
            f"keys_with_multiple_ids={sorted(duplicate_keys.values())} "
            f"ids_with_multiple_keys={sorted(duplicate_ids)} "
            f"form_count={form_count}"
        )
    if form_count != len(keys_to_ids) or form_count != len(ids_to_keys):
        raise AssertionError(
            "form count does not match distinct keys/ids: "
            f"form_count={form_count} keys={len(keys_to_ids)} ids={len(ids_to_keys)}"
        )
    return keys_to_ids


def m2_form_identity(
    ctx: AppContext, states: Sequence[M2SourceState]
) -> dict[FormNaturalKey, set[str]]:
    """Collect token-derived Form identities across every state and assert they are unique."""
    observations: list[tuple[FormNaturalKey, str]] = []
    for state in states:
        for segment in ctx.repo.list_segments_for_run(state.normalization.run.id):
            if segment.normalization_profile is None:
                continue
            for token in ctx.repo.list_tokens(segment.id):
                if token.form_id is None or token.normalized_surface is None:
                    continue
                key = (
                    segment.language,
                    segment.normalization_profile,
                    token.normalized_surface,
                )
                observations.append((key, token.form_id))
    return check_form_identity(observations, ctx.repo.count(EntityType.FORM))


def normalize_m2_snapshot(
    ctx: AppContext,
    states: Sequence[M2SourceState],
) -> dict[str, JsonValue]:
    """Project the M2 pipeline state into ID-free, machine-independent JSON-ready rows."""
    m2_form_identity(ctx, states)
    labels = _m2_labels(ctx, states)
    tokens, forms = _m2_tokens_and_forms(ctx, states, labels)
    return {
        "runs": _rows(_m2_runs(states), labels),
        "segments": _rows(_m2_segments(ctx, states, labels), labels),
        "tokens": _rows(tokens, labels),
        "forms": _rows(forms, labels),
        "lineage": _m2_lineage(ctx, states),
        "reports": _rows(_m2_reports(ctx, states, labels), labels),
    }


def _m2_labels(ctx: AppContext, states: Sequence[M2SourceState]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for state in states:
        key = state.key
        labels[state.registration.source.id] = f"src:{key}"
        for obj in state.registration.objects:
            labels[obj.id] = f"sobj:{key}/{obj.original_path}"
        labels[state.extraction.run.id] = f"run:extraction:{key}"
        if state.extraction.report is not None:
            labels[state.extraction.report.id] = f"artifact:extraction_report:{key}"
        labels[state.normalization.run.id] = f"run:normalization:{key}"
        if state.normalization.report is not None:
            labels[state.normalization.report.id] = f"artifact:normalization_report:{key}"
        labels[state.tokenization.run.id] = f"run:tokenization:{key}"
        if state.tokenization.report is not None:
            labels[state.tokenization.report.id] = f"artifact:tokenization_report:{key}"
        for segment in ctx.repo.list_segments_for_run(state.extraction.run.id):
            labels[segment.id] = f"seg:{key}/raw/{segment.ordinal}"
        for segment in ctx.repo.list_segments_for_run(state.normalization.run.id):
            labels[segment.id] = f"seg:{key}/norm/{segment.ordinal}"
            for token in ctx.repo.list_tokens(segment.id):
                labels[token.id] = f"tok:{key}/norm{segment.ordinal}/{token.ordinal}"
                if token.form_id is not None:
                    labels[token.form_id] = _form_label(segment, token)
    return labels


def _form_label(segment: Segment, token: TokenOccurrence) -> str:
    return f"form:{segment.language}/{segment.normalization_profile}/{token.normalized_surface}"


def _m2_runs(states: Sequence[M2SourceState]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        key = state.key
        for run in (state.extraction.run, state.normalization.run, state.tokenization.run):
            rows.append(
                {
                    "id": f"run:{run.stage.value}:{key}",
                    "stage": run.stage.value,
                    "tool": run.tool_name,
                    "config": dict(run.config),
                    "status": run.status.value,
                }
            )
    return rows


def _m2_segments(
    ctx: AppContext, states: Sequence[M2SourceState], labels: Mapping[str, str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        for run in (state.extraction.run, state.normalization.run):
            for segment in ctx.repo.list_segments_for_run(run.id):
                rows.append(_segment_row(segment, labels))
    return rows


def _segment_row(segment: Segment, labels: Mapping[str, str]) -> dict[str, Any]:
    return {
        "id": labels[segment.id],
        "source": labels[segment.source_id],
        "object": labels[segment.source_object_id],
        "ordinal": segment.ordinal,
        "language": segment.language,
        "locator": segment.locator,
        "raw_text": segment.raw_text,
        "normalized_text": segment.normalized_text,
        "profile": segment.normalization_profile,
        "status": segment.status.value,
    }


def _m2_tokens_and_forms(
    ctx: AppContext, states: Sequence[M2SourceState], labels: Mapping[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tokens: list[dict[str, Any]] = []
    forms: dict[str, dict[str, Any]] = {}
    for state in states:
        for segment in ctx.repo.list_segments_for_run(state.normalization.run.id):
            for token in ctx.repo.list_tokens(segment.id):
                form = labels[token.form_id] if token.form_id is not None else None
                tokens.append(
                    {
                        "id": labels[token.id],
                        "segment": labels[token.segment_id],
                        "ordinal": token.ordinal,
                        "raw_surface": token.raw_surface,
                        "raw_span": _span_pair(token.raw_span),
                        "normalized_surface": token.normalized_surface,
                        "normalized_span": _span_pair(token.normalized_span),
                        "tokenizer": token.tokenizer,
                        "form": form,
                    }
                )
                if form is not None:
                    entry = forms.setdefault(
                        form,
                        {
                            "id": form,
                            "language": segment.language,
                            "profile": segment.normalization_profile,
                            "text": token.normalized_surface,
                            "attesting_sources": set(),
                        },
                    )
                    entry["attesting_sources"].add(labels[segment.source_id])
    form_rows = [
        {**entry, "attesting_sources": sorted(entry["attesting_sources"])}
        for entry in forms.values()
    ]
    return tokens, form_rows


def _span_pair(span: Span | None) -> list[int] | None:
    return None if span is None else [span.start, span.end]


def _m2_lineage(ctx: AppContext, states: Sequence[M2SourceState]) -> list[JsonValue]:
    """Summarize the M2 lineage edges as counts of (from layer, kind, to layer)."""
    nodes: set[str] = set()
    for state in states:
        for report in (
            state.extraction.report,
            state.normalization.report,
            state.tokenization.report,
        ):
            if report is not None:
                nodes.add(report.id)
        for run in (state.extraction.run, state.normalization.run):
            for segment in ctx.repo.list_segments_for_run(run.id):
                nodes.add(segment.id)
        for segment in ctx.repo.list_segments_for_run(state.normalization.run.id):
            for token in ctx.repo.list_tokens(segment.id):
                nodes.add(token.id)
                if token.form_id is not None:
                    nodes.add(token.form_id)

    edges: dict[str, LineageEdge] = {}
    for node_id in sorted(nodes):
        for edge in ctx.repo.list_lineage_edges(node_id, "out"):
            edges[edge.id] = edge

    counts: dict[tuple[str, str, str], int] = {}
    for edge in edges.values():
        from_layer = _layer(ctx, edge.from_id)
        to_layer = _layer(ctx, edge.to_id)
        bucket = (from_layer, edge.kind.value, to_layer)
        counts[bucket] = counts.get(bucket, 0) + 1
    return [
        {"from": from_layer, "kind": kind, "to": to_layer, "count": count}
        for (from_layer, kind, to_layer), count in sorted(counts.items())
    ]


def _layer(ctx: AppContext, object_id: str) -> str:
    entity_type = ctx.repo.entity_type_of(object_id)
    return entity_type.value if entity_type is not None else "unknown"


def _m2_reports(
    ctx: AppContext, states: Sequence[M2SourceState], labels: Mapping[str, str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        for report in (
            state.extraction.report,
            state.normalization.report,
            state.tokenization.report,
        ):
            if report is None:
                continue
            payload = json.loads(ctx.artifact_store.read_bytes(report.sha256))
            if payload["schema"] not in _REPORT_SCHEMAS:
                continue
            rows.append(_report_row(payload, labels[report.id], labels))
    return rows


def _report_row(
    payload: Mapping[str, Any], label: str, labels: Mapping[str, str]
) -> dict[str, Any]:
    row: dict[str, Any] = {"id": label, "schema": payload["schema"]}
    if payload["schema"] == "extraction-report":
        row["objects"] = [
            {
                "object": labels[entry["source_object_id"]],
                "extractor": entry["extractor"],
                "units": entry["units"],
                "stats": entry["stats"],
                "empty_units": len(entry["empty_units"]),
            }
            for entry in payload["objects"]
        ]
        row["skipped"] = len(payload["skipped"])
    elif payload["schema"] == "normalization-report":
        row["profiles"] = payload["profiles"]
        row["totals"] = payload["totals"]
        row["failure_codes"] = payload["failure_codes"]
    else:
        row["tokenizers"] = payload["tokenizers"]
        row["totals"] = payload["totals"]
        row["skipped"] = len(payload["skipped"])
    return row
