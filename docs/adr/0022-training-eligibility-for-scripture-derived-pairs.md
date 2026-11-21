# ADR-0022: Training eligibility for scripture-derived parallel pairs

**Status:** Superseded by ADR-0025 (presence-based source authorization).

> **Superseded.** The rules and conclusions below are historical. ADR-0025 governs: a source
> present in this repository may be processed and trained; licence, ownership, and register
> are records, not gates. The row counts and diagnostics below remain factually useful.

## Context

The Marúbo NLLB adapter was trained on `exports/mzr/datasets/train.hf.jsonl`: 4,701 pairs, of which 4,671 come from `corpus:*` (Bible verses, 8 books: ACT, EXO, GEN, JAS, JHN, LUK, NEH, RUT) and 30 from `harvested`.

The ScriptureEarth Marúbo source is governed by `var/external/scriptureearth/mzr/policy.yaml`, which is `distill_only` with access class `community`. Its allowed operations are `ingest`, `read_raw`, `extract`, and `normalize`. `docs/GOVERNANCE.md` prohibits raw or lightly transformed `distill_only` prose from entering trainable datasets. Human attestation and clean splits do not change that status.

Current training data therefore may fall outside policy. Diagnostics also show the adapter fails on short conversational Portuguese (e.g. "Qual seu nome?" returns English). The training set has 9 pairs with four or fewer Portuguese words, so retraining on the same data would not fix that failure and would extend any policy exposure.

## Decision

Pending decision (authority unassigned; the previously named organization was removed on 2026-10-18 as unverified). Options:

1. **Exclude** `distill_only` scripture pairs from trainable datasets. Retrain only on eligible data. **Recommended by the reviewers** (Opus and Codex, 2026-10-18).
2. **Approve** training use of the scripture pairs. Not achievable by editing `policy.yaml` alone: `direct_training` is hard-denied for `distill_only` (`src/langpipe/governance/policy.py:54`), ADR-0007 says no explicit allow lifts a hard deny, and a policy listing it is rejected at load (`policy.py:84`). It needs a new ADR amending ADR-0007, a recorded authority decision (name, scope, date, basis), and a lawful policy transition. ADR-0018 approvals cannot lift this.
3. **Partial**: keep scripture for evaluation only. Not established: `evaluation` is default-deny for `distill_only` (`policy.py:53`) and `policy.yaml` grants no evaluation allow. Requires an explicit recorded evaluation authorization first.

Until a decision is recorded, no new training run may use `corpus:*` rows, or any row whose lineage traces to a `distill_only` source.

**Harvested rows are a separate question.** The 30 `harvested` train rows all carry `provenance: harvested:zenodo_1008779_cesarino_marubo_2017_parallel` (the Cesarino and Marúbo collaborators' *The teachings of the Death-Path*, CC-BY-4.0 in `docs/research/universal_sources_registry.json:176-195`). They are not ScriptureEarth rows, but they have no policy id or run lineage, and `GOVERNANCE.md` requires both. A CC-BY label does not clear them. They need their own policy file, lineage, and authority review before training. The community-authority text (`GOVERNANCE.md:146`) also applies.

**Current status:** no subset of the existing train data is cleared for training. The adapter already trained on these rows is in the same position; whether it stays in use is also the authority's call.

## Consequences

- Option 1 requires new eligible conversational data before any useful retrain. Elicitation of new pairs with speakers needs a consent protocol and a policy file entry with `trainable` status.
- Under any option, every dataset row needs a policy id and a per-row lineage run id, and every manifest must cite them.
- `exports/mzr/datasets/manifest.json` counts (4,725 train, including 24 synthetic) do not match the exported files (4,701 rows, all corpus or harvested). Fix before the next export.
- Synthetic rows, even if later approved, stay train-only. Val and test remain attested-only.

## Alternatives

- Relabelling scripture pairs as derived or paraphrased: rejected. Lightly transformed text is still covered by the prohibition.
- Using an LLM to produce Marúbo training text: rejected by invariant 9 (no LLM invention of target-language forms).

## Related

- Invariants 6 (distill-only protection) and 12 (ADR for architectural decisions) in `CLAUDE.md`.
- ADR-0018 (source use approvals).
- Encoding fix for label language tags: `src/langpipe/training/nllb_encoding.py`.
