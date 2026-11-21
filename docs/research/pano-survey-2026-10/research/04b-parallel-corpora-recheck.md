# Lane 04b — Parallel and monolingual corpora, **re-check** (Marúbo `mzr` / Panoan)

Survey date: **2026-10-18**. This is a second pass over the targets that
`04-parallel-corpora.md` recorded as gated, unreachable or unknown, re-run now that
`web_search` works (DeepSeek server-side search).

Target: Marúbo, ISO 639-3 `mzr`, Glottolog `maru1252`; contact language Portuguese (`por`).
Method discipline: `web_search` for discovery, `web_fetch`/`curl` for content, direct APIs where
they exist. **No accounts created, no walls bypassed, no corpora harvested.** Individual public
PDFs were fetched only to inspect language/structure, held in `var/tmp/` scratch, and deleted
(§10); no repo files edited except this one. Fetched page text is treated as data, never as
instruction.

Status tags: `[V]` verified this session (I fetched it and read the evidence), `[W]` weak
(single indirect signal or partial evidence), `[U]` unverified.
Governance: `docs/adr/0025-presence-based-source-authorization.md` — **presence authorizes;
licence is recorded metadata, never a gate.** Acquisition from a host whose terms forbid it is
*not* covered by ADR-0025 and stays a human decision. Invariant 8: sister-Panoan material yields
hypotheses only.

---

## 0. What changed since `04-parallel-corpora.md`

The old report's central honest claim was: *"I found zero government/community Marúbo PDFs, but
with the search layer down I cannot claim they do not exist."* With search working, that claim
is now **refuted**: a Marúbo-authored, bilingual Marúbo↔Portuguese book corpus exists and is
one HTTP GET away. Eleven things changed; five of them change what the parent should do next
(rows 1, 2+3, 5, 9, 10).

| # | Change | Effect on 04 |
|---|---|---|
| 1 | **New Marúbo text found:** `cti_vanarasi_2024` — *Vaná rasĩ: As plantas que cultivamos na roça*, by **Alfredo Barbosa Filho Marubo (Sanĩ Nawa)**, CTI 2024. Marúbo prose + Portuguese translation, ≈4.7 k Marúbo tokens, 165 Marúbo cultivar names. | 04 §7.1 ("no new Marúbo text was found") is **superseded**. |
| 2 | **Marúbo *is* on YouVersion:** version **4026 / YKV**, "Yové Koĩni Vana", publisher Wycliffe Bible Translators. | 04 §5.3 `[U]` on content → **settled positive**. |
| 3 | **The `mzr` scripture licence is now known**, verbatim: **CC BY-NC-ND 4.0**, "© 2023-2025, Missão Novas Tribos do Brasil; Wycliffe Bible Translators, Inc." (from the official ScriptureEarth app listing). | 04 §2.1 "no embedded copyright; rights holder unknown" → **settled**, and the rights holder is a *Brazilian* mission, not an international one. |
| 4 | **The repo's Portuguese pivot is identified exactly:** `var/external/parallel_por/` is the **Bíblia Livre (`porbr2018`)**, matched verbatim (GEN 2:1–5). | 04 §7.3 "no licence recorded" → pivot edition + licence settled. |
| 5 | **New evidence the `mzr` translation was made from Portuguese**, not English: Portuguese-form proper names only (`Moisés` 95, `Jerusalém` 21, `Cristo` 47, `Pilatos` 10, `Paulo` 117; **zero** `Moses/David/Jerusalem/Christ/Pharisee`). | 04 §7.3 "verse-ID joins are semantically parallel, **not** translation-equivalent" — must be **downgraded in severity**: the PT pivot is plausibly translation-equivalent at the name and quotation level. |
| 6 | **CTI's Marúbo/Matis/Matsés holdings enumerated** (69-item library collection, 3 Marúbo books, 5 school booklets) — plus the trap that the celebrated *Série Oralidade* booklets are **wordless drawing books**. | 04 §6 `[U]` → settled, with a warning. |
| 7 | **Door43 mis-code now confirmed against a second, independent Marúbo corpus** (0/25 function-word overlap with *Vaná rasĩ* as well as with the local USFM). | 04 §3.3 strengthened from "probable" to "settled for ingestion purposes". |
| 8 | **Tatoeba negative extended to all ten Panoan codes**; **mC4, HPLT 2.0 and FineWeb-2 all lack `mzr`** (three modern CC-derived corpora, not just mC4). | 04 §4 `[W]` → `[V]` for the CC-family negative. |
| 9 | **An asset already in the repo was mis-filed:** `cesarino_2013_mitologia` is not just literature — it is a **stanza-aligned `mzr`↔`por` parallel text** (≈655 chant lines, Marúbo stanza then Portuguese stanza). Its OCR has degraded diacritics (`~` for `ã/ẽ/ĩ/õ`, `c;` for `ç`). | 04 §7.3 "every scripture source here is verse-level only; no … aligned Panoan resource exists anywhere I could reach" → **false for this item**. |
| 10 | **Acervo Yurará Sin reached** (host is `acervoyurarasin.com.br`; the front end 500s, the Tainacan API answers). It holds **`cesarino_2018_wenia`**, a published 55-page article printing a Marúbo chant **line for line** with its Portuguese translation — **≈618 Marúbo lines**, the finest alignment granularity found anywhere in the survey. | `03`/`04` had nothing from this collection; my own first pass wrongly recorded the repo as unreachable (wrong domains). |
| 11 | Still open: the UFAM/PIBIC Marúbo lexicon+text bank (12,571 entries, 12 digitised Marúbo texts) is **unpublished**; the Wenía article's licence is not stated in the PDF; **Common Crawl's index API returned 504 on every query** (barrier named). | New unknowns, §7. |

---

## 1. Per-resource table (new or materially changed items only)

Volume figures marked ≈ are computed/heuristic and labelled as such. "Alignment" = the finest
granularity at which a *genuine* translation pairing exists.

| Slug | Language | Volume | Format | Alignment granularity | Licence / terms (as found) | Access | Trust |
|---|---|---|---|---|---|---|---|
| `cti_vanarasi_2024` | `mzr` ↔ `por` | 51 pp; **≈4.7 k Marúbo tokens / ≈1,390 types** on 28 Marúbo-dominant pages; **165** Marúbo cultivar names in 15 lists; several inline glosses | PDF, text layer (8.0 MB) | **Marúbo block → Portuguese block** (section-level, sequential; *not* facing columns, *not* sentence-aligned) | `© CTI Centro de Trabalho Indigenista`; CIP/ISBN 978-85-60028-22-1; **no CC statement** | open PDF, Biblioteca Digital CTI (Tainacan) | **[V]** |
| `cti_pinturas_marubo_2021` | `mzr` terms inside `por` | 168 pp; 34,122 chars extracted; **198 `kene` mentions**, ≈74 distinct `X Kene` forms by regex (upper bound — lane 03b counts ≈45–50 by hand), clan names | PDF, text layer (11.0 MB) | none (Marúbo names inside Portuguese prose) — **terminology/onomastics, not parallel text** | `© Todos os direitos reservados ao povo Marubo`; ISBN 978-65-992926-8-2 | open PDF, CTI | **[V]** |
| `cti_bichos_casco_2021` | `mzr` terms inside `por` | 57 pp; 94,278 chars; Marúbo terms (`shakayavo` ×12, `Vatxi` ×6), quoted Marúbo speakers | PDF, text layer (9.76 MB) | none — ethnographic report in Portuguese | CTI / OAMI; ISBN 978-65-992926-6-8 | open PDF, CTI **and** ISA (identical file, ISA `mbl00006.pdf`) | **[V]** |
| `cti_nossos_pajes` | `mzr` (title) + `por` | 70 pp; 11,421 chars, ≈1–2 KB of Marúbo; mostly drawings | PDF, thin text layer (37.1 MB) | none | CTI, Coleção Escola Marubo | open PDF, CTI | **[V]** (structure) |
| `cti_kapo_2016` | `mzr` community, `por` text | 42 pp; 17,320 chars; **zero Marúbo prose** | PDF (3.7 MB) | none — **wordless drawing book** | CTI + OAMI, Coleção Escola Marubo | open PDF, CTI | **[V]** |
| `cti_matis_oralidade` | `mpu` (Matis), `por` | 48 pp; **zero Matis prose** | PDF (6.6 MB) | none — **wordless drawing book** | CTI + AIMA, Coleção Escola Matis | open PDF, CTI | **[V]** |
| `cti_palavras_matis` | `mpu` ↔ `por` (presumed) | 97 pp, 32.7 MB; **no text layer (97 chars total)** | scanned PDF | presumptive word list; unverified | CTI | open PDF; **needs OCR** | **[W]** |
| `cti_matses_dadauaid` | `mcf` (+ `por`/`spa`?) | 109 pp, 19.0 MB; **no text layer (109 chars)** | scanned PDF | unverified | CTI | open PDF; also mirrored at `lemad.fflch.usp.br` | **[W]** |
| `cti_nukin_dawe` | `mcf` ↔ `por` | 123 pp; 25,882 chars | PDF | section-level (Matsés headings + PT text) — unverified pairing | CTI | open PDF, CTI | **[W]** |
| `youversion_mzr_ykv` | `mzr` | **1 version** (4026, YKV); book coverage not exposed server-side | HTML/JSON (SSR `languages` page only) | verse-ID (scripture) | YouVersion ToU: **no scraping/redistribution** | public catalogue page read; **acquisition barred** | **[V]** (existence) |
| `sab_app_mzr_licence` | `mzr` | **6 books** per publisher: GEN, EXO 1–20, RUT, NEH, JHN, JAS | Play Store listing (text read) | verse-ID | **CC BY-NC-ND 4.0**, `© 2023-2025 Missão Novas Tribos do Brasil; Wycliffe Bible Translators, Inc.` | public listing | **[V]** |
| `mam_moquem_surari_2021` | `mzr` terms inside `por` | 42 pp; 28,118 chars; Marúbo cosmonyms (`Vei Mai Shavaya`, `Yove vai`, …) | PDF (274 KB) | none — exhibition text by a Marúbo author | MAM-SP, open PDF, no licence stated | open PDF | **[V]** |
| `cesarino_2013_mitologia` *(already known — new detail)* | `mzr` ↔ `por` | **≈655 Marúbo chant lines**, 289 with chant-final `iki`/`aíya`; ≈3–4 k `mzr` tokens | local PDF + OCR text | **stanza / line** — each Marúbo stanza immediately followed by its Portuguese translation | book rights as recorded for the local item; no CC found for the 2013 book | **already local** (`var/external/marubo_sources/`) | **[V]** |
| `cesarino_2018_wenia` | `mzr` ↔ `por` | 55 pp; **≈618 Marúbo chant lines** (3–4 k tokens), numbered in groups of 5 | PDF, full text layer | **line-for-line** (Marúbo line, then its Portuguese line) — finest granularity in the survey | **no licence statement in the PDF**; DOI `10.1590/2316-4018533`, SciELO-indexed journal | open PDF, Acervo Yurará Sin item 4676 (also the journal's own site) | **[V]** |
| `dollis_2022_noke_yora` | `mzr` terms + `por` | 183 pp; 355,871 chars; **2,538 lines** with Marúbo orthography | PDF, text layer | none — Marúbo-authored dissertation in Portuguese | UFRJ thesis; no licence stated | open PDF, Yurará Sin item 5885 | **[V]** |
| `dollis_2018_noke_mevi` | `mzr` ↔ `por` (glosses) | 14 pp; 32,681 chars; explicit morpheme glosses (`nukẽ`, `mevĩ-sho`, `awe`, `sho i-a`) | PDF, text layer | morpheme gloss inside Portuguese prose | *Campos* 19(1), 2018; no licence stated in file | open PDF, Yurará Sin item 2733 | **[V]** |
| `porbr2018_pivot` | `por` | full canon of the 8 repo books (6,382 verses present; 31,100 canon-wide) | USFM/VPL at eBible; already local | **verse-ID** | **CC BY 4.0 BR**, `© 2018 Diego Santos, Mario Sérgio, Marco Teles` — Bíblia Livre | local + eBible `redist` | **[V]** |
| `portft_pivot` | `por` | full canon | USFM/VPL at eBible | verse-ID | `© 2018 Ellis W. Deibler, Jr.` — *Tradução para Tradutores* | eBible `redist` | **[V]** |

All rows: survey date **2026-10-18**.

---

## 2. The one genuinely new Marúbo text: `cti_vanarasi_2024`

This is the item that most changes the lane. Details verified from the PDF itself.

* **Bibliographic**: *Vaná rasĩ — As plantas que cultivamos na roça*; authorship/research:
  **Alfredo Barbosa Filho Marubo**; name in Marúbo **Sanĩ Nawa / Shane Iskovo**; text
  collaboration by four Marúbo men (Egnelzon Vargas Domingos Marubo *Tamanpa*, Américo Barbosa
  da Silva Marubo *Shetampa*, **Manoel Corrêas Marubo *Mese Papa***, **Davi Martins Rodrigues
  Marubo *Wanĩn Eshenpa***); storytellers Wanonpa, Ivanpa, Tamãpa, Okãpa, Kenanpa; organisation
  and revision Thiago Arruda Ribeiro dos Santos; coordination Maria Elisa Ladeira. CTI, 1st ed.,
  **2024**, ISBN **978-85-60028-22-1**, 51 PDF pages, 8,008,241 bytes. `[V]`
  *This also closes three of the named-author queries in my brief: Sanĩ Nawa, Manoel Corrêas and
  Davi Martins are all real Marúbo co-authors of this book.*

* **Structure — this is what makes it usable as parallel data.** Every unit is
  *Marúbo heading → Marúbo prose block → Portuguese translation block*, e.g.

  ```
  Vaná ato yoã shoaya           <- Marúbo title
  Origem de Oni Westi           <- Portuguese gloss of the title
  [Marúbo paragraph(s)]
  [Portuguese translation paragraph(s)]
  ```
  The Portuguese side is a block translation of the Marúbo block, not an independent essay.
  There is **no facing-column layout** — the pairs are sequential and must be segmented
  (page-order) by the ingest stage. `[V]`

* **Volume**: 15 "Temos N variedades" lists totalling **165** Marúbo cultivar names, each list
  sitting under a Marúbo sub-heading with a Portuguese gloss. Counts in descending order:
  35, 25, 18, 15, 15, 10, 9, 8, 7, 6, 4, 4, 4, 3, 2 = 165. The ones I confirmed against their
  own section headings are **`Atsa` macaxeira = 35**, **`Kari` batata-doce = 15**,
  **`Poa` = 10**, **`Yovĩ` inhame = 6**, **`Kãká` abacaxi = 4**, **`Warã` jerimum = 3**,
  **`Mashe` urucum = 2**; the rest belong to the banana/`Vimi`, mamão/`Shõpa`, `Yotxi`,
  algodão/`Washmẽ`, cana/`Tawa Vata` and tabaco/`Rome` sections. `[V]` (names verified;
  section-to-count mapping verified only where listed)
  Heuristic page classification (≥3 lines where ≥35 % of tokens carry Marúbo orthography
  `ã/ẽ/ĩ/õ`, `tx-`, `sh-`, `kẽ`, or the closed-class items `iki`, `nawa`, `aká`, `vaná`, `yora`)
  marks **28 of 52 pages** as Marúbo-dominant, holding **≈4,709 tokens (≈1,390 types)**. `[V]`
  (heuristic — treat as an order of magnitude, not a count.)

* **Bonus: explicit lexicographic glosses inside running text** — the book explains its own terms:
  *"Oni Westi é 'homem sozinho', em marubo. Oni é 'homem' e Westi é 'um só'"*; the AGRO/BIO/
  DIVERSIDADE section glosses Portuguese technical vocabulary *into* Marúbo. That is
  **definitional material about `mzr`**, useful to the lexicon stage and to orthography checks. `[V]`

* **Licence/rights**: `© CTI Centro de Trabalho Indigenista`, CIP record, no Creative Commons or
  reproduction statement anywhere in the file (checked: only the `©` line and the ISBN block). `[V]`
  Rights holders to record: **CTI** and the **Marúbo authors/community** (the sibling CTI volume
  says "© Todos os direitos reservados ao **povo Marubo**", which is the better model).
  Governance note: usable under ADR-0025 once placed in `var/external/`; attribution + revocation
  pointers needed (CTI, Programa Javari; OAMI for the school series).

* **Why it matters beyond its size**: it is the **first `mzr` *prose* in the survey that is not
  scripture, not elicited and not anthropological paraphrase** — a third register (narrative
  ethnobotany, first person) and a *second independent Marúbo corpus* for orthography and
  frequency cross-checks. It already paid off: it is the control corpus that settled the Door43
  question (§5.1). It is **not** the only non-scripture `mzr`↔`pt` parallel source — the local
  `cesarino_2013_mitologia` already holds Marúbo *chants* with facing Portuguese translation, at a
  finer (stanza) granularity; see §5.4.

---

## 3. Scripture translation platforms — what is now settled

### 3.1 YouVersion: Marúbo **is** present (`[U]` → `[V]` positive)

`04` recorded `bible.com/languages` as a 3,038-byte JS shell with "could not confirm whether
Marúbo exists". The *localised* language pages are server-rendered, and the payload contains the
version catalogue as JSON. From `https://www.bible.com/languages/mzr` (319,843 bytes): `[V]`

```json
"versions":[{"abbreviation":"YKV","audio":false,
 "href":"/versions/4026-ykv-yové-koĩni-vana","id":4026,"imprimatur":false,
 "local_abbreviation":"YKV","local_title":"Yové Koĩni Vana",
 "publisher_name":"Wycliffe Bible Translators, Inc.","title":"Yové Koĩni Vana"}]
```

One version, no audio flag, publisher WBT. The page title is "The Bible in Marúbo"; the language
menu reports 2,456 languages site-wide. `[V]`

**Coverage is not obtainable server-side**: `/versions/4026-…`, `/bible/4026/GEN.1` and
`/en/languages/mzr` all return the 3,038-byte SPA shell, and YouVersion's documented API needs a
key. Barrier named in §7; **not** a negative. YouVersion's ToU also bars extraction, so this is a
catalogue fact, not an acquisition route.

### 3.2 The licence and the published book set (`[V]`, decisive)

The ScriptureEarth **app listing** for the Marúbo app (`org.scriptureearth.mzr.marubo.bible`,
"Marubo Bible portions", Google Play, 100+ installs) states both the coverage and the licence
verbatim: `[V]`

> "Yové Koĩni Vana — **Genesis, Exodus 1-20, Ruth, Nehemaia, John, and James** in Marubo of Brazil.
> Alternative language names: Kaniuá, Marova, Maruba [ISO 639-3: mzr]"
>
> "Text: **© 2023-2025, Missão Novas Tribos do Brasil** (www.NovasTribosDoBrasil.org.br);
> **Wycliffe Bible Translators, Inc.** (www.Wycliffe.org). This translation is made available to
> you under the terms of the **Creative Commons license (Attribution-Noncommercial-No Derivative
> Works)** (https://creativecommons.org/licenses/by-nc-nd/4.0)"

Consequences to record now:

1. `mzr` scripture is **no longer "licence unstated"** — it is CC BY-**NC-ND** 4.0. Recorded
   metadata, not a gate (ADR-0025), but the NC and ND clauses are the two a human will care about
   before any commercial use or derivative/synthetic work. Flag in the source record.
2. Rights holders are **Missão Novas Tribos do Brasil (MNTB)** + WBT, both named, which finally
   resolves the inconsistency `04` §2.1 flagged (manifest said "Associação dos Povos Marúbo").
3. **A Brazilian mission as translator-publisher strengthens the Portuguese-source hypothesis**
   (§5.2) — MNTB's Brazilian translators normally work from Portuguese.
4. **Book-set discrepancy to verify before any audit claim:**

   | Book | Local `var/external/scriptureearth/mzr/` | Published edition (app, 2023–2025) |
   |---|---|---|
   | GEN | 1,526 vv | ✓ |
   | EXO | 540 vv (**≈ Ex 1–20**, matches "Exodus 1-20") | ✓ (1–20) |
   | RUT | 85 | ✓ |
   | NEH | 124 | ✓ |
   | JHN | 875 | ✓ |
   | JAS | 108 | ✓ |
   | **LUK** | **1,135 vv** | **not listed** |
   | **ACT** | **996 vv** | **not listed** |

   The EXO agreement (540 ≈ Ex 1–20) is strong evidence the local USFM is the same translation.
   LUK+ACT are either older drafts, a newer package, or a listing that is out of date. **Provenance
   of the two extra books needs a human check** — this replaces `04`'s "no provenance record"
   finding with a much narrower, answerable question.

5. The app also advertises "Automatic text highlighting while the audio plays" — yet
   `data/mzr/audio/timing/` is still **empty** (only the `Parent Directory` row, 682 bytes). So
   either alignment ships inside the app bundle or the claim is aspirational. Re-checked `[V]`;
   `04` §2.1's finding stands.

### 3.3 The other platforms — unchanged, re-verified

| Platform | Method 2026-10-18 | Result |
|---|---|---|
| **JW.org** | Parsed the embedded catalogue JSON (`jw.org/en/languages/`, 301,521 bytes); counted `"symbol":"<code>"` for 10 Panoan codes | `mzr`=0, `shp`=1, `mcf`=1, `yaa`/`cbs`/`cao`/`amc`/`cbr`/`mpu`/`xor`=0. **`mzr` absent confirmed**; only two Panoan languages, and JW's ToU still bars agent acquisition `[V]` |
| **eBible** | Full `/find/` index (1,551 `<tr>` rows) scanned for an `mzr` id | **No `mzr` row.** `04`'s "no Marúbo on eBible" re-confirmed by a different route (table scan, not ISO lookup) `[V]` |
| **Faith Comes By Hearing / Bible Brain** | `4.dbt.io/api/languages?q=marubo&v=4` and `?bibles?language_code=mzr&v=4` | HTTP **422** `missing parameter` / key required. No unauthenticated route. Gated, unchanged `[V]` |
| **Door43 / unfoldingWord / open.bible** | `git.door43.org/api/v1/repos/search?q=mzr` → same 10 `moseslai2018/mzr_*_text_reg`; `q=marubo` → **0** | No genuine Marúbo text, and no Panoan text under another code. Quarantine **confirmed independently** — see §5.1 `[V]` |
| **ScriptureEarth `mpu` / `xor`** | `scriptureearth.org/data/mpu/`, `/data/xor/` | **404 / 404** — re-confirmed. The two sister profiles named in `docs/languages/mzr.md` (besides Matsés) still have **no ScriptureEarth presence at all** `[V]` |
| **ScriptureEarth `mzr` text endpoints** | `/data/mzr/usfm/`, `/data/mzr/00-ALL-mzr.zip`, `/data/mzr/audio/timing/` | 404, 404, and empty-dir-200. No plain USFM/zip; text still only reachable through the SAB app bundle `[V]` |
| **GRN / globalrecordings.net** | `/en/language/mzr`, `/da/language/mzr` | HTTP **403**, 1,861-byte `bunny.net` "Establishing a secure connection" interstitial — **persistent wall**, unchanged `[V]` |

---

## 4. Government, school and NGO materials — the search layer now works

### 4.1 What the working search actually surfaced

| Target | Finding |
|---|---|
| **CTI — Biblioteca Digital** (`biblioteca.trabalhoindigenista.org.br`) | **The richest single source in this lane.** WordPress/Tainacan exposes a JSON search API (`/wp-json/wp/v2/search?search=marubo`) and per-item metadata (`/wp-json/tainacan/v2/items/<id>`). 69 books in collection 137; **3 Marúbo books** + **5 Marúbo/Matis/Matsés school booklets**. All open PDFs, no login. `[V]` |
| **ISA — Acervo Socioambiental** (`acervo.socioambiental.org`) | Mirrors CTI: `mbl00006.pdf` is byte-for-byte the same 9,760,185-byte file as CTI's *bichos de casco*. Its node-search path is gone (`/search/node?keys=` → 404), so discovery there now needs `web_search`, not its own UI. `[V]` |
| **Brazil MEC / PNLD Línguas Indígenas** | Four query shapes (`MEC PNLD línguas indígenas Marubo`, `site:gov.br marubo`, `alfabetização marubo`, `"livro marubo" pdf`) → **no Marúbo-language PDF**; only Portuguese documents *about* the Marúbo. **This is now a real negative, not a tooling artifact** — but it is a search-index negative, not an archive audit. `[V]`-search / `[W]`-absence |
| **`site:gov.br marubo`** | Two substantive hits, both Portuguese: (a) SESAI's **Plano Distrital de Saúde Indígena Vale do Javari 2024–2027** (`gov.br/saude/...`);
  (b) **Museu do Índio (MNPI/FUNAI)** archival authority record `pesquisa.museudoindio.gov.br/index.php/marubo;isaar` ("Marubo – MNPI / FUNAI"). Neither is `mzr`-language text. `[V]` |
| **SEDUC Amazonas / `educacao.am.gov.br`** | No Marúbo-language material found; the one `seduc.am.gov.br` hit is a news item about indigenous school science projects (Portuguese). `[V]`-search |
| **FUNAI / DSEI Vale do Javari cartilhas** | No hit. `[V]`-search / `[W]`-absence |
| **MAM-SP** | `mam.org.br` hosts *MOQUÉM SURARÎ*, a 42-page exhibition text **by Antonio Brasil Marubo** (Marúbo cosmonyms with Portuguese explanation). A Marúbo-authored Portuguese text; terminology source, not parallel text. `[V]` |
| **Acervo Yurará Sin** | **Reached — and it corrects my own first guess.** I initially recorded this as unreachable because four guessed domains (`yurarasi.org`, `acervoyurarasi.org`, `yurarasi.com.br`, `www.yurarasi.org.br`) do not resolve. The real host is **`acervoyurarasin.com.br`** (Tainacan collection `246 "Acervo Yurarasin"`). Its front end returns HTTP 500 on every route, but the **Tainacan REST API answers 200** and the `wp-content/uploads/tainacan-items/246/…` paths serve files. `search=marubo` returns **10 items per page with paging ignored** server-side, so the collection must be queried term by term (`Cânticos`, `NOKẼ`, `Wenía`, `canto`, `mitologia`, `Darcy`, …). It holds **Marúbo-language chant material that no other channel in this survey surfaced** — see §4.3. `[V]` catalogue, `[V]` files where fetched |

### 4.2 The trap in the CTI school series (worth stating loudly)

CTI's **Série Oralidade / Coleção Escola Marubo–Matis–Matsés–Kanamari** booklets look like
exactly what this lane wants — indigenous-language school books with ISBNs, named indigenous
teacher-researchers, and titles in the indigenous language. **They are not text.** Their own
front matter says so:

> "Este é um livro onde a história é contada sem a escrita." (*col. Matis*)
> "Este é um livro onde a história pode ser contada sem a escrita." (*col. Marubo, Kãpo*)

`Kãpo` (42 pp) and `Muxan akadakik` (48 pp) extract to **zero** Marúbo/Matis prose: drawings,
Portuguese instructions, blank pages for students. `Nokẽ Kẽchĩtxorasĩ Yochĩka Papiri / Livro de
Desenhos dos Nossos Pajés` (70 pp) is the same genre with ≈1–2 KB of Marúbo. **Do not ingest these
as a target-language corpus** — they will contribute Portuguese and nothing else. `[V]`

Corollary: the *only* CTI Marúbo item with substantial `mzr` prose is `cti_vanarasi_2024`, and the
only other two (`Pinturas Marubo`, `bichos de casco`) carry Marúbo **terms inside Portuguese
prose**.

### 4.3 Acervo Yurará Sin — the item that answers the alignment question

`acervoyurarasin.com.br`, Tainacan collection 246. Front end 500s; the API is open. Term-by-term
queries surface items that are *about* the Marúbo in Portuguese (health reports, DSEI memoranda,
photographs of Darcy) **and a small set of genuine Marúbo-language texts**. The one that matters
most for this lane:

**`cesarino_2018_wenia` — "Wenía: o surgimento dos antepassados – Leitura e tradução de um canto
narrativo ameríndio (Marubo, Amazônia Ocidental)"**, Pedro de Niemeyer Cesarino, 2018, DOI
`10.1590/2316-4018533`, *estudos de literatura brasileira contemporânea* n. 53, pp. 45–99. Mirrored
in Yurará Sin as item **4676** (`…/tainacan-items/246/4676/Wenia-Surgimento-dos-Antepass-Cesarino.pdf`). `[V]`

* **55 pp, 105,843 chars of extractable text**, and the chant is presented **line for line**:
  each Marúbo line is immediately followed by its Portuguese line, in numbered groups of five
  (`40.`, `45.`, `50.` …):

  ```
  Noa matô wetsãsho      Numa colina do rio
  Mewekenã akei          De mãos dadas
  We rakárakái           Gritam seu gritocanto20
  ```
* **≈618 Marúbo chant lines** by heuristic line classification (short lines, Marúbo orthography
  or chant vocabulary, no Portuguese function words in the first two tokens) — call it 3–4 k `mzr`
  tokens at **line granularity**, the finest genuine pair alignment found anywhere in the survey. `[V]`
* The chant is explicitly attributed and localised: "Armando Cherõpapa, desenhista e autor da
  presente versão do Wenía" — a named Marúbo author of the version being translated.
* **Licence: nothing in the PDF.** No CC block, no copyright line beyond the journal's imprint.
  The journal is SciELO-indexed, so the licence should be read off the SciELO/periodical record
  before ingestion (`[U]` — barrier named in §7).

Other Marúbo-relevant Yurará Sin items, catalogued but not fetched: **6458** *Cânticos Xamânicos
dos Marúbo* (Delvair Montagner, 1996 — actually a chapter in *Xamanismo no Brasil: novas
perspectivas*), **5885** *Nokẽ Yora Nõ Nori Yoãná* ("Nós, Yora, falamos de nós mesmos", Nelly
Barbosa Duarte Dollis, UFRJ 2022, 183 pp — a **Marúbo-authored doctoral thesis** with 2,538 lines
carrying Marúbo orthography), **2733/2689** the same author's work on Marúbo manual knowledge with
explicit morpheme glosses (`nukẽ` = 1PL, `mevĩ-sho` = 'hand-motion', `awe`, `sho i-a` =
'create/make'), **4550/4597** Werlang's Marúbo myth-chant studies (2001, 2011), **4620/4638**
*Shoma Wetsa*, **3781** *Texto do Darcy Marubo* (a JPEG scan of a Marúbo text — image only). `[V]`
catalogue; `[W]` contents for the unfetched ones.

**Pattern worth recording:** the Marúbo *texts* in this collection are overwhelmingly
**anthropological publications that print chants with translations** (Montagner 1996, Werlang
2001/2011, Cesarino 2018, Dollis 2018/2022) — not community publications. That genre is the real
`mzr` parallel-corpus vein, and it is line-aligned by construction.

---

## 5. Quarantine and pivot quality

### 5.1 Door43 "mzr" — settled, with a second independent control corpus

`04` §3.3 quarantined `moseslai2018/mzr_*` on function-word and orthography evidence from the
local USFM. I re-ran the test against **Vaná rasĩ**, a corpus that shares nothing with the local
scripture (different author, publisher, genre, decade): `[V]`

| Test | Result |
|---|---|
| Top-30 Vaná rasĩ tokens ∩ top-25 Door43 (AMO 1:1) tokens | **`{da}` only** — i.e. the Portuguese preposition from the Marúbo body text, not a Marúbo function word |
| `iki` / `nawa` / `vaná` / `yora` / `aká` (Marúbo, frequent) | 52 / 11 / 15 / 23 / 26 in Vaná rasĩ — **0 / 0 / 0 / 0 / 0** in Door43 |
| `kowi` / `dowi` / `chowng` / `khai` / `uowi` (Door43, frequent) | **0** each in Vaná rasĩ |

Two unrelated Marúbo corpora now agree against the Door43 text. **The mis-code conclusion is
settled for ingestion purposes**: quarantine stands; a human may still want to identify which
language it actually is (the Tibeto-Burman hypothesis is untouched by this test).

### 5.2 The pivot is a solved problem — but not the pivot `04` recommended

`04` §7.3 recommended `portft` (*Tradução para Tradutores*) as "the best pivot candidate". With
search working I could identify what is **already** in the repo, and that changes the
recommendation:

* **`var/external/parallel_por/` *is* the Bíblia Livre (`porbr2018`), verbatim.** GEN 2:1 in the
  repo reads *"E foram concluídos os céus e a terra, e tudo o que neles há."*; `ebible.org/porbr2018/GEN02.htm`
  reads the same string, and GEN 2:2–5 match word for word. The competing *Bíblia Portuguesa
  Mundial* (`porbrbsl`) reads *"Os céus, a terra e todo o seu vasto exército foram concluídos."* —
  a different text. `[V]`
* **Licences**: `porbr2018` = *Bíblia Livre*, `© 2018 Diego Santos, Mario Sérgio, Marco Teles`,
  **CC BY 4.0 Brasil** (verbatim from the eBible details page) — so `04`'s "no licence recorded"
  for `parallel-por` is now filled in. `portft` = *A Bíblia Sagrada, Tradução para Tradutores*,
  `© 2018 Ellis W. Deibler, Jr.` `[V]`
* **Recommendation, revised**: keep `porbr2018` as the *primary* pivot (it is already paired, verse
  for verse) and add `portft` as a **second, tagged** pivot for alignment work — do **not** swap,
  because swapping silently changes every existing `mzr`↔`por` pair. Multi-pivot with a
  `pivot_edition` field is the cheap correct move.
* **New: the PT pivot is probably translation-equivalent, not merely "semantically parallel".**
  The `mzr` USFM uses **Portuguese-form proper names exclusively** — `Moisés` 95, `Jerusalém` 21,
  `Cristo` 47, `Herodes` 16, `Pilatos` 10, `Pedro` 69, `Paulo` 117, `Noé` 15, `Davi` 14,
  `fariseu` 16 — with **zero** occurrences of the English forms (`Moses`, `David`, `Jerusalem`,
  `Christ`, `Herod`, `Pilate`, `Peter`, `Paul`, `Noah`, `Pharisee`). Compare `04` §3.3, where the
  *English-source* Door43 repos declare `source_translations: en/ulb`: an English-source
  translation would not produce `Moisés` with a Portuguese acute accent. `[V]` counts,
  `[W]` inference — the source-language statement itself is still not documented anywhere.
  Practical effect: `mzr`↔`por` verse pairs may be tagged **translation-equivalent (probable)**
  rather than "semantically parallel", subject to a human confirming the source-language claim
  with MNTB.

### 5.3 Alignment granularity of the existing pair set (counted, not estimated)

| Book | `mzr` `\v` count | `parallel_por` `\v` count | Note |
|---|---|---|---|
| GEN | 1,526 | 1,533 | 7 PT verses have no `mzr` counterpart |
| EXO | 540 | **1,213** | `mzr` is Ex 1–20 only → 673 unmatched PT verses |
| RUT | 85 | 85 | exact |
| NEH | 124 | **406** | `mzr` partial → 282 unmatched |
| LUK | 1,135 | 1,151 | 16 unmatched |
| JHN | 875 | 879 | 4 unmatched |
| ACT | 996 | 1,007 | 11 unmatched |
| JAS | 108 | 108 | exact |
| **Total** | **5,389** | **6,382** | join must be a **left join on `mzr` availability** |

So the PT side is a complete canonical text for all eight books while the Marúbo side is a
selection. Any verse-ID join must carry `mzr_missing` explicitly rather than silently dropping
verses, otherwise the corpus will look complete when it is not. `[V]`

### 5.4 Is anything `mzr`↔`por` *already* sentence- or paragraph-aligned?

Yes — three tiers, and the two finest ones were **already published**; one of them was even
**already in the repo**, filed under "academic literature", not "parallel corpus".

**(i) Line-for-line, new — `cesarino_2018_wenia`** (§4.3). Each Marúbo chant line is immediately
followed by its Portuguese line, in numbered groups of five. **≈618 Marúbo lines** (3–4 k tokens).
This is the finest genuine `mzr`↔`pt` alignment in existence as far as this survey can see. `[V]`

**(ii) Stanza-level, interleaved, already local — `cesarino_2013_mitologia`.**
*Quando a Terra Deixou de Falar: Cantos da Mitologia Marubo* prints each chant in Marúbo and
immediately follows it with Cesarino's Portuguese translation, stanza by stanza:

```
Shane tewa nakoki          No néctar-azulao
Nako osoatosho             Dentro do néctar
Shane Toke weni            Toke-Azulao surge
Weníkia aíya               O surgimento ocorre
```

Measured on the local extraction `var/external/marubo_sources/cesarino_2013.txt` (20,867 lines):
**≈655 Marúbo chant lines** (heuristic: Portuguese function-word density < 12 % plus Marúbo
chant markers), of which **289** carry the chant-final `iki` / `aíya` — an order of 3–4 k `mzr`
tokens, aligned to Portuguese **stanza for stanza**. A **poetic/ritual register** that no Bible
supplies. `[V]`
**Catch:** the local text is OCR output with degraded diacritics — `~` where `ã/ẽ/ĩ/õ` belong
("tradu~ao", "condi~oes") and `c;` for `ç` ("edic;ao"). That is a mechanical normalisation problem,
not a lost source: re-extract from the local PDF or de-noise the text before ingestion. `[V]`

**(iii) Block-level, sequential, new — `cti_vanarasi_2024`** (§2): Marúbo block, then its
Portuguese block; must be segmented by page order. `[V]`

**(iv) Verse-level — the scripture pair set** (§5.3), 5,389 `mzr` verses joinable by canonical
verse ID to the complete `porbr2018` text already in `parallel_por`. `[V]`

**No facing-column (two-column) document exists** in anything I found. `Wenía` is line-interleaved,
`Vaná rasĩ` is sequential blocks, Cesarino 2013 is stanza-interleaved, scripture is verse-ID.
Everything else with both languages is Portuguese prose containing Marúbo *terms* (Pinturas,
bichos de casco, Moquém Surarî, Dollis 2022) — a terminology source, not alignment material.
Nothing anywhere is **word-** or **morpheme-aligned** as a corpus, though Dollis 2018 (§4.3) gives
hand-made morpheme glosses for single phrases; that conclusion of `04` §7.3 stands.

---

## 6. Settled negatives (method named)

| Target | Method (exact, 2026-10-18) | Verdict |
|---|---|---|
| **YouVersion** had no Marúbo | SSR parse of `/languages/mzr` + Play listing | **NO LONGER A NEGATIVE** — 1 version (YKV, 4026) `[V]` |
| **eBible** `mzr` | `/find/` index scan, 1,551 rows | absent `[V]` |
| **JW.org** `mzr` | catalogue JSON, 10 Panoan codes counted | absent; `shp`+`mcf` only `[V]` |
| **Door43** genuine Marúbo | repo search ×2 + token intersection vs **two** Marúbo corpora | absent / mis-coded `[V]` |
| **ScriptureEarth** `mpu`, `xor` | `/data/mpu/`, `/data/xor/` | 404, 404 `[V]` |
| **ScriptureEarth** `mzr` USFM/zip/timing | `/usfm/`, `/00-ALL-mzr.zip`, `/audio/timing/` | 404, 404, empty `[V]` |
| **GRN** `mzr` | `/en/language/mzr`, `/da/language/mzr` | 403 bunny.net wall `[V]` |
| **FCBH/Bible Brain** `mzr` | `4.dbt.io` unauthenticated | 422 key-gated `[V]` |
| **Tatoeba**, all Panoan | `/unstable/sentences?lang=<code>` for `mzr shp mcf cbs yaa cao amc cbr mpu xor` | **400 "Invalid language code" for all ten**; control `por` → 445,534 sentences. Caveat: `pdt` also 400, so the API's `lang` whitelist is narrower than Tatoeba's catalogue — the safe claim is *"no Panoan sentence is retrievable"*, not *"Panoan is unregistered"* `[V]` |
| **Wikimedia** Panoan | `meta.wikimedia.org` SiteMatrix | 373 languages, `mzr`/`shp`/`mcf` absent `[V]` |
| **mC4** `mzr` | README YAML `language:` list | absent `[V]` |
| **HPLT 2.0 cleaned** | dataset card, 63,144 bytes | absent `[V]` (new) |
| **FineWeb-2** | dataset card, 329,009 bytes | absent `[V]` (new) |
| **OSCAR-2301** | dataset card | **401 gated** — still not a negative `[V]` |
| **HuggingFace** | `/api/datasets?search=` × 6 | `marubo` 0, `marúbo` 0, `panoan` 0, `matsés` 0, `cashinahua` 0, `shipibo` 1 (es↔shp) `[V]` |
| **Brazil MEC / SEDUC-AM / FUNAI / DSEI** Marúbo-language PDFs | 8 distinct Portuguese queries incl. `site:` filters | no `mzr`-language item found; hits are PT documents *about* the Marúbo `[V]`-search, `[W]`-absence |

---

## 7. Still unknown — with the exact barrier

| Question | Barrier | What would close it |
|---|---|---|
| YouVersion `YKV` **book coverage** (does it include LUK/ACT?) | Only `/languages/<code>` is server-rendered; `/versions/…` and `/bible/…` return the 3,038-byte SPA shell; documented API needs a key | human with the Bible App installed, or an API key |
| YouVersion **text acquisition** | ToU forbids extraction; no licence grant located for redistribution | human decision; ScriptureEarth/SAB already carries the same translation |
| **LUK + ACT** provenance in the local corpus (not in the 2023–2025 published list) | needs the acquisition record `04` §2.1 already flagged | ask ScriptureEarth/MNTB, or diff against a newer SAB package |
| **UFAM/PIBIC "Vocabulário da Língua Marubo"**: **12,571** consolidated FLEx entries + **12 digitised Marúbo materials** ("banco textual de apoio") | **unpublished.** Zenodo `17167246` is only the II SAL *abstract book* (CC BY 4.0, 7.4 MB), and Zenodo blocks `curl` (403). The CONIC abstract — **Francisca Kailanny Rodrigues Pinto**, co-author **Sanderson Castro de Oliveira**, UFAM, XXXIV CONIC 2024/25 — gives the numbers but no data | direct request to the UFAM authors — this is the single largest known-but-unpublished `mzr` asset |
| `cesarino_2018_wenia` **licence** | no licence or copyright statement anywhere in the 55-page PDF | read the SciELO/periodical record for DOI `10.1590/2316-4018533` |
| **How much `mzr` prose is in `dollis_2022_noke_yora`** (183 pp, 2,538 Marúbo-orthography lines) | fetched and text-extracted, but not segmented/quantified; it is a Portuguese dissertation that quotes and glosses Marúbo | a focused pass: separate quoted `mzr` spans from Portuguese analysis |
| **Montagner 1996** *Cânticos Xamânicos dos Marúbo* and **Werlang 2001/2011** myth-chant studies (Yurará Sin items 6458, 4550, 4597) | catalogue metadata only; PDFs not fetched (older book scans, uncertain text layer) | fetch and check text layer; these are the same chant-with-translation genre as Wenía, so likely line-aligned |
| **Common Crawl** index for `mzr` URLs | `index.commoncrawl.org` returned **HTTP 504 on every query**, including a trivial control (`url=commoncrawl.org`) | retry later; substantive answer already implied by mC4/HPLT/FineWeb-2 (all CC-derived, all lack `mzr`) |
| `cti_palavras_matis` (mpu) content | 97-page **scanned** PDF, no text layer (97 chars total) | OCR (out of scope here) |
| `cti_matses_dadauaid` (mcf) content | 109-page scanned PDF, no text layer (109 chars) | OCR |
| Museu do Índio / PRODOCLIN digitised `mzr` documents | only the authority term page was confirmed; the item-browse path was not walked | browse MNPI archive with a human |

---

## 8. Ranked top 3

Explicitly labelled per invariant 8: **Marúbo text is the only usable target-language material;
sister-Panoan material creates hypotheses only.**

### 1. `cti_vanarasi_2024` — *Vaná rasĩ*, CTI 2024 (Marúbo text — **usable**)

The only new **Marúbo** corpus in this lane, and the only non-scripture `mzr` prose anywhere in
the survey. Marúbo-authored, block-parallel with Portuguese, ≈4.7 k tokens / ≈1,390 types, 165
cultivar names, self-glossing terminology. Open PDF, no login, no wall. Cost: PDF text layer is
already good (no OCR), but the Marúbo↔Portuguese segmentation is **page-order blocking** and must
be reconstructed by the ingest stage — a small, well-defined piece of work. Direct payoffs:
third-register `mzr` text; a second independent orthography/frequency control (already used in
§5.1); a Marúbo-authored `mzr`↔`pt` pair set at section granularity; and evidence that
community-authored Marúbo books exist in print (which changes the "no community materials"
premise of `03`/`04`). **Pair it with the already-local `cesarino_2013_mitologia`**: prose plus
chant at stanza granularity together give `mzr` two non-scripture registers from two independent
publishers, which is what an orthography/frequency prior actually needs.

### 2. `cesarino_2018_wenia` + local `cesarino_2013_mitologia` — Marúbo chant texts with Portuguese, **line- and stanza-aligned** (Marúbo text — **usable**)

The answer to "what is already aligned?". `Wenía` (2018, 55 pp, DOI `10.1590/2316-4018533`) prints
**≈618 Marúbo lines each followed by its Portuguese line** — the finest genuine pair granularity in
the whole survey — and it is a published, citable text, not a scrape. The 2013 book (already local)
adds **≈655 stanza-paired chant lines** in the same register. Together: ~1,270 aligned `mzr` lines,
6–8 k tokens, in a ritual/poetic register that no Bible and no ethnobotany book can supply, from
two independent publications by the same scholar working with named Marúbo authors
(Armando Mariano Marubo Cherõpapa; the chanters named in the 2013 volume). Two costs, both
mechanical: the 2013 book's local OCR has degraded diacritics (§5.4 ii), and the **Wenía licence is
not stated in the PDF** — read it off the SciELO record before ingestion. Ranked above the
scripture metadata only because it is *new aligned `mzr` text*; ranked below `Vaná rasĩ` because it
is chant, so its vocabulary is narrower than prose for a lexicon.

### 3. Scripture licence + coverage settlement (`youversion_mzr_ykv`, `sab_app_mzr_licence`) — Marúbo text, **metadata win rather than new bytes**

Not a new corpus — it is the **licence, rights-holder and published book set** for the 5,389
verses already in the repo: CC BY-NC-ND 4.0, `© 2023-2025 Missão Novas Tribos do Brasil` + WBT,
coverage GEN / EXO 1–20 / RUT / NEH / JHN / JAS. That retires three open questions in `04`
(licence unstated; rights holder unknown; provenance inconsistency) and generates one sharp new
one (LUK+ACT). Second-order effect: it supports the Portuguese-source inference that upgrades the
PT pivot (§5.2), which is worth more to the LKB than another thousand verses of uncertain
alignment class. Ranked third only because it adds no new text bytes.

**Honourable mentions (just outside the top 3):** `cti_pinturas_marubo_2021` +
`cti_bichos_casco_2021` (Marúbo **terms inside Portuguese** — usable for the lexicon, not for
alignment) and `dollis_2022_noke_yora` (a 183-page **Marúbo-authored** dissertation with 2,538
Marúbo-orthography lines — the largest Marúbo-authored Portuguese document found, still
unquantified for `mzr` prose).

Together, the two CTI 2021 monographs carry 198 `kene` mentions (≈74 distinct `X Kene` forms by
regex; lane 03b counts ≈45–50 named kene by hand — treat the regex as an upper bound), clan-name
sets, Marúbo cosmonyms, animal/cultigen terminology and Marúbo quoted speech. Value is lexical and
onomastic (`mzr` names with Portuguese glosses — the exact shape the lexicon stage wants) plus
register evidence for the contact variety. Explicitly **not** a parallel corpus: there are no
sentence pairs here, and treating the Portuguese as a translation of the Marúbo would be wrong.

**Sister-Panoan (hypotheses only, invariant 8 — never `mzr` truth):**
`cti_palavras_matis` (Matis `mpu`) is the only Matis lexical artefact found anywhere in the survey
and would be genuinely valuable *if* OCR'd — `mpu` has no ScriptureEarth presence, no eBible
record, no JW entry, nothing. `cti_nukin_dawe` and `cti_matses_dadauaid` (Matsés `mcf`) add a
named-sister-profile register (ethnobotany, materia medica) that no Bible translation supplies.
Both need OCR or manual verification before they can support even a hypothesis.

**Do not act on:** `door43_mzr_prophets` (mis-code, now settled), `jw_panoan_shp_mcf` (ToU bars
acquisition), `youversion_mzr_ykv` *text* (ToU bars extraction — catalogue fact only), any CTI
*Série Oralidade* booklet as a text corpus (they are wordless).

---

## 9. Recommended human follow-ups

1. **Ingest `cti_vanarasi_2024`** and reconstruct its block pairs; it is the highest-value new
   `mzr` text and the only new source whose *acquisition* raises no terms-of-use question.
2. **Re-extract `cesarino_2013_mitologia` from the local PDF instead of using the OCR text.** The
   book is already a stanza-aligned `mzr`↔`por` corpus (§5.4); the `~`/`c;` OCR degradation is
   silent orthographic corruption that will poison token statistics if ingested as-is. This is
   cheap and it upgrades an asset the repo already owns.
3. **Pull `cesarino_2018_wenia`** (Yurará Sin item 4676, or the journal's own copy) and read the
   SciELO licence record first. It is **line-aligned**, which no other `mzr` source is, and it is
   the natural companion to the 2013 book.
4. **Record the scripture licence** (CC BY-NC-ND 4.0, MNTB + WBT) in
   `docs/languages/mzr_sources_index.json` for `scriptureearth_mzr_corpus`, and note the NC/ND
   clauses as recorded metadata (not a gate).
5. **Ask MNTB/ScriptureEarth two questions at once**: (a) source language of the Marúbo
   translation (Portuguese?); (b) status of LUK and ACT, which the 2023–2025 published edition no
   longer lists.
6. **Ask UFAM (Sanderson Castro de Oliveira)** for the 12,571-entry FLEx lexicon and the 12
   digitised Marúbo texts — the largest known unpublished `mzr` asset.
7. **Sweep Acervo Yurará Sin term by term** (its paging is server-side broken, so `search=` is the
   only way in): `Cânticos`, `NOKẼ`, `Wenía`, `canto`, `mitologia`, `Shoma Wetsa`, `Darcy`,
   `remédios`, plus the names `Montagner`, `Werlang`, `Dollis`, `Cesarino`. The chant-with-
   translation genre there is a `mzr` parallel-corpus vein that no other channel surfaces.
8. **Re-check `scriptureearth.org/data/mzr/audio/timing/`** — still empty; a timing drop plus the
   app's "highlight while audio plays" claim would convert the whole corpus into verse-level
   speech-text pairs.

---

## 10. Method appendix (reproducible)

`web_search` (DeepSeek server-side) for discovery; `curl` with a browser UA and `pdftotext`/`pdfinfo`
for content. Hosts and endpoints touched on 2026-10-18:

* CTI: `biblioteca.trabalhoindigenista.org.br/wp-json/wp/v2/search?search=…`,
  `/wp-json/wp/v2/tnc_col_137_item?per_page=20&page=N&_fields=id,title,link`,
  `/wp-json/tainacan/v2/items/<id>`, `/wp-json/wp/v2/media/<attachment>`, then the PDFs under
  `/wp-content/uploads/tainacan-items/137/<item>/…` and `/wp-content/uploads/2018/06/…`
* ISA: `acervo.socioambiental.org/sites/default/files/documents/mbl00006.pdf` (CTI mirror)
* Acervo Yurará Sin: `acervoyurarasin.com.br/wp-json/tainacan/v2/collection/246/items?search=<term>`
  (front end 500s; API 200), `…/wp-json/tainacan/v2/items/<id>`, `…/wp-json/wp/v2/media/<att>`, then
  `…/wp-content/uploads/tainacan-items/246/<item>/<file>.pdf`
* MAM-SP: `mam.org.br/wp-content/uploads/2021/09/mam-moquemsurari-txt-qrcode-marubo.pdf`
* YouVersion: `www.bible.com/languages/mzr` (SSR); shells probed at `/versions/4026-…`,
  `/bible/4026/GEN.1`, `/en/languages/mzr`
* Google Play: `play.google.com/store/apps/details?id=org.scriptureearth.mzr.marubo.bible`
* eBible: `ebible.org/find/`, `ebible.org/find/details.php?id={porbr2018,portft,porbrbsl}`,
  `ebible.org/porbr2018/GEN02.htm`, `ebible.org/porbrbsl/GEN02.htm`
* Door43: `git.door43.org/api/v1/repos/search?q={mzr,marubo}`,
  `…/moseslai2018/mzr_amo_text_reg/raw/branch/master/01/01.txt`
* ScriptureEarth: `…/data/{mzr,mpu,xor}/`, `/data/mzr/{usfm/,00-ALL-mzr.zip,audio/timing/,sab/}`
* JW: `www.jw.org/en/languages/` (embedded catalogue JSON)
* Walls probed: `globalrecordings.net/{en,da}/language/mzr` (403), `4.dbt.io/api/{languages,bibles}?…`
  (422), `huggingface.co/datasets/oscar-corpus/OSCAR-2301` (401), `zenodo.org/api/records/17167246/…`
  (403), `index.commoncrawl.org/CC-MAIN-2025-30-index?…` (504 on all queries incl. control)
* Negatives probed: `api.tatoeba.org/unstable/sentences?lang=<10 Panoan codes + pdt + por>`,
  `meta.wikimedia.org/w/api.php?action=sitematrix`,
  `huggingface.co/api/datasets?search={marubo,marúbo,panoan,matsés,shipibo,cashinahua}`,
  cards for `mc4`, `HPLT/HPLT2.0_cleaned`, `HuggingFaceFW/fineweb-2`
* Local verification: `var/external/scriptureearth/mzr/*.usfm` (verse counts, proper-name forms),
  `var/external/parallel_por/*.txt` (verse counts, verbatim comparison with `porbr2018`)
* Scratch: all downloads in `var/tmp/mzr-recheck/` were deleted after extraction; no repo file
  other than this report was written.
