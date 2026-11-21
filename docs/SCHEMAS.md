# Machine Schema Plan

The Markdown domain model defines semantics. Machine schemas enforce structure.

## Initial schemas

Create versioned schemas for:

```text
source
source-policy
processing-run
artifact
segment
token-occurrence
form
segment-alignment
token-alignment-edge
evidence-item
lexeme
sense
concept
morpheme
allomorph
morph-analysis
morph-segment
feature
paradigm
grammar-construction
review-task
review-decision
dataset-manifest
```

Status (M5, WP5.0): generated JSON Schemas exist for the models in `SCHEMA_MODELS` (`src/langpipe/schemas/registry.py`). As of carry-over C-1 this includes the M4 models `concept`, `lexeme`, `form-lexeme-link`, `sense`, `review-task` and `review-decision`, which now have generated `schemas/*.v1.schema.json`. The remaining names in the list above (`morpheme`, `allomorph`, `morph-analysis`, `morph-segment`, `feature`, `paradigm`, `grammar-construction`, `dataset-manifest`) are described here and in `DOMAIN-MODEL.md` but are **not yet in `SCHEMA_MODELS`** — no `schemas/*.v1.schema.json` exists for them. Do not imply otherwise from this list.

## Generation

Recommended:
- Pydantic v2 models in code;
- generated JSON Schema checked into `schemas/`;
- CI fails when generated output differs from committed schema.

Semantic meaning remains governed by `DOMAIN-MODEL.md`.

## Report artifacts (M2)

Stage 2 and Stage 3 services store JSON report artifacts in the artifact store, versioned through the `Artifact` row's `schema_name`/`schema_version`. JSON Schema generation for these reports is deliberately deferred: they are processing artifacts, not domain models, so they are not generated into `schemas/`. They are described here instead.

All four report schemas carry only identifiers, counts, code-point offsets, component `name@version` strings, fixed reason codes and allowlisted locators — never segment text, token surfaces, TSV cell values, titles or file names.

### `extraction-report` v1

Written by `ExtractionService` on success (`ArtifactKind.EXTRACTION_REPORT`):

- `schema`, `schema_version` — `"extraction-report"`, `1`;
- `source_id`, `run_id`;
- `objects` — per extracted source object: `source_object_id`, `extractor` (versioned name), `units` count, extractor `stats` counters, and `empty_units` as projected locators;
- `skipped` — per skipped object: `source_object_id` and a fixed `reason` (`no_extractor`, `igt_not_in_m2`).

Locator projection is allowlisted: integer keys `chapter`, `para_index`, `part`, `note_index`, `line`, `row`, `column_index` (non-negative ints only) and text keys `book` (three uppercase letters/digits), `verse` (number, optional lowercase-letter suffix, optional range, or empty), `unit` (`verse`/`heading`/`footnote`/`introduction`/`unknown`) and `marker` (USFM-style marker name). Keys outside the allowlist, or values failing the value grammar, are dropped rather than passed through.

### `extraction-error` v1

Written when an extraction run fails (`ArtifactKind.EXTRACTION_ERROR`):

- `schema`, `schema_version` — `"extraction-error"`, `1`;
- `source_object_id` — ID of the object whose parsing failed;
- `code` — fixed reason code (e.g. `tsv_ragged_row`, `usfm_invalid_marker`);
- `line` — 1-based integer line number where the failure occurred, or null when unknown.

### `normalization-report` v1

Written by `NormalizationService` (`ArtifactKind.NORMALIZATION_REPORT`):

- `schema`, `schema_version` — `"normalization-report"`, `1`;
- `extraction_run_id`, `run_id`;
- `profiles` — mapping from language code to profile versioned name (`NAME@VER`);
- `segments` — per derived segment: `segment_id`, `raw_segment_id`, `status`, `events` (`rule`, `raw_start`, `raw_end`, `norm_start`, `norm_end`; half-open code-point offsets), and `diagnostics` (mapping of fixed rule-name or code-point diagnostic keys to integer counts);
- `totals` — `{"segments": N, "failed": M}`;
- `failure_codes` — mapping from fixed failure code to count of occurrences.

### `tokenization-report` v1

Written by `TokenizationService` (`ArtifactKind.TOKENIZATION_REPORT`):

- `schema`, `schema_version` — `"tokenization-report"`, `1`;
- `normalization_run_id`, `run_id`;
- `tokenizers` — mapping from language code to tokenizer versioned name (`NAME@VER`);
- `segments` — per tokenized segment: `segment_id`, `tokens`, `words`, `punct`, `numbers` (integer counts);
- `skipped` — per skipped segment: `segment_id` and fixed `reason` (`normalization_failed`, `token_span_unmappable`);
- `totals` — `tokens`, `words`, `punct`, `numbers`, `forms`, `skipped` (integer totals).

### `segment-alignment-report` v1

Stored as `ArtifactKind.ALIGNMENT_FILE` (schema `"segment-alignment-report"`, version `1`):

- `schema`, `schema_version` — `"segment-alignment-report"`, `1`;
- `run_id` — producing Stage 4 `ProcessingRun` ID;
- `method`, `mode` — versioned method name (e.g. `canonical_locator@0.1.0`) and mode string (`canonical`, `heuristic`, `experimental`);
- `sides` — list of side descriptors (each with `source_id`, `language`, `normalization_run_id`);
- `namespace`, `versification_id` — coordinate namespace and declared versification scheme (nullable);
- `groups` — list of group records:
  - `alignment_id`, `group_key` (SHA256 canonical hash), `status` (`structural`, `inferred`, `candidate`, `approved`, `rejected`), nullable `score`, optional fixed `reason` code, `source_segment_ids` list, `target_segment_ids` list;
- `unmatched_source`, `unmatched_target` — lists of unaligned segment records `{"segment_id": ..., "reason": ...}`;
- `totals` — `groups`, `unmatched_source`, `unmatched_target` (nested integer counts);
- `disposition` — optional mapping present only when imported via disposition.

CLI summary fields (`reused`, top-level counts) are stdout conveniences and are not persisted in the artifact payload.

### `token-alignment-report` v1

Stored as `ArtifactKind.ALIGNMENT_FILE` (schema `"token-alignment-report"`, version `1`):

- `schema`, `schema_version` — `"token-alignment-report"`, `1`;
- `run_id`, `segment_run_id`, `source_tokenization_run_id`, `target_tokenization_run_id`;
- `method`, `backend` — versioned adapter name (e.g. `eflomal@0.1.0`) and dictionary of backend metadata;
- `groups` — list of group records:
  - `alignment_id`, `source_segment_ids`, `target_segment_ids`, `status`;
  - `source_token_ids`, `target_token_ids`;
  - `index_pairs` — mapping of direction to list of pairs: `forward` and `reverse` contain zero-based integer index pairs `[source_index, target_index]`; in current v1 storage, `symmetrized` contains persistent `TokenOccurrence` ID string pairs `[source_token_id, target_token_id]` (an unresolved wire representation discrepancy between directional ordinals and symmetrized occurrences, preserved for v1 backwards compatibility);
  - `links` — mapping of direction (`forward`, `reverse`) to list of `{"source_index": ..., "target_index": ..., "score": ...}`;
  - `counts` — nested mapping: `forward`, `reverse`, `symmetrized` link counts;
  - `score_reason` — fixed code (e.g. `"score_unavailable"` when method does not produce per-link probabilities);
  - `reason` — optional skip reason (e.g. `"empty_token_side"` or null);
  - `unaligned_source_ids`, `unaligned_target_ids` — lists of unaligned `TokenOccurrence` IDs under active symmetrization;
  - `unaligned_by_direction` — nested mapping of direction (`forward`, `reverse`, `symmetrized`) to `{"source": [...], "target": [...]}` unaligned ID arrays;
- `excluded_groups` — list of `{"alignment_id": ..., "reason": "ineligible_status"}`;
- `totals` — `groups`, `edges`, `skipped_groups`, `excluded_groups` (nested integer counts).

### `benchmark-report` v1

Stored as `ArtifactKind.BENCHMARK_REPORT` (schema `"benchmark-report"`, version `1`):

- `schema`, `schema_version` — `"benchmark-report"`, `1`;
- `run_id` — evaluation `ProcessingRun` ID;
- `protocol` — evaluation protocol label (strictly `"transductive_unsupervised"`);
- `direction` — `AlignmentDirection` string (`forward`, `reverse`, `symmetrized`);
- `gold_split` — sorted array of gold split labels (e.g. `["test"]`);
- `metrics` — nested dataclass dictionary:
  - Link counts: `total_predicted`, `total_sure`, `total_possible`, `sure_hits`, `possible_hits` (integer counts);
  - Micro-averaged metrics: `precision` (float or null), `recall` (float or null), `f1` (float or null), `aer` (float or null);
  - Null token metrics: `null_source_tp`, `null_source_fp`, `null_source_fn`, `null_source_precision` (float or null), `null_source_recall` (float or null), `null_source_annotated`, `null_source_total`; `null_target_tp`, `null_target_fp`, `null_target_fn`, `null_target_precision` (float or null), `null_target_recall` (float or null), `null_target_annotated`, `null_target_total`;
  - Applicability tracking: `evaluated_groups` (integer count of evaluated gold groups); `precision_groups`, `recall_groups`, `aer_groups`, `null_source_groups`, `null_target_groups` (arrays of group ID strings contributing to each metric);
  - Diagnostic reason codes: `reasons` (array of string codes, e.g. `precision_undefined`, `recall_undefined`, `aer_undefined`, `null_source_coverage_incomplete`, `null_target_coverage_incomplete`);
- `reasons` — top-level list of reason codes.

## Report artifacts (M4)

M4 stage services store JSON report artifacts in the artifact store, versioned through the `Artifact` row's `schema_name`/`schema_version`, exactly like the M2/M3 reports. Like those, they are processing artifacts, not domain models, so they are not generated into `schemas/` — they are described here instead.

Except for the extraction snapshot below, every M4 report schema carries only identifiers, enum values, counts, digests and `name@version` strings — never a headword, a gloss, a form string or any other source content.

### `lexical-induction-report` v1

Written by `LexicalService` at the end of a Stage 6 run (`ArtifactKind.OTHER`):

- `schema`, `schema_version` — `"lexical-induction-report"`, `1`;
- `run_id`, `input_run_id` — the producing Stage 6 run and the succeeded predecessor run it consumed;
- `method` — resolved inducer reference, `name@version` (e.g. `alignment_cooccurrence@0.1.0`);
- `mode` — `token_alignment`, `wordlist` or `cldf`;
- `target_language`, `contact_language`;
- `totals` — `lexemes`, `form_links`, `senses`, `concepts`, `evidence_items`, `lineage_edges` (integer counts);
- `status_counts` — combined Lexeme and Sense lifecycle counts of the run. `status_counts` can never contain `validated`: machine scoring grants `supported` at most (Invariant 3).

### `wordlist-extraction-report` v1

Written by the governed wordlist extractor (`langpipe.wordlist-extract`, WP4.6) (`ArtifactKind.EXTRACTION_REPORT`):

- `schema`, `schema_version` — `"wordlist-extraction-report"`, `1`;
- `source_id`, `run_id`;
- `target_language`, `contact_language`;
- `objects` — per ingested source object: `source_object_id`, `sha256`, `size_bytes`;
- `totals` — `lexemes`, `senses`, `form_links`, `evidence_items`, `lineage_edges` (integer counts).

### `cldf-extraction-report` v1

Written by `CLDFImporter` (`langpipe.cldf-extract`, WP4.10) (`ArtifactKind.EXTRACTION_REPORT`):

- `schema`, `schema_version` — `"cldf-extraction-report"`, `1`;
- `source_id`, `run_id`;
- `target_language`, `contact_language`;
- `metadata_object_id` — the source object holding the CLDF `*-metadata.json`;
- `objects` — per materialized dataset object: `source_object_id`, `sha256`, `size_bytes`;
- `rows` — snapshot row count (integer);
- `skipped` — skip counts by fixed reason: `other_language`, `unmapped_language`, `empty_form`;
- `ignored_tables` — count of CLDF tables outside the M4 import set (counted, never read).

### `cldf-lexical-snapshot` v1

Stored as `ArtifactKind.EXTRACTION_SNAPSHOT` (schema `"cldf-lexical-snapshot"`, version `1`). It is the normalized payload Stage 6 consumes, so pycldf never runs inside Stage 6:

- `schema`, `schema_version` — `"cldf-lexical-snapshot"`, `1`;
- `target_language`, `contact_language` — carried verbatim so the snapshot is self-describing for Stage 6;
- `rows` — sorted by `(table_path, row_id)`, NFC-normalized; each row is a `form`, `parameter`, `entry` or `sense` record with `kind`, `row_id`, `table_path` and that table's natural fields (`language`, `form`, `parameter_id`, `id`, `name`, `concepticon_id`, `headword`, `pos`, `entry_id`, `description`) plus `cldf_sources`. Upstream status columns are ignored: the snapshot carries no status at all (Invariant 3);
- `counts` — `skipped` (per fixed reason) and `ignored_tables`;
- `source_key`, `table_objects` — added by the importer for lineage (registered source key; per-table source-object IDs).

The snapshot is the *only* M4 artifact that carries target-language form strings. That is allowed because it is an extraction snapshot under the source's policy — governed, access-classed and lineage-traced inside the local store — not an export; nothing leaves local execution through it (Invariants 6 and 10).

### `cldf-export-report` v2

Written by `CLDFExporter` at the end of an `EXPORT` run (`ArtifactKind.OTHER`):

- `schema`, `schema_version` — `"cldf-export-report"`, `2` (version 2: `omitted.stale_dependent` reflects rows that are actually omitted from the export, rather than merely counted while still exported; Invariant 11);
- `run_id`;
- `exporter_version`, `dataset_module`;
- `exported`, `omitted` — counts by entity kind / fixed omission reason;
- `entry_ids`, `sense_ids`, `source_ids` — exported entity and contributing source IDs;
- `files` — per published file: `name`, `sha256`, `size_bytes`.

### `cldf-dictionary`

Not a JSON report: `cldf-dictionary` is the `schema_name` on each `CLDF_EXPORT` file artifact. The format itself is a CLDF Dictionary (EntryTable + SenseTable + LanguageTable) governed by [ADR-0016](adr/0016-cldf-interchange-and-export-eligibility.md) and the CLDF specification, not by this repo.

## Versioning

Every exported object includes schema name/version. Breaking changes increment version.

## Extensions

Tool/language-specific metadata may use extension maps, e.g. `extensions.eflomal`. Core relationships must not be hidden in extensions.

## Enums

Serialized enum values are stable. Never reuse an existing value with different meaning.

M4 vocabularies (`src/langpipe/domain/enums.py`):

- `ReviewTaskType` (9 values): `lexical_sense`, `lemma`, `morphology_segmentation`, `morpheme_function`, `grammar_construction`, `register_domain`, `alignment_spotcheck`, `governance_export`, `pronunciation`;
- review task workflow `status` (operational queue state, *not* a `LifecycleStatus`): `open`, `in_review`, `resolved`, `cancelled`;
- `ReviewDecisionKind`: `accept`, `reject`, `modify`, `uncertain`, `defer`;
- `LineageKind` M4 addition: `stale_dependent` (migration 0005).

The CHECK constraints in migrations 0004/0005 are literal copies of these vocabularies and must change together with the domain enum (Invariant 11).

## Validation boundaries

Validate CLI/API input, imported artifacts, exports and test fixtures.

## `alignment-gold` v1

Each group binds through exactly one of `group_id`, `group_key`, or `locator_selector`.
The portable selector contains a coordinate `namespace` and ordered `source_members` and
`target_members`. Each member records its preserved source object's `original_path` and the
segment's complete locator map. Side roles, member order, paths, locators, and namespace all
participate in matching. A selector must resolve to exactly one persisted alignment group;
missing or ambiguous matches fail evaluation before an evaluation run starts. Token selectors
then bind by ordered member and token ordinal, with an optional installation-specific token ID
available for local-only annotations. The portable form keeps committed fixture gold stable
across installations with different opaque IDs.

## Span convention

Offsets MUST identify representation (`raw` or `normalized`) and use documented end-exclusive semantics.

Recommended: Unicode code-point indexes `[start, end)` at public boundaries.
