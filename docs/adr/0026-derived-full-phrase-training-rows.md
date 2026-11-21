# ADR-0026: Derived full-phrase training rows

**Status:** Accepted (owner-approved design, Opus and GPT reviews, 2026-10-20)

## Context

Chant line rows are 2 to 4 words. The Wenía 2018 Portuguese is couplet-aligned, not
line-aligned, and the Cesarino 2017 (Zenodo 1008779) rows are clause fragments of sentences.
Line rows therefore teach the model fragments. The row judgement
(`var/artifacts/opus_judge/judgement.md`) found that deterministic concatenation of printed
blocks gives faithful longer units, if lineage and leakage are controlled.

## Decision

1. **New row type: derived segment.** A derived row is the concatenation of consecutive,
   verified-corresponding attested line rows of one harvested source. Two unit kinds:
   `stanza` (a printed Wenía block of 2 to 12 lines) and `sentence` (Cesarino 2017 lines up to
   the next line where both sides end a sentence).
2. **No new text.** Members are joined by a recorded separator (`" "`). Nothing is rewritten,
   translated, repaired or invented. Blocks or units that cannot be verified are skipped, never
   fixed: single-line blocks, OCR residue in the Portuguese, footnote digits, unfinished tails.
3. **Train only.** `split_constraint = train_only`. Derived rows are never selected for
   val, test, or the chant benchmark.
4. **Lineage.** Each row carries ordered, source-qualified `member_refs`
   (`provenance`, `ref`), the source file checksum and location, the layout PDF checksum
   (Wenía), and a derivation version plus a deterministic run id (hash of version and input
   checksums; no clock).
5. **Leakage control.** Before any dedup removes a row, the exporter builds components over all
   harvested line rows, the pinned eval rows and the derived rows. Edges: equal folded Marúbo
   key, equal folded Portuguese key (same side only), and derived-to-member. A derived row whose
   component contains a val, test or chant-benchmark row is excluded. Eval membership is
   pinned: derived rows can only be excluded, and no row ever moves from eval to train. Members
   dropped as exact duplicates keep an alias to the retained row, written to
   `derived_rows_audit.json`. The folded key stays comparison-only.
6. **Loader.** `load_derived_rows` reads `*_derived.jsonl` (not matched by the line loader's
   `*_parallel.jsonl` glob). It validates every record and marks rows `is_derived=True`,
   `is_attested=False`. They are not attested single-line rows.
7. **Export.** Derived rows are written to train in all three formats with a `derived` object
   (`unit_kind`, `split_constraint`, `member_refs`, `separator`, `register`, `derivation`).
   The manifest records `derived_train_count`, `derived_built_count`, `derived_excluded`
   (by reason) and `derived_by_unit_kind`.

## Consequences

- Most derived rows are excluded: a stanza is excluded when any of its lines, or any line
  sharing a folded key with one of them (refrains), is in val, test or the chant benchmark.
  This is intended; the benchmark stays frozen.
- Persisted formats change (invariant 11): see
  `docs/research/derived-rows-migration-note.md` and
  `schemas/exports/derived-parallel-row.v1.schema.json`.
- Block detection re-reads the Wenía PDF with the extractor's own row test and fails if any
  line differs from the harvested row. A stanza cannot cross a page break.
- Scores on a benchmark are unchanged by this ADR; train content changes.
