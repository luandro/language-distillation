# Marúbo (`mzr`) Pilot Profile

This is an implementation profile, not a complete grammar.

Claims not independently checked against primary sources remain working assumptions.

## Identity

```yaml
name: Marúbo
iso639_3: mzr
family: Pano
pilot: true
```

## Objective

Use heterogeneous Marúbo resources—parallel religious material, educational/community publications, linguistic descriptions/IGT, wordlists and audio—to build an auditable LKB without allowing the largest source domain to determine language style.

## Working typological assumptions

Research supplied to the project describes predominantly SOV order, agglutinative morphology, ergative/absolutive phenomena, suffix/clitic complexity, graded temporal distinctions and meaningful register distinctions.

These MAY guide benchmark design but MUST NOT be hard-coded as validators until supported by imported Marúbo evidence.

## Initial register taxonomy

```text
everyday
pedagogical
administrative
religious
traditional_public
ritual_restricted
historical
unknown
```

Sensitive/restricted classification MAY be recorded by an authorized Marúbo reviewer.
Register labels are descriptive metadata and never gate processing or training (ADR-0025).

## Source policy

A source present in `var/external/` is authorized for processing and training
(ADR-0025). Licenses, ownership, and register labels are recorded metadata, not gates. A
manifest with no `policy:` block gets the repository default `direct`/`public`/`repo-owner`
(`default_policy_spec()`); only an explicit `exclude` blocks a source. A source may still be
classified `distill_only` for raw-redistribution reasons, but that label never blocks
training.

Register labels (`everyday`, `pedagogical`, `technical`, `historical`, `traditional_public`,
`ritual_restricted`, …) MAY be recorded for a source or a segment. They are descriptive.

## Cold-start alignment

- canonical structural alignment where IDs exist;
- eflomal adapter as token-alignment baseline;
- neural alignment experimental until local benchmark.

## Morphology priorities

Early benchmark attention:
- recurring suffix-like forms;
- case-related morphology;
- negation;
- temporal morphology;
- person/number where evidenced;
- clitic ambiguity;
- stem preservation.

Do not pre-populate them as facts.

## IGT

Academic IGT is a priority source class. Preserve published layers before mapping to internal features.

## Related-language reference

Shipibo-Konibo and other Pano resources MAY inform annotation conventions, benchmark design and hypothesis generation, but not automatic Marúbo truth.

## Evaluation priorities

Focus on phenomena confirmed by source material, with early attention to word order, case, negation, temporal morphology, orthographic variants and register contamination.

## Speech

If aligned audio is used:
- preserve originals;
- processing copies may be mono 16 kHz;
- build a versioned G2P from verified evidence;
- MFA is the initial forced-alignment baseline, not a permanent assumption.

## ScriptureEarth acquisition (WP2.15)

Manual, operator-run steps. They are not code and must not be automated by the pipeline.

1. Check and record the license and rights holder for the Marúbo text on
   `https://www.scriptureearth.org/00por.php?iso=mzr`. This is a record, not a gate (ADR-0025):
   under the repository rule the source is processed because it is present. Record what was
   checked, where, and when. Redistribution stays denied and corpus bytes never enter git.
2. The nine books are ACT, EXO, GEN, JAS, JHN, LUK, NEH, RUT and XXF. Copy their bytes unchanged
   (never move or edit the originals) into `var/external/scriptureearth/mzr/usfm/`. Timing files
   may go to `var/external/scriptureearth/mzr/timing/`. `var/` is gitignored; do not commit any of
   it, not even an excerpt.
3. Build `var/external/scriptureearth/mzr/langpipe-manifest.yaml` with
   `langpipe scriptureearth manifest` and record the license/rights-holder findings in
   `provenance.notes`. The note SHOULD state what license or terms were checked, where the
   evidence is, and who checked it. The manifest may omit `policy:` (it then defaults to
   `direct`/`public`/`repo-owner`), or declare `mode: direct` explicitly. Timing objects, when
   included in the manifest, are preserved and hash-checked but never parsed as USFM. Export
   `LANGPIPE_MZR_SE_DIR=$PWD/var/external/scriptureearth/mzr` and
   `LANGPIPE_MZR_SE_MANIFEST=$LANGPIPE_MZR_SE_DIR/langpipe-manifest.yaml`.

A corpus kept under a tests directory is acceptable only in a gitignored local subdirectory with
the same manifest and path restrictions; committed tests contain synthetic data only.

The real-data test is selected explicitly (`uv run pytest -m realdata`), is deselected by default,
and never downloads. A missing package or manifest is a **failure, not a skip**. The reviewed
per-book counts live in `tests/integration/expected/scriptureearth_mzr_counts.json`; the count
tests fail until a senior fills and signs `reviewed_by`. An observed code-point inventory report
may be written via `LANGPIPE_MZR_SE_REPORT_DIR`: the test's temporary directory (the default),
a local directory outside the repository, or a directory inside the repository only when the
report file itself is gitignored and untracked (`var/...` qualifies). Tracked or nonignored
destinations inside the repository are rejected before anything is written, and the global
`.gitignore` is never extended to hide operator-chosen paths. The report is count-only
(`U+XXXX` labels), stays `status: unverified`, is a report for human review, never a verified
inventory, and is never committed. Real-data failures are content-free in every output channel:
assertions report IDs, counts and `U+XXXX` labels only; captured stdout/stderr/log sections of
`realdata` tests are redacted on the report; and the failure report itself (`longrepr`,
including unexpected exceptions in setup, call or teardown, chained exceptions and rewritten
assertion operands) is reduced to the exception type plus safe test identity/location — never
exception messages, source excerpts, locals, cause/context chains or data-bearing paths. Fixed
diagnostics survive only through an explicit safe-diagnostic marker attached by the test
helpers; every unmarked `pytest.fail` message is redacted like any other failure detail.
Default-suite diagnostics are untouched.

## Dual-source ScriptureEarth alignment (mzr–por, WP3.13)

Operator-run steps. They are not code and must not be automated by the pipeline. The two
packages are independent records: copying the Portuguese bytes into `var/external/` is what
authorizes their processing (ADR-0025), and its own manifest keeps the provenance record.

1. Check and record the license and rights holder for the Portuguese text on
   `https://www.scriptureearth.org/00por.php?iso=por` (or the operator's chosen source). This
   is a record, not a gate: the source is processed because it is present. Redistribution
   denial and local corpus bytes staying out of git are unchanged.
2. Copy the Portuguese USFM bytes unchanged into a package directory, e.g.
   `var/external/scriptureearth/por/usfm/`. Do not move or edit originals. `var/` is gitignored;
   do not commit any of it, not even an excerpt.
3. Build `var/external/scriptureearth/por/langpipe-manifest.yaml` with
   `langpipe scriptureearth manifest` and record the license/rights findings in
   `provenance.notes`. This dual-source workflow needs an explicit `policy:` block because
   step 4 records `policy.restrictions.versification_id`; declare `mode: direct` (or omit
   the mode and let the repository default apply). Ingest, read_raw, extract, normalize and
   align resolve allow; outward operations stay denied.
4. Record two distinct identifiers for each package. They mean different things and neither
   substitutes for the other:
   - `policy.restrictions.versification_id` declares the **coordinate scheme** of that
     edition — the mapping from (book, chapter, verse) to counted verses. Both packages must
     declare the **same** `versification_id`: M3 has no automatic versification mapping, and a
     mismatched or missing declaration fails the pair before any work runs. Matching
     declarations assert coordinate compatibility only; they do not prove the two editions
     actually use the same versification, which remains an operator judgment.
   - `source_mzr.edition` / `source_por.edition` in
     `tests/integration/expected/scriptureearth_parallel_counts.json` identifies the actual
     reviewed published/distributed edition — preferably a stable publisher or ScriptureEarth
     distribution identifier with provenance, never an internal alias. **The two editions are
     distinct objects**: the mzr edition and the por edition keep their own identifiers, and
     having different edition ids is normal and expected; it is the versification that must
     match, not the edition. No edition is guessed here.
5. Export the four environment variables:
   `LANGPIPE_MZR_SE_DIR`, `LANGPIPE_MZR_SE_MANIFEST`, `LANGPIPE_POR_SE_DIR`,
   `LANGPIPE_POR_SE_MANIFEST`, then run
   `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -m realdata tests/integration/test_scriptureearth_parallel.py -q`.

A missing variable, a missing package directory or manifest, an inconsistent manifest,
incompatible pair declarations, or unsigned counts in
`tests/integration/expected/scriptureearth_parallel_counts.json` are
**failures, never skips**: this opt-in suite is a gate on dual-source *processing
integrity*
(pair compatibility, counts, redaction), not on licence or ownership, so it can never
silently pass.

### Signing the counts file (senior step)

`tests/integration/expected/scriptureearth_parallel_counts.json` has exactly two legal states,
and the review gate enforces both:

- **unsigned template** (the committed state): `status: "unsigned"`, `reviewed_by`/`reviewed_at`
  `null`, `expected_counts.*.null` and `UNREVIEWED - …` edition/versification placeholders. A
  template **fails** the gate, so the suite cannot pass until the file is signed. Only this
  state may carry null counts and placeholders — even with a `reviewed_by` value set.
- **complete reviewed record**: `status: "reviewed"`, a real non-placeholder `reviewed_by`, a
  valid RFC-3339 `reviewed_at`, real (non-`UNREVIEWED`) `edition` and `versification` for both
  sides, `package_sha256_inventory` maps keyed by sha256 with nonnegative integer sizes, and
  nonnegative integer (never `null`, `bool`, float or negative) counts for `common_groups`,
  `unmatched_source`, `unmatched_target` and each `book_inventory` pair. Every incomplete field
  individually fails the gate.

Signing is a senior step after an **independent rescan** of the real pair: run both reviewed
packages, cross-check the counts, then record the observed values. Do not self-sign; do not
fabricate a signature, permission, edition or total. The file records metadata only — package
sha256 inventories with sizes, editions, versification ids, `reviewed_by`/`reviewed_at`, and
group/unmatched/book counts — never surface text, corpus bytes, book content or operator paths.

Because the file has two legal states, the tests validate the committed record **by its status**:
the unsigned template must stay structurally valid and gate-rejected, while a signed complete
record must pass. Every negative case is built in memory from a synthetic record constructor, and
the gate's verdict is additionally proved by patching `Path.read_text` — the file is never written
by a test, and no fabricated signature is ever persisted. Signing the checked-in file therefore
keeps both suites green in either direction.

The `package_sha256_inventory` of each side covers **every registered object of that package**,
whatever its media type: USFM books, timing objects and any other registered object. For each one,
the stored bytes and the origin bytes must both hash to the registered sha256 and both must match
the registered size. USFM parsing and duplicate-book-code checks are separate concerns and never
substitute for this per-object inventory check, so a mutated timing file cannot hide behind a
USFM-only inventory. Counts and inventories are compared as integer sizes.

Count meanings, used identically on memory and PostgreSQL: `common_groups` is every Stage 4
group (structural and partial-coverage candidate groups) produced by one canonical alignment
run over the full pair; `unmatched_source` and `unmatched_target` are ALL-UNIT unmatched
entries of that run's report, i.e. verse locators without a counterpart plus every non-verse
unit (headings, titles, notes, XXF front matter) reported with a fixed reason;
`book_inventory` maps each declared book to `[source verse pieces, target verse pieces]`,
zero-retaining for verse-free editions such as XXF. Do not reuse the single-package 5,594
verse count or the mzr marker counts as paired alignment counts.

Expected group counts are derived by an independent test-only rescan oracle that expands
numeric bridges and filters verse-only locators, never by `CanonicalLocatorAligner`, so the test
cannot inherit the aligner's answer. The native token stage runs the **full eligible batch** —
every `structural` (or `approved`) group of the Stage 4 run whose two token sides are nonempty,
exactly as `TokenAlignmentService` selects them; the report's backend entry records the pinned
upstream version, archive digest, options and the absence of seed support. The test mock never
satisfies this stage, and a full native local batch with recorded options and runtime is a
completion gate reviewed separately.

Two integrity guarantees are checked on the real pair, not only on synthetic data:

- **No surface or path leaks.** The single focused leak helper searches the actual evidence —
  the setup-phase and call-phase captured log records *and* both serialized alignment reports
  (Stage 4 and Stage 5) — for forbidden surfaces and for every book-path form of both packages
  (full origin path, relative path and basename for every package object, timing objects
  included). Surfaces are sampled independently per side and bounded per side, so a large mzr
  edition cannot push the por side out of the sample, and non-verse units (headings, notes,
  front matter) are sampled alongside verses. A leak fails with a content-free diagnostic that
  names the forbidden category and never renders the restricted value.
- **Safe diagnostics interpolate nothing untrusted.** Every safe-marked diagnostic is built from
  fixed prose, internal pipeline ids, narrative counts or *numeric entry positions* — never from
  an arbitrary metadata key. A distinctive book code injected into `book_inventory` is therefore
  absent from the exception text, from the captured realdata output and from the serialized JUnit
  report; regressions run the actual gate in-process and in a realdata pytest subprocess.
- **Pair compatibility precedes any pipeline work.** One test-local function,
  `_pair_compatibility`, is the only place the pair is validated, and both entry points — the
  memory corpus fixture and the separate PostgreSQL test — call it before registering,
  ingesting, extracting, tokenizing or aligning anything. It requires two distinct declared
  languages and the same non-placeholder `versification_id` on both sides; a missing or
  mismatched declaration fails closed and is proven by compiler-free tests in which a
  `_build_flow` sentinel would fail if reached.

### Explicit uncertainties

- **Portuguese edition availability is unverified.** This document names operating steps, not a
  reviewed Portuguese edition. No Portuguese package was supplied or acquired while writing it,
  and no Portuguese total, book list or edition identifier is stated here.
- **Versification compatibility is unverified.** Both packages must declare the same
  `versification_id`; whether the operator's mzr and por editions actually use the same
  versification is an operator judgment that this profile does not pre-approve.
- **No target-language gold annotation set exists.** Coverage of the paired corpus is structural
  and integrity evidence only — group counts, matched/unmatched coordinates, lineage, report
  shape, redaction and persistence. It makes **no** word-alignment accuracy claim and no
  translation-quality claim: precision, recall, F1 and AER remain unavailable until an
  independently governed gold annotation set exists.
- Suffix-level interpretation of Marúbo clitics remains M5 ownership; coordinate alignment here
  never asserts morphological analysis.

## Open items before production morphology validation

- verify preferred orthography/variants;
- verify character inventory;
- define tokenizer behavior around punctuation/clitics;
- verify typological assumptions from primary descriptions;
- optionally record register reviewers (labels are descriptive; not a gate);
- identify initial gold IGT set;
- define local feature namespace;
- build initial segment-alignment review set;
- determine which sources may leave community infrastructure.
