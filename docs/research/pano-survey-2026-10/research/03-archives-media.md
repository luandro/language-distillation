# Lane 03 — Institutional & community archives, ethnographic media (Panoan / Marúbo)

- **Survey date:** 2026-10-18
- **Target:** Marúbo (`mzr`, Glottolog `maru1252`), Panoan, TI Vale do Javari, Amazonas, BR
- **Lane scope:** language archives, Brazilian/Amazonian institutions, international ethnographic
  collections, finding aids (field notebooks, annotated photo collections, museum object labels).
- **Companion files:** `../00-preflight.md` (contract, negatives, tooling), `../FINDINGS.md` (digest).
- **Governance frame (read this first):** per `AGENTS.md` invariant 6 / ADR-0025 a source that is
  *present in the repository* is authorized for processing; licence and register are recorded
  **metadata, not gates**. This lane therefore reports licences and rights holders verbatim as
  metadata — and *separately*, in §7, flags material whose **cultural register** (ritual chant,
  shamanic curing, third-party narrative) or **third-party deposit terms** make community
  consultation the right operational path even where a licence exists. Nothing here was
  downloaded into `var/`, no accounts were created, no access controls were bypassed.

---

## 1. Method actually used, and what it cost me

`web_search` was not used (broken per preflight §5). Everything below came from direct fetches:

| Route | Result |
|---|---|
| DuckDuckGo HTML (`html.duckduckgo.com/html/?q=`) | worked once, then returned HTTP 202 challenge pages for the rest of the session; **not usable at scale** |
| DuckDuckGo Lite (`lite.duckduckgo.com/lite/`) | HTTP 202 challenge from first call |
| Bing (`bing.com/search?q=`) | HTTP 200 but **silently ignores `site:` and quotes**, returning TikTok/retail noise for every query → discarded |
| Mojeek | HTTP 403 |
| Direct archive search/API endpoints | **the only productive route** — used for every verified finding |
| Wayback (`web.archive.org`, `archive.org/wayback/available`, CDX API) | partially usable; after ~10 calls began returning **HTTP 429 "suspected abusive bot traffic"**. Two AILLA/PARADISEC snapshots were located but the fetches were refused. Treat as degraded, not as evidence of absence |

Hard blocks encountered from this network (recorded, not retried in loops):

- `ailla.utexas.org`, `ailla.lib.utexas.edu` (incl. `/oai/request?verb=Identify`) → **Anubis
  proof-of-work wall**, page title "Oh noes!", `Access Denied: error code e90858179722cc4`.
- `catalog.paradisec.org.au` (all paths incl. `/api/v1/search`, `/languages`, `/collections`) →
  **"WAF Block – The University of Sydney"**, HTTP 403.
- `collections.si.edu`, `www.loc.gov/search/?fo=json`, `www.sil.org/resources/search`,
  `www.britishmuseum.org/collection` → Cloudflare/Incapsula interstitial (403).
- `www.sil.org/system/files/.../*.pdf` → 403 even with matching `Referer`; **record pages are
  readable, PDFs are not** from this client.
- DNS/connect failures: `acervo.museudoindio.gov.br` (NXDOMAIN), `opir.org.br` (NXDOMAIN),
  `cti.org.br` (NXDOMAIN), `www.museunacional.ufrj.br`, `www.museu-goeldi.br`,
  `www.worldoral.org`, `www.olharetnografico.com`, `imagem-movimento.org.br`;
  `prodoc.museudoindio.gov.br` resolves (177.184.13.18) but **refuses :80 and :443**.

Consequence: **the single most important archive for this lane (AILLA) could not be verified
from here.** Its status below is `[U]`, not "empty". A human with a browser must close that gap
(§8, item 1).

---

## 2. Master table — language archives (international)

Status: `[V]` = verified by fetching the record/search endpoint named in the row; `[W]` = weak,
partially verified, or verified only at metadata level; `[U]` = unverified/blocked. Date = 2026-10-18 for all rows.

| Slug | Name + URLs | Contents & volume | Formats | Licence | Access | Task fit | Trust note | St | Date |
|---|---|---|---|---|---|---|---|---|---|
| `elar_marubo_title_items` | Endangered Languages Archive (ELAR/ELDP) — <https://www.elararchive.org/?s=marubo>; deposit <https://www.elararchive.org/index.php?name=SO_9bc2e901-f5ee-47ec-b418-2ce95ee4131c> | **Zero Marúbo-language deposits.** 2 folder records *titled* after Marúbo, nested in the **Matsés/Kulina Pano** deposit `mayoruna-fleck-0111` (David W. Fleck, U. Oregon, ELDP MDP0193, Peru–Loreto–Yaquerana). Deposit facets: Kulina 267, Matses 287, Chankueshbo 13, Mayoruna 1 | WAV + "raw" audio, EAF/annotation pairs elsewhere in deposit; folder-level metadata | Not stated at item level; ELDP deposits carry depositor-set conditions | Sessions marked `U_UserAccess` (ELAR registration + depositor approval); deposit is "Collection online" | **Negative for Marúbo speech.** The two items are Kulina Pano/Matsés speech *about* Marúbo (autobiography genre) — related-language hypothesis material only | Archive record fetched directly (item pages + collection page) | [V] | 2026-10-18 |
| `elar_panoan_inventory` | ELAR Panoan holdings — <https://www.elararchive.org/?s=cashibo> (and `?s=shipibo`, `?s=yaminawa`, `?s=amahuaca`, `?s=kakataibo`) | Panoan inventory, not Marúbo: Cashibo-Cacataibo/Kakataibo **344** items, Yaminahua **36**, Nahua **25**, Sharanahua (subset), "Panoan" 1, Kulina 267, Matsés 287; **Iskonawa = 0** | WAV, EAF, MP4, PDF, ZIP; mixed `O_OpenAccess` / `U_UserAccess` | Per deposit; not crawlable without login | Mixed | Related-Panoan hypotheses (esp. Cashibo-Cacataibo, Yaminahua, Nahua — all with ELAN annotation) | Facet counts read off search pages | [V] | 2026-10-18 |
| `mpi_tla` | The Language Archive, MPI Nijmegen (DoBeS + MPI corpora) — <https://archive.mpi.nl/tla/islandora/search/marubo> | **0** for `marubo` and `marupa`; **0** for `mayoruna`, `matses`, `shipibo`, `shipibo-konibo`, `kashinawa`, `amahuaca`, `yora`, `iskonawa`, `kakataibo`. Real Panoan: `kaxinawa` = **34** (Cashinahua/Huni Kuin, e.g. "A velha que virou tatú", "Yube xenidan", "Napu ainbu") | WAV/MPEG + ELAN/TextGrid | Per deposit (TLA terms; DoBeS deposits vary) | Mostly open after free registration | Related-language only (Cashinahua) | **False-positive warning:** TLA `matsés` = 142 hits are **Murui/Witoto** (lluakɨ, Buinaima, icaros), not Panoan. Do not record "Matsés at TLA" | [V] | 2026-10-18 |
| `ailla` | Archive of the Indigenous Languages of Latin America — <https://ailla.utexas.org/>, <https://ailla.lib.utexas.edu/> | **Unverified.** Panoan holdings are known to exist (Shipibo, Cashinahua, Matsés, Yaminawa are all standard AILLA languages); Marúbo presence **not confirmed** | Unknown from here | Per deposit; AILLA has three access tiers incl. community-restricted | Account required for most media; some public | Potentially the highest-value gap in this lane | Blocked by Anubis; Wayback snapshot of `/languages` located (2026-02-05) but fetch returned 429 | [U] | 2026-10-18 |
| `paradisec` | PARADISEC — <https://catalog.paradisec.org.au/> | **Unverified** (all catalogue routes 403 WAF). Australia/Pacific-weighted; Amazonian Panoan is a low prior | — | Per collection; some community-closed | Registration for most items | Low prior, unverified | WAF block recorded verbatim; no retry loop | [U] | 2026-10-18 |
| `cla_berkeley` | California Language Archive — <https://cla.berkeley.edu/>; search API `https://xfhpwly456.execute-api.us-east-1.amazonaws.com/api/ac?q=marubo` | **0 results** for `marubo` / `Marubo` (API returns `{"results": []}`). CLA is California + Andes weighted (its showcased non-CA collection is Matsigenka, Arawak) | — | Per collection (Berkeley terms) | Open browse; some deposits restricted | None found | Autocomplete/search API queried directly (the site's own search backend) | [V] | 2026-10-18 |
| `pangloss_lacito` | Collection Pangloss, LACITO/CNRS — <https://pangloss.cnrs.fr/corpus> | **0 Panoan** among the **299** corpora embedded in the page JSON (no marubo, matsés, shipibo, cashinahua, yaminawa, amahuaca, kakataibo, isconahua) | WAV + interlinear annotation | CC-style per corpus (Pangloss terms) | Open | None found | Full corpus array parsed, not a keyword grep of rendered text | [V] | 2026-10-18 |
| `sil_lca_javari_survey` | SIL Language & Culture Archives record 9091 — <https://www.sil.org/resources/archives/9091> | **Anonby, Stan & David J. Holbrook (2010), "A survey of the languages of the Javari River Valley, Brazil"**, *Journal of Language Survey Reports* 2010-003 (= SIL Electronic Survey Reports 2010-003), **44 pp.** Abstract states data were collected on **Kanamari [knm], Korubo [xor], Kulina Pano, Marúbo [mzr], Matís [mpq], Matsés [mcf]** | PDF `silesr2010_003.pdf`, 1.35 MB | Not stated on record; SIL "Rights and Permissions" governs | Free download link on record page; PDF returned 403 to this client | **New find.** Sociolinguistic survey with comparative wordlist material incl. Marúbo — direct lexical candidates + Javari contacts | Metadata fully verified; PDF content `[W]` (download blocked) | [V] metadata / [W] content | 2026-10-18 |
| `sil_ebook086_marubo_demonstratives` | SIL e-Books 086 (2024) record 99688 — <https://www.sil.org/resources/archives/99688> | **Nicolle, Steve (ed.) 2024, *Discourse Functions of Demonstratives*, SIL e-Books 086, viii+166 pp.** Chapter 2: **"Marubo Demonstratives: Providing Structure, Cohesion, and Referent Clarity in Discourse" — Melissa Ruth Smith** | PDF `silebook086_Functions_Nicolle.pdf`, 2.33 MB | **No licence stated on the record**; © SIL International (see SIL Rights & Permissions) | Free download link; PDF 403 to this client | **Highest-value new find.** Grammar-writing with quoted Marúbo forms and glosses → IGT/alignment candidates; also a named specialist to contact | Metadata verified incl. table of contents; PDF content `[W]` | [V] metadata / [W] content | 2026-10-18 |
| `sil_lca_texting_marubo` | SIL L&C Archives record 100815 — <https://www.sil.org/resources/archives/100815> | Eberhard, David (2022), "Who texts what to whom and when? … Four Multilingual Minoritized Language Communities", *IJSL* 276:169–205; **Marubo is one of the four communities** | Metadata only; external DOI | Journal (De Gruyter) — subscription | Record open, article paywalled | Indicates a **Marúbo texting corpus exists** (author-level lead), not directly usable | Record verified; article body not accessed | [V] metadata | 2026-10-18 |
| `dobes_mpi` | DoBeS programme outputs (via TLA, above) | No Marúbo; no Panoan beyond Cashinahua at TLA | — | — | — | None | Covered by `mpi_tla` row | [V] | 2026-10-18 |
| `wolp_cambridge` | World Oral Literature Project (Cambridge) — `worldoral.org` | **Host does not resolve** from here; WOLP collections reportedly migrated into Cambridge's repository | — | — | — | Unknown | NXDOMAIN; not equivalent to "no holdings" | [U] | 2026-10-18 |
| `lac_cologne` | "Language Archive Cologne" | No resolvable hostname found for this name (`language-archive-cologne.uni-koeln.de` NXDOMAIN) | — | — | — | Unknown | Possibly a mis-citation for TLA/MPI; flag as ambiguous target | [U] | 2026-10-18 |
| `hrelp_eldp` | HRELP / ELDP grant outputs | ELDP outputs land in ELAR (see `elar_*` rows); no Marúbo grant output found via ELAR search | — | — | — | None found | Same search method as ELAR | [V] | 2026-10-18 |

---

## 3. Master table — Brazilian / Amazonian institutions

| Slug | Name + URLs | Contents & volume | Formats | Licence | Access | Task fit | Trust note | St | Date |
|---|---|---|---|---|---|---|---|---|---|
| `museu_indio_tainacan` | **Museu Nacional dos Povos Indígenas (ex-Museu do Índio, FUNAI)** — <https://tainacan.museudoindio.gov.br/>; search <https://tainacan.museudoindio.gov.br/?s=marubo> | Ethnographic **object** repository (2 collections: id 471 "Museu do Índio"; 419797 "Participação em Exposições"). `?s=marubo` → **~8 distinct Marúbo item records**, e.g. `75-4-18` "Tubo do pajé Marubo", `2708aart/2708bart/2708cart/2708dart` "Instrumento marubo", `75-4-40`, plus woven arm/ankle bands. Fields include **`Nome étnico do item`** with Marúbo forms: `"rome rawe"` (75.4.18), `"bona tachota ya"` (2708dart) | WordPress/Tainacan REST (`/wp-json/tainacan/v2/…`, namespaces confirmed) + object photographs / "Documento" attachments (`Baixar`) | **Not stated.** Rights holder: FUNAI / Museu Nacional dos Povos Indígenas | Open web; item attachments downloadable; `Disponibilidade do objeto: Livre` | **Lexical candidates (small, high precision):** object names in Marúbo with Portuguese glosses. Also a pointer to the **Delvair Melatti (Montagner) 1975** field collection and **Artíndia 1994** | Highest-integrity Marúbo-language data I found in a Brazilian institution. Caveat: `Língua` field says only "Pano" (family), so it cannot be used as an mzr assertion | [V] | 2026-10-18 |
| `museu_indio_acervo_dead` | `acervo.museudoindio.gov.br` (the URL named in the mission) | **DNS does not resolve** — host retired; Tainacan above is the live successor | — | — | — | — | NXDOMAIN on 2026-10-18; update the registry entry | [V] | 2026-10-18 |
| `prodoclin` | PRODOCLIN — `prodoc.museudoindio.gov.br` | Host resolves but **refuses ports 80/443** (offline). PRODOCLIN resource already indexed in the repo (`prodoclin_museu_do_indio`) — this lane adds only the availability fact | — | — | — | Existing known item; **no new Marúbo PRODOCLIN product found** | Connection refused twice (http/https) | [V] dead / contents [U] | 2026-10-18 |
| `isa_pib_marubo` | Instituto Socioambiental, *Povos Indígenas no Brasil* — <https://pib.socioambiental.org/en/Povo:Marubo> (PT: `/pt/Povo:Marubo`) | Long ethnographic article signed **Julio Cezar Melatti** (UnB; originally 12/1998, last edited 2018-03-26) + full bibliography and "Sources of information". Language note: Marúbo is Pano; Erikson groups it with Katukína-Pâno, Nukiní (Rêmo), Poyanáwa, Kapanáwa (Peru) as the central branch; **"The contemporary Marubo language possesses a ritual counterpart. A parallel vocabulary exists in myths and curing chants…"** | HTML | **"All rights reserved. Express written permission from the Instituto Socioambiental is required for the reproduction of any part of this site. Reproduction of photos and illustrations is prohibited."** | Open to read | **Finding aid + register warning**, not data. Zero Marúbo-language text | Do **not** treat as evidence of Marúbo forms; it *is* the best free statement of the ritual-register problem | [V] | 2026-10-18 |
| `isa_cpce_films` | ISA bibliography (same page) — CPCE film list | **5 ethnographic videos about Marúbo, 1991–1995, Betacam/HI-8**: *Marubo: uma tribo na Amazônia* (dir. Nilson Araújo, 1991, 27 min); *Meninos nus* (dir. Delvair Montagner, 1995, 9 min); *Pintura corporal: uma pele social* (dir. Delvair Montagner, 1994, 20 min); *Yoranawa: gente de verdade* (dir. André Luís, 1993, 17 min); *Pau-Brasil* (1992, 5 min) | Video (magnetic tape originals) | Unknown; produced by CPCE | **No online holding located**; likely physical, with CPCE or the filmmakers' institutions | *Possible* Marúbo speech with no transcription; **preservation risk** (tape) | Strong [W] lead: title-level evidence only, no catalogue record fetched. Names a second Marúbo specialist (Delvair Montagner/Melatti) | [W] | 2026-10-18 |
| `vna_video_nas_aldeias` | Vídeo nas Aldeias — <https://videonasaldeias.org.br/> | Site replaced by a placeholder: **"Novo site em breve"**, only an e-mail and a YouTube link. The old film catalogue is **gone** | — | — | — | Films presumably now YouTube-distributed (lane 05 scope) | Fetched 2026-10-18; Wayback CDX returned no `/marubo` or `/javari` URLs before rate-limiting | [V] site dead / catalogue [U] | 2026-10-18 |
| `opir` | OPIR — Organização dos Povos Indígenas do Vale do Javari — `opir.org.br` | **NXDOMAIN** | — | — | — | Consent authority for anything from TI Vale do Javari | Must be reached off-line (§7) | [V] | 2026-10-18 |
| `cti` | CTI — Centro de Trabalho Indigenista — `cti.org.br` | **NXDOMAIN** | — | — | — | — | Same | [V] | 2026-10-18 |
| `cimi` | CIMI — <https://cimi.org.br/> | Homepage reachable; **no Marúbo mention on front page**; site-internal search not run | HTML | Site terms | Open | Low (advocacy/pastoral archive) | Homepage-level check only | [U] partial | 2026-10-18 |
| `coiab` | COIAB — <https://coiab.org.br/> | Homepage reachable; no Marúbo mention on front page | HTML | Site terms | Open | Low | Homepage-level check only | [U] partial | 2026-10-18 |
| `funaia` | FUNAI (general) | No language-archive service located; FUNAI is the holding institution behind the Tainacan museum above | — | — | — | Institutional rights holder | — | [W] | 2026-10-18 |
| `mpeg_mae_mn_inpa` | Museu Paraense Emílio Goeldi, MAE-USP, Museu Nacional/UFRJ, INPA | `museu-goeldi.br` and `museunacional.ufrj.br` **NXDOMAIN** from here; `mae.usp.br` and `gov.br/inpa` reachable but no Marúbo on front pages; no online object-catalogue query path found | — | — | — | Possible notebook/object holdings (Montagner worked with MPEG: *A morada das almas*, MPEG 1995) | Front-page-level only; **not** evidence of absence | [U] | 2026-10-18 |
| `catitu` | Instituto Catitu — <https://www.institutocatitu.org.br/> | Reachable; no Marúbo on front page | HTML | — | — | Low | Front-page check only | [U] partial | 2026-10-18 |
| `olhar_etnografico` / `imagem_movimento` | Olhar Etnográfico; Imagem-Movimento | **Hosts do not resolve** | — | — | — | — | NXDOMAIN | [U] | 2026-10-18 |

---

## 4. Master table — international ethnographic collections

| Slug | Name + URLs | Contents & volume | Formats | Licence | Access | Task fit | Trust note | St | Date |
|---|---|---|---|---|---|---|---|---|---|
| `smithsonian_si_nmai_hsfa` | Smithsonian (NMAI, HSFA) — <https://collections.si.edu/search/results.htm?q=marubo> | **Blocked** ("Smithsonian request verification" interstitial, HTTP 403) | — | — | — | HSFA is the likeliest US holder of Amazonian film/audio | No result obtained; do not record as negative | [U] | 2026-10-18 |
| `loc` | Library of Congress — <https://www.loc.gov/search/?q=marubo&fo=json> | **Blocked** (403 on the JSON API) | — | — | — | — | Same | [U] | 2026-10-18 |
| `british_library` | British Library — <https://www.bl.uk/> | Site reachable; catalogue search not attempted (post-cyber-attack reading rooms limits); no Marúbo on front page | — | — | — | Low prior | Front-page check only | [U] | 2026-10-18 |
| `british_museum` | British Museum — <https://www.britishmuseum.org/collection/search?keyword=marubo> | **Blocked** (Cloudflare "Just a moment…", 403) | — | — | — | Object labels only | — | [U] | 2026-10-18 |
| `quai_branly` | Musée du quai Branly – Jacques Chirac — <https://www.quaibranly.fr/fr/collections> | Collections page returns a 1 KB JS shell; no server-rendered results | — | — | — | Amazonian object labels | Requires browser | [U] | 2026-10-18 |
| `iai_berlin` | Ibero-Amerikanisches Institut — <https://www.iai.spk-berlin.de/> | Homepage reachable, no Marúbo on front page; digital collections not queried | — | — | — | IAI holds major Amazonianist print/ephemera collections | Not verified | [U] | 2026-10-18 |
| `smb_berlin` | Ethnologisches Museum Berlin via museum-digital — <https://smb.museum-digital.de/objects?q=marubo> | Query parameter **cannot be verified** from HTML: `q=Brasilien` and `q=shipibo` return the same empty raster grid as `q=marubo` → results are AJAX-loaded | — | — | — | — | Explicitly **not** a negative — the test is inconclusive | [U] | 2026-10-18 |
| `getty` | Getty — <https://www.getty.edu/search/?q=marubo> | Sitewide search: **0** Marúbo results | HTML | Getty terms | Open | None | Verified at sitewide-search level | [V] | 2026-10-18 |
| `unesco_marubo_item` | UNESCO archive item (known negative, preflight §3) | Not re-verified: search engines were blocked/rate-limited, and no direct UNESCO endpoint was reachable | — | none found previously | — | — | **Still negative, re-check attempted via DDG (202 + challenge) — inconclusive** | [U] | 2026-10-18 |

---

## 5. Explicit negatives (with the method that produced them)

These are the rows somebody will otherwise re-do. Each states *how* it was established.

1. **No Marúbo-language deposit exists at ELAR.** `GET https://www.elararchive.org/?s=marubo`
   returned 3 titles and a language facet of Kulina/Matses/Mayoruna only; no `Marubo` facet, and
   no `mzr`-labelled collection. Method: ELAR Preservica search + item pages.
2. **The two ELAR items whose titles say "Marubo Indians" are not Marúbo speech.** Verified on the
   item pages: language = **Kulina** (recording/annotation) with **Matses** as contact language,
   recorded in **Peru** (Estirón 2011-11-17; Puerto Callao 2011-02-26), genre *Autobiography*.
   They are Kulina Pano narratives *about* Marúbo. Method: item-page metadata.
3. **MPI/TLA has no Marúbo, Mayoruna, Shipibo, Iskonawa or Kakataibo material.** Method:
   `archive.mpi.nl/tla/islandora/search/<term>` for 15 terms. Also disproved a plausible false
   positive: TLA's 142 `matsés` hits are Murui/Witoto.
4. **CLA (Berkeley) holds nothing labelled Marúbo.** Method: CLA's own search backend
   (`…execute-api.us-east-1.amazonaws.com/api/ac?q=marubo`) → `{"results": []}`.
5. **Pangloss/LACITO has no Panoan corpus at all** (299 corpora parsed from the page's embedded
   JSON; zero matches for 8 Panoan language names). Method: JSON parse, not rendered-text grep.
6. **`acervo.museudoindio.gov.br` is dead** (NXDOMAIN); the live Museu do Índio catalogue is the
   Tainacan instance. Method: DNS + HTTP.
7. **`prodoc.museudoindio.gov.br` is offline** (DNS resolves, TCP refused on 80 and 443).
8. **OPIR and CTI have no working public web presence** (NXDOMAIN on 2026-10-18). This matters
   for §7 — the two most obvious consent intermediaries are unreachable online.
9. **Vídeo nas Aldeias' catalogue is offline** ("Novo site em breve"); no Marúbo/Javari catalogue
   URL survives in Wayback's index for that host (CDX query returned empty before rate-limiting).
10. **No open Marúbo dictionary/grammar in any archive** — confirms the repo's existing negative
    from a *different* method (archive-record search rather than web search).

Explicit `[U]`, **do not convert to negatives**: AILLA, PARADISEC, Smithsonian, LoC, British
Museum, quai Branly, IAI, SMB, WOLP, Museu Goeldi, Museu Nacional/UFRJ, MAE-USP, INPA, CIMI/COIAB
site-internal search, and the UNESCO item.

---

## 6. What actually has linguistic value — and of what kind

**Documentation *of* Marúbo speech (language documentation):**

| Source | What it is | Why it matters | Caveat |
|---|---|---|---|
| `sil_lca_javari_survey` (Anonby & Holbrook 2010) | Sociolinguistic survey of six Javari languages, 44 pp., Marúbo included by name in the abstract | Comparative lexical/sociolinguistic data; Javari contact network; near-contemporary (2010) | Wordlist-level, not discourse; orthography likely practical/SIL-influenced; PDF not fetched here |
| `sil_ebook086_marubo_demonstratives` (Smith 2024, ch. 2) | Discourse-pragmatic analysis of Marúbo demonstratives with quoted forms | **IGT-grade**: Marúbo form + gloss + English; exactly the shape that becomes alignment evidence | Only one chapter; PDF blocked to this client; licence unstated |
| `museu_indio_tainacan` | Object names in Marúbo with Portuguese glosses (`rome rawe`, `bona tachota ya`) | Unique lexical items, incl. ritual/shamanic vocabulary, with material-culture referents | ~8 items; ritual register; collected 1975/1994 without recorded consent |
| `sil_lca_texting_marubo` (Eberhard 2022) | Indicates a Marúbo texting/messaging dataset | A *modern, informal* register — rare and valuable for NMT | Paywalled; corpus itself not deposited |

**About Marúbo, in Portuguese/English (low linguistic value, real finding-aid value):**
`isa_pib_marubo` (Melatti), the ELAR Kulina narratives, `isa_cpce_films` (title-level only),
CIMI/COIAB front pages.

**Related Panoan only (hypothesis-generating, never `mzr` truth — invariant 8):** ELAR
Cashibo-Cacataibo/Kakataibo (344), Yaminahua (36), Nahua (25), Kulina Pano (267), Matsés (287);
TLA Cashinahua (34).

A note on the *kind* of evidence: nothing in this lane is a clean speech/transcript pair. The best
this lane can feed the LKB is (a) IGT sentences from Smith 2024, (b) a comparative wordlist from
Anonby & Holbrook, and (c) isolated nominal lexemes from museum labels. All three are
`supports_hypothesis` material at best; none should be promoted past `supported` without the
Clef grounding path (ADR-0020/0021).

---

## 7. Community-first list — use requires Marúbo/OPIR engagement

Ordered by how much friction the *right* path involves. Nothing in this section should be ingested
merely because a licence or an "open" flag exists.

1. **`museu_indio_tainacan` — Marúbo object names (`rome rawe`, `bona tachota ya`).**
   The items are marked `Disponibilidade do objeto: Livre` (availability of the *object*), collected
   in 1975 and 1994 with no recorded consent for language reuse. Several are shamanic-ritual
   instruments → register `ritual_restricted` by default. **Approach:** ask FUNAI's Museu Nacional
   dos Povos Indígenas museology service for the collector's field sheets (Delvair Melatti
   collection), and put the lexical items to Marúbo speakers via OPIR before any use beyond
   catalogue metadata.
2. **`elar_marubo_title_items` — Fleck's two "Marubo" sessions.** Third-party (non-Marúbo)
   recordings of Marúbo people's history of conflict, made in Peru, `U_UserAccess`. **Approach:**
   ELAR deposit access request **plus** Fleck as depositor **plus** Marúbo consent; do not treat
   ELAR registration as sufficient.
3. **`ailla` (once verified).** AILLA's tiers explicitly include community-restricted deposits;
   if any Marúbo deposit exists it will likely carry such a tier. **Approach:** read each deposit's
   access statement before requesting anything; route through OPIR.
4. **`isa_cpce_films` (1991–1995 Betacam).** If located, the films will contain Marúbo people and
   possibly Marúbo speech with **no transcriptions**; rights sit with the filmmakers/production
   centre, and the people filmed retain interests the copyright line does not express.
   **Approach:** filmmaker permission *and* community consultation; treat as `unknown` register.
5. **Known-item overlap (`cesarino_2017`, myth-chants; `cesarino_2013`).** Already in the LKB with
   CC-BY-4.0, but they are **ritual chant** material — the ISA page states outright that Marúbo has
   a "ritual counterpart" with a "parallel vocabulary" in myths and curing chants. Flag for
   `ritual_restricted` register review even though the licence permits reuse (ADR-0023 quality/
   register fields), so the LKB does not learn chant-only vocabulary as everyday Marúbo.

**How to approach, given that OPIR (`opir.org.br`) and CTI (`cti.org.br`) are both NXDOMAIN as of
2026-10-18:** route through (a) FUNAI's Atalaia do Norte regional coordination, (b) ISA's Vale do
Javari programme (ISA is reachable and its Marúbo page is authored by a long-standing Amazonianist),
(c) CIMI's regional office (site up), and (d) the named academics who have worked in the Javari and
hold institutional relationships — David Fleck (Matsés/Kulina, U. Oregon), Raquel Guimarães
Romankevicius Costa, Pedro de Niemeyer Cesarino, and **Melissa Ruth Smith** (new name from
`sil_ebook086`). Ask OPIR/associations for a **written reuse policy** rather than case-by-case
permission; record it as the `policy_id` and `authority` for every Javari source. *This route is
unverified — it is the next lane's first task, not a conclusion.*

---

## 8. Ranked top-3 for the LKB (and the two blocking checks)

1. **`sil_ebook086_marubo_demonstratives` — Smith 2024, "Marubo Demonstratives" (SIL e-Books 086,
   ch. 2).** New, IGT-shaped, discourse-level, from a named Marúbo specialist. *Blocking check:*
   fetch `silebook086_Functions_Nicolle.pdf` (2.33 MB) from a normal browser session and confirm
   the copyright page; no licence is stated on the record page.
2. **`sil_lca_javari_survey` — Anonby & Holbrook 2010, SILESR 2010-003 (44 pp.).** Open, explicitly
   covers Marúbo, and gives comparative Javari data that also strengthens the related-language
   hypothesis graph (Korubo/Kulina Pano → Northern Panoan). *Blocking check:* same 403; confirm
   whether the Marúbo section is a real wordlist or only a sociolinguistic questionnaire.
3. **`museu_indio_tainacan` — Marúbo object records with `Nome étnico do item`.** Tiny but
   genuine, and it opens a documented path to the Melatti/Montagner 1975 field materials, which is
   where Marúbo notebooks, if they survive anywhere, will be. *Blocking check:* consent route (§7.1).

Honourable mention / highest-upside unknown: **`ailla`**. It is the only archive in this lane whose
Panoan depth is certain and whose Marúbo status is genuinely open. It must be closed by a human
before this lane can claim exhaustion.

---

## 9. Cross-lane leads this lane produced (hand to lanes 02/01)

Collected incidentally; not my lane to verify, but each is a concrete next fetch:

- **"Banco de Dados da Língua Marubo"**, Judith Ferreira Pedrosa, *Anais do XXXII Congresso de
  Iniciação Científica* (CONIC, Manaus, 2024), ISBN 978-65-272-0470-1,
  DOI `10.29327/xxxii-congresso-de-iniciacao-cientifica-380957.768609` → resolves to an
  **abstract-only** Even3 page (pt-BR). Lead: the author built a Marúbo database; ask for it.
- **"Vestiges of body-part prefixation in Marubo"** (2022), DOI `10.1093/oso/9780198852476.003.0015`
  — chapter in an OUP Panoan volume; morphology-relevant.
- **"Did the Kulinas become the Marubos? A Linguistic and Ethnohistorical Investigation"**,
  *Tipití* (2007), DOI `10.70845/2572-3626.1042` — directly about Marúbo/Kulina Pano relations.
- **"Entre la parole et l'image : le système mythopoétique marubo"**, *JSA* (2011), DOI
  `10.4000/jsa.11739` — **French-language** article (mission asked for FR catalogues).
- **"87 Marubo"**, De Gruyter eBooks (2024), DOI `10.1515/9783111053226-087` — unknown handbook
  chapter; check for IGT.
- **"Emerging peoples: Marubo myth-chants"** (2001), University of St Andrews repository (= Couto
  2001 doctoral thesis, per ISA's bibliography).
- **`Kirinkobaon kirika` ("Gringos' Books"): an annotated Panoan bibliography**, Erikson et al.,
  *Amerindia* 19 (1994), 152 pp. — the single best Panoan finding aid; if Amerindia/CELIA has it
  open, it converts this whole survey from search-driven to bibliography-driven.

---

## 10. Residual uncertainty (stated plainly)

- AILLA's Marúbo status is **unknown**, not negative. It is the largest hole in this lane.
- PARADISEC is unknown (WAF). Low prior for Amazonian Panoan, but unmeasured.
- Every PDF in §2 is **metadata-verified, content-unverified** because `sil.org` returns 403 to a
  non-browser client. Two of my top three recommendations therefore rest on record metadata plus a
  table of contents, not on reading the text.
- Museum holdings in Berlin, Paris, London, Washington and Belém are **unmeasured** — every one of
  those catalogues is JS-rendered or bot-walled. Absence there is not asserted anywhere in this
  report.
- The ISA film list is title-level evidence from a 1998 bibliography; whether the Betacam masters
  still exist is unknown and worth one phone call, not another web search.
