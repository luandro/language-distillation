# Pipeline Contracts

This document is normative.

Every stage follows:

```text
inputs → preconditions → processing → outputs → invariants → failure behavior → quality gate
```

A stage MUST NOT skip semantic layers.

## Stage 0 — Source registration

### Inputs
- source manifest;
- one or more source objects or resolvable references;
- an optional governance policy (omitted ⇒ the repository default `direct`/`public`/`repo-owner`, ADR-0025).

### Preconditions
- a manifest with resolvable source objects, or an explicit `exclude` manifest with none;
- language set known or explicitly unknown.

### Outputs
- `Source`;
- immutable `SourceObject` metadata;
- content hashes;
- registration `ProcessingRun`.

### Invariants
- no raw normalization;
- duplicate bytes may be deduplicated physically but provenance remains distinct;
- a policy (declared or defaulted) is persisted before downstream processing.

### Failure
Reject registration atomically; do not leave a partially governed source.

## Stage 1 — Raw ingestion

### Inputs
Registered source objects.

### Outputs
Immutable stored objects plus verified hashes.

### Invariants
- original bytes unchanged;
- access class preserved;
- third-party upload forbidden when policy denies it.

### Quality gate
Hash verification succeeds.

## Stage 2 — Extraction

Extraction writes new raw `Segment` rows and `extraction-report`/`extraction-error` artifacts. The M2 derivation model and its append-only guarantees are decided in [ADR-0010](adr/0010-text-processing-derived-segments.md).

### Sentence extraction adapter: `tsv_sentences@0.1.0`
Opt-in extractor for bilingual TSV sources where individual cells contain multiple sentence units. Splits only the explicitly configured `por` column at `.!?` followed by whitespace or end of cell; preserves `ref`, `row`, and `column` from the parent cell and attaches `sentence_part` (integer part ordinal within cell) along with half-open Unicode `cell_start` and `cell_end` offsets into the original cell. `raw_text` is always a direct cell slice. Other columns/languages pass through untouched. Default TSV extraction and raw segments remain completely unmodified. Extraction, normalization, and tokenization remain strictly separate versioned processing runs.

### Inputs
Raw source object.

### Outputs
Extracted structural units/artifacts and preliminary Segments.

### Must preserve
- page/section/paragraph/table/verse structure where available;
- source locators;
- language metadata;
- original extracted text.

### Must not
- infer lexemes;
- modify source policy;
- delete apparent anomalies silently.

### Failure
Emit extraction error artifact and preserve source for retry.

## Stage 3 — Normalization and tokenization

Normalization derives a *new* normalized `Segment` row per raw segment, linked to its parent by a `normalized_from` lineage edge, instead of updating `segment.normalized_text` in place ([ADR-0010](adr/0010-text-processing-derived-segments.md)).

### Inputs
Extracted segments plus language profile.

### Outputs
- normalized Segment representation;
- normalization events;
- TokenOccurrences;
- Forms.

### Invariants
- raw text retained;
- normalization profile/version recorded;
- destructive transformations forbidden unless explicitly configured and auditable;
- tokenizer version recorded.

### Failure
Segment may be marked `normalization_failed`; do not fabricate output.

## Stage 4 — Segment alignment

### Inputs
Normalized segments from two sources (or two language sides of a registered bilingual source).

### Preconditions
- Source governance permits alignment (`local_operations` includes `ALIGN` on both sources and full source ancestry).
- Selected normalization runs are valid, succeeded, and not revoked.
- Source policy and revocation check: `ensure_alignment_allowed` checks source status plus ancestry before reuse, and re-checks inside the transaction under sorted source-row locks (`lock_sources`). Revoked sources block execution and reuse.
- Declared versification schemes are compatible when coordinate-based (`namespace="scripture"` requires `versification_id`).

### Modes
- `canonical`: exact structural coordinate matching (`canonical_locator@0.1.0`), expanding numeric ranges and bridges into n:m connected components;
- `heuristic`: comparable corpus alignment;
- `experimental`: experimental alignment methods.

### Disposition import
`SegmentAlignmentService.import_disposition(...)` creates immutable successor `SegmentAlignment` records with operational status `approved` or `rejected` (ADR-0011 §2).
- Requires a superseded predecessor (`supersedes_id`) and an authorized review basis Artifact (`authorization_basis_id`).
- The basis artifact must have a succeeded producing run from an operator-allowlisted tool, matching authorized actor, and `HUMAN_REVIEW` permission on every source ancestor.
- Lineage: writes `supersedes` to predecessor and `imported_from` to the basis artifact.
- Rejection successor excludes its predecessor from active Stage 5 selection; multiple conflicting active successors fail preflight.

### Outputs
- `SegmentAlignment` hyperedges with relational `segment_alignment_member` rows (zero-based contiguous positions per side).
- `segment-alignment-report` v1 artifact (`ArtifactKind.ALIGNMENT_FILE`).
- Stage 4 `ProcessingRun` pinned to inputs and configuration.

### Invariants
- Pairwise n:m membership preserved; no Cartesian cross-product degradation.
- Alignment stage does not create dictionary senses or translations.
- Method, mode, status, nullable score, finite `raw_scores` mapping, and run ID recorded.
- Duplicate segment IDs within a side or across sides are forbidden.
- Reruns with identical inputs and configuration reuse existing successful runs.
- **Lineage**: Group links to each member Segment via `derived_from` (no group-to-group edges). Report links to selected groups and source-bearing inputs (segments) via `derived_from` even with zero matches (retaining ancestry). Run ownership is recorded by `run_id` and run I/O (no cycles).

### Quality gate
Method-specific benchmark when inferred rather than structurally guaranteed.

## Stage 5 — Token/word alignment

### Inputs
Approved or structural `SegmentAlignment` hyperedges (`status in {STRUCTURAL, APPROVED}`) with associated `TokenOccurrence` records. Candidate, inferred, and rejected alignments are excluded.

### Preconditions
- Segment alignment status is `structural` or `approved`.
- Selected segment alignment run is succeeded.
- Normalization runs match the sides of the segment alignment run; selected tokenization runs consume those exact normalization runs.
- Full selected-segment coverage: selected tokenization runs must cover all active segment members.
- Source governance re-checked under sorted source locks; revoked sources deny execution and reuse.

### Baseline and execution
- Statistical alignment adapter protocol, initially `eflomal@0.1.0` (`EflomalAligner`).
- Subprocess isolation: execution runs in isolated temporary directories with automatic cleanup.
- Symmetrization: `none`, `intersection`, `union`. Grow-diag heuristics are explicitly excluded (ADR-0011 §5).
- Nullable scores: probabilistic scores and `raw_scores` dictionary may be null/empty where not produced by the method (`score_reason="score_unavailable"`).
- Index direction mapping: statistical aligner translates zero-based token matrix ordinals to persistent `TokenOccurrence` IDs.
- Mock/native boundary: compiler-free baseline vs. native eflomal C extension compiled via optional `alignment` extra.

### Outputs
- `TokenAlignmentEdge` records (`direction in {FORWARD, REVERSE, SYMMETRIZED}`).
- `token-alignment-report` v1 artifact (`ArtifactKind.ALIGNMENT_FILE`) recording edge counts, directional index pairs, unaligned source/target token occurrence IDs, symmetrization method, and execution metadata.
- Stage 5 `ProcessingRun` pinned to segment alignment run and tokenization runs.

### Invariants
- **Lineage**: Each `TokenAlignmentEdge` links to its parent `segment_alignment_id`, `source_token_id`, and `target_token_id` via `derived_from`. The report links to created edges and all selected token/segment/source inputs via `derived_from` (including zero-link runs).
- Succeeded normalization and tokenization runs are explicitly pinned; defaults derive from unique selected parents and fail with `AmbiguousInput` if multiple exist.
- Append-only immutability: token edges are insert-only; modifying or deleting edges is rejected by database triggers.

### Must not
- create validated translations or lexemes;
- collapse token occurrences into dictionary forms;
- overwrite previous aligner runs.

### Failure
Failed token alignment runs roll back all token edges, record the failure on the Stage 5 run, and leave existing Stage 4 segment alignment groups completely intact and unchanged. Failure recording persists only the exception type on the failed run, with no error message or error artifact.

## Stage 6 — Lexical induction

### Tools / methods
`langpipe lexicon induce` runs the Stage 6 service (`LexicalService`, `lexicon/service.py`). Methods are registered in `lexicon/registry.py` and resolved by `name@version` reference; each accepts exactly one input run type:

- `alignment_cooccurrence@0.1.0` — `AlignmentLexicalInducer`, over a succeeded Stage 5 token-alignment run;
- `wordlist_tabular@0.1.0` — `WordlistAdapter`, over a succeeded wordlist extraction run (`langpipe.wordlist-extract`);
- `cldf_lexical@0.1.0` — `CLDFLexicalInducer`, over a succeeded CLDF extraction run's `cldf-lexical-snapshot` v1 artifact (`langpipe.cldf-extract`).

### Inputs (M4)
One succeeded predecessor run — a Stage 5 token-alignment run, a wordlist extraction run, or a CLDF extraction run — plus target and contact language. For the alignment path the run's sides pin both languages; explicit caller values must agree, never relabel. **Deferred, not implemented in M4:** IGT (scheduled M5), co-occurrence statistics, and optional multilingual evidence remain listed as future inputs.

### Preconditions
- the input run exists and is `succeeded`; anything else raises `AmbiguousInput` (exit 11);
- a run whose stage/tool matches none of the three modes is refused (`SchemaViolation`), and a method whose family does not match the input mode is refused before any preflight, run row or reuse decision;
- source policy: `Operation.DISTILL_LEXICON` must resolve to `allow` over the full source ancestry of every contributing object — checked before the run key is computed and re-checked inside the transaction under sorted `lock_sources`. A refusal writes exactly one `POLICY_DENIED` audit event and raises `PolicyDenied`; nothing else is persisted.

### Outputs
- `Lexeme`, `FormLexeme` (`form_lexeme` links), `Sense` and `Concept` rows at `candidate` or `supported`;
- `EvidenceItem`s with versioned `score_breakdown` (`lexical-v1`);
- lineage edges from created entities to the producing run and consumed inputs;
- one `lexical-induction-report` v1 artifact;
- all in one transaction, with run I/O pinning the input run and every contributing object.

### Invariants
- one form may have multiple lexeme/sense hypotheses;
- one sense may have multiple translations;
- source/domain distribution is retained;
- source-domain frequency does not imply preferred everyday sense;
- machine scoring never yields `validated` — `status_counts` in the report can never contain it (Invariant 3);
- contact-language glosses land in `Sense.glosses` as meaning hypotheses and never become target-language `Lexeme`s or `Form`s (Invariants 8/9);
- underlying `Segment`s and `TokenOccurrence`s are immutable: induction is read-only over observations (golden-checked, WP4.11);
- idempotent reruns: identical inputs and configuration, pinned by the run key's parameter/input hash, return the existing succeeded run with `reused=true` and write nothing;
- pycldf never runs inside Stage 6 — CLDF evidence enters only as the pre-extracted `cldf-lexical-snapshot` artifact.

### Failure
The whole run rolls back; the run is marked `FAILED` with the exception *type* only (never a message, which may carry restricted content), and no partial semantic output survives.

### Quality gate
Configured evidence policy; `supported` is allowed, `validated` requires allowed validation basis.

### Lineage and revocation
Revocation impact over lexical lineage is computed, not materialized ([ADR-0015](adr/0015-computed-revocation-impact.md)): `revocation_impact(repo, source_id)` traverses the lineage DAG from a source to every dependent object (segments, alignments, evidence, lexemes, senses, review tasks and decisions, artifacts) and reports identifiers only; `lineage_eligibility(repo, object_id, op)` is the read-time eligibility gate that denies any object with a revoked ancestor source. Neither call mutates stored state.

## CLDF interchange (import and export)

Governed CLDF interchange ([ADR-0003](adr/0003-cldf-interchange.md), [ADR-0016](adr/0016-cldf-interchange-and-export-eligibility.md)). pycldf is a core dependency, imported lazily, and runs only inside the extraction stage below — never inside Stage 6.

### CLDF import (extraction → Stage 6)

- **Tool:** `langpipe.cldf-extract` (`EXTRACTION` run) then Stage 6 with method `cldf_lexical@0.1.0`; `CLDFImporter.import_dataset` runs both.
- **Inputs:** an already-registered `Source` of type `wordlist` or `dictionary` whose manifest lists every dataset file (`*-metadata.json`, each CSV, `sources.bib`). The importer never registers sources and never reads the original directory.
- **Order (part of the contract, same as the wordlist path):** resolve + type check → revoked check → `ingest_source` (`INGEST` gate) → structural check (exactly one `metadata.json` object) → `EXTRACT` gate → materialize every object sha256-verified into a temp directory → containment check (table `url`s and `dc:source` must resolve to registered relative paths; `..`, absolute paths and URL schemes refused before parsing) → `pycldf.Dataset.from_metadata` restricted to `Wordlist`/`Dictionary` + `ds.validate()` → snapshot normalization → one-transaction persist of the snapshot and report artifacts, run I/O and lineage; idempotent reruns reuse the succeeded run.
- **Outputs:** a `cldf-lexical-snapshot` v1 artifact (`EXTRACTION_SNAPSHOT`; rows sorted by `(table, ID)`, NFC-normalized, target-language filtered, upstream status columns ignored) and an IDs-only `cldf-extraction-report` v1 artifact.
- **Invariants:** a related-language form never becomes a target lexeme (Invariant 8); nothing imported is above `candidate` before scoring (Invariant 3); `ExampleTable`/`CognateTable`/`BorrowingTable`/`CodeTable`/`ValueTable` are counted under `ignored_tables`, never imported in M4.

### CLDF export (`EXPORT` run)

- **Tool:** `langpipe.cldf-export`; module `Dictionary` (EntryTable + SenseTable + LanguageTable).
- **Inputs:** one language's `VALIDATED` lexical knowledge (plus `SUPPORTED` with `include_supported`, which adds a `Status` column).
- **Checks:** eligibility (`REDISTRIBUTE_DERIVED` = `allow` for every contributing entity, `REVIEW_REQUIRED` counts as not eligible); headword resolution (lemma `Form` first, else the single distinct eligible `headword` evidence claim; `ambiguous_form`/`no_form` are omissions); attribution collection over ancestor sources; staging write → pycldf validation → commit under `lock_sources` with a full eligibility/status re-check → rename into place.
- **Outputs:** one published CLDF Dictionary directory; one `CLDF_EXPORT` artifact per file (`schema_name="cldf-dictionary"`) plus a `cldf-export-report` v1 artifact (ids, enum values, counts, file digests only); lineage from table artifacts to the entities they contain and from metadata/`sources.bib` to the tables. Run config pins a `selection_digest` so a status flip or changed license is a new run.
- **Invariants:** no ExampleTable and no read path to raw stores, segments or tokens (structural, so no source prose is emitted); `distill_only` prose can never appear — only lemma observations and evidence claims are emitted, and raw redistribution stays denied; nothing eligible is fail-closed (`NoEligibleRecords`, one `POLICY_DENIED` event per denying source, no run, no artifact, no output directory); output is byte-deterministic for a given selection and never overwrites a non-empty directory.

## Stage 7 — IGT import

### Inputs
IGT source representation.

### Outputs
- `IGTObservation`;
- token/morpheme observations;
- candidate or authoritative morphological/grammatical evidence.

### Invariants
- preserve original IGT layers;
- imported glosses keep source attribution;
- do not silently normalize source analysis into a universal scheme.

## Stage 8 — Morphology induction

### Inputs
- TokenOccurrences/Forms;
- lexeme hypotheses;
- IGT;
- known morpheme/affix evidence;
- monolingual frequency/distribution.

### Outputs
- `MorphAnalysis` candidates;
- ordered `MorphSegment`s;
- Morpheme/Allomorph candidates;
- FeatureAssignments;
- score breakdown.

### Invariants
- multiple analyses are allowed;
- an unknown/unsegmented analysis is allowed;
- algorithmic output cannot validate a morpheme;
- character spans preserved where possible.

### Quality gate
Benchmark against held-out IGT or manually validated segmentation before method promotion.

## Stage 9 — Grammar extraction

### Inputs
- IGT;
- descriptive grammar evidence;
- validated/supported morphology;
- human editorial rules.

### Outputs
`GrammarConstruction` candidates and EvidenceItems.

### Invariants
- rules have explicit scope/conditions;
- exceptions are representable;
- related-language rules remain hypotheses.

## Stage 10 — Human review

### Inputs
Reviewable object and evidence bundle.

### Outputs
Immutable `ReviewDecision`; optionally new/superseding linguistic object version.

### Invariants
- reviewer authority recorded;
- uncertain/defer available;
- modifications do not erase original hypothesis/evidence.

**M4 implementation:** lexical review — see [REVIEW-WORKFLOW.md](REVIEW-WORKFLOW.md) §Implementation (M4). Reviewer authority is checked against the registry before any write; the decision insert, the target status change, the score recompute and the `stale_dependent` flags commit in one transaction.

## Stage 11 — Controlled synthesis

Not part of the first implementation milestone.

### Inputs
Only eligible lexemes/senses, morphological realizations, grammar constructions, and semantic frames.

### Outputs
Synthetic examples with complete lineage.

### Must not
- retrieve raw source prose as generation seeds (only eligible derived knowledge is consumed);
- invent unknown target-language forms;
- bypass lineage, revocation or trace-id constraints.

## Stage 12 — Training firewall/export

### Inputs
Eligible direct data and/or synthetic candidates.

### Checks
- governance (trace ids present; `exclude`/revocation rules apply to lineage-governed
  exports — the file-based HF/Alpaca/ChatML exporter does not consult them yet, see
  `docs/governance/training-enablement-plan.md` §1a);
- lineage completeness;
- required review;
- exact/fuzzy/near-duplicate contamination;
- register/quality advisory (recorded, does not block training — ADR-0025);
- revoked-source impact.

### Outputs
Versioned dataset + immutable manifest + firewall report.

The file-based exporter's `manifest.json` also records the register cap applied to test and val
(`max_register_share`, `register_cap_limits`, `register_overflow_to_train`) and a per-split
`register_histogram`; harvested records may carry an optional `register` label (absent =
`unspecified`). Capped rows move to train and are never dropped. Rules: `docs/EVALUATION.md`,
"Benchmark composition".

### Invariant
Exporter reads from an explicit eligible view, never by recursively scanning files.

## Stage 13 — Evaluation

### Inputs
Model or pipeline component plus frozen benchmark.

### Outputs
Versioned evaluation report.

### Invariants
- benchmark data cannot be reused as training/generation evidence;
- report includes tool/config/model versions;
- human results remain distinguishable from automatic metrics.
