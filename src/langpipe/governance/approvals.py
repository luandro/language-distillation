"""Source-use approvals: the ADR-0018 overlay (M5-PLAN WP5.5).

`effective_policy` is the single governance door (ADR-0018 §6): every operation
decision in `langpipe` reads it, no caller consults approval rows or static policies
directly (guarded by `tests/unit/test_governance_single_door.py`). The overlay is
pure and computed:

* source permissions live in the stored, frozen `SourcePolicy`;
* per `(source, operation)` effective state is the latest `ApprovalAction` over the
  append-only `source_use_approval` rows — a reversal is a new `withdraw` append,
  never an edit (ADR-0018 §1, §5);
* only a `review` baseline may be lifted, and only for an operation on
  `APPROVABLE_OPERATIONS`; explicit `deny`, `default_deny` and `hard_deny`
  win over any approval (ADR-0018 §2);
* revoked sources are unaffected by approvals: revocation already denies
  everything, computed at decision time (ADR-0015), so `effective_policy` reads
  only policy mode and approval rows and carries no source-status shortcut that
  could mask a revocation elsewhere.

`record_approval` is the only writer of approval rows: it gates on the
`governance_steward` role of the `ReviewAuthorityRegistry` for one of the source's
languages (ADR-0018 §4) and atomically records a minimal succeeded `HUMAN_REVIEW`
run, the approval row and one audit event (review-service run precedent, invariant
4 — every governance write carries run lineage).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import JsonValue

from langpipe import __version__
from langpipe.domain.enums import (
    AccessClass,
    ApprovalAction,
    AuditEventType,
    Operation,
    PolicyMode,
    RunIoRole,
    RunStage,
    RunStatus,
)
from langpipe.domain.errors import PolicyConflict
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdFactory, IdPrefix
from langpipe.domain.ids import new_id as new_ulid
from langpipe.domain.models.approval import SourceUseApproval
from langpipe.domain.models.base import UTC_NOW
from langpipe.domain.models.run import AuditEvent, ProcessingRun
from langpipe.governance.policy import Baseline, baseline

ROLE_GOVERNANCE_STEWARD = "governance_steward"

if TYPE_CHECKING:
    from langpipe.domain.models.source import Source, SourcePolicy
    from langpipe.review.authority import ReviewAuthorityRegistry
    from langpipe.storage.repository import Repository

# M5 approvable operations (ADR-0018 §3): the list is exhaustive for M5.
# `direct_training` and `synthetic_generation_support` are refused until the owner
# returns (DELEGATED-DECISIONS §2); `audio_align` is deliberately not approvable in
# M5 (no M5 stage uses it); any outward operation (`third_party_api`,
# `cloud_processing`, `redistribute_*`) is never approvable, and neither is
# `human_review` — human review is the gate, not something approvals can waive.
APPROVABLE_OPERATIONS: frozenset[Operation] = frozenset(
    {
        Operation.READ_RAW,
        Operation.EXTRACT,
        Operation.NORMALIZE,
        Operation.ALIGN,
        Operation.DISTILL_LEXICON,
        Operation.DISTILL_MORPHOLOGY,
        Operation.DISTILL_GRAMMAR,
        Operation.EVALUATION,
    }
)

# Tool identity of the creator run recorded alongside every approval (ADR-0018 §1).
_APPROVAL_TOOL = "langpipe.governance"


@dataclass(frozen=True)
class EffectivePolicy:
    """Static policy with the ADR-0018 approval overlay applied to its `allow` list.

    Structurally satisfies `governance.policy.PolicyLike`, so `resolve`,
    `resolve_many` and the `governance.guard` entry points consume it unchanged.
    Carries access_class and metadata so downstream services inspect it without
    needing to query static policies directly.
    """

    id: str
    mode: PolicyMode
    access_class: AccessClass
    authority: str
    allow: tuple[Operation, ...] = ()
    deny: tuple[Operation, ...] = ()
    approved_operations: tuple[Operation, ...] = ()
    restrictions: dict[str, JsonValue] = field(default_factory=dict)
    policy_version: int = 1
    created_at: datetime | None = None


def _resolve_source(repo: Repository, source: Source | str) -> Source:
    """The registered source row, accepting an id or an already-loaded `Source`."""
    return repo.get_source(source) if isinstance(source, str) else source


def get_source_policy(repo: Repository, source: Source | str) -> SourcePolicy:
    """The stored, frozen static policy of one registered source.

    Governance-internal read: the single door exposes it only through
    `effective_policy`, which composes it with the approval overlay.
    """
    return repo.get_policy(_resolve_source(repo, source).policy_id)


def _latest_action(repo: Repository, source_id: str, operation: Operation) -> ApprovalAction | None:
    """The latest action over the append-only rows for `(source_id, operation)`.

    Ordered by `(created_at, id)`, so the maximal row is the authoritative
    effective state; `None` when no approval row exists for the pair yet.
    """
    matching = [
        approval
        for approval in repo.list_source_use_approvals(source_id)
        if approval.operation is operation
    ]
    if not matching:
        return None
    latest = max(matching, key=lambda a: (a.created_at, a.id))
    return latest.action


def effective_policy(repo: Repository, source: Source | str) -> EffectivePolicy:
    """The static policy of a source with granted `review` baselines overlaid.

    `allow` becomes the static `allow` list plus every approvable operation whose
    latest approval action is `grant` and whose baseline under the mode is
    `review` (ADR-0018 §2). `mode` and `deny` pass through unchanged, so explicit
    denials and every non-`review` baseline keep their ADR-0007 §3 resolution.
    """
    registered = _resolve_source(repo, source)
    policy = get_source_policy(repo, registered)
    granted: set[Operation] = set()
    for operation in APPROVABLE_OPERATIONS:
        if operation in policy.allow:
            continue
        if _latest_action(repo, registered.id, operation) is not ApprovalAction.GRANT:
            continue
        if baseline(policy.mode, operation) is Baseline.REVIEW:
            granted.add(operation)
    allow = tuple(sorted({*policy.allow, *granted}, key=lambda operation: operation.value))
    approved_ops = tuple(sorted(granted, key=lambda operation: operation.value))
    return EffectivePolicy(
        id=policy.id,
        mode=policy.mode,
        access_class=policy.access_class,
        authority=policy.authority,
        allow=allow,
        deny=policy.deny,
        approved_operations=approved_ops,
        restrictions=dict(policy.restrictions),
        policy_version=policy.policy_version,
        created_at=policy.created_at,
    )


def record_approval(
    repo: Repository,
    source_id: str,
    operation: Operation,
    action: ApprovalAction,
    approver_id: str,
    basis: str,
    *,
    authority_registry: ReviewAuthorityRegistry | None = None,
    approver_role: str = ROLE_GOVERNANCE_STEWARD,
    clock: Callable[[], datetime] | None = None,
    new_id: IdFactory | None = None,
    code_revision: str = "unknown",
) -> SourceUseApproval:
    """Record one append-only grant or withdrawal, with run lineage and audit trail.

    Authority precedes any write (review-service precedent): the approver must hold
    the `governance_steward` role and be authorized in the registry for at least one
    of the source's languages, else `UnauthorizedReviewer`. The operation must be on
    `APPROVABLE_OPERATIONS` *and* have a `review` baseline under the source's policy
    mode, else `PolicyConflict` — nothing else is ever lifted (ADR-0018 §2-4).
    A blank `basis` is refused; a recorded approval must say why it exists.

    Writes the `SourceUseApproval`, a minimal succeeded `HUMAN_REVIEW` creator run
    (keyed by the approval id so reruns never collide on run_key) and an audit event
    (`source_use_approved` / `source_use_withdrawn`) in one `repo.transaction()`:
    a refused approval changes nothing, a committed one leaves the full trail.
    """
    source = _resolve_source(repo, source_id)
    language = source.languages[0]
    if authority_registry is None:
        from langpipe.review.authority import registry_from_profiles

        authority_registry = registry_from_profiles()
    if approver_role != ROLE_GOVERNANCE_STEWARD or not any(
        authority_registry.is_authorized(approver_id, approver_role, lang)
        for lang in source.languages
    ):
        from langpipe.review.base import UnauthorizedReviewer

        raise UnauthorizedReviewer(approver_id, approver_role, language)
    policy = get_source_policy(repo, source)
    if operation not in APPROVABLE_OPERATIONS or (
        baseline(policy.mode, operation) is not Baseline.REVIEW
    ):
        raise PolicyConflict()
    if not basis.strip():
        raise ValueError("basis must be nonempty")

    factory = new_id or new_ulid

    with repo.transaction():
        repo.lock_sources([source.id])
        existing = [
            a for a in repo.list_source_use_approvals(source.id) if a.operation is operation
        ]
        moment = clock() if clock is not None else UTC_NOW()
        if existing:
            latest = max(existing, key=lambda a: (a.created_at, a.id))
            if moment <= latest.created_at:
                moment = latest.created_at + timedelta(microseconds=1)

        approval_id = factory(IdPrefix.SOURCE_USE_APPROVAL)
        # The approval id pins the run identity: identical re-approvals under a fixed
        # clock still get distinct run keys, like the review-service task precedent.
        config: dict[str, JsonValue] = {
            "purpose": "source_use_approval",
            "approval_id": approval_id,
            "source_id": source.id,
            "operation": operation.value,
            "action": action.value,
        }
        digest = config_hash(config)
        run = ProcessingRun(
            id=factory(IdPrefix.RUN),
            stage=RunStage.HUMAN_REVIEW,
            tool_name=_APPROVAL_TOOL,
            tool_version=__version__,
            config=config,
            config_hash=digest,
            code_revision=code_revision,
            run_key=ProcessingRun.compute_run_key(
                RunStage.HUMAN_REVIEW, _APPROVAL_TOOL, __version__, digest, ()
            ),
            status=RunStatus.SUCCEEDED,
            started_at=moment,
            finished_at=moment,
        )
        approval = SourceUseApproval(
            id=approval_id,
            source_id=source.id,
            operation=operation,
            action=action,
            approver_id=approver_id,
            approver_role=approver_role,
            basis=basis.strip(),
            run_id=run.id,
            created_at=moment,
        )
        event = AuditEvent(
            id=factory(IdPrefix.AUDIT),
            event_type=(
                AuditEventType.SOURCE_USE_APPROVED
                if action is ApprovalAction.GRANT
                else AuditEventType.SOURCE_USE_WITHDRAWN
            ),
            actor=approver_id,
            subject_id=source.id,
            run_id=run.id,
            details={"operation": operation.value, "mode": policy.mode.value},
            occurred_at=moment,
        )
        repo.add_run(run)
        repo.add_run_io(run.id, source.id, RunIoRole.INPUT)
        repo.add_source_use_approval(approval)
        # The approval is registered by the write above, so its output edge resolves.
        repo.add_run_io(run.id, approval.id, RunIoRole.OUTPUT)
        repo.add_audit_event(event)
    return approval


__all__ = [
    "APPROVABLE_OPERATIONS",
    "EffectivePolicy",
    "effective_policy",
    "get_source_policy",
    "record_approval",
    "ROLE_GOVERNANCE_STEWARD",
]
