# ADR-0017: IGT observation and morphology graph

**Status:** Accepted (under delegated authority, owner ratification pending)

## Context

M5 introduces interlinear glossed text (IGT) and the morphology graph. The
evidence substrate built in M1–M4 has no representation for either:
`DOMAIN-MODEL.md` names `IGTObservation`, but no model or table exists, and M2
extraction skips IGT objects (reason `igt_not_in_m2`). IGT records (Toolbox
`.txt`, Xigt `.xml`) are tiered observations — text, morphs, glosses,
translations — whose verbatim content is source material (Invariant 1), while
every segmentation, morpheme and feature asserted over them is inference
(Invariant 2) that must stay representable as ambiguous, unknown or wrong
(Invariants 3, 4, 7). `MORPHOLOGY.md` fixes the linguistic contract:
occurrence-level analysis targets, an unsegmented analysis always available,
fusion preserved, no string-merging of morphemes, intrinsic scores never
validate. What was missing is the concrete object model, identity rules,
lifecycle wiring and storage that WP5.2–WP5.16 implement against.

`docs/implementation/M5-PLAN.md` §7 settles the open questions; this ADR records
the decisions that outlive the work package.

## Decision

1. **IGT is an observation; its analysis is evidence.** `IGTObservation`
   preserves the source's tiers verbatim (marker, line number, raw line) plus a
   parsed layer modeled on Xigt: a `words` tier, a `morphemes` tier segmenting
   words, a `glosses` tier aligned to morphemes, and `translations`. Imported
   glosses keep source attribution and are never mapped to a universal scheme at
   import.

2. **Two-step import.** Stage 7a (`RunStage.EXTRACTION`, tool
   `langpipe.igt-extract`, readers `toolbox_igt@0.1.0` / `xigt_xml@0.1.0`)
   extracts observations plus the text-tier `Segment` (observation layer only).
   Stage 7b (`RunStage.IGT_IMPORT`, method `igt_assertion@0.1.0`) maps IGT words
   to that segment's tokens by sequential exact match (normalized under the
   tokenization run's pinned profile) — unmapped words are counted, never
   forced — and produces morphological hypotheses on tokens.
   Rationale: reuse the M2 normalization/tokenization chain and keep one
   semantic layer per run (a stage must not write through multiple semantic
   layers at once).
   For each mapped word with `parse_status ok` for that word: morphs must locate
   left-to-right in the token surface (normalized) with profile boundary marks
   as separators, else no analysis is produced and the morphemes are recorded
   with `form_basis=underlying` (counted `words_unmapped_underlying`;
   OPEN-MORPH-005). Roles come only from source markers, evaluated as an
   ordered first-match rule:
   1. a lexical gloss component is present → `root`;
   2. else `=` boundary → `clitic`;
   3. else `-` boundary → `unknown_bound`;
   4. else (free morph whose gloss is UNKNOWN, or that carries only grammatical
      labels) → `unknown`.
   A bound morph with an UNKNOWN gloss therefore gets `unknown_bound` and
   identity-key branch `UNKNOWN`. Each word token gets one
   segmented `MorphAnalysis` with one segment per morph (`source_gloss`
   verbatim), segment-feature rows (`basis=igt_gloss`), evidence
   `igt_assertion`/`supports` on the analysis and each morpheme, and lineage to
   the `IGTObservation` and the token.

3. **Analysis target: occurrence only.** `MorphAnalysis.target_token_id` is the
   only analysis target in M5 — OPEN-MORPH-003 is resolved for M5; type-level
   `Form` analyses remain deferred. Spans are over `normalized_surface` when
   present, else `raw_surface`; `span_representation` records which
   representation a span indexes.

4. **Segmentation.** Segments are ordered and non-overlapping; code points not
   covered by any segment must be profile boundary marks (they are orthography,
   not morphs). Zero-width segments exist only with `is_zero` and supporting
   evidence; no M5 producer creates them. A segment links ≤1 `Morpheme`
   (many-morpheme fusion stays open — OPEN-MORPH-001) and realizes 0..n
   `Feature`s.

5. **Unsegmented analysis.** `analysis_kind=unsegmented` carries one
   whole-surface segment, `morpheme_id=None`, and an optional `abstention`
   reason. It is an explicit hypothesis like any other, never implied by the
   absence of a segmented analysis.

6. **Features.** Vocabulary rows are keyed `(namespace, label)`, append-only,
   created idempotently. Local entries are `local:<lang>:<LABEL>` with
   definition `"source gloss label <LABEL>"` and `defined_by=source_gloss_label`.
   Features carry no source lineage — a gloss label is not source content — so
   revocation never removes vocabulary; the `morph_segment_feature` assignment
   rows carry the governed link to sources. Mapping to external namespaces
   (`unimorph`, `ud`) is deferred.

7. **Lifecycle.** Morpheme, Allomorph and MorphAnalysis: `candidate → supported`
   by `morph-v1` only; `validated`/`rejected` only by review; `deprecated` via
   review `modify`. Importers never validate — M5 has no
   `AUTHORITATIVE_IMPORT` path. Known discrepancy, recorded and unchanged in
   M5: review `accept` validates a `candidate` directly (M4 behavior), while
   `lifecycle.check_transition` would forbid `candidate → validated`.

8. **Identity.** Morpheme identity is per producing run: key =
   `(language, bound|free, NFC form, lexical glosses | sorted grammatical
   labels | UNKNOWN)`. No merge across runs or sources; no merge of distinct
   strings (`MORPHOLOGY.md` §Allomorphy). Allomorphs are unique by
   `(morpheme_id, form)`.

9. **Deferred** (each remains an OPEN item in `MORPHOLOGY.md` unless noted):
   Paradigm/ParadigmSlot; Morpheme↔Lexeme link; competing role hypotheses
   (OPEN-MORPH-004); underlying-vs-surface `\m` mapping (OPEN-MORPH-005);
   external feature mapping; IGT/morphology export (ADR-0016 fence stands);
   clitic UD strategy (OPEN-MORPH-002, untouched).

## Consequences

- **Storage (Migration 0006).** Tables: `igt_observation` (append-only; UNIQUE
  `(run_id, source_object_id, record_ordinal)`), `feature` (append-only; UNIQUE
  `(namespace, label)`), `morpheme` (hypothesis guard; UNIQUE
  `(run_id, identity_key)`), `allomorph` (hypothesis guard; UNIQUE
  `(morpheme_id, form)`), `morph_analysis` (hypothesis guard; UNIQUE
  `(target_token_id, run_id, signature)`; index `(target_token_id)`),
  `morph_segment` (append-only; UNIQUE `(analysis_id, ordinal)`; index
  `(morpheme_id)`), `morph_segment_feature` (append-only; PK
  `(segment_id, feature_id)`). Every `id` column FKs `object_registry.id`
  (ADR-0009) and carries a `^prefix_[ULID]$` CHECK.
- **Graph queries without a graph database.** The relational projection supports
  the queries the pipeline needs: "tokens analyzed with this morpheme" walks
  `morph_segment.morpheme_id` → `analysis_id` → `morph_analysis.target_token_id`;
  "competing analyses for a token" is every `morph_analysis` row sharing
  `target_token_id`, distinguished by `signature`. There is no winner column:
  ranking (top-1 for benchmarks, review ordering) is computed at query time —
  `morph-v1` overall descending, then method, then signature.
- **Competing analyses and ambiguity.** Two segmentations of one token are two
  `MorphAnalysis` rows on the same `target_token_id` with distinct signatures;
  the same segmentation from two methods is two rows (provenance differs;
  agreement counted by `cross_method_agreement`); a bound piece of unknown
  function is a segment with `morpheme_id=None`, `role=unknown`; an observed
  unglossed free morph is `Morpheme(role=unknown)` with no glosses; a bound
  one is `unknown_bound`; fusion (`ir.PST`)
  is one segment → one morpheme + several features. Accepting one analysis never
  rejects, deprecates or demotes another (Invariant 4). Algorithmic abstention
  is the absence of a row, counted in the report; an `unsegmented` row exists
  only when the `unsegmented` method (or a reviewer) produced it. Contradiction
  is `contradicts` evidence on the analysis — penalized, never averaged away.
- **Hypothesis guard semantics.** `morpheme`, `allomorph` and `morph_analysis`
  are hypothesis-guarded tables (append plus status/score writes only), like the
  lexical hypothesis tables; `igt_observation`, `feature`, `morph_segment` and
  `morph_segment_feature` are append-only. Every morpheme, allomorph, analysis
  and evidence item carries `derived_from` edges to its producing run and inputs
  (IGT observations, tokens, inventory morphemes).
- **Scoring and promotion (`morph-v1`).** Raw components retained:
  `igt_support` (distinct IGT records attesting), `igt_independence` (distinct
  independence groups), `form_diversity` (distinct word forms containing the
  morpheme / allomorph), `projection_support` (`morphology_induction` supports),
  `boundary_mark_support` (segment edges coinciding with orthographic marks),
  `cross_method_agreement` (distinct methods producing the same signature on the
  token); penalties `contradiction`, `unknown_segment`, `ambiguity`. Promotion
  to `supported` (constants are versioned policy parameters, not linguistic
  claims): Morpheme/Allomorph — `igt_support ≥ 2` and (`igt_independence ≥ 2` or
  `form_diversity ≥ 2`) and no contradiction; MorphAnalysis — method is
  `igt_assertion` (or on the ADR-0019 allowlist, empty in M5), every linked
  morpheme is `supported` or `validated`, no unknown segment, no contradiction.
  Everything else stays `candidate`; `validated` is unreachable by machine
  output. Related-language evidence alone never promotes (none exists in M5).
- **M5 scope fences.**
  - No IGT input to lexical induction (Stage 6); Stage 6 is not widened in M5.
  - `langpipe text extract` keeps skipping IGT objects with the unchanged reason
    `igt_not_in_m2` (M2 snapshot stability); IGT goes only through `langpipe igt extract`.
  - Language-specific rules (boundary marks, unknown-gloss markers, Toolbox marker
    aliases, `grammatical_label_pattern`, stem-length limits) live only on
    `MorphologyProfile`; generic code has no Marúbo rule.
  - No synthetic generation, model training or generator code in M5 (cross-reference
    ADR-0018 §3).
  - The Xigt writer exists only as a test helper for round-trip proofs; there is no
    Xigt export command (this sharpens the ADR-0016 export fence already in §9).

## Alternatives Rejected

- **Form-level canonical analyses.** Premature — no evidence base to canonicalize
  over; kept as OPEN-MORPH-003.
- **IGT words as their own analysis target.** Splits the target model: analyses
  would live on IGT words and on M2 tokens with no shared identity.
- **One-step import writing observations and hypotheses together.** Violates
  layer separation (Invariant 2) and the AGENTS.md rule that a stage must not
  write through multiple semantic layers at once; it would also re-implement
  normalization/tokenization inside the importer.
- **Auto-merging allomorphs by gloss.** Violates `MORPHOLOGY.md` §Allomorphy:
  do not merge strings solely because functions seem similar; identity stays
  per-run, keyed, and unmerged.
