# Lane 01 — Reference catalogs & structured databases (CLLD / CLDF / Lexibank / aggregators)

Survey date: **2026-10-18**. Target: Marúbo, ISO `mzr`, Glottolog `maru1252`, ASJP `MARUBO`,
family Panoan (`pano1256`), stock Pano-Tacanan (`pano1259`).

Scope of this lane: catalogs and downloadable structured databases that contain Marúbo **or** other
Panoan-language data and could add rows to the LKB. Literature PDFs, archives, parallel corpora,
media and NLP model hubs are lanes 02–06 and are not duplicated here.

-----------------------------------------------------------------------------------------------

## 0. Method note (read this before re-running the lane)

1. `web_search` is dead in this session, as the preflight warned. Everything below was checked either
   with `web_fetch` or with `curl` against direct APIs, raw GitHub, and clld `.json` endpoints.
2. **`web_fetch` loses table rows on clld apps.** For `glottolog.org`, `grambank.clld.org`,
   `phoible.org`, `ids.clld.org`, `dictionaria.clld.org`, `tsammalex.clld.org` the fetch returned the
   page chrome and an *empty* table, which would have produced false "no data" conclusions.
   `curl` + a small Python HTML/CSV parse reads the same pages correctly. Every presence/absence
   claim below was therefore re-checked against a **data file** (CSV/JSON/tsv), not against rendered HTML.
3. **The single highest-yield discovery route** (worth reusing for every other language and lane):
   the CLDF-Meta catalogue publishes a machine-readable index of which CLDF dataset version contains
   which Glottocode:

   ```
   https://raw.githubusercontent.com/cldf-datasets/cldf_meta/master/cldf/dataset-languages.csv   # 14.8 MB, 308,794 rows
   https://raw.githubusercontent.com/cldf-datasets/cldf_meta/master/cldf/datasets.csv            # dataset → contribution
   https://raw.githubusercontent.com/cldf-datasets/cldf_meta/master/cldf/contributions.csv       # title, licence, DOI, GitHub link
   ```

   Filtering `dataset-languages.csv` on `Language_ID == maru1252` returned **41 dataset-version rows**
   (≈10 distinct datasets, each spread over several Zenodo versions) with exact `Form_Count`,
   `Value_Count`, `Entry_Count`, `Example_Count` per dataset. That is how `zariquieypano`,
   `numeralbank`, `channumerals`, `elcat`, `imtvault` and `panobodyparts` were found — none of them
   shows up in a naive GitHub repo search for "panoan" (which returns 7 repos total).
4. Glottolog bibliography resolution: a `md.ini` `[sources]` key such as `hh:phon:Costa:Marubo`
   resolves with a 301 to `/resource/reference/id/<pk>`; the target page carries the full BibTeX.
   `curl -sSL` follows it; `urllib` without an `Accept` header does not return the BibTeX block.
   A `.bib` export endpoint (`/resource/languoid/id/<gc>.bib`) returns **406** — do not rely on it.
5. Two standing name traps, both hit live during this survey:
   - **WALS/Glottolog `Maru` (`maru1249`, ISO `mhx`)** is a **Burmese Loloish** language, not Marúbo.
   - **ELCat `Mru` (`mruu1242`, ISO `mro`)** lists "Maru" as an alt name — also not Marúbo.
   Marúbo's own alt names (`Kaniuá`, `Katukína`, `Marobo`, `Marova`, `Maruba`) collide with
   Katukína/Canamarí and with Kulinas–Marubos discussions (Fleck) — never merge on name alone.

Denominator used throughout: **Glottolog 5.3 lists 38 child languages and 28 dialects under Panoan
(`pano1256`)** (`child_family_count` 15 → Pano-Tacanan also contains Tacanan). "Panoan coverage" below
counts language-level varieties, not dialects.

-----------------------------------------------------------------------------------------------

## 1. Scoreboard — is Marúbo actually in there?

| Resource | Slug | Panoan varieties | **`mzr`/`maru1252` present?** | Volume for Marúbo | Verified against |
|---|---|---|---|---|---|
| Oliveira Proto-Panoan CLDF | `oliveiraprotopanoan` | 20 (18 glottocodes) | **YES** | 324 forms / 266 concepts / 283 cognate-set members | `cldf/forms.csv` [V] |
| Zariquiey Pano CLDF | `zariquieypano` | 26 (23 glottocodes) | **YES** | 187 forms / 181 concepts | `cldf/forms.csv` [V] |
| Valenzuela & Zariquiey Pano-Takana CLDF | `valenzuelazariquieypanotakana` | 33 (28 glottocodes) | **YES** | 25 forms (lang id `Mar`) | `cldf/forms.csv` [V] |
| Body-part terminology CLDF | `panobodyparts` | 26 | **YES** | 26 forms (25 body-part concepts) | `cldf/forms.csv` [V] |
| Grambank v1.0.3 | `grambank` | 16 | **YES** | 195 codings (44 present / 82 absent / 69 `?`), 98 comments | `cldf/values.csv` [V] |
| ASJP v21 (CLDF + web) | `asjp` | 27 (20 glottocodes) | **YES** | 38 lexical items | `languages/MARUBO.json` + `cldf/languages.csv` [V] |
| IMTVault v1.3 | `imtvault` | n/a (IGT vault) | **YES** | 97 example sentences | `cldf/examples.csv` [V] |
| Catalogue of Endangered Languages CLDF | `elcat` | n/a | **YES** | 27 metadata values | `cldf/values.csv` [V] |
| Numeralbank (analysed) | `numeralbank-analysed` | n/a | **YES** | 14 numeral forms (v0.9.1); 21 in older versions | `dataset-languages.csv` [V] |
| Chan Numeral Systems | `channumerals` | n/a | **YES** | 29 forms | `dataset-languages.csv` [V] |
| IDS Panoan subset (Key) | `keypano` | 8 Panoan + 3 Tacanan + 11 other | **NO** | 0 | `cldf/languages.csv` + `forms.csv` [V] |
| Intercontinental Dictionary Series | `ids` | 6 Panoan + 3 Tacanan | **NO** | 0 | `cldf/languages.csv` (319 langs) [V] |
| WALS Online | `wals` | 15 Pano-Tacanan | **NO** | 0 | `cldf/languages.csv` (3,573 lects) [V] |
| PHOIBLE 2.0 | `phoible` | 16 glottocodes | **NO** | 0 | `data/phoible.csv` (105,484 rows) [V] |
| Dictionaria | `dictionaria` | 0 | **NO** | 0 | `/languages` family filter [V] |
| Tsammalex | `tsammalex` | 0 | **NO** | 0 | `languages.geojson` (153 langs) [V] |
| Wikidata | `wikidata` | languoid only | **NO lexemes** | 0 | SPARQL on Q3296011 [V] |
| Wiktionary (en) | `wiktionary` | 23 Panoan categories | **NO lemmas** | 0 | MediaWiki API [V] |
| Concepticon 3.4.0 | `concepticon` | concept lists only | concept-mapping only | 517 + 1,310 concepts | contributions pages [V] |
| Glottolog 5.3 | `glottolog` | 38 Panoan languages | **YES (catalogue)** | 59 bibliography entries | `md.ini` + 59 reference pages [V] |
| CLDF-Meta | `cldf-meta` | index | **YES (index)** | 41 dataset-version rows | `dataset-languages.csv` [V] |
| PanLex | `panlex` | unknown | **unverified** | — | API DNS failure [W] |
| Endangered Languages Project / ELCat web | `elp` | — | **blocked** | — | TCP timeout [W] |

`[V]` = verified by fetching the data file / API payload named in the table.
`[W]` = partially verified (page reachable, data path blocked or ambiguous). `[U]` = unresolved.

-----------------------------------------------------------------------------------------------

## 2. Primary evidence: CLDF / Lexibank lexical datasets with Marúbo forms

These are the rows that can actually become **observed Marúbo lexical forms** in the LKB. All are
CLDF `Wordlist` modules, i.e. directly compatible with the repo's existing CLDF interchange
scaffolding (`docs/adr/0003-cldf-interchange.md`, `docs/adr/0016-cldf-interchange-and-export-eligibility.md`).

### 2.1 `oliveiraprotopanoan` — Proto-Panoan reflexes (Soares de Oliveira 2014)

| Field | Value |
|---|---|
| Slug | `oliveiraprotopanoan` |
| Name | CLDF dataset derived from Oliveira's *Contribuições para a Reconstrução do Protopáno* (2014) |
| URL | https://github.com/pano-takanan-history/oliveiraprotopanoan · https://doi.org/10.5281/zenodo.10214016 (v1.2.0; also 10.5281/zenodo.10016548, 10.5281/zenodo.10015142) |
| Contents & volume | 20 varieties (18 glottocodes) incl. **Marúbo** and **Proto-Panoan**; 469 concepts (302 Concepticon sets); 7,305 lexemes; 43 sources; 7,305 cognate-coded forms in **834 cognate sets** (314 singletons); 32,288 tokens; 138 segments; avg inventory 36.45. **Marúbo-specific: 324 forms across 266 concepts, in 283 cognate sets.** |
| Formats | CLDF 1.x `Wordlist`: `forms.csv` (1.44 MB), `cognates.csv` (607 KB), `parameters.csv`, `languages.csv`, `sources.bib`, `cldf-metadata.json`; BIPA/CLTS-segmented (`Form`, `Segments`, `Graphemes`, `Profile`, `Alignment`, `Morphemes`, `Cognacy`, `Partial`-style `UncertainCognacy`, `ProtoSet`, `ConceptInSource`, `EntryInSource`) |
| License (verbatim) | Repo `metadata.json`: `"license": "CC-BY-4.0"`; README: *"This dataset is licensed under a CC-BY-4.0 license"*; `LICENSE` = *"Creative Commons Attribution 4.0 International Public License"* |
| Rights holder | Data: Oliveira, Sanderson Castro Soares de (UnB dissertation, https://repositorio.unb.br/handle/10482/17129), compiling Costa 1992, Costa 2000, Cesarino 2008, Kennell 1978, Boutle 1964, Cabral 2009/2010, Melatti 2005, Anonby 2010. CLDF editorial layer: F. Blum, C. M. B. Ugarte, J.-M. List (MPI-EVA / Lexibank community). |
| Access | **Fully downloadable by an agent**, no registration: `raw.githubusercontent.com/.../main/cldf/forms.csv` or the Zenodo record. |
| Task fit | Best single source of *structured Marúbo lexicon*: concept-mapped (Concepticon), IPA-segmented, cognate-clustered, with Proto-Panoan forms in the same rows. Supports concept mapping, cognate hypotheses, proto→reflex directionality, and a Marúbo phoneme cross-check (avg inventory 36.45). |
| Trust note | `Value == Form` for all 324 Marúbo rows (counted): the dataset does **not** preserve the source spelling separately from the normalised BIPA form, so the "observed" string is already normalised by the compiler — record `Source` (`Costa1992`, `Costa2000`, `Cesarino2008`, `Kennell1978`, `Boutle1964`, `Oliveira2014`, …) per row and keep the normalisation as a derived field. Proto-Panoan rows are **reconstructions → hypotheses only**. Marúbo source list includes **Kennell 1978 and Boutle 1964**, neither of which is in the current known-source list. |
| Register guess | everyday lexicon / traditional_public for the vocabulary; proto-forms = scholarly inference. |
| Check | 2026-10-18 · `[V]` (forms.csv parsed: 7,305 rows, 324 `Language_ID=Marubo`) |

### 2.2 `zariquieypano` — "CLDF dataset for Pano languages" (Zariquiey, Blum, List, Greenhill)

| Field | Value |
|---|---|
| Slug | `zariquieypano` |
| Name | CLDF dataset for Pano languages (companion to *Tracing the Evolution of Panoan Languages*) |
| URL | https://github.com/pano-takanan-history/zariquieypano · https://doi.org/10.5281/zenodo.20322670 (v0.4); v0.1 = 10.5281/zenodo.10988938 |
| Contents & volume | 26 varieties (23 glottocodes); 181 concepts, **all linked to Concepticon** (100 % badge); 4,265 lexemes; 12 sources; 18,544 tokens; 59 segments; avg inventory 26.38. **Marúbo: 187 forms covering 181 concepts** — i.e. one near-complete 181-item list for Marúbo. Has `Cognacy` **and** `Partial_Cognacy`, `Alignment`, `Morphemes`. |
| Formats | CLDF `Wordlist`: `forms.csv` (465 KB), `parameters.csv`, `languages.csv` (IDs are custom, e.g. `Mar`; Glottocode + ISO carried separately), `sources.bib`, `cldf-metadata.json` |
| License (verbatim) | `metadata.json`: `"license": "CC-BY-4.0"`; README: *"This dataset is licensed under a CC-BY-4.0 license"* |
| Rights holder | Dataset: Roberto Zariquiey, Frederic Blum, Johann-Mattis List, Simon J. Greenhill. **Marúbo column: 187/187 forms carry `Source = fleck2005`, whose bib entry reads `@unknown{fleck2005, title = {Fleck 2005 fieldnotes}}`** — David W. Fleck's *unpublished* fieldnotes. |
| Access | **Fully downloadable by an agent**, no registration. |
| Task fit | The cleanest comparative Panoan wordlist: one complete 181-concept list per variety with partial cognacy → ideal backbone for cross-Panoan cognate hypotheses and for aligning Marúbo against sister languages (Matsés, Matis, Korubo, Shipibo) already profiled in-repo. |
| Trust note | **Highest-value / highest-caution item of the lane.** The CC-BY-4.0 assertion is made by the CLDF compilers; the underlying Marúbo data is unpublished field notes, so the rights basis is not the usual published-source basis and the licence may not travel cleanly to the notes themselves (record rights holder as "compiler-asserted; underlying Fleck fieldnotes", and get a human decision before treating it as an observed-form source). It is also **the only dataset in this survey where 100 % of Marúbo forms come from a single unpublished source** — cross-check a sample against Costa 2000 / Kennell 1978 before promotion beyond `candidate`. |
| Register guess | everyday lexicon / unknown for fieldnotes provenance. |
| Check | 2026-10-18 · `[V]` (forms.csv: 4,265 rows, 187 `Language_ID=maru1252`, all `Source=fleck2005`; sources.bib inspected) |

### 2.3 `valenzuelazariquieypanotakana` — Pano-Takana hypothesis dataset

| Field | Value |
|---|---|
| Slug | `valenzuelazariquieypanotakana` |
| Name | CLDF dataset derived from Valenzuela & Zariquiey's *Language classification in Western Amazonia: advances in favor of the Pano-Takana Hypothesis* (2023) |
| URL | https://github.com/pano-takanan-history/valenzuelazariquieypanotakana · https://doi.org/10.5281/zenodo.10212481 (v1.0.0) |
| Contents & volume | 33 varieties (28 glottocodes), incl. Proto-Pano, Proto-Takana, Proto-Pano-Takana; 44 concepts (23 Concepticon sets); 856 lexemes; **856 cognate-coded forms in 44 cognate sets, 0 singletons**; 1 source. **Marúbo: 25 forms** (language ID `Mar`), e.g. `iwi` tree, `ʃɨta` tooth, `ravɨvakĩ` two, `taka` liver, `pɨi` leaf-to-fan, `ʃau` bone. |
| Formats | CLDF `Wordlist` + `cognates.csv`; `forms.csv` 120 KB |
| License (verbatim) | README: *"This dataset is licensed under a CC-BY-4.0 license"*; `metadata.json` `CC-BY-4.0` |
| Rights holder | Valenzuela, Pilar & Zariquiey, Roberto (source: LIAMES 23, e023002, doi 10.20396/liames.v23i00.8670150); CLDF conversion by the pano-takanan-history group. |
| Access | **Fully downloadable by an agent**. |
| Task fit | Deep-cognacy scaffold across Panoan **and** Tacanan — the right prior for "is this Marúbo form a retention or a contact item". Small vocabulary (25 Marúbo items) so it is a *hypothesis* generator, not a lexicon bulk source. |
| Trust note | Marúbo forms are explicitly attributed (`Source = Valenzuela2023`), from a peer-reviewed article — stronger provenance than 2.2. Cognate columns are comparative hypotheses by construction (invariant 8). |
| Register guess | traditional_public (basic vocabulary). |
| Check | 2026-10-18 · `[V]` (forms.csv: 856 rows, 25 with `Language_ID=Mar`; sources.bib = Valenzuela 2023) |

### 2.4 `panobodyparts` — body-part terminology (2022)

| Field | Value |
|---|---|
| Slug | `panobodyparts` |
| Name | CLDF dataset accompanying Zariquiey et al.'s *Evolution of Body-Part Terminology in Pano* (2022) |
| URL | https://github.com/lexibank/panobodyparts · https://doi.org/10.5281/zenodo.7318439 (v1.0) |
| Contents & volume | 26 varieties; 25 concepts; 637 lexemes; 12 sources. **Marúbo: 26 forms** (e.g. `kaʂu`, `pustu`, `imi`, `ʂau`, `pantʃu`, `βɨru`), all `Source = fleck2005`. |
| Formats | CLDF `Wordlist`; `forms.csv` 66 KB |
| License (verbatim) | README: *"This dataset is licensed under a CC-BY-4.0 license"* |
| Rights holder | Zariquiey et al. (Lexibank); Marúbo rows trace to Fleck 2005 fieldnotes (see 2.2 caution). |
| Access | **Fully downloadable by an agent**. |
| Task fit | Semantically tight body-part set → excellent for elicitation-paradigm alignment and for morphological segmentation of body-part compounds. |
| Trust note | Same fieldnotes provenance caveat as 2.2; overlapping vocabulary with 2.2 (both Fleck-derived) so **de-duplicate by concept+form**, do not add as independent confirmation. |
| Register guess | traditional_public. |
| Check | 2026-10-18 · `[V]` |

### 2.5 `keypano` — IDS Panoan subset in standardised transcription (Key & Comrie; Miller & List)

| Field | Value |
|---|---|
| Slug | `keypano` |
| Name | CLDF dataset on Panoan Languages in Standardized Transcription derived from Key and Comrie's *Intercontinental Dictionary Series* (2023) |
| URL | https://github.com/intercontinental-dictionary-series/keypano · https://ids.clld.org · CALC paper: https://calc.hypotheses.org/7503 |
| Contents & volume | 22 varieties (21 glottocodes), 1,310 concepts (1,308 Concepticon sets, = `Key-2016-1310`), **23,232 lexemes**, 146,061 tokens, 120 segments, avg inventory 32.45, 22 sources. Per-language lexeme counts: Yagua 1,776 · Spanish 1,770 · Portuguese 1,683 · Yaminahua 1,347 · Shipibo-Conibo 1,334 · Aguaruna 1,258 · Tacana 1,190 · Mosetén 1,162 · Cayuvava 1,154 · Araona 1,125 · Catuquina 1,124 · Movima 1,038 · Aymara 1,026 · Chácobo 1,019 · Cavineña 1,005 · Ese Ejja 968 · Itonama 902 · Cashibo 744 · Ese Ejja (Huarayo) 710 · Mashco Piro 569 · Pacaas Novos 228 · Pacahuara 100. **Marúbo: 0 (absent).** |
| Formats | CLDF `Wordlist`; `forms.csv` 2.5 MB; `parameters.csv`; `sources.bib` |
| License (verbatim) | `metadata.json`: `"license": "CC-BY-4.0"`; README: *"This dataset is licensed under a CC-BY-4.0 license"*; `LICENSE` = CC BY 4.0 full text |
| Rights holder | Mary Ritchie Key, Bernard Comrie (IDS founding editors); orthography profiles/maintenance J. Miller, J.-M. List; IDS = Max Planck Institute for Evolutionary Anthropology. |
| Access | **Fully downloadable by an agent**. |
| Task fit | 1,310-concept IDS questionnaire mapped to Concepticon — the best **concept-mapping scaffold** for sister languages, and the reference list to align any new Marúbo elicitation against. Also the place where an `mzr` gap is most conspicuous. |
| Trust note | The repo calls this "Panoan languages" but 11 of 22 varieties are not Panoan (Spanish, Portuguese, Aymara, Mosetén, Movima, Itonama, Cayuvava, Aguaruna, Yagua, Pacaas Novos, plus Tacanan). Treat as *Pano-Tacanan + areal contact*, not Panoan. All Marúbo-usable value is **sister-language hypothesis material only** (invariant 8). |
| Register guess | traditional_public (basic vocabulary). |
| Check | 2026-10-18 · `[V]` (`cldf/languages.csv` 22 rows, no `maru*`; `cldf/forms.csv` 23,232 rows, 0 Marúbo) |

-----------------------------------------------------------------------------------------------

## 3. Primary evidence: typology, numerals, IGT, metadata

### 3.1 `grambank` — Grambank v1.0.3 (CC-BY-4.0)

| Field | Value |
|---|---|
| Slug | `grambank` |
| Name | Grambank (The Grambank Consortium; Skirgård et al.) |
| URL | https://grambank.clld.org/languages/maru1252 · https://github.com/grambank/grambank · https://doi.org/10.5281/zenodo.7844558 (v1.0.3) |
| Contents & volume | 2,467 varieties total, 195 features. **Marúbo: 195 codings — 44 `1` (present), 82 `0` (absent), 69 `?`; 126 substantive values; 98 rows carry a `Comment`.** Sources on every row: `15379` (= Costa & Dorigo 2005, *A expressão da posse em Marúbo e Matsés (Páno)*) and `costa_1998` (= Costa, *Aspects of ergativity in Marubo (Panoan)*, J. Amazonian Linguistics 1(2):50-103). Contributors: Mariana Poblete, Roberto Zariquiey. Pano-Tacanan languages coded in Grambank: 16 (incl. Marúbo, Matsés, Shipibo-Conibo, Chácobo, Capanahua, Amahuaca, Isconahua, Katukína-Pano, Panobo, Poyanáwa, Shanenawa, Yaminahua, Yawanawa, Cavineña, Ese Ejja, Araona). |
| Formats | CLDF `StructureDataset`: `values.csv` (51 MB), `parameters.csv`, `codes.csv`, `languages.csv`, `sources.bib` (3 MB); web `.json` per language |
| License (verbatim) | Site footer: *"Grambank edited by The Grambank Consortium is licensed under a Creative Commons Attribution 4.0 International License."* Repository `CC-BY-4.0`. |
| Rights holder | The Grambank Consortium (MPI-EVA); Marúbo coding attributed to Poblete & Zariquiey from Costa 1998 / Costa & Dorigo 2005. |
| Access | **Fully downloadable by an agent**. Note: the clld HTML page for `maru1252` renders an **empty** feature table (and so does Matsés'), so presence cannot be judged from the web page — use `cldf/values.csv`. `representation=195 / nzrepresentation=126` in `/languages/maru1252.json` is a useful cheap probe (those two fields are per-language, not constants — Matsés differs at 174). |
| Task fit | Directly 126 **typology priors** about Marúbo (basic word order, case flagging, agreement, clause linkage) usable as constraints/priors for morphology induction and as a validator for generated paradigms. Zero lexical-hallucination risk. |
| Trust note | Codings are *analyst judgements* from two short papers by the language's main phonologist, not from a reference grammar; 69 features are `?`. Treat as `supported` priors, never as `validated` grammar facts. `Comment` column (98 rows) is the only place the actual Marúbo evidence is quoted — read it before trusting a value. |
| Register guess | n/a (analytic). |
| Check | 2026-10-18 · `[V]` (51 MB `values.csv` streamed and filtered: 195 rows with `Language_ID=maru1252`) |

### 3.2 `asjp` — ASJP Database v21 (CLDF + web)

| Field | Value |
|---|---|
| Slug | `asjp` |
| Name | The ASJP Database (Wichmann, Brown, Holman, Dryer, Ran) |
| URL | https://asjp.clld.org/languages/MARUBO · https://github.com/lexibank/asjp · https://doi.org/10.5281/zenodo.16736409 (v21, 2025) |
| Contents & volume | 11,540 varieties in the CLDF release; **27 Panoan varieties across 20 glottocodes** (+6 Tacanan). **Marúbo: 38 lexical items** (of the 40-item ASJP list; 2 meanings absent), ASJP-notation strings (`3a` I, `mia` you, `nuk3` we, `w3stis3` one, `r3b3oki` two, …). Sources: Costa 1993 (= the 1992 MA thesis), Costa 2000. |
| Formats | Web `.json` with the full list inline (`txt` field); CLDF `Wordlist` (`forms.csv`); Zenodo zip contains `raw/lists.txt` |
| License (verbatim) | Site footer: *"The ASJP Database edited by Wichmann, Søren & Brown, Cecil H. & Holman, Eric W. & Dryer, Matthew S. & Ran, Qibin is licensed under a Creative Commons Attribution 4.0 International License."* CLDF repo: `CC-BY-4.0`. |
| Rights holder | ASJP editors (Max Planck / Univ. of Hong Kong); Marúbo list compiled by Viveka Velupillai from Costa's thesis data. |
| Access | **Downloadable by an agent** (Zenodo zip, no registration). Already a known source (`asjp_swadesh_wordlist`) — new detail here is the 38-item count, the v21 DOI, the CC-BY-4.0 licence, and the 27-variety Panoan coverage. |
| Task fit | Swadesh-style comparanda + a ready-made 20-language Panoan distance matrix seed. ASJP phoneme notation is **lossy** — do not use for phoneme inventory. |
| Trust note | Already-downloaded source; ASJP forms are transcribed in a reduced 41-symbol code, so they are *normalised*, not observed orthography. Keep as `candidate`-grade comparison data. |
| Check | 2026-10-18 · `[V]` (`.json` wordlist parsed: 38 meaning lines; CLDF `languages.csv` 11,540 rows, 27 Panoan) |

### 3.3 `imtvault` — IMTVault v1.3 (IGT examples from published grammars)

| Field | Value |
|---|---|
| Slug | `imtvault` |
| Name | IMTVault — CLDF `Generic` dataset of interlinearised examples extracted from linguistic publications (Stenzel, Franchetto et al.) |
| URL | https://github.com/cldf-datasets/imtvault · https://doi.org/10.5281/zenodo.19947331 (v1.3) |
| Contents & volume | Vault-wide (1,735 languages in the indexed version). **Marúbo: 97 examples**, every one `Source = stenzel:franchetto:ed:17` (Language Science Press `langsci167`, = Stenzel & Franchetto (eds) 2017, the volume carrying Cesarino's Marúbo chapter). Columns: `Primary_Text`, `Analyzed_Word`, `Gloss`, `Translated_Text`, `Abbreviations`, `Corpus_Reference`, `LGR_Conformance`. |
| Formats | CLDF `Generic`: `examples.csv` (50.7 MB), `contributions.csv`, `languages.csv`, `sources.bib` |
| License (verbatim) | CLDF-Meta contribution record: `"License": "cc-by-4.0"`; repo `CC-BY-4.0`. The underlying book (Language Science Press, `langsci167`) is itself CC-BY. |
| Rights holder | Vault: cldf-datasets / IMTVault editors. Chapter: Cesarino, Pedro de Niemeyer, in Stenzel & Franchetto (eds) 2017. |
| Access | **Fully downloadable by an agent**. |
| Task fit | **97 sentence-level IGT records with segmentation + gloss + translation** in one CLDF file — the most morphology-relevant reservoir in this lane, and a natural test set for alignment/morphology induction on real Marúbo clauses. |
| Trust note | Register: these are **mythic/ritual song lines** ("Txõtxo Koro shavo winin aká shavo" / "Bird-women, seductive women"). Treat as `ritual_restricted` until a human reviews; the text is a poetic register, not everyday speech. It substantially **overlaps the already-known `zenodo_1008779_cesarino_2017` record (105 IGT records)** — same underlying chapter — so this is a *re-packaging into CLDF*, not new content. Value added: stable DOI, uniform columns, segmentation, glosses, de-duplication against the other 1,700 languages in the vault. |
| Check | 2026-10-18 · `[V]` (50.7 MB `examples.csv` streamed: 97 rows with `Language_ID=maru1252`) |

### 3.4 `elcat` — Catalogue of Endangered Languages as CLDF (v2024.1)

| Field | Value |
|---|---|
| Slug | `elcat` |
| Name | The Catalogue of Endangered Languages (ELCat) as CLDF `StructureDataset` |
| URL | https://github.com/cldf-datasets/elcat · https://doi.org/10.5281/zenodo.13946786 (v2024.1) |
| Contents & volume | 3,465 languages. **Marúbo (ELCat id `3008`): 27 values** — `vitality` = *Threatened (20 percent certain)*, `LEI` same; `speakers` figures from multiple sources (1,000–9,999; "1,252"; "1043"; "594"); `location` = Brazil, coordinates `-6.0968, -70.2246`; `bib` = "See Source". Registry row: `Name=Marubo`, `Glottocode=maru1252`, `ISO=mzr`, `classification=Pano-Tacanan`, `endangerment=threatened`, alt names `Marobo; Marúbo; Maruba; Marova; Kaniuá; Katukína; Marubo of the Javari Basin`. |
| Formats | CLDF `StructureDataset`: `values.csv` (12.4 MB), `languages.csv` (746 KB), `parameters.csv`, `codes.csv`, `sources.bib` |
| License (verbatim) | CLDF-Meta contribution record: `"License": "cc-by-4.0"`. (ELCat's own web terms were not reachable — see §6.) |
| Rights holder | ELCat = Catalogue of Endangered Languages (University of Hawaii / Living Tongues), packaged by cldf-datasets. |
| Access | **Fully downloadable by an agent** — this is the working substitute for the unreachable `endangeredlanguages.com` pages. |
| Task fit | Sociolinguistic metadata + **speaker-number and vitality evidence with per-value sources** for the LKB `Source`/metadata layer, and a citable "threatened" status that agrees with Glottolog's ElCat-derived status (`shifting`, checked 2023-07-06). No lexical content. |
| Trust note | Multiple conflicting speaker counts are preserved (good: invariant 7 — ambiguity kept representable). Populate LKB as *metadata observations*, never as lexical evidence. |
| Check | 2026-10-18 · `[V]` (`values.csv`: 27 rows for `Language_ID=3008`) |

### 3.5 `numeralbank-analysed` + `channumerals` — numeral systems

| Field | Value |
|---|---|
| Slug | `numeralbank-analysed`, `channumerals` |
| Name | CLDF Numeralbank Analysed (v0.9.1) and CLDF dataset derived from Chan's *Numeral Systems of the World's Languages* (2019) |
| URL | https://github.com/numeralbank/numeralbank-analysed (10.5281/zenodo.17597468) · https://github.com/numeralbank/channumerals (10.5281/zenodo.15654191 v1.0.2; 10.5281/zenodo.3475912 v1.0) |
| Contents & volume | Numeralbank analysed: 9,119 varieties; **Marúbo: 14 numeral forms (v0.9.1); 21 in an earlier version.** channumerals: 5,332 varieties; **Marúbo: 29 forms.** (Both counts from CLDF-Meta `Form_Count`.) |
| Formats | CLDF `Wordlist` (`forms.csv` 34.5 MB for numeralbank; `languages.csv` 3.3 MB) |
| License (verbatim) | Numeralbank: `"License": "cc-by-4.0"`. **channumerals: `"License": "other-open"`** — do **not** assume CC-BY; the Zenodo record must be read before ingestion. |
| Rights holder | Numeralbank project (Chan, Comrie et al.); Chan's Numeral Systems of the World's Languages database. |
| Access | **Fully downloadable by an agent**. |
| Task fit | A numeral paradigm for Marúbo (1–14/21/29 items depending on version) — directly useful for paradigm completeness checks and for a small, high-frequency inflectional probe. |
| Trust note | Two independent data files give *different* Marúbo counts (14 vs 21 vs 29) → version drift or different source lists. Diff before ingesting; do not merge silently. channumerals' `other-open` licence must be resolved by a human. |
| Check | 2026-10-18 · `[V]` for counts (CLDF-Meta index); `[W]` for content (forms not individually opened) |

-----------------------------------------------------------------------------------------------

## 4. Catalogues (not data): Glottolog, CLDF-Meta, Concepticon

### 4.1 `glottolog` — Glottolog 5.3 (the bibliography mine)

| Field | Value |
|---|---|
| Slug | `glottolog_maru1252` (known) |
| URL | https://glottolog.org/resource/languoid/id/maru1252 · md.ini: `https://github.com/glottolog/glottolog/blob/master/languoids/tree/pano1259/pano1256/main1279/pano1257/maru1251/maru1252/md.ini` |
| Contents & volume | **59 bibliography keys** for Marúbo in `[sources]`, each resolvable to a full BibTeX record: 3 grammar sketches (`hh:s:Kennell:Marubo` = Kennell 1978 *Descrição da gramática e da fonêmica da língua Marúbo (Chainawa)*, FUNAI processo 3507:6-52; `hh:phon:Costa:Marubo` = Costa 2000 PhD; `hh:typ:Sean:Marubo` = Smith, C. Sean 2021 *Aspects of Switch Reference in Marubo* — Trinity Western MA, 114 pp), 6 descriptive/typological items (Costa 1998 ergativity; Costa 1995 *Manifestaciones de la ergatividad en Marubo*; Costa & Dorigo 2005 possession; **Soares, Costa & Dorigo de Carvalho, *Signo y Seña*** — comparative), 4 comparative/classification items (Fleck 2013 *Panoan Languages and Linguistics*, AMNH AP 99; Kensinger Panoan survey; de Aguiar Pano; **Fleck, *Did the Kulinas Become the Marubos?***, Tipití 2:137-207 — a direct warning about Marúbo/Kulina conflation), 1 dictionary-ish/wordlist (`hh:hw:Martius:Brasiliens`, 1867 — the 3-item "wordlist_or_less" med), 4 `<hhtype>text` items (Cesarino 2013; Montagner Melatti IJAL 1981 *Marubo discourse genres*; Meléndez & Scott 1971 — actually Sharanahua text, mis-assigned), 1 sociolinguistic survey (Anonby & Holbrook 2010 SIL ESR 2010-003, Javari), 38 `fabreall2009ann` ethnographic/ anthropological items (Melatti, Montagner Melatti, Allen, Ruedas, de Lima, Cavuscens & Neves, Alviano…). |
| Formats | HTML + JSON per languoid; BibTeX per reference (`/resource/reference/id/<key>` → 301 → `<pk>`) |
| License (verbatim) | *"Glottolog 5.3 edited by Hammarström, Harald & Forkel, Robert & Haspelmath, Martin & Bank, Sebastian is licensed under a Creative Commons Attribution 4.0 International License."* |
| Rights holder | Max Planck Institute for Evolutionary Anthropology (Glottolog editors). |
| Access | **Fully machine-readable**; no `.bib` bulk endpoint (406) — resolve key-by-key. `glottolog-cldf` (GitHub) is the bulk route. |
| Task fit | The authoritative *lead list*: every one of the 59 entries is a candidate source for lane 02. New leads not in the known list: **Kennell 1978** (grammar + phonemics, FUNAI), **Smith 2021** (switch reference, MA), **Costa 1995** (ergativity, Spanish), **Soares/Costa/Dorigo (Signo y Seña)**, **Fleck 2013** (Panoan survey, classification authority), **Anonby & Holbrook 2010** (SIL Javari sociolinguistic survey), **Boutle 1964** (cited in `oliveiraprotopanoan`), **Montagner Melatti 1981 IJAL** (discourse genres). |
| Trust note | Glottolog's "med" (most-diverse-type) list is *not* a completeness list; several entries are ethnographic, not linguistic, and at least one (`Meléndez & Scott 1971`) is a Sharanahua text mis-filed under Marúbo. `hhtype` is auto-assigned for some records (visible as `(computerized assignment from "text")`). |
| Check | 2026-10-18 · `[V]` (md.ini parsed: 59 keys; every key resolved and its BibTeX title/author/year read) |

### 4.2 `cldf-meta` — CLDF-Meta catalogue (the discovery layer)

| Field | Value |
|---|---|
| Slug | `cldf-meta` |
| URL | https://meta.clld.org · https://github.com/cldf-datasets/cldf_meta · https://meta.clld.org/languages/maru1252 |
| Contents & volume | Index of every Zenodo-released CLDF dataset: 2,479 dataset versions, 308,794 dataset-language rows. **`maru1252` appears in 41 dataset-version rows ≈ 10 distinct datasets** (see §2–§3). Fields per row: `Value_Count`, `Form_Count`, `Entry_Count`, `Example_Count`. |
| Formats | CSV (`datasets.csv`, `dataset-languages.csv`, `contributions.csv` incl. `License`, `DOI`, `GitHub_Link`, `Version`) |
| License (verbatim) | *"CLDF Meta edited by Englisch, Johannes is licensed under a Creative Commons Attribution 4.0 International License."* |
| Rights holder | Johannes Englisch / cldf-datasets. |
| Access | **Fully downloadable**; the web table is JS-rendered (empty HTML for `web_fetch`), the CSVs are the real interface. |
| Task fit | The **cheapest possible completeness check** for "does any CLDF dataset contain my language?" — run it before any GitHub search. Reusable verbatim for other languages/lanes. |
| Trust note | Index lags dataset releases (e.g. `valenzuelazariquieypanotakana` is indexed under glottocode but the current `main` uses a custom language ID `Mar`), so confirm hits by opening the dataset. |
| Check | 2026-10-18 · `[V]` |

### 4.3 `concepticon` — Concepticon 3.4.0 (concept mapping only, no language data)

| Field | Value |
|---|---|
| Slug | `concepticon` |
| URL | https://concepticon.clld.org · Panoan-relevant lists: https://concepticon.clld.org/contributions/Oliveira-2014-517 · https://concepticon.clld.org/contributions/Key-2016-1310 |
| Contents & volume | 481 concept lists. **Exactly two Panoan-relevant lists exist**: `Oliveira-2014-517` — 517 concepts, *"This list presents the concepts that are reconstructed for Proto-Panoan. In the original data, the reflexes are presented for various Panoan languages"*, target languages "Panoan languages"; and `Key-2016-1310` — 1,310 IDS concepts with glosses in many languages. **No Marúbo-specific concept list exists** (`search` for `oliveira|pano|maru|key-|costa|shipibo|matses|kakataibo` over all 481 list files). |
| Formats | TSV per list (`concepticondata/conceptlists/*.tsv`), Concepticon API, CLDF-ready mappings |
| License (verbatim) | *"CLLD Concepticon 3.4.0 edited by List, Johann Mattis & Tjuka, Annika & Blum, Frederic & Kučerová, Alžběta & Ugarte, Carlos Barrientos & Rzymski, Christoph & Greenhill, Simon & Forkel, Robert is licensed under a Creative Commons Attribution 4.0 International License."* |
| Rights holder | Concepticon editors (MPI-EVA). |
| Access | **Fully downloadable** (GitHub `concepticon/concepticon-data`). |
| Task fit | The mapping substrate: `Oliveira-2014-517` gives a ready-mapped 517-item Panoan concept inventory, `Key-2016-1310` the IDS 1,310-item questionnaire — both already used by the two big CLDF wordlists, so concept IDs line up across `oliveiraprotopanoan`, `keypano`, `zariquieypano` for free. This is exactly the "concept mapping" leg the LKB needs. |
| Trust note | Concepticon contains **no lexical forms** — it cannot contribute a Marúbo row, only `Concepticon_ID` glue and gloss normalisation. |
| Check | 2026-10-18 · `[V]` (recursive tree of `concepticondata/conceptlists`, 481 files, filtered) |

-----------------------------------------------------------------------------------------------

## 5. Explicit negatives (with the check actually performed)

| Resource | Claim | Check method | Result |
|---|---|---|---|
| **IDS** (`ids.clld.org`, `intercontinental-dictionary-series/ids`) | "IDS has a Marúbo/Chainawa column" | `cldf/languages.csv` (master) parsed: **319 languages**; `grep -i maru` on the file | **0 hits.** IDS Panoan coverage = Cashibo, Catuquina, Chácobo, Shipibo-Conibo, Yaminahua, Pacahuara (+ Tacanan Cavineña, Araona, Ese Ejja). Marúbo is **absent from IDS entirely**. |
| **`idssegmented`** | derived segmented IDS might add Marúbo | `cldf/languages.csv`: 268 languages | **0 Marúbo.** |
| **`keypano`** | the "Panoan IDS" repo → Marúbo | `cldf/languages.csv` (22 rows) + `cldf/forms.csv` (23,232 rows) filtered | **Absent.** Closest neighbours: Shipibo-Conibo (1,334), Catuquina (1,124), Chácobo (1,019), Cashibo (744), Yaminahua (1,347), Pacahuara (100). Also note: 11/22 varieties are not Panoan. |
| **WALS Online** | Marúbo is a WALS lect | `cldf-datasets/wals` `cldf/languages.csv`, 3,573 lects, filtered on Family~/Pano/ | **Absent.** 15 Pano-Tacanan lects coded (Amahuaca, Araona, Capanahua, Cashibo, Cavineña, Chácobo, Cashinahua, Ese Ejja, Karipuna-Panoan, Matis, Matsés, Sharanahua, Shipibo-Konibo, Tacana, Yaminahua). **Trap:** the only "Maru" in WALS is `mru`/`maru1249`/`mhx`, a **Burmese Loloish** language. ASJP's `code_wals: null` for Marúbo independently corroborates the absence. |
| **PHOIBLE 2.0** | a Marúbo phoneme inventory is available | `phoible/dev` `data/phoible.csv` streamed (105,484 rows, 2,176 glottocodes), filtered on glottocode/ISO | **`maru1252`/`mzr` absent — 0 rows.** Panoan inventories that *are* present (16 glottocodes): Amahuaca (3 inventories: spa/upsid/saphon), Chácobo (2), Cavineña, Matsés (2), Capanahua, Cashibo-Cacataibo, Kashinawa, Katukína, Kaxararí, **Korubo**, **Matís**, Poyanáwa, Saynawa, Shanenawa, Sharanahua, Yaminawa, Yawanawa. → **No open phoneme inventory for Marúbo exists in PHOIBLE**; the inventory must come from Costa 2000 (PDF) or be reconstructed from `oliveiraprotopanoan` segments. |
| **Dictionaria** | some Panoan dictionary | `/languages` family filter list | **No Panoan family** in Dictionaria (13 families present: Afro-Asiatic, Austronesian, Indo-European, Mayan, Mixed, Nakh-Daghestanian, Otomanguean, Sino-Tibetan, Timor-Alor-Pantar, Tupian, West Bomberai, Yam, Zaparoan). |
| **Tsammalex** | Panoan/Amazonian flora-fauna lexicon | `languages.geojson`: 153 languages, names scanned | **No Panoan language, no Marúbo.** Tsammalex is Africa-centred; nothing here. |
| **Wikidata** | Wikidata Lexemes for `mzr` | SPARQL `?lexeme dct:language wd:Q3296011` on `query.wikidata.org` | **0 lexemes.** The item Q3296011 exists (linked from Glottolog) with no lexical content. |
| **Wiktionary (en)** | Marúbo lemmas exist | MediaWiki API `list=categorymembers` for `Category:Marúbo language`, `Category:Panoan languages` | `Category:Panoan languages` lists 23 sub-categories **including `Category:Marúbo language`**, but that category's only member is `Category:Marúbo entry maintenance` → **0 lemmas**. `Category:Proto-Panoan` = 0 members. The one Panoan asset is `Appendix:Proto-Panoan reconstructions` (37,580 bytes), which is a table of **Oliveira 2014 Proto-Panoan forms with English glosses** — i.e. a duplicate of the proto rows already in `oliveiraprotopanoan`, and containing **no Marúbo forms**. |
| **pt.wiktionary** | Marúbo entries in Portuguese Wiktionary | MediaWiki API `Categoria:Marúbo` | **0 members** (empty category, `batchcomplete`). |
| **`lexibank.github.io`** | Panoan datasets listed there | `https://lexibank.github.io/` | **Does not exist** (GitHub Pages "Site not found"). The live catalogue is `https://lexibank.clld.org/` (134 datasets aggregated) and the `lexibank` GitHub org (2 pages, no Panoan-named repo). **NorthEuraLex** (`lexibank/northeuralex`, 38 MB, CC-BY-4.0) is Eurasia-only → structurally excludes Marúbo. |
| **Chirila** | Chirila might hold Marúbo data | `https://chirila.clld.org/` | TLS cert/SNI mismatch → no service at that host. Chirila is an **Australian**-languages database, so it cannot contain Panoan data on principle. |
| **ALIC** | a wordlist aggregation named ALIC includes Marúbo | DDG HTML + Bing + `alic.clld.org` probe | **Unresolved `[U]`**: no CLLD host exists, no result establishes what "ALIC" refers to, and no evidence of any Panoan content. Treated as a non-resource until a source is named. |

-----------------------------------------------------------------------------------------------

## 6. Blocked / unverifiable checks

| Item | What was tried | Failure mode | Consequence / workaround |
|---|---|---|---|
| `endangeredlanguages.com` (ELP, ELCat's home) | `curl http://` and `https://` on `/lang/3008`, `web_fetch` on the same, `getent hosts` | DNS resolves (Cloudflare 2606:4700…) but **TCP connect times out at 20 s** on both schemes, and `web_fetch` returns `fetch failed` | **Blocked `[W]`.** Use `cldf-datasets/elcat` (§3.4) for ELCat content and Glottolog's mirrored ElCat status (`shifting`, source ElCat, dated 2023-07-06) for the vitality claim. The ELP *reference list* on the Marúbo page remains unseen. |
| **PanLex** | `curl https://api.panlex.org/v2/lang` with `{"i":"mzr"}`, then `web_fetch https://panlex.org/`, then `/license/` | API host: **`Could not resolve host: api.panlex.org`** (DNS). Website: reachable, © 2023 | **Unverified `[W]`**: Marúbo coverage in PanLex is unknown, and the bulk DB is not agent-accessible from here. **Licence is a hard constraint**: *"provides the contents and organization of the PanLex database ("the Database") under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License"* → **CC BY-NC-SA 4.0, non-commercial**. Under the repo's current ADR-0025 presence-based authorization this is recorded metadata, but it is the only NC-licensed item found in this lane. |
| `grambank.clld.org/languages/maru1252` HTML | `curl` + HTML table parse; same for Matsés as control | Feature table renders **empty** for both languages (header + 1 blank row), so the web UI cannot confirm or deny codings | Worked around via `cldf/values.csv` (§3.1). Do not use clld HTML tables for presence checks on grambank/phoible/ids. |
| Glottolog bulk `.bib` | `/resource/languoid/id/maru1252.bib`, `.bibtex`, `?ext=.bib`, `/resource/references?ext=.bib&languoid=…`, with `Accept: text/plain` | **406 Not Acceptable** on all variants | Worked around by resolving the 59 `md.ini` keys to `/resource/reference/id/<pk>` one by one (§0.4). Bulk alternative = `glottolog-cldf` repo (`cldf/sources.bib`). |
| `web_fetch` on clld pages generally | used first, per preflight | Tables silently dropped → false negatives | Re-ran everything with `curl`. Recorded in §0.2 so other lanes do not repeat it. |

-----------------------------------------------------------------------------------------------

## 7. Observed forms vs. hypotheses (invariant 8 mapping)

**May become `observed` Marúbo lexical evidence (with per-row `Source` + lineage):**

- `oliveiraprotopanoan` `forms.csv` rows with `Language_ID=Marubo` (324) — per-row `Source` already
  names Costa 1992 / Costa 2000 / Cesarino 2008 / Kennell 1978 / Boutle 1964 / Oliveira 2014.
  Caveat: `Value == Form` (no raw spelling preserved) → ingest as *normalised* observation, mark
  the normalisation as a derived attribute.
- `zariquieypano` (187) and `panobodyparts` (26) — **only after human provenance review**, because
  100 % of these rows are `Fleck 2005 fieldnotes` (unpublished).
- `valenzuelazariquieypanotakana` (25) — sourced to a peer-reviewed article; best provenance of the
  three, smallest volume.
- `asjp` (38) — already ingested; ASJP orthography is lossy, keep as comparison-grade.
- `imtvault` (97 IGT examples) — observed *sentences* with glosses; register = mythic/ritual, review first.
- `numeralbank`/`channumerals` (14–29 numerals) — pending version diff and the `other-open` licence read.
- `elcat` (27 metadata values) — metadata observations, not lexical.

**May only create hypotheses (never Marúbo truth):**

- All Proto-Panoan rows in `oliveiraprotopanoan` (`Language_ID=Proto-Panoan`) and the
  `Appendix:Proto-Panoan reconstructions` on Wiktionary — reconstructions.
- Every `Cognacy` / `Partial_Cognacy` / `ProtoSet` value in either dataset — comparative hypotheses,
  candidate-grade at best.
- All sister-language columns: `keypano` (Shipibo-Conibo, Cashibo, Catuquina, Chácobo, Yaminahua,
  Pacahuara, Mashco Piro), WALS/PHOIBLE/Grambank Panoan neighbours, `asjp` Panoan varieties.
- Grambank `values` — analyst typological judgements → `supported` priors, and per
  `docs/EVIDENCE-AND-CONFIDENCE.md` not "validated grammar".
- PHOIBLE's 16 Panoan inventories — *not* Marúbo; usable only as an areal/phonotactic prior.

**Coverage gaps this lane confirms (things no catalog will give us):**

1. **No phoneme inventory for `mzr`** in PHOIBLE (or anywhere machine-readable) → must come from
   Costa 2000 / Kennell 1978 PDFs (lane 02) or be derived from `oliveiraprotopanoan` `Segments`.
2. **No dictionary**: IDS, Dictionaria, PanLex (unverified), Wiktionary, Wikidata all lack Marúbo
   lexical content. The largest open Marúbo lexicon in existence is the 324-row
   `oliveiraprotopanoan` slice.
3. **No WALS typology**; Grambank's 126 substantive values are the only open typology.

-----------------------------------------------------------------------------------------------

## 8. Ranked top-3 for the LKB

**#1 — `oliveiraprotopanoan` (Proto-Panoan reflexes; CC-BY-4.0; CLDF Wordlist).**
324 Marúbo forms over 266 Concepticon-mapped concepts, IPA-segmented, cognate-clustered against
20 Panoan varieties and Proto-Panoan, with per-row source attribution spanning six Marúbo
publications. Highest lexical yield, best provenance, zero-friction agent download, and it drops
straight into the ADR-0003/ADR-0016 CLDF import path. Ingest first.

**#2 — `zariquieypano` v0.4 (Zariquiey/Blum/List/Greenhill; CC-BY-4.0; CLDF Wordlist).**
A complete 181-concept Marúbo list (187 forms) with **partial cognacy** against 25 other Panoan
varieties and 100 % Concepticon linkage — the best cross-Panoan comparison frame in existence.
Gate it behind a provenance decision: every Marúbo form is `Fleck 2005 fieldnotes` (unpublished),
so the compiler's CC-BY-4.0 assertion needs human sign-off before these become observed forms.
Highest *potential*, needs one governance step.

**#3 — `grambank` v1.0.3 (Grambank Consortium; CC-BY-4.0; CLDF StructureDataset).**
195 codings for Marúbo, 126 substantive, 98 with quoted comments, attributed to Costa 1998 and
Costa & Dorigo 2005. No provenance ambiguity, no hallucination surface, and it is the only source of
machine-readable Marúbo typology. Ingest as `supported` priors (typology constraints for morphology
induction and paradigm validation).

**Runner-up — `imtvault` v1.3** (97 segmental IGT examples, glossed, CC-BY-4.0): the only
sentence-level Marúbo in CLDF, but it re-packages the already-known Cesarino 2017 chapter and its
register is mythic/ritual, so it needs a register review before it is useful. Worth opening the same
week, not first.

-----------------------------------------------------------------------------------------------

## 9. Reusable recipe (hand to lanes 02–06 and to the next language)

```
# 1. Which CLDF datasets contain my language, and how much data?
curl -sSL https://raw.githubusercontent.com/cldf-datasets/cldf_meta/master/cldf/dataset-languages.csv \
  | grep <glottocode>            # → Dataset_ID, Form_Count, Value_Count, Entry_Count, Example_Count
# 2. Name/licence/DOI/GitHub for each hit
curl -sSL .../cldf/datasets.csv | grep <Dataset_ID>          # → Contribution_ID
curl -sSL .../cldf/contributions.csv | grep <Contribution_ID> # → Title, License, DOI, GitHub_Link, Version
# 3. Confirm on the data file (never on rendered HTML)
curl -sSL https://raw.githubusercontent.com/<org>/<repo>/main/cldf/forms.csv | python3 -c '...filter Language_ID...'
# 4. Authoritative bibliography for the languoid
curl -sSL https://raw.githubusercontent.com/glottolog/glottolog/master/languoids/tree/<path>/<gc>/md.ini
#    then resolve each [sources] key: curl -sSL https://glottolog.org/resource/reference/id/<key>   (follows 301)
```

Keep the rule that produced every finding above: **presence is a row in a data file, not a row in a
rendered web page.**
