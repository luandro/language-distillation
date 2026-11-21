"""Bounded direct-dependent recalculation service (M5-PLAN §7.12, WP5.14, Gate 43).

Contracts under test:
- Stale ⇔ the dependent has a `stale_dependent` lineage edge with no later
  `recalculated` edge from the same dependent to the same decided object.
- `RecalcService.recalculate(object_ids | all_stale)`:
  recomputes each stale dependent's score breakdown under its own policy
  (`lexical-v1` or `morph-v1`), keeping its lifecycle status unchanged
  (recalculation never promotes past `supported`, and never demotes a `validated` object);
  writes a `recalculated` edge (dependent → decided object) under a `HUMAN_REVIEW`-stage
  maintenance run; idempotent.
- Depth is bounded by the M5 graph (lexeme → senses; morpheme → analyses);
  deeper cascades remain OPEN:
  TODO: REVIEW-WORKFLOW.md §State transition — cascading recalculation beyond
  direct dependents remains open.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue

from langpipe import __version__
from langpipe.app_context import AppContext
from langpipe.domain.enums import LineageKind, RunStage, RunStatus
from langpipe.domain.errors import NotFound
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdPrefix
from langpipe.domain.ids import new_id as default_new_id
from langpipe.domain.models.base import UTC_NOW
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import ProcessingRun
from langpipe.review.targets import get_target_handler
from langpipe.storage.repository import Repository

_RECALC_TOOL = "langpipe.review.recalc"


def is_stale(repo: Repository, object_id: str) -> bool:
    """Return True iff object_id has an unresolved stale_dependent edge.

    Stale ⇔ the dependent has a `stale_dependent` edge with no later `recalculated`
    edge from the same dependent to the same decided object (M5-PLAN §7.12).
    """
    edges = repo.list_lineage_edges(object_id, direction="out")
    stale_edges = [e for e in edges if e.kind is LineageKind.STALE_DEPENDENT]
    if not stale_edges:
        return False
    recalc_edges = [e for e in edges if e.kind is LineageKind.RECALCULATED]
    for s_edge in stale_edges:
        has_recalc = any(
            r_edge.to_id == s_edge.to_id and r_edge.created_at >= s_edge.created_at
            for r_edge in recalc_edges
        )
        if not has_recalc:
            return True
    return False


def stale_decided_targets(repo: Repository, object_id: str) -> list[str]:
    """Return all decided object IDs for which object_id has an unresolved stale flag."""
    edges = repo.list_lineage_edges(object_id, direction="out")
    stale_edges = [e for e in edges if e.kind is LineageKind.STALE_DEPENDENT]
    recalc_edges = [e for e in edges if e.kind is LineageKind.RECALCULATED]
    targets: set[str] = set()
    for s_edge in stale_edges:
        has_recalc = any(
            r_edge.to_id == s_edge.to_id and r_edge.created_at >= s_edge.created_at
            for r_edge in recalc_edges
        )
        if not has_recalc:
            targets.add(s_edge.to_id)
    return sorted(targets)


def find_all_stale(repo: Repository) -> list[str]:
    """Find all object IDs in the repository with unresolved stale flags."""
    stale_edges = repo.list_lineage_edges_by_kind(LineageKind.STALE_DEPENDENT)
    candidate_ids = {e.from_id for e in stale_edges}
    return sorted([oid for oid in candidate_ids if is_stale(repo, oid)])


@dataclass(frozen=True)
class RecalcResult:
    """Outcome of a recalculation run."""

    run: ProcessingRun
    recalculated_ids: tuple[str, ...]
    skipped_ids: tuple[str, ...]


class RecalcService:
    """Service for bounded direct-dependent recalculation."""

    def __init__(
        self,
        target: AppContext | Repository,
        *,
        clock: Callable[[], datetime] | None = None,
        new_id: Callable[[IdPrefix], str] | None = None,
        code_revision: str | None = None,
    ) -> None:
        if isinstance(target, AppContext):
            self.repo = target.repo
            self._clock = clock or target.clock
            self._new_id = new_id or target.new_id
            self._code_revision = code_revision or target.code_revision
        else:
            self.repo = target
            self._clock = clock or UTC_NOW
            self._new_id = new_id or default_new_id
            self._code_revision = code_revision or "dev"

    def recalculate(
        self,
        object_ids: Sequence[str] | None = None,
        *,
        all_stale: bool = False,
    ) -> RecalcResult:
        """Recalculate score breakdowns for stale dependents.

        Either `all_stale=True` or a non-empty `object_ids` sequence must be provided,
        not both.
        """
        if all_stale and object_ids:
            raise ValueError("cannot specify both object_ids and all_stale")
        if not all_stale and not object_ids:
            raise ValueError("must specify either object_ids or all_stale=True")

        if all_stale:
            targets = find_all_stale(self.repo)
        else:
            assert object_ids is not None
            for oid in object_ids:
                if self.repo.entity_type_of(oid) is None:
                    raise NotFound("object", oid)
            targets = list(object_ids)

        with self.repo.transaction():
            now = self._clock()
            recalc_targets: list[str] = []
            skipped_targets: list[str] = []
            stale_map: dict[str, list[str]] = {}

            for oid in targets:
                decided_ids = stale_decided_targets(self.repo, oid)
                if decided_ids:
                    recalc_targets.append(oid)
                    stale_map[oid] = decided_ids
                else:
                    skipped_targets.append(oid)

            for oid in recalc_targets:
                entity_type = self.repo.entity_type_of(oid)
                if entity_type is None:
                    raise NotFound("object", oid)
                handler = get_target_handler(entity_type)
                status = handler.status_of(self.repo, oid)
                if status is None:
                    raise NotFound("object", oid)
                lang = handler.language_of(self.repo, oid)
                # Recomputes breakdown under entity's own policy with status UNCHANGED.
                handler.set_status(self.repo, oid, status, lang)

            # Record maintenance run
            run_id = self._new_id(IdPrefix.RUN)
            config: dict[str, JsonValue] = {
                "purpose": "recalculate_stale_dependents",
                "run_id": run_id,
                "recalculated_targets": list(recalc_targets),
                "skipped_targets": list(skipped_targets),
            }
            digest = config_hash(config)
            run = ProcessingRun(
                id=run_id,
                stage=RunStage.HUMAN_REVIEW,
                tool_name=_RECALC_TOOL,
                tool_version=__version__,
                config=config,
                config_hash=digest,
                code_revision=self._code_revision,
                run_key=ProcessingRun.compute_run_key(
                    RunStage.HUMAN_REVIEW, _RECALC_TOOL, __version__, digest, ()
                ),
                status=RunStatus.SUCCEEDED,
                started_at=now,
                finished_at=now,
            )
            self.repo.add_run(run)

            # Write recalculated edges for each resolved decided target
            for oid in recalc_targets:
                for decided_id in stale_map[oid]:
                    self.repo.add_lineage_edge(
                        LineageEdge(
                            id=self._new_id(IdPrefix.LINEAGE),
                            from_id=oid,
                            to_id=decided_id,
                            kind=LineageKind.RECALCULATED,
                            run_id=run_id,
                            created_at=now,
                        )
                    )

            # Depth is bounded by the M5 graph (lexeme → senses; morpheme → analyses).
            # TODO: REVIEW-WORKFLOW.md §State transition — cascading recalculation beyond
            # direct dependents remains open.

            return RecalcResult(
                run=run,
                recalculated_ids=tuple(recalc_targets),
                skipped_ids=tuple(skipped_targets),
            )


__all__ = [
    "RecalcResult",
    "RecalcService",
    "find_all_stale",
    "is_stale",
    "stale_decided_targets",
]
