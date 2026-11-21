"""Lineage-aware governance helper for the M2 text layers (WP2.11).

Derived objects (normalized segments, tokens, forms) carry no policy of their own; their
effective decision is the most restrictive decision over the sources they descend from.
This is a proof that governance follows lineage, not an export or eligibility engine.

Since WP4.9 (ADR-0015) operational eligibility is layered on top: a revoked ancestor
source denies every operation for the object, computed from the lineage graph —
revocation changes no stored state on downstream entities.
"""

from langpipe.domain.enums import EntityType, Operation, PolicyDecision, SourceStatus
from langpipe.governance.approvals import effective_policy
from langpipe.governance.policy import resolve_many
from langpipe.storage.repository import Repository


def ancestor_source_ids(repo: Repository, object_id: str) -> list[str]:
    """Sorted ids of every source the object descends from, through any lineage path."""
    lookup_id = object_id
    if repo.entity_type_of(object_id) is EntityType.MORPH_SEGMENT:
        lookup_id = repo.get_morph_segment(object_id).analysis_id
    found = {
        ancestor_id
        for ancestor_id, _depth in repo.ancestors(lookup_id)
        if repo.entity_type_of(ancestor_id) is EntityType.SOURCE
    }
    return sorted(found)


def effective_decision(repo: Repository, object_id: str, op: Operation) -> PolicyDecision:
    """Most restrictive decision over the object's ancestor sources (and itself if a source).

    An object with no governing source is denied.
    """
    source_ids = set(ancestor_source_ids(repo, object_id))
    if repo.entity_type_of(object_id) is EntityType.SOURCE:
        source_ids.add(object_id)
    if not source_ids:
        return PolicyDecision.DENY

    policies = [effective_policy(repo, source_id) for source_id in sorted(source_ids)]
    return resolve_many(policies, op)


def revoked_ancestor_ids(repo: Repository, object_id: str) -> list[str]:
    """Sorted ids of every source the object descends from that is currently revoked.

    Includes `object_id` itself if it is a source with status REVOKED.
    """
    source_ids = set(ancestor_source_ids(repo, object_id))
    if repo.entity_type_of(object_id) is EntityType.SOURCE:
        source_ids.add(object_id)
    return sorted(
        s_id for s_id in source_ids if repo.get_source(s_id).status is SourceStatus.REVOKED
    )


def lineage_eligibility(repo: Repository, object_id: str, op: Operation) -> PolicyDecision:
    """Evaluates operational eligibility for an object over its lineage.

    Returns PolicyDecision.DENY if ANY ancestor source (or the object itself if a source)
    has status REVOKED, or if no governing source exists.
    Otherwise delegates to `effective_decision(repo, object_id, op)`.
    """
    if revoked_ancestor_ids(repo, object_id):
        return PolicyDecision.DENY
    return effective_decision(repo, object_id, op)
