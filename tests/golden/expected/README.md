# Golden expectations

`m1/` holds the expected M1 snapshot: `sources.json`, `source_objects.json`, `runs.json`,
`artifacts.json`, `lineage.json`, `audit.json` and `eligibility.json`. The test
`test_golden_m1_snapshot` compares the normalized database state against these files.

`m2/` holds the expected M2 snapshot: `runs.json` (extraction/normalization/tokenization runs),
`segments.json` (raw and normalized segments), `tokens.json`, `forms.json`, `lineage.json`
(M2 edge kinds by layer) and `reports.json` (report counts only). The test
`test_golden_m2_snapshot` compares the normalized M2 state against these files.

`m3/` holds ID-normalized segment groups, token edges, allowlisted reports, lineage, and benchmark
metrics. `test_golden_m3_snapshot` compares these files after the pinned mock alignment pipeline.
Mock links establish infrastructure behavior only and do not assert statistical output.

`m4/` holds the nine ID-normalized sections of the lexical world (`runs.json`, `lexemes.json`,
`senses.json`, `evidence.json`, `review.json`, `lineage.json`, `export.json`, `revocation.json`,
`reports.json`). `test_golden_m4_snapshot` compares them after induction from both paths (alignment
and wordlist), the review decisions T1-T7, the revocation of `01-parallel-distill` and the CLDF
exports; all ids are semantic labels (`lex:<source>:<headword>`, `task:T1`, ...) and the normalizer
fails if any raw ULID survives. A second synthetic wordlist source under `fixture/lexicon/` is the
only policy that grants `redistribute_derived`, so it alone produces export rows.

## Update rules

1. Do not regenerate snapshots to make a failing test pass. A change needs a semantic reason and
   matching updates to the docs, schemas and migrations that define the behavior.
2. To rewrite the files, run `LANGPIPE_UPDATE_GOLDEN=1 uv run pytest tests/golden/test_golden_m1.py::test_golden_m1_snapshot`
   (or `tests/golden/test_golden_m2.py::test_golden_m2_snapshot`,
   or `tests/golden/test_golden_m3.py::test_golden_m3_snapshot`).
   The test still fails after writing. Read the diff with `git diff tests/golden/expected`, then
   commit the change on purpose.
3. Do not add skip-marked placeholder tests for later milestones. Record pending items below.

## Pending expectations (not checked yet)

| Milestone | Pending expectation |
|---|---|
| M5 | The IGT-validated morpheme `-ki`, the competing segmentation of `wesa-ra`, the unknown morpheme (the fixed corpus does not explicitly identify an unglossed component; `wesa-ra`, glossed `ir-NEG`, is only a candidate for ambiguity analysis, not missing-gloss evidence), and review accept/reject decisions for IGT-1 and IGT-2 |

The M3 expectations are now checked: `m3/` holds the TXT.1.4 1:n group, the `wesa-ra` whole-token
null case and the standalone `foo -ra` null challenge. Correctness of those snapshots is not read
off the snapshots alone: `tests/golden/test_golden_m3.py` also compares persisted
`SegmentAlignment.group_key` values against independently recomputed canonical hashes and asserts
exact real-identifier lineage parent sets for groups, edges, reports and the benchmark report.
