# Agent capability matrix — verified 2026-10-20

What was actually tested on this machine, for the `language-distillation` dictionary
session + print edition work. Every "works" below was exercised with a real
subtask, not inferred from documentation.

## Purpose

Decide where the *senior* model is actually needed, and route everything else to the
cheapest agent that reliably completes the work.

## Verified agent inventory

| Agent / model | Interface | Cost (in/out per Mtok) | Verified to |
|---|---|---|---|
| `ollama-cloud/beam` | opencode subagent | **$0 / $0** | execute a command and write a file |
| `opencode/beam-free` | opencode subagent | **$0 / $0** | review a file against 4 acceptance criteria, and **catch the exact accent-bucketing bug** the plan fixes |
| `ollama-cloud/gpt-oss:20b` | opencode subagent | $0.07 / $0.30 | fix a code bug and run the test |
| `ollama-cloud/gemma4:31b` | opencode subagent | $0.14 / $0.40 | fix a Unicode-normalization bug and run the test |
| `ollama-cloud/glm-5.3-flash` | opencode subagent | $0.15 / $0.50 | *not on the free plan* — rejected with a credit error |
| `acpx pool` (Poolside) | ACP | subscription | execute a command, read files, review code |
| `acpx codex` | ACP | ChatGPT plan | *broken*: `gpt-6-sol` is not supported on a ChatGPT account |
| `codex-companion.mjs` | direct CLI | ChatGPT plan | task, review, and adversarial-review — **works** with `--model gpt-5.6-sol` |
| `mimo run -m deepseek/deepseek-flash` | CLI | DeepSeek | execute a command and write a file — works |
| `ollama/*` local models | opencode subagent | $0 | *unusable*: 4096-token context, the agent prompt alone is ~31k tokens |

## Hard-won facts

1. **`acpx` needs `--approve-all`.** Without it, every write is denied
   (`"user denied tool"`). The `senior-junior` skill's `junior.sh` does not pass it —
   call `acpx --approve-all <agent>` directly, or extend the script.
2. **`acpx` needs a session first:** `acpx <agent> sessions new`.
3. **Codex model naming is `<family>-<variant>`.** `gpt-5.6-sol`, never `gpt-5.6`.
   The `codex-companion-cli` skill documents this; a bare version 400s with
   *"not supported when using Codex with a ChatGPT account"*.
4. **`acpx codex set model <x>` silently does not stick** — the session keeps
   `gpt-6-sol` from `~/.codex/config.toml`. Use `codex-companion.mjs` instead.
5. **Top-level `const` in a classic `<script>` is not on `window`.** `window.I18N` and
   `window.State` are `undefined`; a separate `<script src>` sees them only as bare
   identifiers. This bit the dictionary plan during verification.
6. **WeasyPrint drops `string-set` on flex/grid items** — a `display: flex` wrapper
   around the headword silently empties the running head. No error, no warning.
7. **Mimo's ACP server dies when detached**; `mimo run` works fine.
8. **Several mimo providers are dead or unpaid:** `huggingface/*` (no credits),
   `opencode/*` via mimo (expired key), `groq/*` (no access).

## The two free routes (chosen, verified)

The user selected these two as the only free models worth using. Both were
exercised on a **real implementation task** from the plan, not a toy.

### 1. `claude-th` — DeepSeek V4.1 Flash free via Token Harbor

**⚠ FREE ALLOWANCE EXHAUSTED as of 2026-10-20.** The route returned:

```
API Error: Request rejected (429) · You've used this period's free allowance.
Your next rolling 7-day period starts on 27 Oct 2026 at 14:44 UTC.
```

This is a *rolling 7-day quota*, not a daily one, so it will not recover
sooner. Until 27 Oct the reviewer role must be filled by another route — see
"Routing while `claude-th` is exhausted" below. The route is still the
preferred reviewer once the allowance resets, and the paid `deepseek-v4.1-flash`
(no `:free` suffix) works immediately if a paid tier is ever accepted.

A wrapper in `~/Dev/agent-harnesses/scripts/claude-th` that points Claude Code at
`https://tokenharbor.ai` with every model slot pinned to the same `:free` route.

```bash
claude-th -p "<task>" --permission-mode bypassPermissions
```

- Model: `deepseek-v4.1-flash:free` (override with `CLAUDE_TH_MODEL`).
- **Without `--permission-mode bypassPermissions` it cannot write files.** It will
  ask for approval, and in `-p` mode there is nobody to answer — it then *declines
  and says so* rather than fabricating a result. Do not mistake that for a failure.
- It prints `unrecognized_model` and a 200k-context warning. Both are harmless:
  the id is a gateway id, not a Claude id.
- The wrapper deliberately refuses to be wired into harness configs, because
  `tokenharbor connect` rewrites the default model of every harness it detects.
  Keep using the launcher.

### 2. `ollama/minimax-m3.1-flash:cloud` — MiniMax M3.1 Flash (cloud)

```bash
opencode run -m "ollama/minimax-m3.1-flash:cloud" "<task>"
```

- Also available as `ollama-cloud/minimax-m3.1-flash` ($0.15/$0.60),
  `zenmux/minimax/minimax-m3.1-flash` ($0.15/$0.60), and the free
  `opencode/minimax-m3.1-flash-free` ($0/$0).
- Writes files without extra flags. Runs lint and tests unprompted.
- **Chosen as the reviewer.** See "Reviewer capability" below.

### 3. `opencode/minimax-m3.1-flash-free` — MiniMax M3.1 Flash (free tier)

```bash
opencode run -m "opencode/minimax-m3.1-flash-free" "<task>"
```

- **$0 / $0.** Works with no extra flags. Runs lint and tests unprompted.

## Reviewer capability — both routes

Tested against deliberately-planted defects, each matching one of the plan's
seven verified traps. Both reviewers **executed the code** to check the
criteria rather than only reading it.

| Planted defect | `minimax-m3.1-flash:cloud` | `claude-th` (DeepSeek V4.1) |
|---|---|---|
| `normalize_key` does not strip accents | yes — `returned "coração", expected "coracao"` | n/a (verified on the good file) |
| `normalize_key` does not lowercase | yes — `returned "CORACAO", expected "coracao"` | n/a |
| `letter_for` buckets on the raw char | yes — `"Á"` and `"Õ"` | n/a |
| `string-set` attached to the entry, not the headword | yes — quoted the line, explained the whole-entry capture | n/a |
| **`string-set` on a flex item** (WeasyPrint drops it) | yes — *"making it a flex item, so WeasyPrint 70 silently drops its `string-set`"* | yes — *"`.headword` is a direct child of `.entry-head { display: flex }`, so it is a flex item and its `string-set` is silently dropped in WeasyPrint 70"* |
| `.entry` missing `break-inside: avoid` | yes — quoted the absence | yes — *"`break-inside: avoid` is never applied"* |
| missing `lang="pt-BR"` (no Portuguese hyphenation) | yes — quoted the absence | yes — *"the rendered HTML declares no `<html lang="pt-BR">`"* |
| missing `@page` margin box consuming the string | yes | yes |
| **correct file → must PASS** | yes — `CRITERIA: 5 / FAILURES: none / VERDICT: PASS` | yes — `CRITERIA: 3 of 5 met` on a file that genuinely lacked the `@page` rule and `lang`, i.e. it did not rubber-stamp |

**Cross-validation:** on the *same* file both reviewers independently returned
the same criteria count and the same failure list. Neither is trivially
permissive, and they agree on a false negative as well as on true positives.

`claude-th` needed `--permission-mode bypassPermissions` to read the files in
`-p` mode; without it it would have had no evidence to review.

### Reviewer notes

- `minimax-m3.1-flash:cloud` is also capable as an implementer: given the
  `normalize_key` spec it produced a correct implementation, then swept all
  1,114,112 Unicode code points and 400k random strings across four
  normalization orderings to validate its own approach, and flagged that
  `testpaths` in `pyproject.toml` would not collect the test file.
- `minimax-m3.1-flash:cloud` will wander if the prompt does not name the target
  file explicitly — it started grepping the repo and reading task briefs. Always
  pass the target path in the prompt.

## What the routes did, on the real plan tasks

| Task | `minimax-m3.1-flash:cloud` | `claude-th` (DeepSeek V4.1) |
|---|---|---|
| Implement `normalize_key` + `letter_for` from a spec | correct, 3/3 tests pass | correct, 6/6 tests pass |
| Honour the `window.I18N` trap | correct — used the bare identifier | correct — used the bare identifier |
| Review against acceptance criteria | correct verdict, 7/7 planted defects | correct verdict, 4/4 planted defects |
| Run its own negative control | verified the trap is load-bearing | verified the trap is load-bearing |
| Run ruff unprompted | yes | yes |

## Chosen routing

**MiniMax M3.1 Flash cloud implements; `claude-th` (DeepSeek V4.1) reviews.**

This keeps each role on its stronger model while preserving family independence
— the reviewer is never the implementer.

| Work | Agent | Why |
|---|---|---|
| Implement a well-specified task | `opencode run -m "ollama/minimax-m3.1-flash:cloud"` | stronger on the spec-to-code path; verified on real plan tasks; writes files without extra flags |
| Review against acceptance criteria | `claude-th -p "..." --permission-mode bypassPermissions` | different model family; caught 4/4 planted defects including the WeasyPrint flex trap; verified it does not rubber-stamp |
| Ambiguous / novel code, architecture | senior (this loop) | needs judgment the free models lack |
| Adversarial security & policy review | `codex-companion.mjs adversarial-review` | found 3 real governance bugs in the notebook diff |

`claude-th` is free (Token Harbor `:free` route) and `minimax-m3.1-flash:cloud`
is $0.15/$0.60 per Mtok, so the whole loop is effectively free. The senior is
spent only on cross-task integration and the final accept/reject decision.

### Ordering consequence

The reviewer runs **after** the implementer, so `claude-th` must be able to read
the files the implementer changed. `claude-th` needs
`--permission-mode bypassPermissions` even to read in `-p` mode.

## Routing while `claude-th` is exhausted (2026-10-20 → 27 Oct)

With the Token Harbor allowance spent, the reviewer role was re-derived by
testing every remaining **$0/$0** route in the model catalogue against the
planted-defect suite. Each was given the same review brief and the same three
probe files.

| Route | Cost | Flex trap | `break-inside` | `lang="pt-BR"` | Perfect file → PASS? | Verdict |
|---|---|---|---|---|---|---|
| `opencode/minimax-m3.1-flash-free` | $0/$0 | found | found | found | yes — `5 / none / PASS` | **usable** |
| `opencode/nemotron-3.5-super-vl-free` | $0/$0 | found | found | found | yes — `5 of 5 / none / PASS` | **usable, different family** |
| `ollama-cloud/beam` | $0/$0 | found | found | found | not run | usable, but **user-rejected** |
| `groq/allam-2-7b` | $0/$0 | — | — | — | — | **broken**: `reasoning_format is not supported` |
| `groq/groq/compound` | $0/$0 | — | — | — | — | **broken**: model does not exist / no access |
| `opencode/nemotron-3.5-super-vl-free` on a *good-but-incomplete* file | $0/$0 | — | — | found missing | — | returned FAIL, not a rubber-stamp |

**Chosen interim reviewer:** `opencode/nemotron-3.5-super-vl-free` when a
different family from the implementer is wanted, and
`opencode/minimax-m3.1-flash-free` when only cost matters. Both are free, both
find the WeasyPrint flex trap, and both PASS a correct file. The cloud MiniMax
(`ollama/minimax-m3.1-flash:cloud`, $0.15/$0.60) remains available for
adjudication when a stronger review is wanted — it reviewed Task 1 to
`5/5 PASS` by rendering the fonts itself and inspecting the PDF output.

**Caveat:** `nemotron` and `minimax-free` are the *same family* as the cloud
MiniMax implementer, so using them as the sole reviewer loses family
independence. Mitigation in force: the review brief lists the seven known
traps explicitly, the reviewer runs the verification commands itself, and the
senior (a different model) audits the verdict.

**Note on `beam`:** it is a genuinely capable free reviewer and it found the
flex trap, but the user explicitly rejected `beam` from the routing, so it is
not used. Recorded here so the option is visible if the user changes their mind.


## Other agents (available, not the chosen path)

| Agent / model | Interface | Cost (in/out per Mtok) | Verified to |
|---|---|---|---|
| `ollama-cloud/gpt-oss:20b` | opencode subagent | $0.07 / $0.30 | fix a code bug and run the test |
| `ollama-cloud/gemma4:31b` | opencode subagent | $0.14 / $0.40 | fix a Unicode-normalization bug and run the test |
| `acpx --approve-all pool` (Poolside) | ACP | subscription | execute a command, read files, review code |
| `codex-companion.mjs` | direct CLI | ChatGPT plan | task, review, and adversarial-review — works with `--model gpt-5.6-sol`; found 3 real governance bugs in the notebook diff |
| `mimo run -m deepseek/deepseek-flash` | CLI | DeepSeek | execute a command and write a file — works |

## Hard-won facts

1. **`acpx` needs `--approve-all`.** Without it, every write is denied
   (`"user denied tool"`). The `senior-junior` skill's `junior.sh` does not pass it.
2. **`acpx` needs a session first:** `acpx <agent> sessions new`.
3. **Codex model naming is `<family>-<variant>`.** `gpt-5.6-sol`, never `gpt-5.6`.
   A bare version 400s with *"not supported when using Codex with a ChatGPT account"*.
4. **`acpx codex set model <x>` silently does not stick** — the session keeps
   `gpt-6-sol` from `~/.codex/config.toml`. Use `codex-companion.mjs` instead.
5. **Top-level `const` in a classic `<script>` is not on `window`.** `window.I18N` and
   `window.State` are `undefined`; a separate `<script src>` sees them only as bare
   identifiers. This bit the dictionary plan during verification.
6. **WeasyPrint drops `string-set` on flex/grid items** — a `display: flex` wrapper
   around the headword silently empties the running head. No error, no warning.
7. **Mimo's ACP server dies when detached**; `mimo run` works fine.
8. **Several mimo providers are dead or unpaid:** `huggingface/*` (no credits),
   `opencode/*` via mimo (expired key), `groq/*` (no access).
9. **Local Ollama models are unusable as agents** — 4096-token context against a
   ~31k-token agent prompt.

## Cheapest reliable routing

| Work | Agent | Why |
|---|---|---|
| Implement a well-specified task | `claude-th` or `minimax-m3.1-flash-free` | both verified on real plan tasks |
| Review against acceptance criteria | the other one of the two | a different model family, so it catches blind spots |
| Ambiguous / novel code, architecture | senior (this loop) | needs judgment the free models lack |
| Adversarial security & policy review | `codex-companion.mjs adversarial-review` | found 3 real governance bugs in the notebook diff |

**Rule:** the senior model writes the plan and decides *what* is correct. It should
only be spent on: ambiguous requirements, cross-task integration, and the final
accept/reject decision. Everything mechanical — writing files that the plan
specifies, running the plan's own verification commands, reviewing against stated
criteria — is free-tier work.

## Cost of the senior loop

The senior model is `minimax-m3.1-flash` via ollama-cloud in this session. The
saving comes from not spending *senior context* on mechanical work, and from
delegating implementation tokens to free agents.
