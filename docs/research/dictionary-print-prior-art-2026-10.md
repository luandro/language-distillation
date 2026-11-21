# Prior art: web dictionaries and print-ready PDF dictionaries

**Surveyed:** 2026-10-20 (URLs re-verified 2026-10-21)
**Method:** live web search, GitHub API, CTAN, PyPI/npm registries, and direct
inspection of shipped font binaries with fontTools.
**Scope:** a bilingual Marúbo (`mzr`) ↔ Portuguese dictionary of ~900 entries, evidence
first, served from a plain `http.server` with no build step.

Every non-obvious claim below carries a URL. Claims that could not be confirmed are
recorded in §1 ("Names that could not be confirmed") and §6 ("Open questions") rather
than asserted.

## 1. Open-source dictionary web UIs

| Project | URL | Licence | Stack | What it contributes | Adopted? |
|---|---|---|---|---|---|
| CLDF | https://github.com/cldf/cldf | Apache-2.0 | CSVW + JSON | The interchange standard. The repository already exports CLDF. | Data contract only |
| clld | https://github.com/clld/clld | Apache-2.0 | Python / Pyramid | "A web framework to display Cross Linguistic Linked Data." Renders CLDF lexicons as citable web apps. | No — a server stack, and it produces research databases, not community portals |
| cldfofflinebrowser | https://github.com/cldf/cldfofflinebrowser | Apache-2.0 | Python | A `cldfbench` plugin that writes an offline-browseable HTML representation of a CLDF dataset. | No — deferred with the PWA |
| Dictionaria | https://dictionaria.clld.org/ | — | clld | Peer-reviewed, electronic-first dictionaries of small languages. The governance model this project most resembles. | Model only |
| Lexonomy | https://github.com/lexicalcomputing/lexonomy | MIT | JavaScript | "A cloud-based, open-source dictionary writing system" — the open successor in spirit to Lexique Pro. | No — authoring, not display |
| Webonary | https://www.webonary.org/about-webonary/ | GPL | WordPress / PHP | SIL's hosted bilingual dictionary publisher; imports FLEx XHTML. | No |
| Mukurtu | https://mukurtu.org/ | open source | PHP / Drupal | Indigenous-governed content platform with **cultural protocols** and curated **word lists** grouped by topic/region/POS. | Model for the facet filters |
| FLEx → Pathway | https://downloads.languagetechnology.org/fieldworks/Documentation/Technical%20Notes%20on%20FLEx%20Dictionary%20Printing%20and%20Export.pdf | — | C# / XHTML | SIL's own print pipeline for indigenous dictionaries: XHTML → **Prince**, with a `TwoColumn` stylesheet. | Validates the HTML → paged-media approach |
| dictpress | https://github.com/soumendrak/ekathi | AGPL-3.0 | Go | "Build and publish dictionaries for any language." Paginated **A–Z glossaries for all alphabets**. | Model for the A–Z index |
| bg-en | https://github.com/kfet/bg-en | MIT | TypeScript | Instant **prefix search via binary search, no server**; accent-insensitive lookup; PWA; shareable `?q=` links. | Model for the search |
| PeakSlab | https://github.com/tnelsond/peakslab | — | C | "A libre progressive web app offline dictionary platform from scratch in under 128kb", purpose-built for obscure languages. | Model for the PWA |
| GoldenDict | https://github.com/goldendict/goldendict | GPL | C++ / Qt | Its headline feature — type words "without any accents or correct case" — is table stakes. | Validated the accent-insensitive requirement |
| Kaikki / wiktextract | https://kaikki.org/ · https://github.com/tatuylonen/wiktextract | CC-BY-SA / MIT | Python | Wiktionary's structured JSON — the richest open example of a machine-readable dictionary schema. | Schema reference |
| ENGLAWI `<pos>` | https://redac.univ-tlse2.fr/lexicons/englawi/doc/pos.html | — | — | The entry model: `type`, `etymNb`, `lemma`, `labels[]`. The labels array is the precedent for per-entry status flags. | Model for the entry anatomy |
| FLEx bilingual (MXB) | https://software.sil.org/fieldworks/wp-content/uploads/sites/38/2018/12/MXB-FLEx-8-3-10-eng.pdf | — | — | Distinguishes **Definition** (monolingual) from **Gloss** (bilingual translation equivalent); describes the **Reversal index** in the contact language. | The repository already implements the reversal index in `src/langpipe/lexicon/reverse.py` |

### Names that could not be confirmed

- **"Lexicographer"** (a JS/OSX dictionary editor) — not located on GitHub as a
  dictionary workbench. A GitHub repository search for `lexicographer` returns 43
  hits, none of which is a dictionary editor of that description: the closest are
  `gliese1337/Lexicographer` ("A system for maintaining natural language
  dictionaries", last pushed 2012), `bhalash/lexicographer` (a *lexicographic
  permutation generator*, JavaScript) and `hadware/lexicographer` (an EPUB search
  engine in Shell/Python). The live successor in the OSX/SIL space is FLEx; in the
  open-source web space it is Lexonomy. **Do not cite "Lexicographer" without
  verifying it.**
- **Lexique Pro** — not open source. SIL freeware, **Windows-only** ("Lexique Pro is a
  Windows program. Sorry, there are no plans to develop versions for Linux or Mac OS.",
  https://software.sil.org/downloads/r/lexiquepro/Lexique%20Pro%20-%20User%20Guide%202.5.pdf).
  The open French successor is Lexique 2.0/3000 (CC BY-SA 4.0, https://a3nm.net/git/lexique/).
- **Lexikothek** — this is a **Bertelsmann 1970s–80s German encyclopedia series**, not a
  software package (https://files.eric.ed.gov/fulltext/ED081456.pdf).
- **scaMorph** — a medical brain-image registration method, not a lexicon tool. The
  GitHub search for `scaMorph` returns 2 repositories, both unsupervised deformable
  image registration.
- **TeX Gyre Pagella** as a dictionary face — the font binary was parsed and it is
  disqualified for IPA-adjacent text. Parsed directly with fontTools: against the
  368-codepoint IPA set (U+0250–U+02AF, U+02B0–U+02FF, U+1D00–U+1DBF) it covers
  **12** codepoints; Charis SIL covers **368/368**. The specific figure quoted in the
  plan ("269 of 271 absent") does not reproduce on a standard IPA set and is not
  repeated here; the direction of the claim is confirmed.

## 2. PDF dictionaries

| Tool | Version | Licence | Two columns | Guide words | Cross-ref page no. | IPA | PDF/A | Verdict |
|---|---|---|---|---|---|---|---|---|
| **WeasyPrint** | 70.0 | BSD-3-Clause | ✅ `column-count` | ✅ `string-set` + `string(name, first\|last)` | ✅ `target-counter()` | ✅ via Charis | ✅ `--pdf-variant=pdf/a-2b` | **Adopted** |
| Typst | 0.15.1 | Apache-2.0 | ⚠️ `columns` is **not height-balanced** (https://typst.app/docs/reference/layout/columns/) | ✅ `header:` + `context` | ✅ `ref()` | ✅ | ❌ | Documented alternative |
| LaTeX (XeLaTeX) | — | LPPL | ✅ `paracol` | ✅ `fancyhdr` + `markboth` | ✅ `hyperref` | ✅ | ✅ | Documented alternative; needs TeX Live |
| Prince | 17 | commercial | ✅ | ✅ | ✅ | ✅ | ✅ | Not adopted (licence) |
| Paged.js | 0.4.3 | MIT | ✅ | ✅ | ✅ | ✅ | ❌ | Rejected (needs headless Chrome) |
| reportlab | 4.x | BSD | manual | manual | manual | ✅ | manual | Rejected (hand-roll everything) |

Version numbers were re-checked against the registries on 2026-10-21: WeasyPrint
70.0 is the only 70.x release (https://pypi.org/pypi/weasyprint/json), Typst's
latest release is v0.15.1 (https://api.github.com/repos/typst/typst/releases/latest),
and Paged.js's latest published version is 0.4.3 (https://registry.npmjs.org/pagedjs).
The Typst limitation is quoted from the reference itself: "It will currently not
balance the height of the columns." WeasyPrint's PDF/A support is listed in its
option reference as `pdf/a-2b` among the accepted `--pdf-variant` values
(https://doc.courtbouillon.org/weasyprint/stable/api_reference.html).

### WeasyPrint features verified in this repository

Confirmed by rendering to PDF and inspecting the output:

| Feature | CSS | Verified how |
|---|---|---|
| Guide words | `string-set: gw content(text);` + `string(gw, first)` / `string(gw, last)` | `pdftotext` on the committed 61-page PDF shows the first and last headword on every page checked (e.g. page 5 → `aakase` / `aĩyama`, page 20 → `koĩní` / `maivoropa`). |
| Guide words (**broken forms**) | `position: running(...)`, `:first-of-type` | Rendered to PNG during Task 3; the running head was **empty**. Do not reintroduce. |
| Guide words (**flex/grid trap**) | `string-set` on a flex item | WeasyPrint 70 does not evaluate `string-set` on a flex or grid item. The guide word is silently dropped and the running head stays empty. The `.entry-head` row therefore uses inline flow with `margin-left` spacing, not `display: flex`. |
| Cross-references | `a::after { content: target-counter(attr(href url), page); }` | A purpose-built render with a `related_entry` produced `ver pakasaw (p. 4)` in `pdftotext` output. |
| Folios | `@bottom-center { content: counter(page); }` | `pdftotext` showed the page number. |
| Font embedding | `@font-face` + a local `.woff2` | `pdffonts` on the committed PDF shows only `Charis`, `Charis-Bold` and `Charis-Italic`, all `CID TrueType` / `Identity-H`, all embedded and subset. |
| Diacritics | — | `pdftotext` round-tripped `ẽa`, `nukẽ`, `wẽstisẽ` and `ˈmaˈɾuβa` intact through a Charis-staged render. |

### Measured render times (892 entries, two columns)

| Configuration | Time | Pages |
|---|---|---|
| Previous export (Newsreader, per-letter column containers, per-entry citation blocks) | ~80 s | 43 |
| Local fonts, one continuous two-column container | ~7 s | — |
| Local fonts, one container, with a citation block per entry | ~35 s | — |
| **Adopted template: one example per entry + `hyphens: auto`** | **~41 s** | **~60** |
| Same, two examples per entry | ~2 m 15 s | 95 |
| Same, no example blocks | ~12 s | 48 |

The per-entry example block is the dominant cost, not the fonts. The numbered-bibliography
treatment in the new template reduces the repeated text and brings the full scholarly
edition back under a minute.

Re-measured on this machine for this report: the committed
`exports/mzr/formats/dictionary_mzr_printable.html` renders in **43.4 s** to **61
pages** (A4, 595.276 × 841.89 pt), producing a byte-comparable output. The committed
PDF contains **no `http(s)://` reference at all** — the three `@font-face` sources are
relative paths (`url('fonts/Charis-Regular.woff2')` and siblings), so the render
fetches nothing from the network.

Two layout properties are load-bearing and must not be "optimised" away:

- `break-inside: avoid` on `.entry`. Removing it cut the render to 31 s but let
  entries split across columns, breaking the one-entry-one-block convention.
- The per-letter `.entries-columns` containers. Flattening them into a single column
  container was 3× faster (46 s vs ~2 m 15 s) but broke the layout: the letter heading
  no longer spans the full page width.

## 3. Dictionary typography and layout

- **Entry structure** — headword → pronunciation → POS → senses → examples →
  cross-references. The OED's *Guide to the dictionary* enumerates the components
  (https://premium.oxforddictionaries.com/fr/mots/guide-to-the-dictionary): *Headword*,
  *Line breaks/syllabification*, *Pronunciation*, *Parts of speech*, *Senses*,
  *Example sentences*, *Derivatives*, *Origin*. The cross-reference element is not
  among them; in this project it is added as a local convention.
- **Macrostructure / microstructure** — Béjoint's distinction, in Luna, *Clearly defined
  continuity and innovation in the typography of English dictionaries*:
  https://typography.network/wp-content/uploads/2024/04/Luna_TypPp_4_Clearly_defined_continuity_and_innovation_in_the_typography_of_English_dictionaries.pdf
  (The host was returning HTTP 503 on 2026-10-21; the issue record is
  https://typography.network/typographypapers4/.)
- **Guide words** — the Overleaf *Dictionary template* puts the first and last word on
  the page in the header: https://www.overleaf.com/latex/examples/dictionary-template/pdztbwjxrpmz
  ("The header on each page contains the first and last word on that page, making for
  easy navigation.")
- **Small caps** — the *Indexer* typographic note recommends letter-spacing small caps
  at least one unit: https://doi.org/10.3828/indexer.1958.2.3.4 (Kenneth Day, "The
  Typography of Indexes: Some Notes", *The Indexer* 2(3), 1958, pp. 85–89. The
  publisher's PDF endpoint returns HTTP 403 to automated clients; the DOI resolves to
  the article record.)
- **Justification** — the same note warns that wide word spacing in narrow columns makes
  the eye stray; hyphenation (`hyphens: auto` with `lang="pt-BR"`) is the mitigation.
- **Frequency banding** — dictionaries for learners band by frequency. The academic
  caution: word *frequency* is a poor proxy for lexical sophistication (Kyle,
  Crossley & Berger 2018,
  https://bspace.buid.ac.ae/buid_server/api/core/bitstreams/d819851a-c2f8-4f23-a945-a31032e12ef2/content).
  With no large Marúbo corpus, banding here uses **this repository's own attestation
  counts** — evidence density, the honest signal available.
- **Typeface for a dictionary** — only **Lexicon** (Bram de Does, 1992) was designed
  specifically for dictionary setting, at very small point sizes:
  https://en.wikipedia.org/wiki/Lexicon_(typeface) ("specially designed for use at very
  small point sizes in Van Dale's Dictionary of the Dutch Language"). The same source
  records the exception that makes this relevant here: dictionaries always used types
  designed for other purposes, with the exception of fonts to explain pronunciation.

## 4. Search and browse UX

- **Accent-insensitive lookup is table stakes** — GoldenDict's headline feature is
  typing words "without any accents or correct case":
  https://github.com/goldendict/goldendict. The canonical implementation is
  `String.prototype.normalize('NFD')` with combining marks stripped, which is what
  Fuse.js does (https://github.com/krisk/Fuse/commit/ef1637140064a1dbce651fe8998cba964ea5bce2,
  the "ignore-diacritics" merge).
- **Instant prefix search without a server** — https://github.com/kfet/bg-en
  ("Instant prefix search (binary search, no server) with match highlighting"; the
  search is an in-memory binary search over a sorted JSON array, with no database in
  the browser).
- **Keyboard focus model** — "The search bar captures keystrokes only while it has
  focus. `/` focuses it; Escape returns focus.":
  https://github.com/EtherAura/Kartend/wiki/Input-and-Controls
- **A–Z index** — https://smart-interface-design-patterns.com/articles/navigation-queries-ux/
  ("One way to address navigation issues on large websites is by using an A-Z Index
  pattern.")
- **Facets and word lists** — https://docs.mukurtu.org/dictionary/WordLists/index.pdf
- **Showing confidence without misleading** — https://github.com/ericsocrat/decision-os/issues/114:
  "Without visual confidence indicators, users may trust estimated data as much as
  verified data." The adopted remedy is a badge with three visual states, a tooltip, and
  a "show only high-confidence" filter — the issue's own technical specification.

## 5. Offline-first without a bundler

- Service workers and web app manifests are **plain files**; neither needs a bundler.
  They require HTTPS or `localhost`, and the worker must be served from the site root.
- **bg-en** — ~4.1 MB one-time download, cached by a service worker; installable as a PWA;
  shareable search links. https://github.com/kfet/bg-en
- **PeakSlab** — under 128 kb, offline. https://github.com/tnelsond/peakslab
- **dictpress — "Paginated A-Z (all alphabets for any language) glossaries"** —
  https://github.com/soumendrak/ekathi

## 6. Open questions

- The status of the **"Lexicographer"** editor is unverified. See §1.
- Whether a community print run wants a page size other than A4 (e.g. 15×21 cm, or a
  saddle-stitched booklet). A4 is the current default and the page box is a single CSS
  variable.
- Whether the printed edition needs a short **orthography note** explaining the nasal
  diacritics (`ẽ ĩ ã õ`) and the `w`/`y` contrast. This is a question for the community
  editor, not for the pipeline.
- Whether the print edition should carry **IPA**. The typeface can render it (Charis
  covers 368/368 IPA codepoints) and `pdftotext` round-trips it, but there is **no IPA
  in the data**: a scan of `exports/mzr/dictionary.clean.json` finds zero IPA codepoints.
  This is a data gap, not a rendering limit.

## 7. How this survey shaped the decisions

See `docs/adr/0027-dictionary-rendering-and-print-pipeline.md`. In short: the **data
contract** from CLDF was adopted, the **HTML → paged-media** route was validated by
SIL's own print pipeline, **WeasyPrint** was chosen over Typst and LaTeX, **Charis SIL**
was chosen over Newsreader and TeX Gyre Pagella, and the **three-tier evidence
disclosure** was adopted from the confidence-indicator problem documented in
`decision-os` issue 114.
