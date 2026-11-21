# ADR-0014: Review dependent staleness representation and review authority configuration

**Status:** Accepted (under delegated authority, owner ratification pending)

## Context

WP4.8 delivers the human review queue (M4-PLAN §6, ADR-0013 §4-5). Two representation
questions were left open by ADR-0013:

1. **Dependent staleness (M4-PLAN C10).** ADR-0013 §5 requires that recording a decision
   "updates the target object's score breakdown, and flags directly dependent items as
   stale", but names no representation for the staleness flag. The score side has an
   existing versioned contract (`lexical-v1` `LexicalScoreBreakdown`, ADR-0013 §3); the
   staleness side had none.
2. **Authority configuration mechanism (M4-PLAN C3).** ADR-0013 §4 decides that review
   authority is "configured via a structured language profile registry" but the profile
   data model had no field to carry it, so the first implementation fell back to built-in
   fixture reviewers — which conferred live operational authority through the CLI.

## Decision

1. **Directly dependent staleness is a `stale_dependent` lineage edge.** When a review
   decision changes a lexical object's lifecycle status, the review service writes one
   `LineageEdge` of kind `stale_dependent` from each directly dependent record to the
   decided object (child → parent, matching the graph's direction contract). In M4 the
   only directly dependent records are the `Sense`s of a decided `Lexeme`. The edge is
   idempotent on `(from_id, to_id, kind)` like every lineage edge, visible by traversing
   forward from the decided object, and carries the deciding task's creator run.
   `stale_dependent` extends the `LineageKind` vocabulary:
   - Migration `0005_review_stale_dependent` replaces the `ck_lineage_edge_kind` CHECK
     with the extended vocabulary; downgrade refuses while `stale_dependent` rows exist.
   - The committed `schemas/lineage-edge.v1.schema.json` is regenerated in the same
     change.
   - Full cascading recalculation of dependent scores remains future work
     (TODO linked to `REVIEW-WORKFLOW.md` §State transition, M4-PLAN C10).

2. **Review authority is structured language profile data.** `LanguageProfile` carries a
   `review_authority` tuple of `ReviewAuthorityGrant(reviewer_id, role, languages,
   domains)` records (ADR-0013 §4's "structured language profile registry"). The review
   service and CLI build their `ReviewAuthorityRegistry` from the registered profiles at
   call time. A profile without grants contributes nothing: an unconfigured deployment
   denies every reviewer by default. There are no built-in fixture reviewers; tests
   construct their own registries or profile configurations explicitly.

3. **A task's `target_version` pins the lifecycle status-of-record.** Lexical objects
   carry no version counter; the smallest reversible version contract is the object's
   lifecycle status when the task was created (`candidate`, `supported`, ...). Task
   creation refuses a pin that does not match, and a decision is refused when the target
   no longer carries the pinned status. Concepts have no status and accept no pin.

## Consequences

- Revocation impact analysis (WP4.9) can reach review records and stale dependents by
  graph traversal alone: source → lexical target → task → decision, plus
  decided-target → dependent staleness flags.
- Accepting a scored `supported` target updates its versioned breakdown instead of
  erasing the audit record; the breakdown is recomputable from immutable evidence.
- Deployments must explicitly configure review authority per language before any human
  decision can be recorded through the CLI; this is the intended fail-closed default.
- The lineage kind vocabulary grows by one value; readers of `lineage_edge` that switch
  on kinds must treat unknown kinds conservatively.

## Alternatives Rejected

- **A boolean `stale` column on lexeme/sense:** a stored format change to two tables, a
  second flag mechanism beside the existing lineage graph, and a second place to keep
  consistent; the edge reuses the existing idempotent, indexed, traversable relation.
- **Reusing `supersedes` or `derived_from` for staleness:** both name derivations; a
  staleness flag is a different fact and would corrupt graph semantics.
- **Database RBAC tables for reviewer authority:** rejected in ADR-0013 §4; unchanged.
- **Built-in default reviewers scoped to registered languages:** turns test fixtures
  into live operational authority (the defect this ADR removes).
