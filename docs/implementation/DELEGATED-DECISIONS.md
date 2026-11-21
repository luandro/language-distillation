# Delegated Architecture Decisions Log

> **Reading note (ADR-0025):** entries below predate the presence-based authorization rule.
> References to supplying a "rights decision", self-authorizing rights, or holding a package
> until authorization are historical; a source present in the repository is processed and
> trained on, and licence/ownership are records.

This document records architectural, governance, and milestone execution decisions made by Chief Architect (Claude Opus 5.5) under delegated authority from the project owner, pursuant to the directive:
*"human going to sleep, consult with opus 5.5 from now on, on decisions, dont ask human anymore"*.

Every entry records the date, the decision, the rationale (citing repository invariants), and how the human owner may ratify, amend, or reverse the decision.

---

## 1. 2026-10-15: Milestone 3 Realdata Gate vs Milestone 4 Progression

- **Decision**: Keep `tests/integration/test_scriptureearth_parallel.py` as an explicit external-operator gate that fails safely when inputs are unconfigured. Mark Milestone 3 as code/contract complete, with the dual-source realdata gate unsatisfied pending external human operator inputs. Advance immediately to Milestone 4 (Lexical Evidence).
- **Rationale**:
  - Live research (`scratch/research_por.md`) confirmed ScriptureEarth does not publish a Portuguese USFM package; candidate eBible texts (`porbrbsl`, `porbr2018`) exist on a third-party host and have structural versification divergence in EXO and NEH.
  - Fabricating ScriptureEarth provenance or having an automated pipeline self-authorize rights, self-sign counts, or heuristically map verse numbers violates Invariants 1, 3, 4, 5, 7, 9, 10, and 12.
  - The safe-fail gate is the system working as designed.
- **Reversal / Ratification**:
  - To ratify: Accept ADR-0012, provide Portuguese USFM package and reviewed manifest, supply rights decision, choose 6-book scope or versification mapping, and sign `scriptureearth_parallel_counts.json` (tracked on `tsk` task 175).
  - To reverse: Reject ADR-0012 or supply an alternative Portuguese text source.

---

## 2. 2026-10-15: Autonomous Execution Scope & Stop Boundary

- **Decision**: Authorize the agentic pipeline (Antigravity coordinator, `omp` junior implementer, `codex` senior reviewer) to draft and implement Milestone 4 (Lexical Evidence) and Milestone 5 (IGT & Morphology Graph) autonomously under Opus 5.5 architectural oversight. Stop strictly after Milestone 5.
- **Strict Invariants Preserved**:
  - No synthetic validation: No real Marúbo data receives `validated` status without human review; test/golden runs use synthetic reviewer identities.
  - No external transfer: No git push, PR, or external publication; local commits only.
  - No synthetic generation or model training in code before M5 is verified and owner returns.
  - Realdata gates requiring human operator inputs remain explicitly blocked on `tsk`.
- **Reversal / Ratification**:
  - Owner may review the git log for commits on main (each work package committed with clean unit/integration/schema test passes).
  - Any work package or milestone branch can be reset or reverted cleanly via `git revert`.

---

## 3. 2026-10-15: ADR-0013 Lexical Model & Review Authority

- **Decision**: Accept ADR-0013 under delegated authority (owner ratification pending).
  - Add explicit many-to-many `Form ↔ Lexeme` relation to preserve lexical ambiguity.
  - Concepts are local by default, with external Concepticon mappings optional.
  - Strictly omit paradigms and feature bundles from `Lexeme` (deferred to M5).
  - Model review authority as a language profile configuration registry rather than a separate database roles table (smallest reversible abstraction).
- **Rationale**: Follows `docs/DOMAIN-MODEL.md`, `docs/REVIEW-WORKFLOW.md`, and Invariant 7 (ambiguity preservation). Avoids premature schema complexity for reviewer roles.
- **Reversal / Ratification**:
  - To ratify: Change status in `docs/adr/0013-lexical-model-and-review-authority.md` to `Accepted`.
  - To reverse / amend: Update ADR-0013 and adjust configuration or schema via migration.

---

## 4. 2026-10-16: WP4.11 Golden M4 — Synthetic Export Source and Two-Part P12

- **Decision**: Golden sources `01-parallel-distill` and `03-wordlist` stay unchanged. `redistribute_derived` is default-deny in every policy mode, so neither of them can ever export a CLDF row. WP4.11 therefore adds a synthetic redistributable wordlist under `tests/golden/fixture/lexicon/`, following the M3 `fixture/alignment/` precedent. Phenomenon 12 is proven in two parts: revoking 01 flips the eligibility of the objects derived from it without changing any stored row (ADR-0015), and revoking the export source makes its existing export artifacts ineligible, so re-exporting fails closed. Full spec: `docs/implementation/WP4.11-GOLDEN-M4-SPEC.md`.
- **Rationale**: Editing a golden manifest's policy would change a governance fact and churn the M1 snapshots. The added source sits outside `fixture/sources/`, so M1 and M2 are unaffected.
- **Reversal / Ratification**:
  - To ratify: keep as is.
  - To reverse: grant `redistribute_derived` on `03-wordlist` (this regenerates the M1 snapshots), then delete `fixture/lexicon/`.

---

## 5. 2026-10-16: M5 Plan — Delegated Architectural Decisions and Scope Fences

- **Decision**: Adopt the architectural decisions of `docs/implementation/M5-PLAN.md` under delegated authority (owner ratification pending). Recorded here per M5 carry-over C-5:
  - **G1 — Source-use approval overlay (ADR-0018)**: a `review_required` operation becomes `allow` for one specific source via append-only `source_use_approval` rows applied in `effective_policy`, only where the mode's baseline is `review`; `deny`, `default_deny` and `hard_deny` are never lifted. The golden manifest is not edited (§4 precedent: editing a manifest changes a governance fact). This is the mechanism ADR-0007 deferred and the only way the `review_required` golden IGT source can be processed at all.
  - **G8 — Unknown-morpheme fixture**: phenomenon 7 is proven by a new synthetic fixture outside `fixture/sources/` (`tests/golden/fixture/morphology/unknown-gloss.{txt,manifest.yaml}`, `direct`, public), one record glossed with the Toolbox unknown marker `***` (M3/M4 synthetic-fixture precedent; M1/M2 untouched).
  - **G14 — Method promotion gate (ADR-0019)**: a morphology method's analyses are policy-promotable only if the method is listed in `morph-v1`'s promotion allowlist with a pinned benchmark report. M5 ships an empty allowlist for induction methods, so only IGT-asserted hypotheses can reach `supported`.
  - **G16 — Stale-dependent recalculation (C-2)**: direct dependents are recalculated with a `recalculated` lineage kind; the CLDF exporter then truly omits rows with an unresolved stale flag instead of counting them under `omitted` while exporting them; `cldf-export-report` moves to schema_version 2.
  - **Scope fences (M5-PLAN §1)**: no synthetic generation, no model training, no generator code; no IGT or morphology export (ADR-0016 deferral stands); no `Paradigm`/`ParadigmSlot`; no Form-level materialized analyses (occurrence-level only); no IGT input to Stage 6 lexical induction; no automatic morpheme merging across strings or runs; no authoritative-import validation path; no feature mapping to external namespaces (`local:<lang>:<LABEL>` verbatim); language-specific behavior only in language profiles.
- **Rationale**: Preserves Invariants 2, 3, 4, 6, 8, 9 and 12: observation stays separate from inference, machine output never yields `validated`, ambiguity and unknowns stay representable, governance acts through one door, related-language evidence never becomes target-language truth, and no decision is silent. Full decision table and evidence: `docs/implementation/M5-PLAN.md` §1–§2.
- **Reaffirmed**: no real Marúbo data receives `validated` status without human review (§2 above), and no real source receives a source-use approval without its owner.
- **Reversal / Ratification**:
  - To ratify: owner accepts ADR-0017/0018/0019 (status `Accepted (delegated; owner ratification pending)` becomes `Accepted`).
  - To reverse G1: reject ADR-0018; the `review_required` IGT source stays blocked as ADR-0007 left it. Existing approval rows are append-only history and are not edited.
  - To reverse G8: delete `tests/golden/fixture/morphology/`; M1/M2 snapshots are untouched.
  - To reverse G14: reject ADR-0019 or keep the `morph-v1` promotion allowlist empty; promotion then stays human-only.
  - To reverse G16: revert the exporter to M4 behavior and the `cldf-export-report` to schema_version 1 (the false `omitted` key name returns with it).
  - To reverse a scope fence: amend the fence in the M5 plan and record the widening here; several fences have planned escape hatches (e.g., Form-level analyses: additive column + migration; Paradigm: ADR-0017 §9 deferral).
