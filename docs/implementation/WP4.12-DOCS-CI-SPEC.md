# WP4.12 — Contract Documentation & CI Accounting: Architect Spec

> **Superseded policy note (ADR-0025).** Any rule below that blocks processing or
> training because of a source's classification, licence, rights holder, or register is
> historical. Presence in the repository authorizes processing and training; licences
> and ownership are records, not gates.

**Status:** Approved — Chief Architect (Opus 5.5) under delegated authority, 2026-10-16. Owner ratification pending.
**Depends:** WP4.11 (`9e7e849`).
**Baseline measured 2026-10-16 on `9e7e849`:** `scripts/ci.sh` exit 0 — ruff/format/mypy/schema check clean, `2053 passed, 41 deselected, 0 skipped` (deselected = `realdata` + `native_alignment` by `pyproject.toml` addopts), 3 pydantic `register`-shadowing warnings (see §9).

## 0. Ground rules

1. **Docs describe code as landed, not as planned.** Where M4-PLAN text and the code disagree, the doc follows the code and §8 records the drift. Transcribe names, columns, enums and prefixes from `migrations/versions/0004_m4_lexical_and_review.py`, `0005_review_stale_dependent.py`, `src/langpipe/domain/models/{lexical,review}.py`, `src/langpipe/lexicon/service.py`, `src/langpipe/ingest/wordlist.py`, `src/langpipe/cldf/{importer,exporter}.py`, `src/langpipe/review/{authority,service}.py`. Do not paraphrase from M4-PLAN §6.
2. **No restatement of ADRs.** Each doc section states the contract in a few lines and links ADR-0013/0014/0015/0016 for rationale.
3. **No code changes** outside `tests/unit/test_ci_script.py`. No new ADR is required: every decision documented here is already covered by ADR-0013–0016. Scope widening is forbidden; anything found missing goes to §9 as a carry-over.
4. Report schemas stay IDs/counts/enums/digests only; each documented report MUST say so explicitly (same wording pattern as SCHEMAS.md §Report artifacts (M2)).

## 1. `docs/DOMAIN-MODEL.md`

- **§Type-level linguistic entities → Lexeme / Sense / Concept:** keep the semantic prose; append a "Storage (M4)" line for each naming the table, ID prefix and status column. Lexeme: no paradigms or feature bundles in M4. Sense: `glosses` is language-tag → list of gloss strings; contact-language glosses are meaning hypotheses on the Sense, never target forms (Invariants 8/9). Concept: `concept_type` default `local`; `concepticon_id` / `external_urn` optional.
- **New subsection `### Form–Lexeme link`** after Lexeme: table `form_lexeme` (prefix `flx`), unique `(form_id, lexeme_id)`, optional `role`, append-only (INSERT-only trigger). This is the realization of `Form * ─ * Lexeme` (ADR-0013, M4-PLAN C1).
- **§Review entities:** expand ReviewTask and ReviewDecision with fields, enums (`task_type` 9 values; task `status` = `open|in_review|resolved|cancelled` — note this is a task-workflow status, *not* `LifecycleStatus`; decision = `accept|reject|modify|uncertain|defer`), prefixes `rtask` / `rdec`, and that `review_decision` is append-only at the database level.
- **§Lineage:** add the `stale_dependent` lineage kind (migration 0005, ADR-0014): direction child → parent, written by the review service on a decided lexeme's senses; it marks, never mutates or deletes. Note the 0005 downgrade refuses while such edges exist.
- **New subsection `## Relational realization (M4)`** — one table: entity | table | ID prefix | lifecycle column | append-only | key FKs. Rows: concept, lexeme, form_lexeme, sense, review_task, review_decision. All IDs FK `object_registry.id` (ADR-0009).
- **§Cardinalities:** add `Form * ─ * Lexeme (via form_lexeme)`, `Sense * ─ 0..1 Concept` — and fix the existing `Sense * ─ * Concept` line: the landed model is one optional `concept_id` per Sense. Keep the many-to-many as the logical target, marked "M4 storage: 0..1; widening requires migration + ADR". Add `ReviewTask 1 ─ * ReviewDecision`, `ReviewTask * ─ 1 target (any registered object)`.
- **§Required graph queries:** annotate the two M4 now answers: "Which sources support this sense?" → `ancestor_source_ids` / `lineage descendants`; "Which descendants depend on a revoked source?" → `revocation_impact` (ADR-0015). Others remain future.

## 2. `docs/SCHEMAS.md`

- **New section `## Report artifacts (M4)`** after the M3 reports, same format (purpose, producing stage/run type, artifact kind, top-level keys, guarantees):
  - `lexical-induction-report` v1 — keys: `schema`, `schema_version`, `run_id`, `input_run_id`, `method`, `mode`, `target_language`, `contact_language`, `totals{lexemes, form_links, senses, concepts, evidence_items, lineage_edges}`, `status_counts`. State: `status_counts` can never contain `validated` (Invariant 3).
  - `wordlist-extraction-report` v1 (WP4.6) — transcribe keys from `ingest/wordlist.py`.
  - `cldf-extraction-report` v1 and `cldf-lexical-snapshot` v1 (`EXTRACTION_SNAPSHOT`) — transcribe from `cldf/importer.py`; state the snapshot is the *only* M4 artifact that carries target-language form strings, and why that is allowed (it is an extraction snapshot under source policy, not an export).
  - `cldf-export-report` v1 — keys: `schema`, `schema_version`, `run_id`, `exporter_version`, `dataset_module`, `exported`, `omitted`, `entry_ids`, `sense_ids`, `source_ids`, `files[{name, sha256, size_bytes}]`.
  - `cldf-dictionary` — not a JSON report: the `schema_name` on each `CLDF_EXPORT` file artifact; the format is CLDF Dictionary governed by ADR-0016, not by this repo.
  - The WP checklist says "`cldf-export`"; the landed names are the ones above. Use landed names.
- **§Initial schemas:** add a status column or note: which entries have generated JSON Schema in `schemas/` today. Lexeme, Sense, Concept, ReviewTask, ReviewDecision are **not yet in `SCHEMA_MODELS`** (`src/langpipe/schemas/registry.py`) — say so plainly and link §9 carry-over C-1. Do not imply they exist.
- **§Enums:** list the M4 enum vocabularies (task types, task statuses, decisions, `stale_dependent` lineage kind) with the note that migration CHECK constraints are literal copies and must change together with the domain enum (Invariant 11).

## 3. `docs/PIPELINE-CONTRACTS.md` — Stage 6

Rewrite Stage 6 to the landed contract (the current Inputs list includes IGT and co-occurrence, which M4 did not implement):

- **Tools / methods:** `langpipe lexicon induce`; registered methods in `lexicon/registry.py` (alignment-baseline adapter, `wordlist` path, `cldf_lexical@0.1.0`). List each with its accepted input run type.
- **Inputs (M4):** a succeeded Stage 5 token-alignment run, a wordlist extraction run, or a CLDF extraction snapshot; target + contact language. **Deferred:** IGT (M5), co-occurrence, multilingual — mark as "not implemented in M4", don't delete.
- **Preconditions:** input run succeeded; source policy gates (cite the exact operation checked); ambiguous input run → `AmbiguousInput` (use the real exit code).
- **Outputs:** Lexeme/FormLexeme/Sense/Concept rows at `candidate` or `supported`, EvidenceItems with `score_breakdown` (`lexical-v1`), lineage edges, one `lexical-induction-report` v1 artifact; all in one transaction.
- **Invariants:** keep the existing four; add: scoring never yields `validated`; contact-language glosses never become target Lexemes/Forms; does not mutate Segments/TokenOccurrences (golden check, WP4.11); idempotent rerun reuses the succeeded run (parameter/input hash); pycldf never runs inside Stage 6.
- **Failure:** whole-run rollback, failure recorded on the run, no partial semantic output.
- **Stage 10 — Human review:** add a pointer: "M4 implementation: lexical review — see REVIEW-WORKFLOW.md §Implementation (M4)"; add invariants: authority checked against the registry before any write; decision insert + status change + score recompute + stale flags in one transaction.

## 4. `docs/REVIEW-WORKFLOW.md`

Keep the normative text; append:

- **`## Implementation (M4)`** — scope: `lexical_sense` and `lemma` targets (confirm against service; other task types exist in the enum but have no producer yet). CLI: `langpipe review list [--type --role --language --min-priority --limit]` and `langpipe review decide --task-id --decision --reviewer --role [--notes --superseding]` (verify flags against `cli/review.py`). Output is IDs/enums only.
- **`## Authority registry`** — `ReviewAuthorityRegistry` built by `registry_from_profiles()` from `LanguageProfile.review_authority` (`ReviewAuthorityGrant`); semantics verbatim from `review/authority.py` docstring: any-grant match on role + language (+ domain); `domains=None` = all domains; domain-scoped grant fails closed on untagged objects; language-less targets (concepts) fall back to `holds_role`; no grants ⇒ deny all. State it is process-local configuration, not database RBAC (ADR-0013 §4), and that the reviewer ID is an asserted string — there is no authentication in M4 (see §9 C-4).
- **`## Decision effects (M4)`** — table: decision → target status effect → task status. `accept` → `validated` (the only path to `validated`); `reject` → `rejected`; `modify` → requires `--superseding`, original kept; `uncertain`/`defer` → status unchanged. Transcribe exact behavior from `review/service.py`; if the code differs from this table, the code wins.
- **§State transition:** replace the implicit promise with the landed reality: direct dependents flagged `stale_dependent` (ADR-0014); full cascading recalculation is **OPEN**, tracked by `TODO(M4)` in `review/service.py` and `cldf/exporter.py`; exporter counts but does not filter stale rows.

## 5. `docs/DEVELOPMENT.md`

- **§M4 — Lexical evidence:** mark "Delivered (2026-10-16)", one line per deliverable with WP numbers.
- **New `## Local commands (M4)`** following the M3 format: `lexicon induce`, `review list`, `review decide`, `cldf import`, `cldf export`, `lineage descendants`, each with real flags and the output rule (key=value, no forms/glosses/prose on stdout). Note `cldf export --output-dir` refuses a non-empty directory.
- **§CI baseline:** replace `cldf validate   # when exporter exists` with `cldf validation — in-process (pycldf validate on the staging dir) inside the exporter; covered by service + golden tests`. **Decision:** no separate `cldf validate` CI step; the exporter cannot commit an invalid dataset, and a second validator would be a redundant dependency path.
- **§Local commands (M3) first paragraph:** generalize to "M1–M4"; add the zero-skip rule: `LANGPIPE_REQUIRE_POSTGRES=1` turns any skip (not only DB skips) into a session failure (`tests/fixtures/db.py`), so "zero skips" is enforced, not hoped for. Record the measured baseline (2053 passed / 41 deselected / ≈10 min) as an informational figure, not a contract.

## 6. `tests/unit/test_ci_script.py`

The zero-skip guarantee and the "all suites run" guarantee currently rest on lines of `ci.sh` that no test guards. Add, without touching `ci.sh`:

1. `test_ci_pytest_requires_postgres_and_forbids_skips` — the pytest line in `ci.sh` sets `LANGPIPE_REQUIRE_POSTGRES=1`.
2. `test_ci_pytest_does_not_narrow_selection` — the pytest invocation has no `-m`, `-k`, `--deselect`, `--ignore`, `-x`/`--maxfail`, or explicit path args (the default collection must include `tests/unit`, `contract`, `service`, `golden`, `integration`). Parse the line; don't just substring-search the whole file.
3. Extend `test_ci_migrates_test_database_when_guard_passes` (stubbed run, already exists) to assert the full gate order from the call log: `uv sync --frozen` → `ruff check` → `ruff format --check` → `mypy src` → `python -m langpipe.schemas check` → `docker compose up -d --wait db` → `alembic … upgrade head` → `pytest`. Order matters: migrations before tests, guard before docker.
4. Optional, recommended: a unit test that `pyproject.toml` addopts still contains `-m 'not realdata and not native_alignment'` and `--strict-markers` (the deselection the two existing marker tests rely on lives there, not in `ci.sh`).

Each new test MUST be shown to fail when the guarded line is mutated (temporarily edit a copy or monkeypatch `CI_SCRIPT`), and pass on the real script.

## 7. `docs/implementation/M4-PLAN.md`

- Header `**Status:**` → `Completed — 2026-10-16 (WP4.1–WP4.12; Gates …). Owner ratification pending.` Keep "owner ratification pending": delegated approval is not owner ratification.
- Tick every WP checklist item that landed; any item that did **not** land stays unticked with a pointer to §9 of this spec (do not tick to make the page look complete).
- Add `## 8. Completion record`: commit per WP, gate numbers, CI evidence (`2053 passed, 0 skipped, 41 deselected`, date, commit), and the drift list below.
- **Drift to record (plan text vs landed):** C11 prefixes `rev_task_`/`rev_dec_` → landed `rtask`/`rdec` (+ `flx`, `cpt`, `lex`, `sense`); WP4.2 plural table names (`lexemes`, `review_tasks`, …) → landed singular; WP4.2 migration-test wording "downgrades to 0003 / reapplies to 0004" → head is now `0005_review_stale_dependent`; Stage 6 inputs narrower than PIPELINE-CONTRACTS listed. Do not rewrite the original WP text — annotate.

## 8. Acceptance

1. `scripts/ci.sh` exit 0 with `0 skipped` in the summary (the session hook would fail otherwise).
2. New `test_ci_script.py` tests pass and were seen failing under mutation.
3. Every table, enum value, report key and CLI flag named in the docs greps to the source (a reviewer spot-check of ≥10 names).
4. `git diff --stat` touches only the seven owned files plus this spec.

## 9. Open questions / carry-overs into M5 (not blockers for declaring M4 complete)

- **C-1 JSON Schema export gap.** SCHEMAS.md lists `lexeme`, `sense`, `concept`, `review-task`, `review-decision`, but they are not in `SCHEMA_MODELS` and no `schemas/*.v1.schema.json` exists. Decision: not widened into WP4.12 (code + generated artifacts outside the docs WP). First task of M5 (WP5.0): add the five models to the registry, generate, commit; `schemas check` then guards them.
- **C-2 Cascading recalculation** (REVIEW-WORKFLOW §State transition, M4-PLAN C10, ADR-0014): OPEN. Exporter counts stale rows but exports them. Must be resolved, or stale rows filtered from export, before any external CLDF publication.
- **C-3 Pydantic warning:** field `register` on `Lexeme`, `Sense`, `EvidenceItem` shadows an inherited attribute. Harmless today; rename-with-alias would be a persisted-format change (migration + ADR-free but Invariant 11 applies). Schedule with C-1 since both touch serialized shapes.
- **C-4 Reviewer identity is unauthenticated** (asserted `--reviewer` string checked against config). Acceptable for single-operator M4; must be addressed before multi-reviewer community use. Record in GOVERNANCE.md backlog.
- **C-5 Owner ratification** of ADR-0013–0016 and M4 completion remains pending; M5 may start on delegated authority, but ADR-0013 §4 (authority-as-config) is the item most likely to be revisited by the owner.
