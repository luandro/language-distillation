# ADR-0010: Text Processing and Derived Segments

## Status

Proposed (Decided for Milestone 2)

## Context

In Milestone 1, `Segment` rows record raw extracted text and are enforced as append-only via database triggers (`langpipe_forbid_mutation` in ADR-0009).

Milestone 2 introduces Stage 2 (Extraction) and Stage 3 (Normalization and Tokenization). Normalization must produce normalized representations of segments and record normalization events and diagnostics. However, modifying `Segment.normalized_text` and `Segment.normalization_profile` in place on an existing extracted segment would violate:
1. ADR-0009 append-only database triggers (SQLSTATE 23001 `restrict_violation`).
2. The core invariant that observations are immutable and stages do not mutate inputs.

Furthermore, typological research and language profile guidelines for Marúbo (`mzr.md`) indicate that clitic and affix boundaries (e.g. `-ki`, `-ra`, `txipo`, `shovimakĩ`) represent linguistic interpretation and morphological analysis, not raw character-level tokenization. Splitting clitics at Stage 3 would violate AGENTS.md invariant 9: *"Do not use an LLM or unverified heuristics to invent target-language morphology"*.

## Decisions

1. **Derived Segments with Relational Lineage**:
   A normalization run produces a *new* `Segment` row for each input raw segment. The new segment:
   - Copies `raw_text`, `locator`, `language`, `source_id`, `source_object_id`, and `ordinal` verbatim from the raw segment.
   - Sets `normalized_text` and `normalization_profile` (or sets `status=normalization_failed` with `normalized_text=None` if normalization fails).
   - Records a lineage edge: `seg_norm --normalized_from--> seg_raw` with the normalization run ID.
   - Is recorded as run output of the normalization run (the raw segment is run input).

2. **Stage Separation: Two Processing Runs**:
   Stage 3 executes as two distinct runs:
   - `RunStage.NORMALIZATION`: takes raw segments as input, produces normalized segments.
   - `RunStage.TOKENIZATION`: takes normalized segments as input, produces `TokenOccurrence` and `Form` records linked via `tok --derived_from--> seg_norm`.

3. **Conservative Word-Level Tokenization**:
   The tokenizer preserves hyphenated words and words with internal apostrophes as single tokens (e.g., `mabi-ki` is a single token with a single character span). Splitting into morphemes and clitics is strictly deferred to Stage 8 (Morphology induction, M5) as `MorphAnalysis` candidates.

4. **Pure, Versioned Components**:
   Extractors, NormalizationRules, and Tokenizers are pure functions without side effects, registered under immutable versioned names `name@version` (`VERSIONED_NAME`).

5. **Backward Compatibility**:
   `ObservationRecorder.record_tokens` accepts either a normalized segment (M2 standard) or a raw segment (for backward compatibility with M1 synthetic tests), enforcing that if `segment.normalization_profile` is set, `orthography_profile` must match it.

## Consequences

- Append-only database triggers require zero modification.
- Lineage graph captures the exact derivation chain: `SourceObject -> Segment(raw) -> Segment(normalized) -> TokenOccurrence -> Form`.
- Normalization failures are tracked losslessly with `status=normalization_failed` without polluting downstream tokenization.
- Clean isolation between orthographic normalization (Stage 3) and morphological analysis (Stage 8).
