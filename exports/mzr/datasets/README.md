# mzr datasets (benchmark version 2)

Produced by `langpipe synth export --lang mzr`. `manifest.json` records every count, the
sha256 of every file, the register histogram and `benchmark_version: 2`.

| File | Content |
|---|---|
| `{train,val,test}.{hf,alpaca,chatml}.jsonl` | Primary splits in three formats. Train 5018 (5000 line/other rows + 18 derived), val 546, test 241. |
| `benchmark_v2_audit.json` | Every held-out Bible row repaired or excluded in v2, with reason and original text. |
| `derived_rows_audit.json` | ADR-0026 derived full-phrase rows: kept ids with member refs, excluded ids with reason, member aliases. Derived rows are train-only (`derived` object on the record). |
| `chant_benchmark/` | Separate ritual-chant benchmark: `test.hf.jsonl` (100), `val.hf.jsonl` (40), `manifest.json`. |

Benchmark v2 differs from the legacy v1 held-out text (`../datasets_legacy/v1/`):

- 14 val / 8 test Bible rows had whitespace before punctuation in the Portuguese; it is removed.
  (27 / 14 rows had it in v1; 13 / 5 of those are edition-note rows and are excluded instead.)
- 20 val / 9 test Bible rows carry a textual-apparatus note (TR/RP/N4). They are excluded, not
  refilled, and not returned to train. They are restorable only by a verified correction in a
  later benchmark version.

Scores are comparable only within one benchmark version. Do not compare v2 scores with v1 or v0
numbers.

## Chant benchmark

Chant rows (Wenia and Cesarino 2017) carry the register `ritual_chant`. The primary splits keep
the 0.2 register cap, so primary test holds 50 chant rows. The chant benchmark is exempt from
that cap and is the place to measure chant quality: test 100 rows (50 reused from primary test,
50 moved out of train) in 96 components, val 40 rows (all inside primary val) in 40 components.
Rows are whole components, linked by a shared folded Marubo or Portuguese key, stratified by
source and word length. Bootstrap by `component` (a field on every row), not by row. The chant
benchmark rows are excluded from train; 50 of 590 chant train rows (8.5%) moved out.
Details: `chant_benchmark/manifest.json` and `docs/EVALUATION.md`.

Reproduce: `langpipe synth export --lang mzr -o <dir>` gives byte-identical files (manifest
differs only in `output_dir`).
