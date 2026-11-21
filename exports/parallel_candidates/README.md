# Parallel candidates — extracted, **not** promotable yet

This directory holds parallel-text extractions that are structurally sound but fail a
quality gate, so they are deliberately kept out of `exports/harvested_parallel/`. Nothing here
is loaded into the training export: `load_harvested_parallel_sentences()` only globs
`exports/harvested_parallel/*_parallel.jsonl` (`src/langpipe/synthesis/export_dataset.py:30`).
Promote a file by copying it to `exports/harvested_parallel/` **only after** the blocker below
is cleared and a human has reviewed the review-priority rows.

## `cesarino_2013_columns.jsonl`

| | |
|---|---|
| Source | `cesarino_2013_mitologia` — *Quando a Terra Deixou de Falar: Cantos da Mitologia Marubo* (Cesarino, Editora 34, 2013), `var/external/marubo_sources/Cesarino_2013_QuandoATerraDeixouDeFalar_MitolMarubo.pdf` |
| Records | 4,033 line-aligned `mzr` ↔ `por` pairs, 10,497 vernacular tokens, 112 PDF pages within 16–154 |
| Extractor | `scripts/extract_pairs.py columns` (deterministic, offline); PDF pages 25, 72, 106, 123 and 148 are read with `--column-gap-page P=25` because their chant column is indented |
| Locator | `ref = cesarino-2013:p<PDF page>:l<row>`; `qc.printed_line` gives the book's own margin line number when the scan kept it (18.5 % of rows). Adding the five override pages left the earlier 3,951 rows byte-identical, so their locators did not move |
| Register | ritual / shamanic chant — `ritual_restricted` review required (recorded metadata, not a gate: ADR-0025) |
| Status | **candidate** — alignment verified, vernacular orthography incomplete |

### Why the alignment can be trusted

The book prints a narrow chant column beside its Portuguese translation, one row per line, two
book pages per scan. The extractor finds text columns by left-edge clustering, decides which
column is vernacular from *aggregate* stopword evidence (a single line like "Pajé Samaúma" has
no Portuguese function word in it), and then pairs rows by vertical position with a per-column
baseline offset — never by rank, so a missing translation loses one pair instead of shifting
the rest. Verified row-by-row against the page images for PDF pages 26, 46, 67 and 120; the
same 26 rows appear in the same order as the printed page. The 96 rows read from the five
`--column-gap-page` sheets (82 kept, 14 dropped as duplicates) were all checked against 200 dpi
renders: 0 order and 0 pairing failures, one truncated translation (`p148:l1`); log in
`var/artifacts/cesarino_2013/t5_check/qa.json`.

### The blocker: the vernacular lost its nasality marks

The PDF's OCR text layer (Adobe Paper Capture, 2024) drops the Marúbo diacritics completely.
The scan clearly prints them:

| printed (page image) | OCR text layer |
|---|---|
| `Awẽ nimẽaitõ` | `Awe nimeaito` |
| `Ino Sheta Rekẽne` | `Ino Sheta Rekene` |
| `Pani txiwávakĩsho` | `Pani txiwávakisho` |
| `Niro Kaso inĩki` | `Niro Kaso inlki` |
| `Txai mā txai` | `Txai ma txai` |

The book mixes tildes (`ẽ ĩ ã õ`) and macrons (`ā`), and OCR sometimes turns `ĩ` into `l` or
`i`. This is **not** the "mechanical `~`→`ã`, `c;`→`ç` normalisation" the 2026-10 survey
assumed: on the Portuguese side the cedilla survives as a substitute glyph (`~`, `\:`, `<;`,
`c;`), so it can be repaired deterministically; on the Marúbo side the mark is simply absent,
so no rule recovers it. Reconstructing it from another source would be a hypothesis, and
inventing target-language forms is forbidden (AGENTS.md invariant 9).

Measured state of the 4,033 rows (see the extraction report for the reproduction command):

| signal | rows | meaning |
|---|---|---|
| every vernacular token attested as printed in the 15,695-word reference vocabulary (which now includes the clean 2018 *Wenía* pairs), and no Portuguese residual | 761 (18.9 %) | **review first** — best candidates for promotion |
| at least one vernacular token unattested as printed | 3,261 (80.9 %) | chant vocabulary, and/or lost diacritics — needs the clean transcription |
| `l`/`T`/digit artefacts inside vernacular tokens | 176 rows | `ĩ`-damage family, see table above |
| Portuguese residual after repair | 38 rows | mostly `<` read for `d` (`<leve`); `qc.tgt_raw` keeps the raw line |

The Portuguese side was repaired deterministically: 421 repairs (`~`/`\:`/`<;`/`c;` → `ç`,
`çao`→`ção`, `ç6es`→`ções`, footnote superscripts stripped — including spaced (`tias 1`) and
quote-adjacent (`parece”37`) markers). Every applied rule is named in `qc.tgt_repairs` and the
pre-repair line is kept in `qc.tgt_raw`.

### Two corrections to the first pass (2026-10-18, second pass)

1. **A tokenizer bug inflated the damage count.** The word pattern was `[A-Za-zÀ-ÿ]{2,}`, which
   excludes `ẽ ĩ ũ` (U+1EBC/0129/0169 — outside `À-ÿ`), so `postĩno` was counted as two tokens
   `post` + `no` and the fragment `no` was scored as a Portuguese function word. It is now
   `[^\W\d_]{2,}`, the reference vocabulary grew from 13,689 to 15,695 words, and the measured
   state of the vernacular side changed with it (see the table above; the pairs themselves did
   not move).
2. **A clean digital transcription exists — but not of these chants.** The 2018 article
   *Wenía: o surgimento dos antepassados* has a born-digital text layer with the diacritics
   intact; it is a **different** chant of the same cycle (the book's contents are the twelve
   chants listed in its table of contents), so it cannot repair these rows. It is extracted as
   its own clean corpus: `exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl`
   (921 verse rows / 2,401 tokens, `scripts/extract_pairs.py table`).

### What unblocks it

1. A clean digital transcription **of these twelve chants** (the author's own files). The 2018
   *Wenía* article turned out to be a different chant of the cycle, so it does not unblock this
   file — see the correction above. If the author's digital manuscript surfaces, align it to
   these row pairs by page/row locator.
2. Or re-OCR of the page images with an engine whose character set includes `ẽ ĩ ũ ã õ ō`.
   Standard Portuguese OCR models do not, which is why this is a *source* problem, not a
   pipeline problem. A second OCR of this byte-identical file does exist inside DeepSeek's search
   index (snippets keep the nasals as `î`/`ô`), but `POST /v1/tools/fetch` returns 404 for that
   host, so it cannot be pulled as text; the index is worth re-querying if a fetch path appears.
3. Human review of the 761 review-first rows for register clearance.

### Reproduction

```bash
.venv/bin/python scripts/extract_pairs.py columns \
    --pdf var/external/marubo_sources/Cesarino_2013_QuandoATerraDeixouDeFalar_MitolMarubo.pdf \
    --ref-prefix cesarino-2013 \
    --mzr-reference 'var/external/scriptureearth/mzr/*.usfm' \
    --mzr-reference 'exports/harvested_parallel/*_parallel.jsonl' \
    --mzr-reference 'var/external/marubo_vocab/*.tsv' \
    --mzr-reference 'var/external/marubo_sources/academic_lexicon.tsv' \
    --column-gap-page 25=25 --column-gap-page 72=25 --column-gap-page 106=25 \
    --column-gap-page 123=25 --column-gap-page 148=25 \
    --out exports/parallel_candidates/cesarino_2013_columns.jsonl \
    --qa var/artifacts/cesarino_2013/columns_qa.json
.venv/bin/pytest tests/unit/test_extract_pairs.py -q
```

## `cesarino_2013_clean_refs.jsonl`

| | |
|---|---|
| Source rows | the 3,951 rows of `cesarino_2013_columns.jsonl` that predate the five `--column-gap-page` sheets; the 82 rows added from those sheets are not yet covered (copy of `ref`/`src`/`tgt`; `src` is never rewritten) |
| Added fields | `clean_src` (the cited form), `clean_sources` (every cited page), `clean_votes`, `clean_candidates`, `clean_evidence` (`unanimous`/`conflict`), `qc.clean_delta` |
| Records | **867 cited rows: 606 unanimous, 191 conflict, 70 uncorroborated** — 319 add a nasal mark the scan lost, 287 confirm the observed line, 0 resolve a conflict by majority (Villada + Wenía only: 465 rows, 285 / 15 / 165; Villada only: 292 / 285 / 7) |
| Reference | `villada-2018` — Villada Castro, *De dobles y trocas*, *Mundo Amazónico* 9(1) 2018, a **born-digital** PDF quoting the book's *Kaná kawã*, *Rome Owe Romeya* and *Roka* chants with real Unicode diacritics (`quoted-chant`); `cesarino-2008` — the decoded 2008 UFRJ thesis, also `quoted-chant` (see below); `wenia-2018` — `shared-formula` |
| Extractor | `scripts/recover_chant_orthography.py` (deterministic key match, never fuzzy) |
| Status | **hypotheses with citations** — `clean_src` is evidence, not a validated observation; promote only after review |

### Shared-formula citations (Wenía 2018) — candidate run, not published

`--reference-jsonl LABEL:JSONL` adds a second, weaker citation tier: an aligned born-digital JSONL
of a *different* chant that shares formulaic refrain lines with the book (here
`exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl`, label `wenia-2018`). Each
record's `src` is the reference surface; its **locator is the record's `ref` verbatim**
(`cesarino-2018:p38:l21`), never prefixed with the label, which only names the reference set
in the QA report. PDF locators keep the `<label>:p<pdf page>` shape.

| tier | `clean_confidence` | may it originate `clean_src`? |
|---|---|---|
| `--reference` PDF quoting the book's own chant (Villada 2018) | `quoted-chant` | yes |
| `--reference-jsonl` refrain shared with another chant (Wenía 2018) | `shared-formula` | **no** — it only confirms (one more vote) or contradicts (`conflict`) a quoted-chant citation |

When a shared-formula reference is supplied, every record also carries `clean_confidence` (the
tier that originated `clean_src`; `shared-formula` for an `uncorroborated` row; `null` for a
conflict) and `clean_citations` (`[{locator, surface, clean_confidence}]`, every locator,
including those of a conflict). A row cited by shared-formula references alone gets
`clean_evidence: "uncorroborated"` and `clean_src: null`. A quoted-chant-only run keeps the published
**record** schema byte for byte; the QA JSON (`--qa`) always gains two keys, `uncorroborated`
(count) and `quoted_and_shared` (every row cited by both tiers, with its `clean_evidence`).

In the Villada + Wenía run (`var/artifacts/cesarino_2013/clean_refs_t2.jsonl`, QA diff and
page-image verdicts in `var/artifacts/t2/diff.md`), 59 published rows gain shared-formula votes
with the same `clean_src`, 225 keep their values, 165 new rows are `uncorroborated` (0 new
`clean_src`), and 8 published unanimous rows become `conflict`. The 8 conflicts are kept:

- **`Ato aki amaino` ×5** (p30:l18, p103:l2, p107:l18, p139:l20, p146:l10): Wenía prints
  `Atõ aki amaĩnõ` 4 of 7 times and `Ato aki amaĩno`/`Ato aki amaĩnõ` the other 3; the book's
  page image matches Villada (`Atõ aki amaĩnõ`). The conflict is Wenía disagreeing with itself.
- **`Awe rakámaino` ×3** (p46:l22, p78:l38, p103:l6): the published file gives these
  `clean_src: Awẽ rakãmaĩnõ` (Villada), but the book prints `rakámaĩnõ` with an **acute**, so
  the published `clean_src` is itself suspect and these 3 rows **need review**. Wenía's
  `Awe rakamaĩnõ` makes them `conflict` in the tiered run, which is the intended outcome: no
  `clean_src` is cited for them until a reviewer decides.

### What a match means

The OCR key folds case, every combining mark, and the scan's three nasal stand-ins
(`z`/`l`/`T` → `i`: the scan prints `Koz` for `Koĩ`, `Chz` for `Chĩ`, `inlki` for `inĩki`;
Marúbo has no /l/ or /z/). A row matches when its **whole** token sequence occurs contiguously,
with those letters, in the reference. The reference's own surface form is then the citation:

```
observed (scan)      clean_src (citation)   cited page        printed page image
Ato aki amaino   →   Atõ aki amaĩnõ         villada-2018:p8    verified: Atõ aki amaĩnõ
Awe aki amaino   →   Awẽ aki amaĩnõ         villada-2018:p10   verified: Awẽ aki amaĩnõ
```

All 285 `clean_src` surfaces occur **verbatim on a cited page** of the reference PDF (checked
programmatically) and two were checked against the book's own page images. That is not the same
as matching the 2013 print: in a 10-crop sample for the T3 review packet, 3 printed lines did not
match their cited form (p93:l10 `Awe anõ nĩkã` vs `Awẽ…`; p102:l42 `Awẽ aki amãino` vs
`amaĩnõ`; p53:l10 `Ẽta neskai!` vs `Eta neskái`). Two of those are published nasal-added rows.
Treat every `clean_src` as a citation to review against the crop, not as verified print. The
review packet is `var/artifacts/cesarino_2013/review/` (built by `scripts/build_clean_ref_review.py`).
When the reference
prints the same letter sequence with different marks in different places, the row is kept with
`clean_src: null` and the `clean_candidates` listed — the conflict is reported, never voted away
(e.g. `Shokó Naí Shavaya` / `Shokô naí shavaya`).

### Reproduction

The committed file is the three-reference run (Villada + Wenía + the decoded thesis):

```bash
.venv/bin/python scripts/recover_chant_orthography.py \
    --candidates exports/parallel_candidates/cesarino_2013_columns.jsonl \
    --reference villada-2018:var/external/villada_2018/villada_2018.pdf \
    --reference-jsonl wenia-2018:exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl \
    --reference-text cesarino-2008:var/artifacts/cesarino_2008_thesis/decoded.txt \
    --out exports/parallel_candidates/cesarino_2013_clean_refs.jsonl \
    --qa var/artifacts/cesarino_2013/clean_refs_qa.json
.venv/bin/pytest tests/unit/test_recover_chant_orthography.py -q
```

`decoded.txt` is rebuilt from the raw PDF by `scripts/cesarino_pua_decode.py`. Drop the
`--reference-text` line to get the previous (Villada + Wenía) 465-row file; drop `--reference-jsonl`
too for the Villada-only run.

### The 2008 thesis (`--reference-text`) — third citation reference

Cesarino's 2008 UFRJ doctorate (*Oniska*, Museu Nacional) is born-digital and quotes the same
chants as the 2013 book, so it is a `quoted-chant` reference (it may originate `clean_src`).
Its font stores nasal marks as private-use glyph slots (U+F017/F018/F01C); `scripts/cesarino_pua_decode.py`
maps them to U+0303 and writes `var/artifacts/cesarino_2008_thesis/decoded.txt` (pages marked
`=== page N ===`). `--reference-text LABEL:PATH` reads that file; the locator is
`cesarino-2008:p<page>`.

| measure | Villada + Wenía | + thesis |
|---|---|---|
| cited rows | 465 | 867 |
| unanimous (`clean_src` set) | 285 | 606 |
| conflict | 15 | 191 |
| uncorroborated (`clean_src` null) | 165 | 70 |
| nasal marks added / confirm observed | 164 / 121 | 319 / 287 |

333 rows gain a `clean_src` from the thesis alone, 82 `uncorroborated` rows are resolved by it,
115 rows are cited by both Villada and the thesis with the same form, and 94 previously
unanimous rows (+13 uncorroborated) become `conflict`: the thesis prints the same refrain with
varying marks (`awẽ aki amaĩnõ` p387 vs `awẽ aki amainõ` p409; `awe iki amaĩnõ` p402 vs
`awẽ iki amaĩno`). Page images show the decoder is faithful and the thesis is internally
inconsistent; against the 2013 book the thesis was right in 2 of 6 checked conflicts and
Villada in 4 of 6, so no vote is taken. Details: `var/artifacts/t1/diff.md`,
`var/artifacts/t1/image_check.md`.

### Conflict reads (`cesarino_2013_conflict_reads.jsonl`) — evidence for the 191 conflicts

One JSON line per `clean_evidence: conflict` row of `cesarino_2013_clean_refs.jsonl` (191, sorted
by `ref`): which candidate spelling two free vision readers saw in the printed 2013 book line.
**Evidence only.** `clean_src` is always `null`, `src` and `clean_src` in the clean-refs file are
untouched, and promotion stays an explicit `langpipe review decide` step by the owner.

| field | meaning |
|---|---|
| `ref`, `candidates` | row ref and its `clean_candidates` (a pick is an index into them) |
| `status` | `agreed` both readers picked the same candidate; `disputed` both read it but disagree, or one gave NONE/empty; `unread` fewer than two readers read it |
| `print_spelling` | the candidate both readers picked (`agreed` only), else `null` |
| `readers` | `[{name, pick, conf}]`; `pick` `-1` = none of the candidates, `empty: true` = no parseable answer, optional `printed` form |
| `claude_audit` | `{sonnet, haiku, agree}` earlier Claude reads when known (all `agreed` rows and the `disputed` ones), else `null` |
| `crop` | repo-relative 200 dpi review crop (local `var/`, not committed) |
| `method`, `benchmark`, `clean_src` | `free-reader pick, tight 300 dpi crop; accepted on two-reader agreement`; `var/artifacts/row_adjudication_probe/reader_benchmark.md` (local only); `null` |

Counts: **163 agreed, 11 disputed, 17 unread** (191). The 11 disputed are listed for the owner;
no reader named a printed form that matches no candidate, so none carries a `printed` string. The
17 unread rows (idx 23, 29, 30, 44, 51, 77, 84, 102, 131, 134, 136, 139, 148, 149, 160, 187, 190
of the worklist) are the contested ones the readers could not reach before the OpenCode
free tier blocked the IP; resume procedure in `.skills/row-adjudication/SKILL.md`.

Readers: `opencode/glm-5.3-flash-free` (`glm`) and `opencode/mimo-v2.6-flash-free` (`mimo`), tight
300 dpi crop of the source-column line, prompt "which candidate matches mark for mark, letter or
NONE". Benchmark on the 174 rows where two Claude reads (Sonnet, Haiku) agreed: single reader
97.1% (glm) and 96.6% (mimo); **100% precision on the 163 rows where both free readers agree**
(all 163 equal both Claude reads), coverage 163/174 = 93.7%. **Caveat:** the gold is two Claude
reads agreeing, a proxy and not ground truth, so 100% means "matches Claude's reads", not "matches
the page". Majority vote is never used: a disagreement stays a disagreement.

Regenerate (needs the local probe outputs, which are not committed):

```bash
.venv/bin/python scripts/build_conflict_reads.py \
  --refs exports/parallel_candidates/cesarino_2013_clean_refs.jsonl \
  --reads-dir var/artifacts/row_adjudication_probe \
  --out exports/parallel_candidates/cesarino_2013_conflict_reads.jsonl
```

The script fails loudly if the worklist refs or candidates drift from the clean-refs file, if a
pick index is out of range, or if the status counts disagree with `conflicts_compare_free.json`.
