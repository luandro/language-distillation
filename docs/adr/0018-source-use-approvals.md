# ADR-0018: Source-use approvals for `review_required` operations

**Status:** Accepted (under delegated authority, owner ratification pending)

## Context

`ADR-0007` made `review` baselines resolve to `review_required` and explicitly
deferred the approval mechanism: "Review workflows … will need a way to record
approvals that turn `review_required` into `allow` for a specific object. That
mechanism is deliberately not designed here." M5 needs it: the golden IGT source
`04-igt` is `review_required`, so `read_raw`, `extract`, `normalize`,
`distill_morphology` and `evaluation` all block (G1), and no M5 IGT work can run
at all without a way to record an authorized approval.

The mechanism must be auditable, append-only and revocable, and must not mutate
immutable governance facts: raw sources are immutable (Invariant 1), the
`source` row trigger (`langpipe_source_guard`, Migration 0001) forbids changing
anything but `status` (G2), and editing a manifest changes a governance fact
(DELEGATED-DECISIONS §4 precedent).

## Decision

1. **An approval is an append-only row.** `(source_id, operation,
   action ∈ {grant, withdraw}, approver_id, approver_role, basis, run_id,
   created_at)`. The effective state per `(source, operation)` is the latest
   action. Rows are never updated or deleted; a reversal is a new `withdraw`
   row.

2. **`effective_policy` overlay, review baselines only.** `effective_policy`
   adds granted operations to `allow` **only** where `baseline(mode, op) is
   REVIEW`. The resolution order of ADR-0007 §3 is otherwise unchanged:
   explicit `deny` and every non-review baseline (`allow`, `default_deny`,
   `hard_deny`) win over an approval. `deny`, `default_deny` and `hard_deny`
   are never lifted.

3. **Approvable operations in M5.** `read_raw`, `extract`, `normalize`,
   `align`, `distill_lexicon`, `distill_morphology`, `distill_grammar`,
   `evaluation`. The list is exhaustive for M5: `direct_training` and
   `synthetic_generation_support` are refused until the owner returns
   (DELEGATED-DECISIONS §2); `audio_align` is deliberately not approvable in M5
   (no M5 stage uses it); adding it later is an additive ADR amendment plus a
   CHECK-list migration; operations outside the list keep their baseline
   resolution unchanged.

4. **Approver authority.** The approver must hold a `governance_steward` grant
   in the review authority registry for one of the source's languages. Identity
   is an unauthenticated, asserted string checked against process-local
   configuration (C-4 backlog); no real-source approval is recorded under
   delegated authority.

5. **Withdrawal is computed, not stored.** A `withdraw` makes downstream
   objects computed-ineligible for that operation, exactly like revocation is
   computed (ADR-0015); no stored row of derived objects changes.

6. **Single door.** All operation decisions read `effective_policy`; no call
   site consults approval rows or static policies directly. A guard test fails
   if a module outside `governance/` and `storage/` calls `get_policy(`.

## Consequences

- The overlay is transparent: static policies and manifests stay frozen, and
  the full grant/withdraw history is auditable as append-only rows with
  approver, basis and run attribution.
- Withdrawal takes effect immediately and fail-closed: the next
  `effective_policy` evaluation for that `(source, operation)` returns
  `review_required` (or worse), so new runs are refused while
  already-computed objects lose eligibility through lineage, without touching
  stored rows.
- There is one door for all governance evaluations in `langpipe`: adding a
  grant can only lift a `review` baseline and nothing else, so the same
  decision comes out of every call site.
- New audit events `source_use_approved` and `source_use_withdrawn` join the
  `audit_event.event_type` CHECK (Migration 0006).

## Alternatives Rejected

- **Editing the source manifest** (e.g. flipping `04-igt` to `direct`). Changes
  a governance fact and churns M1 snapshots (DELEGATED-DECISIONS §4
  precedent).
- **A new policy version plus repointing `source.policy_id`.** Breaks the M1
  source-row guard: the trigger forbids changing anything but `status` (G2).
- **Per-object approvals.** ADR-0007's Consequences phrase says "for a specific
  object", but source granularity is the smallest unit policies are declared
  at; per-object scoping is deferred until a concrete need exists.
- **Deleting or editing approval rows on reversal.** Destroys the audit trail;
  the latest-action rule makes reversal a plain `withdraw` append.
