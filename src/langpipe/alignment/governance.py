"""ALIGN-operation policy preflight for alignment inputs (M3-PLAN WP3.5, ADR-0011 §7).

Governance follows lineage: an alignment is governed by every ancestor source of every
input object. Non-allow decisions, revoked sources and inputs without source ancestry
fail closed before any run is created, adapter is called or semantic row written:
exactly one existing ``POLICY_DENIED`` audit event and nothing else. The returned
sorted source ids carry the combined ancestry so callers can evaluate other
operations — an alignment cannot open an operation that every ancestor keeps closed
(ADR-0025).
"""

import logging
from collections.abc import Sequence

from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AuditEventType,
    EntityType,
    Operation,
    PolicyDecision,
    SourceStatus,
)
from langpipe.domain.errors import InvalidLineage, PolicyDenied
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.run import AuditEvent
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.logging import log_event
from langpipe.storage.repository import Repository

logger = logging.getLogger(__name__)


def ensure_alignment_allowed(ctx: AppContext, input_ids: Sequence[str]) -> tuple[str, ...]:
    """Check Operation.ALIGN over the full ancestry of every input; return sorted sources.

    Raises ``PolicyDenied`` (with one audit event) for the first non-allow decision,
    revoked source, or input without source ancestry, in sorted id order. Raises
    ``InvalidLineage`` for an empty input set: nothing to align is not a permission.
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

    # An input with no governing source is not alignable evidence; fail closed first.
    for input_id in missing:
        decision = PolicyDecision.DENY
        _record_denial(ctx, input_id, decision)
        raise PolicyDenied(input_id, Operation.ALIGN, decision)

    for source_id in sorted(sources):
        source = repo.get_source(source_id)
        decision = effective_decision(repo, source_id, Operation.ALIGN)
        if source.status is SourceStatus.REVOKED or decision is not PolicyDecision.ALLOW:
            _record_denial(ctx, source_id, decision)
            raise PolicyDenied(source_id, Operation.ALIGN, decision)
    return tuple(sorted(sources))


def _record_denial(ctx: AppContext, subject_id: str, decision: PolicyDecision) -> None:
    # Mirrors the M2 denial events: identifiers and enum values only, never content.
    with ctx.repo.transaction():
        ctx.repo.add_audit_event(
            AuditEvent(
                id=ctx.new_id(IdPrefix.AUDIT),
                event_type=AuditEventType.POLICY_DENIED,
                actor=ctx.actor,
                subject_id=subject_id,
                run_id=None,
                details={"operation": Operation.ALIGN.value, "decision": decision.value},
                occurred_at=ctx.clock(),
            )
        )
    fields: dict[str, str | int | bool | None] = {
        "operation": Operation.ALIGN.value,
        "decision": decision.value,
    }
    # source_id log fields must be source ids; a missing-ancestry subject may be any
    # registered object, so its id is not echoed there.
    if _is_source_id(ctx.repo, subject_id):
        fields["source_id"] = subject_id
    log_event(logger, "policy.denied", level=logging.WARNING, **fields)


def _is_source_id(repo: Repository, object_id: str) -> bool:
    return repo.entity_type_of(object_id) is EntityType.SOURCE
