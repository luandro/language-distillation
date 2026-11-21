# ADR-0015: Revocation impact is computed, not materialized

**Status:** Accepted (under delegated authority, owner ratification pending)

## Context

Revoking a source must immediately render every derived resource ineligible for export
and training (`docs/GOVERNANCE.md`, §Revocation and §Training eligibility). WP4.9
extends the transitive lineage impact query (M1 `impact_of`, ADR-0009) across the lexical
layers, so a revoked ancestor source reaches: raw observations (segments, tokens),
alignments, evidence items, candidate/supported/validated lexemes and senses, review
tasks, review decisions, and artifacts (M4-PLAN C9, Gate 25).

That raised a representation question: does revocation write anything onto downstream
records?

Any materialized marker — a `revoked` flag, an `affected` status, or a mass lifecycle
rewrite — would have to be kept consistent with the lineage graph, would conflate
linguistic status with governance state, and would touch immutable observations. ADR-0014
already established that staleness of review dependents is a lineage edge, and that
decisions are immutable; the same reasoning extends to revocation.

## Decision

1. **Revocation impact is computed dynamically from the relational lineage DAG, not
   persisted as flags on downstream records.** `revocation_impact(repo, source_id)`
   (`src/langpipe/lineage/lexical_impact.py`) traverses the graph with the existing
   `impact_of` primitive and returns a deterministic `RevocationImpact` summarizing
   affected objects by `EntityType`, with `validated_affected` naming affected objects
   whose lifecycle status is `validated`. It works on unrevoked sources too (what-if
   analysis).

2. **Revocation changes no stored state on downstream entities.** `Lexeme.status` and
   `Sense.status` are untouched (Invariants 2 and 3: a status remains an observation of
   evidence; only an authorized `ReviewDecision` produces `validated` or `rejected`).
   `ReviewDecision` rows stay immutable; no `stale_dependent` edges are written for
   revocation. `ReviewTask` status is untouched. The only write on revocation remains
   `Source.status = REVOKED`.

3. **Governance eligibility is a read-time function.**
   `lineage_eligibility(repo, object_id, op)` (`src/langpipe/governance/lineage_policy.py`)
   returns `DENY` if any ancestor source (or the object itself, when it is a source) is
   `SourceStatus.REVOKED`, or if the object has no governing source; otherwise it
   delegates to the unchanged `effective_decision`. "Affected" means present in
   `revocation_impact`; "ineligible" means `lineage_eligibility` returns `DENY`. There
   are no stale flags or out-of-sync markers to maintain.

4. **No content in impact output.** `RevocationImpact.to_dict()` carries identifiers,
   statuses, and enum values only — never source text, forms, or glosses (M2 E10).

## Consequences

- Clean separation between linguistic truth/status and governance eligibility.
- Zero database writes on revocation beyond setting `Source.status = REVOKED`.
- Fully deterministic across backends (memory and PostgreSQL); impact is a pure function
  of the lineage graph and current source statuses.
- Every eligibility consumer (exports, training gates, future CLDF export in WP4.10)
  must call `lineage_eligibility` rather than trusting stored statuses alone.
- Large graphs pay the traversal cost per query instead of amortizing it into writes;
  if that becomes a problem, caching needs its own ADR.

## Alternatives Rejected

- **Materialized `affected`/`revoked` flags on downstream rows:** a second place to keep
  consistent with the graph, write amplification on every revocation, and mutations of
  append-only observation layers.
- **Mass lifecycle rewrite to `rejected` on revocation:** destroys linguistic evidence —
  the lexeme remains a true observation of its surviving sources (e.g. the bystander
  source that still supports a shared lexeme) — and would misreport Invariant 3 state.
- **`stale_dependent` edges for revocation:** ADR-0014's edge flags review-decision
  staleness of dependent lexical records; revocation is a source-level fact already
  represented by `Source.status` plus the graph, and per-object edges would duplicate it.
