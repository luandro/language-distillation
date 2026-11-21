"""ID-free projection for the M4 golden lexical world (WP4.11 spec §5).

Every section is derived from persisted state plus the two export output directories.
Upstream objects reuse the M1-M3 naming so a reader can cross-reference them
(``src:<key>``, form keys, ``seg``/``tok``/``edge``); M4 objects are labeled
semantically (``lex:<source-key>:<headword>``, ``sense:...``, ``link:...``,
``ev:<target>:<n>``, ``task:T<n>``, ``dec:T<n>``, ``run:<stage>:<source-key>``,
``run:export:pre``, ``run:review:T<n>``, ``artifact:<run label>:<schema or file>``).
The walk at the end fails if any raw ULID survives unlabeled, and the whole snapshot
carries no timestamps; config/selection/artifact digests are masked ``<sha256>``.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from langpipe.app_context import AppContext
from langpipe.cldf.exporter import EXPORT_REPORT_SCHEMA, CLDFExportResult
from langpipe.domain.enums import EntityType, LineageKind, RunIoRole, RunStage
from langpipe.domain.hashing import canonical_json
from langpipe.domain.models.lexical import LexicalScoreBreakdown
from langpipe.governance.lineage_policy import ancestor_source_ids, lineage_eligibility
from langpipe.ingest.wordlist import REPORT_SCHEMA as WORDLIST_REPORT_SCHEMA
from langpipe.lexicon.adapters.alignment import PRIMARY_LEMMA_ROLE
from langpipe.lexicon.service import REPORT_SCHEMA as INDUCTION_REPORT_SCHEMA
from langpipe.storage.repository import Repository

if TYPE_CHECKING:
    from tests.golden.test_golden_m4 import _M4World

_ID = re.compile(r"^[a-z]+_[0-9A-HJKMNP-TV-Z]{26}$")

SOURCE_KEYS = ("01-parallel-distill", "03-wordlist", "golden-lexicon-export")
KEY01 = "01-parallel-distill"
EXPORT_KEY = "golden-lexicon-export"
LANGUAGE = "qaa"


def normalize_m4_snapshot(ctx: AppContext, world: _M4World) -> dict[str, Any]:
    """Project the M4 world into the nine ID-free snapshot sections (spec §5.2)."""
    repo = ctx.repo
    labels: dict[str, str] = {}
    taken: dict[str, str] = {}

    def bind(object_id: str, label: str) -> str:
        existing = labels.get(object_id)
        if existing is not None:
            assert existing == label, f"conflicting labels for one id: {existing} != {label}"
            return existing
        clash = taken.get(label)
        assert clash is None or clash == object_id, f"label reused: {label}"
        labels[object_id] = label
        taken[label] = object_id
        return label

    m4_ids: set[str] = set()
    _bind_upstream(ctx, world, bind)
    _bind_lexical(ctx, world, labels, bind, m4_ids)
    _bind_review(world, bind, m4_ids)
    _bind_reports(ctx, world, labels, bind, m4_ids)

    snapshot = {
        "runs": _runs_section(ctx, world, labels),
        "lexemes": _lexemes_section(ctx, world, labels),
        "senses": _senses_section(ctx, world, labels),
        "evidence": _evidence_section(ctx, world, labels),
        "review": _review_section(world, labels),
        "lineage": _lineage_section(repo, labels, m4_ids),
        "export": _export_section(ctx, world, labels),
        "revocation": _revocation_section(ctx, world, labels),
        "reports": _reports_section(ctx, world, labels),
    }
    _assert_no_raw_ids(snapshot)
    return snapshot


def lexeme_headword(repo: Repository, lexeme_id: str) -> str | None:
    """The headword a lexeme is known by: its lemma form text, else its headword claim."""
    for link in repo.list_form_lexeme_links_for_lexeme(lexeme_id):
        if link.role == PRIMARY_LEMMA_ROLE:
            return str(repo.get_form(link.form_id).text)
    for item in repo.list_evidence_for_target(lexeme_id):
        claim = item.claim or {}
        if "headword" in claim:
            return str(claim["headword"])
    return None


def _sense_gloss(sense: Any) -> str:
    return str(sense.glosses[sorted(sense.glosses)[0]][0])


def flow_extraction_run(repo: Repository, world: _M4World) -> Any:
    """The extraction run that produced the raw segments the sentences flow normalized."""
    return _extraction_run_of(repo, world.flow)


def _extraction_run_of(repo: Repository, flow: Any) -> Any:
    """The extraction run that produced the raw segments one flow normalized."""
    for object_id, role in repo.list_run_io(flow.normalization.run.id):
        if role is not RunIoRole.INPUT:
            continue
        if repo.entity_type_of(object_id) is not EntityType.SEGMENT:
            continue
        raw = repo.get_segment(object_id)
        if raw.normalization_profile is None:
            return repo.get_run(raw.run_id)
    raise AssertionError("normalization without raw extraction inputs")


def _segment_ref(segment: Any) -> str:
    locator = segment.locator
    return str(locator.get("ref", locator.get("row", "")))


def _segment_label(prefix: str, segment: Any) -> str:
    base = f"{prefix}:{segment.language}:{_segment_ref(segment)}"
    part = segment.locator.get("sentence_part")
    return base if part is None else f"{base}:{part}"


def _labeled(value: str, labels: dict[str, str]) -> str:
    if value in labels:
        return labels[value]
    assert _ID.fullmatch(value) is None, f"unlabeled identifier: {value}"
    return value


# --- labeling ----------------------------------------------------------------------------


def _bind_upstream(ctx: AppContext, world: _M4World, bind: Callable[[str, str], str]) -> None:
    """Sources, source objects, the flow's segments/tokens/forms and alignment rows."""
    repo = ctx.repo
    flow = world.flow
    for key in SOURCE_KEYS:
        bind(world.source(key), f"src:{key}")
        for obj in repo.list_source_objects(world.source(key)):
            bind(obj.id, f"sobj:{key}/{obj.original_path}")

    for run in (
        flow.registration.run,
        _ingestion_run(repo, world, KEY01),
        flow_extraction_run(repo, world),
        flow.normalization.run,
        flow.tokenization.run,
        world.aligned.segment.run,
        world.aligned.token.run,
    ):
        bind(run.id, f"run:{run.stage.value}:{KEY01}")
    for segment in repo.list_segments_for_run(_extraction_run_of(repo, flow).id):
        bind(segment.id, _segment_label("segraw", segment))
    for segment in repo.list_segments_for_run(flow.normalization.run.id):
        bind(segment.id, _segment_label("seg", segment))
        for token in repo.list_tokens(segment.id):
            if token.run_id != flow.tokenization_run_id:
                continue
            bind(token.id, f"{_segment_label('tok', segment)}:{token.ordinal}")
            if token.form_id is not None:
                form = repo.get_form(token.form_id)
                bind(form.id, f"{form.language}/{form.orthography_profile}/{form.text}")

    alignments = repo.list_segment_alignments_for_run(world.aligned.segment_run_id)
    for alignment in alignments:
        first = repo.get_segment(alignment.source_segment_ids[0])
        bind(alignment.id, f"sal:{KEY01}:{_segment_ref(first)}")
    for edge in repo.list_token_alignment_edges_for_run(world.aligned.token_run_id):
        group = next(item for item in alignments if item.id == edge.segment_alignment_id)
        ref = _segment_ref(repo.get_segment(group.source_segment_ids[0]))
        source_index = _side_index(repo, flow, group.source_segment_ids, edge.source_token_id)
        target_index = _side_index(repo, flow, group.target_segment_ids, edge.target_token_id)
        bind(
            edge.id,
            f"edge:{KEY01}:{ref}:{source_index}->{target_index}:{edge.direction.value}",
        )


def _side_index(
    repo: Repository, flow: Any, segment_ids: Sequence[str], token_id: str | None
) -> int:
    index = 0
    for segment_id in segment_ids:
        for token in repo.list_tokens(segment_id):
            if token.run_id != flow.tokenization_run_id:
                continue
            if token.id == token_id:
                return index
            index += 1
    raise AssertionError(token_id)


def _ingestion_run(repo: Repository, world: _M4World, source_key: str) -> Any:
    objects = repo.list_source_objects(world.source(source_key))
    runs = repo.list_runs_with_input(objects[0].id, RunStage.RAW_INGESTION)
    assert len(runs) == 1, source_key
    return runs[0]


def _bind_lexical(
    ctx: AppContext,
    world: _M4World,
    labels: dict[str, str],
    bind: Callable[[str, str], str],
    m4_ids: set[str],
) -> None:
    """Stage 6 runs, lexemes, senses, form links and their evidence items."""
    repo = ctx.repo
    runs = (
        (world.induce01.run, f"run:lexical_induction:{KEY01}"),
        (world.registration03.run, "run:source_registration:03-wordlist"),
        (world.extract03.run, "run:extraction:03-wordlist"),
        (_ingestion_run(repo, world, "03-wordlist"), "run:raw_ingestion:03-wordlist"),
        (world.induce03.run, "run:lexical_induction:03-wordlist"),
        (world.registration_export.run, f"run:source_registration:{EXPORT_KEY}"),
        (_ingestion_run(repo, world, EXPORT_KEY), f"run:raw_ingestion:{EXPORT_KEY}"),
        (world.extract_export.run, f"run:extraction:{EXPORT_KEY}"),
        (world.induce_export.run, f"run:lexical_induction:{EXPORT_KEY}"),
        (world.export_pre_run(), "run:export:pre"),
    )
    for run, label in runs:
        bind(run.id, label)
        m4_ids.add(run.id)

    source_by_id = {world.source(key): key for key in SOURCE_KEYS}
    lexemes = repo.list_lexemes_by_language(LANGUAGE)
    headwords: dict[str, str] = {}
    for lexeme in lexemes:
        source_key = source_by_id[ancestor_source_ids(repo, lexeme.id)[0]]
        headword = lexeme_headword(repo, lexeme.id)
        assert headword is not None, lexeme.id
        headwords[lexeme.id] = headword
        bind(lexeme.id, f"lex:{source_key}:{headword}")
        m4_ids.add(lexeme.id)
        for link in repo.list_form_lexeme_links_for_lexeme(lexeme.id):
            bind(link.id, f"link:{labels[lexeme.id]}")
            m4_ids.add(link.id)
    for lexeme in lexemes:
        for sense in repo.list_senses_for_lexeme(lexeme.id):
            source_key = source_by_id[ancestor_source_ids(repo, lexeme.id)[0]]
            bind(sense.id, f"sense:{source_key}:{headwords[lexeme.id]}:{_sense_gloss(sense)}")
            m4_ids.add(sense.id)
    for lexeme in lexemes:
        items = sorted(
            repo.list_evidence_for_target(lexeme.id),
            key=lambda item: _evidence_sort_key(repo, labels, item),
        )
        for number, item in enumerate(items, start=1):
            bind(item.id, f"ev:{labels[lexeme.id]}:{number}")
            m4_ids.add(item.id)


def _evidence_sort_key(repo: Repository, labels: dict[str, str], item: Any) -> tuple[str, str, str]:
    """Kind, canonical claim, then the label of the observation the item documents."""
    observation = ""
    for edge in repo.list_lineage_edges(item.id, "out"):
        if edge.kind is LineageKind.DERIVED_FROM and edge.to_id in labels:
            observation = labels[edge.to_id]
            break
    return (item.kind.value, canonical_json(item.claim or {}), observation)


def _bind_review(world: _M4World, bind: Callable[[str, str], str], m4_ids: set[str]) -> None:
    """Review tasks, their creator runs and the recorded decisions."""
    for name in sorted(world.tasks):
        task = world.tasks[name]
        bind(task.id, f"task:{name}")
        bind(task.creator_run_id, f"run:review:{name}")
        m4_ids.add(task.id)
        m4_ids.add(task.creator_run_id)
    for name in sorted(world.decisions):
        decision = world.decisions[name].decision
        bind(decision.id, f"dec:{name}")
        m4_ids.add(decision.id)


def _bind_reports(
    ctx: AppContext,
    world: _M4World,
    labels: dict[str, str],
    bind: Callable[[str, str], str],
    m4_ids: set[str],
) -> None:
    """Report artifacts of the M4 runs, the export's file artifacts and the flow reports."""
    repo = ctx.repo
    # The export run is handled separately: its file artifacts all share one schema_name,
    # so they take their file names as the label tail (spec §5.3: schema or file name).
    for run in (
        world.induce01.run,
        world.extract03.run,
        _ingestion_run(repo, world, "03-wordlist"),
        world.induce03.run,
        world.extract_export.run,
        _ingestion_run(repo, world, EXPORT_KEY),
        world.induce_export.run,
        world.flow.registration.run,
        _ingestion_run(repo, world, KEY01),
        flow_extraction_run(repo, world),
        world.flow.normalization.run,
        world.flow.tokenization.run,
        world.aligned.segment.run,
        world.aligned.token.run,
    ):
        for object_id, role in repo.list_run_io(run.id):
            if role is not RunIoRole.OUTPUT:
                continue
            if repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
                continue
            artifact = repo.get_artifact(object_id)
            if artifact.schema_name is None:
                continue
            bind(artifact.id, f"artifact:{labels[run.id]}:{artifact.schema_name}")
            m4_ids.add(artifact.id)
    pre = world.require_export_pre()
    bind(pre.report.id, f"artifact:{labels[pre.run.id]}:{EXPORT_REPORT_SCHEMA}")
    m4_ids.add(pre.report.id)
    names = _file_names(ctx, pre)
    for artifact in pre.files:
        bind(artifact.id, f"artifact:{labels[pre.run.id]}:{names[artifact.sha256]}")
        m4_ids.add(artifact.id)


def _file_names(ctx: AppContext, pre: CLDFExportResult) -> dict[str, str]:
    payload = json.loads(ctx.artifact_store.read_bytes(pre.report.sha256))
    return {str(entry["sha256"]): str(entry["name"]) for entry in payload["files"]}


# --- sections ----------------------------------------------------------------------------


def _runs_section(ctx: AppContext, world: _M4World, labels: dict[str, str]) -> dict[str, Any]:
    repo = ctx.repo
    rows: dict[str, Any] = {}
    run_ids = [
        world.induce01.run.id,
        world.registration03.run.id,
        world.extract03.run.id,
        _ingestion_run(repo, world, "03-wordlist").id,
        world.induce03.run.id,
        world.registration_export.run.id,
        _ingestion_run(repo, world, EXPORT_KEY).id,
        world.extract_export.run.id,
        world.induce_export.run.id,
        world.export_pre_run().id,
        *(world.tasks[name].creator_run_id for name in sorted(world.tasks)),
    ]
    for run_id in run_ids:
        run = repo.get_run(run_id)
        method = run.config.get("method")
        rows[labels[run_id]] = {
            "stage": run.stage.value,
            "tool": run.tool_name,
            "method": method if isinstance(method, str) else None,
            "status": run.status.value,
            "config_hash": "<sha256>",
            "inputs": sorted(
                labels[object_id]
                for object_id, role in repo.list_run_io(run_id)
                if role is RunIoRole.INPUT
            ),
            "outputs": sorted(
                labels[object_id]
                for object_id, role in repo.list_run_io(run_id)
                if role is RunIoRole.OUTPUT
            ),
        }
    return rows


def _lexemes_section(ctx: AppContext, world: _M4World, labels: dict[str, str]) -> dict[str, Any]:
    repo = ctx.repo
    rows: dict[str, Any] = {}
    for lexeme in repo.list_lexemes_by_language(LANGUAGE):
        source_id = ancestor_source_ids(repo, lexeme.id)[0]
        rows[labels[lexeme.id]] = {
            "language": lexeme.language,
            "status": lexeme.status.value,
            "domain": lexeme.domain,
            "register": lexeme.register,
            "lemma_form": None if lexeme.lemma_form_id is None else labels[lexeme.lemma_form_id],
            "run": labels[lexeme.run_id],
            "source": labels[source_id],
            "headword": lexeme_headword(repo, lexeme.id),
        }
    return rows


def _senses_section(ctx: AppContext, world: _M4World, labels: dict[str, str]) -> dict[str, Any]:
    repo = ctx.repo
    rows: dict[str, Any] = {}
    for lexeme in repo.list_lexemes_by_language(LANGUAGE):
        for sense in repo.list_senses_for_lexeme(lexeme.id):
            rows[labels[sense.id]] = {
                "lexeme": labels[sense.lexeme_id],
                "glosses": sense.glosses,
                "domain": sense.domain,
                "register": sense.register,
                "status": sense.status.value,
                "breakdown": _breakdown(sense.score_breakdown, labels),
            }
    return rows


def _breakdown(breakdown: LexicalScoreBreakdown | None, labels: dict[str, str]) -> Any:
    if breakdown is None:
        return None
    return {
        "policy_version": breakdown.policy_version,
        "overall": round(breakdown.overall, 6),
        "components": {name: round(value, 6) for name, value in breakdown.components.items()},
        "penalties": {name: round(value, 6) for name, value in breakdown.penalties.items()},
        "independence_groups": [_labeled(axis, labels) for axis in breakdown.independence_groups],
    }


def _evidence_section(ctx: AppContext, world: _M4World, labels: dict[str, str]) -> dict[str, Any]:
    repo = ctx.repo
    rows: dict[str, Any] = {}
    for lexeme in repo.list_lexemes_by_language(LANGUAGE):
        items = sorted(
            repo.list_evidence_for_target(lexeme.id),
            key=lambda item: _evidence_sort_key(repo, labels, item),
        )
        rows[labels[lexeme.id]] = [
            {
                "kind": item.kind.value,
                "polarity": item.polarity.value,
                "strength": {name: round(value, 6) for name, value in item.strength.items()},
                "independence_group": (
                    None
                    if item.independence_group is None
                    else _labeled(item.independence_group, labels)
                ),
                "claim": item.claim,
                "domain": item.domain,
            }
            for item in items
        ]
    return rows


def _review_section(world: _M4World, labels: dict[str, str]) -> dict[str, Any]:
    repo = world.ctx.repo
    tasks: dict[str, Any] = {}
    for name in sorted(world.tasks):
        task = repo.get_review_task(world.tasks[name].id)
        tasks[f"task:{name}"] = {
            "type": task.task_type.value,
            "target": labels[task.target_id],
            "required_role": task.required_role,
            "priority": round(task.priority, 6),
            "status": task.status,
            "reason": task.reason,
            "evidence": sorted(labels[item] for item in task.evidence_item_ids),
            "run": labels[task.creator_run_id],
        }
    decisions: dict[str, Any] = {}
    for name in sorted(world.decisions):
        decision = repo.get_review_decision(world.decisions[name].decision.id)
        decisions[f"dec:{name}"] = {
            "task": labels[decision.task_id],
            "target": labels[decision.target_id],
            "kind": decision.decision.value,
            "reviewer_id": decision.reviewer_id,
            "reviewer_role": decision.reviewer_role,
            "superseding": (
                None
                if decision.superseding_object_id is None
                else labels[decision.superseding_object_id]
            ),
            "notes": decision.notes,
        }
    return {"tasks": tasks, "decisions": decisions}


def _lineage_section(repo: Repository, labels: dict[str, str], m4_ids: set[str]) -> list[list[str]]:
    """Every lineage edge with at least one endpoint among the M4 objects."""
    edges: set[tuple[str, str, str]] = set()
    for object_id in sorted(m4_ids):
        for edge in repo.list_lineage_edges(object_id, "out"):
            edges.add((labels[edge.from_id], labels[edge.to_id], edge.kind.value))
    return [[from_label, to_label, kind] for from_label, to_label, kind in sorted(edges)]


def _export_section(ctx: AppContext, world: _M4World, labels: dict[str, str]) -> dict[str, Any]:
    denials = [
        {"source": labels[source_id], "decision": decision}
        for source_id, decision in world.p12b_denials
    ]
    return {
        "pre": _export_result(ctx, world.require_export_pre(), labels),
        "post": _export_result(ctx, world.require_export_post(), labels),
        "p12b": {
            "operation": "redistribute_derived",
            "denials": sorted(denials, key=lambda row: (row["source"], row["decision"])),
        },
    }


def _export_result(
    ctx: AppContext, result: CLDFExportResult, labels: dict[str, str]
) -> dict[str, Any]:
    files = sorted(path.name for path in result.output_dir.iterdir())
    return {
        "reused": result.reused,
        "run": labels[result.run.id],
        "exported": result.exported,
        "omitted": result.omitted,
        "files": files,
        "entries": _csv_rows(result.output_dir / "entries.csv", labels),
        "senses": _csv_rows(result.output_dir / "senses.csv", labels),
    }


def _csv_rows(path: Any, labels: dict[str, str]) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        raw = list(csv.DictReader(handle))
    rows: list[dict[str, Any]] = []
    for row in raw:
        clean: dict[str, Any] = {}
        for column, value in row.items():
            if column is None:
                continue
            text = "" if value is None else str(value)
            clean[column] = labels.get(text, text) if text else text
        rows.append(clean)
    return sorted(rows, key=lambda row: str(row.get("ID", "")))


def _revocation_section(ctx: AppContext, world: _M4World, labels: dict[str, str]) -> dict[str, Any]:
    from tests.golden.test_golden_m4 import OPS  # avoids a runtime import cycle

    repo = ctx.repo
    impact = world.require_impact()
    by_type: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for entity_type, ids in impact.to_dict()["by_type"].items():
        by_type[str(entity_type)] = sorted(labels[object_id] for object_id in ids)
        counts[str(entity_type)] = len(ids)
    eligibility: dict[str, dict[str, list[str]]] = {}
    for object_id in sorted(set(impact.lexemes) | set(impact.senses)):
        before = world.pre_eligibility[object_id]
        eligibility[labels[object_id]] = {
            op.value: [before[op].value, lineage_eligibility(repo, object_id, op).value]
            for op in OPS
        }
    return {
        "source": labels[impact.source_id],
        "source_status": impact.source_status.value,
        "revoked": impact.revoked,
        "total": impact.total,
        "counts": counts,
        "ids": by_type,
        "validated_affected": sorted(labels[object_id] for object_id in impact.validated_affected),
        "entries": [
            {
                "object": labels[entry.object_id],
                "entity_type": entry.entity_type.value,
                "depth": entry.depth,
            }
            for entry in sorted(
                impact.entries, key=lambda item: (item.depth, labels[item.object_id])
            )
        ],
        "eligibility": eligibility,
    }


def _reports_section(ctx: AppContext, world: _M4World, labels: dict[str, str]) -> dict[str, Any]:
    repo = ctx.repo
    rows: dict[str, Any] = {}
    for run in (world.extract03.run, world.extract_export.run):
        payload = _payload_of(ctx, repo, run.id, WORDLIST_REPORT_SCHEMA)
        rows[labels[_artifact_of(repo, run.id, WORDLIST_REPORT_SCHEMA)]] = {
            "schema": payload["schema"],
            "schema_version": payload["schema_version"],
            "source": labels[str(payload["source_id"])],
            "run": labels[str(payload["run_id"])],
            "target_language": payload["target_language"],
            "contact_language": payload["contact_language"],
            "objects": [
                {
                    "object": labels[str(entry["source_object_id"])],
                    "sha256": entry["sha256"],
                    "size_bytes": entry["size_bytes"],
                }
                for entry in payload["objects"]
            ],
            "totals": payload["totals"],
        }
    for run in (world.induce01.run, world.induce03.run, world.induce_export.run):
        payload = _payload_of(ctx, repo, run.id, INDUCTION_REPORT_SCHEMA)
        rows[labels[_artifact_of(repo, run.id, INDUCTION_REPORT_SCHEMA)]] = {
            "schema": payload["schema"],
            "schema_version": payload["schema_version"],
            "run": labels[str(payload["run_id"])],
            "input_run": labels[str(payload["input_run_id"])],
            "method": payload["method"],
            "mode": payload["mode"],
            "target_language": payload["target_language"],
            "contact_language": payload["contact_language"],
            "totals": payload["totals"],
            "status_counts": payload["status_counts"],
        }
    pre = world.require_export_pre()
    payload = _payload_of(ctx, repo, pre.run.id, EXPORT_REPORT_SCHEMA)
    rows[labels[pre.report.id]] = {
        "schema": payload["schema"],
        "schema_version": payload["schema_version"],
        "run": labels[str(payload["run_id"])],
        "exporter_version": payload["exporter_version"],
        "dataset_module": payload["dataset_module"],
        "exported": payload["exported"],
        "omitted": payload["omitted"],
        "entries": sorted(labels[str(item)] for item in payload["entry_ids"]),
        "senses": sorted(labels[str(item)] for item in payload["sense_ids"]),
        "sources": sorted(labels[str(item)] for item in payload["source_ids"]),
        "files": [
            {"name": entry["name"], "sha256": "<sha256>", "size_bytes": entry["size_bytes"]}
            for entry in payload["files"]
        ],
    }
    return rows


def _payload_of(ctx: AppContext, repo: Repository, run_id: str, schema_name: str) -> dict[str, Any]:
    artifact = repo.get_artifact(_artifact_of(repo, run_id, schema_name))
    payload: dict[str, Any] = json.loads(ctx.artifact_store.read_bytes(artifact.sha256))
    return payload


def _artifact_of(repo: Repository, run_id: str, schema_name: str) -> str:
    for object_id, role in repo.list_run_io(run_id):
        if role is not RunIoRole.OUTPUT:
            continue
        if repo.entity_type_of(object_id) is not EntityType.ARTIFACT:
            continue
        if repo.get_artifact(object_id).schema_name == schema_name:
            return object_id
    raise AssertionError(schema_name)


def _assert_no_raw_ids(value: Any, path: str = "") -> None:
    """The whole snapshot must be free of unlabeled ULIDs (spec §5.3 rule 2)."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert _ID.fullmatch(str(key)) is None, f"unlabeled identifier at key {path}/{key}"
            _assert_no_raw_ids(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_raw_ids(item, f"{path}/{index}")
    elif isinstance(value, str):
        assert _ID.fullmatch(value) is None, f"unlabeled identifier at {path}"
