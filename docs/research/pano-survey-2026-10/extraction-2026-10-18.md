# Extraction report — Vaná rasĩ, Smith 2021, Cesarino 2013 and Wenía 2018 (2026-10-18)

Three newly found Marúbo sources were acquired, registered in the governed store, verified, and
extracted. A fourth extraction (Cesarino 2013, already in the repository) was run in the same pass
and exposed a correction to the plan (§2.4). §2.5 records the acquisition that the correction
pointed at: the 2018 *Wenía* article, a **born-digital** chant text whose diacritics are intact.
This report records what was produced, what was **not** produced and why, and what a reviewer must
check before any of it is promoted.

## 1. Sources acquired and registered

| Key | Title | Raw file (immutable) | SHA-256 | Registered |
|---|---|---|---|---|
| `vana-rasi` | *Vaná rasĩ — As plantas que cultivamos na roça* (CTI, 1. ed. 2024, 51 pp., ISBN 978-85-60028-22-1) | `var/external/vana_rasi/vana_rasi.pdf` | `6b06cb2b…eceec1c` | `src_01M58173H25H70ZA0PAFBTAAB5` |
| `smith-2021-twu` | Smith, *Aspects of Switch Reference in Marubo* (TWU MA, 2021, 114 pp.) | `var/external/smith_2021_twu/smith_2021_twu.pdf` | `dded03b4…1d396911` | `src_01M58179MD0NMZ6B3J0TJNCZ3S` |
| `wenia-2018` | Cesarino, *Wenía: o surgimento dos antepassados* (*Estudos de Literatura Brasileira Contemporânea* 53, 2018, pp. 45–99, DOI 10.1590/2316-4018533) | `var/external/wenia_2018/wenia_2018.pdf` | `a3661ae5…4dfab767` | `src_01M5866N90VRTA9RAC6BJ2V51H` |

Each directory carries `SOURCE.md` (provenance, rights holder, licence, URL, acquisition date),
`langpipe-manifest.yaml` (valid `SourceManifest`, `manifest_version: 1`) and `policy.yaml`
(`direct` / `public`; licence recorded as metadata, not a gate — ADR-0025). `wenia-2018` was
acquired in a later pass (§2.5) and follows the same layout.

Governed pipeline run per source (`source add` → `source ingest` → `source verify`):

- `vana-rasi`: registration run `run_01M58173GNCS276K4HR6XXMVR8`, ingest run
  `run_01M5817BBCBFYV075N1T7PRFFS`, object `sobj_01M58173H25H70ZA0PAFBTAAB6`,
  verification `status=ok`, blob SHA-256 matches the recorded hash.
- `smith-2021-twu`: registration run `run_01M58179KZF1A1JCCGRHMXTQDA`, ingest run
  `run_01M5817KV8R2JKAG0W1F1CQH06`, object `sobj_01M58179MEQX9RAVXTVCCGX3AZ`,
  verification `status=ok`, blob SHA-256 matches.
- `wenia-2018`: registration run `run_01M5866N8PAT122JVPT9SSR3GR`, ingest run
  `run_01M5866TZPBVW51FE7EG2TTDA6`, object `sobj_01M5866N90VRTA9RAC6BJ2V51J`,
  verification `status=ok`, blob SHA-256 matches.

Licence position: neither publication states an open licence. `Vaná rasĩ` is a CTI/Marúbo-authored
community publication; the thesis is © C. Sean Smith 2021. Under ADR-0025 presence authorizes
processing and training; both rights holders remain recorded so attribution and any later
revocation are possible.

## 2. What was extracted

### 2.1 Smith 2021 — IGT evidence (appendices B and C)

`exports/igt/smith_2021_twu_igt.jsonl` — **31 records**, one per numbered clause that passed tier
validation, each with `ref` (appendix + clause number), `mzr` (Marúbo tier), `gloss` (morpheme
glosses) and `eng` (published free translation).

These are **not** mzr↔por pairs: the published translations are English. They are morphology and
syntax evidence for the LKB (switch-reference markers, clause linkage), not training pairs, and
must not be written into `exports/harvested_parallel/` or the train/val/test splits.

Quality: 47 clauses were found and 31 passed the strict tier gate. The gate rejects a clause when
the Marúbo tier contains gloss leakage (uppercase runs), when any tier is empty, or when the
vernacular looks like Portuguese/English prose. Of the 31 accepted, some gloss strings are
truncated at a line wrap (the continuation line is a gloss fragment that the gate classifies as
vernacular, so the record is kept with a partial gloss rather than a corrupted one). Human spot
check before any morphology promotion is required; nothing here may be marked `validated`
mechanically.

### 2.1a Cesarino 2018 (*Wenía*) — IGT evidence from the segmentation annex

`exports/igt/cesarino_2018_wenia_igt.jsonl` — **41 records**, one per verse of the annex
"Anexo – Segmentação dos versos 545-585" (PDF pp. 52-53), extracted by
`scripts/extract_wenia_igt.py` from word bounding boxes (`pdftotext -bbox`; `-layout` re-wraps
the tier lines). Abbreviations ("Siglas", pp. 54-55, 36 entries) are in the sidecar
`exports/igt/cesarino_2018_wenia_igt.legend.json`, which also lists the bare labels the glosses
use but the legend does not (`DEM`, `DIR`).

Record shape follows the Smith file — `ref` (`cesarino-2018:v<N>`, the annex number), `mzr`
(segmented tier), `gloss` — with two differences:

- **`por`, no `eng`.** The glosses and the free translation are Portuguese. `por` is the
  author's translation of the same verse in the main text; nothing is machine-translated into
  English. The annex numbers 545-585 are the main text's 497-537 (offset 48), kept as
  `source.main_text_verse`; units are matched to main-text verses by their letters, which also
  merges the annex's split `Atovoki / Amaĩnõ` back into verse 562.
- `surface` (unsegmented verse), `source` (PDF pages) and `qc` (`alignment_ok`, `round_trip_ok`
  and their details) are added.

Checks, reported and never repaired: 39/41 verses align word-for-word and morpheme-for-morpheme;
verses 550-551 print 4 glosses for 5 words, so they keep `gloss: null` and the whole printed
line in `qc.gloss_unaligned`. Five verses fail the round trip (segmented letters ≠ surface):
546, 555, 557 (`Sai-ai-ina-ya` under `Saiainaiya`), 578 (`A raka-sho` under `Aa rakasho`) as
printed, and 563, where the text layer loses the `Ẽ` of `“Ẽ píti` (`qc.image_reading`). Image
spot-check: `var/artifacts/wenia_igt/spotcheck.md`.

Like Smith 2021, these are **morphology evidence, not parallel training pairs**: the same verses
are already in `cesarino_2018_wenia_parallel.jsonl`, and this file must never be written into
`exports/harvested_parallel/` (the extractor refuses that path).

### 2.2 Vaná rasĩ — Marúbo-only pedagogical prose

`exports/monolingual/vana_rasi_mzr.jsonl` — **19 blocks / 4,242 characters** of Marúbo prose with
page locators (`ref` = `vana-rasi:p{page}:b{n}`).

The lane 03b recheck clarified the book's real structure: it is bilingual but **sectioned, not
facing**, with 166 named ethnovarieties, each entry carrying a Marúbo headword and Marúbo prose
(origin / how it is planted / what it is for / respects) followed by a Portuguese translation on
other pages. That is why the monolingual pass captures only a fraction: Marúbo and Portuguese
paragraphs are interleaved with Portuguese section labels, so a block boundary is not a translation
boundary. Extracting the full Marúbo prose is feasible with a human reading the 51 pages or with a
bilingual section map; a heuristic that guesses it would produce the same invented alignment the
pair pass produced.

This is a new **register** (community pedagogical writing about cultivated plants, not scripture
and not shamanic chant), which is the scarcity the dataset actually has. It is monolingual and it
is not a parallel corpus. OCR artefacts remain (e.g. a replacement glyph inside a personal name,
occasional Portuguese words in Marúbo sentences, line-order jitter where the book mixes columns);
blocks must not be treated as clean text without review.

### 2.4 Cesarino 2013 — 4,033 line pairs, and the vernacular blocker

Action 15 of `FINDINGS.md` asked for the OCR of
`var/external/marubo_sources/Cesarino_2013_QuandoATerraDeixouDeFalar_MitolMarubo.pdf` to be repaired
and its pairs extracted. It was run, and the action's premise had to be corrected twice.

**Layout.** The earlier reading of `cesarino_2013.txt` (plain `pdftotext`) showed a Marúbo block
followed by a Portuguese block, hence "stanza-aligned". That was an artefact of reading order:
`pdftotext -bbox-layout` on the PDF shows each chant line is printed **beside** its Portuguese
line, with two book pages per scanned sheet (e.g. PDF page 46 = book pages 88–89). The correct
unit is the **row**, which is finer than a stanza and gives more pairs.

**Extraction.** `scripts/extract_pairs.py columns`:

- groups words into visual rows, splits each row into segments at wide gaps;
- clusters segments into text columns by left edge, and classifies a *column* — not a line — as
  vernacular or Portuguese from aggregate stopword evidence (a single line such as
  `Pajé Samaúma` carries no Portuguese function word, so per-line classification loses it);
- pairs each vernacular column with the translation column immediately to its right, estimates
  that column pair's baseline offset by search (printed rows are offset several points), and
  pairs rows by vertical position only, so a missing translation loses one row instead of
  shifting every following pair;
- drops a sheet whose row count is below `--min-pairs-per-page` (prose chapters and plates);
- drops exact duplicate `(src, tgt)` rows (chant refrains and running heads): 530 removed.

Result: `exports/parallel_candidates/cesarino_2013_columns.jsonl` — **4,033 pairs**, 10,497
vernacular tokens, 112 of 162 PDF pages, locators `cesarino-2013:p<page>:l<row>` plus the book's
own margin line number where the scan kept it (18.5 % of rows). Alignment was checked against the
page images on PDF pages 26, 46, 67 and 120: same rows, same order, same translations.

**Indented chant pages (`--column-gap-page`).** With the default `--column-gap 60`, PDF pages 25,
72, 106, 123 and 148 yield nothing: their chant column is indented inside the prose margin, so
its left edges merge with the neighbouring column. A global `--column-gap 25` recovers them but
re-clusters 34 other pages and renumbers their positional `p<page>:l<row>` locators, which would
orphan refs already cited (e.g. `cesarino_2013_clean_refs.jsonl`). The repeatable
`--column-gap-page PAGE=GAP` option applies the narrower gap to the listed pages only. Dedup
still keeps the first occurrence, but an override page only claims a `(src, tgt)` key that no
default-gap page holds; without that rule, refrains on pages 25 and 72 would have displaced 4
existing rows (`p26:l4`, `p26:l7`, `p73:l24`, `p73:l37`). Measured result:

- the 3,951 rows of the default run are byte-identical and in the same order (the default run
  without the option still reproduces the earlier file byte for byte);
- 96 rows found on the five pages, **82 added** (p25: 11, p72: 12, p106: 17, p123: 18, p148: 24);
- 14 dropped as duplicates: 7 repeat an existing row on another page, 7 are refrains repeated
  on the same page (`var/artifacts/cesarino_2013/t5_check/dedup_drops.json`);
- every one of the 96 rows was checked against the 200 dpi page image for print order and
  pairing: 0 order failures and 0 pairing failures. One translation is truncated: `p148:l1`
  reads `"Caiçuma` where the book prints `"Caiçuma do Inca` (the log is
  `var/artifacts/cesarino_2013/t5_check/qa.json`);
- still not extracted on these sheets: the facing book page of PDF 72 (book p. 140, ~23 rows),
  123 (p. 243, ~29 rows) and 148 (p. 293, 4 rows), and the 2 chant lines under the prose on
  book p. 46 (PDF 25). On each of those sheets only one of the two book pages pairs at either
  gap.

**Portuguese repair.** This OCR encodes `ç` as `~`, `\:`, `\=`, `<;` or `c;` (`tradu~ao`,
`come\:a`, `lan<;a`) and welds footnote superscripts onto words (`Sucuri-Sol3`). Those are
deterministic rewrites, so they are applied: 421 repairs, each rule named in `qc.tgt_repairs`,
with the pre-repair line preserved in `qc.tgt_raw` (spaced and quote-adjacent footnote markers had
to be added in the second pass; they were the bulk of the earlier residual). 38 tokens in 38 rows
remain damaged and are listed in `qc.tgt_residual`.

**The blocker.** The Marúbo side cannot be repaired from this text layer. The scan prints the
nasality marks — `Awẽ nimẽaitõ`, `Ino Sheta Rekẽne`, `Pani txiwávakĩsho`, `Awẽ rakámãĩnõ`,
`Niro Kaso inĩki`, `Txai mā txai` — and the OCR drops them (`Awe nimeaito`, `Ino Sheta Rekene`,
`Pani txiwávakisho`, `Awe rakámaino`, `Niro Kaso inlki`, `Txai ma txai`). Unlike the Portuguese
cedilla there is no substitute glyph to rewrite: the information is gone, the book mixes tilde and
macron conventions, and reconstructing it would be inventing target-language orthography
(AGENTS.md invariant 9). Measured against a 15,695-word reference vocabulary built from the mzr
USFM, the harvested chapter/chant pairs, the Marúbo lexicon and the academic wordlist:

| screen | rows |
|---|---|
| no vernacular token unattested as printed, no Portuguese residual | **761 (18.9 %)** — review first |
| at least one vernacular token unattested as printed | **3,261 (80.9 %)** — chant vocabulary and/or lost diacritics |
| `l`/`T`/digit artefacts inside vernacular tokens (`ĩ` damage family) | 176 |
| Portuguese residual after repair | 38 |

(Before the five `--column-gap-page` pages were added the same screens read 753 / 3,187 / 171 /
37 of 3,951 rows.)

The pairs are therefore shipped as **alignment evidence** in `exports/parallel_candidates/`,
outside the dataset glob, and explicitly not promoted. `exports/parallel_candidates/README.md`
records the promotion conditions.

**Tokenizer correction (second pass).** The word pattern was `[A-Za-zÀ-ÿ]{2,}`, which excludes
`ẽ ĩ ũ` — so `postĩno` was measured as `post` + `no` and the fragment `no` counted as a Portuguese
function word. With the corrected pattern (`[^\W\d_]{2,}`) the reference vocabulary grew from
13,689 to 15,695 words and the vernacular screen moved (table above). The pairs did not move.

**One live lead (verified 2026-10-18, not yet usable).** DeepSeek's own crawl of the *same*
byte-identical PDF (sha256 `585b9308…6d2c4f`, confirmed by downloading the etholinguistica.org copy)
has a **better text layer than the PDF's own**: searching for a chant line returns
`Koî rome weki / Ao vento de rapé-névoa / Veôini otivo / Há tempos flutua / Koî shôpa weki /
Vento de lírio-névoa / Chîkirinatôsho`, i.e. the nasals survive as circumflexes (`î`≈`ĩ`, `ô`≈`õ`)
where our text layer has `Koi rome …, Chz kirinatosho`. It is not retrievable programmatically:
`POST /v1/tools/fetch` on that URL returns HTTP 404, and search snippets are truncated. Recorded
so nobody re-derives it; the practical ask is a clean transcription, not a crawl of snippets.

**Correction to the earlier plan.** `FINDINGS.md` §3/action 15 and the lane 04b recheck said the
repair was `~`→nasal and `c;`→`ç`. That is only true of the Portuguese column. The vernacular
repair needs a clean transcription (author's files, or the 2018 *Wenía* article if that chant
overlaps) or an OCR engine whose character set includes `ẽ ĩ ũ ã õ ō`; Portuguese-language OCR
models do not, so this is a source problem rather than a pipeline problem.

### 2.5 Wenía 2018 — 921 clean verse pairs from a born-digital chant text

The correction above asked for a clean digital transcription. One was found and acquired:
Cesarino, *Wenía: o surgimento dos antepassados* (*Estudos de Literatura Brasileira
Contemporânea* 53, 2018, DOI [10.1590/2316-4018533](https://doi.org/10.1590/2316-4018533)).
`pdfinfo` reports `Producer: Microsoft® Word 2010`: this is the author's own digital manuscript,
not a scan. Its chant section (pp. 59–88) prints each Marúbo verse beside its Portuguese
translation, numbered every fifth verse, and **the nasality diacritics are intact** —
`Veõini otivo`, `Vari shõpa weki`, `Ato awe shavoyai` — the exact marks the 2013 scan lost.

Registered as governed source `wenia-2018` (`src_01M5866N90VRTA9RAC6BJ2V51H`), raw
`var/external/wenia_2018/wenia_2018.pdf` (sha256 `a3661ae5…4dfab767`), ingest and verify `status=ok`.
The article is CC BY-NC 4.0 per the SciELO record (recorded metadata, not a gate: ADR-0025);
register is ritual chant.

New extractor `scripts/extract_pairs.py table` reads `pdftotext -layout`: a born-digital table
keeps both cells of a row on one reconstructed line, so the pair is *read out of the source*
rather than inferred from baselines, and the printed margin number becomes the locator. Guards
reject the single-cell running heads, page footers, section headings and the one wrapped footnote
line that also contain wide spaces. It emits 76 deterministic footnote-superscript repairs
(`qc.tgt_raw` keeps the raw line) and no OCR repair at all, because there is no OCR layer.

| | |
|---|---|
| Artifact | `exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl` |
| Records | **921 verse rows / 2,401 Marúbo tokens**, PDF pages 15–48 |
| Locators | `cesarino-2018:p<page>:l<row>`; 185 rows (20.1 %) also carry the printed verse number, monotone with zero gaps |
| Damage | **0 residual damaged tokens, 0 OCR-artefact flags** |
| Lexical coverage | 113 rows fully attested in the scripture/lexicon reference; 808 rows use chant vocabulary absent from it — that is lexicon, not damage, since there is no OCR layer |
| Dataset effect | the artifact is inside the `exports/harvested_parallel/*_parallel.jsonl` glob, so `load_harvested_parallel_sentences()` now returns **1,026** mzr rows (105 from the 2017 chapter + 921 from Wenía) |

**Capital Ẽ (tilde marks).** The article prints eight word-initial capital `Ẽ` that the text
layer shows as `E`: Word draws the tilde as a separate Times New Roman glyph (CID font, code
0x047A) right after the Book Antiqua `E`, and that font's ToUnicode maps the code to U+0020, so
`pdftotext` emits a space. `scripts/wenia_tilde_decode.py` scans the content streams for that
operator directly after an `E` on the same baseline, locates it by `-bbox-layout` word and keys
it to the `-layout` line; the 9 hits (8 harvested rows, plus an interlinear quote on p52 outside
the table) are committed in `exports/harvested_parallel/cesarino_2018_wenia_tilde_marks.json`.
`extract_pairs.py table --tilde-marks` rewrites exactly that `E` to `Ẽ` (U+1EBC, NFC) in `src`
only: p33:l25, p37:l11, p37:l16, p42:l28, p43:l11, p43:l19, p45:l12, p46:l2. The other 18
E-initial rows have no marker and stay plain `E` (`p42:l13 Enõ` is plain, `p43:l11 Ẽnõ` is not),
so there is no blanket rule. `qc` is computed on the printed `E` and is unchanged. Image
evidence: `var/artifacts/bare_e/findings.md`.

**It does not repair the 2013 book.** The book's table of contents lists its twelve chants (Naí
Mai vaná, Kaná kawa, Shono Romeya, Sheta Veká, Shoma Wetsa, Rane Nawavo pakaya, Rome Owa Romeya,
Roka, Isko metaska, Temi Txoki, Inka roe yoká, Tama rera); the 2018 article publishes a
*different* chant of the same cycle. Measured directly against the book's 3,951 rows: the two
texts share only **formulaic refrains** — 162 of the 921 Wenía lines (17.6 %, 56 distinct lines
such as `Sai toã ikiya`, `Nawa wení iniya`, `A aki avai`) match a book row after diacritic
folding, and 82.4 % of Wenía rows appear in no book row at all. So §2.4's blocker stands: what
unblocks it is still the author's digital text of *those* chants, or a re-OCR whose character set
covers `ẽ ĩ ũ ã õ ō`.

**A partial, citation-based repair path (lead, not done).** Those 162 shared refrains are the one
place where the clean 2018 text speaks to a 2013 row: the book row and the Wenía line carry the
same consonant-and-vowel skeleton, so the Wenía form is *evidence* for the marks the scan lost.
It is evidence, not a rewrite — the two chants are separate performances and a refrain may be
re-pointed or respelled — so it would have to arrive as a hypothesis attached to the candidate
row (clean form + match evidence + lineage), never as an overwrite of `src`. 4.1 % of the book
rows is a small prize; the full unblock is still the book's own digital text.

**One editing artefact worth knowing.** The article's printed line numbering skips verse 114 on
p. 19 (the page image shows only three verses between the numbers 110 and 115) and prints one
extra quoted verse later, so the printed number is a locator, not a row index. The extractor keeps
the printed number and never infers the missing line.

### 2.6 Clean-form citations for the 2013 rows — mid-course correction to 2.5

The answer to 2.4's blocker was closer than 2.5 concluded. The 2018 *Wenía* article is one chant
the book does not print, but other born-digital works **quote the book's own chants with the
diacritics intact**. One of them was acquired and used as a citation reference:

| | |
|---|---|
| Reference | Villada Castro, *De dobles y trocas: a propósito de la traducción del portugués al español de cantos marubo*, *Mundo Amazónico* 9(1): 105–117, 2018, DOI [10.15446/ma.v9n1.64860](https://doi.org/10.15446/ma.v9n1.64860) |
| Raw | `var/external/villada_2018/villada_2018.pdf`, sha256 `226c17db…4163361`, born-digital (`Adobe PDF Library 15.0`) |
| Governed | `villada-2018`, `src_01M5871WGJDC0DHVJXF7DB4MER`, ingest `run_01M5871Y7BF0J9PBX87ZMP5D4K`, verify `status=ok` |
| Quoted chants | *Kaná kawã*, *Rome Owe Romeya*, *Roka* — three of the book's twelve |

`scripts/recover_chant_orthography.py` matches a book row against the reference by a **letter
key** only: case and all marks folded, and the scan's nasal stand-ins folded too (`z`/`l`/`T` →
`i`; the scan prints `Koz`/`Chz`/`inlki` for `Koĩ`/`Chĩ`/`inĩki`, and Marúbo has no /l/ or /z/).
When the whole row's token sequence occurs contiguously in the reference, the reference's surface
becomes a **citation**; the observed `src` is never rewritten.

| measure | rows |
|---|---|
| book rows with a cited occurrence | 292 of 3,951 (7.4 %), across 76 of 162 pages |
| unanimous citation (`clean_src` filled) | 285 |
| citation **adds a nasal mark** the scan lost | **167 (4.2 %)** |
| citation confirms the observed line (identical or same letters) | 118 |
| citation conflict (same letters, different marks in different places) | 7 — reported with `clean_candidates`, never voted away |

Verification: all 285 cited surfaces occur **verbatim on a cited page** of the reference PDF
(programmatic check), and two rows were checked against the book's own page images — the scan
really prints `Atõ aki amaĩnõ` (book row `Ato aki amaino`, p. 30) and `Awẽ aki amaĩnõ` (`Awe aki
amaino`, p. 32), exactly as the citation says.

Artifact: `exports/parallel_candidates/cesarino_2013_clean_refs.jsonl` — still a candidate file,
because `clean_src` is evidence with a citation, not a validated observation. The promotion path
is now concrete: review the 167 nasal-mark rows (and the 118 confirmations), then write
`clean_src` as the vernacular side of a promoted pair with the citation attached.

**Wenía 2018 as a second, weaker citation tier.** The 921 Wenía pairs (§2.5) are a different
chant, but they share formulaic refrain lines with the book. `--reference-jsonl
wenia-2018:exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl` reads them as
`shared-formula` citations (locator = the Wenía record's `ref`, verbatim), next to Villada's
`quoted-chant` ones. Rule: a shared-formula citation **never originates** a `clean_src`; it only
confirms or contradicts a quoted-chant one. Result on the 4,033-row columns file (candidate,
`var/artifacts/cesarino_2013/clean_refs_t2.jsonl`; row-by-row QA in `var/artifacts/t2/diff.md`):

| measure | rows |
|---|---|
| Villada-only run (current columns file) | 300 (the published 292, byte-identical, + 8 from the `--column-gap-page` sheets) |
| Villada + Wenía | 465 |
| cited by both tiers | 69 — 61 confirm (vote gained, same `clean_src`), 8 contradict |
| published unanimous rows turned `conflict` | 8 (`Ato aki amaino` ×5, `Awe rakámaino` ×3) |
| new rows, Wenía only (`uncorroborated`, `clean_src: null`) | 165 |

The 8 conflicts are kept, after a page-image check (verdicts in `var/artifacts/t2/diff.md`):
for the 5 `Ato aki amaino` rows the book image matches Villada's `Atõ aki amaĩnõ`, and Wenía
prints that form only 4 of 7 times, so the conflict is Wenía disagreeing with itself. For the 3
`Awe rakámaino` rows (p46:l22, p78:l38, p103:l6) the book prints `rakámaĩnõ` (acute), so the
published Villada `clean_src` `Awẽ rakãmaĩnõ` needs review; turning them into conflicts is the
intended outcome.

**The 2008 thesis, decoded (T1).** Cesarino's 2008 UFRJ doctorate (*Oniska*, 472 pp.,
`var/external/cesarino_2008_thesis/cesarino_2008_thesis.pdf`) is born-digital and quotes the same
chants. The scraped HTML had broken font slots, but the real PDF's text layer carries nasal marks
as private-use glyphs (U+F017/F018/F01C, 1,347 occurrences); `scripts/cesarino_pua_decode.py`
maps them to U+0303 (`var/artifacts/cesarino_2008_thesis/decoded.txt`, 469 pages, 0 PUA left).
`recover_chant_orthography.py --reference-text cesarino-2008:...decoded.txt` adds it as a third
`quoted-chant` reference (locator `cesarino-2008:p<page>`). Run on the 4,033-row columns file
(with the Wenía `Ẽ` fix of commit 335a8ac, which only rewrote `Eta neskái` to `Ẽta neskái` on 5
`uncorroborated` rows):

| measure | before (Villada + Wenía) | after (+ thesis) |
|---|---|---|
| cited rows | 465 | 867 |
| unanimous / conflict / uncorroborated | 285 / 15 / 165 | 606 / 191 / 70 |
| nasal marks added / confirm observed | 164 / 121 | 319 / 287 |
| rows with a `clean_src` | 285 | 606 |

Breakdown: 333 new `clean_src` rows from the thesis alone (199 add nasal marks), 82
`uncorroborated` rows resolved, 115 rows where the thesis and Villada agree, 94 published
unanimous rows turned `conflict` (+13 `uncorroborated` ones), 69 new conflicts. The conflicts
are real: the thesis prints the same refrain with different marks in different places
(`awẽ aki amaĩnõ` p387 vs `awẽ aki amainõ` p409; `a aki avaikĩ` p390 vs `a aki avaiki` p399).
**Image checks** (thesis page crops at 200 dpi, `var/artifacts/t1/image_check.md`): 18 crops, all
match `decoded.txt`, so the decoder neither drops nor invents marks; 6 new thesis-only rows match
both the thesis and the book crop where viewed; in 6 thesis-vs-Villada conflicts compared with the
book, the book agrees with Villada 4 times (`Ino Sheta Wesí`, `Ána shea sheai`, `Neskárivi katái`,
`Shõkẽ shõkẽ isi`) and with the thesis twice (`Awe anõ nĩkã`, `rakámaĩnõ`). Neither source is a
safe tiebreak, so conflicts stay conflicts. Decoder, row-by-row diff: `var/artifacts/t1/`.
**Conflict reads (evidence only).** Two free vision readers read the 191 conflict rows against
the printed book line: `exports/parallel_candidates/cesarino_2013_conflict_reads.jsonl` (163 agreed,
11 disputed, 17 unread; `clean_src` stays null). Schema, accuracy numbers and the proxy-gold caveat:
`exports/parallel_candidates/README.md`.

### 2.3 The negative that matters

**Vaná rasĩ was not extracted as mzr↔por pairs.** The first attempt assumed a facing-column
layout. A `pdftotext -bbox-layout` pass showed that the book is *sectioned*, not cleanly
face-to-face: pages carry a Marúbo block followed by a Portuguese block, heading glosses such as
`Vimi, os frutos` are plant-name labels rather than translations, and several pages have two
Marúbo columns. The automatic paragraph-pair pass produced 42 candidates of which inspection
showed front-matter, colophon and same-language material paired across columns — i.e. invented
alignment. That output was **deleted rather than shipped**. Paragraph pairing for this book needs
a human (it is 51 pages) or a layout-aware table extractor, not a heuristic.

This is the correct failure mode under the repo invariants: no alignment is better than a
fabricated one, because a wrong pair silently teaches wrong translation.

## 3. Effect on the dataset

- **921 new trainable pairs** were added: `exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl`
  is inside the loader's glob, so `load_harvested_parallel_sentences()` now returns 1,026 mzr rows
  (105 from the 2017 chapter + 921 from Wenía). The generated `exports/mzr/datasets/` splits were
  **not** regenerated in this pass (another change was in flight there); the next
  `langpipe synth export` run will pick the new rows up.
- The 4,033 Cesarino-2013 rows still sit in `exports/parallel_candidates/`, outside that glob.
- The rest of the new value is (a) 31 IGT clause records for morphology/syntax evidence, and
  (b) 18 blocks of a new Marúbo register for style/register work and future alignment.
- The higher-yield dataset work is elsewhere and already catalogued: the four CC-BY CLDF wordlists
  (`oliveiraprotopanoan` 324 forms/266 concepts, `zariquieypano` 187/181, `panobodyparts` 26,
  `valenzuelazariquieypanotakana` 25) and the SIL Javari 2010 375-concept wordlist. Those are
  lexicon, not pairs.

## 4. Reproduction

```bash
# raw acquisition is a human step; the files are already in var/external/
.venv/bin/langpipe source show vana-rasi
.venv/bin/langpipe source show smith-2021-twu

# Cesarino 2013 chant columns (4,033 row pairs; candidates, see exports/parallel_candidates/README.md)
# --column-gap-page reads the five indented-chant sheets with a 25-point gap and leaves every
# other page, and so its p<page>:l<row> locators, at the default gap (§2.4)
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

# extraction (deterministic, offline once the PDFs exist)
.venv/bin/python scripts/extract_pairs.py igt \
    --pdf var/external/smith_2021_twu/smith_2021_twu.pdf \
    --out exports/igt/smith_2021_twu_igt.jsonl \
    --qa var/artifacts/smith_2021_twu/igt_qa.json
.venv/bin/python scripts/extract_pairs.py monolingual \
    --pdf var/external/vana_rasi/vana_rasi.pdf \
    --out exports/monolingual/vana_rasi_mzr.jsonl \
    --qa var/artifacts/vana_rasi/monolingual_qa.json

# Wenía 2018 born-digital chant table (921 clean verse pairs; enters the training glob)
.venv/bin/python scripts/extract_pairs.py table \
    --pdf var/external/wenia_2018/wenia_2018.pdf \
    --ref-prefix cesarino-2018 \
    --pages 15-48 \
    --mzr-reference 'var/external/scriptureearth/mzr/*.usfm' \
    --mzr-reference 'var/external/marubo_vocab/*.tsv' \
    --mzr-reference 'var/external/marubo_sources/academic_lexicon.tsv' \
    --tilde-marks exports/harvested_parallel/cesarino_2018_wenia_tilde_marks.json \
    --out exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl \
    --qa var/artifacts/wenia_2018/table_qa.json

.venv/bin/pytest tests/unit/test_extract_pairs.py -q
```

## 5. Open items

1. Human-assisted alignment of Vaná rasĩ (51 pp.) — the only way to turn it into por↔mzr pairs.
1a. Cesarino 2013: obtain a clean digital transcription **of the book's twelve chants** and align it
   to the 4,033 row locators, then review the 761 review-first rows and promote. The 2018 *Wenía*
   article is a different chant and does **not** unblock this (§2.5). Do **not** re-run the
   extractor expecting a better vernacular text: this scan does not contain one.
1b. Re-run `langpipe synth export` so the 921 Wenía pairs enter `exports/mzr/datasets/` (they are
   already in the loader's input glob), and check the split balance after the 10× growth in
   attested pairs.
1c. Cesarino 2013 layout gaps left after `--column-gap-page` (§2.4): book pp. 140, 243 and 293
   (PDF 72, 123, 148; ~56 rows) and the 2 chant lines on book p. 46 (PDF 25) still do not pair at
   gap 60 or 25. Diagnose `cluster_columns`/`pair_columns` on those sheets before trying another
   gap; any fix must keep the existing locators byte-stable, as the `--column-gap-page` run did.
   The 82 rows it added are not yet covered by `cesarino_2013_clean_refs.jsonl`.
1d. Wenía shared-formula citations (§2.6): review the 3 `Awe rakámaino` rows (p46:l22, p78:l38,
   p103:l6), where the book's acute `rakámaĩnõ` disagrees with Villada's `rakãmaĩnõ`. The 165
   `uncorroborated` rows stay without `clean_src` by rule.
2. Review the 31 IGT records for gloss truncation; promote via the normal IGT observation path
   (not by copying JSONL into a training split).
3. A repository-wide PDF extractor for the governed `extract` stage: today PDF objects are
   registered and verified but no registered extractor consumes them, so text extraction is a
   harvest-side script rather than a `langpipe extract` run. That gap is why these sources have
   source-lineage but not segment-lineage in the database.
