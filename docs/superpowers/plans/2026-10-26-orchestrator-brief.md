# 2026-10-26 Orchestrator Brief — direction approved by GPT-6.1-Sol

Purpose: this file is the contract between the owner, the orchestrator agent, and
the tsk board. The board (project `/home/luandro/Dev/AI/language-distillation`)
stays the **single source of task truth**; this file only records the approved
order, the per-card acceptance criteria, and the dispatch mechanics.

## Approval record

- **Reviewer:** GPT-6.1-Sol, effort `low`, read-only one-shot via
  `codex-companion.mjs`, job `task-mvpz8ni1-bqhzkx`, 2026-10-26–27.
- **Verdict: on-track.** "The dictionary work improves evidence presentation
  without promoting linguistic claims; ADR-0028 moves corpus configuration
  toward the required language-profile boundary. Approve continuation with a
  short M5 contract refresh before implementation resumes."
- **Independent verification of Sol's evidence (by the incumbent GLM session):**
  `session.py:118` (basis inferred from provenance text + citations, status
  copied unchanged), `tests/unit/test_lexicon_dictionary_session.py:432` (63
  orphan forms pinned, `form_index == []`), `ADR-0028:56` (acknowledged
  corpus-specific debt: `derived:cesarino-2018:` prefix, `wenia`/`zenodo` keys),
  `M5-PLAN.md` header + `ADR-0025:44`, and the two handoff nits Sol found
  (the "plan file and nothing else" scope, and the `#277` "closed" wording) —
  both now fixed in the handoff. Everything Sol cited exists as claimed.
- **Board caveat:** Sol could not read the board live (`tsk list` needs
  filesystem writes its sandbox lacked). The incumbent verified board state
  directly and aligned statuses (#275, #276 → `ready`) with the approved order.

## Approved direction (summary)

1. Owner disposes of the seven `review` cards (#204, #268, #269, #270, #271,
   #273, #277). Agents stay off them.
2. First agent work is the **#275 + #276 maintenance package**. Its acceptance
   criteria were already written by the Sol pass (below), so **no additional
   senior plan call is needed** — juniors start directly.
3. **#272 is OWNER** — exposure model, permitted surfaces, identities, auth.
   A named tunnel alone is insufficient. #175 stays a separate realdata lane,
   OWNER supplies operator inputs.
4. **M5 (#210–#222) is gated on one senior plan refresh** of
   `docs/implementation/M5-PLAN.md` against the current code and ADR-0025 —
   bounded scopes, test commands, ownership and review checkpoints, and explicit
   resolution of superseded policy clauses. No #211+ work before that exists.
5. **No dictionary deliverable is an M5 prerequisite** (orphan forms, portal,
   PDF, review-card closure — none supplies morphology evidence).

## Reconciliation nuance for the M5 refresh (do not "fix" this wrong)

`M5-PLAN.md` says the ADR-0018 overlay "is the only way the `review_required`
golden IGT source can be processed at all"; `ADR-0025` says those approvals are
"no longer needed **for the sources this ADR covers**". This is not a
contradiction: ADR-0025 covers the sources that are actually present in the
repository (presence-based authorization); the golden IGT source is absent, so
the ADR-0018 overlay remains its declared mechanism. The refresh should resolve
the wording explicitly, not delete the overlay.

## Approved backlog (Sol, verified)

| # | Card(s) | Scope + acceptance criteria | Tag |
|---|---|---|---|
| 1 | #204 #268 #269 #270 #271 #273 #277 | Accept or return with specific unmet criteria; the zero-skip CI evidence stands. | **OWNER** |
| 2 | #275 #276 | One maintenance frame: define policy-change reuse tests and constrain report regeneration to expected prose changes. | ~~SENIOR-PLAN~~ **already done by the Sol pass above** |
| 3 | #275 | Correct CLDF reuse under changed `access_class`. Tests must change classification while preserving selected rows and attribution, prove current classification governs the result, preserve historical artifacts, and retain denial/revocation guards. | **JUNIOR** |
| 4 | #276 | Regenerate `derived_rows_audit.json`. Diff contains only expected policy prose; row identities, counts, content, provenance, lineage unchanged. Investigate any broader diff. | **JUNIOR** |
| 5 | #275 #276 | Review together: discriminating reuse tests pass, regeneration has no unexplained semantic change. | **SENIOR-REVIEW** |
| 6 | #272 | Owner decides exposure model, surfaces, identities, auth; explicit choices + owner-approved access matrix. | **OWNER** |
| 7 | #210–#222 | Senior refresh of the M5 execution brief vs current code + ADR-0025. | **SENIOR-PLAN** |
| 8 | #210 | Finish WP5.5: approvals lift only applicable `review` baselines; withdrawal tightens eligibility; explicit denials stay effective; policy access uses the single door. No recreated superseded rights gates. | **JUNIOR** |
| 9 | #210 | Gate 34 review: PostgreSQL service tests, governance properties, M1–M4 golden regressions. | **SENIOR-REVIEW** |
| 10 | #211 | IGT readers: verbatim preservation, hardened XML, typed malformed-input outcomes, Toolbox/Xigt round-trips. | **JUNIOR** |
| 11 | #212 | Stage 7a extraction: immutable observations, complete lineage, governed reads, idempotence, normalize/tokenize handoff. | **JUNIOR** |
| 12 | #213 | Morphology protocol/scoring: deterministic unsegmented baseline, versioned breakdowns, automatic `validated` unreachable. | **JUNIOR** |
| 13 | #214 | Assertion service: exact occurrence mapping, honest abstention, atomic persistence, competing analyses, lineage. | **JUNIOR** |
| 14 | #211–#214 | Review package vs Gates 35–38. | **SENIOR-REVIEW** |
| 15 | #215 | IGT projection: pinned inventory, alternative segmentations preserved, contradiction evidence, no invented morphemes/features. | **JUNIOR** |
| 16 | #216 | Benchmark: held-out lineage-leakage refusal, deterministic ranking, coverage/abstention metrics, baseline comparisons. | **JUNIOR** |
| 17 | #217 | Optional Morfessor spike: documented reproducible/offline go or no-go; no base-CI dependency; a documented no-go satisfies the card. | **JUNIOR** |
| 18 | #215–#217 | Review adapter + benchmark; #217 stays non-blocking. | **SENIOR-REVIEW** |
| 19 | #218 | Morphology review: authority/target pairing; accepting one analysis leaves competitors untouched; lexical behavior unchanged. | **JUNIOR** |
| 20 | #219 | Recalculation/export: bounded idempotent recalculation without status promotion; stale rows actually omitted; report changes versioned + documented. | **JUNIOR** |
| 21 | #220 | Revocation/withdrawal impact: correct descendant sets and scope; stored observations unchanged. | **JUNIOR** |
| 22 | #218–#220 | Review trio vs Gates 42–44. | **SENIOR-REVIEW** |
| 23 | #221 | Golden M5: phenomena 5/6/7/10/11, ambiguity, unknowns, leakage refusal, governance, output non-disclosure. | **JUNIOR** |
| 24 | #222 | Contracts + CI reconciled; full required-PostgreSQL gate, zero skips, explicit optional deselections. | **JUNIOR** |
| 25 | #221 #222 | Final milestone review; stop at M5. | **SENIOR-REVIEW** |
| — | #175 | Operator inputs + signed scope/count evidence; agents must not fabricate. Separate realdata gate. | **OWNER** |

Card-to-WP mapping follows WP5.6–WP5.17; confirm against the live board before
dispatch. Go-gate for the chain (M5-PLAN.md:249,262,277): WP5.0–5.4 predecessor
evidence verified, #210 complete and reviewed, superseded contracts refreshed,
first package framed with the real test environment. Pure reader/protocol work
depends only on WP5.2; extraction needs WP5.5 and the readers.

## Orchestrator prompt (copy-paste into the orchestrator session)

```text
You are the ORCHESTRATOR for /home/luandro/Dev/AI/language-distillation. You frame, dispatch and verify; juniors implement. Read first, in order:
  1. docs/superpowers/plans/2026-10-26-orchestrator-brief.md  (this mandate: approved backlog, per-card criteria, dispatch mechanics, go-gates)
  2. docs/superpowers/plans/2026-10-20-dictionary-session-HANDOFF.md  (Final state + Working rules + verification traps)
  3. AGENTS.md invariants; docs/implementation/M5-PLAN.md when M5 work begins.

SOURCE OF TASKS: the tsk board, project /home/luandro/Dev/AI/language-distillation (`tsk list --all --json`). The board is the single truth; do not keep parallel lists. New discoveries become new cards with evidence. Only the owner sets done / disposes review cards. Direction was approved by GPT-6.1-Sol (2026-10-26): start with the #275 + #276 maintenance package (criteria in the brief, no extra senior plan call), keep #272 and #175 as OWNER, gate #211+ on the senior M5 plan refresh (brief row 7), and never start it before that refresh exists.

ROSTER — verify each route once with a cheap identity probe before real use; never burn retries against 402/429 routes (route around them):
  - Junior implement (default, free/cheap): `opencode run -m "ollama/minimax-m3.1-flash:cloud" "<brief>"`, or the same with the owner's opencode GLM-5.3-Flash Free alias. Alternative junior: `glm -p "<brief>"` (owner says it routes gpt-6-luna; probe first). Name exact target files in every brief; open-ended prompts make implementers wander (verified in the handoff).
  - Cheap per-file review, different family where possible: opencode nemotron-3.5-super-vl-free / minimax-m3.1-flash-free (the planted-defect reviewers named in the handoff's execution model).
  - Senior plan/review — spend minimally, ALWAYS batch (one plan per framed package, one review per completed package, never per-file):
      * Codex one-shot, read-only: `node ~/.claude/plugins/cache/openai-codex/codex/<active>/scripts/codex-companion.mjs task --model gpt-6.1-sol --effort low --background "<read-only brief>"`; find the active cache dir via ~/.claude/plugins/installed_plugins.json; fetch results with `result <id> --json`, findings at .storedJob.result.rawOutput; jobs are scoped to the launch cwd.
      * agy (Antigravity, Gemini 4 Carbon): headless mode; discover the exact model id from agy's help/config before use. If agy is unavailable or unfunded, Codex sol is the senior fallback.

LOOP, per card (this is the whole job):
  1. Read the card, the brief-table row, and any docs AGENTS.md routes for it.
  2. Senior plan only if the row says one is needed and none exists yet. Batch clarifying questions into a single call.
  3. Brief juniors: target files, acceptance criteria, tests-first for behavior changes, no git commits, no rm, cite file:line via XERJ (`xerj search`, `xerj def`).
  4. VERIFY EVERY DIFF PERSONALLY: read the actual diff, run the relevant tests; never accept a junior self-report. Reject and re-brief on failure (max 2 rounds, then senior review or stop).
  5. Cheap-family review pass on the changed files; embed the planted-defect checklist for UI/print work (see docs/research/agent-capability-matrix-2026-10.md).
  6. Full gate before any "done": `export DOCKER_HOST=unix:///var/run/docker.sock` (the default socket is a dead rootless daemon), `docker compose up -d --wait db`, `bash scripts/ci.sh`; require CI_EXIT=0, 2687 passed, 0 skipped, 41 deselected. A "2010 passed, 677 skipped" run is NOT a pass. The DB is likely already up on 55432.
  7. Commit yourself, from the exact reviewed revision: explicit `git add <paths>`, conventional message explaining why; agents never git add/commit. Known clean-tree noise to leave alone: modified notebooks/Marubo_NLLB_600M_Finetune.ipynb, two "Texto colado*.txt" files, exports/mzr/datasets/embedded_bundle.b64.
  8. Board hygiene: set the card to review with a note naming commit, commands and results; update DEVELOPMENT/ADR/plan docs when wiring changed.

REPO RULES (violations cost real rework):
  - `.venv/bin/python` (bare python3 fails: pyenv 3.12 missing). NEVER `rm`. Line length 100; ruff excludes *.md.
  - Canonical artifacts (exports/mzr/dictionary*.json and friends) are regenerated by the pipeline, never hand-edited. After any change under lexicon/dictionary/, restart exports/web/server.py on :8000 — the payload is built once at process start.
  - Evidence lifecycle: ambiguity stays representable; candidate never auto-promotes to validated; review is the sole validated writer. No target-language rules in generic code — parameterize by profile/target_lang.
  - Clef protocols only when synthesis or lexicon-audit work actually occurs, and only per AGENTS.md egress rules (local L0/L1 may see the target language; L2/network sees Portuguese only). Clef cannot read pixels.
  - Gotchas: ruff on .sh files emits phantom invalid-syntax errors (never pass .sh to ruff); ruff config resolves per-directory, so run lint from the repo root; eval scripts use var/eval_venv, not the project venv.

STOP CONDITIONS:
  - All agent-actionable cards in review, gate green at final HEAD → write the owner a one-page report (shipped / commits / card states / open owner decisions) and stop.
  - Any card needs >2 failed review rounds → stop looping, get a senior review or ask the owner.
  - Never start #211–#222 before the senior M5 refresh is recorded on the board.
  - Never commit, push, publish, or touch the four OWNER rows.
```
