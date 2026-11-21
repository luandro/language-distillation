# Lane 03b — Archives & ethnographic media, re-run with working search (Panoan / Marúbo)

- **Survey date:** 2026-10-18 (recheck run)
- **Target:** Marúbo (`mzr`, Glottolog `maru1252`), Panoan, TI Vale do Javari, Amazonas, BR
- **Supersedes nothing.** `03-archives-media.md` is left intact and remains the record of the first pass.
  This file re-walks only its **blocked/unverified** and **community-first** items and reports what is now settled.
- **Companion files:** `../00-preflight.md` (contract, governance, tooling), `../FINDINGS.md` (digest).
- **Governance frame:** per `AGENTS.md` invariant 6 / ADR-0025, presence in the repository is the
  authorization; licence and register are **recorded metadata, never gates**. Licences below are quoted
  verbatim where found. Nothing here was ingested into `var/`, no accounts were created, no bot wall,
  paywall or CAPTCHA was bypassed, and no large media was downloaded (only PDFs of books, ≤11 MB, to
  read their copyright pages and quantify their Marúbo content).

---

## 1. What changed since `03-archives-media.md`

**The single largest hole is closed: AILLA does hold Marúbo material, and it is public.**

| # | Change | Old status | New status |
|---|---|---|---|
| 1 | **AILLA holds 2 Marúbo resources** (Ernest Migliazza, recorded Rio Ituí 1976-07-23: a 55-minute *Word List and Songs* and a *Stories* session), both **Access Level 1 = Public** | `[U]` "Marúbo presence not confirmed" | `[V]` — full item metadata recovered |
| 2 | **Root cause of every failed AILLA query found:** AILLA indexes Marúbo under its own legacy code **`qkf`**, not `mzr`. `site:ailla.utexas.org mzr` could never have matched | — | recorded; correct the query templates in the registry |
| 3 | **CTI is not dead — it moved.** `cti.org.br` is still NXDOMAIN, but CTI's digital library (`biblioteca.trabalhoindigenista.org.br`, "Biblioteca Digital CTI") is live, open, and holds **bilingual Marúbo–Portuguese books with running Marúbo prose** | `[V]` NXDOMAIN, no holdings recorded | `[V]` — new top find |
| 4 | **World Oral Literature Project is alive** at `www.oralliterature.org` (the old report only tried `worldoral.org`, which is genuinely NXDOMAIN) — and has no Marúbo collection | `[U]` "host does not resolve" | `[V]` negative |
| 5 | **museum-digital settled as a real negative** using its JSON search backend with a positive control (Marúbo 0, Shipibo 38) | `[U]` "inconclusive, AJAX" | `[V]` negative |
| 6 | **ELCat settled:** `lang/3008` is Marúbo, and its Resources tab is empty | `[U]` | `[V]` negative |
| 7 | **Acervo Yurará Sin reached via API:** 64 Marúbo items (front end is broken, API is not) | not in the lane | `[V]` catalogue / `[W]` files |
| 8 | **Library of Congress partially readable** via the search index: 3 HLAS bibliographic records about Marúbo | `[U]` 403 | `[W]` (titles only) |
| 9 | **Pavia DEmA has a Marúbo entry with 3 glossed IGT clauses** | not in the lane | `[V]` |
| 10 | **The 1991 CPCE film *Marubo: uma tribo na Amazônia* is online** (YouTube), plus 3 more Marúbo videos | `[W]` "title-level only, no online holding located" | `[W]` located, untranscribed |
| 11 | British Library, quai Branly, IAI Berlin, Smithsonian: **still unknown**; no new access route worked | `[U]` | `[U]` (unchanged, now with a stated barrier) |
| 12 | PARADISEC: catalogue still WAF-403, but the **main site's own search returns "Nothing Found"** for `marubo` | `[U]` | `[W]` weak negative |

**Net effect on the LKB:** this lane moves from "nothing ingestible" to **one genuinely large,
community-authored, bilingual Marúbo↔Portuguese text corpus** (CTI's *Vaná rasĩ*, 51 pp. + *Pinturas
Marubo*, 168 pp. + *Os Marubo e os bichos de casco*, 57 pp.), plus **55 minutes of 1976 Marúbo audio
(wordlist + songs) on public access at AILLA**. That is a categorical change in what this lane can feed
the pipeline — see §6.

---

## 2. Method this run — and why it finally worked

`web_search` is functional in this session (DeepSeek server-side search), 4 queries per call, `site:` honoured.

What actually produced the findings, in order of yield:

| Route | Yield |
|---|---|
| `web_search` with `site:` | **decisive** — surfaced the AILLA item, the OLAC record, the ELAR/LoC/ELCat pages, and the CTI/Yurará Sin PDFs |
| **Wayback playback** (`web.archive.org/web/2023/<url>`) | **decisive for AILLA** — full object pages rendered from 2023 snapshots |
| **Site JSON/REST backends** (museum-digital `/json/objects`, Tainacan `/wp-json/tainacan/v2/…`, WordPress `/wp-json/wp/v2/search`) | **decisive** for museum-digital, CTI, Acervo Yurará Sin, PIB wikitext |
| Direct `pdftotext` on publisher PDFs | how the CTI finds were quantified |
| Wayback **CDX API** | **unavailable** — "Internet Archive services are temporarily offline" (playback still worked) |

Blocked or degraded, recorded not retried in loops:

- `ailla.utexas.org` — **Anubis v1.27.0 proof-of-work wall** on every path, *including* the metadata
  datastreams `/islandora/object/ailla:<id>/datastream/{MODS,DC,LANGUAGE}/download`, which the search
  index shows are normally plain downloads. Not circumvented. Wayback was used instead.
- `catalog.paradisec.org.au` — "WAF Block – The University of Sydney", HTTP 403 (unchanged).
- `collections.si.edu` — "Smithsonian request verification", HTTP 403.
- `www.loc.gov` — Cloudflare "Just a moment…", HTTP 403 on both the JSON API and item pages.
- `search.language-archives.org` — **NXDOMAIN**. OLAC's new search SPA (`language-archives.org`) has no
  A record for its own API host, so OLAC records are not machine-readable from here.
- `prodoc.museudoindio.gov.br` — DNS resolves (177.184.13.18), TCP still refused on 80/443.
- `opir.org.br`, `cti.org.br` — **still NXDOMAIN**.
- `acervoyurarasin.com.br` — every front-end route returns **HTTP 500**; the Tainacan REST API and
  direct `wp-content/uploads/` file paths still answer 200.

---

## 3. Per-target table

Three sub-tables together are "the per-target table": **A** = targets with Marúbo content,
**B** = targets checked this run and settled negative, **C** = still unknown.
Status `[V]` = verified by fetching the record/endpoint named in the row; `[W]` = partial,
metadata-only, or secondary evidence; `[U]` = unverified/blocked. All dates 2026-10-18.

### 3.A — Targets where Marúbo material IS present

| Slug | Name / collection | URL | Marúbo present? (evidence) | Volume | Media type | Access | Licence / terms | St |
|---|---|---|---|---|---|---|---|---|
| `ailla_marubo_migliazza` | **AILLA** — *Amazonian Languages Collection of Ernest Migliazza*, Marúbo language collection (`ailla:119566`) | <https://ailla.utexas.org/islandora/object/ailla%3A119566> · items `ailla:125121`, `ailla:125122` | **YES.** Language object page: `Name: Marúbo · Language Code: qkf · Macro Language: N · Language Family: Panoan · Countries: Brazil`. Both resources carry `Subject Language: Marúbo · Language PID(s): ailla:119566`. Recorded **Rio Ituí, Amazonas, 1976-07-23** | **2 resources, 4 files** (mp3 + wav each). Resource 1 `QKF001R001I001` = **0:55:04**, 128 kbps, `Original Medium: audio:cassette`, `Quality of Original Medium: 3`, archived 2004-11-04 | Audio (digitised cassette); one session of **Wordlist + Song**, one of **Narrative** | **Access Level 1 = Public.** AILLA: *"AILLA Users have full access to these materials after creating an account and agreeing to AILLA's Conditions for Use of Archive Resources."* | Licence not stated at item level. AILLA Conditions for Use govern. AILLA asserts for Level 1 that *"depositors have already gained permission for public access from the speakers or authors"* — an archive-side assertion for a 1976 recording deposited 2004 | **[V]** |
| `cti_biblioteca_digital` | **Biblioteca Digital CTI** (= Centro de Trabalho Indigenista; successor to the dead `cti.org.br`) | <https://biblioteca.trabalhoindigenista.org.br/?s=marubo> · <https://biblioteca.trabalhoindigenista.org.br/povos/marubo/> | **YES — best Marúbo text source found this run.** `?s=marubo` → 5 items; `?s=Javari` → 37. Two are bilingual Marúbo–Portuguese books (§6.1, §6.2) | **5 Marúbo-titled items** (2 books with downloadable PDFs, 2 theses, 1 article) inside a 37-item Javari cluster | PDF books (51 pp., 57 pp.), theses, articles | **`Controle de acesso: público`**; PDFs download directly, no account | `Vaná rasĩ`: **"© CTI Centro de Trabalho Indigenista"**, ISBN 978-85-60028-22-1. `Bichos de casco`: **"© Centro de Trabalho Indigenista – CTI/Programa Javari"**, ISBN 978-65-992926-6-8. `Pinturas Marubo`: see next row | **[V]** |
| `cti_pinturas_marubo` | **Pinturas Marubo** (2021), Maria Elisa Ladeira (org.), CTI — *Coleção Escola Marubo, Série Cultura e Memória* | <https://biblioteca.trabalhoindigenista.org.br/livros/pinturas-marubo/> · PDF `…/tainacan-items/137/113971/PINTURAS_MARUBO1.pdf` | **YES.** Marúbo **kene** nomenclature: *"Cada kene tem seu nome e significado próprio."* Text yields **≈45–50 distinct named kene** (e.g. `Kapê Shikachi Kene`, `Ene Pixi Kene`, `Ene Txitxã Kene`, `Ene Kenã Kene`, `Ene Chomo Kene`, `Asi Tae Kene`, `Mîpo Tae Kene`, `Txeshê Ashká Kene`, `Yawa Merîki Kene`), plus clan names (`Tamawavo`, `YnoNawavo`, `RaneNawavo`, `Vari/Tama/Shane Shavovo`) and personal names | **168 pp.**, 11 MB | PDF (print book, illustrated) | Open download, no account | **"© Todos os direitos reservados ao povo Marubo"** — rights holder is *the Marúbo people*, not the NGO. Publisher CTI. Marúbo co-authors named: Juliana B. Duarte Marubo, Nelly B. Duarte Marubo, Aldeney Võpa, Genivaldo de Oliveira, Nishavo Kamã, Tamã Shëta | **[V]** |
| `acervo_yurara_sin` | **Acervo Yurará Sin** — Tainacan collection `246 "Acervo Yurarasin"` | <https://acervoyurarasin.com.br/wp-json/tainacan/v2/collection/246/items?search=marubo> · <https://acervoyurarasin.com.br/> | **YES — 64 items matching `marubo`** returned by the collection API. Lexically/linguistically notable: **`Cânticos Xamânicos dos Marúbo`**, **`Texto do Darcy Marubo`** (JPEG scan of a Marúbo text), **`NOKẼ MEVI REVÕSHO SHOVIMA AWE`** ('o que é transformado pelas pontas das nossas mãos' — Marúbo title + PT gloss), **`Wenía … Leitura e tradução de um canto narrativo`**, `Mani Pei Rao: remédios do mato dos Marúbo`, `A coda nasal em Marubo e Matsés (Pano)`, `MITOLOGIA MARÚBO` | **64 items** (Marúbo query); 4 are online videos | Mixed: PDF, DOCX, JPEG, YouTube links | **Catalogue API open; front end HTTP 500 on every route**; `exposer_urls` empty, so file links are not published. **Direct `wp-content/uploads/tainacan-items/246/…` paths DO return 200** (verified, 709 KB PDF) — files are retrievable if the path is known | No site-level licence found; individual items carry their own publisher terms (mostly academic PDFs). Treat as a **link/index resource**, not a rights grant | **[V]** catalogue / **[W]** files |
| `pavia_dema_marubo` | **Pavia DEmA** — Diachronic Emergence of Alignment database | <https://dema.apnetwork.it/database/?pagina=l&id=13> | **YES.** `Marubo · Glottocode: maru1252 · Panoan`. 3 glossed clauses, e.g. (1) `Ɨa-n 'matu-Ø ɨn-ʃu'tun-ai` = `1SG-ERG 2PL-ABS 1SG(A)-push-PRES/IPFV` 'I have pushed you.'; (2) `Ɨa-Ø ra'ka-ai` 'I am lying.' | **3 IGT examples**, ~40 words | HTML | Open | Not stated; DB is academic citation — entries attribute **Siewierska 2004:135** and **Ganfi 2016:166-167** | **[V]** |
| `loc_hlas_marubo` | **Library of Congress** — HLAS bibliographic records | <https://www.loc.gov/item/hlas-bi2013002889/> · `/hlas-bi2012005633/` · `/hlas-bi88000602/` | **Titles only**, all *about* Marúbo in PT: "A escrita e os corpos desenhados: transformações do conhecimento xamanístico entre os Marubo"; "Donos e Duplos: relações de conhecimento, propriedade e autoria entre Marubo"; "Os padrões Marúbo" | 3 records | Bibliographic metadata | Record pages **403 (Cloudflare)**; titles recovered from the search index | n/a (citations) | **[W]** |
| `ia_marubo_video` | **Internet Archive** — community uploads | <https://archive.org/advancedsearch.php?q=marubo> | 8 hits total; only one Marúbo-topic video (`MARUBOKABLESGEREKBRAMAZONDENEYM`, a Turkish travel channel's Marúbo episode; no language metadata, no transcript). Others are unrelated (a newspaper, "Vanishing Amazon", a Starlink news clip) | 1 low-value video + noise | MP4/OGV | Open | Uploader-chosen; no licence stated | **[W]** |

### 3.B — Checked this run, settled negative

| Slug | Name / collection | URL | Marúbo present? (evidence + method) | St |
|---|---|---|---|---|
| `museum_digital_all` | **museum-digital** (all institutions incl. SMB / Ethnologisches Museum Berlin) | `https://global.museum-digital.org/json/objects?s=marubo` | **NO.** JSON backend (the real search, not the AJAX grid): `s=marubo` → `{"status":"Error","msg":"There are no results for this query."}` (HTTP 404 = 0 hits); `s=marúbo` → 0; `s=javari` → 0. **Positive controls in the same call:** `s=shipibo` → **38** objects (e.g. "Shipibo-Frauen vom Rio Pachitea", `VIII E Nls 818`), `s=pano` → 4, `s=culina` → 3. The index demonstrably holds Panoan ethnographic records and returns 0 for Marúbo | **[V]** |
| `wolp_oralliterature` | **World Oral Literature Project** (Cambridge) — **alive at a different hostname than the previous lane tried** | <http://www.oralliterature.org/> | **NO Marúbo.** `www.worldoral.org` = NXDOMAIN; **`www.oralliterature.org` = HTTP 200**. Zero matches for `marubo|marúbo|pano` on `/collections/collections.html`, `/collections/map.html`, `/grants/grantees.html`, `/research/wols.html`; `site:oralliterature.org marubo` → nothing | **[V]** |
| `elcat_marubo` | **ELCat / Endangered Languages Project** — `lang/3008` | <http://elcat.colo.hawaii.edu/lang/3008/bibliography> · `/lang/3008/samples` | **Metadata yes, media no.** `Marubo [aka Marobo, Marúbo, Maruba] · Classification: Pano-Tacanan · threatened`. Bibliography = 6 citations (ELCat 2012; UNESCO Atlas 2010; WOLP; Crevels 2012; Ethnologue 16; Anonby & Holbrook 2010; Kensinger 1985) — all bibliographic, **no holdings**. Resources tab: **"There are no samples of Marubo yet"** | **[V]** |
| `paradisec` | **PARADISEC** | <https://www.paradisec.org.au/?s=marubo> · <https://catalog.paradisec.org.au/> | **Catalogue still blocked; site search negative.** `catalog.paradisec.org.au` every path incl. `/api/v1/search` → WAF 403 (University of Sydney). PARADISEC's own WordPress site search: **"Nothing Found"** for `marubo`. Wayback has the catalogue home (200) but archived **no** search URL. Weak negative, not a catalogue-level negative | **[W]** |
| `cti_domain` | `cti.org.br` (bare domain) | — | **Still NXDOMAIN** — but see `cti_biblioteca_digital`: the organization's holdings are reachable via `trabalhoindigenista.org.br` and `biblioteca.trabalhoindigenista.org.br` | **[V]** |
| `opir_domain` | OPIR — Organização dos Povos Indígenas do Vale do Javari | `opir.org.br` | **Still NXDOMAIN** (re-verified this run). No successor public web channel found. This still matters: OPIR is the consent authority for TI Vale do Javari | **[V]** |
| `prodoclin` | PRODOCLIN — `prodoc.museudoindio.gov.br` | <http://prodoc.museudoindio.gov.br/> | **Still offline:** DNS resolves (177.184.13.18) but HTTP/HTTPS connection refused. Note: the search index still holds paths such as `/images/boletins/Boletim_program_linguas_ano05_n54.pdf` (PRODOCLIN "Programa de Documentação de Línguas" bulletins) — the server *did* host language-documentation bulletins; it is unreachable, not absent | **[V]** dead / contents **[U]** |
| `cimi` | CIMI | <https://cimi.org.br/> | **No Marúbo language data.** Reachable; hits for Marúbo are advocacy PDFs (*"Carta dos Povos Indígenas do Vale do Javari"*, Coipam letter to FUNAI). Useful as a **consent intermediary**, not as data | **[V]** |
| `museu_indio_tainacan` | Museu Nacional dos Povos Indígenas (ex-Museu do Índio) Tainacan | <https://tainacan.museudoindio.gov.br/?s=marubo> | **Unchanged from lane 03 — not re-enumerated.** Live (HTTP 200, 376 KB); lane 03 already verified ~8 Marúbo item records with `Nome étnico do item` Marúbo forms (`rome rawe`, `bona tachota ya`). Re-confirmed live only; the correct row remains in `03-archives-media.md` §3 | **[V]** live |

### 3.C — Still unknown, with the exact barrier

| Slug | Target | Barrier (exact) | What would close it |
|---|---|---|---|
| `smithsonian_si_nmai_hsfa` | Smithsonian (NMAI, HSFA/Fitzroy) | `collections.si.edu` → "Smithsonian request verification" 403; `api.si.edu` needs a registered API key (would require an account — not obtained). `site:si.edu marubo` returned only a `mads.si.edu` HSFA/NAA subject-guide PDF with no Marúbo entry | A keyed SI Open Access API query, or one human browser session |
| `british_library` | British Library | No catalogue route found; `site:bl.uk marubo` → no hits. BL catalogues still degraded post-cyber-attack | BL Explore / Sound Archive search by hand |
| `quaibranly` | Musée du quai Branly – Jacques Chirac | Collection front end is a JS shell; `site:quaibranly.fr marubo` → only an accessibility brochure, no object record | Browser session on the collection UI |
| `iai_berlin` | Ibero-Amerikanisches Institut | `site:iai.spk-berlin.de marubo` → no hits; digital collections not queryable via a JSON route I could find | IAI OPAC / digitalisierte Sammlungen by hand |
| `british_museum` | British Museum | Not re-attempted this run (Cloudflare previously) | — |
| `mpeg_mae_mn_inpa` | Museu Paraense Emílio Goeldi, MAE-USP, Museu Nacional/UFRJ, INPA | No online object-catalogue query path found; `museu-goeldi.br` / `museunacional.ufrj.br` were NXDOMAIN in lane 03 and no JSON catalogue surfaced this run. **Absence not asserted** — Montagner worked with MPEG (*A morada das almas*, MPEG 1995), so notebook/object holdings remain plausible | MPEG's collection database by hand |
| `olac` | OLAC aggregator records | `search.language-archives.org` **NXDOMAIN**; `language-archives.org` is a JS SPA whose API host does not resolve; `olaca3.pl` → 404 | Any OLAC mirror, or a browser session on the SPA |
| `ailla_other_depositors` | Whether AILLA holds Marúbo material **beyond** the Migliazza collection | The per-language listing route and the `ailla-language-codes` table are Anubis-walled; the archived copy of the codes page is an empty paginated shell. The Migliazza collection is the only one I could enumerate end-to-end, and its own index lists Marúbo with exactly 2 resources | One logged-in AILLA session: `Languages → Marúbo` |

---

## 4. Corrections to `03-archives-media.md`

1. **"AILLA … Marúbo presence not confirmed"** → **wrong to leave open.** AILLA has Marúbo; the reason
   it was invisible is that **AILLA's internal code for Marúbo is `qkf`, not `mzr`.** Querying by ISO
   code against AILLA will keep failing. Registry entries for AILLA must carry `qkf` as an alias key.
2. **"`worldoral.org` does not resolve … WOLP collections reportedly migrated"** → the live host is
   **`www.oralliterature.org`**, and it still carries the original (small) collection list, with **no
   Marúbo collection**. This is now a negative, not an unknown.
3. **"museum-digital … not a negative, the test is inconclusive"** → now a **real negative**, because the
   `~/.json/objects` backend is the search itself and Shipibo returns 38 in the same call.
4. **"`isa_cpce_films` … No online holding located"** → the 1991 film **`Marubo: uma tribo na Amazônia`
   is online** (`youtu.be/b0pxE7J3i3Q`, indexed in Acervo Yurará Sin). Still title/link-level: no
   transcript, no timecodes, no rights statement.
5. **"`biblioteca.trabalhoindigenista.org.br` hosts *Vaná rasĩ*"** → understated. *Vaná rasĩ* is not a
   PDF of a thesis; it is a **2023, 51-page, bilingual Marúbo–Portuguese book with continuous Marúbo
   prose** explicitly written *"nas 2 línguas: a língua pano e a língua portuguesa"`. See §6.1.
6. **`cti.org.br` NXDOMAIN ≠ CTI is unreachable.** CTI's digital library is live and is the richest
   Marúbo-publisher found in this lane.
7. **`elcat.colo.hawaii.edu/lang/3008/bibliography`** (named in the mission) resolves and is Marúbo —
   but its sample/resource tab is empty; do not re-query it hoping for media.

---

## 5. Ranked top-3 finds (dataset value + consent notes)

### 1. `cti_biblioteca_digital` — CTI's bilingual Marúbo books: *Vaná rasĩ* (2023) + *Pinturas Marubo* (2021) + *Os Marubo e os bichos de casco* (2021)

**What it is.** Three open, community-authored books in which Marúbo people write *in Marúbo*, with
Portuguese alongside:

- **`Vaná rasĩ: As plantas que cultivamos na roça`** (CTI, 2023, 51 pp., ISBN 978-85-60028-22-1), by
  **Sanĩ Nawa / Alfredo Barbosa Filho Marubo** with Maria Elisa Ladeira & Thiago Arruda Ribeiro dos
  Santos. Chapters are Marúbo category terms: **Yorã Wai** (as roças), **Tae** (as batatas), **Vimi**
  (os frutos), **Tasho** (os caules), **Pei** (as folhas). Structure per entry: Marúbo headword →
  Marúbo prose for *Origem / Como se planta / Para que serve / Respeitos* → Portuguese translation.
  Reports **166 etnovariedades tradicionais** Marúbo cultivars across four categories. Also contains a
  first-person Marúbo autobiographical narrative (with Portuguese lexical borrowing: *fita kasete*,
  *pesquisador*, *reunião*, *universidade*) — i.e. a **modern, informal register**, the rarest thing to
  find for this language, and the one the previous lane could only point at through a paywalled article.
- **`Pinturas Marubo`** (2021, 168 pp.): **≈45–50 named *kene*** (graphic/body-painting designs), each
  with its own name and meaning, plus clan and personal names. Kene are collected 1975–1990
  (Delvair Montagner), 2004–2007 (Elena Welper), 2011 (Mafê Vieira), face-paintings 1990 (aldeia São
  Sebastião). Marúbo co-authorship is explicit and named.
- **`Os Marubo e os bichos de casco do rio Ituí`** (2021, 57 pp., ISBN 978-65-992926-6-8): the **shakayavo
  / shawe** folk taxonomy, **5 species cards** in the form `SHAWẼWÃ | tartaruga-da-amazônia |
  Podocnemis expansa`, and Marúbo seasonal/ritual terms with glosses — `tãko vatxi aka shavá` ('tempo de
  pegar ovos de tracajá', Jun–Jul), `shawẽwã atxi aka shavá` ('tempo de pegar tartaruga', Aug–Sep),
  **`Shawẽ Vatxi Piá`** ('Festa dos Ovos de Tartaruga').

**Why it is #1.** It is the only Marúbo↔Portuguese material this lane found that is (a) *prose*, not
wordlists; (b) *paragraph-aligned* by construction (each Marúbo passage is immediately translated);
(c) *community-authored and community-copyrighted*; (d) *modern* (2021–2023), so it does not teach only
1976 or chant register; and (e) *freely downloadable without an account*. For NMT and for a
natural-text register it is worth more than everything else in this lane combined. Lexical payload is
concentrated: ethnobotanical and ethnobiological nouns with scientific + Portuguese anchors.

**Consent notes.** `Pinturas Marubo` states **"© Todos os direitos reservados ao povo Marubo"** — the
rights holder is the Marúbo people, so attribution must name them, and any revocation request would come
from a Marúbo body (associations / OPIR), not from CTI. The other two books are **"© CTI"**. All three
were produced with named Marúbo co-authors and, for `Vaná rasĩ`, from a participatory survey across the
9 Marúbo villages of the Rio Curuçá, agreed with village elders, chiefs, women and teachers. That is a
far stronger consent provenance than any museum label or 1976 archive deposit. **Register caution
(invariant 3/8 of the lane brief):** *kene* designs are clan/ritual property and `Pinturas Marubo`
contains shamanic exegesis ("Tudo é pensamento de pajé") and named `Respeitos` taboos — the *lexicon* is
safe to record, the *ritual exegesis* should be tagged `ritual_restricted` rather than learned as
everyday Marúbo. `Shawẽ Vatxi Piá` is a named festival, not everyday vocabulary.

**Blocking check:** nothing. All three PDFs are open and were read here. Recommended next step is a
human/operator `presence` decision to place them in `var/external/`, not another search.

---

### 2. `ailla_marubo_migliazza` — AILLA, Migliazza's 1976 Rio Ituí *Word List and Songs* + *Stories*

**What it is.** Two resources, four files, recorded **1976-07-23 at Rio Ituí, Amazonas** by **Ernest
Migliazza** for the *Brazilian National Museum word list* elicitation programme (NEH grant PD-50003-06):

- **`ailla:125121` "Word List and Songs" / "Vocabulario y Canciones"** — genres **Wordlist; Song**;
  speaker **Juan Janisio**; **0:55:04**, 128 kbps; digitised from **cassette** (source quality 3);
  archived 2004-11-04.
- **`ailla:125122` "Stories" / "Cuentos"** — genre **Narrative**; 2 files (mp3 + wav).

**Why it is #2.** A comparative wordlist elicitation is *exactly* the structured lexical shape the LKB
wants, and it is date-stamped and place-stamped (Rio Ituí, 1976) — which matters because Marúbo has a
ritual/"parallel vocabulary" register (ISA's own page says so) and a 1976 Ituí wordlist is a plausible
check on ordinary register. It also gives **audio**, which almost nothing else in this lane has. Access
is the best AILLA offers.

**Consent notes.** AILLA Level 1 is *"Public Access … For this level, we assume that depositors have
already gained permission for public access from the speakers or authors."* That is a 2004-era
archive-side assumption covering a 1976 recording of a named speaker (Juan Janisio) and a named
researcher. It is not a Marúbo community consent, and **it is not a statement about the ritual
vocabulary inside the songs**. Practical route: treat the *wordlist* as ordinary register; tag the
*song* genre `ritual_restricted` pending Marúbo review through OPIR/FUNAI Atalaia do Norte, per the
community-first list in `03-archives-media.md` §7.

**Blocking check:** none now — but the human must create a free AILLA account to download (agents may
not). Volume to expect: ~55 min + one narrative session, 4 files.

---

### 3. `acervo_yurara_sin` — Acervo Yurará Sin: a 64-item Marúbo-focused digital collection, currently half-broken

**What it is.** A Tainacan collection (`246 "Acervo Yurarasin"`) with **64 items matching `marubo`**,
including material no other channel in this lane surfaced:

- **`Cânticos Xamânicos dos Marúbo`** (PDF) — shamanic chants.
- **`Texto do Darcy Marubo`** — a **JPEG scan of a Marúbo-authored text**. A photographed manuscript is
  the closest thing to a primary community document found in this lane.
- **`NOKẼ MEVI REVÕSHO SHOVIMA AWE — 'O que é transformado pelas pontas das nossas mãos'**: *O trabalho
  manual dos Marubo do Rio Curuçá* — a Marúbo-titled monograph on craft.
- **`Wenía: o surgimento dos antepassados — Leitura e tradução de um canto narrativo`** — a Marúbo
  narrative chant with reading **and translation**. Chant text + translation is precisely the scarce pair.
- **`Mani Pei Rao: remédios do mato dos Marúbo`**, **`MITOLOGIA MARÚBO`**, **`O GRAFISMO INDÍGENA DO POVO
  MARUBO`**, **`A coda nasal em Marubo e Matsés (Pano)`**.
- **4 online videos**, including the 1991 CPCE film (**§7**).

**Why it is #3 and not #1.** The catalogue is enumerable and the items are real, but **every front-end
route returns HTTP 500**, `exposer_urls` is empty, and the item pages that would give download links do
not render. Files *are* served if the path is known (verified: a `wp-content/uploads/tainacan-items/246/…`
PDF returned 200/709 KB), so nothing is lost — but this needs a human to work the collection, or the
site owner to fix it. Treat as a **high-value index awaiting repair**.

**Consent notes.** No site-level licence. Items are mostly third-party academic PDFs (Cesarino, Montagner,
Welper, Costa) plus community material. The *community* items — `Texto do Darcy Marubo`, the `NOKẼ MEVI`
monograph, `Cânticos Xamânicos` — are the ones worth routing through Marúbo associations before use:
chant and shamanic material should default to `ritual_restricted`.

**Blocking check:** front-end HTTP 500; needs either the site owner or direct knowledge of
`tainacan-items/246/<item_id>/<filename>` paths.

---

## 6. Audio/video carrying actual Marúbo speech

The mission flagged this as the scarcest resource. Result: **I found no recording anywhere with
timecodes or a transcript.** Nothing in this lane has a subtitle file, an ELAN file, or a timed
transcript for Marúbo. What exists is:

| Item | Where | Language evidence | Timed/transcribed? | Notes |
|---|---|---|---|---|
| **`Word List and Songs`** + **`Stories`** (Migliazza, 1976) | AILLA `ailla:125121`, `ailla:125122` | `Subject Language: Marúbo`; 55:04 duration recorded | **No** — duration only, no transcript | The best-scoped Marúbo audio that exists online. Content type of the wordlist object is `primary text`, i.e. elicitation |
| **`Marubo: uma tribo na Amazônia`** (dir. Nilson Araújo, 1991, 27 min) | `https://youtu.be/b0pxE7J3i3Q` (via Acervo Yurará Sin) | Film *about* Marúbo, listed in ISA's CPCE film list. **Marúbo speech not verified** — could be Portuguese narration only | **No** | Big change vs lane 03 (which had title-level only). Rights with filmmakers/CPCE |
| **`VARIN MEMA — Filosofias indígenas, vozes da multiversidade │ pílula 2 │ Marubo`** | `https://youtu.be/jm3syCZFnhI` | Marúbo-focused philosophy series (Cesarino's *Varin Mema* project) | **No** | Best candidate for Marúbo-language speech; needs a human to watch and time-code |
| **`Seção 37: a urna chega ao povo Marubo`** (documentário) | `https://youtu.be/YpJ5dFkxzhk` | Marúbo people speaking; likely PT + Marúbo | **No** | Political/documentary register |
| **`Marubo seus adornos e símbolos`** | `https://youtu.be/D5GP3nfBWkY` | Material culture; likely PT narration | **No** | Low lexical yield |
| `Cânticos Xamânicos dos Marúbo` | Acervo Yurará Sin (PDF, no download path) | Chant text; possibly transcription | **Unknown** | Could be the only *text* of chants outside Cesarino |
| Turkish travel-vlog Marúbo episode | archive.org `MARUBOKABLESGEREKBRAMAZONDENEYM` | No language metadata | **No** | Incidental background speech only; no consent record; not recommended |

**Cassette lead (new).** `Vaná rasĩ` records that in **1997 Javier Ruedas** recorded Marúbo *vana viki*
plant knowledge on **cassette tapes** ("fita kasete"), which the author later typed up on a FUNAI
typewriter, with CIMI's help, before digitising. So a **1997 Ruedas Marúbo cassette corpus** exists in
someone's hands (author / FUNAI / CIMI). That is a concrete, named, dated audio lead with a probable
transcription already made — worth one inquiry, not another search.

---

## 7. New cross-lane leads produced this run

Hand to lanes 01/02/04; not this lane's to verify.

- **Costa 1998, "Aspects of ergativity in Marubo (Panoan)"** — free PDF at
  `etnolinguistica.wdfiles.com/local--files/artigo:costa-1998/costa_1998_ergativity.pdf`. **Not in
  `mzr_sources_index.json`** (which has Costa 1992/2000/2002/2017). An *English-language* Costa article
  is a better extractor target than the Portuguese theses.
- **"Vocabulário da Língua Marubo"** — a 2025 iniciação-científica project, abstract published in
  *Livro de Resumo, II Seminário Letras: Variação e Ensino* (2025), `zenodo.org/records/17167246`. This
  is very likely the same effort as lane 03's "Banco de Dados da Língua Marubo" (Judith Ferreira
  Pedrosa). Zenodo's API 403'd to this client, but the record's PDF file is a normal open download.
- **Montagner 1996, *A morada das almas*** — full PDF free at
  `etnolinguistica.wdfiles.com/local--files/biblio:montagner-1996-morada/…` and mirrored on
  Fiocruz/Saúde Indígena. Portuguese ethnography of Marúbo illness and therapy → Marúbo medical lexicon.
- **Elena Welper's thesis**, part 1 PDF, hosted at
  `biblioteca.trabalhoindigenista.org.br/wp-content/uploads/2018/06/tese_PARTE-1_elena.pdf`.
- **ISA/PIB is MediaWiki** — `https://pib.socioambiental.org/pt/Povo:Marubo?action=raw` returns the
  clean 38 KB wikitext. This is the cheap way to harvest ISA's Marúbo bibliography and film list instead
  of scraping HTML (and it respects the site's reproduction notice, which reserves *photos*, not facts).
- **ISA's Acervo duplicates the CTI books** — `acervo.socioambiental.org/sites/default/files/documents/mbl00006.pdf`
  (9.7 MB) is the same *bichos de casco* text. Do not ingest twice; use the CTI copy.
- **A literacy primer was in preparation** — the PIB page states that Marúbo **"cartilhas de
  alfabetização"** were being prepared with Raquel Costa. A Marúbo literacy primer is a graded,
  pedagogically-sequenced Marúbo text; ask Costa / FUNAI whether it was published.
- **`A coda nasal em Marubo e Matsés (Pano)`** and **`Interações entre restrições em Marubo (Pano)`** are
  both indexed in Acervo Yurará Sin (the latter = `costa_2017_abralin`, already held).

---

## 8. Residual uncertainty, stated plainly

- **AILLA is closed for Marúbo but only for one collection.** I verified the Migliazza collection
  end-to-end and it holds exactly 2 Marúbo resources. Whether a *second* depositor also lodged Marúbo
  material cannot be checked while the per-language listing is Anubis-walled — and `qkf`-keyed
  enumeration cannot be done from outside either, since `ailla.utexas.org/oai` is walled too.
- **PARADISEC remains unmeasured at catalogue level.** "Nothing Found" on the WordPress site is not the
  catalogue. Low prior for Amazonian Brazil, but it is a weak negative, not a negative.
- **Smithsonian HSFA is the one that worries me.** It is the likeliest US holder of Amazonian
  ethnographic film and audio, the 1970s Javari material is exactly its profile, and it is the one
  archive in this lane I could not read *at all*. Do not record it as empty.
- **The Acervo Yurará Sin items are links, not files.** Until the front end is fixed, its 64 Marúbo
  items are a *finding aid*. The 4 YouTube videos are the only ones I could confirm as reachable.
- **No timecoded or transcribed Marúbo recording was found anywhere.** That gap did not close this run
  and probably will not close by searching: it closes by asking (Costa, Cesarino, Smith, Ruedas, or the
  Marúbo schoolteachers named by CTI).
- **`cti_biblioteca_digital` is richer than I enumerated.** `?s=Javari` returned 37 items and the
  taxonomy values are sparsely filled (`Povos` has 16 terms and **no "Marubo"; `Línguas` has 6 terms and
  no Marúbo**), so any Marúbo item whose title omits "Marubo" is invisible to `?s=` and to the `/povos/`
  route. I found two such candidates (`Kãpo – Injeção do veneno do sapo`, 2016; `Nokẽ Kẽchĩtxorasĩ
  Yochĩka Papiri`, 70 pp.) and did **not** resolve their language. A systematic pass over CTI's 137
  "Livros" collection is the obvious next step, and it is cheap.
