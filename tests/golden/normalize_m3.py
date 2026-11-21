"""ID-free projection for the M3 golden alignment graph.

Every snapshot value is derived from persisted state only: opaque ids are replaced by
side/group/member/token ordinal labels and hashes by fixed placeholders, exactly like the
M1/M2 golden projections. Source 01 is ``distill_only``, so its benchmark is a denial; the
benchmark report in this snapshot belongs to the synthetic ``direct`` null challenge, whose
runs are passed in ``auxiliary_flows`` so their lineage stays labeled instead of opaque.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import Any

from langpipe.app_context import AppContext
from langpipe.domain.enums import EntityType, LineageKind, RunIoRole, RunStage

_ID = re.compile(r"^[a-z]+_[0-9A-HJKMNP-TV-Z]{26}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REPORT_NAMES = ("segment-report", "token-report", "benchmark-report")
_RUN_NAMES = ("segment-run", "token-run", "benchmark-run")


def normalize_m3_snapshot(
    ctx: AppContext,
    source_ids: list[str],
    segment_run_id: str,
    token_run_id: str,
    benchmark_run_id: str,
    auxiliary_flows: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    """Project the M3 alignment graph into the five ID-free snapshot sections.

    ``auxiliary_flows`` lists ``(segment_run_id, token_run_id)`` pairs — the null challenge that
    produced the benchmark report — so every object reachable from that benchmark keeps a
    stable ordinal label in ``lineage`` instead of an opaque id.
    """
    labels: dict[str, str] = {
        source_id: f"source:{index}" for index, source_id in enumerate(source_ids)
    }

    alignments = _label_flow(ctx, labels, segment_run_id, token_run_id, "")
    _label_raw_segments(ctx.repo, labels, alignments, "raw-segment")
    token_edges = _edges(ctx, token_run_id)
    for index, edge in enumerate(token_edges):
        labels[edge.id] = f"edge:{index}"

    for number, (aux_segment_run, aux_token_run) in enumerate(auxiliary_flows):
        prefix = f"aux{number}-"
        _label_flow(ctx, labels, aux_segment_run, aux_token_run, prefix)
        # Every parent of the benchmark report needs its own recognizable label: the auxiliary
        # source, the gold artifact and the upstream extraction/normalization/tokenization runs
        # are all distinct evidence identities, not interchangeable opaque ids.
        _label_auxiliary_sources(ctx.repo, labels, aux_segment_run, prefix)
        labels.update(
            _gold_artifact_label(ctx.repo, labels, benchmark_run_id, f"{prefix}gold-artifact")
        )
        labels.update(_input_run_labels(ctx.repo, labels, aux_token_run, f"{prefix}input-"))
        labels.update(_extraction_run_labels(ctx.repo, labels, aux_segment_run, prefix))
        _label_raw_segments(
            ctx.repo,
            labels,
            ctx.repo.list_segment_alignments_for_run(aux_segment_run),
            f"{prefix}raw-segment",
        )

    labels[benchmark_run_id] = "benchmark-run"
    for run_id in (segment_run_id, token_run_id):
        labels[run_id] = run_id_to_name(run_id, segment_run_id, token_run_id)
    _label_flow_runs(ctx.repo, labels, segment_run_id, token_run_id)
    for number, (aux_segment_run, aux_token_run) in enumerate(auxiliary_flows):
        _label_flow_runs(ctx.repo, labels, aux_segment_run, aux_token_run, f"aux{number}-")

    reports = _collect_reports(
        ctx,
        labels,
        ((segment_run_id, "segment-report"), (token_run_id, "token-report")),
    )
    reports["benchmark-report"] = _collect_reports(
        ctx, labels, ((benchmark_run_id, "benchmark-report"),)
    )["benchmark-report"]
    for name in _REPORT_NAMES:
        assert reports.get(name), f"{name} is empty"
    _validate_benchmark_report(reports["benchmark-report"])

    lineage: dict[str, dict[str, str]] = {}
    for node_id in list(labels):
        for edge in ctx.repo.list_lineage_edges(node_id, "out"):
            lineage[edge.id] = {
                "from": labels.get(edge.from_id, _safe_label(edge.from_id)),
                "kind": edge.kind.value,
                "to": labels.get(edge.to_id, _safe_label(edge.to_id)),
            }

    segment_rows = [
        {
            "source_members": [labels[item] for item in row.source_segment_ids],
            "target_members": [labels[item] for item in row.target_segment_ids],
            "method": row.method,
            "mode": row.mode.value,
            "status": row.status.value,
            "group_key": "<hash>",
        }
        for row in alignments
    ]
    token_rows = [
        {
            "alignment": labels[row.segment_alignment_id],
            "source": labels[row.source_token_id],
            "target": labels[row.target_token_id],
            "direction": row.direction.value,
            "algorithm": row.algorithm,
            "symmetrization": row.symmetrization.value,
        }
        for row in sorted(
            token_edges,
            key=lambda item: (
                labels[item.segment_alignment_id],
                item.direction.value,
                labels[item.source_token_id],
                labels[item.target_token_id],
            ),
        )
    ]
    return {
        "segment_alignments": segment_rows,
        "token_edges": token_rows,
        "reports": reports,
        "lineage": sorted(lineage.values(), key=lambda row: (row["from"], row["kind"], row["to"])),
        "benchmark": reports["benchmark-report"],
    }


def run_id_to_name(run_id: str, segment_run_id: str, token_run_id: str) -> str:
    if run_id == segment_run_id:
        return "segment-run"
    if run_id == token_run_id:
        return "token-run"
    return "run"


def _label_flow(
    ctx: AppContext,
    labels: dict[str, str],
    segment_run_id: str,
    token_run_id: str,
    prefix: str,
) -> list[Any]:
    """Label one Stage 4 run's groups, members, tokens and its Stage 5 run's edges."""
    alignments = ctx.repo.list_segment_alignments_for_run(segment_run_id)
    alignments.sort(key=lambda row: _segment_ref(ctx, row.source_segment_ids[0]))
    for index, alignment in enumerate(alignments):
        labels[alignment.id] = f"{prefix}alignment:{index}"
        for side, members in (
            ("source", alignment.source_segment_ids),
            ("target", alignment.target_segment_ids),
        ):
            for member_index, segment_id in enumerate(members):
                labels[segment_id] = f"{prefix}segment:{index}:{side}:{member_index}"
                for token in ctx.repo.list_tokens(segment_id):
                    labels[token.id] = (
                        f"{prefix}token:{index}:{side}:{member_index}:{token.ordinal}"
                    )
    if token_run_id not in labels:
        labels[token_run_id] = f"{prefix}token-run"
    for index, edge in enumerate(_edges(ctx, token_run_id)):
        labels.setdefault(edge.id, f"{prefix}edge:{index}")
    return alignments


def _edges(ctx: AppContext, token_run_id: str) -> list[Any]:
    return ctx.repo.list_token_alignment_edges_for_run(token_run_id)


def _label_auxiliary_sources(
    repo: Any,
    labels: dict[str, str],
    segment_run_id: str,
    prefix: str,
) -> None:
    """Label every source an auxiliary flow draws on, so its benchmark keeps source ancestry."""
    source_ids = {
        source_id
        for source_id, _depth in repo.ancestors(
            next(iter(repo.list_segment_alignments_for_run(segment_run_id))).id
        )
        if repo.entity_type_of(source_id) is EntityType.SOURCE
    }
    for index, source_id in enumerate(sorted(source_ids)):
        labels.setdefault(source_id, f"{prefix}source{index}")


def _label_raw_segments(
    repo: Any, labels: dict[str, str], alignments: Sequence[Any], name: str
) -> None:
    """Label the raw segments the flow's normalized members were normalized from.

    ``normalized_from`` parents are distinct evidence identities: the raw observation is not the
    normalized segment that reached the alignment groups.
    """
    segment_ids = {
        segment_id
        for alignment in alignments
        for members in (alignment.source_segment_ids, alignment.target_segment_ids)
        for segment_id in members
    }
    raw_ids = sorted(
        {
            edge.to_id
            for segment_id in segment_ids
            for edge in repo.list_lineage_edges(segment_id, "out")
            if edge.kind is LineageKind.NORMALIZED_FROM
        }
    )
    for index, raw_id in enumerate(raw_ids):
        labels.setdefault(raw_id, f"{name}:{index}")
    object_ids = {
        edge.to_id
        for raw_id in raw_ids
        for edge in repo.list_lineage_edges(raw_id, "out")
        if edge.kind is LineageKind.EXTRACTED_FROM
    }
    for index, object_id in enumerate(sorted(object_ids)):
        labels.setdefault(object_id, f"{name.split(':', 1)[0]}-object:{index}")


def _label_flow_runs(
    repo: Any,
    labels: dict[str, str],
    segment_run_id: str,
    token_run_id: str,
    prefix: str = "",
) -> None:
    """Label a flow's own Stage 4/5 runs and the normalization/tokenization runs it pinned.

    Reports quote these run ids, so each one needs its own recognizable label rather than an
    opaque placeholder; without them identical ``<id>`` values would compare equal for
    different evidence identities.
    """
    labels.setdefault(segment_run_id, f"{prefix}segment-run")
    labels.setdefault(token_run_id, f"{prefix}token-run")
    for run_id in _upstream_run_ids(repo, segment_run_id, token_run_id):
        if run_id not in labels:
            labels[run_id] = f"{prefix}{repo.get_run(run_id).stage.value}-run"


def _upstream_run_ids(repo: Any, segment_run_id: str, token_run_id: str) -> list[str]:
    """Normalization and tokenization runs one flow's Stage 4/5 runs were pinned to."""
    run_ids: set[str] = set()
    for alignment in repo.list_segment_alignments_for_run(segment_run_id):
        for segment_id in alignment.source_segment_ids + alignment.target_segment_ids:
            run = repo.get_run(repo.get_segment(segment_id).run_id)
            if run.stage in (RunStage.NORMALIZATION, RunStage.TOKENIZATION):
                run_ids.add(run.id)
    token_run = repo.get_run(token_run_id)
    for key in ("source_tokenization_run_id", "target_tokenization_run_id"):
        value = token_run.config.get(key)
        if isinstance(value, str):
            run_ids.add(value)
    return sorted(run_ids)


def _gold_artifact_label(
    repo: Any, labels: dict[str, str], benchmark_run_id: str, name: str
) -> dict[str, str]:
    """Label the frozen gold artifact taken as an input by the benchmark run."""
    found: dict[str, str] = {}
    for object_id, role in repo.list_run_io(benchmark_run_id):
        if role is not RunIoRole.INPUT or object_id in labels:
            continue
        if repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
            continue
        artifact = repo.get_artifact(object_id)
        if artifact.schema_name == "alignment-gold":
            found[artifact.id] = name
    return found


def _input_run_labels(
    repo: Any, labels: dict[str, str], run_id: str, prefix: str
) -> dict[str, str]:
    """Label INPUT run I/O of one run (its selected upstream runs) with stable names."""
    found: dict[str, str] = {}
    for object_id, role in repo.list_run_io(run_id):
        if role is not RunIoRole.INPUT or object_id in labels:
            continue
        if repo.entity_type_of(object_id) is not EntityType.PROCESSING_RUN:
            continue
        stage = repo.get_run(object_id).stage.value
        found[object_id] = f"{prefix}{stage}-run"
    return found


def _extraction_run_labels(
    repo: Any, labels: dict[str, str], segment_run_id: str, prefix: str
) -> dict[str, str]:
    """Label the extraction runs whose objects feed one flow's segments and reports."""
    found: dict[str, str] = {}
    object_ids = {
        object_id
        for alignment in repo.list_segment_alignments_for_run(segment_run_id)
        for member_ids in (alignment.source_segment_ids, alignment.target_segment_ids)
        for object_id in member_ids
    }
    for object_id in sorted(object_ids):
        segment = repo.get_segment(object_id)
        run = repo.get_run(segment.run_id)
        if run.stage is not RunStage.NORMALIZATION:
            continue
        for input_id, role in repo.list_run_io(run.id):
            if role is not RunIoRole.INPUT or input_id in labels:
                continue
            if repo.entity_type_of(input_id) is EntityType.PROCESSING_RUN:
                found[input_id] = f"{prefix}extraction-run"
    return found


def _collect_reports(
    ctx: AppContext,
    labels: dict[str, str],
    runs: Iterable[tuple[str, str]],
) -> dict[str, Any]:
    """Read every run's output report artifact; ``list_run_io`` yields ``(id, role)``."""
    reports: dict[str, Any] = {}
    for run_id, name in runs:
        for object_id, role in ctx.repo.list_run_io(run_id):
            if role is not RunIoRole.OUTPUT:
                continue
            if ctx.repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
                continue
            artifact = ctx.repo.get_artifact(object_id)
            if artifact.schema_name is None:
                continue
            labels[artifact.id] = name
            payload = json.loads(ctx.artifact_store.read_bytes(artifact.sha256))
            reports[name] = _clean(payload, labels)
    return reports


def _validate_benchmark_report(report: Any) -> None:
    """A benchmark report must carry the transductive protocol and defined metrics."""
    assert isinstance(report, dict)
    assert report["protocol"] == "transductive_unsupervised"
    assert report["direction"] in {"forward", "reverse", "symmetrized"}
    assert report["schema"] == "benchmark-report"
    assert isinstance(report["gold_split"], list)
    metrics = report["metrics"]
    for key in ("total_predicted", "total_sure", "total_possible", "sure_hits", "possible_hits"):
        assert isinstance(metrics[key], int) and metrics[key] >= 0, key
    for key in ("precision", "recall", "f1", "aer"):
        assert metrics[key] is None or 0.0 <= metrics[key] <= 1.0, key
    assert isinstance(report["reasons"], list)


def _safe_label(value: str) -> str:
    return "<id>" if _ID.fullmatch(value) else value


def _segment_ref(ctx: AppContext, segment_id: str) -> str:
    locator = ctx.repo.get_segment(segment_id).locator
    return str(locator.get("ref", locator.get("row", "")))


def _clean(value: Any, labels: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _clean(item, labels) for key, item in value.items()}
    if isinstance(value, list):
        cleaned = [_clean(item, labels) for item in value]
        if len(cleaned) > 1 and all(isinstance(item, dict) for item in cleaned):
            return sorted(cleaned, key=lambda row: _sort_key(row))
        return cleaned
    if isinstance(value, str):
        if value in labels:
            return labels[value]
        if _ID.fullmatch(value):
            return "<id>"
        if _HASH.fullmatch(value):
            return "<hash>"
    return value


def _sort_key(row: dict[str, Any]) -> str:
    """Canonical sort key for report rows keyed by their labeled alignment id."""
    return str(row.get("alignment_id", ""))


def report_artifact(ctx: AppContext, run_id: str, schema_name: str) -> Any:
    """The output artifact of one run with a given schema name; used by tests."""
    for object_id, role in ctx.repo.list_run_io(run_id):
        if role is not RunIoRole.OUTPUT:
            continue
        if ctx.repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
            continue
        artifact = ctx.repo.get_artifact(object_id)
        if artifact.schema_name == schema_name:
            return artifact
    return None
