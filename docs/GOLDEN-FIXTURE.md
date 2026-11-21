# Golden End-to-End Fixture

The golden fixture is normative executable documentation.

## Purpose

A coding agent should be able to run a tiny corpus through the pipeline and prove it understood the semantics.

Use synthetic/permission-safe fixture data rather than restricted real language data.

## Required sources

1. one `distill_only` bilingual structured source;
2. one `direct` educational-like bilingual source;
3. one tiny dictionary/wordlist;
4. one IGT document;
5. one monolingual target-language text.

## Required phenomena

Exercise:
- same surface form in multiple occurrences;
- one form with two candidate senses;
- one 1:n segment alignment;
- one unaligned token;
- one competing morphology segmentation;
- one validated morpheme from IGT;
- one unknown morpheme;
- one orthographic variant;
- one domain-specific lexical item;
- one review accept;
- one reject/uncertain review;
- one revoked source used for lineage impact.

### Null links vs. morphology interpretation
Whole-token null infrastructure is strictly separated from suffix-level morphological analysis:
- In M3, unaligned tokens (e.g. standalone punctuation/word tokens such as `foo -ra` yielding separate occurrences `foo`, `-`, and `ra` where `-` and `ra` have no links) exercise infrastructure null handling and unaligned occurrence reporting in `token-alignment-report`.
- By contrast, internal token spellings such as `wesa-ra` remain a single unsegmented `TokenOccurrence` during M2 and M3. Analyzing `-ra` as an affix or morpheme belongs exclusively to M5 morphology induction and is never asserted by alignment evidence. M5 retains sole ownership of sub-token morphological segmentation.

## Expected outputs

Check in expected snapshots/assertions for sources, segments, tokens, forms, alignments, evidence, lexeme/sense candidates, morph analyses, lineage, review decisions and eligibility results.

## Critical invariant tests

### Observation/inference separation
Changing MorphAnalysis must not modify TokenOccurrence.

### Ambiguity
Two analyses may coexist.

### Governance
A `distill_only` sentence is trainable (ADR-0025); its source cannot be redistributed raw.
An `exclude` source is never processed.

### Revocation
Revoking a source marks transitive dependent exports affected/ineligible until rebuilt.

### Idempotence
Same stage/config does not create semantic duplicates.

### Reproducibility
Outputs record run/tool/config identifiers.

## Updating golden outputs

Do not regenerate snapshots blindly. Expected changes require an intentional semantic change plus relevant docs/schema/migration updates.
