# Panoan resource survey — Marúbo (`mzr`) dataset expansion

**Survey date:** 2026-10-18. **Target:** Marúbo, ISO 639-3 `mzr`, Glottolog `maru1252`,
ASJP `MARUBO`; family Panoan (`pano1256`), Pano–Tacanan; Terra Indígena Vale do Javari,
Amazonas, Brazil (Ituí / Curuçá). **Contact language:** Portuguese. **Panoan sisters already
profiled in-repo:** Matsés (`mcf`), Matis (`mpu`), Korubo (`xor`); Shipibo-Konibo (`shp`) is
named in `docs/languages/mzr.md` and is already used for NLLB embedding seeding.

**Method.** Six parallel research lanes (reference catalogs; academic literature; archives and
ethnographic media; parallel corpora; living platforms; NLP datasets and models), plus
coordinator-side direct verification. Preflight, canonical identifiers, the already-known list,
governance extract and lane assignments: [`00-preflight.md`](00-preflight.md). Raw per-lane
reports: `research/NN-*.md`.

**Capability note (read this before trusting any negative).** `web_search` was unavailable in
this session: the harness is configured with search provider `ddg` (from the `dsh-free-search`
plugin) but that provider is not registered in the running process, so every `web_search` call
failed. Research therefore used `web_fetch` against search-engine HTML endpoints plus direct
catalog APIs. DuckDuckGo HTML/Lite started returning HTTP 202 bot challenges ~40 minutes into
the run; Bing works but geo-personalises to a Brazilian market and silently mangles narrow
academic queries. Conclusions below rest on **direct API/page fetches**, not search snippets.
Where a lane could only see a snippet, the item is marked `[U]`.

**Verification notation:** `[V]` loaded this run · `[W]` verified via archive snapshot or
bibliographic record but full text not retrievable · `[U]` unverified. Every URL was checked on
2026-10-18 unless stated.

**Headline.** The first pass found no new Marúbo *text* on the open web; the same-day
DeepSeek-search follow-up (§9) then found two real ones — Smith 2021's two glossed narratives
and the Marúbo-authored bilingual book *Vaná rasĩ* — plus a downloadable Fleck 2013 survey and the
finding that an asset **already in the repo** (*Cesarino 2013*) is line-aligned mzr↔por
(**3,951 row pairs**, extracted on 2026-10-18) whose *vernacular* diacritics are lost in the OCR
text layer. The hunt for the clean transcription the blocker pointed at then found the 2018
*Wenía* article: a **born-digital** chant text (Microsoft Word PDF, diacritics intact) that gives
**921 clean `mzr`↔`por` verse pairs** — a different chant of the same cycle, so it is now the
largest source of trainable pairs but does not repair the book.
The bulk of the gains still sit elsewhere:
(a) a **13,382-lexeme FLEx database at UFAM** plus a **375-concept SIL wordlist** and **four
CC-BY CLDF datasets** — together enough to multiply the current 1,099-entry lexicon several
times; (b) **162 untapped chapter MP3s** of Marúbo scripture audio and a 3 h 20 m subtitled
Javari film set, the only real speech assets; (c) a large gate-free mass of **sister-Panoan
scripture** (Cashinahua whole Bible in two editions, Shipibo, Cashibo, Yaminawa, Matsés) for
hypotheses and transfer, never for Marúbo truth; (d) two traps that would have poisoned the
dataset — Door43's mislabelled `mzr` repos and ELAR's "Marubo Indians" items — now quarantined
with evidence.

---

## 1. Corrections to the current inventory

These correct assumptions that were live in the repo or in the 2026-10 license note.

1. **Governance changed mid-survey.** `docs/adr/0025-presence-based-source-authorization.md`
   (accepted 2026-10-18) makes repository presence the authorization: licenses, ownership and
   register are **records, not gates**, and only an explicit operator `exclude` blocks a source.
   It supersedes ADR-0022/0023/0024 as authorization gates. Consequence for this survey: every
   resource below is catalogued with its license and rights holder for attribution and later
   revocation, but **no finding is rejected because its license is unstated, NC, or missing**.
   The "not trainable" column in `docs/research/candidate-source-licenses-2026-10.md` is
   therefore obsolete as a gate. Access (can we obtain the bytes?) and quality are the real
   constraints now.
2. **OPUS negative is weaker than recorded, not stronger.** The 2026-10 note said no Panoan
   corpus exists in OPUS. Re-checked: `opus.nlpl.eu/corpora.php` contains no Marúbo/Panoan
   entry, but the OPUS API silently ignores unsupported 3-letter codes (`?source=mzr` returns
   *all* corpora, i.e. the filter is dropped, and `?source=shp&target=spa` returns
   `{"corpora":[]}`). That is not proof of absence. **Status: probable negative, unproven by
   API.** Treat OPUS as low-priority and do not re-check unless an ISO-639-1-coded Panoan
   source appears.
3. **eBible: Marúbo absent, four Panoan scripture corpora present.** The full eBible scripture
   index (`ebible.org/Scriptures/`, 763 KB) contains no `mzr` or Marúbo entry `[V]`. It does
   host four Panoan New Testaments/Bible with USFM downloads: Matsés `mcfNT` (Wycliffe 2008),
   Kashinawa `cbsNT` (2008), Yaminahua `yaaNT` (page did not resolve this run, `[U]`), and a
   **full Shipibo-Conibo Bible** `shpNTpo` (Wycliffe 2012). See §4.
4. **The `Banco de Dados da Língua Marubo` exists and is bigger than the whole current
   lexicon.** OpenAlex carries a truncated DOI (`…-38095`) that 404s; the correct DOI is
   `10.29327/xxxii-congresso-de-iniciacao-cientifica-380957.768609` `[V]`. It is a UFAM
   PIBIC/CONIC abstract (Pedrosa, supervised by Sanderson Castro Soares de Oliveira) reporting
   **13,382 Marúbo lexemes entered into FieldWorks (FLEX)**, all extracted from a 117-page
   Marúbo book, *"Vana nía anosh tanati Askai awe iki inã anosho tanaa"* (no named author).
   Neither the FLEX database nor the source book is online as far as this survey could verify;
   both are requestable from UFAM. See §4, find 1.
5. **The current dataset is 98% scripture and that is the real bottleneck, not source volume.**
   Measured from `exports/mzr/datasets` on 2026-10-18:

   | Split | Rows | Scripture (`corpus:`) | Cesarino 2017 IGT (`harvested:`) |
   |---|---:|---:|---:|
   | train | 4,701 | 4,671 (99.4%) | 30 |
   | val | 543 | 518 (95.4%) | 25 |
   | test | 250 | 200 (80.0%) | 50 |
   | **total** | **5,494** | **5,389 (98.1%)** | **105 (1.9%)** |

   All 105 harvested Cesarino pairs *are* used (30/25/50 across splits) — an earlier suspicion
   that they were unused was wrong. The distortion is the opposite: the small non-scripture
   set is 20% of the test split but 0.6% of train, so evaluation is not measured on the same
   distribution the model trains on. ADR-0023's proposed 0.2 scripture share is the right
   direction but is not enforced anywhere.
6. **The Cesarino 2013 book in `var/external` is OCR-degraded, not merely unmined — and the
   repair the earlier survey proposed does not exist.** The 2026-10-18 extraction
   (`extraction-2026-10-18.md` §2.4) re-derived the layout from the PDF word boxes and corrected
   two assumptions: the book is **line-aligned** (each chant line beside its Portuguese line,
   two book pages per scanned sheet), not stanza-aligned, and it yields **3,951 `mzr`↔`por` row
   pairs / 10,302 vernacular tokens** on PDF pages 16–154, not ~655 lines. The Portuguese side
   *is* mechanically repairable (`~`, `\:`, `<;`, `c;` are substitute glyphs for `ç`; 408
   deterministic repairs) — but the **Marúbo side is not**: the OCR drops the printed nasality
   marks outright (`Awẽ nimẽaitõ` → `Awe nimeaito`, `inĩki` → `inlki`, `Txai mā txai` → `Txai ma
   txai`) and the book mixes tilde and macron conventions, so there is no substitution rule to
   recover them. The pairs are therefore **alignment evidence, not training data**: 80.7 % of
   rows contain at least one vernacular token that is unattested as printed, and the 753 rows
   (19.1 %) that screen clean are the review-first subset. See
   `exports/parallel_candidates/README.md`. **Follow-up, same day:** the clean transcription the
   blocker asked for was found — Cesarino's 2018 *Wenía* article is a born-digital (Microsoft
   Word) chant text with the diacritics intact, extracted as 921 clean verse pairs
   (`exports/harvested_parallel/cesarino_2018_wenia_parallel.jsonl`, §2.5 of the extraction
   report). It is a *different* chant of the cycle (no book row beyond 162 shared formulaic
   refrains), so it does not unblock this file: that still needs the author's digital text of
   the book's twelve chants, not more processing of this scan.
7. **NLLB transfer assumption is already documented, so sister-Panoan data is not a side
   quest.** `notebooks/build_notebook.py` initialises the new `mzr_Latn` embedding as
   `0.75·shp_Latn + 0.25·por_Latn`. Any high-quality Shipibo-Konibo (and, by extension, other
   Panoan) parallel data has direct transfer value beyond hypothesis generation.
8. **MMS does not cover Marúbo (verified hard negative).** `facebook/mms-1b-all` ships 3,606
   files, one `adapter.<iso3>.bin` per language; there is no `adapter.mzr.*` `[V]`. Do not
   assume multilingual ASR coverage for `mzr`.
9. **The provenance of our own Marúbo USFM does not match the live source.** The live
   ScriptureEarth tree `scriptureearth.org/data/mzr/` exposes **no USFM and no PDF** (`/usfm/`,
   `/USFM/`, `00-ALL-mzr.zip` all 404; `PDF/` empty); the verse text is bundled inside a
   SvelteKit app. It *does* expose **162 chapter MP3s** (GEN 50, EXO 20, RUT 5, NEH 7, LUK 25,
   JHN 21, ACT 29, JAS 5) and an **empty** `audio/timing/`. Yet
   `var/external/scriptureearth/mzr/langpipe-manifest.yaml` records
   `acquired_from 00por.php?iso=mzr`. Under ADR-0025 this is a metadata inconsistency, not a
   gate, but the lineage record deserves human re-verification before the corpus is described
   anywhere as "downloaded from ScriptureEarth USFM". `[V]`
10. **Door43 is a false-positive trap that would poison the lexicon.** Ten repos
   `moseslai2018/mzr_{amo,hab,hag,jol,lam,mal,mic,oba,zec,zep}_text_reg` carry running text with
   `\v` markers, an `mzr`/Marúbo manifest, clean CC BY-SA 4.0 LICENSE, ~912 verses. Function-word
   overlap with our local mzr USFM is **0/25 raw, 2/30** after folding accents; our 1,099-entry
   lexicon has no `th` tokens and no word-final `-ng`, both dense in that text; sole committer is
   UTC+07:00, 2018 bulk import. Almost certainly a Chin/Kuki Tibeto-Burman language
   mislabelled `mzr`. **Quarantine — never ingest as Marúbo.** `[V]`
11. **No new Marúbo *corpus* exists on the open web, but new *text* does.** The six lanes found
   no new Marúbo corpus; every lane finding was lexical, bibliographic or sister-language, and
   government/community school materials could not be reached (hosts dead or blocked), so they
   remain `[U]`, **not** a negative. The same-day DeepSeek-search follow-up (§9) corrected this
   in two places: Smith 2021 contains **two fully glossed narratives** (Appendix B and C) and
   *Vaná rasĩ* is a 51-page **Marúbo-authored bilingual book with facing Portuguese** — both new
   text, neither a crawlable corpus.


## 2. Measured baseline the findings must beat

| Asset | Current state | Source |
|---|---|---|
| Train/val/test rows | 4,701 / 543 / 250 | `exports/mzr/datasets/manifest.json` |
| Register mix | 98.1% scripture, 1.9% Cesarino narrative IGT | measured above |
| Lexicon entries | 1,099 (with POS, glosses, citations) | `exports/mzr/dictionary.json` |
| Morphology notes | 12 | `exports/mzr/dictionary.json` |
| Parallel sentences with IGT | 8 | `exports/mzr/dictionary.json` |
| Synthetic phrases | 44 generated, 24 passed quarantine | `exports/mzr/synthetic_phrases.json` |
| Audio in exports | none | grep over `exports/mzr/` |
| Known indexed sources | 12 mzr records | `docs/languages/mzr_sources_index.json` |
| Registry catalogues | 11 repositories, 18 discovered resources | `docs/research/universal_sources_registry.json` |

Local raw holdings (immutable, `var/external/`): Costa 1992/2000/2002/2017 PDFs + text,
Cesarino 2013 book + Cesarino 2017 chapter, USFM scripture (9 books), Portuguese parallel text,
ASJP-based lexicon TSV. Nothing else.

## 3. Ranked top finds (merged across lanes, coordinator-verified where marked)

1. **UFAM FLEX database: ~13,382 Marúbo lexemes** (+ the 117-page source book it was built
   from). This dwarfs the current 1,099-entry lexicon by ~12×. Not downloadable online;
   requires contacting UFAM (Pedrosa; supervisor Sanderson C. S. Oliveira, who is also the
   author of the Proto-Panoan CLDF in find 2 and the supervisor of the Jaques dissertation in
   find 6). Highest expected yield of any finding. `[V]` abstract; database `[U]` (unpublished).
2. **`oliveiraprotopanoan` CLDF — 19 Panoan languages + Proto-Panoan, 7,305 forms, cognate
   sets, CC-BY-4.0.** Marúbo included: **324 forms across 266 concepts**, sourced from
   Oliveira 2014, Costa 1992 and Cesarino 2008. Downloadable now
   (`github.com/pano-takanan-history/oliveiraprotopanoan`, `cldf/forms.csv` 1.44 MB,
   `cldf/cognates.csv` 607 KB). Measured overlap with our 1,099-lemma lexicon: 31 forms match
   exactly after normalisation, 21 more match deaccented, **272 have no form match** — i.e. the
   gain is not marginal. Caveat: these are IPA-style transcriptions, so importing them needs an
   explicit IPA→Marúbo-orthography mapping recorded as a normalisation step, not invented.
   `[V]`
3. **SIL Javari survey 2010 — a 375-item six-language comparative vocabulary that includes
   Marúbo.** Anonby & Holbrook, *A Survey of the Languages of the Javari River Valley, Brazil*,
   SILESR 2010-003. Appendix 1 (pp. 32–45) has columns Portuguese / English / Matís / Kulina Pano
   / **Marúbo** / Matsés, numbered **001–375** `[V]` (the lane reported 345; the appendix was
   counted directly). This is the largest retrievable Marúbo wordlist with an English concept
   column, so it maps to Concepticon and to the existing lexicon. Caveat: forms are typed in a
   legacy SIL phonetic font, so `pdftotext` yields mojibake (`ƒ‹\`ta`) — needs font mapping or
   vision OCR plus a human spot-check; the Marúbo column is the 5th of 6.
4. **Four CC-BY-4.0 CLDF datasets carrying real Marúbo forms** (all in `pano-takanan-history`,
   all verified by reading `cldf/forms.csv`): `oliveiraprotopanoan` (324 forms / 266 concepts /
   283 cognate-set members, Zenodo `10.5281/zenodo.10214016`), `zariquieypano` (187 forms /
   181 concepts, 100% Concepticon-linked, partial cognacy, Zenodo `10.5281/zenodo.20322670`),
   `valenzuelazariquieypanotakana` (25 forms, language id `Mar`, Zenodo `10.5281/zenodo.10212481`),
   `panobodyparts` (26 body-part forms, Zenodo `10.5281/zenodo.7318439`). ≈560 Marúbo rows before
   de-duplication. Plus **`imtvault` (Zenodo `10.5281/zenodo.19947331`): 97 glossed Marúbo IGT
   sentences** with analyzed words + glosses, though it re-packages the already-held Cesarino
   2017 chapter and is ritual register. Provenance flag: every `zariquieypano` Marúbo form is
   `fleck2005` "fieldnotes" (unpublished), so promote those only as `candidate`.
5. **eBible Panoan USFM: Matsés NT, Kashinawa NT, full Shipibo-Conibo Bible** (+ Yaminahua NT
   unverified). Verse-keyed, downloadable ZIPs (Wycliffe Bible Translators, 2008–2012; USFM
   confirmed for mcf/cbs/shp). Sharing versification with the USFM scripture already in
   `var/external/scriptureearth/mzr` enables **verse-aligned Marúbo↔Matsés↔Shipibo↔Kashinawa
   comparative tables** — hypothesis-generating evidence under invariant 8 and useful for Panoan
   transfer. `[V]`
6. **SIL e-Books 086 (2024), ch. 2: Melissa Ruth Smith, "Marubo Demonstratives: Providing
   Structure, Cohesion, and Referent Clarity in Discourse"** — IGT-shaped Marúbo form + gloss +
   English, the best alignment-evidence candidate found in the archives lane; a new Marúbo
   specialist name. Free at SIL but the PDF 403s to scripted clients → one human browser fetch
   `[W]`.
7. **Descriptive-grammar cluster.** C. Sean Smith 2021 MA thesis, *Aspects of switch reference
   in Marubo* (Trinity Western University) — **now retrieved** `[V]`: 114 pp., downloadable PDF
   at `https://twu.arcabc.ca/_flysystem/repo-bin/2021-05/twu_778.pdf`. It contains a language
   overview with phonology (§2.2), a review of previous Marúbo publications (§2.3), nine
   switch-reference markers each with glossed examples (§4.2–4.10), Panoan cognates (§4.11),
   **Appendix A** on even/odd syllable allomorphy, and **two fully transcribed/glossed
   narratives — Appendix B *Kamãne Pikẽnkẽã Yoã* (The Jaguar's Almost Eating Story) and
   Appendix C *Pani Aká* (To Make a Hammock)**. This is the single best new grammatical source
   found. Also relevant: **Costa 1998, "Aspects of ergativity in Marubo (Panoan)"**, *Journal of
   Amazonian Linguistics* 1(2), 27 pp., open PDF at
   `etnolinguistica.wdfiles.com/local--files/artigo:costa-1998/costa_1998_ergativity.pdf` `[V]`
   (this closes a lead that was unresolved in the first pass). Still closed: Smith 2024 "87
   Marubo" (De Gruyter, pp. 1037–1048), Fleck 2022 "Vestiges of body-part prefixation in Marubo"
   (OUP, pp. 401–424), Ruedas 2002 IJAL.
8. **Villada Castro 2016 (UFSC MA), triple-aligned chants.** Shamanic chants laid out in adjacent
   "Versão em Marubo / português / español" columns — the best line-aligned Marúbo↔PT↔ES text
   found. Ritual register; lineage must terminate at Cesarino's editions, not at the translator.
   Open access, no licence stated `[V]`. Related: Gontijo Flores 2019 (Cadernos de Tradução).
9. **Jaques 2021 (UFAM, 297 pp.) and Oliveira 2014 (UnB, 492 pp.).** Jaques is openly
   downloadable and contains a Marúbo grammar/phonemics appendix (Anexo A) plus a corpus of texts
   written by Marúbo students. Oliveira's dissertation is the **primary source behind the
   Proto-Panoan CLDF** and is open at `repositorio.unb.br/handle/10482/17129`. Both `[V]`.
10. **Living media with human translations (consent-bound).** CTI/UNIVAJA "Javari" film set on
    YouTube (`@TrabalhoIndigenista`): 6 films, 3 h 54 m, of which **3 h 20 m carries manual pt-BR
    subtitles** — the only place with indigenous speech + human PT translation + timecodes. The
    single Marúbo-language film (*Assim Aprendemos*, 33:18) is the one without manual subs.
    `VIMI MARUBO` (`@vimimarubo3341`, 30 videos, 47 min, everyday register) is a community
    channel. UNIVAJA's "Vozes do Javari" produces weekly radio/audio bulletins "traduzidas para
    a língua de cada povo" — Marúbo news audio exists and is non-public (`[V]` for the pages).
    YouTube captions are enumerable but not extractable without a PO token; no bypass attempted.
11. **Sister-Panoan transfer assets, now quantified.** AmericasNLP `shipibo_konibo-spanish`
    14,592 train pairs (2021/2024/2025 editions, no licence declared); HF
    `pollitoconpapass/spanish_2_shipibo_konibo` 30,180 pairs (no licence, no provenance);
    Common Voice Matsés `mcf` 11 validated hours / 21 speakers / 997 sentences (the only Panoan
    CV locale); UD Shipibo treebank 5,365 tokens + Kakataibo 1,262 tokens; UniMorph `shp`
    14,588 inflection rows; `keypano` CLDF 23,232 forms / 22 varieties (no Marúbo); MMS provides
    ASR+TTS for `shp`, `cbr`, `cbs`. `[V]`
12. **Model coverage reality:** Omnilingual ASR covers `mcf` (7.3 h train, CER 5.6), `shp`
    (27.1 h, CER 1.1) and `cbs` (33.1 h, CER 0.9) — **not `mzr`** (checked against the 1,668-entry
    `lang_ids.py`). NLLB-200/FLORES-200, Whisper, Seamless, Glot500, M2Lingual and Epitran
    contain zero Panoan languages. MMS gives `mzr` only a language-identification label. The
    published Panoan CERs are a usable benchmark floor for any future mzr model. `[V]`
13. **The largest gate-free Panoan text mass is sister-language scripture, not Marúbo.**
    ScriptureEarth data trees exist for 8 Panoan codes `[V]`: Cashinahua `cbs` has the **whole
    Bible in two parallel editions** (`…cbsBR-web.pdf` Brazil vs `…cbsP-web.pdf` Peru, ~31.1k
    verses each — a rare two-orthography comparison), Cashibo-Cacataibo `cbr` ~28.7k verses,
    Shipibo `shp` full Bible, Yaminawa `yaa` NT **plus 260 MP3s (complete NT audio)**, Matsés
    `mcf` NT, Chácobo `cao` NT, Amahuaca `amc` NT. Matis `mpu` and Korubo `xor` — two of the
    three sister profiles named in `docs/languages/mzr.md` — have **no ScriptureEarth presence**
    (404). eBible is the ingestible USFM route for `mcfNT`, `caoNT`, `cbrNT`, `shpNTpo`
    (`_usfm.zip` and `_vpl.zip`, © Wycliffe, class `redist`). `[V]`
14. **Portuguese pivot texts are available for alignment.** The repo already holds
    `var/external/parallel_por/` for exactly the 8 mzr books; eBible adds `pobr2018` (Bíblia
    Livre) and, more usefully, **`portft` (Tradução para Tradutores, a literal/structural
    translation)** — both `redist`. A literal pivot improves verse-level and sub-verse alignment
    quality over a literary translation. `[V]`

## 4. Findings by task

### A. Lexicon and structured lexical data — what can be ingested

| Resource | Marúbo volume | Licence | Access | Verdict |
|---|---|---|---|---|
| UFAM FLEX database (Pedrosa & Oliveira) | **13,382 lexemes** | none stated | unpublished; request from UFAM | highest yield, human action |
| `oliveiraprotopanoan` CLDF | 324 forms / 266 concepts | CC-BY-4.0 | GitHub / Zenodo | ingest first |
| `zariquieypano` CLDF | 187 forms / 181 concepts | CC-BY-4.0 (compiler) | GitHub / Zenodo | ingest, but `fleck2005` provenance needs a decision |
| `panobodyparts` CLDF | 26 body-part forms | CC-BY-4.0 | Zenodo | dedupe against `zariquieypano` |
| `valenzuelazariquieypanotakana` CLDF | 25 forms (id `Mar`) | CC-BY-4.0 | Zenodo | best provenance, small |
| SIL Javari survey 2010, Appendix 1 | 375 numbered concepts × 6 languages, Marúbo column | "© SIL International", free | Wayback copy of the PDF | ingest after OCR/font mapping |
| Museu Nacional dos Povos Indígenas (Tainacan) | ~8 object records with Marúbo forms (`rome rawe`, `bona tachota ya`) | `Livre` on object records | live catalogue | lexical fragments only; `Língua` = "Pano" family, not mzr |
| Grambank v1.0.3 | 195 codings (126 substantive) | CC-BY-4.0 | CLDF | typology priors, not lexicon |
| Numeralbank / Chan numerals | 14 / 29 numeral forms | mixed ("other-open" for Chan) | CLDF | small, check licence per dataset |
| ASJP v21 | 38 items (already held) | CC-BY-4.0 | CLDF | known |
| Common Voice `mcf` (Matsés) | 11 validated hours | gated HF terms | HF | sister-language speech |

### B. Sentence-level and parallel text

| Resource | Volume / shape | Register | Access |
|---|---|---|---|
| Cesarino 2017 IGT (held) | 105 pairs, already fully used | mythic narrative | held |
| `imtvault` CLDF | 97 glossed sentences (same source) | ritual/mythic | CC-BY-4.0 |
| *Vaná rasĩ* (CTI, 51 pp.) | Marúbo prose with facing Portuguese, paragraph level (plant/cultivation vocabulary) | pedagogical / ethnobotanical | open PDF `[V]` |
| Smith 2021, App. B/C (TWU) | two fully transcribed + glossed narratives (*Kamãne Pikẽnkẽã Yoã*, *Pani Aká*) | mythic narrative / procedural | downloadable PDF `[V]` |
| Costa 1998 (*J. Amazonian Linguistics*) | ergativity/split-S examples, 27 pp. | descriptive IGT | open PDF `[V]` |
| Villada Castro 2016 | chant stanzas, Marúbo/PT/ES columns | ritual | open PDF |
| Gontijo Flores 2019 | two chants, Marúbo vs PT | ritual | open PDF |
| Cesarino 2018 *Wenía* (SciELO) | PT translation + glossed terms, no facing Marúbo | ritual narrative | open |
| SIL e-Books 086 ch. 2 (Smith) | demonstratives, IGT-shaped | discourse | free, browser |
| eBible Panoan USFM | verse-keyed Matsés/Kashinawa/Shipibo | scripture | free ZIPs |
| CTI/UNIVAJA films | 3 h 20 m manual pt-BR subtitles (5 of 6 films) | everyday/documentary | YouTube ToS forbids download |
| ScriptureEarth mzr (held) | 9 books USFM + timing | scripture | held |

### C. Typology, morphology and phonology priors

- **Grambank**: 195 Marúbo codings, 44 present / 82 absent / 69 unknown, 98 comments, attributed
  to Costa 1998 and Costa & Dorigo 2005. Cheapest high-certainty priors; the clld HTML page shows
  an empty table, so read `cldf/values.csv`.
- **Valenzuela & Oliveira 2022 (LIAMES, CC BY-NC 4.0)**: five graded-tense markers (`-katsai`,
  `-katsa`, `-ai`) with split-ergativity/negation interaction `[V]`.
- **Costa & Dorigo 2013 (Letras de Hoje, CC BY 4.0)**: Marúbo vs Matsés nasal coda, minimal
  pairs — the only explicitly CC-BY Marúbo data article found; scanned, no text layer.
- **Fleck 2022 (OUP)** body-part prefixation and **Smith 2024 (De Gruyter)** onomatopoeia:
  closed access, high value.
- **PHOIBLE has no Marúbo inventory** (16 Panoan inventories, zero `mzr`), so the phoneme
  inventory must come from Costa 2000 / Kennell 1978 or be derived from the CLDF `Segments`.
- **ELCat as CLDF**: 27 metadata values, "Threatened" at 20% certainty, four conflicting speaker
  counts (1,000–9,999 / 1,252 / 1,043 / 594) — keep the conflicts rather than choosing one.

### D. Speech, audio and living media

| Item | Volume | Transcript? | Constraint |
|---|---|---|---|
| CTI/UNIVAJA Javari films | 3 h 54 m | manual pt-BR subs for 3 h 20 m | YouTube ToS; consent |
| `VIMI MARUBO` channel | 30 videos / 47 min | none | consent; platform ToS |
| UNIVAJA "Vozes do Javari" radio/WhatsApp | weekly, unknown | unknown, non-public | needs relationship |
| Rádio Nacional do Alto Solimões | live stream only | no archive | no transcripts |
| ScriptureEarth mzr audio/timing (held) | 9 books | USFM text | held |
| GRN *Palavras de Vida* (indexed) | unknown | scripts exist? | unverified |
| Common Voice `mcf` | 11 validated h | sentence prompts | gated |

### E. Model artifacts and evaluation baselines

- **Omnilingual ASR**: apache-2.0 weights; `mcf`/`shp`/`cbs` supported with published CERs;
  `mzr` absent → use the Panoan CERs as the target band and `omniASR_LLM_7B_ZS` zero-shot path
  for `mzr`. Its public corpus release is only 348 languages with zero Panoan — the "1,600
  languages" claim is training mix, not data.
- **MMS**: `mzr` has a language-identification label only; ASR/TTS exist for `shp`, `cbr`, `cbs`
  (useful for synthetic Panoan speech probes).
- **Shipibo POS taggers** (`floressullon/shipibo_pos_tagging_v{1,2,3}`, MIT, F1 .93) and the
  `chana` toolkit (MIT) are architecture templates for a future mzr pipeline.
- **Apron of negatives**: NLLB-200/FLORES-200 (204 codes), Whisper (100), Seamless (96),
  Glot500 (411), M2Lingual (58), OPUS (1,064 codes), Epitran (162 G2P maps) — none contain a
  Panoan language `[V]`.

### F. Archives and institutions (lane 03)

- No archive holds Marúbo *language-documentation* deposits. ELAR 0, MPI/TLA 0, CLA 0,
  Pangloss 0, Getty 0 — all verified; **AILLA and PARADISEC are bot-walled, not negative**
  (AILLA is the biggest open question and needs a browser).
- Trap: ELAR's two items titled "…the Marubo Indians" are **Kulina Pano/Matsés speech about**
  Marúbo, recorded in Peru, inside Fleck's deposit `mayoruna-fleck-0111`.
- Trap: TLA's 142 "matsés" hits are Murui/Witoto, not Panoan.
- ELAR's genuine Panoan inventory (hypotheses only): Cashibo-Cacataibo 344, Matsés 287,
  Kulina Pano 267, Yaminahua 36, Nahua 25, Chankueshbo 13.
- Museu Nacional dos Povos Indígenas Tainacan catalogue is the only Brazilian institution with
  Marúbo-language object labels; the Delvair Melatti 1975 collection is a path to field material.
- ISA lists 5 CPCE ethnographic videos (1991–1995, Betacam) — title-level only, preservation risk.
- Verified infrastructure deaths: `acervo.museudoindio.gov.br`, `prodoc.museudoindio.gov.br`,
  `opir.org.br`, `cti.org.br`, `videonasaldeias.org.br` catalogue, Museu Goeldi and Museu
  Nacional/UFRJ hosts. Consent route therefore runs via FUNAI Atalaia do Norte / ISA / CIMI.

### G. Panoan scripture inventory and pivots (lane 04)

| Language | ScriptureEarth | eBible USFM route | Notes |
|---|---|---|---|
| `mzr` Marúbo | **audio only**: 162 chapter MP3s, 8 books; no USFM/PDF; empty `audio/timing/` | — | our held USFM provenance needs re-verification (§1.9) |
| `cbs` Cashinahua | **whole Bible ×2 editions**, ~31.1k verses each | `cbsNT` | two-orthography comparison; duplicate-policy record needed |
| `cbr` Cashibo-Cacataibo | ~28.7k verses | `cbrNT` | |
| `shp` Shipibo-Konibo | full Bible | `shpNTpo` | also the NLLB seeding language |
| `yaa` Yaminawa | NT text + **260 MP3s (complete NT audio)** | `yaaNT` `[U]` | audio+text pair worth evaluating |
| `mcf` Matsés | NT | `mcfNT` | also Common Voice `mcf` (11 h) |
| `cao` Chácobo | NT | `caoNT` | |
| `amc` Amahuaca | NT | — | |
| `mpu` Matis, `xor` Korubo | **none (404)** | — | the other two in-repo sister profiles |
| Portuguese pivot | — | `pobr2018` (Bíblia Livre), `portft` (literal) | `portft` is the better alignment pivot |

Quarantine: Door43's ten `mzr_*_text_reg` repos are **not Marúbo** (§1.10) — never ingest.

### H. Conflict resolutions (direct checks)

| Conflict | Resolution |
|---|---|
| `valenzuelazariquieypanotakana` Marúbo count: 25 (lane 01) vs 52/37 (lane 06) | forms.csv keys Marúbo as `Mar` = **25 rows**; 52 is `Mar` + `ReyMar` (27), a different variety. Use 25. |
| SIL survey item count: 345 (lane 02) vs mine | Appendix 1 numbered **001–375** (8 pages) — counted directly. |
| OPUS negative: "probable" (me) vs confirmed (lane 06) | lane 06's `?languages=True` check was superseded by lane 04's full API dump (65,771 records, 1,063 codes, none Panoan) → **confirmed negative**. |
| `oliveiraprotopanoan` volume | 324 forms / 266 concepts confirmed independently by two lanes and by direct parse. |
| BDTD "Marubo" records | 15 total, only 3 with Marubo in the title: Costa 1992, Costa 2000 (held) + Jaques 2021 (new). |
| Cross-lane confirmation as trust signal | UFAM FLEX database, Jaques 2021, SIL Javari survey, and the Smith 2021 thesis each surfaced in two independent lanes. |

## 5. Confirmed negatives (with method)

All checked on 2026-10-18. A negative here means "checked by the method named"; it does not mean
"does not exist anywhere".

| Negative | Method |
|---|---|
| No Marúbo Bible on eBible | fetched full `ebible.org/Scriptures/` index (763 KB), grep for `mzr`/Marubo → 0 `[V]` |
| MMS has no Marúbo adapter | listed `facebook/mms-1b-all` tree (3,606 files), no `adapter.mzr.*` `[V]` |
| No `mzr` in Omnilingual ASR | parsed the 1,668-entry `lang_ids.py`; `mcf`/`shp`/`cbs` present, `mzr` absent `[V]` |
| No Marúbo/Panoan dataset on HuggingFace datasets | HF datasets API search for marubo, panoan and matses → `[]` `[V]` |
| No Panoan corpus in OPUS | full API dump: **65,771 records, 1,063 language codes**, none of `mzr shp cbs yaa cao amc cbr mcf` — stronger than the earlier page scrape, and it shows the old method was unsound `[V]` |
| No Marúbo on Tatoeba | API returns HTTP 400 "Invalid language code 'shp'" `[V]` |
| No Panoan Wikipedia / Wikimedia content | Wikimedia SiteMatrix: 374 languages, none Panoan; `Wp/mzr` does not exist `[V]` |
| No Marúbo in mC4 | mC4 language list: 108 languages, no `mzr` `[V]` |
| JW.org has `shp` + `mcf`, no `mzr`, and forbids harvesting | JW catalogue JSON `[V]`; terms of use explicitly ban collection tools → gated, not merely copyrighted |
| Door43 `mzr_*` repos are not Marúbo | 0/25 function-word overlap, 2/30 folded; no `th`/final `-ng` in our lexicon; committer UTC+07:00 `[V]` → quarantine |
| No NLLB-200 / FLORES-200 / Whisper / Seamless / Glot500 / M2Lingual / Epitran Panoan coverage | their own language lists / model configs `[V]` |
| No Marúbo in IDS (319 langs), `idssegmented` (268) or `keypano` (22 varieties) | `cldf/languages.csv` per dataset `[V]` |
| No Marúbo in WALS (3,573 lects), PHOIBLE (no `mzr` inventory), Dictionaria, Tsammalex, Wikidata lexemes, en/pt Wiktionary | per-dataset CSV / API `[V]` |
| No Marúbo language-documentation deposit at ELAR, MPI/TLA, CLA Berkeley, Pangloss, Getty | each archive's own search endpoint `[V]` |
| Glottolog's 59-entry Marúbo bibliography is the bibliography source of record | resolved `md.ini` `[sources]` keys; Glottolog has no `.bib` export (406) `[V]` |
| `Banco de Dados` DOI in OpenAlex is truncated | truncated DOI → 404; corrected DOI `…-380957.768609` resolves `[V]` |
| BDTD has only 3 Marubo-titled theses | BDTD VuFind API, `lookfor=Marubo` (15 records) + per-record metadata `[V]` |
| St Andrews thesis *Emerging peoples: Marubo myth-chants* unreachable | repository returned HTTP 503 `[U]`, retry |
| No Marúbo podcast/audio on Apple, Deezer, Mixcloud, SoundCloud, Internet Archive; no Marúbo blog | platform search/APIs `[V]` |
| GitHub search `marubo` = 44 repos, all false positives (MaruBot bots, marubozu) | `api.github.com/search/repositories` `[V]` |
| Trap: "Marubo" is a Boi-Bumbá toada keyword; "Maru" `mru`/`mhx` is Burmese Loloish; TLA "matsés" hits are Murui/Witoto; ELAR's "…Marubo Indians" items are Kulina Pano *about* Marúbo | recorded per lane §negatives `[V]` |

**Still unverified, not negative:** AILLA (Anubis wall), PARADISEC (WAF 403), Smithsonian,
Library of Congress, British Museum, quai Branly, IAI Berlin, PanLex (DNS NXDOMAIN),
`endangeredlanguages.com` (TCP timeout), MINEDU Peru (Check Point), TWU/ArcaBC (captcha).
These need one human with a browser.

## 6. Governance notes

- Under ADR-0025, everything catalogued here is usable for local processing **and training once
  present in the repo**. What still matters: recording `source_id`/provenance per row (the
  eligibility gate is traceability-only), the rights holder (for attribution and to honor a later
  revocation), and `exclude` if a community objects.
- ADR-0025 changes the pipeline, not the platforms. YouTube/TikTok terms forbid downloading
  without permission, and presence-based authorization does not cure the consent gap for
  identifiable Marúbo speakers. Acquire community media only with permission, routed through
  FUNAI Atalaia do Norte / ISA / CIMI now that OPIR and CTI hosts are dead.
- Register: ISA states the modern Marúbo language "possesses a ritual counterpart" with a parallel
  vocabulary in myths and curing chants. Chant-derived sources (Villada, Gontijo Flores, Cesarino
  2017/2023, IMTVault) should carry a `ritual_restricted` review flag even where CC-BY.
- Invariant 8 still governs use: Matsés/Kashinawa/Shipibo/Chacobo forms may create **hypotheses**
  about Marúbo, never `validated` Marúbo truth. Invariant 9 forbids letting a model invent missing
  Marúbo forms; the CLDF and FLEX finds matter precisely because they are observed strings.

## 7. Ranked next actions

| # | Action | Effort | Expected gain |
|---|---|---|---|
| 1 | Request the UFAM FLEX DB (13,382 lexemes) + the 117-page source book from Pedrosa / Oliveira (UFAM, `sanderson@ufam.edu.br`) | medium | largest single lexical gain, ~12× current lexicon |
| 2 | Ingest the four CC-BY CLDF datasets; start with `oliveiraprotopanoan` (324 forms / 266 concepts), record the IPA→orthography normalisation | low | lexicon breadth + cognate hypotheses |
| 3 | Fetch SIL Javari survey 2010 Appendix 1 (375 concepts × 6 languages) and font-map/OCR the Marúbo column | low-medium | a complete 375-concept Marúbo wordlist with English glosses |
| 4 | Fetch SIL e-Books 086 ch. 2 (Marúbo demonstratives) with a browser; extract IGT | low | sentence-level discourse evidence |
| 5 | Download eBible `mcfNT`, `cbsNT`, `shpNTpo` USFM; build verse-aligned Panoan comparison tables | low | cross-Panoan morphology evidence |
| 6 | ~~Re-extract Cesarino 2013 with layout-aware parsing and validate before use~~ **done 2026-10-18**: `extract_pairs.py columns` (3,951 pairs, validators + page-image checks); the only remaining limit is the source's OCR, not the parsing | done | large narrative source now aligned as evidence |
| 7 | Acquire Smith 2021 TWU thesis and the Smith 2024 / Fleck 2022 chapters | medium | the missing grammatical description |
| 8 | Ask UNIVAJA / OAMI about "Vozes do Javari" Marúbo bulletins and the CTI film set's Marúbo-language material | medium | only route to spoken/new register and audio |
| 9 | Use Omnilingual ASR Panoan CERs (mcf 5.6 / shp 1.1 / cbs 0.9) as the benchmark band; `mzr` needs zero-shot path | low | an honest ASR baseline |
| 10 | ~~Rebalance splits: stop letting the 100 non-scripture rows dominate the test set; enforce a scripture cap~~ **done 2026-10-18**: `synth export --max-register-share` (default 0.20) caps each harvested register in test/val against the scripture block; overflow goes to train. mzr test 300 → 250 (200 scripture + 25 Wenía + 25 Cesarino 2017), train +50, val unchanged. Rules in `docs/EVALUATION.md` "Benchmark composition" | low | honest evaluation |
| 11 | Re-verify the mzr USFM lineage record against the live ScriptureEarth tree (no USFM is published there) | low | lineage integrity |
| 12 | Acquire the 162 mzr chapter MP3s and prototype audio→text alignment; no verse timing is published, so timing must be produced locally | medium | spoken evidence, MFA/G2P work |
| 13 | Quarantine the Door43 `mzr_*` repos in the registry with the evidence, so no future ingest mistakes them | low | prevents a poisoning error |
| 14 | Keep `porbr2018` as the primary pivot and add `portft` as a **second, tagged** pivot (do not swap: `porbr2018` is CC BY 4.0 BR, © 2018 Diego Santos/Mario Sérgio/Marco Teles) | low | comparison axis without losing the verified pivot |
| 15 | ~~Repair the in-repo Cesarino 2013 OCR and extract its stanza-aligned mzr↔por pairs~~ **done 2026-10-18, with a correction**: 3,951 **line**-aligned pairs extracted + Portuguese repaired (408 deterministic repairs); *Marúbo* diacritics are unrecoverable from this scan, so the pairs ship as candidates. The clean transcription this action asked for was then found — but for a different chant (see 15c) | done / blocked | closes the "largest immediately available pair source" assumption |
| 15c | ~~Find a clean digital transcription of the chant text~~ **done 2026-10-18**: acquired Cesarino 2018 *Wenía* (born-digital, Microsoft-Word PDF, diacritics intact), registered as `wenia-2018`, extracted **921 clean mzr↔por verse pairs / 2,401 tokens** into `exports/harvested_parallel/` (`extract_pairs.py table`); zero residual damage. It is a different chant from the book's twelve (162 shared formulaic refrains only), so the 2013 blocker 15 stands | done | 10× the attested mzr pair inventory |
| 15d | Re-run `langpipe synth export` so the 921 Wenía pairs reach `exports/mzr/datasets/`, then rebalance splits (they are already in the loader's input glob). **Status 2026-10-18**: rebalanced export built and checked in `var/artifacts/t4/after` (Wenía: 646 train / 25 val / 25 test after dedup); promotion into `exports/mzr/datasets/` pending | low | new clean pairs actually reach training |
| 15e | **Review and promote the cited clean forms**: `exports/parallel_candidates/cesarino_2013_clean_refs.jsonl` cites 285 book rows from a born-digital source, 167 of them adding a nasal mark the scan lost (Villada Castro 2018, *Mundo Amazónico*; 2 rows verified against page images, all 285 verbatim in the cited PDF). Promotion = write `clean_src` as the vernacular side with the citation attached | low | first real recovery of the 2013 chant marks |
| 15f | Fetch `dominiopublico.gov.br/download/texto/cp059749.pdf` (2008 UFRJ thesis, 3.67 MB) from a **browser session** and read the font tables; its scraped text has font-slot control bytes (`Ko\x03` = `Koĩ`), so only the real PDF can turn the thesis into a citation source for the remaining ~3,600 rows | medium | largest remaining unblock for the 2013 book |
| 15a | Ingest *Vaná rasĩ* block-parallel sections: lane 04b counts ≈4.7k Marúbo tokens and 165 cultivars; our monolingual pass captured 19 blocks (partial) | medium | third register, community-authored |
| 15b | Record the settled scripture licence (CC BY-NC-ND 4.0, MNTB/WBT) and resolve the LUK/ACT provenance question | low | removes a lineage gap |
| 15b | Download Smith 2021 (TWU) and Costa 1998; extract Appendix B/C glossed narratives and the ergativity examples | low | new sentence-level IGT that is retrievable today |
| 16 | Survey Acervo Yurará Sin, the CIMI/Trabalho Indigenista library and the ELCat bibliography for further Marúbo items | medium | unknown volume, likely more text and media |
| 17 | Restart the DSH web app so the `deepseek-official` search override takes effect, then re-run the thin lanes with real search | low | closes the remaining `[U]` items |

## 8. Limitations

- **All six lanes completed**, but general web search was unusable for most of the run:
  DuckDuckGo HTML/Lite returned HTTP 202 bot challenges, Bing HTML and RSS silently degrade or
  geo-personalise (a query for "switch reference Marubo" returned Nintendo Switch results),
  Mojeek/Searx/Brave/Ecosia returned 403 or captcha, Semantic Scholar 429'd throughout, and
  several `.br`/`.pe` hosts (`periodicos.unb.br`, `riu.ufam.edu.br`, `repositorio.umssa`,
  `cybertesis.unmsm`) refused TCP connections. Everything usable came from direct APIs
  (OpenAlex, Crossref, DataCite, DOAJ, OpenAIRE, BDTD VuFind, DSpace REST, Zenodo, HF, platform
  APIs) and the Wayback Machine. **Consequence: "not found" in this digest is weak evidence for
  government/community materials, gated archives and live platforms — report those as `[U]`,
  never as confirmed absence.**
- **`web_fetch` silently drops CLLD tables** (Grambank, PHOIBLE, IDS, Dictionaria render as empty
  tables). Every presence claim here was re-checked against CSV/JSON data files; anyone repeating
  the survey must do the same or will record false negatives.
- Gated catalogues (AILLA, PARADISEC, Smithsonian, Library of Congress, British Museum, quai
  Branly, IAI Berlin, TWU) were not inspected; account creation and captcha solving are out of
  scope for agents and remain human steps. AILLA is the largest open question for Panoan audio.
- Panoan orthographies vary between sources (IPA in CLDF, legacy SIL font in the 2010 survey,
  Costa's practical orthography in the repo). Row-level imports must not be merged without an
  explicit normalisation record; `Value == Form` in `oliveiraprotopanoan` means the raw spelling
  was not preserved there.
- Register is underexplored: ISA states Marúbo has a ritual counterpart with a parallel
  vocabulary in myths and curing chants. Several chant sources are catalogued, but no register
  review has happened, so none should be trained on yet.
- This survey catalogues; it downloads nothing into the repo. `var/` ingestion is a human step
  under the raw-source immutability rule.



---

## 9. Follow-up pass — DeepSeek Search enabled (same day, 2026-10-18)

The first pass ran without working web search (see Limitations). Later the same day DeepSeek's
own search became usable, which changed several `[W]`/`[U]` items into `[V]`. Two routes exist
and both are documented in `scripts/deepseek_search.py`:

- **`server-tool` (default, free window).** An Anthropic-compatible `/messages` call carrying the
  `web_search_20250305` server tool — the same mechanism DeepSeek Harness uses. DeepSeek bills
  these server-side search calls **free of charge until 2026-11-01 00:00 Beijing**; only the
  supporting model turn is billed. This is the route to prefer while it lasts.
- **`tools`.** Raw `POST /v1/tools/search` / `/v1/tools/fetch`. Richer payload (summary, content,
  authority, date) but billed at $0.75 per 1,000 successful requests.

The harness itself was also misconfigured: the `dsh-free-search` bundle pointed
`web.searchProvider` at `ddg`, a provider not registered in the running build, so every
`web_search` failed. `~/.dsh/profiles/web/cordis.patch.yml` now overrides that back to
`deepseek-official` (the shipped provider); the override takes effect on the next GUI restart.

### Items closed or corrected by this pass

| Item | Before | After |
|---|---|---|
| Smith 2021 TWU thesis (switch reference) | captcha-blocked `[W]` | **downloadable `[V]`**, 114 pp., `twu.arcabc.ca/_flysystem/repo-bin/2021-05/twu_778.pdf`; two glossed narratives (App. B, C) + phonology overview + 9 SR markers |
| Costa 1998, "Aspects of ergativity in Marubo (Panoan)", *J. Amazonian Linguistics* 1(2) | unidentified lead `[U]` | **open PDF `[V]`**, 27 pp., `etnolinguistica.wdfiles.com/local--files/artigo:costa-1998/costa_1998_ergativity.pdf` — core split-ergativity IGT |
| *Emerging peoples: Marubo myth-chants* (St Andrews/‘Couto 2001’) | repository 503 `[U]` | **open PDF `[V]`**, but the attribution was wrong: it is **Guilherme Werlang, *Emerging Peoples: Marubo Myth-Chants*, LIT Verlag 2011, 714 pp.**, hosted at `acervoyurarasin.com.br`. It is an **English-language monograph on *saiti* myth-chants — no facing Marúbo text** (0 lines in Marúbo orthography in 23k extracted lines), so it is ethnographic/narrative reference, not parallel data. |
| Zenodo `17167246` | — | **II Seminário Amazônia em Letras (UFAM/UEA, 2025) abstract book, CC-BY-4.0** `[V]`; contains a "Vocabulário da Língua Marubo" PIBIC report — a second, independent UFAM lexical project (digitisation + orthography revision) beyond the FLEX database. |
| New archive leads | — | **Acervo Yurará Sin** (`acervoyurarasin.com.br`, Tainacan collection with Marúbo items), **Biblioteca do Trabalho Indigenista / CIMI** (`biblioteca.trabalhoindigenista.org.br`), **ELCat bibliography** (`elcat.colo.hawaii.edu/lang/3008/bibliography`) and the **Pavia DEmA** database (Marúbo alignment examples) — all reachable `[V]`; each needs a survey pass of its own. |
| **OLAC / Open Language Archive Search** | no data | queried the OLAC Elasticsearch index directly (`search.language-archives.org/elastic/olac-search/_search`): **0 records** for `dc.language.olac.language = mzr`, 0 for `glottolog.id = maru1252` beyond the Glottolog catalogue row, 0 for AILLA records at all. So **no OLAC-harvested archive holds a Marúbo deposit**; AILLA itself is not in the OLAC index, so AILLA stays unknown rather than negative. |
| *Vaná rasĩ — As plantas que cultivamos na roça* | — | **new `[V]`**: CTI publication, 51 pp., authored by Manoel Corrêas Marubo and Davi Martins Rodrigues Marubo, **Marúbo prose in one column with the Portuguese translation facing it**. Open PDF at `biblioteca.trabalhoindigenista.org.br`. This is the first Marúbo↔Portuguese parallel text found outside scripture/chants, in the pedagogical/ethnobotanical register. |
| Fleck 2013, *Panoan Languages and Linguistics* (AMNH AP 99) | AMNH page 202 `[U]` | **`[V]`**: 116 pp. PDF resolved through the AMNH DSpace API — the bibliographic gateway to Panoan sources. |
| **AILLA — the hole is closed** | Anubis `[U]` | **AILLA does hold Marúbo, and it is public.** Two resources in the Ernest Migliazza collection, recorded Rio Ituí, Amazonas, **1976-07-23**: `ailla:125121` "Word List and Songs / Vocabulario y Canciones" (wordlist + song genres, speaker Juan Janisio, **0:55:04**, cassette→archived 2004-11-04) and `ailla:125122` "Stories / Cuentos" (narrative). Language object `ailla:119566`: Marúbo · Panoan · Brazil · **Access Level 1 = Public**. Metadata recovered via Wayback playback because Anubis v1.27 walls every path including `/datastream/*` and `/oai`. |
| **Why every AILLA query failed** | — | **AILLA indexes Marúbo under its own legacy code `qkf`, not `mzr`.** `site:ailla.utexas.org mzr` could never match. `qkf` is now recorded in preflight §1 and in the registry's `mzr.query_aliases`; any future archive query must use both codes. |
| **Biblioteca Digital CTI** | dead host `[U]` | **CTI is alive, relocated.** `cti.org.br` is still NXDOMAIN, but `biblioteca.trabalhoindigenista.org.br` is live and is the richest Marúbo publisher found: *Vaná rasĩ* (bilingual, community-authored, 166 named cultivars), **`Pinturas Marubo` (2021, 168 pp., ≈45–50 named `kene`, "© Todos os direitos reservados ao povo Marubo")**, and **`Os Marubo e os bichos de casco do rio Ituí` (2021, 57 pp., folk taxonomy)**. The last two are open and not yet ingested. |
| **Acervo Yurará Sin** | front end 500 | Tainacan API still works: **64 Marúbo items**, including *Cânticos Xamânicos dos Marúbo*, a scan of a Marúbo-authored text (*Texto do Darcy Marubo*), and *NOKẼ MEVI REVÕSHO SHOVIMA AWE*. Item files are not linked but `wp-content/uploads/tainacan-items/...` paths return 200 when known. |
| Pavia DEmA | — | Marúbo page `id=13`, Glottocode `maru1252`, **3 glossed IGT clauses** (e.g. `Ɨa-n 'matu-Ø ɨn-ʃu'tun-ai` 'I have pushed you') — tertiary (Siewierska 2004 via Ganfi 2016), low volume, real IGT shape. |
| Settled archive negatives | — | **World Oral Literature Project** is alive at `oralliterature.org` (the old lane tried the dead `worldoral.org`): 0 Marúbo/Panoan. **museum-digital** JSON backend: marubo 0, marúbo 0, javari 0, while **shipibo → 38** (positive control) and pano → 4 → real negative. **ELCat** page states "There are no samples of Marubo yet"; bibliography = 6 citations. **PARADISEC** site search "Nothing Found" (weak, catalogue still WAF-403). |
| Audio/video | — | **Still no timecoded or transcribed Marúbo recording anywhere.** Best scoped audio: AILLA 1976 (55 min). The 1991 film *Marubo: uma tribo na Amazônia* is now online (`youtu.be/b0pxE7J3i3Q`), as are `VARIN MEMA` (`youtu.be/jm3syCZFnhI`), a urna/Seção 37 item and an adornos/símbolos item. A **named cassette lead**: *Vaná rasĩ* says Javier Ruedas taped *vana viki* knowledge on cassettes in 1997, later typed up with FUNAI/CIMI help — an inquiry, not a search. |
| **YouVersion — Marúbo IS present** | negative `[V]` | Version **4026 / `YKV` "Yové Koĩni Vana"**, publisher Wycliffe Bible Translators. Settles the old "no Marúbo on YouVersion" claim. Coverage per the published listing: GEN / EXO 1–20 / RUT / NEH / JHN / JAS. Text acquisition is forbidden by its ToU and was not attempted. |
| **mzr scripture licence and rights holder** | "no rights statement" | **CC BY-NC-ND 4.0**, "© 2023-2025, Missão Novas Tribos do Brasil; Wycliffe Bible Translators, Inc." (from the official ScriptureEarth app listing) `[V]`. That coverage makes the local corpus's **LUK and ACT** a provenance question — they are not in the published book set. |
| **Portuguese pivot identified** | "no licence recorded" | `var/external/parallel_por/` is the **Bíblia Livre (`porbr2018`)**, matched verbatim (GEN 2:1–5). The `mzr` text carries Portuguese-form proper names only (`Moisés` 95, `Jerusalém` 21, `Cristo` 47, `Pilatos` 10, `Paulo` 117; zero `Moses/David/Jerusalem/Christ`), so the PT pivot is plausibly translation-equivalent, not merely verse-aligned. |
| **Cesarino 2013 in-repo alignment** | "OCR-degraded, unusable" | **Line-aligned mzr↔por: 3,951 row pairs / 10,302 tokens** (extracted 2026-10-18, `extract_pairs.py columns`). Pairing is verified against page images; the Portuguese side is repaired deterministically (408 repairs). **The Marúbo side cannot be healed from this scan**: the OCR drops the printed `ẽ ĩ ũ ã õ`/macron marks entirely. 753 rows (19.1 %) screen clean against the reference vocabulary; the rest are candidates. **Partial recovery found**: 285 rows now carry a cited clean form from a born-digital work (`cesarino_2013_clean_refs.jsonl`, 167 of them add a lost nasal mark), and 2 rows were verified against the page images. Shipped as `exports/parallel_candidates/` (alignment evidence), not as training data. |
| **Villada Castro 2018** (Mundo Amazónico, DOI 10.15446/ma.v9n1.64860) | — | **Acquired 2026-10-18**: born-digital Spanish-language analysis that quotes the book's *Kaná kawã*, *Rome Owe Romeya* and *Roka* chants **with the diacritics intact** — the citation key for 292 of the 2013 rows. Registered as `villada-2018`. It is a secondary citation of the printed text, so its forms are evidence, never an overwrite. |
| **Cesarino 2008 UFRJ doctorate** | "USP thesis, unreachable" | **Corrected twice**: it is *UFRJ* (Museu Nacional, 469 pp. in the deposited PDF — the catalogue's 472 counts 12 bound preliminary leaves; the thesis's own ficha says "469 pp., xii pp." — advisor Viveiros de Castro), and `teses.usp.br`'s legacy `pt-br.php` tree returns 400 to **everyone**, not to our IP. The CAPES PDF is `dominiopublico.gov.br/download/texto/cp059749.pdf`, Cloudflare-gated; only an HTML rendering could be scraped, and its font map is broken (nasal i/e = base vowel + glyph-slot control byte: `Ko\x03` = `Koĩ`, so the naive decode produces `Ko Naí`). Lead for 15f, not a source. |
| **Second UFAM lexical project** | — | The 2025 "Vocabulário da Língua Marubo" (CONIC 2024/25, Francisca Kailanny Rodrigues Pinto with Sanderson Castro de Oliveira, UFAM) reports **12,571 consolidated FLEx entries and 12 digitised Marúbo materials** — a *different* project from Pedrosa/Oliveira's 13,382-entry database, also unpublished. One request to UFAM can cover both. |
| **CTI library enumerated** | — | 69-item collection: **3 Marúbo books + 5 school booklets**. Trap: the celebrated *Série Oralidade* booklets are **wordless drawing books**, not text. |
| Tatoeba / CC-derived corpora | — | **Tatoeba**: all ten Panoan codes return HTTP 400 "Invalid language code" (control `por` → 445k sentences; the `lang` whitelist is narrower than the catalogue, so the safe claim is "no Panoan sentence retrievable"). **mC4, HPLT 2.0, FineWeb-2** all lack `mzr` `[V]`. OSCAR-2301 is gated (401), not a negative. |
| **`cesarino_2018_wenia`** (SciELO, DOI 10.1590/2316-4018533) | — | **Acquired 2026-10-18 and extracted**: 921 Marúbo chant verses, each printed beside its Portuguese translation, line-numbered every fifth verse. The PDF is born-digital (Microsoft Word 2010), so the text layer **keeps the diacritics the 2013 scan lost** — this is the clean transcription the 2013 blocker pointed at, except that it is a different chant. Registered as `wenia-2018`, licence CC BY-NC 4.0 per the SciELO record (metadata, not a gate), 921 pairs in `exports/harvested_parallel/`. |
| **`dollis_2022_noke_yora`** | — | A **183 pp. Marúbo-authored dissertation** with **2,538 lines in Marúbo orthography** — the largest Marúbo-authored text lead found; not yet quantified or acquired. |
| **`cti_palavras_matis`** (mpu) | — | The only Matis lexical artefact found anywhere: 97-page **scanned** PDF with no text layer (`[W]`; OCR needed). Sister-language only (invariant 8). |
| **Pivot accounting** | — | `porbr2018` has **6,382** verses for the same 8 books where mzr has **5,389** (EXO 540 vs 1,213; NEH 124 vs 406). Join left on mzr availability and carry `mzr_missing` explicitly instead of silently dropping verses. |
| **Door43 second control** | — | The mis-code is now confirmed against a second Marúbo corpus (*Vaná rasĩ*): 0/25 function-word overlap; `kowi/uowi/chowng/khai` absent from Marúbo, `iki/nawa/vaná/yora/aká` absent from Door43. Settled for ingestion purposes. |
| Still unreadable (never record as empty) | — | **Smithsonian NMAI/HSFA** (the likeliest US holder of 1970s Javari film/audio: `collections.si.edu` 403, `api.si.edu` needs a key), British Library, quai Branly, IAI Berlin, British Museum, MPEG/MAE-USP/Museu Nacional/INPA, OLAC (`search.language-archives.org` answered NXDOMAIN to the lane), and whether AILLA holds Marúbo beyond the Migliazza deposit. |
| Santa Barbara Papers in Linguistics vol. 10 (Costa, case marking) | lead `[W]` | cited UCSB PDF path returns **404** — still `[U]`; try Wayback or UCSB eScholarship. |
| Fleck 2013, *Panoan Languages and Linguistics* (AMNH AP 99) | — | AMNH item page answers HTTP 202 to scripts `[U]`; the bibliographic gateway, worth a browser fetch. |
| "~64 h of *saiti* chant recordings held by ASDEC" claim | — | **unverified**: the ASDEC document located is a 2-page COVID emergency letter, not an archive description. Do not cite the hours. |

The practical consequence: the survey's "no new Marúbo text exists" headline holds for *web
corpora*, but the **sentence-level IGT available to the project just grew** — Smith 2021's two
glossed narratives and Costa 1998's ergativity examples are retrievable today, and Costa 1998 was
already a cited-but-unlocated source in the repo's own bibliography chain.
