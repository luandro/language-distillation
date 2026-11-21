"""Human review queue service (M4-PLAN §6 WP4.8, ADR-0013 §4-5, REVIEW-WORKFLOW.md).

`ReviewService` owns the only path to `validated` or `rejected` lifecycle status: an
authorized human `ReviewDecision`. Invariants this service owns (AGENTS.md; M4-PLAN §3):

* **Authority precedes any write.** The acting reviewer is checked against the
  `ReviewAuthorityRegistry` for the target's language and domain, the reviewer role
  must equal the task's required role (a gate, not a routing hint), and
  `Operation.HUMAN_REVIEW` is resolved over the ancestor sources of the target — and,
  for `modify`, of the replacement object, which must also be a distinct, compatible
  successor (same language; for senses, the same lexeme). Any refusal raises before
  the transaction commits: an unauthorized or ungoverned decision changes nothing
  (invariant 3).
* **One decision per task.** Task read, authority and policy checks, and every write
  happen in one transaction behind a locked task reread (`get_review_task_for_update`),
  so interleaved decisions serialize and a resolved or cancelled queue entry takes no
  further decision.
* **Lifecycle legality.** `deprecated` is terminal: no decision revives it. `accept`
  moves `candidate`/`supported` to `validated` (never a rejected object); `reject`
  retires `candidate`/`supported`/`validated`; `modify` deprecates a
  `candidate`/`supported`/`validated` target and validates a `candidate`/`supported`
  successor. A supplied `target_version` pins the status-of-record the reviewer saw;
  a task about a moved object is refused.
* **Score and staleness (M4-PLAN C10).** Every lifecycle write recomputes the target's
  versioned `lexical-v1` score breakdown from its current evidence, so the audit
  breakdown is updated, never erased, and directly dependent records (the senses of a
  decided lexeme) are flagged with `stale_dependent` lineage edges (ADR-0014). Bounded
  direct-dependent recalculation is handled by `RecalcService` (WP5.14, Gate 43);
  cascading recalculation beyond direct dependents remains open (REVIEW-WORKFLOW.md
  §State transition).
* **Decisions are immutable and append-only.** Recording a decision inserts a new
  `ReviewDecision`; it never edits a previous one (REVIEW-WORKFLOW.md §Immutability).
* **Queue lineage (invariant 4).** A task derives from its target and its evidence
  bundle, and its creator run consumes both and produces the task, so ancestor source
  traversal reaches every review record (WP4.9 groundwork).
* **Concepts are queue-only.** Concepts carry no lifecycle status in the accepted
  model: `uncertain`/`defer` resolve the queue entry without touching anything, and
  lifecycle decisions are refused before any write.
* **M4 scope fence.** Only lexical task types are created in M4 (ADR-0013 §5).

Every queue entry must retain run lineage (invariant 4): when the caller supplies no
`creator_run_id`, the service persists a minimal succeeded `HUMAN_REVIEW` run as the
task's creator, keyed by the task id so entries never collide even under a fixed
clock. Errors carry identifiers and enum values only, never source content.
"""

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import JsonValue

from langpipe import __version__
from langpipe.domain.enums import (
    EntityType,
    LifecycleStatus,
    LineageKind,
    Operation,
    PolicyDecision,
    ReviewDecisionKind,
    ReviewTaskType,
    RunIoRole,
    RunStage,
    RunStatus,
    SourceStatus,
)
from langpipe.domain.errors import (
    InvalidLineage,
    InvalidTransition,
    NotFound,
    PolicyDenied,
    SchemaViolation,
)
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdFactory, IdPrefix
from langpipe.domain.ids import new_id as new_ulid
from langpipe.domain.models.base import UTC_NOW
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.review import REVIEW_TASK_STATUSES, ReviewDecision, ReviewTask
from langpipe.domain.models.run import ProcessingRun
from langpipe.governance import effective_policy
from langpipe.governance.lineage_policy import ancestor_source_ids
from langpipe.governance.policy import resolve
from langpipe.review.authority import ReviewAuthorityRegistry
from langpipe.review.base import M5_TASK_TYPES, UnauthorizedReviewer
from langpipe.review.targets import TargetHandler, get_target_handler
from langpipe.storage.repository import Repository

logger = logging.getLogger(__name__)

# Tool identity of the internal creator run recorded when a caller pins no run of its own.
_REVIEW_TOOL = "langpipe.review"

# Language tag standing in for objects no registry scope can name: concepts carry no
# language, so their queue-only decisions reduce to the required role (see base.py).
_UNSCOPED_LANGUAGE = "und"

# Targets a queue entry may name (WP4.8, WP5.13: lexeme, sense, concept, morpheme, morph_analysis).
_TASK_TARGET_TYPES = (
    EntityType.LEXEME,
    EntityType.SENSE,
    EntityType.CONCEPT,
    EntityType.MORPHEME,
    EntityType.MORPH_ANALYSIS,
)

# Legal source statuses per lifecycle decision; anything else (notably `deprecated`,
# which is terminal, and `rejected`, which accept never revives) is refused.
_LIFECYCLE_WRITES: dict[ReviewDecisionKind, tuple[LifecycleStatus, ...]] = {
    ReviewDecisionKind.ACCEPT: (LifecycleStatus.CANDIDATE, LifecycleStatus.SUPPORTED),
    ReviewDecisionKind.REJECT: (
        LifecycleStatus.CANDIDATE,
        LifecycleStatus.SUPPORTED,
        LifecycleStatus.VALIDATED,
    ),
    ReviewDecisionKind.MODIFY: (
        LifecycleStatus.CANDIDATE,
        LifecycleStatus.SUPPORTED,
        LifecycleStatus.VALIDATED,
    ),
}
# A successor must still be an open hypothesis to be validated by `modify`.
_SUPERSEDABLE: tuple[LifecycleStatus, ...] = (
    LifecycleStatus.CANDIDATE,
    LifecycleStatus.SUPPORTED,
)


@dataclass(frozen=True)
class ReviewDecisionResult:
    """The recorded decision, the target's new lifecycle status and the task's new state.

    `target_status` is `None` for `uncertain` and `defer`, which leave the target untouched.
    """

    decision: ReviewDecision
    target_status: LifecycleStatus | None
    task_status: str


class ReviewService:
    """Records authorized review decisions and applies their state transitions."""

    def __init__(
        self,
        repo: Repository,
        authority_registry: ReviewAuthorityRegistry,
        *,
        clock: Callable[[], datetime] | None = None,
        new_id: IdFactory | None = None,
        code_revision: str = "unknown",
    ) -> None:
        self.repo = repo
        self.authority = authority_registry
        self._clock = clock or UTC_NOW
        self._new_id = new_id or new_ulid
        self._code_revision = code_revision

    # --- queue ----------------------------------------------------------------------------

    def create_task(
        self,
        target_id: str,
        task_type: ReviewTaskType,
        required_role: str,
        frequency: float = 1.0,
        uncertainty: float = 1.0,
        downstream_impact: float = 1.0,
        evidence_conflict: float = 1.0,
        sensitivity: float = 1.0,
        reason: str = "Lexical candidate review",
        evidence_item_ids: Sequence[str] = (),
        target_version: str | None = None,
        creator_run_id: str | None = None,
    ) -> ReviewTask:
        """Queue one human review request about an existing target object."""
        if task_type not in M5_TASK_TYPES:
            raise ValueError("non-lexical task type rejected in M4")
        for name, value in (
            ("frequency", frequency),
            ("uncertainty", uncertainty),
            ("downstream_impact", downstream_impact),
            ("evidence_conflict", evidence_conflict),
            ("sensitivity", sensitivity),
        ):
            # A boolean factor would silently score 1.0 and a NaN factor would be swallowed
            # by the clamp below, so both are refused like every other score input.
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        now = self._clock()
        with self.repo.transaction():
            entity_type = self.repo.entity_type_of(target_id)
            if entity_type not in _TASK_TARGET_TYPES or entity_type is None:
                raise NotFound("object", target_id)
            handler = get_target_handler(entity_type)
            if task_type not in handler.allowed_task_types:
                if handler.entity_type in (EntityType.LEXEME, EntityType.SENSE, EntityType.CONCEPT):
                    raise ValueError("non-lexical task type rejected in M4")
                raise ValueError(
                    f"task type {task_type.value} not allowed for {handler.entity_type.value}"
                )
            if (
                task_type
                in (
                    ReviewTaskType.MORPHOLOGY_SEGMENTATION,
                    ReviewTaskType.MORPHEME_FUNCTION,
                )
                and required_role != "community_linguist"
            ):
                raise ValueError(f"required role for {task_type.value} must be community_linguist")
            self._ensure_not_revoked(target_id)
            if target_version is not None:
                self._require_version_matches(handler, target_id, target_version)
            task_id = self._new_id(IdPrefix.REVIEW_TASK)
            run_id = self._creator_run_id(target_id, task_type, task_id, creator_run_id, now)
            task = ReviewTask(
                id=task_id,
                task_type=ReviewTaskType(task_type),
                target_id=target_id,
                target_version=target_version,
                evidence_item_ids=list(evidence_item_ids),
                required_role=required_role,
                priority=max(
                    0.0,
                    float(
                        frequency
                        * uncertainty
                        * downstream_impact
                        * evidence_conflict
                        * sensitivity
                    ),
                ),
                reason=reason,
                creator_run_id=run_id,
                status="open",
                created_at=now,
            )
            self.repo.add_review_task(task)
            # Queue lineage (invariant 4): the task derives from its target and evidence,
            # so source ancestor traversal reaches the queue entry and its decisions.
            for parent_id in (task.target_id, *task.evidence_item_ids):
                self.repo.add_lineage_edge(
                    LineageEdge(
                        id=self._new_id(IdPrefix.LINEAGE),
                        from_id=task.id,
                        to_id=parent_id,
                        kind=LineageKind.DERIVED_FROM,
                        run_id=run_id,
                        created_at=now,
                    )
                )
            self.repo.add_run_io(run_id, task.target_id, RunIoRole.INPUT)
            for evidence_id in task.evidence_item_ids:
                self.repo.add_run_io(run_id, evidence_id, RunIoRole.INPUT)
            self.repo.add_run_io(run_id, task.id, RunIoRole.OUTPUT)
        return task

    def list_tasks(
        self,
        task_type: ReviewTaskType | None = None,
        required_role: str | None = None,
        limit: int | None = None,
        *,
        status: str | None = "open",
        min_priority: float | None = None,
        language: str | None = None,
    ) -> list[ReviewTask]:
        """Queue entries, highest priority first, optionally filtered and truncated.

        `status` defaults to the open queue; `None` lists every operational state.
        `min_priority` keeps entries at or above the threshold. `language` matches the
        target's language — a sense's through its lexeme; language-less targets
        (concepts) never match a language filter.
        """
        if limit is not None and limit < 0:
            raise ValueError("limit must be nonnegative")
        if status is not None and status not in REVIEW_TASK_STATUSES:
            raise ValueError("status must be an operational queue state")
        if min_priority is not None and (
            isinstance(min_priority, bool) or not math.isfinite(min_priority)
        ):
            raise ValueError("min_priority must be a finite number")
        tasks = self.repo.list_review_tasks(
            task_type=task_type,
            required_role=required_role,
            status=status,
            min_priority=min_priority,
        )
        if language is not None:
            tasks = [task for task in tasks if self._target_language(task.target_id) == language]
        if limit is not None:
            tasks = tasks[:limit]
        return tasks

    # --- decisions ------------------------------------------------------------------------

    def record_decision(
        self,
        task_id: str,
        decision: ReviewDecisionKind,
        reviewer_id: str,
        reviewer_role: str,
        superseding_object_id: str | None = None,
        notes: str | None = None,
    ) -> ReviewDecisionResult:
        """Record one immutable decision and apply its state transition, or change nothing."""
        now = self._clock()
        with self.repo.transaction():
            # Locked reread: interleaved decisions on one task serialize here, and a
            # resolved or cancelled queue entry is refused before anything is written.
            task = self.repo.get_review_task_for_update(task_id)  # NotFound when missing.
            if task.status != "open":
                raise InvalidTransition()
            entity_type = self.repo.entity_type_of(task.target_id)
            if entity_type is None or entity_type not in _TASK_TARGET_TYPES:
                raise NotFound("object", task.target_id)
            handler = get_target_handler(entity_type)

            # In a morphology modify decision where target and successor share entity type,
            # acquire row locks for update in deterministic sorted ID order to prevent AB-BA
            # deadlocks between opposing concurrent modify reviews.
            if (
                entity_type in (EntityType.MORPH_ANALYSIS, EntityType.MORPHEME)
                and decision is ReviewDecisionKind.MODIFY
                and superseding_object_id is not None
                and superseding_object_id != task.target_id
                and self.repo.entity_type_of(superseding_object_id) == entity_type
            ):
                first_id, second_id = sorted([task.target_id, superseding_object_id])
                handler.lock(self.repo, first_id)
                handler.lock(self.repo, second_id)
            else:
                handler.lock(self.repo, task.target_id)
            target_status = handler.status_of(self.repo, task.target_id)
            target_language = handler.language_of(self.repo, task.target_id)
            target_domain = handler.domain_of(self.repo, task.target_id)

            handler.check_decision_legal(self.repo, task.target_id, decision)

            # The pin names the status-of-record the reviewer saw; a moved object is
            # refused instead of decided under a stale version. An unpinned task checks
            # nothing: only an explicit pin carries the reviewer's version expectation.
            if task.target_version is not None and (
                target_status is None or task.target_version != target_status.value
            ):
                raise InvalidTransition()
            # The task's required role is a gate, not a routing hint; registry scope is
            # checked on top of it.
            if reviewer_role != task.required_role:
                raise UnauthorizedReviewer(reviewer_id, reviewer_role, target_language)
            if entity_type is EntityType.CONCEPT:
                # Nothing in the decision mutates the target, so authority reduces to the
                # required role held by a registered reviewer.
                if not self.authority.holds_role(reviewer_id, reviewer_role):
                    raise UnauthorizedReviewer(reviewer_id, reviewer_role, target_language)
            else:
                if not self.authority.is_authorized(
                    reviewer_id, reviewer_role, target_language, target_domain
                ):
                    raise UnauthorizedReviewer(reviewer_id, reviewer_role, target_language)
                self._ensure_human_review_allowed(task.target_id)

            successor: Any = None
            if decision is ReviewDecisionKind.MODIFY:
                successor = handler.check_successor(
                    self.repo, task.target_id, superseding_object_id
                )
                successor_domain = handler.domain_of(self.repo, successor.id)
                successor_lang = handler.language_of(self.repo, successor.id)
                if not self.authority.is_authorized(
                    reviewer_id, reviewer_role, successor_lang, successor_domain
                ):
                    raise UnauthorizedReviewer(reviewer_id, reviewer_role, successor_lang)
                self._ensure_human_review_allowed(successor.id)
                if successor.status not in _SUPERSEDABLE:
                    raise InvalidTransition()
                assert target_status is not None
                self._require_transition_legal(target_status, decision)
            elif decision in _LIFECYCLE_WRITES:
                assert target_status is not None
                self._require_transition_legal(target_status, decision)

            rev_dec = ReviewDecision(
                id=self._new_id(IdPrefix.REVIEW_DECISION),
                task_id=task.id,
                target_id=task.target_id,
                decision=decision,
                reviewer_id=reviewer_id,
                reviewer_role=reviewer_role,
                superseding_object_id=superseding_object_id,
                notes=notes,
                created_at=now,
            )
            self.repo.add_review_decision(rev_dec)
            new_target_status = self._transition_target(
                decision, handler, task, target_language, successor, now
            )
            if entity_type in (EntityType.MORPH_ANALYSIS, EntityType.MORPHEME):
                new_task_status = "resolved"
            else:
                new_task_status = "open" if decision is ReviewDecisionKind.DEFER else "resolved"
            self.repo.set_review_task_status(task.id, new_task_status)
            # The decision is a new derived object: its lineage names the queue entry it
            # answers (invariant 4).
            self.repo.add_lineage_edge(
                LineageEdge(
                    id=self._new_id(IdPrefix.LINEAGE),
                    from_id=rev_dec.id,
                    to_id=task.id,
                    kind=LineageKind.DERIVED_FROM,
                    run_id=task.creator_run_id,
                    created_at=now,
                )
            )
        logger.info(
            "review decision recorded: task=%s decision=%s target_status=%s",
            task.id,
            decision.value,
            new_target_status.value if new_target_status is not None else "unchanged",
        )
        return ReviewDecisionResult(
            decision=rev_dec, target_status=new_target_status, task_status=new_task_status
        )

    # --- helpers --------------------------------------------------------------------------

    def _creator_run_id(
        self,
        target_id: str,
        task_type: ReviewTaskType,
        task_id: str,
        creator_run_id: str | None,
        now: datetime,
    ) -> str:
        """The caller's run, or a minimal succeeded review run owning this queue entry.

        The repositories require every queue entry to name an existing run (invariant 4);
        a caller without a run of its own gets one pinned to exactly this task creation.
        The task id is part of the run identity, so two entries never share a run key
        even when the clock is fixed and only their ids differ.
        """
        if creator_run_id is not None:
            return creator_run_id
        config: dict[str, JsonValue] = {
            "purpose": "review_task",
            "target_id": target_id,
            "task_type": ReviewTaskType(task_type).value,
            "task_id": task_id,
        }
        digest = config_hash(config)
        run = ProcessingRun(
            id=self._new_id(IdPrefix.RUN),
            stage=RunStage.HUMAN_REVIEW,
            tool_name=_REVIEW_TOOL,
            tool_version=__version__,
            config=config,
            config_hash=digest,
            code_revision=self._code_revision,
            run_key=ProcessingRun.compute_run_key(
                RunStage.HUMAN_REVIEW, _REVIEW_TOOL, __version__, digest, ()
            ),
            status=RunStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
        )
        self.repo.add_run(run)
        return str(run.id)

    def _require_version_matches(
        self, handler: TargetHandler, target_id: str, target_version: str
    ) -> None:
        """Refuse a pin that does not name the target's current status-of-record.

        Concepts carry no lifecycle state, so there is nothing a pin could name.
        """
        current_status = handler.status_of(self.repo, target_id)
        if current_status is None:
            raise SchemaViolation()
        if target_version != current_status.value:
            raise SchemaViolation()

    def _target_language(self, target_id: str) -> str | None:
        """The target's language; a sense's through its lexeme; `None` when unnamable."""
        entity_type = self.repo.entity_type_of(target_id)
        if entity_type is None or entity_type not in _TASK_TARGET_TYPES:
            return None
        lang = get_target_handler(entity_type).language_of(self.repo, target_id)
        return None if lang == _UNSCOPED_LANGUAGE else lang

    def _ensure_not_revoked(self, target_id: str) -> None:
        """Refuse new queue entries for targets with a revoked source ancestor."""
        for source_id in ancestor_source_ids(self.repo, target_id):
            if self.repo.get_source(source_id).status is SourceStatus.REVOKED:
                raise PolicyDenied(source_id, Operation.HUMAN_REVIEW, PolicyDecision.DENY)

    def _ensure_human_review_allowed(self, target_id: str) -> None:
        """Resolve `Operation.HUMAN_REVIEW` over every ancestor source, or refuse."""
        sources = ancestor_source_ids(self.repo, target_id)
        if not sources:
            # Fail closed, matching effective_decision: no governing source, no permission.
            raise InvalidLineage()
        for source_id in sources:
            source = self.repo.get_source(source_id)
            if source.status is SourceStatus.REVOKED:
                raise PolicyDenied(source_id, Operation.HUMAN_REVIEW, PolicyDecision.DENY)
            policy = effective_policy(self.repo, source)
            resolved = resolve(policy, Operation.HUMAN_REVIEW)
            if resolved is not PolicyDecision.ALLOW:
                raise PolicyDenied(source_id, Operation.HUMAN_REVIEW, resolved)

    @staticmethod
    def _require_transition_legal(current: LifecycleStatus, decision: ReviewDecisionKind) -> None:
        """Refuse lifecycle writes that legality forbids; `deprecated` is terminal."""
        if current not in _LIFECYCLE_WRITES[decision]:
            raise InvalidTransition()

    def _transition_target(
        self,
        decision: ReviewDecisionKind,
        handler: TargetHandler,
        task: ReviewTask,
        target_language: str,
        successor: Any,
        now: datetime,
    ) -> LifecycleStatus | None:
        """Apply the decision's target transition inside the caller's transaction."""
        if decision is ReviewDecisionKind.ACCEPT:
            handler.set_status(
                self.repo, task.target_id, LifecycleStatus.VALIDATED, target_language
            )
            self._flag_dependents_stale(handler, task.target_id, task.creator_run_id, now)
            return LifecycleStatus.VALIDATED
        if decision is ReviewDecisionKind.REJECT:
            handler.set_status(self.repo, task.target_id, LifecycleStatus.REJECTED, target_language)
            self._flag_dependents_stale(handler, task.target_id, task.creator_run_id, now)
            return LifecycleStatus.REJECTED
        if decision is ReviewDecisionKind.MODIFY and successor is not None:
            handler.set_status(
                self.repo, task.target_id, LifecycleStatus.DEPRECATED, target_language
            )
            self._flag_dependents_stale(handler, task.target_id, task.creator_run_id, now)
            handler.set_status(self.repo, successor.id, LifecycleStatus.VALIDATED, target_language)
            self._flag_dependents_stale(handler, successor.id, task.creator_run_id, now)
            # The successor, not the service, carries the supersession: lineage stays
            # relational and queryable (invariant 4).
            self.repo.add_lineage_edge(
                LineageEdge(
                    id=self._new_id(IdPrefix.LINEAGE),
                    from_id=successor.id,
                    to_id=task.target_id,
                    kind=LineageKind.SUPERSEDES,
                    run_id=task.creator_run_id,
                    created_at=now,
                )
            )
            return LifecycleStatus.DEPRECATED
        return None

    def _flag_dependents_stale(
        self, handler: TargetHandler, object_id: str, run_id: str, now: datetime
    ) -> None:
        """Flag the decided object's directly dependent records as stale.

        Minimal explicit representation (ADR-0014): a `stale_dependent` lineage edge
        from each dependent to the decided object, visible traversing forward from it.
        Cascading recalculation of those dependents remains future work (M4-PLAN C10).
        """
        for dep_id in handler.dependents(self.repo, object_id):
            self.repo.add_lineage_edge(
                LineageEdge(
                    id=self._new_id(IdPrefix.LINEAGE),
                    from_id=dep_id,
                    to_id=object_id,
                    kind=LineageKind.STALE_DEPENDENT,
                    run_id=run_id,
                    created_at=now,
                )
            )


__all__ = ["ReviewDecisionResult", "ReviewService"]
