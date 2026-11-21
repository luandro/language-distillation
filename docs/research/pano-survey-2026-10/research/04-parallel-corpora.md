# Lane 04 — Parallel corpora and translation text (Marúbo `mzr` / Panoan)

Survey date: **2026-10-18**. Lane: scripture/translation platforms, corpus aggregators,
government/school materials, related-language parallel data.
Target: Marúbo, ISO 639-3 `mzr`, Glottolog `maru1252`; contact language Portuguese (`por`).
No corpus bytes were downloaded. No accounts created. No repo files edited except this report.

**Status key used throughout**

| Tag | Meaning |
|---|---|
| `[V]` | Verified this session — I fetched the page/API myself and read the evidence quoted. |
| `[W]` | Weak — rests on an inference, a single indirect signal, or partial evidence. |
| `[U]` | Unverified — could not be reached, or the fact is asserted by a third party only. |

**Classification key (mission-mandated)**

| Tag | Meaning |
|---|---|
| **(a)** | Already in the repo and known (preflight §2 list) — reported only for new detail. |
| **(b)** | New **and downloadable by an agent** (public HTTP, no login, no bot wall). |
| **(c)** | New but **gated** (login, API key, bot challenge, or terms that forbid acquisition). |
| **(d)** | Confirmed **negative**, with the method named. |

---

## 0. Two findings that change how this lane should be read

### 0.1 The governance premise in my brief is superseded (ADR-0025)

My mission text said "`distill_only` scripture may never enter a trainable dataset
directly; aligned pairs need the ADR-0022/0023 gates." That is no longer the operative rule.
`AGENTS.md` invariant 6 was rewritten this same day, and
`docs/adr/0025-presence-based-source-authorization.md` §6 states it supersedes ADR-0022,
ADR-0023 and ADR-0024 **as authorization gates**:

> "**Presence is authorization.** A source directory, file, or manifest placed under
> `var/external/` is authorized for `ingest`, `read_raw`, `extract`, `normalize`, `align`,
> `distill_lexicon`, …, `synthetic_generation_support`, and `direct_training`."
> …
> "**Licenses, ownership, and register are records, not gates.**"

So in the tables below, **license is recorded as metadata, not as a permission verdict.**
What still binds is:

1. **Acquisition is not covered by ADR-0025.** The ADR authorizes *material present in the
   repo*; it does not grant a right to take material from a host whose terms forbid it.
   Where a publisher's terms of use prohibit scraping or restrict use to
   "personal and non-commercial purposes", that is a **human decision**, and I record it as
   `(c) gated` regardless of the license field.
2. **Third-party egress stays closed** (ADR-0025 §8): no cloud/API processing of any of this
   material unless policy opts in.
3. **Invariant 8 still holds**: sister-Panoan scripture can produce *hypotheses*, never
   `mzr` truth. Everything in §3 (except Marúbo itself) is hypothesis-grade for the LKB.

### 0.2 General web search is unusable in this session — one lane-wide caution

Every search route named in the preflight failed or degraded. This matters because it means
**"not found" in this report is generally weaker than "absent"**. Named results:

| Route | Result 2026-10-18 |
|---|---|
| `html.duckduckgo.com/html/?q=` | HTTP **202**, 14 KB anti-bot page, zero result links `[V]` |
| `lite.duckduckgo.com/lite/?q=` | HTTP **202**, same challenge `[V]` |
| `bing.com/search?q=` (HTML) | HTTP 200 but **degraded**: query `marubo` returned only TikTok profile pages; `povo marubo` returned the newspaper *O Povo*; `marubo língua indígena tradução` returned the same TikTok set `[V]` |
| `bing.com/search?q=…&format=rss` | HTTP 200, real URLs, but **same degraded relevance** (`cartilha marubo` → generic "how to make a cartilha" pages) `[V]` |
| `mojeek.com` | HTTP 200, page title `Captcha` `[V]` |
| `ecosia.org` | HTTP 403 challenge `[V]` |
| `search.brave.com` | HTTP 200, `captcha` in body `[V]` |
| `search.marginalia.nu` | HTTP 200, but index too small → unrelated hits `[V]` |
| `searx.be`, `search.inetol.net`, `searxng.site`, `priv.au` | JS shell / security check / 403 / 429 `[V]` |

**Consequence:** I could not do open-ended Portuguese/Spanish discovery of government or
community publications. Those items appear below as `[U]`/`(d)` with the failed method named,
not as proofs of non-existence. Everything substantive in this report was obtained by
**direct URL/API against named hosts**, which is reproducible.

---

## 1. Master inventory

Volumes marked *est.* are computed from canonical verse counts, not counted in the files.

| # | Slug | Name | Language(s) / pair | Contents & volume | Formats | License (as found) | Access | Task fit | Trust | Class |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `scriptureearth_mzr_corpus` | ScriptureEarth Marúbo text portions | `mzr` (mono) | 8 books + video book: **5,389 `\v` lines** (GEN 1526, EXO 540, NEH 124, LUK 1135, JHN 875, ACT 996, RUT 85, JAS 108) + XXF=video | USFM | Not stated in files (no `\ide`/`\rem`); manifest claims rights holder "Associação dos Povos Marúbo" | already local | Monolingual `mzr`; verse segments for `mzr`↔`por` | Partial books; no embedded copyright | **(a)** |
| 2 | `scriptureearth_mzr_audio` | ScriptureEarth Marúbo audio, 8 books | `mzr` (audio) | **162 MP3s**: GEN 50, EXO 20, RUT 5, NEH 7, LUK 25, JHN 21, ACT 29, JAS 5 (chapter-level) | MP3 | page-level TOU only | **open dir listing, no login** | future audio↔text; not usable alone | chapter granularity; **no timing files** | **(b)** |
| 3 | `scriptureearth_cbs_full_bible` | Cashinahua full Bible, two editions | `cbs` (mono) | **~140 PDFs** = 66 books × 2 editions (`…cbsBR-web.pdf` Brazil, `…cbsP-web.pdf` Peru) + `cbsNTPeru`, `cbsOTPeru`; *est.* ~31,100 verses ×2 | PDF | none stated on directory | open dir listing | related-lang priors; orthography comparison across two editions | huge; **two orthographies** = duplicate risk | **(b)** |
| 4 | `scriptureearth_cbr_bible` | Cashibo-Cacataibo Bible (OT portion + NT) | `cbr` (mono) | **57 book PDFs** (30 OT + 27 NT) + `cbrPB-web`, `cbrPOT-web`; *est.* ~28,700 verses | PDF | © Wycliffe Bible Translators (eBible record) | open dir listing | related-lang priors (closest well-documented Panoan sister corpus) | generation-quality unknown | **(b)** |
| 5 | `scriptureearth_yaa_nt` | Yaminawa NT, text **and full audio** | `yaa` (mono) | 30 PDFs (00-POT, 00-WNT, 27 NT) **+ 260 MP3s covering all 27 NT books**; *est.* ~7,957 verses | PDF, MP3 | none stated | open dir listing | related-lang; the only **complete Panoan NT with aligned chapter audio** | audio granularity vs verse unknown | **(b)** |
| 6 | `scriptureearth_mcf_nt` | Matsés NT | `mcf` (mono) | 28 PDFs (00-WNT + 27 NT); *est.* ~7,957 verses | PDF | © 2008 WBT (eBible) | open dir listing | **named sister profile in repo** → high hypothesis value | same translation as eBible mcfNT | **(b)** |
| 7 | `scriptureearth_cao_nt` | Chácobo NT (+ extras) | `cao` (mono) | 28 PDFs (00-WNT + 27) + 6 others (`cao 24933`, `cao24934Chácobo`, … Santiago ST); *est.* ~7,957 verses | PDF | © 2010 WBT (eBible) | open dir listing | related-lang (Bolivian Panoan) | extras unlabelled | **(b)** |
| 8 | `scriptureearth_amc_nt` | Amahuaca NT (single volume) | `amc` (mono) | 1 PDF `amcNT-Amahuaca.pdf`; *est.* ~7,957 verses | PDF | none stated | open dir listing | related-lang | single-volume, verse breaks unverified | **(b)** |
| 9 | `scriptureearth_shp_bible` | Shipibo-Konibo Bible | `shp` (mono) | 2 PDFs (`shpBP-print`, `shpBP-web`); *est.* ~8,500 verses (NT + shorter OT) | PDF | © 2012 WBT (eBible: "New Testament and Shorter Old Testament") | open dir listing | most NLP-supported sister; orthography → Spanish, not PT | print/web duplicates | **(b)** |
| 10 | `ebible_panoan_usfm` | eBible USFM packages: `mcfNT`, `cbrNT`, `caoNT`, `shpNTpo` | mono each | 4 translations, each ~7,957–8,500 verses; 7 artefact types each (`_usfm.zip`, `_html.zip`, `_readaloud.zip`, `_vpl.zip`, `_browserBible.zip`, `_usfx.zip`, `_xetex.zip`) | **USFM zip**, HTML, VPL | `class='redist'`; © 2008/2010/2011/2012 WBT | direct download, no login | **directly ingestible by the existing USFM pipeline** | same underlying translations as ScriptureEarth PDFs | **(b)** |
| 11 | `ebible_por_pivot` | Portuguese Bibles on eBible (verse-ID pivot) | `por` | 6 editions incl. `porbr2018` *Bíblia Livre*, `porblt` *Bíblia Livre Para Todos*, `porbrbsl` *Bíblia Portuguesa Mundial*, `portft` *Tradução para Tradutores*, `poronbv`; *est.* 31,100 verses each | USFM zip, HTML | all `redist` except `por` (VFL NT, `restricted`) | direct download | **supplies the `por` side for verse-ID joins** | translation register varies (TFT is literal, good for alignment) | **(b)** |
| 12 | `door43_mzr_prophets` | Door43 `moseslai2018/mzr_*_text_reg` (10 repos) | claims `mzr` | 10 books: AMO, HAB, HAG, JOL, LAM, MAL, MIC, OBA, ZEC, ZEP; *est.* ~912 verses, ~330 KB | USFM **chunked** (`NN/MM.txt` with `\v`) + `manifest.json` | **CC BY-SA 4.0** with explicit `LICENSE.md` in every repo | public git over HTTPS, no login | would be *high* if it were Marúbo | **LANGUAGE UNVERIFIED — probable mis-code (see §2.1)** | **(b) but quarantined** |
| 13 | `jw_panoan_shp_mcf` | JW.org Shipibo-Conibo + Matsés publications | `shp`, `mcf` | JW's catalogue JSON lists both with `hasWebContent: true`; volume unknown (not fetched) | HTML, PDF, MP3, EPUB | Watch Tower, "personal and non-commercial" only | **acquisition forbidden by TOU** | high linguistic value, unusable | absolutely copyrighted | **(c)** |
| 14 | `ia_rosetta_panoan` | Rosetta Project Panoan items (Internet Archive) | `amc`, `cbs` | `rosettaproject_amc_vertext-1` = **audio** (Lomax recording, not verse text); `rosettaproject_cbs_ortho-1` = *Diccionario Cashinahua* scan (47 KB PDF) | FLAC/MP3/WAV; PDF | `licenseurl: null`, `rights: null` | IA item endpoints | low | mislabelled "vertext"; no license | **(b)** |
| 15 | `shipibo_mt_es_shp` | Shipibo NLP/parallel assets on GitHub | `shp`↔`spa` | `aoncevay/mt-es-shp` (es↔shp MT), `UD_Shipibo_Konibo-PUCP` (treebank), `unimorph/shp`, `jpereiran/chana` (MIT), `pollitoconpapass/spanish_2_shipibo_konibo` (HF) | varies | mostly **no license field** | public git | hypotheses + method transfer only; **Spanish-aligned, not Portuguese** | licenses unstated on most | **(b)/(c)** |
| 16 | `americasnlp_repos` | AmericasNLP shared-task repositories | multi-indigenous | `AmericasNLP/americasnlp2021`…`2026` exist; Panoan membership not confirmed this session | varies | per-year terms | public git | candidate related-lang pairs | not verified to contain Panoan beyond `shp` | **(c)** |

---

## 2. New detail on the already-known Marúbo items (classification **(a)**)

### 2.1 `scriptureearth_mzr_corpus` — what the live site actually exposes `[V]`

I re-walked the public file tree rather than the UI. **The Marúbo tree contains no USFM and
no verse-timing data**, which is a provenance gap worth recording:

```
https://www.scriptureearth.org/data/mzr/          200
  PDF/     (empty — zero files)
  audio/   162 *.mp3 + timing/
  sab/     mzr/  mzr_micropi/
  video/
https://www.scriptureearth.org/data/mzr/audio/timing/    200, EMPTY (parent link only)
https://www.scriptureearth.org/data/mzr/usfm/            404
https://www.scriptureearth.org/data/mzr/USFM/            404
https://www.scriptureearth.org/data/mzr/00-ALL-mzr.zip   404
```

* `sab/mzr/` is a SvelteKit Scripture-App-Builder bundle: 11 entries, of which only
  `spinner.css` is not under `_app/`. `sab/mzr_micropi/` is the low-storage variant
  (`manifest.webmanifest`, icons, `css/sab-stylesheet.css`). **The verse text lives inside
  the app bundle, not in a plainly linked download.**
* **Audio is chapter-granular, not verse-granular**: 162 files across 8 books
  (GEN 50, EXO 20, RUT 5, NEH 7, LUK 25, JHN 21, ACT 29, JAS 5), named
  `01-GENmzr001.mp3` … `60-JASmzr005.mp3`. `audio/timing/` exists but is **empty** → no
  verse-level timing is published for `mzr`. `[V]`
* The language page (`00por.php?iso=mzr`, 158 KB) says: "**A Bíblia em Marúbo**";
  "Autodesignação da língua dos falantes: **Yora**"; alternative names "Kaniuá, Marova,
  Maruba, Marubo, Marúbo, 마루보, Марубо"; Brazil; code `mzr`; **Index 2477**; tabs
  Texto / Áudio / Vídeo / App / Outros / Mapa. `[V]`
  *Caution:* the "self-designation: Yora" claim is ScriptureEarth metadata and conflicts with
  the ordinary use of *Yora*/Nahua as a distinct Panoan people. Do **not** import that as a
  language fact.
* Local files carry **no** `\ide`, `\rem` or copyright line (checked all 9 files) — the only
  rights statement in the repo is the manifest's
  `rights_holder: Associação dos Povos Marúbo` plus a note "License checked by operator on
  2026-10-12 … redistribution denied". Under ADR-0025 that note is metadata, but the
  **inconsistency between "acquired_from `00por.php?iso=mzr`" and the fact that this URL
  exposes no USFM** means the lineage record deserves human re-verification before `mzr`
  scripture is described anywhere as "downloaded from ScriptureEarth USFM". `[V]`
* Verse counts (counted locally, not estimated):
  GEN 1526, EXO 540, NEH 124, LUK 1135, JHN 875, ACT 996, RUT 85, JAS 108 = **5,389**.
  EXO and NEH are clearly partial (canonical 1,213 and 406). `[V]`

### 2.2 `grn_words_of_life_mzr` — still gated `[V]`

`globalrecordings.net` now sits behind a **bunny.net "establishing a secure connection"
interstitial on every path** (`/en/search?q=marubo`, `/en/language/mzr`,
`/en/language/1969`, `/en/population/mzr` → all HTTP **403**, 1,861-byte challenge).
`5fish.mobi/search?q=marubo` returns HTTP 200 but **zero** `marubo` occurrences.
No new GRN detail obtainable. Remains `(a)` indexed-only, and now also `(c)` bot-walled. `[V]`

---

## 3. The actually new Panoan scripture inventory

### 3.1 ScriptureEarth sister-language trees — all eight codes probed `[V]`

Method: fetch `https://www.scriptureearth.org/data/<iso>/`, then `/audio/` and `/PDF/`
listings for each. This is a different access path from the earlier survey's UI browsing.

| ISO | `/data/<iso>/` | subdirs | audio files | PDF files |
|---|---|---|---|---|
| `mzr` | 200 | PDF, audio, sab, video | **162** | 0 |
| `mcf` Matsés | 200 | PDF, sab, video | 0 | 28 |
| `mpu` Matis | **404** | — | — | — |
| `xor` Korubo | **404** | — | — | — |
| `shp` Shipibo-Konibo | 200 | PDF, sab, video | 0 | 2 |
| `yaa` Yaminawa | 200 | PDF, audio, sab, video | **260** | 30 |
| `cbs` Cashinahua | 200 | PDF, sab, video | 0 | ~140 |
| `cbr` Cashibo-Cacataibo | 200 | PDF, sab, video | 0 | 57 |
| `cao` Chácobo | 200 | PDF, sab | 0 | 34 |
| `amc` Amahuaca | 200 | PDF, sab, video | 0 | 1 |

`mpu` and `xor` — the two sister profiles named in `docs/languages/mzr.md` besides Matsés —
have **no ScriptureEarth presence at all**. `[V]`

The single most valuable new fact in this lane: **Cashinahua has the whole Bible in two
parallel editions on the open file tree** (`01-GENcbsBR-web.pdf` vs `01-GENcbsP-web.pdf`
through `67-REV…`), plus `cbsNTPeru-web.pdf` / `cbsOTPeru-web.pdf`. Two editions of the same
Panoan text is a rare orthography-comparison asset — and simultaneously a duplicate-policy
problem if both are ever ingested (ADR-0023's duplicate concern, still worth honouring as a
quality record even though it is no longer a gate).

### 3.2 eBible — the machine-readable route to the same translations `[V]`

eBible does **not** key on ISO codes; it keys on `<iso><NT|OT><source-lang>`. Queried
`details.php` for each Panoan id found in the 1,553-row translation table:

| id | Language | eBible title | Copyright line (verbatim) | class |
|---|---|---|---|---|
| `mcfNT` | Matsés | Matsés NT | "Copyright © 2008 Wycliffe Bible Translators, Inc." | `redist` |
| `caoNT` | Chácobo | Chácobo NT | "Copyright © 2010 Wycliffe Bible Translators, Inc." | `redist` |
| `cbrNT` | Cashibo-Cacataibo | Cashibo-Cacataibo NT | "Copyright © 2011 Wycliffe Bible Translators, Inc." | `redist` |
| `shpNTpo` | Shipibo-Conibo | "New Testament and Shorter Old Testament in Shipibo-Conibo (PE:shp:Shipibo-Conibo)" | "Copyright © 2012 Wycliffe Bible Translators, Inc." | `redist` |

Each record offers seven artefacts per translation, including
`<id>_usfm.zip` (USFM), `<id>_usfx.zip`, `<id>_vpl.zip` (verse-per-line — convenient for
verse-level TSV construction), `<id>_readaloud.zip` (audio-oriented HTML),
`<id>_browserBible.zip`, `<id>_html.zip`, `<id>_xetex.zip`. `[V]`

Why this outranks the ScriptureEarth PDFs for our pipeline: the repo already ingests USFM
(§2.1 has 9 local `.usfm` files), so `_usfm.zip` / `_vpl.zip` need no PDF extraction, and
verse boundaries come for free.

`show.php?id=<iso>` returns "ID not found" for every bare ISO — worth remembering, since the
earlier survey's "no Marubo on eBible" conclusion is reproducible only via the right key
scheme. Also **no Panoan language other than these four appears in eBible's 1,553-row
table**: grep for `shipibo|cashinahua|matsés|chácobo|amahuaca|yaminawa|cakataibo|cashibo|marubo`
returns exactly 4 rows. `[V]`

### 3.3 Door43 / unfoldingWord / open.bible — a near-miss that must be quarantined

`https://git.door43.org/api/v1/repos/search?q=mzr` returns **10 repositories**:
`moseslai2018/mzr_{amo,hab,hag,jol,lam,mal,mic,oba,zec,zep}_text_reg` (24–48 KB each). `[V]`

What they claim:

```json
{"format":"usfm","generator":{"name":"ts-desktop","build":"132"},
 "target_language":{"id":"mzr","name":"Marúbo","direction":"ltr"},
 "project":{"id":"amo","name":"Amos"},
 "source_translations":[{"language_id":"en","resource_id":"ulb","checking_level":"3"}],
 "translators":[],"finished_chunks":[]}
```

`LICENSE.md` in each repo is **CC BY-SA 4.0**, with an explicit attribution clause:

> "Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) … You must
> attribute the work as follows: 'Original work available at https://door43.org/'."

The chunks contain **running text with `\v` markers**, e.g. `01/01.txt` of AMO:

> `\v 1 Juda mangkri Owsimin Israel mangkri Zawsiah chapa, Zerobowm mang aup mi chang kowi, krung lahawng uowi dowi rown pre nik aluk kowi, …`

**But the language is almost certainly not Marúbo.** Evidence, strongest first:

1. **Function-word frequency profiles do not intersect.** Top-25 raw tokens of the local
   `mzr` USFM corpus vs. top-25 of the Door43 AMO chunks: **overlap = 0/25**. After folding
   nasal vowels and accents (a defensible leniency), overlap = **2/30** (`mi`, `mai`).
   Same-language prose never has a near-empty overlap on its highest-frequency items.
   Local top items: `ãwẽ, ato, akĩ, ivo, aská, atõ, ea, yové, yora, mĩ`. Door43 top items:
   `kowi, dowi, da, mang, ngak, mi, ah, khai, mro, uowi, thurai`. `[V]`
2. **Orthography is incompatible with the local lexicon.** `var/external/marubo_vocab/marubo_lexicon.tsv`
   (1,100 entries) contains **zero** tokens with the digraph `th`, and **zero** word-final
   `-ng` tokens; the Door43 text is dense in `Thurai`, `chowng`, `lowng`, `phung`. The
   modern Marúbo forms sampled from the same lexicon (`txipo`, `yové`, `shavá`) are absent
   from the Door43 text. `[V]`
3. **Provenance smells wrong for a Brazilian language.** Single committer
   `moseslai2018`, commits dated **2018-03-01T14:10 +07:00** (UTC+7 — SE Asia), a bulk-import
   `ts-desktop` generator, and empty `translators` / `finished_chunks` arrays. `[V]`

**Verdict:** report it as a **probable mis-code** — best hypothesis is a Tibeto-Burman
(Chin/Kuki) language of Myanmar/India, given `mang` 'chief/king', `-ng` finals, `kh-`/`th-`
onsets. **Do not ingest as `mzr`.** If a human checks it and it turns out to be Marúbo in an
archaic orthography, it is still worth having: ~912 verses (AMO 146, HAB 56, HAG 38, JOL 73,
LAM 154, MAL 55, MIC 105, OBA 21, ZEC 211, ZEP 53) of Books that the local corpus lacks
entirely, under a clean CC BY-SA 4.0 license.

No other Panoan code exists on Door43: `q=shp_text`, `cbs_text`, `mcf_text`, `yaa_text`,
`cao_text`, `cbr_text`, `amc_text` → **0 repositories each**. `[V]`
(So "unfoldingWord/open.bible has no Panoan content" holds — open.bible reads Door43.)

---

## 4. Aggregators — decisive negatives, with method

| Aggregator | Method (exact) | Result |
|---|---|---|
| **OPUS** | Full inventory dump `https://opus.nlpl.eu/opusapi/?source=mzr` → 18,783,732 bytes, **65,771 records**, parsed with `json` | **1,063 distinct language codes; `mzr`, `shp`, `cbs`, `yaa`, `cao`, `amc`, `cbr`, `mcf` all absent.** Method validated against control `?corpus=OpenSubtitles&source=en&target=pt` → sane single record (27,086,773 alignment pairs). This re-check is strictly stronger than the earlier "no Panoan in fetched OPUS pages", because the API silently ignores unknown filters — the earlier negative could have been an artifact. `[V]` **(d)** |
| **Tatoeba** | `https://api.tatoeba.org/unstable/sentences?lang=shp&sort=relevance` (and `mzr`) | HTTP **400**: `{"message":"Invalid value for parameter 'lang': Invalid language code 'shp'"}`. Controls: `spa` → total 445,556; `swe` → 57,495. So Panoan codes are not merely empty, they are **not registered languages** in Tatoeba. `[V]` **(d)** |
| **Wikimedia** (Wikipedia / Wiktionary / Wikisource / Incubator) | `meta.wikimedia.org/w/api.php?action=sitematrix&format=json&smtype=language` → **374 languages**; plus `incubator.wikimedia.org/wiki/Wp/mzr` | None of `mzr, shp, cbs, yaa, cao, amc, cbr, mcf` in SiteMatrix; `Wp/mzr` and `Wp/shp` say "does not exist"; `Wp/shipibo`, `Wt/mzr` → 404. **No Panoan wiki, no Incubator test wiki, no Panoan Wikisource.** `[V]` **(d)** |
| **HuggingFace** (names only — lane 06 goes deeper) | `huggingface.co/api/datasets?search=` | `marubo` → 0; `panoan` → 0; `matsés` → 0; `shipibo` → **1**: `pollitoconpapass/spanish_2_shipibo_konibo` (es↔shp). `[V]` |
| **mC4** | `huggingface.co/datasets/mc4/raw/main/README.md` → YAML `language:` list | **108 languages enumerated; no `mzr`.** `[V]` **(d)** |
| **OSCAR-2301** | `…/oscar-corpus/OSCAR-2301/raw/main/README.md` | HTTP **401** (gated repo) — could not verify. Report as `[U]`, not as negative. |
| **Common Crawl** | `commoncrawl.org/languages` | HTTP **404**; CC language stats are CLD-based and mC4's CLD-derived 108-language list excludes `mzr` — treat CC as `[W]` negative by proxy. |
| **ELRC / LINDAT / CLARIN** | not searched this session (search-engine layer dead; no direct query path) | `[U]` — **not** a negative. Flag for a lane that has search. |

---

## 5. Platforms that are gated or barred — and why the distinction matters

### 5.1 JW.org — `shp` and `mcf` exist, `mzr` does not, and acquisition is forbidden `[V]`

The site embeds its whole catalogue as JSON (1,162 language objects; 648 with web content).
Parsing it:

* `shp` → `{"symbol":"shp","langcode":"SHC","name":"Shipibo-Conibo","hasWebContent":true}`
* `mcf` → `{"symbol":"mcf","langcode":"MSS","name":"Matses","hasWebContent":true}`
* `mzr` → **ABSENT**. Also absent: `cbs`, `yaa`, `cao`, `amc`, `cbr`, `mpu`, `xor`.
  (Only two Panoan entries in the entire JW catalogue.)
* `cbt` "Shawi" present but `hasWebContent:false`.

JW's Terms of Use (`https://www.jw.org/en/terms-of-use/`) — quoted verbatim:

> "View, download, and print Watch Tower's copyrighted artwork, electronic publications,
> music, photos, text, or videos from this website for **your own personal and non-commercial
> purposes**."

and, decisively for an agent:

> "**Create for distribution purposes, any software applications, tools, or techniques that are
> specifically made to collect, copy, download, extract, harvest, or scrape data, HTML, images,
> or text from this site.** (This does not prohibit the distribution of free, non-commercial
> applications designed to download electronic files such as EPUB, PDF, MP3, and MP4 files
> from public areas of this site.)"

A Watch Tower Matsés/Shipibo Bible would be linguistically valuable, but harvesting it is
squarely inside the prohibited clause. **`(c) gated`; human decision only; no agent fetch.**
This is the one case in this lane where ADR-0025 does not help: presence authorizes, but
nothing authorizes the taking.

### 5.2 Faith Comes By Hearing / Bible.is / Bible Brain — gated `[V]`

`bible.is/languages` → HTTP 200 but a Webflow JS app (73,705 bytes, zero language strings).
The API at `https://4.dbt.io/api/languages?q=marubo` → HTTP **422**
`{"error":"You need to provide the missing parameter 'v' …"}` — i.e. it needs API version
**and a key**. No unauthenticated route found this session. `(c) gated`, `[V]`.

### 5.3 YouVersion / bible.com — gated `[V]`

`https://www.bible.com/languages` → HTTP 200, **3,038 bytes**, a JS shell: zero occurrences
of `shp`, `mzr`, `mcf` or any Panoan name. The documented public API requires a key.
Could not confirm whether Marúbo exists in the YouVersion catalogue. Record as `(c) gated` +
`[U]` on content, **not** as a negative.

---

## 6. Government and school materials — could not be reached, method named

| Target | Method attempted | Result | Class |
|---|---|---|---|
| **Peru MINEDU** *repositorio.minedu.gob.pe* | DSpace 7 REST: `/server/api/discover/search/objects?query=shipibo` and `?query=marubo` | Both return the Check Point interstitial — `<title>Security Verification — Check Point</title>`, JSON parse fails. **This is a different access method from the earlier survey's HTML record page, and it is still blocked**, so the earlier "blocked" finding stands and is strengthened. `[V]` | **(c)** |
| **Brazil MEC / PNLD Línguas Indígenas** | no reachable query path (all search engines degraded, §0.2) | `[U]` — cannot confirm or refute | **(c)/(d)-weak** |
| **Amazonas SEDUC / FUNAI / SESAI / DSEI Vale do Javari** | same | `[U]` | `[U]` |
| **"cartilha Marubo" / "livro Marubo" / "alfabetização Marubo"** | Bing HTML + Bing RSS, Portuguese locale | Returns generic *cartilha* pages (CIDESP, Ministério da Saúde, CERT.br, INEP, Embrapa) — **no Marúbo result**. Given §0.2 this is **not** evidence of absence. `[W]` | **(d)-weak** |
| **Bolivia Ministerio de Educación** | same | `[U]` | `[U]` |

Honest summary: I found **zero** government/community Marúbo PDFs, but with the search layer
down I cannot claim they do not exist. A human with browser access, or a lane with a working
search backend, should re-run: `cartilha marubo`, `livro marubo indígena`,
`"povo marubo" texto`, `DSEI Vale do Javari cartilha`, `MEC línguas indígenas material`,
`MINEDU shipibo cuaderno de trabajo`.

One incidental positive: Internet Archive holds **`shipibo10consejoscoronavirus`** ("10
CONSEJOS PARA FRENAR LA CURVA DEL CORONAVIRUS EN SHIPIBO") — i.e. COVID health materials in
a Panoan language do circulate on IA. That suggests the same genre exists for Marúbo; it just
isn't indexed where I can reach it. `[V]` item existence, `[W]` relevance.

---

## 7. Analysis: what this actually buys the LKB

### 7.1 No new Marúbo text was found

This is the headline. After probing ScriptureEarth (all Panoan trees), eBible (1,553 rows),
Door43 (all Panoan codes), JW (1,162 languages), Tatoeba, OPUS, Wikimedia, HF, GRN, IA:
the **only** untapped `mzr` asset is **audio (162 chapter MP3s)** and the Door43 text that is
almost certainly not Marúbo. Everything else new is *other* Panoan languages.

### 7.2 What the sister corpora are good for (and not)

Under invariant 8, `cbs`/`cbr`/`yaa`/`mcf`/`cao`/`amc`/`shp` can only create **hypotheses**.
Realistic uses, in order of payoff:

1. **Orthography and phonology priors** — seven Panoan languages in consistent missionary
   orthographies, all verse-aligned to the same source text. Directly useful for
   normalisation rules and for checking `mzr` orthographic variants (the local corpus uses
   `tx/sh/ã/ẽ/ĩ/õ`; the Cashinahua pair `cbsBR` vs `cbsP` is a ready-made two-orthography
   comparison for one language).
2. **Cognate and morpheme hypotheses** — Matsés (`mcf`) especially, since it is a named
   sister profile with an existing local profile.
3. **Method transfer** — verse-ID alignment machinery, and a test bed for the aligner on
   languages with more data before touching `mzr`.
4. **Not** usable as: `mzr` lexical truth, `mzr` morphology, or `mzr`↔`por` training pairs.

### 7.3 Where an actual `mzr`↔`por` pair set comes from

Nothing in this lane provides a native `mzr`↔`por` parallel corpus. The realistic routes:

* **Already partially built:** the repo holds `var/external/parallel_por/{GEN,EXO,RUT,NEH,LUK,JHN,ACT,JAS}.txt`
  — the Portuguese side for exactly the 8 Marúbo books, manifest key `parallel-por`,
  `acquired_from: "local files in parallel_por"`, no license recorded. So the PT pivot for
  `mzr` **already exists** and matches the ScriptureEarth book set 1:1.
* **Verse-ID join is free but not a translation pair.** Canonical verse numbers let you
  attach any `por` Bible to the 5,389 `mzr` verses trivially (`ebible_por_pivot`:
  `porbr2018` *Bíblia Livre*, `portft` *Tradução para Tradutores* → `redist` at eBible).
  But the Marúbo translator's actual source wording is unknown (sister-repo manifests point
  at English ULB, not Portuguese), so verse-ID joins are **semantically parallel, not
  translation-equivalent** — they must be tagged as such and must not silently become gold
  pairs. `portft` (*Tradução para Tradutores*, deliberately literal) is the best pivot
  candidate for alignment work.
* **Alignment granularity reality:** every scripture source here is **verse-level only**.
  No word- or sentence-aligned Panoan resource exists anywhere I could reach. `shp` has a
  UD treebank (`UD_Shipibo_Konibo-PUCP`) and Unimorph paradigms, but both are monolingual.
  So `mzr`↔`por` work starts and ends at verse granularity, with intra-verse segmentation
  still to be earned.

### 7.4 Volume summary (estimates flagged)

| Language | Verses (est.) | Confidence |
|---|---|---|
| `cbs` Cashinahua | ~31,100 × 2 editions ≈ **62,000** | high (66 books × 2, file listing verified) |
| `cbr` Cashibo-Cacataibo | ~**28,700** (30 OT + 27 NT) | medium-high |
| `yaa` Yaminawa | ~**7,957** (+POT) + 260 audio files | high |
| `mcf` Matsés | ~**7,957** | high |
| `cao` Chácobo | ~**7,957** | high |
| `amc` Amahuaca | ~**7,957** | medium |
| `shp` Shipibo-Konibo | ~**8,500** | medium |
| `mzr` Marúbo (local) | **5,389** (counted) | exact |
| Door43 "mzr" (quarantined) | ~**912** | medium |

---

## 8. Ranked top 3 for immediate action

**1. `ebible_panoan_usfm` — eBible USFM/VPL packages for `mcf`, `cbr`, `cao`, `shp`.**
The only machine-readable, no-login, verse-segmented Panoan text mass (~50,000 verses across
four languages), already in the format the repo's pipeline ingests, with a per-translation
copyright line ("© 2008/2010/2011/2012 Wycliffe Bible Translators") and `redist` class.
Highest ratio of linguistic value to ingestion effort. Use: related-language hypotheses,
orthography priors, aligner test bed. Not `mzr` truth.

**2. `scriptureearth_cbs_full_bible` — Cashinahua full Bible, two editions (~140 PDFs).**
By far the largest Panoan text mass reachable without any gate (~31,100 verses × 2), and the
only case where **two orthographies of one Panoan language** sit side by side — a direct
asset for normalisation and for the orthographic-variation problem the `mzr` corpus already
shows (modern `tx/sh/ã` vs. older `ch/ng/ow` styles in the wild). Cost: PDF extraction, no
USFM. Duplicate policy needed for the two editions.

**3. `scriptureearth_mzr_audio` — 162 Marúbo chapter MP3s, plus the existing `parallel_por`
pivot.**
The only genuinely *new* Marúbo material found. `audio/timing/` is empty, so verse alignment
must be derived (forced alignment against the 5,389 local `\v` segments), not read. Even
un-aligned, it is the first `mzr` acoustic data that matches the text corpus book-for-book,
and it is what a future speech or audio-grounded lexicon pass would need. Pair it with
`ebible_por_pivot` (`porbr2018`/`portft`) if verse-ID `mzr`↔`por` expansion is wanted.

**Do not act on:** `door43_mzr_prophets` (probable mis-code — quarantine), `jw_panoan_shp_mcf`
(TOU forbids acquisition), `ia_rosetta_panoan` (mislabelled, unlicensed, tiny).

---

## 9. Recommended human follow-ups (agent-blocked)

1. **Verify the Door43 language.** 15 minutes with a Marúbo speaker or a Panoanist settles
   whether `moseslai2018/mzr_*` is Marúbo-in-old-orthography or a mis-code. Until then it is
   the single biggest trap in this lane, because the manifest, the license and the file
   structure all look perfect.
2. **Resolve `mzr` USFM provenance.** The live ScriptureEarth `mzr` tree exposes **no USFM**
   (§2.1) while the repo manifest claims `acquired_from: 00por.php?iso=mzr`. Someone should
   record the real acquisition path (likely the SAB app bundle) before that lineage is used
   in any audit.
3. **Re-run government/community discovery with a working search backend** (§6). Nothing in
   §6 should be cited as "does not exist".
4. **Decide the JW.org question explicitly**, since it is the largest non-scripture Panoan
   translation body (`shp`, `mcf`) and its terms prohibit exactly what an agent would do.
5. **Check `audio/timing/` periodically** for `mzr` and `yaa` — it is an empty directory now,
   and a timing drop would convert both corpora into verse-level speech-text pairs overnight.

---

### Method appendix (reproducible)

All `[V]` items were obtained on 2026-10-18 with `curl` (browser UA) against:
`scriptureearth.org/data/{mzr,mcf,mpu,xor,shp,yaa,cbs,cao,amc,cbr}/{,audio/,PDF/,sab/}`,
`scriptureearth.org/00por.php?iso=mzr`, `ebible.org/find/` + `details.php?id={mcfNT,caoNT,cbrNT,shpNTpo}`,
`git.door43.org/api/v1/repos/search` + `/raw/`,
`opus.nlpl.eu/opusapi/` (full dump, parsed), `api.tatoeba.org/unstable/sentences`,
`meta.wikimedia.org/w/api.php?action=sitematrix`, `incubator.wikimedia.org/wiki/Wp/{mzr,shp}`,
`huggingface.co/api/datasets`, `huggingface.co/datasets/mc4`,
`www.jw.org/en/languages/` (JSON catalogue) + `/en/terms-of-use/`,
`4.dbt.io/api/languages`, `www.bible.com/languages`, `repositorio.minedu.gob.pe/server/api/discover/search/objects`,
`archive.org/advancedsearch.php` + `/metadata/`, `api.github.com/search/repositories`.
Local verification used `var/external/scriptureearth/mzr/*.usfm` (verse counts, top-token
profile) and `var/external/marubo_vocab/marubo_lexicon.tsv` (orthographic tests).
