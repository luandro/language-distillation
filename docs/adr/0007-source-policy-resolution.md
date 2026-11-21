# ADR-0007: Source policy resolution semantics

**Status:** Proposed (matrix amended by ADR-0025)

## Context
`GOVERNANCE.md` defines six policy modes, a list of operation permissions, access classes and the rule "deny overrides allow", but it does not say:

- what each mode allows or denies when an operation is not listed explicitly;
- whether an explicit `allow` can loosen a mode (for example, `allow: direct_training` on a `distill_only` source);
- which operation covers storing raw bytes, even though `archive_only` ("preserve") and `exclude` ("do not process") depend on that difference;
- how to combine policies when one object has more than one ancestor source.

Also, the religious-corpus default in `languages/mzr.md` uses operation names that are not in the `GOVERNANCE.md` vocabulary (`structural_alignment`, `lexical_distillation`, `morphology_evidence`, `audio_alignment`, `style_seed_generation`).

M1 has to enforce policy in code before any processing starts (invariant 5), so these questions need concrete answers.

## Decision
1. **Operation vocabulary** is the `GOVERNANCE.md` list plus one new operation, `ingest`: copying raw bytes into the immutable raw store. Operation names are a closed enum, and a policy that names an unknown operation is rejected.
2. **Each mode sets a baseline** for every operation, using one of four levels: `allow`, `default_deny` (an explicit `allow` lifts it), `review` (resolves to `review_required`; an explicit `allow` lifts it) and `hard_deny` (the mode's ceiling: no explicit `allow` lifts it, and a policy whose `allow` list contains a hard-denied operation is rejected at load time with `PolicyConflict`).
3. **Resolution order** for a single policy: explicit `deny`, then `hard_deny` baseline, then explicit `allow`, then baseline. The result is `allow`, `review_required` or `deny`. Anything other than `allow` blocks the operation (`PolicyDenied`).
4. **Outward data flow is closed by default**: `third_party_api`, `cloud_processing`, `redistribute_raw` and `redistribute_derived` are never `allow` at baseline in any mode.
5. **Multiple ancestors** use the most restrictive result: `deny` > `review_required` > `allow`. An empty ancestor set resolves to `deny`.
6. **Baseline matrix** (A = allow, D = default_deny, R = review, H = hard_deny):

| operation | direct | distill_only | review_required | restricted | archive_only | exclude |
|---|---|---|---|---|---|---|
| ingest | A | A | A | A | A | H |
| read_raw | A | A | R | D | D | H |
| extract, normalize, align, distill_lexicon, distill_morphology, distill_grammar, audio_align | A | A | R | D | H | H |
| human_review | A | A | A | D | D | H |
| evaluation | A | A | R | D | H | H |
| direct_training | A | A | R | D | H | H |
| synthetic_generation_support | A | A | R | D | H | H |
| third_party_api, cloud_processing, redistribute_derived | D | D | D | D | H | H |
| redistribute_raw | D | H | D | D | H | H |

The `distill_only` column was amended by ADR-0025: `evaluation`, `direct_training`, and
`synthetic_generation_support` move from `default_deny`/`hard_deny` to `allow`, because a
source classification is no longer a rights judgement. `exclude` keeps every hard deny, and
`distill_only` keeps its `redistribute_raw` hard deny.

7. **`exclude` sources** may be registered, which records the source and its policy, but their objects are neither hashed nor registered, and ingestion is denied.
8. **`restricted` actor and workflow lists** are stored in the policy's opaque `restrictions` map. M1 does not enforce them; while that stays true, the `default_deny` baseline is the protection.
9. **Proposed mapping for `languages/mzr.md`** (the doc change needs governance-owner approval): `structural_alignment` → `align`, `lexical_distillation` → `distill_lexicon`, `morphology_evidence` → `distill_morphology`, `audio_alignment` → `audio_align`. `style_seed_generation` has no equivalent; the nearest is `synthetic_generation_support`, which resolves `allow` under `distill_only` after the ADR-0025 amendment.

## Consequences
Policy checks are deterministic, table-driven and property-testable: adding a policy or a deny never makes the result more permissive. Policies cannot accidentally open outward data flow. Review workflows (M4 and later) will need a way to record approvals that turn `review_required` into `allow` for a specific object. That mechanism is deliberately not designed here.

## Alternatives rejected
- **Fail-open for unlisted operations.** It contradicts invariant 10 and the egress-first stance in `GOVERNANCE.md` (outward operations stay closed by default).
- **Explicit allow overrides any mode.** It would let a manifest typo open an operation the mode intentionally restricts (for example `redistribute_raw` under `distill_only`).
- **Reuse `read_raw` for ingestion.** `archive_only` must allow preservation while restricting raw reads.
