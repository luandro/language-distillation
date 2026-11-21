# Evaluation and Quality Gates

## Principle

No component is promoted because it is newer or neural. It is promoted because it beats the current baseline on a local target-language benchmark without unacceptable regressions.

## Frozen sets

Evaluation data MUST be separated from induction, prompting, synthetic generation and fine-tuning.

Maintain development evidence, development benchmark, frozen test benchmark and diagnostic challenge sets.

## Alignment

### Transductive evaluation protocol
Alignment evaluation operates under the `transductive_unsupervised` protocol (ADR-0011 §8):
- Corpus text (including evaluated segments) participates in unsupervised statistical alignment model fitting, but gold link labels and annotations NEVER enter induction, adapter options, priors, or hyperparameter selection. No strict held-out inductive generalization claim is made.
- Gold annotations bind to corpus occurrences via `alignment-gold` v1 selectors (by `locator_selector` or `group_key` and token ordinal), keeping gold matrices stable across environments with different opaque IDs. Real gold sets must be registered as governed input Artifacts.
- Metrics are micro-evaluated over the set of candidate edges ($A$) against gold `Sure` ($S$) and `Possible` ($P$, where $S \subseteq P$) link sets:
  - $\text{Precision} = \frac{|A \cap P|}{|A|}$; undefined (`null`) iff $|A| = 0$, recording diagnostic reason `precision_undefined`.
  - $\text{Recall} = \frac{|A \cap S|}{|S|}$; undefined (`null`) iff $|S| = 0$, recording diagnostic reason `recall_undefined`.
  - $\text{AER} = 1 - \frac{|A \cap S| + |A \cap P|}{|A| + |S|}$; undefined (`null`) iff $|A| + |S| = 0$, recording diagnostic reason `aer_undefined`.
  - $\text{F1} = \frac{2 \cdot \text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$; `null` if either Precision or Recall is undefined (`null`), and exactly `0.0` if both are defined and their sum is zero.
- **Undefined denominators**: Undefined metrics are recorded strictly as `null` with their corresponding reason codes (`precision_undefined`, `recall_undefined`, `aer_undefined`). They are never coerced to an invented `0.0` or synthetic denominator.
- **Null token metrics**: Predicted unaligned token occurrences are compared exclusively to explicitly annotated null tokens (`annotated_null_source`, `annotated_null_target`). Unannotated tokens are not assumed null; incomplete coverage is flagged as `null_source_coverage_incomplete` or `null_target_coverage_incomplete`.

### Unresolved gates and honest accounting
- **Target-language gold**: Currently, no independently governed gold alignment annotation set exists for Marúbo–Portuguese (`mzr–por`). The synthetic and coordinate suites verify pipeline integrity, structural correctness, and error bounds, but do NOT prove linguistic translation accuracy. Target-language quality remains unmeasured until native speakers/linguists provide gold annotations.
- **Portuguese real-data package**: ScriptureEarth does not publish raw USFM text for Portuguese; open alternatives (`porbr2018` under CC BY 4.0, `porbrbsl` in Public Domain) have been researched on eBible.org, but require operator authorization, versification mapping for Exodus/Nehemiah, and senior review signatures.
- **Non-claims**: Do not claim training firewall implementation, target-language validation, deterministic independent native sampling, or M4 review completion.

Exact thresholds are project configuration, not universal facts.

## Lexical induction

Measure top-1/top-k sense accuracy, precision of supported candidates, ambiguity preservation, false merge/split rate and domain/register contamination.

## Morphology

Measure boundary precision/recall/F1, morpheme identification where gold exists, stem preservation, feature accuracy, ambiguity calibration and downstream impact.

## Generation/translation

Primary surface metric: `chrF++`.

Also track case marking, negation, person/number, tense/aspect/mood, constituent order, lexical adequacy, hallucinated-form rate, copying/contamination and register violation.

BLEU MAY be logged for comparison but is not the primary gate for morphologically rich languages.

### Benchmark composition (`langpipe synth export`)

The NMT export's test and val splits are 100% human-attested (purity is asserted and recorded in
`manifest.json`). They are built in three steps:

1. **Scripture block.** ScriptureEarth verses: test takes `min(200, max(20, 10%))`; val takes
   `val_ratio` of the rest.
2. **Per-file harvested split.** Each `exports/harvested_parallel/*_parallel.jsonl` file is
   deduplicated and ranked by `sha256(provenance, ref)`; a file of 75+ rows gives 50 test / 25 val,
   a smaller one 40% / 25%.
3. **Register cap** (`--max-register-share`, default `0.20`). In test and val, each harvested
   register (the record's `register` field; absent = `unspecified`) is limited to
   `floor(share × S / (1 − share))` rows, where `S` is that split's scripture block, so no
   harvested register exceeds `share` of the split. The register's slots are shared evenly across
   its files; each file keeps its lowest hashes. Overflow rows go to **train**, never dropped.

4. **Cross-split dedup.** Rows are grouped (union-find) when they share a Marúbo key or a
   Portuguese key across all sources; the key is NFC, casefold, no punctuation or quotes,
   collapsed whitespace, no diacritics, and is used only for comparison (stored text is never
   rewritten). Any train row whose group touches a val or test row is removed from train; a val
   row sharing a key with a test row is removed from val. Counts are recorded in the manifest
   `warnings`. The result has zero key overlap train/val, train/test and val/test on both sides.
5. **Bible train cleanup** (scripture rows only; val/test text is never altered): drop rows whose
   Portuguese carries edition-note sigla (`TR`, `RP`, `N4`), remove whitespace before `, . ; : ! ?`
   in the Portuguese, and drop rows failing the word-count ratio guard
   (`training/quality/length_ratio.py`, 2.5). Chant rows are exempt from the ratio guard.
6. **Benchmark v2** and the chant benchmark follow (see below).

Stability: the limit depends only on `S`, so adding a file of another register never moves an
existing test row; adding a file of the same register can only shrink an existing file's test
rows to a subset. Scripture itself is not capped by step 3 (its size is bounded by step 1), so
test is scripture-majority by construction. With no scripture block the cap is skipped and a
warning is recorded.

The manifest records `max_register_share`, `register_cap_limits`, `register_overflow_to_train`
and `register_histogram` (per split). Current mzr export (benchmark v2): test = 191 scripture + 50 chant (25 Wenia + 25 Cesarino 2017,
50 capped chant rows moved out of train or into the chant benchmark); val = 497 scripture + 49 chant
(limit 129, not binding).

### Derived full-phrase rows (ADR-0026)

Wenía stanza rows and Cesarino 2017 sentence rows are built from consecutive line rows
(`python -m langpipe.synthesis.derived_rows build --lang mzr`) and join TRAIN after val, test
and the chant benchmark are pinned. A derived row is excluded when its key component (shared folded Marúbo or
Portuguese key, plus derived-to-member edges) touches val, test or the chant benchmark. Current
mzr export: 218 built, 18 kept (14 stanza, 4 sentence), 124 excluded for an eval member, 76 for a
shared key (refrains). The manifest records `derived_train_count`; `derived_rows_audit.json`
lists every exclusion. Benchmarks are unchanged.

### Benchmark versions (mzr)

Scores are comparable only within one benchmark version. Freeze the version before comparing
models, and record it with every score. The manifest field `benchmark_version` names it.

- **v1** (legacy, `exports/mzr/datasets_legacy/v1/`): the held-out text as first selected. Not
  repaired. `v0-pre-dedup` (the first adapter's training data) is in git history at `9aa157f`.
- **v2** (current, `langpipe synth export --benchmark-version 2`): held-out Bible rows are
  repaired or excluded after steps 1-5. Whitespace before `, . ; : ! ?` is removed from the
  Portuguese (14 val / 8 test rows). Rows whose Portuguese carries an edition note (TR/RP/N4)
  leave val/test (20 val / 9 test rows): they are not refilled and not returned to train, and are
  restorable only by a verified correction in a later benchmark version. The register cap is
  computed before the exclusion, so the cap limits (50 test / 129 val) are unchanged and
  chant is 50 of 241 test rows. Every change is listed with its reason and original text in
  `exports/mzr/datasets/benchmark_v2_audit.json` (sha256 in the manifest). Result: val 546,
  test 241.

### Chant benchmark (`exports/mzr/datasets/chant_benchmark/`)

Chant rows (Wenia and Cesarino 2017 harvested files, the profile's
`LanguageProfile.chant_provenances`) carry the register `ritual_chant` in the register
histogram; any other register keeps the 0.2 cap. The chant
benchmark is a separate manifest, exempt from the cap, so chant quality is measured on enough
rows without letting chant dominate the primary benchmark.

- **Test, target 100 rows:** every chant row already in primary test (reused) plus whole
  components moved out of train. **Val, 25-40 rows:** whole components inside primary val.
- **Components** are rows linked by a shared folded Marubo or Portuguese key on either side,
  which covers derived refrain duplicates. A component is selected whole or not at all, and
  only components made entirely of chant rows of one split are eligible, so no leakage rule is
  weakened. Selection is stratified by source and Marubo word-length tercile, ordered by
  `sha256(seed, component id)` (seed 42), so it is deterministic.
- **Train loss** is measured before accepting: additions are capped at 25% of chant train rows.
  If the targets are not met the manifest status is `provisional` and says why.
- **Globally excluded from train.** The export asserts zero Marubo and Portuguese key overlap
  between train, val, test and the chant benchmark.
- **Bootstrap by component, not by row.** Each row has a `component` field and the manifest
  reports the component counts.

Current mzr chant benchmark (status `frozen`): test 100 rows in 96 components (50 Wenia, 50
Cesarino 2017); val 40 rows in 40 components (20 / 20); 50 of 590 chant train rows (8.5%) moved
out of train. 19 test and 2 val chant rows overlap the first adapter's (v0) training data by
key, so v0 chant scores are contaminated.

Neural semantic metrics MUST NOT be authoritative until locally calibrated.

## Human evaluation

Recommended dimensions: naturalness, meaning preservation, grammatical acceptability, register appropriateness, orthographic acceptability, and speech intelligibility.

Always allow uncertainty/cannot-judge.

## Component promotion

Promote experimental → approved when:
1. benchmark is versioned;
2. baseline exists;
3. result is reproducible;
4. candidate improves required metrics;
5. critical error classes do not regress beyond tolerance;
6. human review agrees where automatic metrics are insufficient.

## Decision-model calibration

Before Jev/Clef-class models judge target-language material, test option randomization, unknown cases, insufficient context, OOD data and minimal morphological pairs.

Measure accuracy, macro F1, Brier score, expected calibration error, abstention quality and positional bias.
