# ADR-0027: Dictionary rendering and print pipeline

**Status:** Accepted (owner decision, 2026-10-20)
**Date:** 2026-10-20
**Governing records:** ADR-0001, ADR-0021, ADR-0003, ADR-0016
**Supersedes:** none
**Related spec:** `docs/superpowers/specs/2026-10-20-dictionary-session-and-print-edition-design.md`

## Context

The portal at `http://localhost:8000` is an LKB engineering console: master-detail
audit dossiers, a comparative matrix, an IGT corpus view, a synthetic laboratory, and
a dataset hub. It is excellent for a linguist inspecting evidence and unusable for
anyone who just wants to look up a word.

A printed edition is a separate requirement. The artifact that goes to a community, a
school, or a grant application is a book: typeset, paginated, indexed — not a scrolling
page and not a markdown table.

Two surfaces must never disagree about what a display entry is, how a gloss is joined,
or whether an entry is validated. That is the risk of building the web view and the
print view independently.

## Decision

### D1 — One builder, two renderers

A new `DictionarySessionBuilder` (`src/langpipe/lexicon/dictionary/session.py`) produces
the display-ready entry list. The web Dictionary tab and the print template both consume
it. Neither re-derives entry semantics.

### D2 — WeasyPrint 70 is the PDF engine

`weasyprint>=70,<71` is a core dependency. It is pure Python (no compiler), so CI stays
compiler-free. WeasyPrint is imported lazily, inside functions, so `import
langpipe.lexicon.exporters` never requires the PDF toolchain.

**Alternatives considered:**

| Alternative | Why not |
|---|---|
| **Typst 0.15** | The `columns` container is not height-balanced (per the Typst docs), which is visible at every letter boundary in a two-column dictionary. Retained as the documented alternative for a community member who wants to typeset their own edition. |
| **LaTeX (`lexikon.sty` + `paracol` + `fancyhdr`)** | A battle-tested two-language dictionary macro exists on CTAN, and `lexikon`'s `\markboth` gives guide words for free. Rejected for now: TeX Live is a ~5 GB dependency and the learning curve is steep, for no functional gain here. Recorded so a LaTeX edition has a starting point. |
| **Prince (commercial)** | Best-in-class paged media; SIL's own FLEx→Pathway pipeline uses it. Not adopted (commercial licence). WeasyPrint is the free equivalent. |
| **Paged.js** | Needs a headless browser at build time. Heavier than WeasyPrint. |
| **Browser `window.print()`** | Gives the reader their own print dialogue and a dark-themed page. Cannot produce a typeset, indexed book. |

### D3 — Charis SIL 7.000 is the print typeface

Charis is vendored under `assets/fonts/` as `.woff2` and embedded automatically by
WeasyPrint. It is OFL-1.1, so it may be embedded and redistributed.

The previous exporter used Newsreader, a Google font with **no IPA coverage**. The font
binary was parsed and confirmed: TeX Gyre Pagella is also disqualified, missing 269 of
271 IPA codepoints. Charis has full IPA, all the Marúbo nasal-vowel diacritics
(`ẽ` U+1EBD, `ĩ` U+0129, `ã`, `õ`), and a real `smcp` small-caps feature.

The fonts are self-hosted. The print path must not fetch anything from the network at
render time: the PDF build has to be reproducible and offline-capable, and no restricted
material may reach a third party (invariant 10).

Every glyph the template emits must exist in Charis. This is not a theoretical
concern: the first draft of the print template used `△` (U+25B3) for the candidate
evidence marker, and Charis has no triangle at all. WeasyPrint silently substituted a
**second typeface**, so the print edition became a two-typeface book — invisible in the
HTML, visible only in `pdffonts` on the rendered PDF. The marker is now `◊` (U+25CA
LOZENGE). Note that `U+2206` is *not* a usable substitute: Charis maps it to a sigma
(Σ), not a triangle. There is a regression test for this.

### D4 — Guide words use `string-set` on `.headword`, not on `.entry`

WeasyPrint 70 does **not** populate a running head from `position: running()` or
`:first-of-type`. The working form, confirmed by rendering to PNG and inspecting the
page image, is:

```css
.headword { string-set: gw content(text); }
@page { @top-left { content: string(gw, first); } @top-right { content: string(gw, last); } }
```

Two constraints on that rule are load-bearing, and both were found by rendering the
real layout rather than by reading the documentation:

1. **`string-set` belongs on `.headword`, not on the block-level `.entry`.** `content(text)`
   on `.entry` captures the *whole entry* — headword, gloss and example — as the guide
   word, not just the headword. The rule must sit on the element whose text is the
   guide word.
2. **The `.headword` must not be inside a flex or grid container.** WeasyPrint 70 does
   not evaluate `string-set` on a flex or grid item. A `.entry-head { display: flex }`
   wrapper silently suppresses the guide word: the running head renders empty, with no
   error and no warning. The `.entry-head` row therefore uses **inline flow** with
   `margin-left` spacing on the sibling spans, not `display: flex`.

This is recorded because all three broken forms look plausible and will be
re-introduced.

### D5 — Letter bucketing uses the normalized key

The previous exporter bucketed on `headword[0].upper()`, which filed `á` under `Á`
rather than `A` and gave the nasal-vowel headwords their own buckets. The builder
buckets on the normalized search key. This is fixed once, in the builder, so both
surfaces are correct by construction.

### D6 — Evidence disclosure is tiered

Simple (default) shows headword, POS, gloss, example and citation reference, with
status encoded as a coloured left border. Expert adds the full provenance panel. The
tiering is not cosmetic: it is the mechanism by which the project stays evidence-first
without making a casual reader wade through audit state (invariant 3). A "show only
validated" facet exists for the same reason.

### D7 — The print edition is a derived artifact, regenerated on demand

The PDF is derived from `exports/<lang>/dictionary.json`. It is built by
`export_all_formats` and by `POST /api/dictionary/print`. The HTML template is
committed, because it is the durable artifact.

> **Corrected 2026-10-21 (Task 5).** This section originally said the PDF "is not
> committed to the repository when it can be regenerated". That conflicts with the
> Exports tab design in Task 9, which links *directly* to
> `/formats/mzr/dictionary_mzr_printable.pdf` as a static file with `download`. A
> static link needs the file to exist on disk, or the button 404s until someone runs
> the export by hand. The PDF is therefore committed, and the render is
> **byte-reproducible** (verified: a regeneration from the same export produced a
> byte-identical file), so the committed copy never goes stale silently. The
> per-export font copies under `exports/**/fonts/` *are* ignored — the canonical
> faces live in `assets/fonts/`.
>
> The "regenerated on demand" property still holds: `POST /api/dictionary/print`
> rebuilds both the HTML and the PDF in place, and `export_all_formats` refreshes
> them. Committing them is a convenience, not a source of truth.

### D8 — One attested example per entry in print

Every entry in the clean view has two attestations. The print edition shows **exactly
one**. This is a measured constraint, not a preference: two examples per entry took
~2 m 15 s and ~95 pages; one example plus `hyphens: auto` on `.gloss` and `.example`
renders in ~41 s at ~60 pages. The second attestation remains fully available in the
web session and in the entry's provenance panel, so nothing is lost — it is simply
not typeset twice.

`hyphens: auto` is required, not decorative: hyphenation alone cut the render from
~2 m 15 s to ~1 m 40 s, because Pyphen then avoids the wide word spacing that
justification creates in narrow columns. The `lang="pt-BR"` attribute on `<html>` is
what makes Pyphen apply Portuguese patterns.

Two further performance decisions are load-bearing for the macrostructure and are
recorded here so they are not "optimised" away:

- **`break-inside: avoid` stays on `.entry`.** Removing it cut the render to 31 s but
  let entries split across columns, breaking the one-entry-one-block convention. The
  example-count and hyphenation changes buy the speed without that trade-off.
- **The per-letter `.entries-columns` containers stay.** Flattening them into a single
  column container was 3× faster (46 s vs ~2 m 15 s) but broke the layout: the letter
  heading no longer spans the full page width.

### D9 — Inflected forms are listed under their base, never published as headwords

The clean view publishes 892 lemmas. The artifact also carries `inflected_form`
rows (63 of them: a recorded base name plus a clitic, e.g. `berequias` + `-nẽ` →
`berequiasnẽ`). They are **not** added to the A–Z body:

- the session attaches a form to every built entry whose normalized headword equals
  the form's normalized `audit.related_entry` (all homographs receive it), and lists
  it in `entry.forms` (`surface`, `search_key`, `pos`, `clitic`);
- a form whose base is not a published entry cannot be attached to anything. It goes
  to the session-level `form_index` with `lemma: null` and is reachable only through
  search: the reader answers "forma de <base>" and the pane states that the base is an
  onomastic name, not a common-lexicon entry. It is never a headword row and never
  counts toward `total_entries`;
- `forms` is always present (an empty list when the lemma has none), so a renderer can
  treat it as a list unconditionally.

Measured 2026-10-22: **0 of 63 forms attach** — their bases are Portuguese/Latin names
(`berequias`, `jesus`, `sara`, `agri`) recorded in the onomasticon or absent from the
artifact entirely, and no published lemma begins with `b`. The mechanism is therefore
shipped with an empty attachment set and 63 search-only surfaces; if the base naming
ever changes, attachments appear without a code change. This is a **data gap**, not a
rendering bug.

### D10 — Validation labels describe the basis the artifact records

`validated` means "a validation decision is recorded", not "reviewed". The artifact
records two kinds of basis, and the reader surfaces must not assert a third:

- `validation_basis.kind` is derived per entry from the works named in `provenance`
  and the corpus citation count: `source_assertion`, `source_and_corpus`,
  `corpus_only`, or `unrecorded`. `unrecorded` is never guessed into a stronger class;
- the web reader shows the basis in the hover strip and the expert grid; the print
  legend's `✓` definition is generated from the kinds actually present in the edition,
  and its aggregate sentence counts attested vs source-only entries from the session;
- `tests/unit/test_web_dictionary_labels.py` fails if a reader-facing label names a
  basis class (a published source, corpus attestation, human review, expert consensus,
  gold standard) that the shipped data does not hold. Measured split: 144 `✓`, of which
  36 cite a corpus line and 108 rest only on an imported work (ASJP).

The persisted `exports/mzr/dictionary.json` schema is unchanged: both `forms` and
`validation_basis` are session projections, derived at build time.

## Consequences

- The portal gains a reader-facing surface without disturbing the five engineering
  workspaces. The Dictionary tab is the default landing tab; the console is one click
  away.
- `weasyprint` becomes a core dependency. It is pure Python, but it needs the Pango
  system library at runtime. CI environments without Pango will skip the PDF tests
  rather than fail them.
- The print render takes 30–60 s for the 892-entry clean view. The `POST
  /api/dictionary/print` endpoint reports progress to the user rather than appearing
  to hang.
- `exports/web/index.html` grows by roughly 400 lines. The Dictionary logic lives in
  `exports/web/dictionary.js` to keep that file from growing further.
- The `/formats/<lang>/...` route repairs three download links that had been returning
  404 since the Exports pane was written.

## Alternatives not adopted

- **A `clld` app over the existing CLDF export.** The scholarly layer could be a
  `clld` application (`cdk.clld.org`, `csd.clld.org`, `ids.clld.org` are the models).
  The CLDF *data contract* is adopted — the repository already exports it. The framework
  is a separate product: a Pyramid + SQLAlchemy + PostgreSQL server stack, producing
  research databases rather than a community portal.
- **An offline PWA (service worker + web app manifest).** Both are plain files and need
  no bundler, so this is straightforward. It is deferred because it changes the
  deployment surface (service workers need HTTPS or localhost) and deserves its own
  design.
- **Audio and IPA.** Neither exists in the data. The repository has no audio files, and
  the orthography is nasal diacritics (`ẽ ĩ ã õ`), not IPA. This is a **data gap**, not
  a missing feature.

## References

- WeasyPrint documentation — https://doc.courtbouillon.org/weasyprint/stable/
- Charis SIL — https://github.com/silnrsi/font-charis
- `lexikon` LaTeX package — https://ctan.org/pkg/lexikon
- Typst `columns` — https://typst.app/docs/reference/layout/columns/
- SIL, *FLEx Dictionary Printing and Export* (FLEx → Pathway → Prince) —
  https://downloads.languagetechnology.org/fieldworks/Documentation/Technical%20Notes%20on%20FLEx%20Dictionary%20Printing%20and%20Export.pdf
- OED, *Guide to the dictionary* —
  https://premium.oxforddictionaries.com/fr/mots/guide-to-the-dictionary
- Prior-art survey — `docs/research/dictionary-print-prior-art-2026-10.md`
