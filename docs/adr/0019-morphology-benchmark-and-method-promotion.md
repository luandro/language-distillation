# ADR-0019: Morphology benchmark and method promotion

**Status:** Accepted (under delegated authority, owner ratification pending)

## Context

M5 adds morphology induction methods (`unsegmented`, `igt_projection`,
`bpe_char`, optional Morfessor) whose output must be compared empirically
against gold annotations before any method is trusted for production use. Two
failure modes are specific to this setting:

- **Leakage (G15).** The projection adapter learns its inventory from IGT, and
  the natural gold set is IGT — evaluating a method against gold its own
  inventory was learned from measures memorization, not generalization.
- **Unprincipled promotion.** `MORPHOLOGY.md` already rules that intrinsic F1
  alone does not choose the production method, and the lifecycle (ADR-0017)
  lets evidence promote hypotheses only to `supported`. A method, however,
  could otherwise drift into production status on a good benchmark number with
  no evaluation artifact and no accountable authority.

The M3 real-data gate precedent (C12) also applies: no accuracy claim on real
Marúbo morphology until authorized gold exists.

`docs/implementation/M5-PLAN.md` §7.3 and §7.10 settle the design; this ADR
records the decisions that outlive the work package.

## Decision

1. **Gold is frozen or derived, and pinned.** Gold is a frozen `MorphGold` v1
   file or a deterministic derivation from named held-out IGT records; the gold
   digest is pinned in the benchmark run config, so an evaluation run names
   exactly the gold it scored.

2. **Leakage guard (G15) is mandatory.** Runs evaluated against gold must not
   have seen the gold sources/records during induction: the benchmark refuses
   (`BenchmarkLeakage`) when any `IGTObservation` named by the gold set is a
   lineage ancestor of the evaluated run's inventory.

3. **Metrics.** Metrics computed per method (M5-PLAN §7.10, WP5.11):
   - boundary P/R/F1 (micro; boundary = start offset of every non-initial
     segment), exact-segmentation accuracy, known-affix preservation, stem
     preservation, over- and under-segmentation rates, coverage, abstention rate,
     mean distinct signatures per token, top-1 vs oracle F1;
   - `downstream_chrf` and `downstream_feature_error` are emitted as
     `not_applicable` (no generation in M5);
   - morpheme identification and feature accuracy (`EVALUATION.md` §Morphology)
     are deferred until gold carries morpheme/feature labels;
   - top-1 = highest `morph-v1` overall, ties broken by method name then
     signature;
   - missing analysis for a gold token counts as an unsegmented prediction, with
     coverage reported separately. Intrinsic F1 alone never promotes a method
     (`MORPHOLOGY.md`).

4. **Promotion allowlist in `morph-v1` config.** Method → pinned benchmark
   report artifact id + thresholds + approving authority. Empty for induction
   methods in M5. Only `igt_assertion` is promotion-capable, because it encodes
   a source assertion, not an algorithm (ADR-0017 Consequences, Scoring and
   promotion).

5. **Baselines.** `unsegmented` and `bpe_char` in base CI; Morfessor as an
   optional extra (WP5.12); FlatCat recorded `not_available`; SentencePiece is
   not added (compiled dependency; `bpe_char` stands in for the BPE baseline).

6. **No real-data accuracy claims.** No accuracy claim on real Marúbo
   morphology until authorized gold exists (M3 C12 precedent); benchmark
   numbers are produced and consumed only over synthetic/gold-authorized data.

## Consequences

- **Reproducible benchmarking.** One `morphology-benchmark-report` v1 per
  benchmark run, idempotent on `(runs, gold digest, config)`; selector
  resolution maps gold items to tokens via `IGTObservation.segment_id` plus
  token ordinal, or segment locator, so a re-run over the same inputs yields
  the same report.
- **Strict leakage prevention.** The leakage refusal is part of the harness,
  not a convention; an evaluation that would compare a method to gold it
  trained on fails closed with `BenchmarkLeakage` before any metric exists.
- **Algorithmic humility.** No method reaches production-promotable status
  autonomously: promotion requires a pinned benchmark report artifact and an
  approving authority recorded in the `morph-v1` allowlist, which ships empty
  for induction methods in M5.
- **Dependency footprint stays small.** Base CI needs no compiled segmenter;
  optional baselines are behind deselected extras and never block the gate.

## Alternatives Rejected

- **Intrinsic F1 alone choosing the production method.** Ignores semantic and
  paradigm coherence — the explicit rule in `MORPHOLOGY.md` §Benchmarking.
- **Evaluating without a leakage check.** The projection adapter's inventory
  comes from IGT and the gold set is IGT; an unchecked benchmark would score
  memorization.
- **Floating or unpinned gold sets.** Without a pinned digest a benchmark run
  cannot prove which gold it scored, and results are neither reproducible nor
  auditable.
- **Adding SentencePiece as the BPE baseline.** A compiled dependency for a
  role `bpe_char` already fills in base CI.
