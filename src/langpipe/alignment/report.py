"""Stage 4 allowlisted alignment reports (M3 WP3.7, M3-PLAN §5.2/§5.4, ADR-0011 §7).

Reports are infrastructure artifacts, never another semantic layer: canonical JSON with
schema ``segment-alignment-report`` version 1 stored as ``ArtifactKind.ALIGNMENT_FILE``.
Payloads carry identifiers, enum values, counts, fixed reason codes and nullable scores
only — never text, titles, filesystem paths, arbitrary locator references or native
stderr — so an alignment report can never leak restricted prose.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AccessClass,
    ArtifactKind,
    LineageKind,
    RunIoRole,
)
from langpipe.domain.hashing import canonical_json
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.alignment import SegmentAlignment
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import Artifact, ProcessingRun

REPORT_SCHEMA = "segment-alignment-report"
REPORT_SCHEMA_VERSION = 1
TOKEN_REPORT_SCHEMA = "token-alignment-report"
logger = logging.getLogger(__name__)


def segment_report_payload(
    *,
    run_id: str,
    method: str,
    mode: str,
    sides: Sequence[Mapping[str, str | None]],
    namespace: str,
    versification_id: str | None,
    groups: Sequence[SegmentAlignment],
    group_reasons: Mapping[str, str | None],
    unmatched_source: Sequence[tuple[str, str]],
    unmatched_target: Sequence[tuple[str, str]],
    disposition: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the canonical Stage 4 report payload; identifiers and codes only."""
    payload: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "method": method,
        "mode": mode,
        "sides": [dict(side) for side in sides],
        "namespace": namespace,
        "versification_id": versification_id,
        "groups": [
            {
                "alignment_id": alignment.id,
                "group_key": alignment.group_key,
                "status": alignment.status.value,
                "score": alignment.score,
                "reason": group_reasons.get(alignment.id),
                "source_segment_ids": list(alignment.source_segment_ids),
                "target_segment_ids": list(alignment.target_segment_ids),
            }
            for alignment in groups
        ],
        "unmatched_source": [
            {"segment_id": segment_id, "reason": reason} for segment_id, reason in unmatched_source
        ],
        "unmatched_target": [
            {"segment_id": segment_id, "reason": reason} for segment_id, reason in unmatched_target
        ],
        "totals": {
            "groups": len(groups),
            "unmatched_source": len(unmatched_source),
            "unmatched_target": len(unmatched_target),
        },
    }
    if disposition is not None:
        payload["disposition"] = dict(disposition)
    return payload


def store_segment_report(
    ctx: AppContext,
    *,
    run: ProcessingRun,
    payload: Mapping[str, Any],
    access_class: AccessClass,
) -> Artifact:
    """Serialize, store and register the report artifact for one Stage 4 run."""
    stored = ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
    artifact = Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.ALIGNMENT_FILE,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=access_class,
        schema_name=REPORT_SCHEMA,
        schema_version=REPORT_SCHEMA_VERSION,
        created_at=ctx.clock(),
    )
    ctx.repo.add_artifact(artifact)
    return artifact


def link_segment_report(
    ctx: AppContext,
    *,
    run: ProcessingRun,
    report: Artifact,
    alignments: Sequence[SegmentAlignment],
    segments: Sequence[str],
) -> None:
    """OUTPUT run I/O plus derived_from lineage to groups and source-bearing inputs.

    Zero-match runs keep both source ancestries: every selected segment is linked even
    when no alignment exists (ADR-0011 §7). No report→run lineage is written because
    run_id and run I/O already record ownership.
    """
    ctx.repo.add_run_io(run.id, report.id, RunIoRole.OUTPUT)
    now = ctx.clock()
    for alignment in alignments:
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=report.id,
                to_id=alignment.id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=now,
            )
        )
    for segment_id in segments:
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=report.id,
                to_id=segment_id,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=now,
            )
        )


def token_report_payload(
    *,
    run_id: str,
    segment_run_id: str,
    source_tokenization_run_id: str,
    target_tokenization_run_id: str,
    method: str,
    backend: Mapping[str, Any],
    groups: Sequence[Mapping[str, Any]],
    excluded_groups: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Build an allowlisted Stage 5 report containing IDs and fixed diagnostics only."""
    return {
        "schema": TOKEN_REPORT_SCHEMA,
        "schema_version": 1,
        "run_id": run_id,
        "segment_run_id": segment_run_id,
        "source_tokenization_run_id": source_tokenization_run_id,
        "target_tokenization_run_id": target_tokenization_run_id,
        "method": method,
        "backend": dict(backend),
        "groups": [dict(group) for group in groups],
        "excluded_groups": [dict(group) for group in excluded_groups],
        "totals": {
            "groups": len(groups),
            "edges": sum(
                int(group["counts"]["forward"])
                + int(group["counts"]["reverse"])
                + int(group["counts"]["symmetrized"])
                for group in groups
            ),
            "skipped_groups": sum(group["reason"] is not None for group in groups),
            "excluded_groups": len(excluded_groups),
        },
    }


def store_token_report(
    ctx: AppContext,
    *,
    run: ProcessingRun,
    payload: Mapping[str, Any],
    access_class: AccessClass,
) -> Artifact:
    """Serialize and register a canonical Stage 5 alignment report."""
    stored = ctx.artifact_store.put_bytes(canonical_json(payload).encode("utf-8"))
    artifact = Artifact(
        id=ctx.new_id(IdPrefix.ARTIFACT),
        run_id=run.id,
        kind=ArtifactKind.ALIGNMENT_FILE,
        media_type="application/json",
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        access_class=access_class,
        schema_name=TOKEN_REPORT_SCHEMA,
        schema_version=1,
        created_at=ctx.clock(),
    )
    ctx.repo.add_artifact(artifact)
    return artifact


def link_token_report(
    ctx: AppContext,
    *,
    run: ProcessingRun,
    report: Artifact,
    inputs: Sequence[str],
    edges: Sequence[Any],
) -> None:
    """Link report to all selected inputs and created edges, including zero-link cases."""
    ctx.repo.add_run_io(run.id, report.id, RunIoRole.OUTPUT)
    targets = [*(edge.id for edge in edges), *inputs]
    for target in dict.fromkeys(targets):
        ctx.repo.add_lineage_edge(
            LineageEdge(
                id=ctx.new_id(IdPrefix.LINEAGE),
                from_id=report.id,
                to_id=target,
                kind=LineageKind.DERIVED_FROM,
                run_id=run.id,
                created_at=ctx.clock(),
            )
        )
