# Domain Model: Evidence and Language Graph

This document is normative.

## Design rule

The model separates:

1. **observations** — what was actually present;
2. **evidence** — typed support/contradiction derived from observations;
3. **hypotheses** — proposed linguistic entities/analyses;
4. **validated knowledge** — hypotheses accepted by an allowed authority.

Never replace observations with hypotheses.

## Logical graph

```text
Source
  └─contains──────────► Segment
                          └─contains────────► TokenOccurrence
                                                │
                    ┌───────────────────────────┼─────────────────────────┐
                    │                           │                         │
               realizes_form               participates_in             has
                    │                        alignment                analysis
                    ▼                           │                         ▼
                   Form                        ▼                   MorphAnalysis
                    │                   TokenAlignmentEdge              │
                variant_of                      │                   ordered segments
                    │                           ▼                         ▼
                    ▼                    TokenOccurrence             MorphSegment
                  Lexeme                                                   │
                    │                                                realizes?
                has_sense                                                   ▼
                    ▼                                                   Morpheme
                   Sense                                                   │
                    │                                                has_allomorph
                expresses                                                   ▼
                    ▼                                                   Allomorph
                  Concept

Any inference ─supported_by─► EvidenceItem
Any derived object ─created_by─► ProcessingRun
ReviewDecision ─targets─► reviewable object
```

## Observation entities

### Source
Logical supplied/discovered resource. Required: ID, title/name, type, languages, provenance, policy ID, acquisition timestamp and status.

### SourceObject
Immutable raw file/object with hash, media type, URI/path, size, original filename and access class.

### Segment
Contiguous structured unit: verse, sentence, paragraph, table cell, etc. Stores raw/normalized text, language, structural locator, normalization profile and run.

### TokenOccurrence
One token instance in one Segment. Stores ordinal, raw/normalized surface, offsets where available and tokenizer version.

### IGTObservation
Preserves IGT surface, segmentation, glosses, tags/features, free translation, source locator and original formatting as far as practical.

### AudioSpan
Time-bounded observation linked to an audio source object and optionally text/token.

## Type-level linguistic entities

### Form
Reusable orthographic form type under language + orthography profile. Not a lexeme.

### Lexeme
Hypothesized/validated lexical unit with preferred lemma Form when known, POS hypothesis, lifecycle status, register and evidence.

A Form may relate to zero, one or multiple Lexeme hypotheses.

**Storage (M4)** ([ADR-0013](adr/0013-lexical-model-and-review-authority.md)): table `lexeme`, ID prefix `lex`, lifecycle column `status`. No paradigms, slot definitions or feature bundles exist in M4 — morphology is Milestone 5 (ADR-0013 §2).

### Form–Lexeme link

Explicit many-to-many join realizing `Form * ─ * Lexeme`: table `form_lexeme` (ID prefix `flx`) with `form_id`, `lexeme_id`, optional `role`, unique `(form_id, lexeme_id)`, and `run_id` lineage. Append-only (INSERT-only trigger): an ambiguity-preserving link is never rewritten (ADR-0013; M4-PLAN C1).

### Sense
Meaning attached to one Lexeme with translations/glosses, concept mapping, domain/register, status and evidence.

`glosses` is a language-tag → list of gloss strings mapping. Contact-language glosses (e.g. Portuguese) are meaning hypotheses on the Sense — never target-language forms (Invariants 8/9; ADR-0013).

**Storage (M4)**: table `sense`, ID prefix `sense`, lifecycle column `status`, optional `concept_id` (one Concept at most per Sense in M4 storage; see Cardinalities).

### Concept
Local or external semantic referent. `local` concepts are first-class and external mapping is optional.

`concept_type` defaults to `local`; `concepticon_id` and `external_urn` are optional external mappings.

**Storage (M4)**: table `concept`, ID prefix `cpt`. Concepts carry no lifecycle status column — they are queue-only review targets, never promoted or rejected.

### Morpheme
Reusable hypothesized/validated morphological unit. Possible kinds: root, lexical stem-like, derivational affix, inflectional affix, clitic, reduplicant, bound lexical element, unknown.

### Allomorph
Surface realization associated with a Morpheme with conditioning context when known.

### MorphAnalysis
One proposed analysis of one TokenOccurrence or Form. Multiple concurrent analyses are allowed.

### MorphSegment
Ordered span within a MorphAnalysis. Stores offsets, surface string and optional linked Morpheme/role/features.

### MorphFeature
Feature definition in namespace `unimorph`, `ud`, or `local:<language>`.

### Paradigm / ParadigmSlot
Sparse feature-bundle structure associated with lexemes/classes. Missing slot means unknown/unobserved, not impossible.

### GrammarConstruction
Reusable syntax/morphosyntax construction with function, constraints, evidence, status and synthesis eligibility.

## Alignment entities

### SegmentAlignment
Addressable evidence object representing an ordered binary n:m relation between segments in two different languages.
- **Relational membership**: `segment_alignment_member(alignment_id, side, position, segment_id)`. Positions within each side are zero-based, contiguous, and ordered by document order (`original_path`, segment ordinal).
- **Sides**: Each side is homogeneous in language and selected normalization run; the two sides have distinct languages. Different sources are typical, but two language sides of a registered bilingual source are permitted.
- **Attributes**: `method` (`name@version`), `mode` (`canonical`, `heuristic`, `experimental`), `status` (`structural`, `inferred`, `candidate`, `approved`, `rejected`), nullable `score`, `raw_scores` (dictionary of finite float components), `run_id`, `group_key` (SHA256 canonical hash), `created_at`, `authorization_basis_id` (nullable Artifact ID), `supersedes_id` (nullable SegmentAlignment ID).
- **Dispositional successors**: `approved` and `rejected` statuses are operational evidence dispositions (never linguistic translation truth, ADR-0011 §2). They can only be created as immutable successors via `SegmentAlignmentService.import_disposition(...)` and require both a superseded predecessor (`supersedes_id`) and an authorized review basis Artifact (`authorization_basis_id`). The basis artifact must have a succeeded producing run from an allowlisted tool, matching actor, and `HUMAN_REVIEW` permission on every source ancestor. Succeeded disposition writes `supersedes` lineage to the predecessor and `imported_from` to the basis artifact. Rejection excludes the predecessor from active selection; conflicting active successors fail preflight.
- **Structural Stage 5 eligibility**: Stage 5 token alignment accepts only `SegmentAlignment` records whose status is `structural` or `approved`. Candidates, inferred alignments, and rejected predecessors are excluded.
- **Lineage**: Each `SegmentAlignment` group links to every member Segment via a `derived_from` lineage edge (no Cartesian group-to-group edges).
- **Database constraints**: Schema `0003` enforces append-only triggers, database-owned `creating_txid`, and deferred constraint triggers validating group completeness, contiguous positions, and homogeneous sides. Downstream downgrades refuse if any alignment rows or registry entries exist.

### TokenAlignmentEdge
Directional token-level alignment evidence linking tokens between aligned segments.
- **Attributes**: `source_token_id`, `target_token_id`, `direction` (`forward`, `reverse`, `symmetrized`), `algorithm` (`name@version`), nullable `score`, `raw_scores` (dictionary of finite float components), `symmetrization` (`none`, `intersection`, `union`), `run_id`, `segment_alignment_id`, `created_at`.
- **Direction and symmetrization**: `forward` and `reverse` directions require `symmetrization="none"`; `symmetrized` direction requires `symmetrization in {"intersection", "union"}`. Grow-diag heuristics are explicitly excluded (ADR-0011 §5).
- **Index direction**: Explicit direction between source and target tokens; statistical aligner adapters translate between zero-based token matrix ordinals and persistent `TokenOccurrence` IDs.
- **Lineage**: Each `TokenAlignmentEdge` links to its parent `segment_alignment_id`, its `source_token_id`, and its `target_token_id` via `derived_from` lineage edges.
- **Null handling**: Unaligned tokens are recorded in the alignment report as unaligned occurrence IDs rather than fictitious NULL edges; tokens that remain unaligned in a challenge or golden fixture are preserved without linguistic promotion.

Alignment is evidence, not translation truth.

## Evidence

`EvidenceItem` kinds include:

- dictionary assertion;
- token alignment;
- segment co-occurrence;
- IGT assertion;
- grammar description;
- speaker review;
- morphology induction;
- related-language comparison;
- monolingual distribution;
- manual annotation.

Fields include kind, source/run, target claim/object, polarity (`supports`, `contradicts`, `context_only`), strength metadata, independence group and domain/register context.

## Lineage

`LineageEdge` kinds:

```text
derived_from
generated_from
normalized_from
extracted_from
imported_from
supersedes
stale_dependent
```

`stale_dependent` ([ADR-0014](adr/0014-review-staleness-and-authority-config.md), migration 0005) is a marking edge written child → parent by the review service on a decided lexeme's senses: `to_id` is the object an authorized review decided, `from_id` is the directly dependent record that needs recalculation. It marks; it never mutates or deletes anything. The 0005 downgrade refuses while any `stale_dependent` edge exists.

Lineage must support transitive impact analysis.

## Review entities

### ReviewTask
Typed request for human judgment about one registered object (`target_id`).

**Storage (M4)** ([ADR-0013](adr/0013-lexical-model-and-review-authority.md)): table `review_task`, ID prefix `rtask`. Fields: `task_type`, `target_id`, optional `target_version`, `evidence_item_ids`, `required_role`, `priority`, `reason`, `creator_run_id`, `status`, `created_at`. `task_type` is one of nine values: `lexical_sense`, `lemma`, `morphology_segmentation`, `morpheme_function`, `grammar_construction`, `register_domain`, `alignment_spotcheck`, `governance_export`, `pronunciation` (M4 producers create lexical types only, ADR-0013 §5). `status` is a task-workflow state — `open`, `in_review`, `resolved`, `cancelled` — *not* a `LifecycleStatus`: lifecycle status belongs to the reviewed object, never to the queue entry.

### ReviewDecision
Immutable decision: accept, reject, modify, uncertain, defer.

**Storage (M4)**: table `review_decision`, ID prefix `rdec`. Fields: `task_id`, `target_id`, `decision` (`accept`, `reject`, `modify`, `uncertain`, `defer`), `reviewer_id`, `reviewer_role`, optional `superseding_object_id`, optional `notes`, `created_at`. The table is append-only at the database level (INSERT-only trigger): a changed opinion records a new decision and never edits one.

## Lifecycle

Inference-bearing objects:

```text
candidate
supported
validated
rejected
deprecated
```

- `candidate`: hypothesis exists.
- `supported`: evidence policy met, not equivalent to human validation.
- `validated`: accepted by an authorized validation basis.
- `rejected`: incorrect/inapplicable.
- `deprecated`: superseded/retired.

`validated` requires a recorded validation basis. Algorithmic confidence alone cannot create it.

## Cardinalities

```text
Source           1 ─ * SourceObject
Source           1 ─ * Segment
Segment          1 ─ * TokenOccurrence
TokenOccurrence  * ─ 1 Form (per profile)
Form             * ─ * Lexeme (via form_lexeme)
Lexeme           1 ─ * Sense
Sense            * ─ 0..1 Concept
TokenOccurrence  1 ─ * MorphAnalysis
MorphAnalysis    1 ─ 1..* MorphSegment
MorphSegment     * ─ 0..1 Morpheme
Morpheme         1 ─ * Allomorph
Lexeme           * ─ * Paradigm
Paradigm         1 ─ * ParadigmSlot
Any inference    * ─ * EvidenceItem
Any derived obj  * ─ 1 ProcessingRun
ReviewTask       1 ─ * ReviewDecision
ReviewTask       * ─ 1 target (any registered object)
```

`Sense * ─ * Concept` remains the logical target, but the M4 storage model is `0..1`: one optional `concept_id` per Sense. Widening to many-to-many requires a migration and an ADR.

## Relational realization (M4)

All IDs FK `object_registry.id` ([ADR-0009](adr/0009-relational-lineage-and-append-only-observations.md)).

| Entity | Table | ID prefix | Lifecycle column | Append-only | Key FKs |
|---|---|---|---|---|---|
| Concept | `concept` | `cpt` | — | no | `run_id → processing_run` |
| Lexeme | `lexeme` | `lex` | `status` | no | `lemma_form_id → form` (nullable), `run_id → processing_run` |
| FormLexemeLink | `form_lexeme` | `flx` | — | yes | `form_id → form`, `lexeme_id → lexeme`, `run_id → processing_run`; unique `(form_id, lexeme_id)` |
| Sense | `sense` | `sense` | `status` | no | `lexeme_id → lexeme`, `concept_id → concept` (nullable), `run_id → processing_run` |
| ReviewTask | `review_task` | `rtask` | — (workflow `status`: `open`/`in_review`/`resolved`/`cancelled`) | no | `target_id → object_registry`, `creator_run_id → processing_run` |
| ReviewDecision | `review_decision` | `rdec` | — | yes | `task_id → review_task`, `target_id → object_registry`, `superseding_object_id → object_registry` (nullable) |

## Versioning

Observations are immutable except explicit administrative correction.

Inference objects use explicit versions or supersession when semantics change. Never rewrite a rejected hypothesis into a different hypothesis under the same identity.

## Required graph queries

- Which sources support this sense? — answered in M4 by `ancestor_source_ids` over the lineage DAG (`src/langpipe/governance/lineage_policy.py`; the reverse direction is `langpipe lineage descendants`).
- Which tokens were analyzed with this morpheme?
- Which descendants depend on a revoked source? — answered in M4 by `revocation_impact`, computed over the lineage DAG ([ADR-0015](adr/0015-computed-revocation-impact.md)).
- Which competing analyses exist for this form?
- Which validated senses lack cross-source evidence?
- Which high-frequency forms remain unanalyzed?
