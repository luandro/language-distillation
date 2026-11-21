# ADR-0023: Source intake quality criteria

**Status:** Superseded by ADR-0025 (presence-based source authorization).

> **Superseded.** The rules below are historical. ADR-0025 governs: licence, rights-holder,
> and register fields are optional records and never gate processing or training.

## Context

Sources enter the training pipeline with uneven metadata. ADR-0022 found training rows with no `policy_id` and no run lineage. The harvested rows carry a CC-BY label, but a license label alone does not settle what training use is allowed.

The eligibility gate in `src/langpipe/training/eligibility.py` rejects rows without a non-empty `policy_id`. It does not check the source-level facts that decide whether a source can be trained on at all: license evidence, rights-holder basis, register, or quality settings.

The project owner wants training eligibility to rest on data quality. Quality can establish that a row is well-formed. It cannot make `distill_only` prose trainable: AGENTS.md invariant 6 and the ADR-0007 baseline matrix still apply. This ADR is therefore a quality gate only. Whether a hard-denied operation may be lifted is a separate decision, recorded in ADR-0024.

## Decision

A source enters the training pipeline only if its intake record contains every field below. A missing or unverifiable field makes the source **not trainable**.

1. **License.** A license identifier, the URL of the license text, and the date that URL was checked. The check must be reproducible: record the checker's identity and the date.
2. **Authority or rights-holder.** The named rights-holder or authority, and the basis for that claim (document, letter, or dated statement). `unknown` does not pass.
3. **Register.** One of `traditional_public`, `ritual_restricted`, `unknown`. Only `traditional_public` may proceed to training review. `ritual_restricted` and `unknown` are excluded.
4. **Quality criteria**, each recorded as a value:
   - alignment method and version, and the length-ratio limit applied to aligned pairs;
   - duplicate policy: the exact and near-duplicate rule, applied before train/val/test split;
   - maximum scripture share of a training dataset: **0.2** (proposed). No such cap exists in code today. `src/langpipe/training/quality/domain.py` does not exist, so this ADR sets the value rather than citing it;
   - archaic and gendered register review: reviewer, date, and notes for each batch.
5. **`policy_id`** on every row, resolving to a policy file that lists the source and its trainable status.

A source that passes 1-5 is still refused if its policy denies `direct_training`. The gate narrows what enters review; it never widens policy.

## Consequences

- Intake takes longer. Each source needs a complete record before any processing that feeds training.
- Existing exported rows stay non-trainable until their source records exist (see ADR-0022).
- Storing the intake record is a persisted format change. Under invariant 11 it needs a migration, tests, and documentation. None of these are part of this ADR.
- The 0.2 scripture cap is a proposal. It must be validated against the datasets before it is enforced in code.

## Alternatives

- **Put quality fields in `policy.yaml`.** Mixes data quality with governance facts that are frozen per ADR-0018. Rejected.
- **Score quality and set a threshold.** A high score can hide a missing license. Required fields are checked first; scores are supplementary.
- **Set the scripture cap as a code constant now.** Deferred until the value is validated against real datasets.
