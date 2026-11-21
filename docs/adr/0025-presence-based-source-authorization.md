# ADR-0025: Presence-based source authorization

**Status:** Accepted (owner decision, 2026-10-18)

## Context

The repository had layered rights gates in front of processing and training: a
`distill_only` hard deny on `direct_training` (ADR-0007 §2/§6), a hard-coded
`("corpus:", "harvested:")` blocklist in the training gate, and two proposed ADRs
(ADR-0022, ADR-0023) plus a pending one (ADR-0024) that required a verified license, a
named rights holder, and an authorized register decision before a source could train.
ADR-0022 and ADR-0024 both concluded that no current source was cleared, so the largest
parts of the local corpus could not enter training.

The project owner has decided that this is the wrong posture for the repository:

> "This repo should ignore licenses, and ownership; we've set gates that are blocking our
> work moving forward. If a source is added to the repo, it should be processed."

This ADR records that decision. It is the authorization basis the earlier ADRs said was
missing; it is not a legal opinion about the material.

## Decision

1. **Presence is authorization.** A source directory, file, or manifest placed under
   `var/external/` is authorized for `ingest`, `read_raw`, `extract`, `normalize`,
   `align`, `distill_lexicon`, `distill_morphology`, `distill_grammar`, `evaluation`,
   `synthetic_generation_support`, and `direct_training`.
2. **Licenses, ownership, and register are records, not gates.** They MAY be recorded in
   policies, manifests, the source registry, and intake documents. No code path in the
   processing or training pipeline may reject a source or a row because a license is
   unverified, a rights holder is unassigned, or a register decision is missing.
3. **The only mode that blocks a source entirely is an explicit operator `exclude`.**
   `archive_only` and `restricted` remain available as explicit operator choices and can
   restrict individual operations; they are not inferred from rights evidence.
4. **The baseline matrix is amended.** In ADR-0007 §6, the `distill_only` column changes
   for `evaluation`, `direct_training`, and `synthetic_generation_support` from
   `default_deny`/`hard_deny` to `allow`. `exclude` keeps every hard deny, and
   `distill_only` keeps its hard deny on `redistribute_raw`. No other cell changes.
5. **The training eligibility gate is traceability-only.** A row is eligible when it
   carries a trace id (`source_id`, `policy_id`, or `provenance`). The gate never consults
   license, ownership, register, or policy mode, and the `corpus:`/`harvested:` blocklist
   is removed.
6. **This ADR supersedes ADR-0022, ADR-0023, and ADR-0024 as authorization gates.**
   Their factual findings remain valid and are preserved. ADR-0018 approvals remain
   available for `review_required` baselines but are no longer needed for the sources this
   ADR covers.
7. **Revocation stays.** If a community or publisher objects later, revoking a source
   still flips `lineage_eligibility` and the next lineage-governed export (CLDF) omits its
   rows (ADR-0015); the file-based HF/Alpaca/ChatML exporter does not consult it yet.
8. **Third-party egress and redistribution are out of scope and unchanged.**
   `third_party_api` and `cloud_processing` remain opt-in (`default_deny`), and the CLDF
   export still enforces its own `redistribute_derived`/attribution rules (ADR-0016). Those
   are rules about releasing data outward, not about processing or training inside the
   repo, so this ADR neither opens nor closes them.
9. **A policy-less manifest gets the default policy, which is versioned in code.**
   `manifest_sha256` covers the manifest as written (with `policy: null`), not the applied
   default; the applied policy is recorded in the persisted `SourcePolicy` row and the
   source's `policy_id`. Changing `default_policy_spec()` therefore changes the policy of
   newly registered manifests without changing their digest; treat that function as a
   governance constant and change it only with an ADR.

Normative rules updated with this ADR: `AGENTS.md` invariant 6, `CLAUDE.md` invariant 6,
`docs/GOVERNANCE.md` (principle, mode table, training eligibility, `distill_only` section,
CARE clause), `docs/GOLDEN-FIXTURE.md` (governance), `docs/PIPELINE-CONTRACTS.md` (Stage 0
inputs/preconditions/invariant, Stage 12 checks),
`docs/adr/0007-source-policy-resolution.md` (matrix), and `docs/languages/mzr.md`
(per-source policy).

## Consequences

- Every source in `var/external/` can be processed and trained on without a rights review.
  The 105 Cesarino pairs and the 4,671 ScriptureEarth verse pairs stop being blocked.
- Provenance, source ids, policy ids, and run ids remain mandatory on records. They are
  what make revocation, reproducibility, and attribution possible; they never authorize.
- A source's `policy.mode` no longer expresses a rights judgement. A leftover
  `distill_only` label cannot block training; it only keeps raw redistribution closed.
- Removing the gates removes the repository's internal representation of CARE authority.
  Community objections can only be honored after the fact, through revocation, and
  already-published artifacts are reported rather than erased.
- The repository makes no legal claim about the material. Copyright and ownership exist
  outside it; this ADR changes what the pipeline enforces, not what third parties own.

## Alternatives rejected

- **Keep the evidence gates and finish the license audit first (previous plan).** Rejected
  by the owner: it blocks processing and training on material already in the repository.
- **Lift the hard deny but keep the intake/register gates.** Rejected: it leaves two
  paperwork gates that do not affect what the pipeline does.
- **Delete provenance and lineage along with the gates.** Rejected: those are technical
  requirements for revocation and reproducibility, not rights checks. Removing them would
  make the dataset untraceable without unblocking anything further.
- **Open third-party egress as well.** Not decided here; kept opt-in because it is a
  data-leaving-the-machine risk, not an ownership gate.
