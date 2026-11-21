# Implementation handoff — dictionary session + print edition

**Read this first after compaction.** It is the durable state; the plan on disk is the
detail. Nothing here depends on conversation history.

## Objective

Build, in `/home/luandro/Dev/AI/language-distillation`:

- **A. Dictionary session** — a new top-level `Dicionário` tab in the portal at
  `http://localhost:8000`: ranked diacritic-insensitive search, A–Z browse, POS/domain/
  evidence facets, a Simple/Expert evidence toggle, and a print button.
- **B. Print edition** — the whole dictionary typeset as a PDF (WeasyPrint 70, Charis
  SIL, guide words, numbered bibliography, front/back matter).

## Authoritative documents (on disk)

| Document | What it is |
|---|---|
| `docs/superpowers/specs/2026-10-20-dictionary-session-and-print-edition-design.md` | the approved design (8 locked decisions) |
| `docs/superpowers/plans/2026-10-20-dictionary-session-and-print-edition.md` | the implementation plan: 11 tasks, 73 steps, full code in every step |
| `docs/research/agent-capability-matrix-2026-10.md` | which agents to use, verified |
| `docs/research/dictionary-print-prior-art-2026-10.md` | (to be written in Task 10) |

**The plan contains complete, verified code for every task.** For *that*
session's own tasks an implementer needs the plan file and nothing else. This is
not authority over later work packages: M5 scheduling and verification follow
`docs/implementation/M5-PLAN.md` and the AGENTS.md contract-first rules; do not
re-derive the dictionary design, and do not treat plan snippets as living
contracts.

## Decisions already made — do not relitigate

| # | Decision |
|---|---|
| D1 | Full scholarly PDF: headword, POS, gloss, domain, 1 attested example + citation, status marker, guide words, A–Z index, numbered bibliography, front matter, domain index |
| D2 | New top-level `Dicionário` tab, default landing tab, separate from the 5 LKB workspaces |
| D3 | Simple by default, Expert toggle (global, persisted, `?expert=1`) |
| D4 | One builder (`DictionarySessionBuilder`), two renderers (web + print) |
| D5 | WeasyPrint 70. Typst and LaTeX documented as alternatives in ADR-0027 |
| D6 | Charis SIL 7.000 for all print text. Newsreader banned (no IPA) |
| D7 | One canonical `Dicionário Imprimível` card offering both HTML and PDF |
| D8 | `weasyprint` is a **core** dependency, imported lazily inside functions |

## Task order (11 tasks, 73 steps)

1. Vendor Charis SIL webfonts into `assets/fonts/`
2. `DictionarySessionBuilder` — `src/langpipe/lexicon/dictionary/session.py`
3. Rewrite the print template — `src/langpipe/lexicon/exporters/printable.py`
4. WeasyPrint driver — `src/langpipe/lexicon/exporters/pdf.py` (+ `uv add weasyprint`)
5. Wire the PDF into `export_all_formats`
6. Server endpoints + fix the 404 artifact links — `exports/web/server.py`
7. The `Dicionário` tab: markup, CSS, i18n — `exports/web/index.html`
8. `exports/web/dictionary.js` — search, browse, facets, entry rendering
9. Fix the Exports tab links + add the print card
10. ADR-0027 + prior-art report + docs
11. End-to-end verification + `tsk` board entry

## Execution model (verified, cheap)

Two routes, both confirmed working on real implementation and review tasks.

### Implementer — MiniMax M3.1 Flash cloud

```bash
opencode run -m "ollama/minimax-m3.1-flash:cloud" "<task>"
```

- $0.15/$0.60 per Mtok. Writes files without extra flags. Runs lint and tests
  unprompted.
- **Always name the target file(s) in the prompt.** Given an open-ended prompt it
  will start grepping the repo and reading unrelated briefs.
- It implements well: given the `normalize_key` spec it produced a correct result
  *and* swept all 1,114,112 Unicode code points to validate its own approach.
- On a review task it found **7/7** planted defects, including the WeasyPrint
  `string-set`-on-a-flex-item trap that Task 3 is built around. It executes the
  code to check criteria rather than only reading it.

### Reviewer — DeepSeek V4.1 Flash free via Token Harbor

```bash
claude-th -p "<review brief>" --permission-mode bypassPermissions
```

- Model `deepseek-v4.1-flash:free`. Free. Key is present.
- **Without `--permission-mode bypassPermissions` it cannot read files** in `-p`
  mode, so it would have no evidence to review. With the flag it catches **4/4**
  planted defects, including the flex trap, and it does **not** rubber-stamp: on
  a file that genuinely lacked the `@page` rule and `lang`, it returned FAIL.
- On the *same* file as the MiniMax reviewer, both independently returned the
  same criteria count and the same failure list. They agree on true positives
  and on a false negative.
- Prints an `unrecognized_model` warning — harmless, the id is a gateway id.

> **⚠ UNAVAILABLE 2026-10-20 → 27 Oct 2026.** The Token Harbor free allowance is
> exhausted (429, *rolling 7-day* quota). Use the interim reviewer below.

### Interim reviewer (while `claude-th` is exhausted)

```bash
opencode run -m "opencode/nemotron-3.5-super-vl-free" "<review brief>"   # different family
opencode run -m "opencode/minimax-m3.1-flash-free"  "<review brief>"    # cheapest
```

Both are $0/$0. Both were tested against the planted-defect suite: each finds
the WeasyPrint flex trap, the missing `break-inside: avoid`, and the missing
`lang="pt-BR"`, **and each returns PASS on a correct file** — so neither
rubber-stamps. `nemotron` also returned FAIL on a good-but-incomplete file.

`groq/allam-2-7b` and `groq/groq/compound` are broken (unsupported
`reasoning_format`; model not found). `ollama-cloud/beam` works but the user
rejected it from the routing.

**Independence caveat:** these are the same model family as the implementer. The
mitigations are that the review brief names the seven traps explicitly, the
reviewer re-runs the verification commands itself, and the senior (a different
model) audits the verdict.

### The loop

```
for task in 1..10:
    brief    = var/task-briefs/task-NN-*.md
    implement → opencode run -m "ollama/minimax-m3.1-flash:cloud" "<brief>"
    review    → opencode run -m "opencode/nemotron-3.5-super-vl-free" \
                "$(cat var/task-briefs/task-NN-REVIEW.md)"
    if the review returns VERDICT: FAIL → write the failures to a file and
      re-run the implementer with them; then re-review
task 11 → senior adjudicates the final accept/reject
```

The senior is spent only on cross-task integration and the final verdict.

Full evidence: `docs/research/agent-capability-matrix-2026-10.md`.

## The seven verified defects — the highest-value content to carry forward

These were found by *running* the plan's code, not by reading it. Each is a trap a
fresh implementer will otherwise hit.

1. **A flex container on the headword silently empties WeasyPrint's running head.**
   WeasyPrint 70 does not evaluate `string-set` on flex/grid items. The `.entry-head`
   row must use inline flow with `margin-left` spacing, **not** `display: flex`.
2. **`string-set` belongs on `.headword`, not on the block-level `.entry`.**
   `content(text)` on `.entry` captures the whole entry (headword + gloss + example).
3. **Top-level `const` in a classic `<script>` is NOT on `window`.** `window.I18N` and
   `window.State` are `undefined`. A separate `<script src>` sees them only as **bare
   identifiers**. Use `typeof I18N !== 'undefined' && I18N[State.locale]`, never
   `window.I18N`. Verified in headless Chrome: the wrong form leaks raw `noun`
   instead of `subst`.
4. **Write the combining-mark regex with explicit escapes:** `/[\u0300-\u036f]/g`.
   A literal `U+0300`–`U+036F` range is invisible in Markdown and gets mangled,
   producing `Invalid regular expression: Range out of order in character class`.
5. **Cut the `ex:` tail BEFORE splitting on `;`.** Provenance strings look like
   `Costa (2000b, 2002); ex: kiya-rantsha (avião; lit. barco longo)` — the example tail
   has its own semicolons. Splitting first leaks 5 spurious works into the
   bibliography. Correct order gives 14 real works, not 18.
6. **The formats route maps `/formats/<lang>/<rest>` to `exports/<lang>/formats/<rest>`.**
   The CLDF URL is `/formats/mzr/cldf/Dictionary-metadata.json`, **not**
   `/formats/mzr/formats/cldf/...` — the latter 404s.
7. **Letter bucketing must use the normalized key.** `headword[0].upper()` files `á`
   under `Á` (the pre-existing bug at `printable.py:50`). Use the normalized key so
   `á`→`A`, `õpo`→`O`, `ẽa`→`E`.
8. **Every glyph the template emits must exist in Charis SIL 7.000.** Charis has
   *no triangle at all*. The plan's template used `△` (U+25B3) for the candidate
   evidence marker; WeasyPrint silently substituted **DejaVu Serif**, so the print
   edition became a two-typeface book. The defect is invisible in the HTML and
   only shows up in `pdffonts` on the rendered PDF. Now `◊` (U+25CA LOZENGE).
   Note `U+2206` is *not* a usable substitute: Charis maps it to a **sigma (Σ)**,
   not a triangle. There is a regression test for this.

## Measured performance envelope

| Configuration | Time | Pages |
|---|---|---|
| Previous export (Newsreader, per-entry citation blocks) | ~80 s | 43 |
| **Plan's template: 1 example/entry + `hyphens: auto`** | **~49 s** | **60** |
| Same, 2 examples/entry | ~2 m 15 s | 95 |
| Same, no example blocks | ~12 s | 48 |

The example blocks dominate the cost, not the fonts. Keep **one** example per entry
and `hyphens: auto` on `.gloss` and `.example`; keep `break-inside: avoid` on `.entry`
(removing it is faster but splits entries across columns); keep the per-letter
`.entries-columns` containers (flattening them breaks the letter-heading layout).

## Data facts (measured against the live export)

- `exports/mzr/dictionary.json` — 1099 entries. `dictionary.clean.json` — 892.
  `dictionary.reverse.json` — 714 contact headwords.
- Clean view: 748 `supported`, 144 `validated`. 815 noun / 52 verb / 17 adj / 3 pron /
  2 adv / 2 num / 1 verb_intransitive.
- Letter buckets under the normalized key: `A C E H I K M N O P R S T U V W Y` (17).
- `example`/`trans` are **derived from `citations[0]`** (100% of 990 entries). Not
  independent data. Every entry has 2 citations with different `source_ref`s.
- `audit.related_entry` on 63 entries (inflected form → lemma).
- Bibliography: **14** distinct works, `Costa (2002)` first with 50 entries.
- Morphology: 12 morphemes. Parallel sentences: 8.
- **No audio files and no IPA in the data.** The orthography uses `ẽ ĩ ã õ`. This is a
  data gap, not a missing feature — do not build a pronunciation or audio UI.

## Bugs being fixed in passing (both verified live)

- The Exports tab's three download links all returned **404** because the server's
  static root was `exports/web/` while the artifacts live in `exports/<lang>/formats/`.
- `printable.py:50` bucketed letters with `hw[0].upper()`.

## Task progress

| Task | Status | Notes |
|---|---|---|
| 1. Charis SIL fonts | **done** | commit `eec3fa4`. 3 × woff2 + OFL licence. Verified: 28/28 codepoints in all 3 faces, `smcp` present, cmap+outlines byte-equivalent to the upstream TTFs, and WeasyPrint embeds them (3 subsets) with the Marúbo orthography round-tripping through `pdftotext`. Reviewer: 5/5 PASS. |
| 2. `DictionarySessionBuilder` | **done** | commit `8d26eb6`. 24 tests pass. Real export: 892 entries, letters `ACEHIKMNOPRSTUVWY`, 14 bibliography works with `Costa (2002)` first (50 entries), facets 815 noun / 748 supported / 144 validated — all matching the plan exactly. Reviewer: 24/24 PASS. |
| 3. Print template v2 | **done** | commits `e957136` + `65b2af0`. Rendered PDF: 61 pages A4, **only Charis faces embedded**, guide words present on every page, 23 PDF bookmarks (4 sections + 17 letters, nested). Fixed the plan's `△` glyph defect (see defect 8). Reviewer: 3/3 then 6/6 PASS. |
| 4. WeasyPrint driver | **done** | commit `a8dad54`. `weasyprint>=70,<71` is a **core** dep; imported lazily inside `render_pdf` (verified: `weasyprint` absent from `sys.modules` after `import langpipe.lexicon.exporters`, and `PdfToolchainUnavailable` is raised when the import is blocked). Render **31–36 s / 61 pages**. No network at render time — zero `http(s)://` refs, fonts relative `url('fonts/…')`. Reviewer: 8/8 PASS. |
| 5. Wire PDF into `export_all_formats` | **done** | commits `ff989f1` + `e979442`. The plan's `REPO_ROOT` was **one level too high** (`parent.parent.parent.parent` → `src/`, so `_fonts_dir()` returned `None` and the fonts were never staged); corrected to `parents[4]`. The PDF step is best-effort but now **logs** the failure instead of swallowing it. `exports/**/fonts/` is gitignored (derived copies; canonical faces in `assets/fonts/`). The PDF is committed and **byte-reproducible**. Reviewer: 6/6 PASS. |
| 6. Server endpoints + 404 fix | **done** | commit `36ea091`. `GET /api/dictionary/session` (892 entries + 714 reverse, cached, 30 ms warm vs ~1 s cold, invalidated on source mtime), `POST /api/dictionary/print` (returns **URL paths**, `entries` 892, `pages` 61), and `GET /formats/<lang>/<rest>`. The three Exports-tab 404s now return 200. Traversal guard verified against **10** adversarial payloads (all 404, never 500). Reviewer: 8/8 PASS. |
| 7. `Dicionário` tab markup/CSS/i18n | **done** | commit `47534b6`. All 15 IDs present, 70 IDs total, no duplicates; 16 i18n keys in both `pt` and `en`; dictionary is the first nav tab and the default landing pane. The plan's unguarded `DictionaryUI.activate()` was a **real bug** — `dictionary.js` does not exist until Task 8, so the `ReferenceError` aborted the whole `DOMContentLoaded` handler and killed the portal. Now guarded with `typeof`. Verified in headless Chrome: no JS errors beyond a pre-existing SVG `polyline` bug at the exports icon. Reviewer: 8/8 PASS. |
| 8. `dictionary.js` | **done** | commits `2230957` + `6b58f6b`. 562 lines. Verified live in headless Chrome: 17 letter buttons + ALL, 22 facet chips, 300 result rows with the count label showing the true **892 / 892**, the reading pane with headword/`subst`/gloss/two attestations with citations, the gold status border, and the Expert provenance panel. The `window.I18N` trap is avoided (bare identifiers + `typeof`); `POS_TRANSLATED=true RAW_LEAKED=false`. Search is diacritic-insensitive: `nuke`→`nukẽ`, `westise`→`wẽstisẽ`, `coracoes`→`corações`. Fixed: facet chips showed raw tokens (`noun`, `universe_nature`) while the reading pane showed `subst`/curated domain names. Reviewer: 7/7 PASS. |
| 9. Exports tab links + print card | **done** | commits `221d9b0` + `8e9e8de`. All four `/formats/mzr/...` links return **200** (the three 404s are gone). The print-edition card offers both the HTML and the PDF. The portal console is now **completely clean** — the stray `predators` in an SVG `polyline` attribute (a pre-existing error on every page load since before this work) is fixed. `printEditionSize` now shows the real **340 KB** instead of a permanent em dash. Reviewer: 10/10 PASS. |
| 10. ADR-0027 + prior-art report | **done** | commit `01bb78d`. `docs/adr/0027-dictionary-rendering-and-print-pipeline.md` (198 lines) + `docs/research/dictionary-print-prior-art-2026-10.md` (216 lines) + index row + `exports/README.md` section. The implementer **corrected three stale claims** rather than transcribing them: the D4 CSS now shows `string-set` on `.headword` (the brief had it on `.entry`), D7 records that the PDF **is** committed and byte-reproducible, and the "269 of 271 IPA codepoints" figure was replaced with a measured one (Charis 368/368, TeX Gyre Pagella 12/368 — independently confirmed by me). Two dead URLs in the brief were found and repaired. Reviewer: PASS. |
| 11. End-to-end verification + `tsk` | **done** | senior-verified. Regeneration byte-identical; all 9 endpoints 200; traversal still blocked; CDP-driven UI test: 300 results, `892 / 892`, `nuke`→`nukẽ`, `westise`→`wẽstisẽ`, `coracoes`→`chinãrasĩ`, reverse `abacaxi`→`kanka`, expert panel with 9 fields persisted to `localStorage`, letter K = 66/892, facet verbo = 6/892, **0 JS errors, 0 console errors**. Full suite: **1895 passed, 531 skipped, 1 failed** (the pre-existing `test_language_isolation`, none of whose 4 offenders are our files). `tsk` **#268** set to `review`. |

## Final state

- **Branch** `main`. Confirm the head with `git log --oneline -1` rather than trusting
  this line. The follow-up session ended with the dictionary cluster in `70cfbf7` and the
  two-tier CI gate in `0c504b1`; this document is the commit after those.
- The portal runs on port 8000 from `exports/web/server.py`. The `Dicionário` tab is the
  default landing surface. **It must be restarted** to pick up changes to
  `lexicon/dictionary/session.py`: the payload is built once at process start.
- The print edition is `exports/mzr/formats/dictionary_mzr_printable.pdf` — 61 A4 pages,
  only Charis faces embedded, guide words on every page, 23 PDF bookmarks, a generated
  evidence legend, and byte-reproducible from `export_all_formats("mzr", view="clean")`
  (three runs, identical sha).
- `tests/unit/languages/test_language_isolation.py` **passes** now (ADR-0028 moved the
  corpus data to the language profile); the allowlist was not extended.
- Full suite, **with the database up**: **2686 passed, 1 skipped, 0 failed**. Getting
  there needs the *system* Docker daemon: `DOCKER_HOST` is pinned to
  `unix:///run/user/1000/docker.sock`, whose rootless daemon is in a failed state, while
  `docker.service` (system) is healthy and the user is in the `docker` group. So run
  `DOCKER_HOST=unix:///var/run/docker.sock docker compose up -d --wait db` and migrate
  before the suite; otherwise 676 tests skip and the run looks greener than it is.
- Without the database, the same suite reports 2010 passed / 677 skipped. Treat that as
  "the non-DB half is green", never as a full pass.
- The one remaining skip is `test_scorer_matches_sacrebleu_corpus_score`, which
  `pytest.importorskip`s `sacrebleu` — a tool used only by `var/eval_venv` and the eval
  scripts, and declared nowhere in `pyproject.toml`. Because
  `LANGPIPE_REQUIRE_POSTGRES=1` turns *any* skip into a failure
  (`tests/fixtures/db.py:71-78`, pinned by `test_db_fixture_policy.py`), `scripts/ci.sh`
  cannot pass until that dependency question is settled (tsk #277).
  **Settled in `bf81f82`**: `sacrebleu>=2.4` is now in the `dev` group, the parity test
  runs instead of opting out, and the gate condition yields 2687 passed / 0 skipped /
  exit 0. `scripts/ci.sh` has since been executed end to end for the first time in this
  environment — `CI_EXIT=0`, 2687 passed, 41 deselected, 26:25 — so `#277` needs no
  further agent work; the card sits in `review` for the owner to close.

**Plan correction from Task 1:** the plan's Step 3 said the licence file should
begin with `SIL OPEN FONT LICENSE Version 1.1`. It does not — both the release's
`OFL.txt` and the canonical OFL start with a copyright header, and the banner is
around line 10. The plan has been corrected. The implementer was right to flag
this and to keep the release copy (it carries the real copyright holder and the
Reserved Font Names).

## Working rules for this repo

- Use `.venv/bin/python` (bare `python3` fails: pyenv 3.12 not installed).
- **Never** use `rm` for cleanup in the repo; `AGENTS.md` forbids destructive commands.
- `exports/mzr/dictionary*.json` are canonical — never hand-edit them.
- Evidence-first: `status` is never silently upgraded; `candidate` never reads as
  `validated`. Preserve ambiguity (multiple glosses, multiple citations).
- No Marúbo-specific rules in generic pipeline code — parameterize by `target_lang`.
- The print path must fetch **nothing** from the network: fonts are self-hosted.
- Every derived artifact keeps lineage; new persisted format → tests + docs.
- Line length 100 (ruff). `extend-exclude = ["*.md"]`.
- Use XERJ (`xerj search`, `xerj def`) to explore; cite `file:line`.
- Track work on the `tsk` board, project `/home/luandro/Dev/AI/language-distillation`.
  Set `review` when done; only the owner sets `done`.

## Open items — start here next session

`#268` and everything split out of it are done: `#269`, `#270`, `#271`, `#273`,
`#277` and the pre-existing `#204` are all in `review` (only the owner sets
`done`). Still `open`: `#272` (tunnel), `#275` (CLDF `access_class` reuse),
`#276` (regenerate one committed report). Boards are the state; this section
only explains *why* each card exists and what was actually shipped.

| Card | State | What to know |
|---|---|---|
| `#269` | review, `d05d641` | Was: `dictionary.js` sliced to 300 rows while reporting 892. Now real paging (`PAGE_SIZE=300`, `state.visible`, `renderPaging`, `showMore`, `revealIndex`), counter "Showing N of M", control self-hides at the end, search resets the window, locale switch preserves it. Re-verified after the forms work: 300 → 600 → 892, 0 console errors. |
| `#270` | review, `70cfbf7` | The card premise was **wrong twice**. The export *does* record a basis — all 144 `validated` entries name a real source, which `EVIDENCE-AND-CONFIDENCE.md:46-50` accepts. The real defect was reader-facing: the label read "Validado (Padrão-Ouro)" and print printed ✓ with no legend. Now `validation_basis` per entry (748 `corpus_only` / 36 `source_and_corpus` / 108 `source_assertion`), label "Validado por fonte publicada", and a generated print legend stating the mark is not human review. |
| `#271` | review, `70cfbf7` | Also a **wrong premise**: `related_entry` is not a join key. 63 form rows → 58 distinct bases, **none** matching a published lemma (only 22 hit a `proper_noun`, which `clean` excludes); the bases are gloss-side names (`berequias`, `cafarnaum`, `camelo`). Shipped: attach-by-normalized-base across homographs, a session `form_index` with `lemma: null` for orphans (63 search-only surfaces today), forms never headwords. **0 forms attach with current data** — a data gap, recorded in ADR-0027 D9. |
| `#272` | open | The quick tunnel is unauthenticated, gets a new URL per restart, exposes all five workspaces, and its helper lives in `/tmp`. Wants a named tunnel + Cloudflare Access + a systemd user unit. |
| `#273` | review, `22c2fca` + `d6d3230` + `0c504b1` | All three debts closed: `mypy src` clean over 187 files; the language-isolation test passes with an unchanged allowlist (ADR-0028); `scripts/ci.sh` now has a **two-tier** lint gate — blocking `ruff check src tests` + `ruff format --check src tests`, non-blocking report over the rest so notebooks 69 / scripts 42 / ops 17 / deploy 7 stay visible without blocking commits. |
| `#275` | open | CLDF reuse does not re-derive `access_class`, so a policy edit reuses stale files. |
| `#276` | open | `exports/mzr/datasets/derived_rows_audit.json` is committed and its `policy` prose still names Marúbo; regenerating it now shows a prose-only diff. Needs a deliberate export run. |
| `#277` | review, `bf81f82` | `scripts/ci.sh` could never pass: in required mode *any* skip is fatal, and the one skip was `importorskip("sacrebleu")` on a package declared nowhere. Declared in the `dev` group; the parity test now runs (and passes — our BLEU/chrF match sacrebleu 2.6.0), and the whole gate completed end to end once: `CI_EXIT=0`, 2687 passed, 0 skipped, 26:25. |

Pre-existing and untouched by this work: `#175` (Milestone 3 Realdata Gate,
blocked on operator inputs, not code) and the M5 chain `#210` → `#211…#222`,
which is the actual roadmap.

**Restart the portal after touching `lexicon/dictionary/session.py`.** `server.py`
builds the session payload once at process start, so a running process keeps
serving the old shape while the static JS on disk is already new — this is how a
pre-forms payload was served to a browser that had the forms code.

**Rebuild the print edition** (`~31-43 s`):
`.venv/bin/python -c "from langpipe.lexicon.exporters import export_all_formats; export_all_formats('mzr', view='clean')"`.
It is byte-reproducible; `exports/**/fonts/` is gitignored and regenerated.

**Tunnel helper** (if the URL dies): `/tmp/opencode/tunnel/start-tunnel.sh` — now uses
`--protocol http2`, because QUIC failed 518× after the host picked up ZeroTier/cellular
interfaces. It prints a new URL; `/tmp` does not survive a reboot, which is `#272`.

## Starting state (historical — the repo at the top of this work, not now)

- Branch `main`, HEAD `fb0d23f` (`docs(research): verified agent capability matrix`).
- Working tree: only pre-existing modifications (the NMT notebook and two untracked
  text files) — **not** from this work.
- The portal server is running on port 8000 from `exports/web/server.py`.
- `weasyprint` is installed in `.venv` but **not yet added to `pyproject.toml`** —
  Task 4 Step 1 does that.
