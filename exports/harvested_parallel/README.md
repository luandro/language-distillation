# exports/harvested_parallel

| File | Content |
|---|---|
| `*_parallel.jsonl` | Harvested line rows (`ref`, `src`, `tgt`, `eng`, optional `qc`). Read by `load_harvested_parallel_sentences`; split into train, val, test. |
| `cesarino_2018_wenia_tilde_marks.json` | Tilde marks used by the Wenía extraction. |
| `cesarino_2018_wenia_stanza_derived.jsonl` | Derived train-only stanza rows (ADR-0026): consecutive Wenía lines of one printed block, joined by one space. |
| `zenodo_1008779_cesarino_marubo_2017_sentence_derived.jsonl` | Derived train-only sentence rows: Cesarino 2017 lines up to a sentence end on both sides. |
| `derived_build_report.json` | Counts, skipped blocks with reasons, output checksums of the last build. |

Rebuild derived files (deterministic): `.venv/bin/python -m langpipe.synthesis.derived_rows build`.
Schema: `schemas/exports/derived-parallel-row.v1.schema.json`. Derived files are not matched by
the `*_parallel.jsonl` loader; `load_derived_rows` reads them. The exporter drops every derived row
whose key component touches val, test or the chant benchmark.
