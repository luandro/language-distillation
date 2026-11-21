# ADR-0024: Direct-training hard-deny revision

**Status:** Superseded by ADR-0025 (presence-based source authorization).

> **Superseded.** The "Decision: Pending" text below is historical. The owner decided on
> 2026-10-18 (ADR-0025): the hard deny on `distill_only` x `direct_training` is removed, and
> licence/ownership/register do not gate training.

## Context

The project owner has stated that training eligibility should be decided on data quality, and that source authority for the scripture-derived material is unassigned. Both points are recorded as context here, not as decisions.

The hard deny is in `src/langpipe/governance/policy.py`. The `DIRECT_TRAINING` row (line 54) sets `distill_only` to `_H`. `resolve()` returns `deny` for a hard-denied operation before it checks the explicit `allow` list. `validate_policy_lists()` rejects any policy whose `allow` list names a hard-denied operation with `PolicyConflict`.

ADR-0007 §2 makes a hard deny the mode's ceiling. ADR-0018 approvals only lift `review` baselines, so they cannot lift it either. AGENTS.md invariant 6 forbids `distill_only` prose in training. ADR-0022 clears no current train data and recommends exclusion.

## Decision

**Pending.** The decision belongs to the project's named decision-maker, a person or body named in the governance documents with authority over the source's community. It is not an AI agent's decision. An operator's chat statement does not satisfy it. A valid decision needs, in a versioned document under the decision-maker's name: the name, scope, date, and basis, plus the license and register evidence from ADR-0023.

**Recommendation: Option A (keep the hard deny) until a named authority exists.** See the reasoning below.

### Option A: keep the hard deny

- **Consequences:** No change to code or policy. Non-`distill_only` sources can still train under ADR-0023. Fixing the conversational gap needs new eligible data, collected under a consent protocol.
- **Risks to community-held material:** Lowest. Material stays out of training no matter how complete its records are.
- **Must be recorded:** Nothing new beyond ADR-0022's current status.

### Option B: amend ADR-0007 to allow `direct_training` when policy records license, register, and a named decision-maker

- **Consequences:** Changes the baseline matrix. `distill_only` `direct_training` moves from `hard_deny` to `review` or `allow`. Policy files then become a training switch.
- **Risks:** Field completeness is not consent. A named decision-maker may not be the community's authority. One passing source sets a pattern for the rest. Editing a manifest could open the gate, which is the reason ADR-0007 rejected explicit allows.
- **Must be recorded:** A superseding ADR for ADR-0007 §2. The decision-maker's name, scope, date, and basis. A dated policy transition in the audit log. A restoration path.

### Option C: per-source approval in an append-only audit

- **Consequences:** Reuses the ADR-0018 grant and withdraw row pattern. It still requires lifting a hard deny, so it needs the same ADR-0007 amendment as Option B.
- **Risks:** Approval is per source, not per community decision. Approver identity is unauthenticated (ADR-0018 §4, C-4), so the audit is only as strong as that check. Withdrawal does not remove already-trained artifacts.
- **Must be recorded:** Grant rows with `approver_id`, `approver_role`, `basis`, date, and a reference to the community's consent. Withdrawal rows.

## Consequences

Option A keeps current behavior. The project meets the quality goal for sources that are eligible under policy, and it avoids deciding authority questions the project has not resolved. The trade-off is that the scripture-derived pairs stay out of training, and the adapter's conversational gap must be fixed with other data.

Revisit this ADR by superseding it when a named authority is recorded and the community consent process has run. Before Option C is reconsidered, its approver-identity gap must be closed.

## Alternatives

- **Option B** is rejected for now. Its gate depends on paperwork that can be completed without the consent of the community the material comes from.
- **Option C** is rejected for now. Its audit relies on an identity check that is not authenticated, and it still requires the same ADR-0007 amendment as Option B.
