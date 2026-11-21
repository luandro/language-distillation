# Lane 06 — NLP hubs, dataset & model artifacts (Marúbo `mzr` / Panoan)

**Survey date:** 2026-10-18
**Target:** Marúbo (Marubo), ISO 639-3 `mzr`, Glottolog `maru1252`, family Panoan (`pano1256`)
**Lane scope:** Hugging Face (datasets, models, Spaces), AmericasNLP shared-task editions, Meta
speech/translation artifacts (MMS, Omnilingual ASR, NLLB-200/FLORES, Seamless, Whisper, XLS-R),
GitHub repositories/code (incl. lexibank CLDF, wordlists, toolkits), Zenodo, Kaggle, OpenML,
LINDAT/ELRC, OPUS API, paperswithcode/model-index, G2P and orthography tooling, and prior
Panoan MT/ASR work in arXiv / ACL Anthology.

**Status legend** (used on every resource):

| Mark | Meaning |
|---|---|
| `[V]` | **Verified in situ.** The claim was checked against the actual artifact: files listed, records counted, or a machine-readable language list parsed. Numbers in this report come from those checks. |
| `[W]` | **Weak.** Artifact exists and a primary attribute (URL, license tag, card) was read, but coverage/volume could not be confirmed from the data itself, or the license text was not read verbatim. |
| `[U]` | **Unverified.** Asserted by a secondary source (index, abstract, paper) with no artifact obtained. Treat as a *lead*, not a finding. |

**Method note.** `web_search` is unusable in this session (see preflight §5). Every result below
came from `web_fetch`-equivalent direct HTTP against documented APIs and raw file URLs:
`huggingface.co/api/{datasets,models,spaces}`, `datasets-server.huggingface.co`,
`api.github.com` (repos/trees/contents), `raw.githubusercontent.com`, `zenodo.org/api/records`,
`api.openalex.org`, `export.arxiv.org/api/query`, `opus.nlpl.eu/opusapi`,
`commonvoice.mozilla.org/api/v1/{languages,stats/languages}`,
`dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html`, `pypi.org/pypi/<pkg>/json`.
Language coverage was established by **parsing the artifact's own language inventory** — HF
`tree` listings, CLDF `languages.csv`, model `lang_ids.py`, per-language result CSVs, or the
MMS coverage table — never by trusting a card's marketing text.

---

## 0. Headline findings

1. **The Meta ASR stack does not cover Marúbo, but it does cover three Panoan languages.**
   Omnilingual ASR's authoritative language list (`lang_ids.py`, 1,668 language–script pairs)
   contains **`mcf_Latn` (Matsés), `shp_Latn` (Shipibo-Konibo) and `cbs_Latn` (Cashinahua/Kashinawa)**
   and **not `mzr`**. This matters directly: the project deploys Omnilingual ASR, so
   *Matsés and Shipibo inference is available today as a sister-Panoan acoustic/orthographic
   reference and as a cross-check target*, while Marúbo needs its own path.
2. **Omnilingual ASR's public corpus release is a 348-language subset, not 1,600.** The
   `facebook/omnilingual-asr-corpus` repo contains exactly 348 `data/<lang>_<Script>/` directories
   and **zero Panoan and zero major South-American languages** (no `qu`, `ay`, `gn`, `aym`).
   The 1,600-language claim belongs to the *model*, not to the released data. Anyone assuming
   the corpus covers what the model covers is wrong.
3. **Four CC-BY-4.0 CLDF comparative datasets carry Marúbo lexical forms — 324 + 187 + 52 + 429
   records.** `oliveiraprotopanoan` (324 rows / 266 concepts) and `zariquieypano` (187 rows /
   181 concepts, source `fleck2005`) are the strongest: cognate-annotated, Proto-Panoan-linked,
   machine-readable. This is the single biggest *usable-now* Marúbo data discovery in this lane.
4. **A 13,382-entry Marúbo FLEX database exists but is unpublished.** Pedrosa & Oliveira (UFAM,
   2024) report a FLEx lexicon of 13,382 Marúbo lexemes — and state explicitly that no such
   database existed before. No artifact was found; the abstract is the only public trace.
   **Its single source book is itself an actionable lead** (§6).
5. **Shipibo-Konibo is the only Panoan language with a working NLP toolchain**: a 14,592-pair
   ES↔SH MT corpus (AmericasNLP 2021/2024/2025), a 30,180-pair HF parallel corpus, BERT POS
   taggers (F1 0.93), a 14,588-row UniMorph inflection table, a CoNLL-U treebank, an MIT-licensed
   `chana` toolkit, and MMS ASR+TTS. **Marúbo has none of these.**
6. **Only one Panoan language has open speech data in Common Voice** — `mcf` Matsés, 11 validated
   hours / 21 speakers / 997 sentences; 445 locales total, **`mzr` absent**.
7. **Explicit, re-verified negatives.** NLLB-200/FLORES-200, Glot500, Whisper, Seamless-M4T,
   M2Lingual, OPUS (1,064 languages), Epitran (162 G2P maps): **no Panoan language at all**.
   OPUS was re-checked by a *different method* than the preflight pass (API instead of page
   scraping) and the negative holds.
8. **No invented-coverage trap fired on any single-artifact claim**, but two systemic traps were
   found and are flagged: (a) the Omnilingual *corpus* card's `language:` frontmatter lists only
   the 348 released languages while surrounding prose and the model claim 1,600+; (b) GitHub
   search for `marubo` is ~100% false positives (`MaruBot`, `marubozu` candlestick charts).

---

## 1. Part A — Marúbo data usable now

These artifacts contain actual `mzr` forms with a retrievable file, a stated license, and a
countable volume. All are **lexical**, all are **derived from published literature**
(observation-vs-inference care applies: the CLDF transcription is a *published-source
observation*, the cognate assignment and any Proto-Panoan reconstruction are *inference*).

| slug | name / what it is | URLs | contents + verified volume | formats | license (verbatim) | rights holder / access | task fit | trust note | status |
|---|---|---|---|---|---|---|---|---|---|
| `oliveiraprotopanoan` | Lexibank CLDF conversion of Soares de Oliveira's 2014 PhD thesis: Proto-Panoan forms + reflexes in 18 Panoan languages | repo `https://github.com/pano-takanan-history/oliveiraprotopanoan`; data `.../main/cldf/forms.csv` | 7,305 forms total; **324 `Language_ID=Marubo` rows over 266 distinct Concepticon-style concepts**, all 324 with `Cognacy` + `ProtoSet`. 20 varieties incl. Korubo 162, Matís 244, Matsés 258, Shipibo 544, Kakataibo 528, Amahuaca 548 | CSV + JSON-LD (`cldf-metadata.json`), CLDF 1.x; BIPA-segmented (`Segments`), grapheme profile | GitHub license `CC-BY-4.0`; LICENSE is the 18,652-byte CC BY 4.0 legalcode; README: *"This dataset is licensed under a CC-BY-4.0 license"* | Lexibank / `pano-takanan-history` org; Oliveira 2014 thesis as source. Public, no auth | Marúbo **lexicon** bootstrap; cognate sets for hypothesis generation; Proto-Panoan ↔ Marúbo correspondence mining; concept-aligned comparison against sisters | **Best provenance of the CLDF set** — per-form `Source` column populated. Per-form sources: Cesarino2008 (95), Oliveira2014 (81), Anonby2010 (70), Costa1992 (27), Cabral2010 (21), Kennell1978 (15), Cabral2009 (5), Boutle1964 (4), Melatti2005 (3), Costa2000 (1). Costa1992/Costa2000/Cesarino2008 are already in the LKB index → **lineage must point to those records, not re-ingest blindly.** Mixed source orthographies; `Comment`/`UncertainCognacy` columns exist and must be preserved | `[V]` |
| `zariquieypano` | Zariquiey, Blum, Greenhill & List — cognate-annotated CLDF dataset for Pano languages ("work in progress") | repo `https://github.com/pano-takanan-history/zariquieypano`; data `.../main/cldf/forms.csv`; Zenodo `https://doi.org/10.5281/zenodo.20322670` (v0.4, 2026-05-21, 300 MB zip) | 4,265 forms; **187 `Marubo` rows / 181 concepts**, every row sourced `fleck2005`. 31 varieties; Marubo `SubGroup=Northern`, `SourceDate=2005` | CSV/CLDF; Zenodo release is a 300 MB zip of the same | GitHub `CC-BY-4.0`; README: *"This dataset is licensed under a CC-BY-4.0 license"* | Zariquiey et al. / `pano-takanan-history`. Public | Same as above; **prefer this over `oliveiraprotopanoan` for Marúbo breadth-per-marker** (single consistent source, Fleck 2005, uniform transcription) | Uniform single-source (fleck2005) is a *strength* for consistency and a *limit* for breadth. Explicitly labelled "work in progress" — cite the Zenodo **version** DOI, not the concept DOI, and expect change | `[V]` |
| `protopanotakana` | CLDF comparative Pano-Tacanan database (53 varieties, historical sources) | repo `https://github.com/pano-takanan-history/protopanotakana`; data `.../main/cldf/forms.csv` | 20,455 lexemes, 1,076 concepts, 6,585 cognate sets. Marúbo is present **under the name `Culino`**: `Language_ID=Culino`, `Name=Marúbo`, `Glottocode=maru1252`, `ISO=mzr`, **429 rows / 375 concepts**, `Source=martius1867` | CSV/CLDF | GitHub `CC-BY-4.0`; README: *"This dataset is licensed under a CC-BY-4.0 license"* | `pano-takanan-history`. Public | Historical (1867) Marúbo lexical attestation — potentially valuable for diachrony, **not** for a modern synchronic lexicon | **Two hard cautions.** (1) `Culino`→Marúbo is a *scholarly identification*, and it is contested — see Fleck 2007, *"Did the Kulinas become the Marubos?"* (DOI `10.70845/2572-3626.1042`). Record as hypothesis, never as `mzr` truth (invariant 8 in spirit; observation≠inference). (2) CLDF badge reports **`Source: 0%`** — no per-form source attribution in the file, so lineage stops at the dataset. Also 1867 orthography/segmentation is coarse | `[V]` |
| `valenzuelazariquieypanotakana` | Valenzuela & Zariquiey CLDF Pano-Tacanan comparison | repo `https://github.com/pano-takanan-history/valenzuelazariquieypanotakana` | 856 forms, 33 variety IDs (incl. `ProPa`, `ProTa` proto-rows). Marúbo under `Language_ID=Mar`: **52 rows / 37 concepts**, `Source=Valenzuela2023` | CSV/CLDF | GitHub `CC-BY-4.0` | Valenzuela / Zariquiey. Public | Small, high-quality concept-aligned Marúbo subset; useful as a **second independent transcription** to cross-check `zariquieypano` | Tiny (37 concepts). Useful chiefly for inter-source agreement checks on Marúbo transcription | `[V]` |
| `pedrosa2024_banco_dados_marubo` | "Banco de Dados da Língua Marubo" — FLEx database of 13,382 Marúbo lexemes (Pedrosa & Oliveira, UFAM) | abstract PDF `https://static.even3.com/formulario-inscricao/ResumoExpandido-CONICPIB-LLA-0085-2022-BancodeDadosdaLnguaMarubo.33ccd29adc1b42289b17.pdf`; DOI `https://doi.org/10.29327/xxxii-congresso-de-iniciacao-cientifica-380957.768609` | **13,382 lexical entries** asserted; built in FieldWorks Language Explorer (FLEx) from a single 117-page book. **No database file published** — abstract only | FLEx (`.fwdata`) — *not distributed*; abstract is PDF | **No license stated** anywhere in the abstract | Universidade Federal do Amazonas (UFAM), grupo Línguas e Culturas Amazônicas (LCA); authors Judith Ferreira Pedrosa, Sanderson Castro Soares de Oliveira | Would be the **largest single Marúbo lexicon** if it can be obtained. Currently: a contact route, not data | **Do not count this as coverage.** It is the kind of item the repo must never let into a language list as if held. Abstract itself claims *"a inexistência de outros bancos de dados da língua Marubo"* (no other Marúbo database existed) — consistent with my finding that no digital Marúbo lexicon is public. Route to a human: request data + terms from UFAM/LCA | `[V]` (abstract verified) / `[U]` (the data) |

**Assessment for Part A.** The four CLDF datasets are the only *retrievable* Marúbo data in this
lane, and they overlap heavily (all ultimately trace to Costa 1992/2000, Cesarino 2008, Fleck
2005, Oliveira 2014). After de-duplication a realistic unique Marúbo lexical yield from this lane
is **on the order of 500–900 distinct concept–form pairs**, not 992. Any ingestion work must key
on concept + source to avoid double-counting, and must preserve `UncertainCognacy` / `Comment`.

---

## 2. Part B — Sister-Panoan data (transfer, hypotheses, evaluation only)

Invariant 8 applies without exception: **none of this may become `mzr` truth.** These artifacts
create hypotheses, supply typological priors, or serve as evaluation/transfer material.

| slug | name / what it is | URLs | contents + verified volume | formats | license (verbatim) | rights holder / access | task fit | trust note | status |
|---|---|---|---|---|---|---|---|---|---|
| `americasnlp_shipibo_2021` | AmericasNLP 2021 shared-task ES↔Shipibo-Konibo data | repo `https://github.com/AmericasNLP/americasnlp2021`, dir `data/shipibo_konibo-spanish/`; task site `https://americasnlp.org/americasnlp_2021.html` | **train 14,592 pairs; dev 996; test 1,003 (es only — targets held out).** Three concatenated sub-corpora also shipped separately: `dictionary.*` (SIL dictionary entries, sil.org/resources/archives/30143), `educational.*` (bilingual-education book translations), `flashcards.*` (Tatoeba sample translated to Shipibo) | plain parallel text (`.shp`/`.es`), UTF-8, line-aligned | **No license declared** — GitHub API `license: null`; README cites papers only. Sub-sources: Tatoeba (CC-BY 2.0 FR for the Tatoeba side), SIL dictionary (SIL terms), educational books | AmericasNLP organisers; underlying rights split across Tatoeba / SIL / MINEDU-lineage book translations. Public, no auth | **Primary sister-Panoan MT resource.** Bidirectional ES↔SH baseline; morphology-aware tokenisation experiments; a template for what a Marúbo ES↔MZR corpus should look like | Rights are genuinely composite and unstated — the harness licenses nothing. Treat `<distill_only>`-adjacent until a human resolves the SIL/educational provenance per ADR-0023. Note the SH side uses practical orthography, not IPA | `[V]` |
| `americasnlp_shipibo_2025` | AmericasNLP 2025 ST1 Shipibo-Konibo package (supersedes 2021, adds mined + synthetic) | repo `https://github.com/AmericasNLP/americasnlp2025`, dir `ST1_MachineTranslation/data/shipibo_konibo-spanish/` | Same 14,592 train / 996 dev, **plus `extra.tsv` 3.20 MB (mined, per De Gibert et al. 2023) and `synthetic.tsv` 3.21 MB (back-translated)**. Columns: `origin_tag \t source \t target` | TSV + parallel text | No license declared (repo `license: null`) | AmericasNLP / Helsinki-NLP | Extra/synthetic data is exactly the augmentation shape this project already contemplates; the `origin_tag` column models provenance-tagging well | `synthetic.tsv` is **machine-generated** — in this repo's terms it is hypothesis-grade and must never be treated as observed Shipibo, let alone as Panoan truth for Marúbo | `[V]` |
| `hf_spanish_shipibo_30180` | `pollitoconpapass/spanish_2_shipibo_konibo` — HF parallel corpus | `https://huggingface.co/datasets/pollitoconpapass/spanish_2_shipibo_konibo` | **train 24,144 / validation 3,018 / test 3,018 = 30,180 ES↔SH pairs**, 2.59 MB text. Rows inspected via datasets-server: genuine Shipibo (e.g. `"Volveré." / "Eara joribai."`, `"Gracias." / "Irake."`) | Parquet (3 shards) | **No license tag and no license text.** Card contains *only* auto-generated `dataset_info` frontmatter — no prose, no authors, no provenance | Uploader `pollitoconpapass` (unclear standing). Public, ungated | Largest single ES↔SH parallel pool found. Volume is attractive for transfer experiments | **Provenance is unknown and there is no license.** Content mixes everyday phrases with what look like health/literacy-worker training sentences. Prefer `americasnlp_shipibo_*` (documented lineage) over this for anything that will be cited; if used, quarantine behind an explicit `policy_id` and do not let the volume impress anyone | `[V]` |
| `keypano` | Key & Comrie IDS data for Pano-Tacanan languages, standardized transcription — CLDF (Miller & List 2024) | repo `https://github.com/intercontinental-dictionary-series/keypano`; Zenodo `https://doi.org/10.5281/zenodo.13234493` | **23,232 forms / 1,310 concepts / 22 varieties.** Panoan: Yaminahua 1,347, Shipibo-Conibo 1,334, Catuquina 1,124, Chácobo 1,019, Cashibo 744, Ese Ejja 968/710, Cavineña 1,005, Araona 1,125, Tacana 1,190, Pacahuara 100, Mashco Piro 569. **No Marúbo** | CSV/CLDF; full Concepticon linkage (`Key-2016-1310`, badges: Glottolog 100%, Concepticon 100%, Source 100%, BIPA 100%) | GitHub `CC-BY-4.0`; README: *"This dataset is licensed under a CC-BY-4.0 license"* | IDS (Key & Comrie) → Miller & List 2024 (doi via CALC). Public | **Best concept-aligned sister set in this lane.** 1,310 concepts × 11 Panoan varieties is a strong basis for cognate/reflex hypothesis generation for Marúbo | Clean, fully sourced, per-form source present. Adjacent-family positives too (Aguaruna, Yagua, Movima, Mosetén) but those are *not* Panoan — do not let the card's "Panoan" framing leak | `[V]` |
| `common_voice_mcf` | Mozilla Common Voice — **Matsés (`mcf`) locale** | locales/stats API `https://commonvoice.mozilla.org/api/v1/stats/languages`; dataset `https://huggingface.co/datasets/mozilla-foundation/common_voice_17_0` | **`mcf`: recordedHours 11, validatedHours 11, invalidatedHours 0, speakersCount 21, sentences 997 / target 750.** Presence verified against all **445** CV locales: `mcf` is the **only Panoan locale**; `mzr` absent | MP3 clips + TSV metadata (CV standard) | License text not read verbatim in this lane (dataset is gated behind HF terms acceptance) — **CV datasets are published CC0 1.0; confirm at download** | Mozilla Foundation + Matsés contributors. **Gated**: HF account + terms acceptance | The only open Panoan *speech* corpus with validation. Useful for: acoustic/prosodic priors, an ASR evaluation set for the `mcf_Latn` Omnilingual path, and a concrete template for a Marúbo CV locale campaign | 11 h / 21 speakers is small and demographically narrow (likely few speakers, read sentences). `is_contributable: 1` and `localizedPercentage: 7` mean the interface is barely localised — community-contribution infrastructure is not really in place | `[V]` (stats) / `[W]` (license wording) |
| `ud_kakataibo_shipibo_treebanks` | "Building an Endangered Language Resource in the Classroom" (LREC 2022) — first release of the **Kakataibo and Shipibo** treebanks + embeddings | repo `https://github.com/FredericBlum/Building-an-Endangered-Language-Resource-in-the-Classroom`; paper `https://arxiv.org/abs/2206.10343` | CoNLL-U under `data/Kakataibo/conllu/` (**1,262 tokens**) and `data/Shipibo/conllu/` (**5,365 tokens** in `all_in_one.conllu`), with train/dev/test splits, **delexicalised** variants, and trained embeddings (`glove.txt` 1.85 MB, `word2vec.txt` 1.83 MB, `gensim_cbr` 1.12 MB). UPOS + XPOS + FEATS (`Clitic=Nomcl`, `Clitic=Spcl`) | CoNLL-U, plain text embeddings | LICENSE is *"Attribution-ShareAlike 4.0 International"* (CC BY-SA 4.0) | Blum, Zariquiey et al. Public | **Annotation-scheme transfer** for a future Marúbo treebank; UD label inventory for a Panoan language; delexicalised splits are a good low-resource modelling template | Tiny (1.3k / 5.4k tokens) but genuine gold UD. CC BY-SA is **share-alike** — derivative annotation must carry the same licence (relevant to LKB export policy). Shipibo XPOS carries clitic features, which is directly germane to Marúbo clitic/particle analysis | `[V]` |
| `unimorph_shp` | UniMorph paradigm table for Shipibo-Konibo | repo `https://github.com/unimorph/shp`, file `shp` | **14,588 inflection rows / 2,016 lemmas / 7 feature bundles** (`N`, `N;ER`, `N;ABS`, `N;DAT`, …). `lemma ⌗ form ⌗ features` | TSV (UniMorph standard) | **No license declared on this repo** (UniMorph organisation-wide practice is CC BY-SA; verify before use) | Annotators: Oncevay, Angulo Pando, Zariquiey. Sources: Loriot et al. 1993 *Diccionario Shipibo-Castellano*; Valenzuela 2003 | **Paradigm template.** Shipibo marks ERG/ABS/DAT — the same case dimensions Costa 1992 describes for Marúbo. A ready-made shape for a `mzr` paradigm table and for the SIGMORPHON-2021-style reinflection task | Nouns only, 7 bundles — shallow. But it is the only *morphological paradigm* artifact for a Panoan language in this lane, and the ERG/ABS/DAT alignment with Marúbo case marking is the most directly transferable structure found | `[V]` |
| `chana_shipibo_toolkit` | `chana` — NLP toolkit for Shipibo-Konibo | repo `https://github.com/iapucp/chana-library` (fork `https://github.com/jpereiran/chana`); PyPI `chana` | Lemmatizer, POS tagger, NER annotation, syllabificator. Built on scikit-learn + python-crfsuite | Python package | MIT (`license: MIT` on repo; README: *"distributed under MIT license"*) | IAPUC/PUCP (Oncevay et al.). Public | **Architecture reference** for a `mzr` toolchain: CRF + rule syllabification is the right complexity level for a language with a few thousand tokens | Code, not data — it ships no Marúbo content and (from the README) no large bundled lexicon. Value is methodological: a Panoan-specific precedent for lemmatiser/POS/syllabifier design | `[V]` |
| `shipibo_pos_models` | BERT POS taggers for Shipibo-Konibo | `https://huggingface.co/floressullon/shipibo_pos_tagging_v1` (`_v2`, `_v3`) | v1: `BertForTokenClassification`, 16-label UD-ish tagset (`ADJ ADP ADV AUX CONJ DET INTJ INTW NOUN NUM ONM PRON PROPN PUNCT SYM VERB`). v2: based on `bert-base-multilingual-cased`, **P 0.93 / R 0.94 / F1 0.93 / Acc 0.95**, 3 epochs. v3: auto-generated card, no metadata | HF `transformers` / safetensors | v1 `license: apache-2.0`; v2 `license: mit`; v3 **none** | Uploader `floressullon`; training data/provenance undocumented | A working Panoan POS baseline; the 16-label tagset is reusable as a `mzr` annotation scheme proposal | **Do not treat F1 0.93 as meaningful without knowing the split** — the card states no train/dev provenance and no data source. This is a demo-grade artifact, not a benchmark | `[V]` (card/config) / `[W]` (metrics) |
| `iapucp_shashiyayi` | ShaShiYaYi — monolingual corpora of Peruvian languages (Shipibo, Asháninka, Yine, Yanesha) | repo `https://github.com/iapucp/multilingual-data-peru`, dir `ShaShiYaYi/` | `shp`: train.txt 1.44 MB, valid 46.8 KB, test 48.5 KB; also `cni`, `pib`, `ame`. **No Marúbo** | plain text, one sentence per line | **No license declared** (repo `license: null`) | IAPUC/PUCP; per Bustamante, Oncevay & Zariquiey LREC 2020 (PDF-extracted corpora) | Monolingual LM/domain adaptation material for a Panoan language | PDF-extraction artefacts are likely present (the source is PDF scraping) — expect noise. No `mzr` | `[V]` |
| `zariquiey_pano_numerals` | "Numerals and Exact Quantity Referring Expressions in 13 Pano languages" (Zariquiey) | Zenodo `https://doi.org/10.5281/zenodo.14010833` (2024-10-30) | 13 languages, numerals 1–10 + non-conventionalised exact-quantity expressions. **Languages: Amahuaca, Chakobo, Chaninawa, Hunikuin, Iskonawa, Kakataibo, Kapanawa, Marinawa, Mastanawa, Matses, Shipibo-Konibo, Sharanawa, Yaminawa — NO Marúbo** | 27 XLSX/CSV files (`Pano_Numerals_Zariquiey.xlsx` 24.6 KB consolidated) | Zenodo `cc-by-4.0` | Roberto Zariquiey. Public | Narrow typological comparison; a ready template for a Marúbo numeral elicitation sheet | Very small (~10 items × 13 langs). Explicitly a **negative for `mzr`** — useful only as method | `[V]` |
| `blumpanotacana` | Blum et al. 2024 comparative wordlist for distant Lowland South American relations (CLDF) | repo `https://github.com/pano-takanan-history/blumpanotacana`; paper `https://doi.org/10.1038/s41597-024-02928-7` | 21 varieties, **no Marúbo** (verified in `cldf/languages.csv`) | CSV/CLDF | GitHub `CC-BY-4.0` | Blum et al. Public | Background phylogeny only | **Negative for `mzr`** — worth recording because it is the most likely dataset to be *assumed* to contain Marúbo (it is the flagship Panoan comparative wordlist) | `[V]` |
| `amazonianlp_survey` | AmazoniaNLP: A Survey of Extreme Low-Resource Languages in the Peruvian-Brazilian Amazon (LREC 2026, SIGUL) | PDF `http://www.lrec-conf.org/proceedings/lrec2026/workshops/sigul/pdf/2026.sigul-1.28.pdf`; DOI `https://doi.org/10.63317/3sbz29bn779p` | Survey of 5 focal languages: **Matsés, Amahuaca, Kashinawa, Ticuna, Kukama-Kukamiria**. States these "lack sufficient digital data". **Marúbo is not a focal language** | PDF | LREC proceedings terms (not read verbatim) | Zevallos, Carraro, Ortega. Public | **Corroboration + citation** for the near-absence claim; its per-language asset table is a good model for this survey's output | Written independently and reaches the same conclusion: Panoan NLP assets are grammars/dictionaries, not corpora. Use as external corroboration, not as a data source | `[V]` |

---

## 3. Part C — Model artifacts (ASR/MT bootstrapping & evaluation only)

| slug | name / what it is | URLs | contents + verified language coverage | formats | license (verbatim) | rights holder / access | task fit | trust note | status |
|---|---|---|---|---|---|---|---|---|---|
| `omniasr_models` | Omnilingual ASR (Meta) — CTC / LLM / W2V models, 300M–7B | models `https://huggingface.co/facebook/omniASR-LLM-7B` (+ `-CTC-*`, `-W2V-*`, `-LLM-*-ZS`); **authoritative language list** `https://raw.githubusercontent.com/facebookresearch/omnilingual-asr/main/src/omnilingual_asr/models/wav2vec2_llama/lang_ids.py`; per-language results `.../per_language_results_table_7B_llm_asr.csv`; repo `https://github.com/facebookresearch/omnilingual-asr`; demo `https://huggingface.co/spaces/facebook/omniasr-transcriptions` | **1,668 language–script pairs / 1,648 distinct ISO codes** (parsed from `lang_ids.py`). **`mzr` ABSENT.** Panoan present: **`mcf_Latn` (7.3 train h, CER 5.6)**, **`shp_Latn` (27.1 h, CER 1.1)**, **`cbs_Latn` (33.1 h, CER 0.9)**. Also `cni_Latn` (Asháninka 29.0 h / 0.7), `kaq_Latn` (63.1 h / 1.3), `pib_Latn` (Yine 45.3 h / 1.0), `quy_Latn`, `quz_Latn`, `ayr_Latn`. Not present: `mpu`, `xor`, `yag`, `qu`, `ay`, `gn`, `arn` | PyTorch `.pt` (LLM-7B weights 31 GB), HF `transformers`, sherpa-onnx / MLX / CoreML / LiteRT community ports | Model cards: `license: apache-2.0` | Meta AI (Omnilingual ASR Team). Public, ungated | **The central artifact for this project.** (i) `mcf`/`shp` inference gives a working sister-Panoan ASR reference and a real orthography↔acoustics sanity check; (ii) the per-language CSV gives **published CER floors** to benchmark a future `mzr` model against; (iii) `-ZS` zero-shot variants are the honest path for `mzr` | **`mzr` is genuinely absent — do not claim ASR coverage.** The per-language training hours are the load-bearing detail: `mcf` at 7.3 h achieving CER 5.6 shows a credible data budget for a Marúbo attempt. Apache-2.0 on the weights, but the *training data* is separately licensed (see next row) | `[V]` |
| `omniasr_corpus` | `facebook/omnilingual-asr-corpus` — released training corpus | `https://huggingface.co/datasets/facebook/omnilingual-asr-corpus`; API tree `.../tree/main/data` | **Exactly 348 language directories** (`data/<iso>_<Script>/`), enumerated. **Zero Panoan; zero South-American indigenous** — no `mzr`, `shp`, `mcf`, `cbs`, `qu`, `ay`, `gn`, `aym`. Fields: `raw_text`, `speaker_id`, `segment_id`, `audio`, `language`, `glottocode` | FLAC audio + metadata | Card: *"This corpus is released under CC-BY-4.0."* frontmatter `license: cc-by-4.0` | Meta AI. Public, ungated | **Not usable for Marúbo or any Panoan language.** Value is methodological: the schema (`glottocode` column, `<laugh>`/`<hesitation>`/`<unintelligible>`/`<noise>` tags, false-start hyphenation) is an excellent target schema for a Marúbo corpus | **The 348-vs-1,600 gap is the single most important false-coverage hazard in this lane.** The card's `language:` frontmatter lists 348; the README prose and model name say 1,600+. The 1,600 belongs to the model's training mix, which is *not* released. Never cite "Omnilingual ASR corpus (1,600 languages)" as if the data were downloadable | `[V]` |
| `mms` | Meta MMS — ASR / TTS / LID, 1,000+ languages | coverage table `https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html`; models `https://huggingface.co/facebook/mms-1b-all`, `mms-1b-l1107`, `mms-1b-fl102` | Table has **4,022 language rows** with per-language ASR / TTS / LID ticks. **`mzr` "Marubo": LID only — no ASR, no TTS.** `mcf` "Matses": LID only. `amc` "Amahuaca": LID only. `ywn` "Yawanawa": LID only. `mqz` "Pano": LID only. `knt` "Katukína, Panoan": LID only. **`shp` "Shipibo-Conibo", `cbr` "Kakataibo-Kashibo", `cbs` "Kashinawa": ASR ✔ + TTS ✔ + LID ✔** | HF `transformers`, fairseq checkpoints, `.bin` | MMS models CC-BY-NC 4.0 (per MMS release terms; not re-read verbatim here) | Meta AI. Public | `shp`/`cbr`/`cbs` ASR **and TTS** are the fastest route to a synthetic Shipibo/Kakataibo/Cashinahua speech probe and to a pronunciation sanity check on Panoan orthography | **`mzr` LID ≠ `mzr` data.** The LID column covers ~4,022 Ethnologue languages, i.e. nearly the whole inventory; a tick there means only that a label existed. It carries **no** Marúbo acoustic data and must never be read as "MMS supports Marúbo". Record `mqz` "Pano" carefully — it is a *different* language from Marúbo and a classic merge hazard | `[V]` |
| `nllb200_flores200` | NLLB-200 / FLORES-200 | model `https://huggingface.co/facebook/nllb-200-distilled-600M`; codes `https://raw.githubusercontent.com/facebookresearch/flores/main/flores200/README.md`; `https://huggingface.co/datasets/openlanguagedata/flores_plus` | FLORES-200 README enumerates **204 `<iso>_<Script>` codes**; NLLB card `language:` list — **no `mzr`, no `shp`, no `mcf`, no `cbs`, no `cbr`, no `yaa`, no `amc`, no `cao`, no Panoan code at all** | JSON/parquet/text | NLLB-200 distilled 600M: **CC-BY-NC-4.0** (already recorded as negative in `candidate-source-licenses-2026-10.md`) | Meta AI | **No Panoan MT baseline exists in NLLB.** Any Marúbo MT must be trained from scratch or adapter-based on a non-Panoan pivot | Confirms the preflight negative with a different method (parsed code lists, not page text). `flores_plus` is `gated: auto` — it adds no Panoan coverage anyway | `[V]` |
| `seamless_m4t_v2` | SeamlessM4T v2 | `https://huggingface.co/facebook/seamless-m4t-v2-large` | Card `language:` = **96 languages**; no `mzr`/`shp`/`mcf`/`cbs` | PyTorch | CC-BY-NC 4.0 (Seamless terms) | Meta AI | None for Panoan | Negative — record and move on | `[V]` |
| `whisper` | OpenAI Whisper | tokenizer `https://raw.githubusercontent.com/openai/whisper/main/whisper/tokenizer.py` | `LANGUAGES` dict = **100 languages**. **No `mzr`/`shp`/`mcf`/`cbs` — and no `qu`, `ay`, `gn`** | PyTorch / HF | MIT (Whisper code & weights) | OpenAI | **Not usable.** Even Quechua/Aymara/Guaraní are absent, so Whisper is *less* Panoan-adjacent than Omnilingual | Strongest negative in the Meta/OpenAI ASR comparison — worth stating plainly to forestall "just fine-tune Whisper" proposals | `[V]` |
| `glot500` | Glot500 (CIS/LMU) — 500-language resource + model | `https://huggingface.co/datasets/cis-lmu/Glot500` | **411 language directories** enumerated (`<iso>_<Script>/`). **Zero Panoan** — `shp`, `cbs`, `mcf`, `cbr`, `cao`, `yaa`, `amc`, `mcd`, `knt`, `ywn`, `xor`, `mpq`, `mzr` all absent. South-American present: `arn`, `aym`, `ayr`, `grn`, `gug`, `quh`, `quy`, `quz` | Arrow shards | Card: `license: other`, `license_name: license` (**non-standard — must be resolved before use**) | CIS/LMU Munich | No Marúbo. Its *methodology* (language-specific vocabulary extension + continual pretraining for unseen languages) is the relevant transferable idea, not its data | Card license is an opaque pointer, not an SPDX id — an ADR-0023 blocker if anyone wants to use it | `[V]` |
| `m2lingual` | M2Lingual (ServiceNow) | `https://huggingface.co/datasets/ServiceNow-AI/M2Lingual` | Card `language:` = **58 languages**; **no Panoan**, not even `quy`/`aym` | JSON | `license: cc-by-nc-sa-4.0` | ServiceNow AI | None for Panoan | Negative. Non-commercial + share-alike anyway | `[V]` |
| `epitran` | Epitran G2P (IPA transcription) | PyPI `https://pypi.org/pypi/epitran/json` (v1.35.3); maps `https://api.github.com/repos/dmort27/epitran/git/trees/master?recursive=1` | **162 map files** under `epitran/data/map/`. **No `mzr`, `shp`, `mcf`, `cbs`, no Panoan map — and not even `spa`/`por`.** Sample maps: `aar-Latn`, `amh-Ethi`, `ara-Arab`, `ben-Beng`, `bxk-Latn` | CSV rule maps | MIT | David Mortensen et al. | **Negative, as predicted in the brief.** A Marúbo G2P must be built from Costa 2000's phonological description, not adapted from Epitran | Record as `[V]` negative via map-file enumeration — this is the strongest form of the negative (file-level, not language-list-level) | `[V]` |

**Cross-cutting model note.** Of the seven large multilingual systems checked (Omnilingual ASR,
MMS, NLLB-200, FLORES-200, Seamless, Whisper, Glot500, M2Lingual), **zero** cover Marúbo, and only
**Omnilingual ASR** and **MMS** cover *any* Panoan language with actual speech capability.
Omnilingual ASR is the better bet: it has published per-language CER, an Apache-2.0 weight
licence, a `-ZS` zero-shot path, and a data schema this project could adopt wholesale.

---

## 4. Part D — Explicit negatives (with the method used)

These are recorded so that later lanes do not re-spend effort, and so that "no result" is
distinguishable from "not looked for".

| # | Negative claim | Method actually used | Status |
|---|---|---|---|
| N1 | **No Marúbo ASR/TTS in MMS.** | Parsed `language_coverage_mms.html` into a 4,022-row table and read the `mzr` row's ASR/TTS/LID cells. | `[V]` |
| N2 | **No Marúbo in NLLB-200 / FLORES-200.** | Enumerated 204 `<iso>_<Script>` codes from the FLORES-200 README and the NLLB model card `language:` list; regex-tested for `mzr` and all Panoan codes. | `[V]` |
| N3 | **No Marúbo in Omnilingual ASR.** | Parsed `lang_ids.py` (1,668 entries) and `per_language_results_table_7B_llm_asr.csv` (1,684 rows); zero `mzr`. | `[V]` |
| N4 | **Omnilingual ASR *corpus* contains no Panoan language.** | Enumerated the 348 `data/*` directories via the HF tree API. | `[V]` |
| N5 | **No Marúbo (and no Panoan at all) in Whisper.** | Parsed the `LANGUAGES` dict from `whisper/tokenizer.py` (100 entries). | `[V]` |
| N6 | **No Panoan in Glot500.** | Enumerated 411 language directories; tested 13 Panoan ISO codes. | `[V]` |
| N7 | **No Panoan in Seamless-M4T v2 / M2Lingual.** | Read card `language:` lists (96 / 58 entries). | `[V]` |
| N8 | **No Panoan in OPUS — re-checked by a different method than the preflight pass.** | `https://opus.nlpl.eu/opusapi/?languages=True` → 1,064 language codes; `mzr`, `shp`, `mcf`, `cbs`, `cbr`, `cao`, `yaa`, `amc`, `mpu`, `xor`, `pano` all **ABSENT** (`quy`, `aym`, `gn` present). Preflight's finding was page-scrape-based; this is API-based and agrees. | `[V]` |
| N9 | **No Marúbo locale in Common Voice.** | Parsed all 445 CV locales from `api/v1/languages` and the 445-row stats endpoint. `mcf` is the only Panoan locale. | `[V]` |
| N10 | **No Panoan G2P in Epitran.** | Enumerated the 162 files in `epitran/data/map/`. | `[V]` |
| N11 | **arXiv has no work on Marúbo.** | `export.arxiv.org/api/query?search_query=all:marubo` → 0 entries; `all:%22Matses%22` → 0; `all:%22Panoan%22` → 1 (the Kakataibo UD paper); `all:%22Shipibo%22` → 6 (none Marúbo). | `[V]` |
| N12 | **GitHub repository search for `marubo` returns no language resources.** | `api.github.com/search/repositories?q=marubo` → 44 results, all false positives: `MaruBot` Twitch chatbots, `marubozu` candlestick chart tools (a Japanese candlestick pattern), profile READMEs. Zero linguistics. | `[V]` |
| N13 | **`matses` repo search returns zero language resources.** | 34 results, all German `MATSE` (a CS apprenticeship programme) coursework. `matsés` (accented) → 0. | `[V]` |
| N14 | **No Panoan in `keypano` IDS Panoan dataset.** | Parsed `cldf/languages.csv` (22 varieties) and counted 23,232 forms per language — no `mzr`. | `[V]` |
| N15 | **No Marúbo in `blumpanotacana`** (the flagship Panoan comparative wordlist). | Parsed `cldf/languages.csv` (21 varieties). | `[V]` |
| N16 | **No Marúbo in Zariquiey's 13-Pano-language numerals dataset.** | Read the record description's explicit 13-language list + file listing. | `[V]` |
| N17 | **No Marúbo in `protopanotakana` under the name "Marubo".** (It appears only as `Culino`.) | Cross-tabulated all 53 `Language_ID` values. | `[V]` |
| N18 | **No Marúbo in ShaShiYaYi monolingual corpora.** | Enumerated the 20 files / 4 language dirs (`shp`, `cni`, `pib`, `ame`). | `[V]` |
| N19 | **Hugging Face full-text search surfaces no Marúbo dataset or Panoan dataset.** | `huggingface.co/api/quicksearch?q=<q>&type=dataset` and `...&type=model` for `marubo`, `panoan`, `shipibo`, `matses` — the only hits were `pollitoconpapass/spanish_2_shipibo_konibo` and the three `floressullon` models (both already captured). | `[V]` |
| N20 | **No Marúbo/Panoan HF Space.** | `api/spaces?search=` for `marubo`, `panoan`, `shipibo`, `americasnlp` — only `marubobiz/internal-time-demo` (unrelated business demo) and `Rezavtn/pano-annotate` (panorama annotation). | `[V]` |
| N21 | **Kaggle: nothing surfaced.** | `https://www.kaggle.com/search?q=marubo+in%3Adatasets` returned a 5 KB JS shell with zero occurrences of the query — Kaggle search is not server-rendered and its API needs credentials. **Probed, not disproved.** | `[W]` |
| N22 | **OpenML / LINDAT: nothing surfaced.** | OpenML `/api/v1/json/data/list` reachable but no Panoan-relevant list endpoint without a query; LINDAT `discover?query=shipibo` → HTTP 404 (search path changed). **Probed, not disproved.** | `[W]` |
| N23 | **NTREX has no Panoan.** | NTREX-128 is built from FLORES-200 devtest, whose 204 codes contain no Panoan (N2). README grep found no Panoan code. **Inferred from derivation, not from an enumerated NTREX list.** | `[W]` |
| N24 | **SEACrowd / Masakhane / WAXAL are scope-excluded.** | SEACrowd = Southeast Asia, Masakhane/WAXAL = Africa. Geography excludes Panoan by construction; I did not enumerate their inventories. Recorded as scope-negative, not as a verified absence. | `[W]` |
| N25 | **No ACL Anthology search possible in this session.** | `aclanthology.org/search/?q=…` returns an identical 11,259-byte JS shell for every query (no server-side results); `html.duckduckgo.com` returned **HTTP 202 bot challenge** for all three queries. Recorded as a **block**, per preflight §5, not retried in a loop. OpenAlex was used as the substitute (see §5). | `[V]` (the block) |

---

## 5. Part E — False positives flagged

The brief warns that invented coverage is a serious hazard. These are the traps found, each with
the verification that defused it.

| # | Trap | Why it looks like a hit | What the artifact actually contains | Verdict |
|---|---|---|---|---|
| F1 | **Omnilingual ASR "1,600+ languages"** | Name, paper title and README prose all say 1,600+; the project deploys this model, so the claim is load-bearing | The released **corpus** has 348 language directories with zero Panoan; the **model** covers 1,668 language–scripts but **still not `mzr`** | **Not Marúbo coverage.** Never cite the 1,600 figure as data availability, and never as `mzr` capability |
| F2 | **MMS `mzr` LID tick** | The coverage table has a row literally reading `mzr / Marubo` with a ✔ | The ✔ is in the **LID** column only; ASR and TTS cells are empty. LID spans ~4,022 languages, i.e. essentially the Ethnologue inventory | **Not speech coverage.** A label existing ≠ data existing |
| F3 | **`mqz` "Pano" in MMS** | Same table, adjacent to `mzr`, named "Pano" | `mqz` is a distinct language from Marúbo (`mzr`), with its own row and LID-only status | **Merge hazard.** Preflight explicitly warns against merging Panoan codes; this is exactly where it would happen |
| F4 | **`protopanotakana` "Culino"** | `languages.csv` maps `Culino` → `Name=Marúbo`, `glottocode=maru1252`, `ISO=mzr` — it *is* Marúbo by the dataset's own metadata | 429 forms under a name that appears nowhere as "Marubo". A search for `marubo` in `forms.csv` finds nothing. Also: the `Culino`=Marúbo identification is contested (Fleck 2007) | **Real data, but invisible to naive search and hypothesis-grade in its language identification.** Both facts must be recorded |
| F5 | **GitHub search `marubo`** | 44 repositories | 100% false positives: `MaruBot` Twitch bots, `marubozu` candlestick patterns, `Maruboina` surnames, profile READMEs | **Zero language resources.** The correct query is `panoan` / `lexibank` / the `pano-takanan-history` org |
| F6 | **GitHub search `matses`** | 34 repositories | All German `MATSE` (IT apprenticeship) coursework. The accented `matsés` returns 0 | **Zero language resources.** Script/accent handling matters |
| F7 | **HF model search `pano`** | 40 models | 100% `panoptic` segmentation, `panorama`, `PanoEvJ` user names. Similarly `matis` → 51 datasets, all Latvian/`Matisse` | **Zero language resources.** ISO codes `shp`/`mcf`/`cbs` are also unusable as search keys (too short/ambiguous) — hence the need to go through language *lists*, not search |
| F8 | **`marubok/wan` (HF model)** | Model id contains "marubo" | README returns 404; unrelated GGUF upload by a user whose handle is `marubok`. Not a Marúbo model | **False positive** |
| F9 | **`pollitoconpapass/spanish_2_shipibo_konibo` license** | 30,180 pairs, looks like a generous open corpus | **No license tag, no license text, no author, no provenance** — the card is auto-generated `dataset_info` only | **Not a licence trap but a provenance trap.** Volume must not be read as quality or as usable rights |
| F10 | **`floressullon/shipibo_pos_tagging_v2` F1 0.93** | Concrete, impressive metrics on a Panoan low-resource task | Card states no train/dev source, no split definition, no data provenance; v3 has an entirely auto-generated card | **Metric without a benchmark.** Do not cite 0.93 as a comparable Panoan POS result |

---

## 6. Ranked top-3 (what the parent should act on first)

### 1. `omniasr_models` — Omnilingual ASR Panoan coverage map (action: adjust the ASR plan)

**Why first:** it changes what the project can do *this week*. The model covers `mcf` (7.3 h →
CER 5.6), `shp` (27.1 h → CER 1.1) and `cbs` (33.1 h → CER 0.9) and **does not cover `mzr`**.
That yields three concrete moves: (i) run `mcf`/`shp` inference on Marúbo-adjacent audio to
characterise what Panoan phone sequences the model already handles; (ii) benchmark any future
`mzr` model against the published Panoan CERs rather than against an English baseline; (iii) use
`omniASR_LLM_7B_ZS` (zero-shot) as the honest `mzr` path, since no `mzr` head exists.
Authoritative list: `lang_ids.py` (1,668 entries). Apache-2.0 weights, ungated.
**Do not** tell anyone Omnilingual ASR "supports Marúbo" — it does not (F1, N3, N4).

### 2. `zariquieypano` + `oliveiraprotopanoan` — Marúbo lexical evidence, CC-BY-4.0 (action: harvest)

**Why second:** the largest *retrievable* Marúbo data found anywhere in this lane, with a clean
licence, machine-readable structure and per-form sourcing (`zariquieypano` is uniformly
`fleck2005`; `oliveiraprotopanoan` is multi-source and already overlaps the LKB via
Costa1992/2000 and Cesarino2008). Combined: **324 + 187 = 511 Marúbo form records** before
de-duplication. Both carry cognate sets and Proto-Panoan membership, which is exactly the
machinery needed to generate (not assert) Marúbo lexical hypotheses. Ingest with
`trace_id` → source → CLDF row; preserve `UncertainCognacy` and `Comment`.
Add `valenzuelazariquieypanotakana` (52 rows) as a second transcription for cross-checking,
and `protopanotakana`'s `Culino` rows (429) only *after* a human rules on the Culino=Marúbo
identification (F4).

### 3. `pedrosa2024_banco_dados_marubo` — the 13,382-entry FLEX lexicon (action: route to a human)

**Why third:** it is the largest Marúbo lexicon reported to exist (over 2× everything found
elsewhere combined) and it is **not published** — so it is simultaneously the highest-value and
zero-currently-usable item in this lane. A request to UFAM / LCA (Judith Ferreira Pedrosa;
Prof. Sanderson Castro Soares de Oliveira, sanderson@ufam.br) is the single highest-expected-value
outreach action available. **Do not record it as coverage until a file exists.**
Its stated single source — the 117-page book *Vana nía anosh tanati Askai awe iki inã anosho
tanaa* (anonymous) — is a separate, independently huntable lead.

---

## 7. Open leads needing a human (not resolvable from this lane)

| Lead | Why it matters | Next action | Why an agent cannot close it |
|---|---|---|---|
| `Vana nía anosh tanati Askai awe iki inã anosho tanaa` (117 pp., no author) | Sole source of the 13,382-entry Marúbo lexicon; if obtainable it is the largest single Marúbo lexical source known | Look for a Marúbo literacy/primer PDF; check UFAM/LCA, Museu do Índio, SIL Brazil, `scriptureearth`, Brazilian MEC/local school materials | No library/archive search interface was reachable; item is not in any indexed digital repository I could query |
| UFAM LCA FLEX database | 13,382 Marúbo lexemes, in `distill_only`-safe hands | Email request; ask for licence + register + authority basis per ADR-0023 | Requires human contact and a data-sharing agreement |
| `pollitoconpapass/spanish_2_shipibo_konibo` provenance | 30,180 ES↔SH pairs, currently un-licenced | Identify the uploader; try to recover the original corpus it was assembled from | No contact route from the card |
| AmericasNLP Shipibo sub-source rights (SIL dictionary / educational books / Tatoeba) | Determines whether the 14,592-pair corpus is trainable under this repo's policy | Resolve per ADR-0023 before ingestion | Composite third-party rights; needs a human judgement |
| Contested `Culino` = Marúbo identification | Gates 429 historical forms in `protopanotakana` | Read Fleck 2007 (DOI `10.70845/2572-3626.1042`) and decide | Scholarly judgement, not a data-availability question |
| ACL Anthology search | Untested territory: Panoan papers not indexed by arXiv/OpenAlex | Retry `aclanthology.org` search from a browser session, or use the Anthology's bulk BibTeX | Server-side search is JS-only; DDG served a bot challenge (N25) |

---

## 8. Cross-lane notes

- **Lane 01 (CLDF/Lexibank/IDS/Keypano) will overlap Part A.** `oliveiraprotopanoan`,
  `zariquieypano`, `protopanotakana`, `valenzuelazariquieypanotakana`, `keypano`,
  `blumpanotacana` are all `lexibank`/CLDF artifacts. They are listed here because the brief
  explicitly assigned "lexibank CLDF datasets, `oliveiraprotopanoan`, `keypano`" to this lane.
  The **form-level counts and licences above are the contribution**; the digest should take
  whichever lane's description is richer and not double-count volumes.
- **Lane 02 (academic literature)** should pick up: Pedrosa & Oliveira 2024 (UFAM abstract),
  Fleck 2007 (Kulina/Marubo), "Vestiges of body-part prefixation in Marubo" (2022,
  `10.1093/oso/9780198852476.003.0015`), Smith 2021 (switch reference in Marubo, Trinity Western),
  Jaques 2021 (UFAM, Marubo Portuguese), Zevallos/Carraro/Ortega 2026 (AmazoniaNLP survey).
  These surfaced through OpenAlex, not through this lane's core hubs.
- **Lane 04 (parallel corpora)** should not re-do Shipibo: the AmericasNLP packages and the HF
  30k corpus are catalogued here with volumes.
- **Lane 03/05 (archives, media)** own the audio/video side. The one speech item this lane found
  is the Common Voice `mcf` locale (11 validated hours) — coordinate so it is not missed.

---

## 9. Method appendix (reproducible)

```bash
# Hugging Face inventories
curl -s "https://huggingface.co/api/datasets?search=<q>&limit=60"
curl -s "https://huggingface.co/api/models?search=<q>&limit=40"
curl -s "https://huggingface.co/api/spaces?search=<q>&limit=15"
curl -s "https://huggingface.co/api/quicksearch?q=<q>&type=dataset"
curl -s "https://huggingface.co/api/datasets/<id>/tree/main?recursive=true"
curl -s "https://datasets-server.huggingface.co/rows?dataset=<id>&config=default&split=test&offset=0&length=15"

# Omnilingual ASR authoritative coverage
curl -sL "https://raw.githubusercontent.com/facebookresearch/omnilingual-asr/main/src/omnilingual_asr/models/wav2vec2_llama/lang_ids.py"
curl -sL "https://raw.githubusercontent.com/facebookresearch/omnilingual-asr/main/per_language_results_table_7B_llm_asr.csv"
curl -s  "https://huggingface.co/api/datasets/facebook/omnilingual-asr-corpus/tree/main/data"

# MMS coverage (4,022 rows; ASR / TTS / LID columns)
curl -s "https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html"

# CLDF / lexibank
curl -sL "https://raw.githubusercontent.com/<org>/<repo>/main/cldf/languages.csv"
curl -sL "https://raw.githubusercontent.com/<org>/<repo>/main/cldf/forms.csv"

# Speech locale inventory
curl -s "https://commonvoice.mozilla.org/api/v1/stats/languages"
curl -sL "https://opus.nlpl.eu/opusapi/?languages=True"

# Models / G2P
curl -sL "https://raw.githubusercontent.com/openai/whisper/main/whisper/tokenizer.py"
curl -s  "https://api.github.com/repos/dmort27/epitran/git/trees/master?recursive=1"

# Literature
curl -s "https://export.arxiv.org/api/query?search_query=all:<term>&max_results=20"
curl -s "https://api.openalex.org/works?search=<term>&per-page=12"
curl -s "https://zenodo.org/api/records?q=<term>&size=15&type=dataset"
```

No accounts were created, no git commands were run, no large model weights or datasets were
downloaded. The largest files fetched were the CLDF `forms.csv` files (≤ 2.6 MB), the MMS
coverage HTML (1.07 MB), and two PDFs (0.3 MB and 4.5 MB). Two bot challenges / dead ends are
recorded as blocks (N21–N25), not retried in loops.
