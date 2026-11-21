# Lane 02 — Academic literature (theses, grammars, articles, wordlists)

Survey date: **2026-10-18**. Target: Marúbo (`mzr`, Glottolog `maru1252`), Panoan, Javari Basin.
Scope: theses/dissertations, grammars, dictionaries, IGT-bearing articles, wordlists, transcribed
narratives in Portuguese/Spanish/English, Brazilian + Peruvian/Bolivian repositories, journals,
and a Panoanist author sweep.

Status key: **[V]** file fetched and content inspected · **[W]** bibliographic record verified but
full text not retrievable in this environment (paywall/captcha/closed) · **[U]** seen only in a
secondary citation, no record or file confirmed.

---

## 0. Method: what actually worked

`web_search` is broken as the preflight states. The following routes were exercised and their
results are recorded in §4 (negatives) so the next lane does not repeat dead work:

| Route | Result on 2026-10-18 |
|---|---|
| `html.duckduckgo.com/html/?q=` | HTTP **202**, empty result shell (bot challenge) — unusable |
| `lite.duckduckgo.com/lite/` (GET and POST) | HTTP **202**, challenge page — unusable |
| `bing.com/search` | HTTP 200 but returns unrelated junk results (localised bot page) — unusable |
| `mojeek.com/search` | HTTP **403** "network appears to be sending automated queries" |
| `search.scielo.org` | HTTP **403** |
| `core.ac.uk/search` | Cloudflare "Just a moment…" **403** |
| `www.sil.org/...` | Cloudflare **403** for every path; **Wayback Machine worked** for both landing page and PDF |
| `digitalcommons.trinity.edu/...pdf` | **403** on direct PDF; **Wayback Machine worked** |
| `periodicos.unb.br` (RBLA, Anuário Antropológico) | TCP-level failure (**000**, DNS/connection) from this host |
| `repositorio.ufmt.br`, `repositorio.ufac.br`, `riu.ufam.edu.br`, `repositorio.umsa.bo`, `cybertesis.unmsm.edu.pe`, `repositorio.museunacional.ufrj.br` | connection failure (**000**) |
| `repositorio.minedu.gob.pe` | Check Point "Security Verification" interstitial |
| `lume.ufrgs.br/discover` | captcha redirect |
| `twu.arcabc.ca` / `arcabc.ca` | "Verifying connection" captcha challenge |
| `api.semanticscholar.org` | HTTP **429** on every call |

**Routes that did work** (use these): OpenAlex `/works`, `/authors`, `/sources` · Crossref REST
(incl. per-journal ISSN queries and DOI lookup) · DataCite · DOAJ article API · OpenAIRE
`/search/publications` (aggregates BDTD, LA Referencia, Peruvian repos) · **BDTD VuFind JSON API**
(`bdtd.ibict.br/vufind/api/v1/search?lookfor=…&type=All|Title`) · DSpace 7 REST
(`/server/api/discover/search/objects`) at UFRJ Pantheon, UFPA, PUCP, UNIA · DSpace 6
`simple-search` at UnB/UFPE · Tede UFAM · OJS article pages (`citation_pdf_url` meta tag) ·
`archive.org/wayback/available` + `web.archive.org/web/<ts>if_/<url>` for Cloudflare-blocked PDFs.

Known-list discipline: the 12 records in `docs/languages/mzr_sources_index.json` were treated as
already-held. Nothing below duplicates them; where a known work reappears (Costa 1992/2000, Costa
2017, Cesarino 2013) it is only mentioned as a cross-reference.

---

## 1. Ranked finds (by likely dataset value)

Ranking rule: does the item contain **actual Marúbo forms** (not just analysis), how many, is it
**retrievable today**, and is it **alignable** (gloss column, translation column, or paradigm)?

| # | Slug | Citation (as published) | URL(s) | Contents & volume | Formats | License (verbatim where found) | Access | Task fit | Trust note | St |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `sil_javari_survey_2010` | Anonby, Stan & Holbrook, David J. 2010. *A Survey of the Languages of the Javari River Valley, Brazil*. SIL Electronic Survey Reports 2010-003. | landing `https://www.sil.org/resources/archives/9091`; PDF `https://www.sil.org/system/files/reapdata/27/57/69/27576908494999060439122454062068171710/silesr2010_003.pdf`; **working copy** `http://web.archive.org/web/20240529162058if_/https://www.sil.org/system/files/reapdata/27/57/69/27576908494999060439122454062068171710/silesr2010_003.pdf` | 45 pp.; §5.2 wordlists + **Appendix 1 "Comparative Vocabulary": 345 Swadesh–Rowe items × 5 columns (Portuguese, English, Matís, Kulina Pano, Marúbo, Matsés)**; plus a per-language annotated bibliography (Marúbo section) | PDF (born-digital, 1.4) | No licence statement on the report or the SIL record page ("© SIL International" only); SIL survey reports are distributed free of charge | Free, no login (sil.org itself Cloudflare-403 to this host; Wayback served the identical file) | Marúbo↔English lexicon, 345 concepts, clean concept alignment via the English column | Forms are typed in a **legacy SIL phonetic font**: extraction yields mojibake (`a`na`, `` `‹kƒa ``, `b‹`ru`). Needs OCR/vision pass or font-mapping, not naive `pdftotext`. Marúbo column is the 4th of 5. | **V** |
| 2 | `villada_2016_ufsc` | Villada Castro, Carolina. 2016. *O proliferar dos outros: tradução e xamanismo*. Dissertação (mestrado), Programa de Pós-Graduação em Estudos da Tradução, UFSC. | handle `https://repositorio.ufsc.br/xmlui/handle/123456789/175904`; PDF `https://repositorio.ufsc.br/bitstream/123456789/175904/1/345641.pdf` | 176 PDF pp. (catalogue record: 175 p.); multiple shamanic chants presented in **three aligned columns: "Versão em Marubo" / "Versão em português" / "Versão en español"** (e.g. *Vo Shono Romeya / Yove kaya apaí / Awẽ mimẽaitõ…*), plus translator's notes on individual terms (*yove*, *anõ yovea*) | PDF (1.5 MB), digitised text layer | No licence statement in the PDF or on the UFSC record (no CC badge; UFSC default "all rights reserved", author retains rights) | Open, "Acesso aberto" | **Best parallel Marúbo↔PT↔ES source found in this lane**; line-level alignment is already in the layout | Chants are **ritual register** (`ritual_restricted` candidate): Cesarino's editions of Marúbo *saiti* chants. Requires register review before any export; source is a secondary translation (indirect, via Cesarino's PT), so the Marúbo column is copied from the published edition — lineage must point at Cesarino 2011/2013, not at Villada alone. | **V** |
| 3 | `fleck_2007_kulinas_marubos` | Fleck, David W. 2007. "Did the Kulinas become the Marubos? A Linguistic and Ethnohistorical Investigation." *Tipití: Journal of the Society for the Anthropology of Lowland South America* 5(2). DOI 10.70845/2572-3626.1042. | DOI `https://doi.org/10.70845/2572-3626.1042`; landing `https://digitalcommons.trinity.edu/tipiti/vol5/iss2/2/`; **working PDF** `http://web.archive.org/web/20250329050243if_/https://digitalcommons.trinity.edu/cgi/viewcontent.cgi?article=1042&context=tipiti` | 72 pp.; Table 1 (Panoan classification), Table 2 (lexical-similarity matrix over 16 Panoan varieties, 137–192 Swadesh comparisons), and **Appendix 1, pp. 197–206: "Lexical comparison of Spix's list with Kulina of the Curuçá River and Modern Marubo"** | PDF (1.27 MB) | Crossref/OALex record: **CC BY-NC-SA** for the journal (Tipití is diamond OA, `is_oa: true`, licence `cc-by-nc-sa`) | Free; the DigitalCommons PDF endpoint 403s to scripted clients, Wayback copy is byte-identical and served fine | Comparative Marúbo wordlist with 1817 Spix attestations → diachronic lexicon; also the authoritative statement that "Marubo" names two distinct Panoan languages | **Appendix pages are image-only** (each table page carries a handful of ~423×80 px images and no text layer — verified with `pdfimages -list`). OCR required. Do not assume the Marúbo column can be scraped. | **V** |
| 4 | `jaques_2021_ufam` | Jaques, Maria Perpétua Socorro Freitas. 2021. *Características estruturais do português marúbo: uma análise a partir de construções em textos escritos*. Dissertação (mestrado), PPGL, Universidade Federal do Amazonas. Advisor: Sanderson Castro Soares de Oliveira. | BDTD record `https://bdtd.ibict.br/vufind/Record/UFAM_f4d1ff207e7e6b0815df6b399d9d9491`; handle `https://tede.ufam.edu.br/handle/tede/8765`; PDF `https://tede.ufam.edu.br/bitstream/tede/8765/6/Disserta%c3%a7%c3%a3o_MariaJaques_PPGL.pdf` | 297 pp.; Ch. 4 surveys Marúbo-language research; contains phonemic/glossed Marúbo examples (*/kamã/* [kamã] 'onça', */kamãn/* 'da onça', */nõti/* 'canoa', */iki/* 'fazer', */papa oa/* 'meu pai chegou', negated-ergative examples) | PDF (4.3 MB), searchable text layer | Repository: **"Acesso Aberto"**; no CC licence stated → author holds copyright | Open | Marúbo phonology/lexicon fragments + Portuguese-interference data; useful for lexicon and for the *português marúbo* contact variety | Written by a Marúbo-area teacher-researcher; the Marúbo forms are quoted mostly from Costa (1992/2000), so this is a **secondary** attestation — lineage must be to Costa, and Jaques's own contribution is the Portuguese-contact data. | **V** |
| 5 | `pedrosa_2024_banco_dados` | Pedrosa, Judith Ferreira & Oliveira, Sanderson Castro Soares de. 2024. "Banco de Dados da Língua Marubo." *Anais do XXXII Congresso de Iniciação Científica (CONIC)*, UFAM. DOI 10.29327/xxxii-congresso-de-iniciacao-cientifica-380957.768609. | DOI `https://doi.org/10.29327/xxxii-congresso-de-iniciacao-cientifica-380957.768609`; PDF `https://static.even3.com/formulario-inscricao/ResumoExpandido-CONICPIB-LLA-0085-2022-BancodeDadosdaLnguaMarubo.33ccd29adc1b42289b17.pdf` | 4 pp.; reports a **13,382-entry Marúbo lexicon** built in FieldWorks (FLEX) from a 117-page word-list book; one FLEX screenshot (Fig. 1) | PDF (4.5 MB) | No licence stated (conference abstract) | Free | Not itself a dataset, but the **single most important pointer found**: names an existing 13k-entry Marúbo lexical database and its paper source | The FLEX database is *not* online. The paper names its source as *Vana nía anosh tanati Askai awe iki inã anosho tanaa* (117 pp., **no author identified**) — that book is the real lexicon target and is a separate, unresolved lead (see §3). | **V** |
| 6 | `costa_2003_coda_nasal` | Costa, Raquel & Dorigo, Carmen. 2013 [issue dated 2003]. "A coda nasal em Marubo e Matsés (Pano)." *Letras de Hoje* 38(4). | article `https://revistaseletronicas.pucrs.br/fale/article/view/14004`; PDF `https://revistaseletronicas.pucrs.br/fale/article/download/14004/9274` | 9 pp.; Marúbo vs Matsés nasal-coda phonology, minimal pairs | PDF — **scanned images only, no text layer** (9 pp., `pdfimages` shows one full-page JPEG per page) | **CC BY 4.0** — "Este trabalho está licenciado sob uma licença Creative Commons Attribution 4.0 International License." | Open | Marúbo phonology evidence, minimal pairs; useful for phonotactics/lexicon validation | This is the **only explicitly CC-BY Marúbo linguistics article** found in this lane, which materially updates the preflight's "no open (CC-BY) Marúbo grammar or dictionary" negative: there is now one openly-licensed Marúbo data article. OCR required for any text extraction. | **V** |
| 7 | `valenzuela_oliveira_2022_liames` | Valenzuela, Pilar M. & Oliveira, Sanderson Castro Soares de. 2022. "Graus de afastamento temporal em Pano: contribuição para os estudos translinguísticos do tempo." *LIAMES* 22: e022003, 1–44. | DOI `https://doi.org/10.20396/liames.v22i00.8668622`; PDF `https://periodicos.sbu.unicamp.br/ojs/index.php/liames/article/download/8668622/30058` | 44 pp.; **§3.3.5 "Marubo (Marubo-Katukina Sub-Branch)"** enumerates five overt graded-tense markers (*-katsai* / *-katsa*, *-ai*), with glossed sentences and the split-ergativity/negation interaction (quoting Costa 1998: 76–80) | PDF | **CC BY-NC 4.0** ("https://creativecommons.org/licenses/by-nc/4.0", © Pilar Valenzuela, Sanderson Castro Soares de Oliveira) | Open | Small but genuine Marúbo paradigm data (TAM markers) with the Panoan comparative frame that lets you keep analysis separate from observation | Forms are attributed to Costa 1998 (not located — see §3); treat the Marúbo examples as secondary citations. Non-commercial licence: fine for local LKB, blocks commercial redistribution. | **V** |
| 8 | `cesarino_2018_wenia` | Cesarino, Pedro de Niemeyer. 2018. "Wenía: o surgimento dos antepassados – Leitura e tradução de um canto narrativo ameríndio (Marubo, Amazônia Ocidental)." *Estudos de Literatura Brasileira Contemporânea* 53: 45–99. DOI 10.1590/2316-4018533. | DOI `https://doi.org/10.1590/2316-4018533`; PDF `http://www.scielo.br/pdf/elbc/n53/2316-4018-elbc-53-45.pdf` | 55 pp.; long analytical essay + **"Tradução"** section (the *Wenía* narrative chant in Portuguese) with Marúbo terms glossed in running text (*yove-a* 'espírito-verbalizador', *nawavo* 'povos', *noa taeri* 'pé do grande rio', *mai vená*) | PDF (born-digital, text layer) | SciELO/OJS record: open access; journal is CC BY (no explicit licence line on the PDF itself) | Open | Running narrative text (PT) + terminological lexicon; not line-aligned to Marúbo | Translation only — **no facing Marúbo text**, so it cannot be used for parallel alignment; it can ground lexicon and narrative structure. Ritual/narrative register. | **V** |
| 9 | `gontijo_flores_2019_walkietalkie` | Gontijo Flores, Guilherme. 2019. "Um Walkie-Talkie na encruzilhada das águas: traduzir e cantar a Poesia Xamânica Marubo." *Cadernos de Tradução* 39 (special issue): 171–. DOI 10.5007/2175-7968.2019v39nespp171. | DOI `https://doi.org/10.5007/2175-7968.2019v39nespp171`; PDF `https://periodicos.ufsc.br/index.php/traducao/article/download/2175-7968.2019v39nespp171/42145` | 56 pp.; translator's essay on singing two Marúbo shamanic chants, **with the Marúbo lines reproduced against the Portuguese** (*yove mawa chinãyai*, *yove kenemataki*, *machit awainiai*, *noa mawa vana*), plus an English abstract | PDF (text layer) | "Copyright (c) 2019 Cadernos de Tradução"; journal publishes under CC BY 4.0 (no explicit licence line on the PDF) | Open | Chant-level Marúbo↔PT, small volume (two chants), performative translation | Same ritual-register caution as Villada; derive lineage from Cesarino's editions. | **V** |
| 10 | `smith_2021_twu_switch_reference` | Smith, C. Sean. 2021. *Aspects of switch reference in Marubo, a Panoan language of Western Amazonia*. Thesis (M.A.), Trinity Western University, Langley, BC. | `https://twu.arcabc.ca/islandora/object/twu:778` (also `https://arcabc.ca/islandora/object/twu:778`) | Unknown extent; a **Marúbo-dedicated grammatical study** (switch-reference), i.e. the closest thing to a Marúbo grammar sketch found in this lane | PDF (presumed; not retrievable here) | Not verifiable — no licence visible behind the challenge page | Repository requires passing a "Verifying connection" captcha; **blocked from this environment** | Potentially the highest-value *grammatical* source in this lane — requires a human browser | Existence corroborated by two independent citations: Valenzuela & Oliveira (2022) reference list gives author, title, degree, institution, year and this handle; Pedrosa (2024, p. 1) cites "Smith (2021, p. 3)" for Marúbo speaker population. Identified as M.A. (LIAMES prints "M.D. dissertation"). | **W** |
| 11 | `fleck_2022_body_part_marubo` | Fleck, David W. 2022. "Vestiges of body-part prefixation in Marubo." In Zariquiey & Valenzuela (eds.), *The Grammar of Body-Part Expressions*, pp. 401–424. Oxford University Press. DOI 10.1093/oso/9780198852476.003.0015. | DOI `https://doi.org/10.1093/oso/9780198852476.003.0015` | 24 pp.; Marúbo body-part prefix morphology with reconstructed Panoan comparanda | PDF/HTML behind OUP paywall | Closed (`is_oa: false`, no licence in Crossref) | **Paywalled** | High-value morphology (prefix allomorphy) if a copy can be lawfully obtained | Only a Marúbo-dedicated chapter by the leading Panoanist; no OA copy located. Metadata verified via Crossref (pages 401–424, OUP). | **W** |
| 12 | `smith_2024_onomatopoeia_marubo` | Smith, C. Sean. 2024. "87 Marubo." In *Onomatopoeia in the World's Languages*. De Gruyter. DOI 10.1515/9783111053226-087. | DOI `https://doi.org/10.1515/9783111053226-087` | One language chapter in a cross-linguistic handbook; ideophones/onomatopoeia, presumably with a Marúbo form list | PDF/HTML (De Gruyter) | Closed (`oa_status: closed`, no licence) | **Paywalled** | Would supply an ideophone sub-lexicon (a class usually missing from grammars) | Existence + authorship verified via Crossref/OpenAlex. Same author as item 10, so a human chasing one can ask for both. | **W** |
| 13 | `ruedas_2002_ijal` | Ruedas, Javier. 2002. "Marubo Discourse Genres and Domains of Influence: Language and Politics in an Indigenous Amazonian Village." *International Journal of American Linguistics*. DOI 10.1086/466501. | DOI `https://doi.org/10.1086/466501` | Article; Marúbo discourse genres and language politics | PDF behind UChicago Press | Closed / paywalled (`is_oa: false`) | **403 to this environment**, paywalled | Sociolinguistic framing of Marúbo genres; may quote short Marúbo text | Only IJAL item on Marúbo found. Metadata (author/title/journal) verified in Crossref + OpenAlex; landing page returns 403Univ. of Chicago bot/paywall. | **W** |
| 14 | `boarin_2024_ufrgs` | Boarin, Fernanda Vivacqua de Souza Galvão. 2024. *Cantos do cipó: poesia, ayahuasca e agência*. Tese (doutorado), UFRGS. | handle `http://hdl.handle.net/10183/280707`; PDF `http://www.lume.ufrgs.br/bitstream/10183/280707/1/001213452.pdf`; BDTD record `https://bdtd.ibict.br/vufind/Record/UFRGS-2_a6d0f381eb15768b3c707c96780d72e1` | Thesis on Cesarino's Marúbo chant translations alongside Santo Daime hymns; quotes chants | PDF | Not stated (LUME default) | Open record; LUME `/discover` is captcha-gated, bitstream path likely open — **unverified** | Mostly literary-critical; low marginal data | Analysis-of-translation, not primary attestation. | **W** |
| 15 | `davila_ufam_kulina_pano` | D'Avila, Janekely Reis. (n.d.). *Os Kulina-Pano do Vale do Javari: histórias, memórias e atuação política*. Dissertação, UFAM. | BDTD record `https://bdtd.ibict.br/vufind/Record/UFAM_39ee918e3e6486a3e82e1b018b55f096` | History/politics of the Kulina-Pano (the group Fleck 2007 links to Marúbo) | PDF (UFAM) | Not stated | Open record | **Related-language only** — may contain a few lexical items | Do **not** treat as Marúbo evidence (invariant 8). | **W** |
| 16 | `oliveira_unb_korubo` | Oliveira, Sanderson Castro Soares de. 2009?. *Preliminares sobre a fonética e a fonologia da língua falada pelo primeiro grupo de índios Korúbo recém-contactados*. Dissertação, UnB. | BDTD `https://bdtd.ibict.br/vufind/Record/UNB_9f0219d5de2eef7a1574d0d3ed3e3aad`; UnB `https://repositorio.unb.br/simple-search?query=marubo` | Korubo (Panoan) phonetics/phonology | PDF | Not stated | Open | Related-language (Korubo `xor`) | Hypotheses only. Author is the Marúbo-database supervisor (item 5), so useful for contact. | **W** |
| 17 | `mayuruna_usp_matses` | Mayuruna, Jaime da Silva. (n.d.). *Tantiabenash Shubinunna: aprenda para chorar*. Dissertação, USP. | BDTD `https://bdtd.ibict.br/vufind/Record/USP_9980afa180c62cddcb1e16036b20a442` | Matsés-authored text/thesis | PDF | Not stated | Open | Related-language (Matsés `mcf`), indigenous-authored running text | Hypotheses only. | **W** |
| 18 | `josileno_marubo_2026_fiocruz` | Marubo, Josileno Estevão. 2026. *Itinerários terapêuticos do povo Marubo do Vale do Javari, Atalaia do Norte, Amazonas*. Dissertação, Fiocruz. | `https://arca.fiocruz.br/handle/icict/77116` | Marúbo-authored health ethnography | PDF | Not stated | Open | Marúbo-authored Portuguese text; may carry plant/illness terminology in Marúbo | Marúbo authorship is itself valuable for register/authority metadata. | **W** |

### 1a. Items that are analysis-only (no usable Marúbo forms) — listed so no one re-hunts them

Cesarino 2008 (*Novos Estudos CEBRAP*), 2010 (*Revista de Antropologia*), 2011 (*JSA*, French), 2011
(*Images Re-vues*), 2012 (*Revista de Antropologia*), 2012 (*Estudos Avançados*, "Os relatos do
Caminho-Morte" — PT translations of Death-Path narratives), 2013 (*Mana*), 2022 (Berghahn chapter),
2023 (*JRAI*), 2023 (*Res*); Melatti 1977/1984/2002/2018 (*Anuário Antropológico*, *Mana*);
Melatti 1986 (*Revista do Museu Paulista*), 1989 (*Receitas da culinária marubo*); Ruedas 2004/2013
(*Tipití*, *Revista Española de Antropología Americana*); Werlang 2008 (*Revista USP*); Lima 1994
(*Cadernos de Campo*); Santos & Sawada 2015 (*Somanlu*); Boarin 2021 (*eLyra*); Villada Castro 2018
(*Mundo Amazónico*, ES/EN twin of item 2); Reis et al. 2026 (*Cadernos Cajuína*, Marúbo/Kanamari
graphic geometry). These give ethnography, poetics and a handful of quoted terms; they are **not**
text-bearing corpora.

---

## 2. Top-3 by dataset value

1. **`sil_javari_survey_2010`** — 345 Marúbo lexical items with an English concept column, free,
   born-digital, and already aligned by concept. It is the only *large* Marúbo wordlist that is
   retrievable today without a human, and its English column makes it directly ingestible into the
   existing Marúbo lexicon view. Caveat: legacy SIL font (needs OCR/vision, not `pdftotext`).
2. **`villada_2016_ufsc`** — the only source found where **Marúbo chants sit in a three-column
   layout with Portuguese and Spanish translations**. Even a modest chant count gives sentence-level
   parallel data in a register (ritual chant) that no other held source covers, and the Marúbo column
   is separable mechanically because the columns are literally adjacent blocks.
3. **`pedrosa_2024_banco_dados`** — not usable as data itself, but it is the highest-leverage
   *pointer*: it proves a 13,382-entry FLEX Marúbo database exists at UFAM (LCA group) and names the
   117-page word-list book it was built from. One email to Sanderson Oliveira potentially converts
   this lane from 345 items to 13k items.

Runner-up worth a human's five minutes: **`smith_2021_twu_switch_reference`** — a Marúbo-dedicated
thesis behind a captcha. It is the most likely single file to contain a real grammatical sketch
(paradigms + IGT) that the project does not yet have.

---

## 3. Unresolved bibliographic leads (do not treat as held)

| Lead | Why it matters | Status / method |
|---|---|---|
| *Vana nía anosh tanati Askai awe iki inã anosho tanaa* (117 pp., no author) | The **paper source of the 13,382-entry lexicon**; a Marúbo word-list book in the Marúbo language | **U** — cited only in `pedrosa_2024_banco_dados` (p. 3, "sem autoria reconhecida", "não há dados com relação à pessoa que elencou os dados lexicais"). No copy, record, or library hit located. Likely an SIL/MNTB or FUNAI literacy product. Search offline library catalogues (UFAM, MPEG, Museu do Índio). |
| Costa, Raquel G. R. 2000. "Case marking in Marubo (Panoan): a diachronic approach." *Santa Barbara Papers in Linguistics* 10 (Proc. WAIL 3). | A **separate Marúbo paper by the main Marúbo linguist**, not in the repo's known list | **W** — corroborated twice: ISA's Marúbo bibliography page (`https://pib.socioambiental.org/pt/Povo:Marubo`, "Fontes de informação") and the UCSB SBLP index (archived: `http://web.archive.org/web/20250806024622/https://linguistics.ucsb.edu/research/santa-barbara-papers`, which lists "…Marubo (Panoan): a diachronic approach." under Volume 10 (2000)). Per-article PDF not located; `papers/10/costa_vol10.pdf` guesses 404. Try Wayback of `…/research/papers/10/` and UCSB eScholarship. |
| Costa 1998 (cited as "Costa 1998: 76–80, 1974") | Marúbo TAM + ergativity-split analysis with page-level citations to glossed examples — likely a full paper with IGT | **U** — appears only as an in-text citation in `valenzuela_oliveira_2022_liames` (lines quoted: *-katsai/-katsa* future, *-ai* 'present/immediate past', "‘I will not throw the bowl.’ (Costa 1998: 80)"). Not identified among her 4 OpenAlex-indexed works. Possibly her 1998 UFRI-internal or WAIL paper. Ask the family/author or check BDTD for a 1998 record. |
| Erikson, Philippe et al. 1994. *Kirinkobaon kirika ("Gringos' Books"): an annotated Panoan bibliography*. *Amerindia* 19, suppl., 152 pp. | A ready-made **annotated bibliography of Panoan sources** — a discovery instrument for exactly this lane | **U** — cited in ISA's Marúbo bibliography. Amerindia is indexed in OpenAlex (source `S4387283302`, 42 works) but this supplement is not among them. Try CELIA/CNRS and the Wayback of `celia.cnrs.fr`. |
| Melatti, Júlio Cezar. 1986. *Wenía: a origem mitológica da cultura Marubo*. Brasília: UnB, 101 pp. (Série Antropologia 48). | Earliest PT publication of the *Wenía* myth — an independent translation to cross-check Cesarino 2018 | **U** — ISA bibliography only. UnB's Série Antropologia is on `repositorio.unb.br`; the ISSN-less series is poorly indexed (BDTD Marubo search returns 3 items, none this). |

---

## 4. Negatives — with method (2026-10-18)

| Target | Method | Result |
|---|---|---|
| **BDTD/IBICT** | VuFind JSON API, `lookfor=marubo/marúbo` (All) and `type=Title` | 15 records (All) / **3 records titled Marubo**: Costa 1992, Costa 2000 (both already held) + **Jaques 2021 (new)**. `type=Title&lookfor=panoan` → **0**. `lookfor=marupa`, `javari` (51) contain no further Marúbo-language work. |
| **UFRJ Pantheon** | DSpace 7 REST `/server/api/discover/search/objects?query=…` | `marubo` → **3** records: the two Costa theses (held) + an unrelated Magüta ethnobotany thesis. No new Marúbo item. |
| **USP** | `repositorio.usp.br/result?search=marubo` → **404**; `teses.usp.br` guessed paths → 404; covered indirectly via BDTD (`lookfor=marubo` returns USP items: Mendes Jr. mitochondrial DNA; Mayuruna Matsés) and OpenAlex | No Marúbo linguistic thesis at USP. USP's *Revista de Antropologia* Marúbo items are all analysis-only (§1a), except Nelly Duarte 2017 "Minha vida como estudante no mundo dos brancos" (Marúbo-authored PT testimony, DOI 10.11606/2179-0892.ra.2017.132066) which contains no Marúbo forms. |
| **UNICAMP** | `repositorio.unicamp.br/Busca/Consulta?busca=marubo` → 404; `/api/search` → connection failure (000) | Not searchable from here. Indirect: OpenAlex shows UNICAMP Panoan theses (Ferreira 2001 *Língua Matís*, Cândido 2004 *Shanenawa*) — sister languages, no Marúbo. |
| **UnB** | `repositorio.unb.br/simple-search?query=marubo` | 18 hits, led by Oliveira's Korubo MA (related language, item 16); no Marúbo-language thesis. `periodicos.unb.br` (RBLA, Anuário Antropológico) unreachable at TCP level, so UnB *journals* were searched via DOAJ/Crossref/OpenAlex instead, which surfaced the Marúbo items in §1a only. |
| **UFAM** | `riu.ufam.edu.br` → 000; **`tede.ufam.edu.br` works** | Found **Jaques 2021** (item 4). D'Avila (Kulina-Pano) is the only other Javari-language thesis. |
| **UFPA** | DSpace 7 REST | `marubo` → 1 (an unrelated theatre thesis). `pano` → 0 relevant. |
| **UFAC / UFMT / UFRGS (LUME) / UFPE / Museu Nacional / Museu Goeldi (MPEG)** | direct probes | UFAC, UFMT, Museu Nacional: connection failure (000). LUME: captcha redirect on `/discover` (but bitstream URLs appear open — see item 14). UFPE `simple-search?query=marubo`: 12 hits, all Matsés/Kulina ethnography or unrelated. MPEG `repositorio.museu-goeldi.br/simple-search` → 404 (DSpace shell); not searched further. |
| **LIAMES (UnB)** | OJS `search/search?query=marubo` and `searchPhrase=Pano` | Marúbo: **"Nenhum resultado encontrado"**. Pano (via OpenAlex source filter `S4210229850`): **15 Panoan articles, none on Marúbo** — Matsés, Matis, Kashinawa, Amahuaca, Kakataibo, Shipibo, Iskonawa, plus Valenzuela & Oliveira 2022 (item 7). So LIAMES has no Marúbo article, but is the best single venue for Panoan IGT (sister-language hypotheses). |
| **Revista Brasileira de Linguística Antropológica (RBLA)** | `periodicos.unb.br/index.php/ling` — connection failure (000); Crossref `journals/2177-7160` → 0 (wrong ISSN guess); no RBLA source in OpenAlex | **Unresolved** — journal not queryable from this host. Note: RBLA published the *other* Costa 2017 DOI (10.5380/rabl.v1i1.52702), which the repo already holds. |
| **Cadernos de Etnolinguística** | no OpenAlex source match; `etnolinguistica.org/busca?q=marubo` → 404 (Wikidot site; search path differs) | Not enumerated. The Biblioteca Digital Curt Nimuendajú is already in the registry; its Marúbo holdings should be enumerated by lane 01/03 via its Wikidot page list, not here. |
| **DELTA, Revista Linguíʃtica, Working Papers em Linguística** | OpenAlex `/sources?search=` | No matching source resolved (no ISSN hit for DELTA's exact title, Revista Linguíʃtica, or Working Papers em Linguística) → **not searched**, recorded rather than guessed. |
| **MOARA** | OpenAlex source `S4210187144`, 654 works, title-filtered for pano/marúbo/indígena | **0** Marúbo or Panoan-linguistic items. |
| **Amerindia** | OpenAlex source `S4387283302`, 42 works | **0** Panoan-Marúbo items (the only Amazonian hit is Bertet 2021 on Tikuna tonogenesis). Note Amerindia 19 (1994) is the Erikson Panoan bibliography — not indexed (§3). |
| **PUCP (Peru)** | DSpace 7 REST, `marubo` and `pano` | `marubo` → 4, all non-linguistic (Fleck 2012 body-part talk; Dunu Maya 2022 isolated peoples; Rodríguez Alzza 2022 Iskonawa COVID memories; ILV 1971 *Informe general*). `pano` → 20, all sister-language (Iskonawa, Amahuaca, Kakataibo, Shipibo, Purús dialects). **No Marúbo-text item.** |
| **UNMSM Cybertesis** | `https://cybertesis.unmsm.edu.pe/` | connection failure (**000**) — unreachable. |
| **UNIA** | `api-repositorio.unia.edu.pe/server/api/discover/search/objects` | `marubo` → **0**; `pano` → 1 unrelated fisheries thesis. No Marúbo. |
| **MINEDU (Peru)** | `repositorio.minedu.gob.pe` | Check Point "Security Verification" interstitial — **blocked** (matches the preflight's earlier MINEDU negative, now via a *different* method: direct repository, not snippet). |
| **SIL Peru / SIL Brazil publications** | `www.sil.org/resources/...` | Cloudflare 403 on every path, including search. **Worked around via Wayback** — which is how item 1 was obtained. Do not conclude "SIL has nothing"; conclude "sil.org needs Wayback or a browser". |
| **Bolivia (UMSA/UCB)** | `repositorio.umsa.bo` | connection failure (**000**). No Bolivian Marúbo material is expected (Marúbo is a Brazilian Javari group), so this is a low-cost negative. |
| **Semantic Scholar** | `/graph/v1/paper/search` ×3 | HTTP **429** every time — route unusable without a key. |
| **SciELO search** | `search.scielo.org` | **403**. SciELO items were nevertheless reached per-DOI (`scielo.br/j/.../pdf`), which worked. |
| **Panoanist author sweep** | OpenAlex `/authors?search=` + `/works?filter=author.id:` | Barros (Maria Cândida Drumond Mendes, 29 works): **no Marúbo/Panoan-language item** (missionary linguistics, Tupi, *língua geral*). Troncarelli (5 works): **none**. Zoraide Amarante Ribeiro, Agnes Balykova: **no OpenAlex author record** (Ribeiro appears only as co-author on the Pano-Takana quantitative-method LIAMES paper, 2012, already reachable via item 7's venue). Fleck/Valenzuela/Zariquiey/Cesarino/Costa enumerated via author IDs; their Marúbo-relevant output is items 3, 6, 7, 8, 11 and the analysis-only list. |

---

## 5. The five PDFs a human should download first

1. `https://www.sil.org/system/files/reapdata/27/57/69/27576908494999060439122454062068171710/silesr2010_003.pdf`
   — Anonby & Holbrook 2010, SIL Javari survey (345-item Marúbo wordlist, Appendix 1). Use
   <http://web.archive.org/web/20240529162058if_/> + the same path if sil.org 403s.
2. `https://repositorio.ufsc.br/bitstream/123456789/175904/1/345641.pdf`
   — Villada Castro 2016, UFSC (triple-aligned Marúbo/PT/ES chants).
3. `http://web.archive.org/web/20250329050243if_/https://digitalcommons.trinity.edu/cgi/viewcontent.cgi?article=1042&context=tipiti`
   — Fleck 2007, *Tipití* (Appendix 1: Spix vs Kulina-of-Curuçá vs Modern Marúbo, image-only).
4. `https://tede.ufam.edu.br/bitstream/tede/8765/6/Disserta%c3%a7%c3%a3o_MariaJaques_PPGL.pdf`
   — Jaques 2021, UFAM (open access; Marúbo examples + Portuguese-contact corpus).
5. `https://twu.arcabc.ca/islandora/object/twu:778`
   — Smith 2021, Trinity Western MA on Marúbo switch-reference (**captcha — needs a real browser**;
   this is the one item in this lane that most plausibly contains a Marúbo grammatical sketch).

Honourable sixth, if sil.org is reachable in a browser: the FLEX database behind
`pedrosa_2024_banco_dados` is **not** downloadable — it needs a human request to
Sanderson Castro Soares de Oliveira (UFAM, `sanderson@ufam.edu.br`, per the CONIC abstract).

---

## 6. Handoff cautions

- **Do not** treat Villada (item 2) or Gontijo Flores (item 9) as independent attestations of the
  Marúbo chant lines: both translate *from Cesarino's Portuguese editions*. Lineage must terminate
  at Cesarino 2011/2013; register is shamanic (`ritual_restricted` candidate) and needs the review
  the preflight requires.
- **Do not** run `pdftotext` on item 1, 3 or 6 and trust the output — legacy SIL font (1), image-only
  tables (3), scanned pages (6). All three need OCR/vision with a human spot-check.
- Item 1's Marúbo column is **4th of 5** (after English/Matís/Kulina Pano) — easy to mis-map.
- The preflight's negative "no open (CC-BY) Marúbo grammar or dictionary" is now **partly outdated**:
  `costa_2003_coda_nasal` is CC BY 4.0 and contains Marúbo data (though it is an article, not a
  grammar). Record it as a licence win, not a grammar win.
- Everything here that is a *sister-language* source (Matsés, Matís, Korubo, Kulina-Pano, Shipibo,
  Iskonawa, Kakataibo) may only create hypotheses (AGENTS.md invariant 8).
- Reproducibility note: direct `sil.org`, `digitalcommons.trinity.edu`, `core.ac.uk`,
  `search.scielo.org`, DDG and Bing were all blocked to this host on 2026-10-18; the Wayback
  Machine and the JSON APIs listed in §0 were the only reliable routes.
