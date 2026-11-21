# WP4.11 — Golden Fixture M4: Architectural Specification

> **Superseded policy note (ADR-0025).** Any rule below that blocks processing or
> training because of a source's classification, licence, rights holder, or register is
> historical. Presence in the repository authorizes processing and training; licences
> and ownership are records, not gates.

**Status:** Decided by chief architect under delegated authority (2026-10-16).
**Depends:** WP4.10. **Gate:** 27.
**Governing records:** ADR-0007 (policy matrix), ADR-0013 (lexical model, review authority),
ADR-0014 (stale dependents), ADR-0015 (computed revocation impact), ADR-0016 (CLDF).

This spec settles how WP4.11 works. It widens the M4-PLAN "Own" list in one place (§8). No
persisted format changes, so no ADR or migration is needed.

---

## 0. Decisions at a glance

| # | Question | Decision |
|---|---|---|
| G1 | Sources in M4 | `01-parallel-distill` (alignment path) and `03-wordlist` (wordlist path), both **unchanged**, plus one new synthetic export source `golden-lexicon-export` under `tests/golden/fixture/lexicon/` (§1.1). The M3 null-token source is **not** used. |
| G2 | Alignments | Reuse the M3 builders (`_parallel_flow`, `_stage4`, `_groups`, `_align`) by importing these underscore helpers from `tests.golden.test_golden_m3`. Leading-underscore names are not collected as tests. Use an **M4-specific mock matrix** of linguistically sensible links, built by surface lookup and never by hard-coded indices (§2.2). |
| G3 | Reviewer authority | Build an explicit in-test `ReviewAuthorityRegistry`. **Never** mutate `LANGUAGE_PROFILES`. `ReviewService` gets `clock=ctx.clock`, `new_id=ctx.new_id`, `code_revision="golden-m4"` (§3). |
| G4 | CLDF in the flow | Two exports, one before and one after revoking 01. Only the synthetic export source can ever produce a row, because `redistribute_derived` is default-deny in **every** policy mode (§1.2). |
| G5 | P12 proof | Two parts: **P12a** revokes 01 and checks that eligibility is lost while no stored row changes. **P12b** revokes the export source and checks that the export it already produced becomes ineligible (§4.5). |
| G6 | Snapshots | Nine JSON files under `expected/m4/`. Labels are semantic, never ordinal-by-ULID. No timestamps. The normalizer **fails** if any ULID is left unlabeled (§5). |
| G7 | Update flow | Same as M1–M3: `LANGPIPE_UPDATE_GOLDEN=1` writes the files, then calls `pytest.fail(UPDATE_MESSAGE)` (§5.4). |
| G8 | Backend parity | The `ctx` fixture already runs on both memory and PostgreSQL. One shared set of expected files is the parity check. Never sort by raw id (§6.3). |

---

## 1. Facts from the code that shape the design

These come from reading the code, not from the plan text. The design depends on them.

1. **`REDISTRIBUTE_DERIVED` is `DEFAULT_DENY` in every mode, including `direct`**
   (`governance/policy.py`, `_ROWS`). The 03 manifest has no `allow` list. The 01 allow list
   is `[align, distill_lexicon, distill_morphology]`. So **neither golden source can ever
   export a CLDF row**. Without a third source, the golden test could only watch
   `NoEligibleRecords` fire before and after revocation, which proves nothing about
   revocation.
2. **`HUMAN_REVIEW` is `ALLOW` for `direct` and `distill_only`.** Review decisions on
   senses derived from 01 or 03 are allowed.
3. **03 cannot enter M2** (it is ragged on purpose; `test_golden_m2_wordlist_03_is_malformed`).
   Its only path is `WordlistExtractor.extract` → `LexicalService.induce_lexicon(extract_run)`.
4. **Wordlist mode pins no `Form`s**, so `lemma_form_id` is `None` for 03 lexemes. That means
   **03 lexemes have no lineage to 01** even though `qaa/default_text@0.1.0/mabi` exists from
   01's tokenization. Revoking 01 must therefore not reach any 03 object. This is asserted
   (§4.5, I6) so a future form-pinning change cannot silently create cross-source lineage.
5. **The domain tag sits on `Sense`, not on `Lexeme`.** The wordlist adapter sets
   `Sense.domain` from the note `domain-specific (ritual/traditional)`, and the evidence item
   carries the same `domain`.
6. **Revocation has no service.** It is `repo.set_source_status(id, REVOKED, clock())` inside
   a transaction, the same as the `_revoke` helper in `tests/service/test_lexical_revocation_impact.py`.
   Revocation impact is *computed* (ADR-0015); no downstream row is mutated.
7. **A repeated CLDF export with an unchanged selection is reused.** `selection_digest` pins
   only the `(id, status)` pairs of exported rows plus attribution. Revoking 01 does not change
   the exported selection, because 01 rows were never in it. So the post-revocation export is
   `reused=True`, and `_reuse` reads the **stored** report, so its `omitted` counts are the
   pre-revocation ones. The test MUST NOT treat reused `omitted` counts as current omission
   reasons (§4.5). The implementer must confirm whether `CLDFExportResult.omitted` on reuse is
   stale. If it is, file a `tsk` item for WP4.12 and do not fix it inside WP4.11.

### 1.1 New synthetic export source (scope widening, precedent: M3 `fixture/alignment/`)

`tests/golden/fixture/lexicon/export-manifest.yaml`:

```yaml
manifest_version: 1
key: golden-lexicon-export
title: Synthetic redistributable wordlist (export challenge)
source_type: wordlist
languages: [qaa, por]
provenance:
  acquired_from: synthetic
acquired_at: "2026-01-01T00:00:00Z"
policy:
  mode: direct
  access_class: public
  authority: synthetic fixture steward
  allow: [redistribute_derived]
objects:
  - path: export-wordlist.tsv
    media_type: text/tab-separated-values
```

`tests/golden/fixture/lexicon/export-wordlist.tsv`:

```
qaa	por	note
nawa	rio
```

- `nawa` is chosen because the M4 mock matrix never links it (§2.2). The only `nawa` lexeme in
  the world is therefore this one, and the expected export content is exactly `{nawa, rio}`.
- If the exporter's attribution rule (WP4.10 D10) refuses this policy, add the smallest
  `restrictions.attribution` block that `tests/service/test_cldf_governance.py::_register_dataset`
  uses. Do not change anything else.
- The file sits outside `fixture/sources/`, so the M1 `rglob` over `FIXTURE_SOURCES` and the M1/M2
  snapshots are unaffected. Confirm this by running M1 and M2 unchanged.

### 1.2 What G4/G5 mean for "CLDF export becomes ineligible"

01 is `distill_only` with no `redistribute_derived` grant, so no export can ever depend on it.
"Revoking 01 makes the export ineligible" therefore has two honest forms, and the golden test
proves both:

- **P12a:** every export *candidate* derived from 01 moves from `denied` to `revoked` at the
  eligibility layer, while its lifecycle status and rows stay exactly as they were.
- **P12b:** revoking a source that an export **did** depend on makes the export's own artifacts
  ineligible, and re-exporting fails closed.

---

## 2. Pipeline execution flow (`test_golden_m4.py`)

### 2.1 One builder, fixed order

Write one `_build_m4_world(ctx, tmp_path, *, until: Stage) -> _M4World`. Each test calls it
with the latest stage it needs. Every test gets a fresh `ctx`, so worlds are never shared. The
order below is part of the contract: snapshot labels and review-task order depend on it.

| Step | Action | API |
|---|---|---|
| S1 | 01 register → ingest → extract (`tsv_sentences@0.1.0`) → normalize → tokenize | `test_golden_m3._parallel_flow(ctx)` |
| S2 | Stage 4 segment alignment + Stage 5 `mock@0.1.0` with the **M4 matrix** | `test_golden_m3._align(ctx, flow, _m4_links(ctx, flow))` |
| S3 | Stage 6 alignment induction | `LexicalService(ctx).induce_lexicon(token_run_id, method="alignment_cooccurrence@0.1.0", target_language="qaa", contact_language="por")` |
| S4 | 03 wordlist extraction, then Stage 6 | `WordlistExtractor(ctx).extract("03-wordlist")` → `induce_lexicon(extract.run.id, method="wordlist_tabular@0.1.0")` |
| S5 | Export source: register, then the same as S4 | `register_source(ctx, LEXICON_DIR/"export-manifest.yaml")` → as S4 |
| S6 | Review tasks T1–T8 and their decisions (§3.2) | `ReviewService` |
| S7 | Pre-revocation export | `CLDFExporter(ctx).export(language="qaa", output_dir=tmp_path/"cldf-pre")` |
| S8 | Revoke 01 | `with repo.transaction(): repo.set_source_status(src01, REVOKED, ctx.clock())` |
| S9 | Impact | `revocation_impact(repo, src01)` |
| S10 | Post-revocation export | `export(language="qaa", output_dir=tmp_path/"cldf-post")` |

`_M4World` exposes the source ids, the flow, every run result, a `lex(source_key, headword)` and
`sense(source_key, headword, gloss)` lookup, task and decision ids by `T<n>`, both export results,
and the impact. Look headwords up through the `headword` claims of each lexeme's supporting
evidence items (wordlist path), or through the `primary_lemma` `FormLexemeLink` → `Form.text`
(alignment path). Never look them up by id order.

### 2.2 The M4 mock matrix

The M3 matrix links token 0 to token 0, which yields meaningless senses such as `kanu → O`.
M4 pins a surface dictionary instead and turns it into index pairs per segment group:

```python
_M4_LINKS = {"kanu": "homem", "mabi": "canoa", "rumi": "pajé"}
```

- For each group, find the source token whose `raw_surface` is a key and the target token whose
  surface equals the value. Emit the pair in **both** forward and reverse direction (symmetrized).
- Expected links: TXT.1.1 `kanu→homem` and `mabi→canoa`; TXT.1.3 `kanu→homem`; TXT.1.4 `rumi→pajé`.
  TXT.1.4 is the 1:2 group, and `pajé` lies in the first `por` member.
- `mabi-ki` and `wesa-ra` are **never** linked. Whole-token forms with suffix-like material
  belong to M5, and linking them would create spurious lexemes.
- The target index MUST use the same token ordering that `MockTokenAligner` uses across
  multi-member groups. Read `tests/fixtures/alignment.py` and compute indices from it. Add a
  guard: `assert` that every key in `_M4_LINKS` produced at least one pair, so a tokenizer
  change cannot pass by silently emitting no links.

Expected S3 output: three 01 lexemes (`kanu`, `mabi`, `rumi`), each with exactly one sense
(`homem`, `canoa`, `pajé`). `kanu` carries two observations.

---

## 3. Review configuration

### 3.1 Authority registry (in-test, explicit)

```python
ROLE = "golden_lexicographer"
registry = ReviewAuthorityRegistry()
registry.register("golden-reviewer", ROLE, ["qaa"])                      # all domains
registry.register("golden-fauna-only", ROLE, ["qaa"], domains=["fauna"])  # P9 negative
service = ReviewService(ctx.repo, registry, clock=ctx.clock, new_id=ctx.new_id,
                        code_revision="golden-m4")
```

The reviewer ids are synthetic. This complies with DELEGATED-DECISIONS §2: no real data gets
`validated` status.

### 3.2 Tasks and decisions, in this order

Every task is `ReviewTaskType.LEXICAL_SENSE`, uses `required_role=ROLE`, and keeps the default
priority factors. Pass `evidence_item_ids` equal to the target's supporting evidence, in sorted order.

| Task | Target | Decision | Purpose |
|---|---|---|---|
| T1 | 03 `mabi` / `canoa` sense | accept | P10 |
| T2 | 03 `mabi` / `tronco` sense | reject | P11 |
| T3 | 03 `mabi` lexeme | accept | a validated object that is still not exportable (shows that `denied` is separate from lifecycle status) |
| T4 | export-source `nawa` lexeme | accept | positive export row |
| T5 | export-source `nawa` / `rio` sense | accept | positive export row |
| T6 | 01 `rumi` lexeme | accept | revocation hits a *validated* object (`validated_affected`) |
| T7 | 01 `rumi` / `pajé` sense | accept | same |
| T8 | 03 `rumi` / `pajé` sense | none (left open) | P9 negative: `golden-fauna-only` is refused |

If `effective_decision(rumi_01_sense, HUMAN_REVIEW)` turns out not to be `ALLOW`, because the
01 allow list is exclusive, do not change the 01 policy. Drop T6 and T7, assert the
`PolicyDenied` instead, and record the fact in the test docstring. P12a then uses supported or
candidate 01 objects through eligibility only.

---

## 4. Phenomenon assertions

Each phenomenon has its own named test function, and every assertion below is mandatory. Status
checks read back from the repository; never trust the returned object alone.

### 4.1 P2: `mabi` has two candidate senses (`test_p2_mabi_one_lexeme_two_senses`, `until=S5`)

- Within the 03 induction run, exactly **one** lexeme has headword `mabi`.
- `list_senses_for_lexeme(mabi03)` returns exactly two senses, with glosses `{"por": ["canoa"]}` and
  `{"por": ["tronco"]}`. Both have `lexeme_id == mabi03`.
- Each sense has a `derived_from` edge to `mabi03`, to the 03 Stage 6 run, and to **its own** gloss
  evidence item. The two senses share no evidence item.
- Neither sense is `validated`, and both are in {`candidate`, `supported`}. The snapshot pins which.
- Cross-source separation: the 01 `mabi` lexeme is a **different** id with exactly one sense
  (`canoa`). M4 merges nothing across sources.
- `FormLexemeLink`: the 03 lexeme has none (fact 4). The 01 lexeme has exactly one `primary_lemma`
  link to `qaa/default_text@0.1.0/mabi`.

### 4.2 P9: `rumi` keeps its domain (`test_p9_rumi_domain_preserved`, `until=S6`)

- 03 `rumi` sense: `domain == "ritual/traditional"`, glosses `{"por": ["pajé"]}`, and its gloss
  evidence item has the same `domain`.
- 03 `rumi` lexeme: `domain is None` (the adapter does not copy the tag up to the lexeme). Pin
  this so any future change is deliberate.
- 01 `rumi` sense: `domain != "ritual/traditional"`. The tag must not leak across sources. The
  source-level `domains: [religious]` is source metadata, not a sense tag. The snapshot pins the
  actual value.
- The tag carries weight in review: `record_decision(T8, accept, "golden-fauna-only", ROLE)` raises
  `UnauthorizedReviewer`. Afterwards T8 is still `open`, the sense status is unchanged, the
  decision count is unchanged, and `state_counts(ctx)` is identical before and after.

### 4.3 P10: accept → `validated` (`test_p10_review_accept_validates`, `until=S6`)

- T1 returns a `ReviewDecisionResult`. The persisted `ReviewDecision` has `task_id=T1`,
  `target_id=canoa03`, `decision=accept`, `reviewer_id="golden-reviewer"`,
  `reviewer_role=ROLE`, and `superseding_object_id=None`.
- `repo.get_sense(canoa03).status is VALIDATED`, and T1's task status is resolved.
- The decision is immutable. Assigning to an attribute of the model raises (the model is frozen).
  A second `record_decision(T1, …)` raises `InvalidTransition`, and the decision count for T1
  stays 1.
- Side effects are contained. Before T3, the sibling `tronco03` and the lexeme `mabi03` keep their
  pre-review status. After T3, `stale_dependent` edges from `mabi03`'s senses exist (ADR-0014).
- The `lexical-v1` score breakdown was recomputed, not erased (snapshot field).
- Machine paths never validate: before S6, no lexeme or sense in the world is `validated`, and
  each induction's `status_counts` has no `validated` key.

### 4.4 P11: reject → `rejected` (`test_p11_review_reject_rejects`, `until=S6`)

- T2's decision has `decision=reject`, and `get_sense(tronco03).status is REJECTED`.
- The rejected sense **still exists**, with its glosses and evidence unchanged. Nothing is deleted.
- The sibling `canoa03` stays `VALIDATED`.
- Rejected is not terminal like `deprecated`. Pin only that the T2 task is resolved and that a
  new decision on it is refused.

### 4.5 P12: revocation (`test_p12a_revoke_01_*` with `until=S10`, `test_p12b_revoke_export_source`)

**P12a: revoke 01**

1. **Pre-revocation export (S7):** `reused is False`, and exported entries equal exactly
   `{nawa_export}` with senses `{rio_export}`. `omitted["denied"] >= 2`: the 03 `mabi` lexeme (T3)
   and the 01 `rumi` lexeme (T6) are validated but have no `redistribute_derived` grant.
   `omitted["revoked"] == 0`.
2. **Impact (S9):** `impact.revoked is True`.
   - `set(impact.lexemes) == {kanu01, mabi01, rumi01}`.
   - `set(impact.senses) == {homem01, canoa01, pajé01}`.
   - `set(impact.validated_affected) == {rumi01, pajé01}`.
   - `impact.review_tasks ⊇ {T6, T7}` and `impact.review_decisions ⊇ {dec T6, dec T7}`.
   - The impact contains **no** 03 or export-source object and no CLDF export artifact (fact 4,
     §1.2). Assert that the intersection with the ids of each of those runs is empty.
3. **Eligibility flips; rows do not.** For every lexeme and sense in the impact:
   - `revoked_ancestor_ids(repo, x) == [src01]`;
   - `lineage_eligibility(x, REDISTRIBUTE_DERIVED) is DENY`;
   - `lineage_eligibility(x, HUMAN_REVIEW) is DENY`;
   - the persisted status equals the status before S8. In particular `rumi01` and `pajé01` are
     **still `VALIDATED`** (ADR-0015: computed, not materialized).
4. **Bystanders are unaffected.** Every 03 and export-source lexeme and sense keeps its status,
   and its `lineage_eligibility` for `REDISTRIBUTE_DERIVED` and `HUMAN_REVIEW` matches the
   pre-S8 value.
5. **Post-revocation export (S10):** `reused is True` (fact 7). The exported entries are the
   same as in S7, and the bytes are identical to `cldf-pre`. No 01-derived id appears in any
   written file. Do not assert on `omitted` here; assert the omission reason through item 3.
6. **New work fails closed.** `induce_lexicon(token_run_id_01, …)` raises `PolicyDenied`, adds
   exactly one `POLICY_DENIED` audit event, and adds no run. A new `create_task` +
   `record_decision` on `canoa01` raises and writes nothing.

**P12b: revoke the export source** (own test, `until=S7`)

- After S7, revoke `golden-lexicon-export`. `revocation_impact` must contain the S7 export run's
  `CLDF_EXPORT` file artifacts and its `cldf-export-report`.
- `lineage_eligibility(artifact, REDISTRIBUTE_DERIVED) is DENY` for each of those artifacts.
- `export(language="qaa", output_dir=tmp/"cldf-after")` raises `NoEligibleRecords`. It adds no
  run and no artifact, does not create `cldf-after`, and adds one `POLICY_DENIED` audit event
  per denying source with `details["operation"] == "redistribute_derived"`. The `cldf-pre`
  bytes on disk are not touched.

---

## 5. Snapshot normalization (`tests/golden/normalize_m4.py`)

### 5.1 Entry point

```python
def normalize_m4_snapshot(ctx: AppContext, world: _M4World) -> dict[str, Any]
```

The function is pure: it reads only persisted state plus the two export output directories.
The snapshot is taken at the end of S10 so that it records post-review and post-revocation state.
Pre-revocation eligibility is captured in the builder at S7 and passed in.

### 5.2 Files in `tests/golden/expected/m4/`

| File | Content |
|---|---|
| `runs.json` | Every run from S3 onward plus the review-creator runs: label, stage, tool, method, status, labels of sorted inputs and outputs. Config hashes are masked. |
| `lexemes.json` | Keyed by label: language, status, domain, register, lemma form key or `null`, run label, source label, headword. |
| `senses.json` | Keyed by label: lexeme label, glosses, domain, register, status, `lexical-v1` breakdown (floats rounded to 6 places). |
| `evidence.json` | Per target label: list of kind, polarity, strength, independence-group label, claim, domain. |
| `review.json` | `tasks` (label, type, target, required role, priority rounded to 6 places, status, reason, evidence labels) and `decisions` (label, task, target, kind, reviewer id, role, superseding label, notes). Also the T8 refusal: no row, so it appears only as T8 `status: open`. |
| `lineage.json` | Every edge with at least one endpoint among the M4 objects: `[from, to, kind]`, sorted lexicographically by label. This includes `stale_dependent` edges. |
| `export.json` | `pre` and `post`: reused flag, exported/omitted counts, file names, and parsed CSV rows with ids replaced by labels. Also `p12b` (denial details). |
| `revocation.json` | `impact.to_dict()` normalized: counts per entity type, labeled id lists, `validated_affected`, and an eligibility table `{label: {op: [pre, post]}}` for `REDISTRIBUTE_DERIVED`, `HUMAN_REVIEW`, `DISTILL_LEXICON`. |
| `reports.json` | An allowlist of payload fields from the `wordlist-extraction-report`, `lexical-induction-report` and `cldf-export-report` artifacts (ids labeled, counts kept). |

`audit.json` is deliberately left out. The `POLICY_DENIED` checks are exact assertions in §4.5,
which is stronger than a snapshot.

### 5.3 Labeling and masking rules

1. **Semantic labels.** Upstream objects use the same naming as M1–M3, so a reader can
   cross-reference them:
   - sources: `src:<key>`;
   - forms: their form key, e.g. `qaa/default_text@0.1.0/mabi`;
   - segments: `seg:01:<lang>:<ref>[:<sentence_part>]`;
   - tokens: `tok:01:<lang>:<ref>:<index>`;
   - alignment edges: `edge:01:<ref>:<src_idx>-><tgt_idx>`.

   M4 objects:
   - `lex:<source-key>:<headword>` and `sense:<source-key>:<headword>:<gloss>`;
   - `link:<lexeme label>`;
   - `ev:<target label>:<n>`, where `n` is the index after sorting by `(kind, canonical_json(claim), observation label)`;
   - `task:T<n>` and `dec:T<n>`;
   - runs: `run:<stage>:<source-key>`, `run:export:pre`, `run:review:T<n>`;
   - artifacts: `artifact:<run label>:<schema_name or file name>`.
2. **Fail on leftovers.** After labeling, walk the whole snapshot. Any string matching
   `^[a-z]+_[0-9A-HJKMNP-TV-Z]{26}$` (the same `_ID` regex as M3) raises `AssertionError` naming
   its key path. An unlabeled id means a missing label rule, never something to mask.
3. **No timestamps** anywhere. The stepping clock is deterministic, but timestamps add no
   meaning. Order is expressed through labels (T1…T8, S-steps).
4. **Hashes:** keep the raw-object sha256 of committed fixture bytes (deterministic and
   meaningful, as in M1). Replace config, selection and artifact digests with `"<sha256>"`.
   Byte determinism of the CLDF export is asserted directly (`pre` bytes == `post` bytes), not
   snapshotted.
5. **Floats** are rounded to 6 decimal places. **Lists** are sorted by label, or by an explicit
   semantic key, never by raw id or insertion order.
6. **Content:** headwords, glosses and claims are recorded verbatim. All of it is synthetic
   fixture content already present in `expected/m2/forms.json`. Report payloads use the
   allowlist only.

### 5.4 Update convention (same as M1–M3)

```python
if os.environ.get(UPDATE_ENV) == "1":
    _write_expected(snapshot)          # json.dumps(indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    pytest.fail(UPDATE_MESSAGE)
for name, value in snapshot.items():
    assert value == json.loads((EXPECTED / f"{name}.json").read_text("utf-8")), name
```

Also assert that `set(snapshot) == {p.stem for p in EXPECTED.glob("*.json")}`, so a stale or
missing file fails. Regenerate with
`LANGPIPE_UPDATE_GOLDEN=1 uv run pytest tests/golden/test_golden_m4.py::test_golden_m4_snapshot`.
The update run is parametrized over both backends and writes twice. The **normal** run on both
backends that follows is the parity gate. Review the result with `git diff tests/golden/expected/m4`.

---

## 6. Invariants and acceptance

### 6.1 Invariant tests (each a named function)

| # | Test | Assertion |
|---|---|---|
| I1 | `test_observations_immutable_under_lexical_status_changes` | Fingerprint `model_dump(mode="json")` of every `Segment`, `TokenOccurrence`, `Form`, `SegmentAlignment`, `TokenAlignmentEdge`, `SourceObject` and `EvidenceItem`, plus the raw-store sha256 of each object, keyed by label. The fingerprint after S5 equals the one after S10. Review decisions, revocation and export change none of them. |
| I2 | `test_rerun_is_idempotent` | Build the world to S5, snapshot `state_counts` and `count_runs`, rerun S3–S5. Every induction and extraction returns `reused=True`, and the counts are identical. |
| I3 | `test_lineage_ancestry_is_exact` | `ancestor_source_ids` is `{src01}` for every 01 lexeme and sense, `{src03}` for 03 ones, and `{src:golden-lexicon-export}` for export ones and for the S7 export artifacts. Every lexeme and sense has `derived_from` to its Stage 6 run. |
| I4 | `test_distill_only_never_exported` | The set of all CSV cell strings in `cldf-pre` that are not ids, metadata or language codes is exactly `{"nawa", "rio"}`. No 01 segment text, no 01 token surface and no 03 headword or gloss appears in any exported byte. |
| I5 | `test_no_machine_validation` | After S5, the count of `validated` objects is 0. After S6, the `validated` set is exactly {canoa03, mabi03, nawa_export, rio_export, rumi01, pajé01}, all of them targets of an accept decision. |
| I6 | `test_wordlist_lexemes_have_no_alignment_ancestry` | No 03 lexeme or sense has `src01` among its ancestors (guards fact 4). |

### 6.2 Test inventory

`test_golden_m4_snapshot`, the P2/P9/P10/P11/P12a/P12b tests from §4, and I1–I6. Do not add
skip-marked placeholders (expected/README rule 3).

### 6.3 Backend parity

- Use only the `ctx` fixture, which is parametrized over memory and PostgreSQL. Do not build
  repositories directly.
- ULIDs created in the same millisecond have no meaningful order, so every lookup goes through
  semantic keys (§2.1) and every list is sorted by label (§5.3).
- PostgreSQL runs are sequential (M4-PLAN §3.8). No xdist in the golden suite.

### 6.4 Acceptance

```bash
LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest tests/golden -q        # M1–M4, both backends
uv run pytest tests/golden/test_golden_m1.py tests/golden/test_golden_m2.py -q   # unchanged by §1.1
uv run ruff check tests/golden && uv run ruff format --check tests/golden
uv run mypy tests/golden/normalize_m4.py tests/golden/test_golden_m4.py
scripts/ci.sh                                                     # zero skips
```

---

## 7. What is deliberately out of scope

- Cross-source lexeme merging, Concept minting, CLDF import in the golden flow (WP4.10 already
  covers import in service tests), and `modify`/`uncertain`/`defer` decisions.
- Any fix to stale reused `omitted` counts (fact 7). File it on `tsk` for WP4.12 if confirmed.
- A revocation service or CLI. The test uses the repository call that the WP4.9 tests use.

## 8. Scope widening (record in M4-PLAN when the WP lands)

WP4.11 additionally owns:

- `tests/golden/fixture/lexicon/export-manifest.yaml` and `export-wordlist.tsv` (§1.1);
- `tests/golden/expected/README.md`: add the `m4/` paragraph and remove the M4 and Post-M1
  revocation rows from "Pending";
- `tests/golden/fixture/PHENOMENA.md`: mark 2, 9 and 12 as checked in M4, and 10 and 11 as
  "M4 infrastructure checked on lexical senses; IGT targets remain M5".
