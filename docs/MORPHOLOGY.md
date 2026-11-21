# Morphology Contract

This document defines how morphological knowledge is represented. It does not prescribe one induction algorithm.

## Core principle

A written word is not assumed to be a single lexical unit, and a proposed segmentation is not assumed to be correct.

The system must preserve surface evidence, multiple competing analyses, unknown analyses, language-specific categories, and source/algorithm provenance.

## Analysis target

The preferred analysis target is a `TokenOccurrence`.

A reusable Form MAY also have generalized analyses, but occurrence-level analyses remain necessary because context can disambiguate morphology.

## MorphAnalysis

```yaml
id: ma_01
target_token: tok_01
status: candidate
method:
  kind: morfessor
  version: "..."
score:
  overall: 0.61
segments:
  - ordinal: 0
    span: [0, 3]
    surface: "abc"
    morpheme_id: morph_root_01
  - ordinal: 1
    span: [3, 4]
    surface: "d"
    morpheme_id: null
  - ordinal: 2
    span: [4, 7]
    surface: "xyz"
    morpheme_id: morph_suffix_02
```

A competing analysis is a different MorphAnalysis object.

## Unknown analysis

Always allow an unsegmented/unknown analysis. The system MUST NOT force segmentation merely because an algorithm emitted one.

## Morpheme

A Morpheme is a reusable linguistic hypothesis/type, not a string.

Possible role categories:
- root;
- lexical stem;
- derivational affix;
- inflectional affix;
- clitic;
- reduplicant;
- bound lexical element;
- unknown.

Role categories are extensible per language.

## Allomorphy

One Morpheme may have several Allomorphs with phonological, morphosyntactic, lexical, or unknown conditioning.

Do not create separate morphemes solely because strings differ. Do not merge strings solely because functions seem similar.

## Root vs stem

Distinguish:
- `Morpheme(kind=root)` — reusable minimal lexical hypothesis;
- `Lexeme` — lexical dictionary unit;
- `stem` — analysis role realizable by one or more morphemes/forms.

Do not add a global Stem entity in v1 unless real data demonstrates the need.

## Affix vs clitic

This may be uncertain. Represent competing role hypotheses rather than hard-coding a category.

## Zero realization

Zero morphemes are supported only when backed by explicit linguistic evidence. Represent zero realization with zero-width structure, never invented visible characters.

## Fusion

A surface segment may realize multiple features.

If one segment may realize multiple morphemes, preserve this as an open modeling question rather than forcing a one-span/one-morpheme assumption.

## Reduplication

Represent copied material as visible MorphSegments and relate it to the base when known. Do not normalize copied material away.

## Features

Prefer external namespaces when faithful:

```text
unimorph:...
ud:...
```

Use local features when required:

```text
local:mzr:graded_tense:...
```

Each local feature needs a stable ID, definition, evidence/source, and optional mapping attempts.

## Paradigms

Paradigms are sparse. Missing means unknown/unobserved, not impossible.

## Inflection vs derivation

Treat as linguistic analysis, not required storage truth. Bound morphology may remain `unknown_bound` until validated.

## Benchmarking

Compare at minimum:
- no segmentation;
- BPE/SentencePiece baseline;
- Morfessor baseline;
- morphology-aware alternative such as FlatCat when maintained/available;
- documented-rule constrained approach when enough evidence exists.

Evaluate boundary precision/recall/F1, stem preservation, known-affix preservation, ambiguity behavior, downstream chrF++, and downstream feature error.

Intrinsic F1 alone does not choose the production method.

## Promotion

Machine-produced MorphAnalysis starts `candidate`, may become `supported` under evidence policy, and requires allowed validation basis to become `validated`.

## Open morphology questions

### OPEN-MORPH-001 — Fusion representation
Whether one segment should directly realize multiple Morphemes or only multiple features.

M5 status: resolved for features — one segment can realize multiple Features
(each with its own assignment row); a segment still links ≤1 Morpheme, so
multi-morpheme segment fusion stays open (ADR-0017 §4, §9).

### OPEN-MORPH-002 — Clitic representation in UD export
Feature vs separate node vs multiword-token strategy.

M5 status: deferred and untouched in M5 (ADR-0017 §9).

### OPEN-MORPH-003 — Type-level canonical analyses
Whether Form-level analyses should be materialized or always derived from occurrence-level analyses.

M5 status: resolved for M5 — analyses target `TokenOccurrence` exclusively
(`MorphAnalysis.target_token_id`); type-level Form analyses remain deferred
(ADR-0017 §3).

### OPEN-MORPH-004 — Competing role hypotheses
Affix vs clitic (and inflection vs derivation) may be uncertain; competing role
rows are deferred. In M5 the importer assigns a segment's role only from
explicit source markers, and role correction happens only through review
`modify`; multi-method induction may later produce competing role rows
(ADR-0017 §9).

### OPEN-MORPH-005 — Underlying vs surface morph representation
`\m` lines may give underlying forms that differ from the surface. In M5,
underlying `\m` lines are mapped to the token surface when exact alignment is
possible; otherwise the morpheme/allomorph is recorded with
`form_basis=underlying` and surface segmentation is omitted for that word
(ADR-0017 §9).

First schemas must keep these choices reversible.
