# PENDING — task tracker

Single place for "what is next" in this repository. The `tsk` board
(project `language-distillation`) remains the state of record for work packages;
this file is the readable summary and the hand-off list.

Last updated: 2026-11-18.

Status values: `TODO` (not started), `IN PROGRESS`, `BLOCKED` (needs a decision
or an external fact), `DONE` (kept here until the next revision).

---

## 1. Release status (public repository)

| Item | Status | Notes |
|---|---|---|
| Public GitHub repository | `DONE` | <https://github.com/luandro/language-distillation> (public, single squashed initial commit) |
| Data excluded from the repository | `DONE` | `var/`, `exports/` data, `tests/golden/expected/m5/` are local artifacts, see §5 |
| Licence | `DONE` | MIT (`LICENSE`), code and docs only |
| Secret and privacy scan | `DONE` | 2026-11-18, Gemini 4 Hydrogen review: SAFE-TO-PUBLISH; see §5 |
| CI gate (`./scripts/ci.sh`) | `DONE` | 2026-11-21: `CI_EXIT=0`. ruff + format on `src`/`tests`, `mypy src` (215 files), schema check, migrations, then `3046 passed, 48 deselected` in 46 min |
| Slow gate | `OPEN` | 46–66 min end to end; see §7 |

## 2. Policy and governance

| Item | Status | Notes |
|---|---|---|
| Presence-based authorization (ADR-0025) in code | `DONE` | `policy.py` matrix, traceability-only training gate |
| Stale prose claiming `distill_only` blocks training | `DONE` | `docs/PRODUCT.md`, `.skills/language-distillation/SKILL.md`, `MODEL_CARD.md` |
| License/register recorded as metadata, not gates | `DONE` | `docs/governance/source-license-audit.md` (2026-11-04 section) |
| Persisted `SourcePolicy` rows match `direct` | `DONE` | 9 sources verified `direct` + `DIRECT_TRAINING: allow` |
| Author an ADR for the 7-source training set | `WONT-FIX` | ADR-0025 already authorizes it; no reversal to record |
| Third-party egress (`third_party_api`) | `TODO` | Stays `default_deny`; separate decision, never needed for training |

## 3. Data and extraction

| Item | Status | Notes |
|---|---|---|
| Register + ingest all `var/external/` sources | `DONE` | 9 sources |
| Extract Costa 2002, Cesarino & Marúbo 2017 | `DONE` | 600 / 803 segments |
| Costa 2002 example extractor (candidates only) | `DONE` | `src/langpipe/languages/mzr/costa_examples.py`; 1 accepted, 21 held back |
| Admit the Costa 2002 candidate into training | `BLOCKED` | Owner decision; phonetic orthography differs from the practical target, recommendation is to keep segment-only |
| Costa 1992, 2000, 2017 pair extraction | `BLOCKED` | Phonology papers: word-level IPA lists with OCR damage, no sentence pairs. Needs printed-page work |
| Cesarino 2013 chant orthography recovery | `TODO` | OCR lost nasal diacritics; use Wenía 2018, Villada 2018, Cesarino 2008 thesis; two-reader adjudication per `.skills/row-adjudication` |
| Cesarino & Marúbo 2017 105 pairs via governed IGT run | `TODO` | Still read from `exports/harvested_parallel/*_parallel.jsonl`; plan §1a |
| Wenía 2018 in `source_index` | `DONE` | `harvested:cesarino_2018_wenia_parallel` |
| Harvested duplicates across sources | `TODO` | Deduped within a source, not across sources |
| `schemas/dataset-manifest.v1.schema.json` | `TODO` | Manifest written by hand today |
| `var/exports/source_index.json` generated from the store | `DONE` | `scripts/build_source_index.py` writes the `.generated.json`; operator copies it |

## 4. Training and evaluation

| Item | Status | Notes |
|---|---|---|
| Dry-run gate passes | `DONE` | 5,018 eligible train rows |
| Real NLLB LoRA run | `TODO` | Deferred by `docs/governance/training-enablement-plan.md` pending dataset sorting |
| Evaluate on benchmark v2 + chant benchmark | `TODO` | `src/langpipe/training/nllb_eval.py`, `exports/mzr/probes/` |
| `MODEL_CARD.md` sources and policy ids | `TODO` | Update after the training run |
| File-based exporter honours `exclude` / revocation | `TODO` | Only the lineage-governed CLDF path does (ADR-0025 §7) |
| File-based exporter keeps one `source_id` per row | `TODO` | Verse pairs spanning two sources lose one side |

## 5. Public release, 2026-11-18

What was published and what was deliberately left out.

**Left out (local only, gitignored):**

- `var/` — 2.6 GB of source material (Costa and Cesarino PDFs, harvest caches).
- `exports/` data — datasets, dictionaries, CLDF, IGT, chant rows, probes. These
  embed ScriptureEarth verses, Wenía 2018 chants (CC BY-NC 4.0) and Cesarino 2013
  material. ADR-0025 removed the *internal* gates; it does not grant onward
  redistribution rights, so the text stays local and is rebuilt with
  `uv run langpipe synth export`.
- `tests/golden/expected/m5/`, `tests/golden/fixture/morphology/` — in-progress
  WP5.16 fixtures.
- `Texto colado*.txt` — scratch snippets, not part of the project.

**Kept:** `src/`, `scripts/`, `tests/`, `schemas/`, `docs/`, `exports/*.py`,
`exports/**/README.md` and `exports/mzr/MODEL_CARD.md`.

`exports/harvested_parallel/cesarino_2018_wenia_tilde_marks.json` was briefly
tracked as glyph evidence, but it also stores the extracted `line_key` — a full
printed chant line from a CC BY-NC work. Codex `gpt-6.2-sol` caught it; it is
local-only now. `exports/` is a default-deny allowlist, so a new file of any
shape stays local.

**Tests that need local data** are marked `pytest.mark.realdata`, so the default
gate deselects them instead of skipping (required mode treats a skip as failure):
the Wenía marks report, the Wenía PDF, the Cesarino thesis PDF, the chant
orthography reproduction, and the derived-row schema check (which now validates
in-memory rows only).

**History:** squashed to a single initial commit. The previous 244-commit
history stays local only (`git branch local-history`); it contained `exports/`
data blobs.

**Secret scan, 2026-11-18:** every file in the published tree was scanned for
private keys, AWS/GitHub/OpenAI-style tokens, `.env` files and credential-shaped
strings. No hits. `.env`, `.env.*`, `checkpoints/` and `*.log` are gitignored. A
third-party personal email quoted in the Pano survey notes was redacted.

### 2026-11-21 follow-up

- `scripts/ci.sh` was blocked at its **blocking** format tier by the untracked
  `tests/golden/normalize_m5.py`; it is now `ruff format` clean. The file is the
  owner's WP5.16 work in progress and is not published.
- `./scripts/ci.sh` exits 0: `3046 passed, 48 deselected`, 0 failed (46 min). The
  slowest tests are listed in §7.
- `docs/README.md` now says that `var/` and `exports/` paths in the docs are local
  build artifacts, so a reader of the public repository is not sent looking for files
  that were deliberately not published.

## 6. Work packages (`tsk`, project `language-distillation`)

| Task | Status |
|---|---|
| #221 WP5.16 Golden fixture M5 | `started` — fixtures local, 20/20 tests pass |
| #222 WP5.17 Contract documentation & CI accounting | `open` — next |
| #175 WP3.13 Milestone 3 realdata gate | `blocked` |
| #204 WP4.12 reused CLDF export reports stale omitted counts | `review` |
| #210–#220 WP5.5–WP5.15 | `review` |
| #268–#271 dictionary session, truncation, attestations, inflected forms | `review` |
| #273 CI gate debt (ruff, mypy, one failing test) | `review` — stale: `ruff check src tests` is clean, `mypy src` is clean (215 files), the suite is green. What remains is the non-blocking tier: 42 ruff findings in `scripts/train_nllb_lora.py` and 12 unformatted files outside `src`/`tests` |
| #277 ci.sh can never pass (undeclared sacrebleu) | `review` — stale: `sacrebleu>=2.4` is declared in the `dev` group and `ci.sh` passes |
| #275 CLDF reuse does not re-derive `access_class` | `review` |
| #276 regenerate `derived_rows_audit.json` | `review` |
| #272 durable authenticated public tunnel for the portal | `open` |

Only the repository owner moves a task to `done`.

## 7. Known defects in the current tree

| Defect | Where | Status |
|---|---|---|
| `scripts/train_nllb_lora.py` carries 42 `ruff check` findings (pre-existing style debt: long lines, f-strings without placeholders, unused imports) | `scripts/train_nllb_lora.py` | `OPEN`, tracked as `#273`; non-blocking by design, `ci.sh` only reports it |
| 12 files outside `src/` and `tests/` are not `ruff format` clean (mostly `scripts/`, `ops/`, `notebooks/`) | `scripts/`, `ops/` | `OPEN`, same non-blocking tier, `#273` |
| The suite takes ~66 min; `test_approval_withdrawal_and_regrant[postgres]` alone is 353 s and six golden-M4 tests are 40–143 s | `tests/service/test_morphology_revocation_impact.py`, `tests/golden/test_golden_m4.py` | `OPEN`, perf only; no sleeps in the tests, it is real database work |
| ADR-0007 is `Proposed` while ADR-0025 (Accepted) amends its matrix | `docs/adr/0007-…`, `docs/README.md:36` | `OPEN`, governance wording only; the matrix in force is ADR-0025's |