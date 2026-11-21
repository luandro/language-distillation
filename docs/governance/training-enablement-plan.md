# Training-enablement plan: process what is in the repo

**Status:** **Implemented** (owner decision, 2026-10-18; recorded as
[ADR-0025](../adr/0025-presence-based-source-authorization.md)). This version supersedes
the evidence-gated draft and records the policy reversal: licenses and ownership are no
longer authorization gates.
**Plan date:** 2026-10-18. **Scope:** every source under `var/external/` for Marúbo (`mzr`).

**Decision (owner, 2026-10-18):** *"This repo should ignore licenses, and ownership; we've set
gates that are blocking our work moving forward. If a source is added to the repo, it should
be processed."*

**Goal:** remove the rights gates, reprocess every source in the repo, re-export, and
retrain — without losing the technical line the repo actually needs (reproducibility,
revocation, no silent data loss).

---

## 1. The rule

| Condition | Effect |
|---|---|
| A source directory, file, or manifest exists under `var/external/` | **Authorized** for `ingest`, `read_raw`, `extract`, `normalize`, `align`, `distill_lexicon`, `distill_morphology`, `distill_grammar`, `evaluation`, `synthetic_generation_support`, `direct_training` |
| License, rights holder, publisher, register, community authority | **Recorded as metadata if known; never blocks.** Unknown is an acceptable value |
| Explicit `mode: exclude` set by the operator | Blocks processing (the only opt-out) |
| Raw bytes immutability, lineage, deterministic ids | **Kept.** They are traceability, not authorization |
| Revocation | **Kept** as an operational capability, not a default gate |

This is the operational form of "if a source is added to the repo, it should be processed."

## 1a. Implementation status (2026-10-18)

The rule is in force. What landed, and what was deliberately dropped:

| Originally planned | Outcome |
|---|---|
| ADR-0025 records the reversal; ADR-0007 matrix amended | **Landed** (`804ecc8`) |
| `distill_only` trains; only `exclude` blocks entirely | **Landed** (`804ecc8`) |
| Training gate is traceability-only; blocklist gone | **Landed** (`804ecc8`) |
| Manifests may omit `policy:`; default `direct`/`public`/`repo-owner` | **Landed** (`804ecc8`, `default_policy_spec()`) |
| Versioned policy documents with authored `policy_id`s (old WP1) | **Dropped.** ADR-0025 makes the policy a default, not an authored authorization; policy ids stay generated at registration for traceability |
| Persisted intake record + ADR-0023 fields (old WP2) | **Dropped.** Licences/ownership are optional records now; fields live in the registry and docs, not a new table |
| Authorized source register decision (old WP3) | **Dropped.** Register labels are metadata and never block; they can be written as manifest `registers` |
| Export carries `source_id`/`policy_id`/`run_id`; no silent drops | **Landed** (`5335e00`) |
| Registry, language index, audit docs updated; sources default to `direct` | **Landed** (this batch) |
| Register/ingest/extract the repo sources | **Landed**: every source present was registered and ingested (14 in the store at last check), 8 extracted (63,953 segments). Six have no segments: two TSV lexicons (no wired extractor), the Glottolog metadata JSON, and three sources added after the extraction pass |
| Regenerate dataset exports, retrain, evaluate | **Not done** by owner instruction: the dataset is being sorted first, and the training run is deferred |

Still open and tracked here: 24 synthetic phrases on disk carry no provenance field
(exported as `synthetic:curriculum` and reported as `rows_without_source_ids` until the generator
is re-run); the 105 Cesarino pairs still come from the loose harvested JSONL rather than a
governed IGT run; `schemas/dataset-manifest.v1.schema.json` does not exist yet; the
file-based HF/Alpaca/ChatML exporter does not consult `lineage_eligibility` or the
`exclude` list, so a revoked or excluded source's rows would not be dropped by that path
until it is wired to the store; it records one `source_id` per row, so a verse pair whose
two sides come from two sources keeps only one; `var/exports/source_index.json` is
operator-made rather than generated from the store; and harvested duplicates are dropped
      within a source but not across sources;de-duplicated across splits. These are the remaining gaps flagged by the Opus 5.5 review.

---

## 2. The gates that were removed

These are the things actually blocking work today, in dependency order.

| # | Gate | Location | Action |
|---|---|---|---|
| G1 | `distill_only` × `direct_training` is `hard_deny`; no `allow` can lift it | `src/langpipe/governance/policy.py:54`, `:83-84`, `:91-92` | Move to `allow`; `validate_policy_lists` stops rejecting it |
| G2 | Hard-coded provenance blocklist `("corpus:", "harvested:")` | `src/langpipe/training/eligibility.py:20` | Delete the list and the prefix check |
| G3 | Row with no `policy_id` is rejected | `src/langpipe/training/eligibility.py:28` | Keep `policy_id` as a traceability field, but **auto-fill it at export**; it never reflects a rights decision |
| G4 | License + rights holder + register intake required before training (ADR-0023) | `docs/adr/0023-source-intake-quality-criteria.md` | Downgrade to optional metadata; the validator no longer blocks |
| G5 | ADR-0024's pending hard-deny decision and the ADR-0022 scripture exclusion | `docs/adr/0022-…`, `docs/adr/0024-…` | Supersede / withdraw; training is no longer restricted by source identity |
| G6 | "Authority restrictions win when openness and community authority conflict" | `docs/GOVERNANCE.md:142-146` | Remove the authority-first clause |
| G7 | Invariant 6: "`distill_only` prose must never enter a trainable dataset" | `AGENTS.md`, `CLAUDE.md` | Rewrite as presence-based authorization |
| G8 | Default labels `mode: distill_only` + `access_class: highly_restricted` + `authority: "unassigned"` | `var/external/*/policy.yaml`, `docs/research/universal_sources_registry.json`, `docs/languages/mzr.md`, `docs/languages/mzr_sources_index.json` | Default to `mode: direct`, `access_class: public`, `authority: "repo-owner"` |
| G9 | Register decision required for Cesarino material | `docs/governance/authority-brief-cesarino-2017.md`, old WP3 | Convert to an optional label; no review authority is required to process or train |
| G10 | `evaluation` and `synthetic_generation_support` are default-deny under `distill_only` | `src/langpipe/governance/policy.py:53,55` | Move to `allow` under `distill_only` as well, so a leftover `distill_only` label cannot block |

`third_party_api` / `cloud_processing` are **not** in scope of this reversal: they are data
egress to third parties, not local processing. They stay opt-in and do not block anything in
this plan. If you also want those open, say so and it is a one-line matrix change (§8).

---

## 3. What stays, and why

| Kept | Reason | Effect on the work |
|---|---|---|
| Raw-source immutability (`var/raw`, `var/external`) | Invariant 1; you cannot re-derive what you mutated | none |
| `Source`/`SourceObject`/`ProcessingRun`/lineage ids | Invariant 4; needed for revocation and for reproducing a training set | none |
| `policy_id` on sources and rows | Traceability: which classification produced this row. It no longer authorizes | auto-filled by WP3/WP4, no operator action |
| Revocation path | If a community or publisher objects later, one `withdraw`/revoke flips eligibility and the next lineage-governed (CLDF) export drops the rows (ADR-0015); the file-based exporter does not consult it yet (§1a) | available, not mandatory |
| No-LLM-invention of target forms | Invariant 9; unrelated to ownership | none |
| Schema/migration discipline | Invariant 11 | WP costs, not gates |

Attribution and license strings, when known, are still worth recording — they cost nothing
and they are what you would need if the stance is ever reversed. They become plain metadata
fields with no enforcing code path.

---

## 4. Work packages (original plan — see §1a for what actually landed)

Order: **WP0 → WP2 → WP1 → WP3/WP4 → WP5 → WP6 → WP7**. WP0/WP2 can start immediately.
The unchecked boxes are the original plan; WP1's authored-policy, WP2 intake, and WP3
register-decision items were dropped per ADR-0025.

### WP0 — Record the reversal

**Files:** `docs/adr/0025-presence-based-source-authorization.md` (new),
`docs/adr/0007-source-policy-resolution.md` (amended matrix),
`docs/adr/0022-…` / `docs/adr/0024-…` (superseded),
`docs/adr/0023-…` (status → Superseded or Downgraded),
`docs/adr/README.md`, `docs/GOVERNANCE.md`, `AGENTS.md`, `CLAUDE.md`,
`docs/languages/mzr.md`.

- [ ] ADR-0025: states the owner decision, the presence rule, the matrix amendment, and
      explicitly records that this supersedes ADR-0022/0023/0024 as authorization gates.
      It must also say what it does **not** do (§7).
- [ ] Amend ADR-0007 §2/§6: `distill_only` × `direct_training` `H → A`,
      `distill_only` × `evaluation` `D → A`, `distill_only` × `synthetic_generation_support`
      `D → A`. `exclude` keeps its hard denies (operator opt-out). Add a note that no
      license/ownership evidence is part of policy resolution.
- [ ] Mark ADR-0022 and ADR-0024 `Superseded by ADR-0025`; mark ADR-0023 `Superseded`
      (its fields may survive as optional metadata in WP1).
- [ ] Rewrite `AGENTS.md` invariant 6 and the matching `CLAUDE.md` bullet:
      *"A source present in the repository is authorized for processing and training.
      Licenses and ownership are recorded as metadata, never as gates. Only an explicit
      `exclude` policy blocks processing."*
- [ ] Replace `docs/GOVERNANCE.md:9-19` mode table wording and delete the authority-first
      clause at `:142-146`; keep revocation and audit sections.
- [ ] Commit the untracked governance drafts first (ADR-0023/0024, license audit, manifest
      reconciliation, candidate-license research) or mark them superseded in ADR-0025 —
      otherwise the reversal edits unversioned files.
- [ ] **Acceptance:** ADR-0025 answers "what authorizes processing?" with one sentence, and
      no normative doc still says a license or owner blocks training. `uv run pytest
      tests/unit/governance` reflects the amended matrix.

### WP1 — Default to `direct`

**Files:** `src/langpipe/domain/models/source.py`, `src/langpipe/ingestion/registration.py`,
`src/langpipe/cli/source.py`, `var/external/*/policy.yaml`,
`docs/research/universal_sources_registry.json`, `docs/languages/mzr_sources_index.json`,
`tests/service/test_registration.py`.

- [ ] Make `SourceManifest.policy` optional. When omitted, registration builds
      `PolicySpec(mode=direct, access_class=public, authority="repo-owner", allow=[])`.
      Manifests that declare a policy keep working unchanged (golden fixtures, ScriptureEarth).
- [ ] Rewrite the local policy files — `var/external/{glottolog,marubo_sources,marubo_vocab,
      parallel_por}/policy.yaml` and `var/external/scriptureearth/mzr/policy.yaml` — to
      `mode: direct`, `access_class: public`, `authority: "repo-owner"`, `allow: []`;
      delete the `highly_restricted`/`unassigned` defaults.
- [ ] Registry: default `policy: direct`; keep `license`/`license_url`/`checked_at` as
      informational fields; add the two missing sources (Costa 2002, Cesarino 2013); fix the
      Costa 2017 `local_path`; split `access_category` from `policy`.
- [ ] `mzr_sources_index.json`: the old `policy_scope` field was replaced by a `policy:
      direct` + `capabilities` pair; there is no third permission vocabulary left.
- [ ] Tests: manifest with no `policy` gets `direct`; explicit `exclude` still blocks;
      explicit `distill_only` now allows training.
- [ ] **Acceptance:** adding a folder + manifest and running `langpipe source add` yields a
      `direct` policy with no license/authority input.

### WP2 — Remove the hard deny from the matrix

**Files:** `src/langpipe/governance/policy.py`,
`tests/unit/governance/test_policy_matrix.py`,
`tests/unit/governance/test_policy_properties.py`,
`tests/service/test_text_governance.py`, `tests/service/test_alignment_governance.py`,
`docs/adr/0007-source-policy-resolution.md`.

- [ ] Edit `_ROWS` per WP0: `DIRECT_TRAINING`, `EVALUATION`,
      `SYNTHETIC_GENERATION_SUPPORT` for `distill_only` become `_A`.
- [ ] Update the copied `ADR_0007_MATRIX` in `test_policy_matrix.py` **in the same commit as
      the ADR edit** (the test's comment demands the ADR is the source of truth). The
      `test_distill_only_direct_training_is_hard_denied` and
      `test_explicit_allow_cannot_lift_hard_deny` tests are replaced by their inverses.
- [ ] Keep the property tests: "adding a deny never increases permission" and "adding a
      policy never increases permission" still hold.
- [ ] **Acceptance:** `baseline(DISTILL_ONLY, DIRECT_TRAINING) is ALLOW`;
      `resolve(_P(DISTILL_ONLY), DIRECT_TRAINING) is ALLOW`; `exclude` still denies.

### WP3 — Make the training gate traceability-only

**Files:** `src/langpipe/training/eligibility.py`, `scripts/train_nllb_lora.py`,
`tests/unit/test_training_eligibility.py`.

- [ ] Delete `REJECTED_PROVENANCE_PREFIXES` and the `provenance` check. The docstring's
      "only a recorded policy change may remove an entry" rule is satisfied by ADR-0025 —
      cite it in the commit.
- [ ] The gate keeps exactly one requirement: the row carries a trace id (`source_id`,
      `policy_id`, or `provenance`; auto-written by WP4). It never consults mode, license,
      register, or source identity. A row that fails is a malformed export, not a governance
      denial.
- [ ] `scripts/train_nllb_lora.py`: delete the `harvested`/`corpus` rejection messaging;
      dry-run reports eligible/malformed counts only.
- [ ] Tests: `corpus:` and `harvested:` rows pass; a row with ids passes; a row without ids
      fails; a `distill_only` policy id passes.
- [ ] **Acceptance:** `filter_eligible` returns every row that has lineage ids, and no row
      is rejected because of where it came from.

### WP4 — Row lineage, and stop dropping rows silently

**Files:** `src/langpipe/synthesis/export_dataset.py`,
`src/langpipe/domain/models/dataset.py` (new: `DatasetRow`, `DatasetManifest`),
`schemas/dataset-manifest.v1.schema.json`, `tests/unit/test_synthesis_batch_and_export.py`,
`exports/mzr/datasets/manifest.json` (regenerated).

- [ ] Write `source_id`, `policy_id`, `run_id`, `provenance` into every record in all three
      formats (HF, Alpaca, ChatML). Auto-fill `policy_id` per provenance from the source
      registry; the value is a traceability id, not an authorization.
- [ ] Fix the defect in `docs/governance/manifest-reconciliation.md`: `_extract_pair` must
      read `target_phrase`/`portuguese_translation` for synthetic rows, and each writer must
      assert `written == len(pool)` and raise otherwise.
- [ ] Manifest records per-split counts, the source/policy id set, and checksums; no
      hand-editing.
- [ ] Tests: all 4,725 train rows are written after the synthetic fix; a malformed row still
      raises; every record carries the ids; manifest counts equal file rows.
- [ ] **Acceptance:** `manifest.json` `train_count` equals `wc -l train.hf.jsonl`, and every
      line has `source_id` + `policy_id` + `run_id`.

### WP5 — Process every source in the repo

**Files:** `var/external/<source>/langpipe-manifest.yaml` (local),
`src/langpipe/harvest/extractors/igt_parser.py`,
`src/langpipe/ingest/governed.py`, `exports/harvested_parallel/`.

- [ ] Create a manifest for each of the seven sources (Costa 1992, 2000, 2002, 2017;
      Cesarino 2013; Cesarino & Marúbo 2017; Glottolog) with `objects` and no `policy:`
      block (WP1 default) — or with an explicit `direct` block if the operator prefers it.
- [ ] `langpipe source add` → `source ingest` → `source verify` → `extract` → `normalize`
      for all seven. Glottolog has no running text; it is registered and ingested like the
      rest and simply yields no parallel pairs.
- [ ] Re-create the 105 Cesarino & Marúbo 2017 IGT pairs through a governed run
      (`IgtObservationParser(source_id, run_id, source_object_id)`) so they carry lineage,
      and stop reading the ungoverned `exports/harvested_parallel/*.jsonl`.
- [ ] **Acceptance:** `langpipe source show` for each source; every trainable row resolves
      to a `source_object_id` + `run_id`.

### WP6 — Re-export, retrain, evaluate

**Files:** `exports/mzr/datasets/*` (regenerated), `exports/mzr/MODEL_CARD.md`,
`notebooks/Marubo_NLLB_600M_Finetune.ipynb`, `scripts/train_nllb_lora.py`,
`src/langpipe/training/nllb_eval.py`.

- [ ] Regenerate the nine splits + manifest. Expect the full attested set plus the 105
      harvested rows and the now-included synthetic rows.
- [ ] `python scripts/train_nllb_lora.py --dry-run` passes; run the real training.
- [ ] Evaluate with `exports/mzr/probes/pt_prompts_v1.jsonl`
      (`src/langpipe/training/nllb_eval.py`, added in `86e076a`) plus chrF/BLEU on held-out
      attested rows; record before/after.
- [ ] `MODEL_CARD.md`: list the processed sources and the policy ids. State the base-model
      license fact (§7).
- [ ] **Acceptance:** the manifest, the model card, and the policy ids agree; dry-run
      eligible count equals the manifest train count.

### WP7 — Registry, docs, tests

**Files:** `docs/research/universal_sources_registry.json`,
`docs/languages/mzr_sources_index.json`, `docs/governance/source-license-audit.md`,
`docs/languages/mzr.md`, `docs/adr/README.md`, `docs/GOVERNANCE.md`,
`src/langpipe/governance/intake.py` (if it lands, it is non-blocking).

- [ ] Mark the license audit as historical/informational, not a gate.
- [ ] `docs/languages/mzr.md`: remove the "religious corpus default" `distill_only` block and
      the authority-first register language; point to ADR-0025.
- [ ] Add the ADR-0020–0025 rows to `docs/adr/README.md`.
- [ ] Guard test: nothing outside `governance/` may reintroduce a license/authority check
      into eligibility. A simple `tests/unit/test_policy_guard.py` scanning
      `src/langpipe/training/` for `license`/`authority`/`rights` imports is enough.
- [ ] **Acceptance:** `uv run pytest tests/unit/governance tests/unit/test_training_eligibility.py
      tests/unit/test_synthesis_batch_and_export.py -q`; `uv run ruff check .`;
      `uv run mypy src/`.

---

## 5. What happens to each source

| Source | Process | Train | Notes |
|---|---|---|---|
| Costa 1992, 2000, 2002, 2017 | yes | yes, once processed | no license work required; record the Pantheon/ABRALIN facts as metadata if convenient |
| Cesarino 2013 | yes | yes, once processed | ritual/myth content is no longer gated; label it `ritual` as metadata if useful |
| Cesarino & Marúbo 2017 | yes | yes | CC-BY-4.0 already verified; register label is metadata only |
| Glottolog | yes | n/a | metadata-only reference; no running text to train on |
| ScriptureEarth / `parallel_por` | already processed under `distill_only` | **now trainable too** under WP2 | this is the largest practical gain: the 4,671 `corpus:` rows stop being blocked |

The Cesarino file's 30 harvested train rows and 25 val / 50 test rows were split when it was
the only harvested source; a second harvested file (Wenia, 921 rows) was added later, so a
re-export will produce different totals. All harvested rows are usable after WP4's lineage
pass. No purge is required by the new policy.

---

## 6. Sequence (historical)

| Order | Work | Blocked by |
|---|---|---|
| 1 | WP0 (ADR-0025 + AGENTS/CLAUDE/GOVERNANCE wording) | owner sign-off on wording |
| 2 | WP2 (matrix) — same commit as the ADR-0007 edit | WP0 |
| 3 | WP1 (defaults) | WP0 |
| 4 | WP3 (gate), WP4 (export) | WP2, WP1 |
| 5 | WP5 (process sources) | WP1 |
| 6 | WP6 (retrain) | WP3, WP4, WP5 |
| 7 | WP7 (docs/tests) | continuous |

Unlike the previous plan, **nothing is blocked on license verification or on a named
authority.** ADR-0025 is recorded and the two questions in §8 are now resolved; this
sequence is kept as a record of how the work was ordered.

---

## 7. What this does not do

- **It does not change external rights.** Copyright and ownership still exist outside the
  repo. This decision means the repo no longer polices them; it does not grant permission to
  the rights holder's material. If outputs (datasets, adapters, demos) are distributed, the
  underlying works' status is unchanged, and that is a decision for wherever they are
  published.
- **It does not clear the base model.** The NLLB-200 600M checkpoint is `cc-by-nc-4.0`
  (`docs/research/candidate-license…`). Training data clearance is separate from model
  license.
- **It does not delete attribution.** Provenance, source ids, and license strings stay in the
  records; they simply stop gating anything.
- **It does not open third-party egress.** `third_party_api`/`cloud_processing` remain opt-in.
- **It does not remove revocation.** If a community or publisher objects later, revocation
  still works and the next lineage-governed (CLDF) export drops the rows; the file-based
  HF/Alpaca/ChatML exporter does not consult revocation yet (see §1a).

---

## 8. Decisions taken

1. **Egress:** kept opt-in (`third_party_api`/`cloud_processing` remain `default_deny`).
   Processing and training never need them; opening them is a separate data-egress decision.
2. **Metadata fields:** `license` / `rights_holder` / `register` are kept as optional recorded
   notes and never gated. Owner decision, 2026-10-18.

---

## 9. Superseded reasoning

The previous draft of this file (2026-10-18) proposed five evidence gates: a committed policy
document, an ADR-0023 intake record (license + rights holder + quality), an authorized
register decision, row-level lineage, and lineage eligibility. It verified that the Cesarino
& Marúbo 2017 chapter is CC-BY-4.0 on the publisher's Zenodo record and that Glottolog is
CC-BY-4.0, and it found the Costa sources and Cesarino 2013 carry no license statement. That
work is recorded in `docs/governance/source-license-audit.md` and remains true as *facts*;
this version downgrades those facts from gates to metadata per the owner's decision. The
technical parts of that plan that survive are WP4 (row lineage, silent-drop fix) and the
re-extraction requirement for the 105 harvested rows.
