# Migration note: derived full-phrase rows (ADR-0026)

Persisted-format changes (invariant 11), all additive:

1. **New files** `exports/harvested_parallel/*_derived.jsonl` and `derived_build_report.json`.
   Schema: `schemas/exports/derived-parallel-row.v1.schema.json` (`schema_version` 1). The line
   loader glob `*_parallel.jsonl` does not match them; existing readers are unaffected.
2. **Dataset records** (`{train,val,test}.{hf,alpaca,chatml}.jsonl`): train rows built from a
   derived row gain an optional `derived` object. Rows without it are byte-identical to before.
   Consumers that ignore unknown keys need no change. Val and test never carry `derived`.
3. **Manifest** gains `derived_train_count`, `derived_built_count`, `derived_excluded`,
   `derived_by_unit_kind`, `derived_audit_file`, `derived_audit_sha256`. Missing keys read as 0 /
   empty for manifests written before this change.
4. **New file** `derived_rows_audit.json` next to the manifest: kept ids with members, excluded
   ids with reason, and member aliases for deduplicated line rows.

Backward: delete the derived files and `derived_rows_audit.json`, re-run
`langpipe synth export --lang mzr`; the export without derived rows is the previous format.
Rebuild: `.venv/bin/python -m langpipe.synthesis.derived_rows build --lang mzr`
(deterministic). The harvested file names, provenance strings and layout page range are
profile data (`LanguageProfile.harvested_sources`), so `--lang` selects them and generic
builder code names no language or corpus.
Tests: `tests/unit/test_derived_rows.py`.
