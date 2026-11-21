# Dictionary Session + Print Edition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a human-facing Marúbo↔Portuguese dictionary session in the portal at `http://localhost:8000` (a new top-level tab with ranked diacritic-insensitive search, A–Z browse, and a Simple/Expert evidence toggle) plus a typeset print edition of the whole dictionary as a PDF (WeasyPrint 70, Charis SIL, guide words, numbered bibliography, front/back matter).

**Architecture:** One new builder (`DictionarySessionBuilder`) turns the canonical `exports/mzr/dictionary.json` into a normalized, sorted, display-ready entry list. Two renderers consume it: the web Dictionary tab and the print template. The print template (HTML+CSS) is rendered to PDF by WeasyPrint. The portal gains two API endpoints and one new workspace pane. A shared JavaScript search/render module powers the web tab so the browser and the server never disagree about normalization, bucketing, or status semantics.

**Tech Stack:** Python 3.12, `uv`, pytest, WeasyPrint 70.0 (pure-Python wheels), Charis SIL 7.000 (OFL-1.1, self-hosted `.woff2`), vanilla JavaScript (no build step), stdlib `http.server`.

**Spec:** `docs/superpowers/specs/2026-10-20-dictionary-session-and-print-edition-design.md`

---

## Global Constraints

These apply to **every** task. Copy them verbatim into task context.

- **Repo root:** `/home/luandro/Dev/AI/language-distillation`. All paths in this plan are relative to it.
- **Python:** always use `.venv/bin/python` or `uv run`. The bare `python3` on this machine fails (pyenv version `3.12` is not installed).
- **Never** call `rm` or any destructive cleanup. The repository's `AGENTS.md` forbids it.
- **Raw sources are immutable.** Never rewrite `exports/mzr/dictionary.json`, `exports/mzr/dictionary.clean.json`, or `exports/mzr/dictionary.reverse.json` by hand. New artifacts are written to *new* paths.
- **Hypotheses are not facts.** `status` must never be silently upgraded. `candidate` is never rendered as `validated`.
- **No Marúbo-specific rules in generic pipeline code.** The builder and exporters are parameterized by `target_lang` / `contact_lang`. Marúbo facts (glottocode, territory, morpheme table) are *data*, read from the export.
- **No third-party API receives restricted material.** The PDF path must not fetch fonts or any data from the network at render time. Fonts are self-hosted in the repository.
- **Line length** is 100 characters (ruff `line-length = 100` in `pyproject.toml`). Ruff's `extend-exclude = ["*.md"]` means Markdown is not reformatted.
- **Existing public API must not break.** `PrintableDictionaryExporter.export(entries, output_path, title=None)` keeps its signature; new parameters are keyword-only with defaults.
- **Dependency policy:** `weasyprint` is added as a **core** dependency in `pyproject.toml` (pure-Python wheels: `brotli`, `cffi`, `cssselect2`, `fonttools`, `pillow`, `pydyf`, `pyphen`, `tinycss2`, `tinyhtml5`, `webencodings`, `zopfli` — no compiler needed, so CI stays compiler-free). It is imported **lazily inside functions**, never at module import time, so `import langpipe.lexicon.exporters` never requires the PDF toolchain.
- **The PDF smoke test must SKIP, not fail**, when WeasyPrint or `pdftotext`/`pdffonts` is unavailable. Use `pytest.mark.skipif`.
- **Guide words in WeasyPrint MUST use `string-set: gw content(text);` on the `.headword` element**, with `string(gw, first)` / `string(gw, last)` in the `@page` margin boxes. Two things were empirically tested and **do not work** in WeasyPrint 70: the `position: running()` and `:first-of-type` approaches (the running head stays empty). Do not reintroduce them.
- **The `.headword` element MUST NOT be inside a flex or grid container.** WeasyPrint 70 does not evaluate `string-set` on a flex/grid item — the guide word is silently dropped and the running head stays empty. The `.entry-head` row must use inline flow with `margin-left` spacing on the sibling spans, **not** `display: flex`. This was found by rendering the real layout to PNG and comparing it against a non-flex variant.
- **`string-set` must be attached to `.headword`, not to `.entry`.** `content(text)` on the block-level `.entry` would capture the whole entry's text (headword + gloss + example) as the guide word, not just the headword.
- **The print edition shows exactly ONE example per entry.** Every entry has two attestations; showing one keeps the render at ~41 s instead of ~2m15s, and the page count at ~60 instead of ~95. The second attestation remains fully available in the web session and in the entry's provenance panel. The spec's D1 said "1–2 attested examples"; the measured constraint forces the 1.
- **`hyphens: auto` is required on `.gloss` and `.example`.** Measured: hyphenation alone cut the render from 2m15s to 1m40s. Combined with one example per entry, the render is ~41 s. The `lang="pt-BR"` attribute on `<html>` is what makes Pyphen apply Portuguese patterns.
- **Keep `break-inside: avoid` on `.entry`.** Removing it cut the render to 31 s but let entries split across columns, which breaks the "one entry = one block" convention. The example-count and hyphenation changes buy the speed without that trade-off.
- **Keep the per-letter `.entries-columns` containers.** Flattening them into a single column container was 3× faster (46 s vs 2m15s) but broke the layout: the letter heading no longer spans the full page width. The letter sections are load-bearing for the macrostructure.
- **Letter bucketing MUST use the normalized search key**, never `headword[0].upper()`. The current `printable.py:50` has this bug (`á` files under `Á` instead of `A`).
- **The print typeface is Charis SIL 7.000.** Newsreader is banned from the print path (it has no IPA coverage).
- **The session payload is built server-side, in Python.** The browser must not re-implement normalization, bucketing, or status semantics.
- **Do not add a JavaScript build step.** The portal is a plain `http.server` with no bundler. New JS is a plain `<script src="...">` file.
- **Write the combining-mark regex with explicit escapes:** `/[\u0300-\u036f]/g`. A literal `U+0300`–`U+036F` range works in a JS file, but it is invisible in a Markdown document and can be mangled by an editor or a copy-paste, producing `Invalid regular expression: Range out of order in character class` at parse time. The escape form is unambiguous in both.
- **Top-level `const` in a classic script is NOT on `window`.** `I18N` and `State` are declared with `const` inside a classic `<script>` block in `index.html`, so `window.I18N` and `window.State` are both `undefined`. A separate `<script src="dictionary.js">` **can** see them as bare identifiers (top-level `const` lives in the global lexical scope), but **not** as `window.I18N` / `window.State`. Use bare `I18N` / `State` and guard with `typeof`. Verified in headless Chrome.
- **The Dictionary tab must be the default landing tab**, and the `dictionary` workspace must be added to the hash-routing allow-list in the `DOMContentLoaded` handler, or `#dictionary` will silently fall back to another pane.

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/langpipe/lexicon/dictionary/__init__.py` | Package marker; re-exports the builder. |
| `src/langpipe/lexicon/dictionary/session.py` | `DictionarySessionBuilder` — the single source of truth for display-ready entries, normalized search keys, A–Z bucketing, facets, stats, and the bibliography. Pure functions over dicts. No I/O. |
| `src/langpipe/lexicon/exporters/printable.py` | **Rewrite.** Renders the print template (HTML+CSS) from session entries. No field logic. |
| `src/langpipe/lexicon/exporters/pdf.py` | **New.** Drives WeasyPrint over the print template. No layout logic. |
| `src/langpipe/lexicon/exporters/__init__.py` | **Modify.** Wire the PDF exporter into `export_all_formats`; keep the existing return keys. |
| `assets/fonts/Charis-Regular.woff2` etc. | **New.** Self-hosted Charis SIL 7.000 (OFL-1.1). |
| `assets/fonts/LICENSE-Charis.txt` | **New.** The OFL-1.1 licence text that ships with the font. |
| `exports/web/dictionary.js` | **New.** Web-side search, A–Z browse, entry rendering, Simple/Expert toggle. Plain ES2020, no bundler. |
| `exports/web/index.html` | **Modify.** New nav tab, new `pane-dictionary` section, new CSS block, new i18n keys, wire the tab. |
| `exports/web/server.py` | **Modify.** New endpoints `/api/dictionary/session` and `/api/dictionary/print`; fix the 404 `/formats/*` links. |
| `tests/unit/test_lexicon_dictionary_session.py` | **New.** Builder unit tests. |
| `tests/unit/test_lexicon_exporters.py` | **Modify.** Extend with print-template assertions. |
| `tests/unit/test_lexicon_print_pdf.py` | **New.** PDF smoke test (skips when toolchain absent). |
| `tests/unit/test_web_dictionary_api.py` | **New.** Server endpoint tests. |
| `docs/adr/0027-dictionary-rendering-and-print-pipeline.md` | **New.** ADR recording the PDF engine + typeface choices. |
| `docs/research/dictionary-print-prior-art-2026-10.md` | **New.** The prior-art survey, with URLs. |
| `docs/adr/README.md` | **Modify.** Add the ADR-0027 row. |

---

## Data Facts (verified — do not re-derive, do not assume differently)

These were measured against the live exports on 2026-10-20. The plan's code depends on them.

- `exports/mzr/dictionary.json` — 1099 entries, 2.4 MB. Top-level keys: `language_code`, `language_name`, `language_family`, `glottocode`, `territory`, `rivers`, `contact_language`, `total_entries`, `lexicon`, `morphology`, `parallel_sentences`, `audit_summary`, `citations_stats`, `semantics_stats`.
- `exports/mzr/dictionary.clean.json` — 892 entries, 1.87 MB. Every entry has `use_scopes: ["grounding", "synthesis_prompt", "dictionary_export"]` and `lexical_class: "lemma"`.
- `exports/mzr/dictionary.reverse.json` — 714 contact headwords, 972 senses. Entry shape: `contact_headword`, `normalized_key`, `total_attestations`, `sense_count`, `senses[]` where each sense has `target_headword`, `pos`, `original_gloss`, `provenance`, `valence`, `inalienability`, `primary_domain`, `subdomains`, `attestation_count`, `sample_citation`.
- **Entry shape** (every key present on every entry): `headword`, `pos`, `glosses_por` (list of strings, exactly 1 for 891 of 892 entries), `status` (`supported` | `validated`), `provenance` (free-text string), `audit` (`audit_id`, `flags`, `headword`, `lexical_class`, `proper_noun_kind`, `reasons`, `related_entry`, `review_required`, `signals`, `use_scopes`), `citations` (list), `semantics` (`confidence`, `inalienability`, `primary_domain`, `rationale`, `subdomains`, `valence`), `example`, `trans`.
- **`example` and `trans` are derived from `citations[0]`.** For all 990 entries with citations, `example == citations[0].target_text` and `trans == citations[0].reference_text` (100%). They carry **no independent information**. The builder must read them from the citation, not treat them as a separate field.
- **Citations per entry:** 0 for 109 entries, 1 for 7 entries, **2 for 983 entries**. When there are 2, their `source_ref` values always differ (983/983). So the print edition can show two examples per entry, from two distinct sources.
- **Citation shape:** `citation_id`, `headword`, `matched_token`, `reference_text`, `score`, `source_ref`, `target_text`. `matched_token == headword` for 1943 of 1973 citations (30 are inflected surface forms).
- **`score`** is a float clustering score (1.5, 1.48, 1.46, …). It is *not* a probability and is **not** a confidence. Do not present it as one.
- **POS values present:** `noun` (1016), `verb` (56), `adj` (19), `pron` (3), `num` (2), `adv` (2), `verb_intransitive` (1).
- **Status values present:** `supported` (955), `validated` (144) in the full export; in the clean view `supported` (748), `validated` (144).
- **Semantic domains:** `general` (743), `universe_nature` (32), `kinship_social` (29), `body_health` (28), `fauna` (19), `artifacts_tools` (15), `flora` (12), `actions_motion` (7), `perception_mind` (4), `quantity_state` (3).
- **Valence:** `non_verbal` (839), `transitive` (43), `intransitive` (9), `ditransitive` (1).
- **Orthography:** the only non-ASCII characters are `À Á Ã É Ê à á â ã ç é ê í ó ô õ ú ĩ Ẽ ẽ` plus typographic quotes and an en dash. **There is no IPA in the data.** Charis covers all of them (verified by parsing the font's `cmap`).
- **Letter buckets** under the normalized key: `A C E H I K M N O P R S T U V W Y`. Six headwords start with a nasal-vowel letter (`ẽa`, `ártemis`, `õpo`, `õsi`, `ãwẽnátserã`, `õsipa`) and must bucket under `A`/`E`/`O` after normalization.
- **`audit.related_entry`** is set on 63 entries (e.g. `berequiasnẽ` → `berequias`) — always an inflected form pointing at its lemma. **63 entries total**; in the clean view these are filtered out (clean view is all `lemma`).
- **Bibliography from provenance:** parsing `provenance` on `;` and stripping the `ex: …` tail yields **18 distinct works** (e.g. `Costa (1993, 2000)`, `Costa (2002)`, `Cesarino (2013)`, `Soares (2006)`, `Melatti (1985)`, `Melatti (1986)`, plus 5 unparseable fragments that must be handled gracefully). 955 of the 1073 distinct provenance strings are `Corpus alignment (…)` and are **not** bibliography works — they are per-citation provenance, already carried by `citations[].source_ref`.
- **Morphology:** `exports/mzr/dictionary.json` → `morphology` is a list of 12 dicts with `morpheme`, `gloss`, `function`.
- **Parallel sentences:** `parallel_sentences` is a list of 8 dicts with `marubo`, `igt_gloss`, `portugues`, `source`.
- **No audio files exist anywhere in the repository**, and no IPA field exists. Do not build a pronunciation or audio UI — it would render empty. (Recorded as a data gap in the spec, §10.)
- **Reverse index attestation counts** (`total_attestations`): 133 entries at 0, and the rest 1–22. Used for the Simple-view ranking of reverse-direction results.

---

## Task 1: Self-hosted Charis SIL font assets

**Files:**
- Create: `assets/fonts/Charis-Regular.woff2`, `assets/fonts/Charis-Bold.woff2`, `assets/fonts/Charis-Italic.woff2`
- Create: `assets/fonts/LICENSE-Charis.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: three `.woff2` files at `assets/fonts/` referenced by later tasks as `assets/fonts/Charis-<Weight>.woff2`, plus `assets/fonts/LICENSE-Charis.txt`.

- [ ] **Step 1: Create the fonts directory and download Charis SIL 7.000**

Charis SIL 7.000 is OFL-1.1 licensed. Download the official release archive from the SIL font repository:

```bash
cd /home/luandro/Dev/AI/language-distillation
mkdir -p assets/fonts
curl -sL -o /tmp/opencode/charis.zip \
  "https://github.com/silnrsi/font-charis/releases/download/v7.000/Charis-7.000.zip"
unzip -o -q /tmp/opencode/charis.zip -d /tmp/opencode/charis
ls /tmp/opencode/charis/Charis-7.000/*.ttf
```

Expected: `Charis-Regular.ttf`, `Charis-Bold.ttf`, `Charis-Italic.ttf` (among others) exist under `/tmp/opencode/charis/Charis-7.000/`.

- [ ] **Step 2: Convert the three needed faces to `.woff2` and copy them into the repository**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python - <<'PY'
import shutil
from pathlib import Path
from fontTools.ttLib import TTFont

SRC = Path("/tmp/opencode/charis/Charis-7.000")
DST = Path("assets/fonts")
DST.mkdir(parents=True, exist_ok=True)

for weight in ("Regular", "Bold", "Italic"):
    font = TTFont(SRC / f"Charis-{weight}.ttf")
    font.flavor = "woff2"
    out = DST / f"Charis-{weight}.woff2"
    font.save(out)
    print("wrote", out, out.stat().st_size, "bytes")
PY
ls -la assets/fonts/
```

Expected: three `.woff2` files, each roughly 300–340 KB.

- [ ] **Step 3: Copy the OFL-1.1 licence text into the repository**

The licence text ships inside the Charis release as `LICENSE` / `OFL.txt` in the archive root. Copy whichever exists:

```bash
cd /home/luandro/Dev/AI/language-distillation
for f in /tmp/opencode/charis/Charis-7.000/OFL.txt \
         /tmp/opencode/charis/Charis-7.000/LICENSE \
         /tmp/opencode/charis/Charis-7.000/LICENSE.txt \
         /tmp/opencode/charis/OFL.txt; do
  if [ -f "$f" ]; then
    cp "$f" assets/fonts/LICENSE-Charis.txt
    echo "copied from $f"
    break
  fi
done
test -f assets/fonts/LICENSE-Charis.txt && head -3 assets/fonts/LICENSE-Charis.txt
```

If none of those paths exist, fetch the canonical OFL-1.1 text instead:

```bash
curl -sL -o assets/fonts/LICENSE-Charis.txt "https://openfontlicense.org/documents/OFL.txt"
head -3 assets/fonts/LICENSE-Charis.txt
```

Expected: the file is the OFL-1.1 text. **Note the layout** — the file does *not*
begin with the `SIL OPEN FONT LICENSE Version 1.1` banner. Both the release's
`OFL.txt` and the canonical `https://openfontlicense.org/documents/OFL.txt` start
with a copyright header:

```
Copyright (c) 1997-2025 SIL Global (https://www.sil.org/)
with Reserved Font Names "Charis" and "SIL".
```

and the `SIL OPEN FONT LICENSE Version 1.1` banner is around line 10. (This was
verified by running the step: the brief's original `head -3` expectation was
wrong about OFL layout, not about the download.) The release copy is preferred
over the canonical fallback because it carries the real copyright holder and the
Reserved Font Names.

Verify the licence is complete and correct with:

```bash
cd /home/luandro/Dev/AI/language-distillation
grep -n "SIL OPEN FONT LICENSE Version 1.1" assets/fonts/LICENSE-Charis.txt
grep -nE "^(PREAMBLE|DEFINITIONS|PERMISSION & CONDITIONS|TERMINATION|DISCLAIMER)" \
  assets/fonts/LICENSE-Charis.txt
```

- [ ] **Step 4: Verify the fonts cover the Marúbo orthography**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python - <<'PY'
from fontTools.ttLib import TTFont

REQUIRED = {
    "ẽ": 0x1EBD, "ĩ": 0x0129, "ã": 0x00E3, "õ": 0x00F5,
    "á": 0x00E1, "é": 0x00E9, "í": 0x00ED, "ó": 0x00F3, "ú": 0x00FA,
    "ç": 0x00E7, "â": 0x00E2, "ê": 0x00EA, "ô": 0x00F4, "À": 0x00C0,
    "É": 0x00C9, "Ẽ": 0x1EBC, "Ã": 0x00C3, "Ĩ": 0x0128,
    "“": 0x201C, "”": 0x201D, "–": 0x2013,
}
IPA = {"ɯ": 0x026F, "ʔ": 0x0294, "ɹ": 0x0279, "ʃ": 0x0283,
       "ˈ": 0x02C8, "ˌ": 0x02CC, "ː": 0x02D0}

for weight in ("Regular", "Bold", "Italic"):
    f = TTFont(f"assets/fonts/Charis-{weight}.woff2")
    cmap = f.getBestCmap()
    missing = [c for c, cp in {**REQUIRED, **IPA}.items() if cp not in cmap]
    assert not missing, f"Charis-{weight} missing {missing}"
    print(f"Charis-{weight}: all {len(REQUIRED) + len(IPA)} required codepoints present")

# small caps feature must exist on Regular
f = TTFont("assets/fonts/Charis-Regular.woff2")
feats = {r.FeatureTag for r in f["GSUB"].table.FeatureList.FeatureRecord}
assert "smcp" in feats, "Charis-Regular has no smcp small-caps feature"
print("Charis-Regular: smcp small-caps feature present")
PY
```

Expected: three `all N required codepoints present` lines and one `smcp` line. No assertion errors.

- [ ] **Step 5: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add assets/fonts/
git commit -m "feat(assets): vendor Charis SIL 7.000 webfonts for the print edition

Charis is the de-facto standard for linguistic publishing: full IPA
coverage, real smcp small caps, OFL-1.1 so it may be embedded and
redistributed. The print edition must not depend on a font CDN."
```

---

## Task 2: `DictionarySessionBuilder`

**Files:**
- Create: `src/langpipe/lexicon/dictionary/__init__.py`
- Create: `src/langpipe/lexicon/dictionary/session.py`
- Test: `tests/unit/test_lexicon_dictionary_session.py`

**Interfaces:**
- Consumes: `langpipe.lexicon.reverse.normalize_search_key(text: str) -> str` (existing, `src/langpipe/lexicon/reverse.py:26`).
- Produces:
  - `langpipe.lexicon.dictionary.session.DictionarySessionBuilder` with:
    - `__init__(self, target_lang: str = "und", target_name: str = "Language", contact_lang: str = "por", contact_name: str = "Português", language_family: str = "", glottocode: str = "", territory: str = "") -> None`
    - `build(self, entries: list[dict[str, Any]], *, morphology: list[dict[str, Any]] | None = None, parallel_sentences: list[dict[str, Any]] | None = None) -> dict[str, Any]`
  - `langpipe.lexicon.dictionary.session.normalize_key(text: str) -> str` — module-level re-export of the normalizer, so the web layer and print layer can import one name.
  - The returned session dict has this exact shape:
    ```python
    {
      "meta": {
        "target_lang": str, "target_name": str, "contact_lang": str, "contact_name": str,
        "language_family": str, "glottocode": str, "territory": str,
        "total_entries": int, "total_letters": int,
        "generated_from": str,
      },
      "entries": [ Entry, ... ],           # sorted by normalized headword
      "letters": [ {"letter": "A", "count": int}, ... ],
      "facets": {
        "pos": [ {"value": str, "count": int}, ... ],
        "domain": [ {"value": str, "count": int}, ... ],
        "status": [ {"value": str, "count": int}, ... ],
      },
      "morphology": [ {"morpheme": str, "gloss": str, "function": str}, ... ],
      "parallel_sentences": [ {...}, ... ],
      "bibliography": [ {"index": int, "label": str, "author": str, "years": str}, ... ],
    }
    ```
  - Each `Entry` is:
    ```python
    {
      "headword": str,
      "search_key": str,          # normalized, accent-stripped, lowercased
      "letter": str,              # bucket letter, always A-Z
      "pos": str,
      "glosses": [str, ...],      # never collapsed
      "status": str,              # "supported" | "validated" | whatever the data says
      "provenance": str,
      "examples": [
        {"source_ref": str, "target_text": str, "reference_text": str,
         "matched_token": str, "score": float, "citation_id": str},
        ...
      ],
      "domain": str,              # semantics.primary_domain or "general"
      "valence": str,
      "inalienability": str,
      "confidence": float,
      "related_entry": str | None,
      "lexical_class": str,
      "flags": [str, ...],
      "reasons": [str, ...],
      "attestations": int,        # len(examples)
    }
    ```

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_lexicon_dictionary_session.py`:

```python
"""Unit tests for the DictionarySessionBuilder (dictionary session + print edition)."""

from __future__ import annotations

from langpipe.lexicon.dictionary.session import DictionarySessionBuilder, normalize_key


def _entry(headword: str, **overrides):
    base = {
        "headword": headword,
        "pos": "noun",
        "glosses_por": ["glosa"],
        "status": "supported",
        "provenance": "Costa (2002)",
        "audit": {
            "lexical_class": "lemma",
            "flags": [],
            "reasons": [],
            "related_entry": None,
            "use_scopes": ["grounding"],
        },
        "citations": [],
        "semantics": {
            "confidence": 0.8,
            "primary_domain": "general",
            "valence": "non_verbal",
            "inalienability": "not_applicable",
            "subdomains": [],
        },
        "example": "",
        "trans": "",
    }
    base.update(overrides)
    return base


def _citation(ref: str, target: str, reference: str, score: float = 1.5):
    return {
        "citation_id": f"cid-{ref}",
        "headword": "x",
        "matched_token": "x",
        "source_ref": ref,
        "target_text": target,
        "reference_text": reference,
        "score": score,
    }


# --- normalization ---------------------------------------------------------

def test_normalize_key_strips_accents_and_case():
    assert normalize_key("coração") == "coracao"
    assert normalize_key("CORACAO") == "coracao"
    assert normalize_key("ẽa") == "ea"


def test_search_key_is_normalized_but_headword_is_preserved():
    session = DictionarySessionBuilder().build([_entry("ẽa", glosses_por=["eu"])])
    entry = session["entries"][0]
    assert entry["headword"] == "ẽa"
    assert entry["search_key"] == "ea"


def test_search_key_collapses_normalized_variants():
    """'é' and 'e' share a search key; the display form must not change."""
    session = DictionarySessionBuilder().build(
        [_entry("mẽvi"), _entry("mevi")]
    )
    keys = [e["search_key"] for e in session["entries"]]
    assert keys == ["mevi", "mevi"]
    heads = [e["headword"] for e in session["entries"]]
    assert set(heads) == {"mẽvi", "mevi"}


# --- letter bucketing -----------------------------------------------------

def test_letter_bucket_uses_normalized_key_not_raw_char():
    """'á' must bucket under A, not under a separate 'Á' bucket."""
    session = DictionarySessionBuilder().build([_entry("árvore")])
    assert session["entries"][0]["letter"] == "A"
    assert [l["letter"] for l in session["letters"]] == ["A"]


def test_nasal_vowel_headwords_bucket_by_base_letter():
    session = DictionarySessionBuilder().build(
        [_entry("ẽa"), _entry("õpo"), _entry("ártemis")]
    )
    buckets = {e["headword"]: e["letter"] for e in session["entries"]}
    assert buckets["ẽa"] == "E"
    assert buckets["õpo"] == "O"
    assert buckets["ártemis"] == "A"


def test_letters_are_sorted_and_carry_counts():
    session = DictionarySessionBuilder().build(
        [_entry("mama"), _entry("mimi"), _entry("papa")]
    )
    assert session["letters"] == [
        {"letter": "M", "count": 2},
        {"letter": "P", "count": 1},
    ]


# --- ordering -------------------------------------------------------------

def test_entries_sorted_by_normalized_key():
    session = DictionarySessionBuilder().build(
        [_entry("õpo"), _entry("aakase"), _entry("nukẽ")]
    )
    assert [e["search_key"] for e in session["entries"]] == [
        "aakase",
        "nuke",
        "opo",
    ]


# --- evidence preservation ------------------------------------------------

def test_status_is_preserved_verbatim():
    session = DictionarySessionBuilder().build(
        [_entry("waka", status="validated"), _entry("mama", status="candidate")]
    )
    by_head = {e["headword"]: e["status"] for e in session["entries"]}
    assert by_head["waka"] == "validated"
    assert by_head["mama"] == "candidate"


def test_glosses_are_never_collapsed_into_one_string():
    session = DictionarySessionBuilder().build(
        [_entry("waka", glosses_por=["água", "rio"])]
    )
    assert session["entries"][0]["glosses"] == ["água", "rio"]


def test_examples_are_built_from_citations():
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "waka",
                citations=[
                    _citation("GEN 1:1", "waka yapa", "a água boa", 1.5),
                    _citation("ACT 9:12", "waka ura", "a água longe", 1.48),
                ],
            )
        ]
    )
    entry = session["entries"][0]
    assert entry["attestations"] == 2
    assert [ex["source_ref"] for ex in entry["examples"]] == ["GEN 1:1", "ACT 9:12"]
    assert entry["examples"][0]["target_text"] == "waka yapa"
    assert entry["examples"][0]["reference_text"] == "a água boa"
    assert entry["examples"][0]["score"] == 1.5


def test_entry_without_citations_has_no_examples():
    session = DictionarySessionBuilder().build([_entry("waka")])
    assert session["entries"][0]["examples"] == []
    assert session["entries"][0]["attestations"] == 0


def test_example_ignores_stale_top_level_example_field():
    """`example`/`trans` duplicate citations[0]; citations are the source of truth."""
    session = DictionarySessionBuilder().build(
        [
            _entry(
                "waka",
                example="STALE",
                trans="STALE",
                citations=[_citation("GEN 1:1", "waka yapa", "a água boa")],
            )
        ]
    )
    assert session["entries"][0]["examples"][0]["target_text"] == "waka yapa"


def test_related_entry_is_carried_through():
    session = DictionarySessionBuilder().build(
        [_entry("berequiasnẽ", audit={
            "lexical_class": "inflected_form",
            "flags": [],
            "reasons": [],
            "related_entry": "berequias",
            "use_scopes": [],
        })]
    )
    assert session["entries"][0]["related_entry"] == "berequias"
    assert session["entries"][0]["lexical_class"] == "inflected_form"


def test_audit_flags_and_reasons_are_carried_through():
    session = DictionarySessionBuilder().build(
        [_entry("x", audit={
            "lexical_class": "proper_noun",
            "flags": ["gloss_is_name"],
            "reasons": ["gloss looks like a name"],
            "related_entry": None,
            "use_scopes": [],
        })]
    )
    assert session["entries"][0]["flags"] == ["gloss_is_name"]
    assert session["entries"][0]["reasons"] == ["gloss looks like a name"]


# --- facets and stats -----------------------------------------------------

def test_facets_count_matches_entries():
    session = DictionarySessionBuilder().build(
        [
            _entry("a", pos="noun", status="validated"),
            _entry("b", pos="noun", status="supported"),
            _entry("c", pos="verb", status="supported"),
        ]
    )
    pos = {f["value"]: f["count"] for f in session["facets"]["pos"]}
    status = {f["value"]: f["count"] for f in session["facets"]["status"]}
    assert pos == {"noun": 2, "verb": 1}
    assert status == {"validated": 1, "supported": 2}
    assert sum(pos.values()) == len(session["entries"])


def test_domain_facet_defaults_to_general():
    session = DictionarySessionBuilder().build([_entry("a")])
    assert session["entries"][0]["domain"] == "general"


def test_meta_reports_totals():
    session = DictionarySessionBuilder(
        target_lang="mzr", target_name="Marúbo", contact_lang="por"
    ).build([_entry("a"), _entry("b")])
    assert session["meta"]["target_lang"] == "mzr"
    assert session["meta"]["target_name"] == "Marúbo"
    assert session["meta"]["total_entries"] == 2
    # 'a' and 'b' are two different letter buckets.
    assert session["meta"]["total_letters"] == 2


# --- bibliography ---------------------------------------------------------

def test_bibliography_deduplicates_works_and_orders_by_use():
    session = DictionarySessionBuilder().build(
        [
            _entry("a", provenance="Costa (2002); ex: a x"),
            _entry("b", provenance="Costa (2002); ex: b x"),
            _entry("c", provenance="Cesarino (2013); ex: c x"),
            _entry("d", provenance="Costa (1993, 2000) [ASJP]; ex: d x"),
        ]
    )
    labels = [b["label"] for b in session["bibliography"]]
    assert "Costa (2002)" in labels
    assert "Costa (1993, 2000)" in labels
    assert "Cesarino (2013)" in labels
    assert len(labels) == len(set(labels)), "bibliography must be de-duplicated"
    # most-cited work first
    assert labels[0] == "Costa (2002)"


def test_bibliography_ignores_corpus_alignment_provenance():
    session = DictionarySessionBuilder().build(
        [_entry("a", provenance="Corpus alignment (ACT 21:25, co-oc=3, dice=1.00)")]
    )
    assert session["bibliography"] == []


def test_bibliography_cuts_example_tail_before_splitting():
    """The example tail contains its own semicolons; it must not leak into the works."""
    session = DictionarySessionBuilder().build(
        [
            _entry("kiya", provenance="Costa (2000b, 2002); ex: kiya-rantsha (avião; lit. barco longo)"),
            _entry("shava", provenance="Costa (1992, 2002); Cesarino (2013); ex: na-shava-ma (ontem; lit. este dia não)"),
        ]
    )
    labels = sorted(b["label"] for b in session["bibliography"])
    assert labels == ["Cesarino (2013)", "Costa (1992, 2002)", "Costa (2000b, 2002)"]
    for spurious in ("barco longo", "este dia", "kiya-rantsha", "avião"):
        assert not any(spurious in label for label in labels), labels


def test_bibliography_survives_unparseable_provenance():
    session = DictionarySessionBuilder().build(
        [_entry("a", provenance="USFM GEN")]
    )
    assert len(session["bibliography"]) == 1
    assert session["bibliography"][0]["author"] == "USFM GEN"


# --- optional sections ----------------------------------------------------

def test_morphology_and_parallel_sentences_pass_through():
    morph = [{"morpheme": "-n", "gloss": "ERG", "function": "Marcador ergativo"}]
    parallel = [{"marubo": "x", "igt_gloss": "y", "portugues": "z", "source": "GEN 1:1"}]
    session = DictionarySessionBuilder().build(
        [_entry("a")], morphology=morph, parallel_sentences=parallel
    )
    assert session["morphology"] == morph
    assert session["parallel_sentences"] == parallel


def test_build_is_deterministic():
    entries = [_entry("õpo"), _entry("aakase"), _entry("nukẽ")]
    first = DictionarySessionBuilder().build(entries)
    second = DictionarySessionBuilder().build(entries)
    assert first == second


def test_build_ignores_entries_without_headword():
    session = DictionarySessionBuilder().build(
        [_entry("a"), {"pos": "noun", "glosses_por": ["orphan"]}]
    )
    assert len(session["entries"]) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_lexicon_dictionary_session.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'langpipe.lexicon.dictionary'`.

- [ ] **Step 3: Create the package marker**

Create `src/langpipe/lexicon/dictionary/__init__.py`:

```python
"""Dictionary session builder: display-ready entries shared by web and print."""

from __future__ import annotations

from langpipe.lexicon.dictionary.session import (
    DictionarySessionBuilder,
    normalize_key,
)

__all__ = [
    "DictionarySessionBuilder",
    "normalize_key",
]
```

- [ ] **Step 4: Implement the builder**

Create `src/langpipe/lexicon/dictionary/session.py`:

```python
"""DictionarySessionBuilder: one display-ready entry model for web and print.

Both the portal's Dictionary tab and the print edition read the entries
produced here, so the screen and the printed book cannot disagree about
normalization, letter bucketing, or evidence status.

Pure functions over dicts: no filesystem, no network, no Marúbo-specific rules.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from langpipe.lexicon.reverse import normalize_search_key

# `Author (1993, 2000) [ASJP]` / `Costa (2002 ABRALIN)` / `Cesarino (2013:7)`
_SOURCE_RE = re.compile(r"^([A-ZÀ-Þ][A-Za-zÀ-ÿ'´\s]*?)\s*\(([^)]*)\)\s*(.*)$")
_YEAR_RE = re.compile(r"(\d{4}[a-z]?)")
_CORPUS_ALIGNMENT = "corpus alignment"

__all__ = ["DictionarySessionBuilder", "normalize_key"]


def normalize_key(text: str) -> str:
    """Accent-insensitive, case-insensitive key used for matching and bucketing."""
    return normalize_search_key(text or "")


def _letter_for(headword: str) -> str:
    """Bucket letter derived from the normalized key.

    'á' buckets under A, 'õpo' under O. The raw first character is never
    used: the precomposed nasal vowels would each get their own bucket.
    """
    key = normalize_key(headword)
    for ch in key:
        if ch.isalpha():
            return ch.upper()
    return "#"


def _split_works(provenance: str) -> list[tuple[str, str]]:
    """Parse a provenance string into (author, years) work references.

    The `ex:` example tail often contains its own semicolons and parentheses
    (e.g. "Costa (2000b, 2002); ex: kiya-rantsha (avião; lit. barco longo)"),
    so the example tail is cut BEFORE the remaining work clauses are split
    on semicolons. Splitting first would leak the example text into the
    bibliography as spurious works.
    """
    works: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # Cut the example tail first: everything from the first "ex:" onwards.
    head = (provenance or "").split("ex:")[0]

    for chunk in head.split(";"):
        piece = chunk.strip()
        if not piece or piece.lower().startswith(_CORPUS_ALIGNMENT):
            continue

        match = _SOURCE_RE.match(piece)
        if match:
            author = match.group(1).strip()
            years = ", ".join(sorted(set(_YEAR_RE.findall(match.group(2)))))
        else:
            author = piece
            years = ""

        key = (author, years)
        if key not in seen:
            seen.add(key)
            works.append(key)

    return works


class DictionarySessionBuilder:
    """Builds the display-ready dictionary session from canonical lexicon entries."""

    def __init__(
        self,
        target_lang: str = "und",
        target_name: str = "Language",
        contact_lang: str = "por",
        contact_name: str = "Português",
        language_family: str = "",
        glottocode: str = "",
        territory: str = "",
    ) -> None:
        self.target_lang = target_lang
        self.target_name = target_name
        self.contact_lang = contact_lang
        self.contact_name = contact_name
        self.language_family = language_family
        self.glottocode = glottocode
        self.territory = territory

    # -- entry construction -------------------------------------------------

    def _build_entry(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        headword = (raw.get("headword") or "").strip()
        if not headword:
            return None

        audit = raw.get("audit") or {}
        semantics = raw.get("semantics") or {}

        examples = []
        for citation in raw.get("citations") or []:
            examples.append(
                {
                    "citation_id": citation.get("citation_id", ""),
                    "source_ref": citation.get("source_ref", ""),
                    "target_text": citation.get("target_text", ""),
                    "reference_text": citation.get("reference_text", ""),
                    "matched_token": citation.get("matched_token", ""),
                    "score": citation.get("score", 0.0),
                }
            )

        glosses = raw.get(f"glosses_{self.contact_lang}") or raw.get("glosses") or []
        if isinstance(glosses, str):
            glosses = [glosses]

        return {
            "headword": headword,
            "search_key": normalize_key(headword),
            "letter": _letter_for(headword),
            "pos": raw.get("pos", ""),
            "glosses": list(glosses),
            "status": raw.get("status", ""),
            "provenance": raw.get("provenance", ""),
            "examples": examples,
            "domain": semantics.get("primary_domain") or "general",
            "valence": semantics.get("valence", ""),
            "inalienability": semantics.get("inalienability", ""),
            "confidence": semantics.get("confidence", 0.0),
            "related_entry": audit.get("related_entry"),
            "lexical_class": audit.get("lexical_class", "lemma"),
            "flags": list(audit.get("flags") or []),
            "reasons": list(audit.get("reasons") or []),
            "attestations": len(examples),
        }

    # -- facets -------------------------------------------------------------

    @staticmethod
    def _facet(values: list[str]) -> list[dict[str, Any]]:
        counter = Counter(values)
        return [
            {"value": value, "count": count}
            for value, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    # -- bibliography --------------------------------------------------------

    def _build_bibliography(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: Counter[tuple[str, str]] = Counter()
        for entry in entries:
            for work in _split_works(entry.get("provenance", "")):
                counter[work] += 1

        ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
        bibliography = []
        for index, ((author, years), count) in enumerate(ordered, start=1):
            label = f"{author} ({years})" if years else author
            bibliography.append(
                {
                    "index": index,
                    "label": label,
                    "author": author,
                    "years": years,
                    "count": count,
                }
            )
        return bibliography

    # -- public API ---------------------------------------------------------

    def build(
        self,
        entries: list[dict[str, Any]],
        *,
        morphology: list[dict[str, Any]] | None = None,
        parallel_sentences: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build the dictionary session payload from canonical lexicon entries."""
        built = [e for e in (self._build_entry(raw) for raw in entries) if e is not None]
        built.sort(key=lambda e: (e["search_key"], e["headword"]))

        letter_counts = Counter(e["letter"] for e in built)
        letters = [
            {"letter": letter, "count": letter_counts[letter]}
            for letter in sorted(letter_counts)
        ]

        return {
            "meta": {
                "target_lang": self.target_lang,
                "target_name": self.target_name,
                "contact_lang": self.contact_lang,
                "contact_name": self.contact_name,
                "language_family": self.language_family,
                "glottocode": self.glottocode,
                "territory": self.territory,
                "total_entries": len(built),
                "total_letters": len(letters),
                "generated_from": "exports/{lang}/dictionary.json".format(
                    lang=self.target_lang
                ),
            },
            "entries": built,
            "letters": letters,
            "facets": {
                "pos": self._facet([e["pos"] for e in built]),
                "domain": self._facet([e["domain"] for e in built]),
                "status": self._facet([e["status"] for e in built]),
            },
            "morphology": list(morphology or []),
            "parallel_sentences": list(parallel_sentences or []),
            "bibliography": self._build_bibliography(built),
        }
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_lexicon_dictionary_session.py -q
```

Expected: all tests pass. If `test_bibliography_survives_unparseable_provenance` fails because the unparseable fragment was dropped, re-check that the `else` branch of `_split_works` appends the raw piece as the author — it must, so the fragment is not silently dropped.

- [ ] **Step 6: Verify against the real export**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python - <<'PY'
import json
from langpipe.lexicon.audit.view import LexiconView
from langpipe.lexicon.dictionary.session import DictionarySessionBuilder

raw = json.load(open("exports/mzr/dictionary.json", encoding="utf-8"))
view = LexiconView(raw, view="clean")
builder = DictionarySessionBuilder(
    target_lang="mzr",
    target_name=raw["language_name"],
    contact_lang=raw["contact_language"],
    language_family=raw["language_family"],
    glottocode=raw["glottocode"],
    territory=raw["territory"],
)
session = builder.build(
    view.entries,
    morphology=raw.get("morphology", []),
    parallel_sentences=raw.get("parallel_sentences", []),
)

assert session["meta"]["total_entries"] == 892, session["meta"]["total_entries"]
print("entries:", session["meta"]["total_entries"])
print("letters:", "".join(l["letter"] for l in session["letters"]))
print("bibliography:")
for b in session["bibliography"]:
    print(f"  {b['index']:2d}. {b['label']}  ({b['count']} entries)")
print("facets.pos:", session["facets"]["pos"])
print("facets.status:", session["facets"]["status"])

# Every entry must appear exactly once and carry its headword verbatim.
heads = [e["headword"] for e in session["entries"]]
assert len(heads) == len(set(heads)), "duplicate headwords"
for e in session["entries"]:
    assert e["search_key"] == e["search_key"].lower()
    assert e["letter"].isalpha() and e["letter"].isupper()
print("OK: 892 unique entries, all bucketed A-Z")
PY
```

Expected output (values must match exactly — these were verified against the live export):

```
entries: 892
letters: ACEHIKMNOPRSTUVWY
bibliography count: 14
   1. Costa (2002)  (50 entries)
   2. Costa (1993, 2000)  (38 entries)
   3. Cesarino (2013)  (24 entries)
   4. Soares (2006)  (18 entries)
   5. Costa (2000b)  (13 entries)
   6. Costa (2000b, 2002)  (13 entries)
   7. Costa (1992, 2002)  (7 entries)
   8. Costa (1992, 2000b, 2002)  (6 entries)
   9. Costa (1998, 2002)  (6 entries)
  10. Melatti (1985)  (2 entries)
  11. Melatti (1986)  (2 entries)
  12. Costa (1992, 1998, 2002)  (1 entries)
  13. Costa (1998, 2000b, 2002)  (1 entries)
  14. USFM GEN  (1 entries)
facets.pos: [{'value': 'noun', 'count': 815}, {'value': 'verb', 'count': 52}, {'value': 'adj', 'count': 17}, {'value': 'pron', 'count': 3}, {'value': 'adv', 'count': 2}, {'value': 'num', 'count': 2}, {'value': 'verb_intransitive', 'count': 1}]
facets.status: [{'value': 'supported', 'count': 748}, {'value': 'validated', 'count': 144}]
OK: unique entries, all bucketed A-Z
```

The bibliography must contain **14** works, and `Costa (2002)` must be first.

> **The `ex:` tail must be cut BEFORE splitting on `;`.** Provenance strings look like
> `Costa (2000b, 2002); ex: kiya-rantsha (avião; lit. barco longo)` — the example tail
> contains its own semicolons and parentheses. Splitting first leaks the example text
> into the bibliography as spurious works (`lit. barco longo)`, `nai mai vana`,
> `USFM GEN`, …). Cutting the tail first reduces the bibliography from 18 works to
> the 14 real ones.

- [ ] **Step 7: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add src/langpipe/lexicon/dictionary/ tests/unit/test_lexicon_dictionary_session.py
git commit -m "feat(lexicon): DictionarySessionBuilder for the web and print editions

One builder produces the display-ready entry list consumed by both the
portal's Dictionary tab and the print template, so the screen and the
book cannot disagree about normalization, letter bucketing, or evidence
status.

Letter bucketing uses the normalized key, fixing the pre-existing
hw[0].upper() bug that filed 'á' under 'Á' instead of 'A'."
```

---

## Task 3: Print template v2 (HTML + CSS)

**Files:**
- Modify: `src/langpipe/lexicon/exporters/printable.py` (full rewrite)
- Modify: `tests/unit/test_lexicon_exporters.py` (extend)

**Interfaces:**
- Consumes: `langpipe.lexicon.dictionary.session.DictionarySessionBuilder` (Task 2) and the `Entry` shape it produces. `Entry` keys: `headword`, `search_key`, `letter`, `pos`, `glosses`, `status`, `provenance`, `examples`, `domain`, `valence`, `inalienability`, `confidence`, `related_entry`, `lexical_class`, `flags`, `reasons`, `attestations`.
- Produces:
  - `PrintableDictionaryExporter.__init__(self, target_lang="und", target_name="Language", contact_lang="por", contact_name="Português", *, language_family="", glottocode="", territory="", fonts_dir: Path | str | None = None, edition_date: str = "")`
  - `PrintableDictionaryExporter.export(self, lexicon_entries: list[dict[str, Any]], output_path: Path | str, title: str | None = None, *, session: dict[str, Any] | None = None, morphology: list[dict[str, Any]] | None = None, parallel_sentences: list[dict[str, Any]] | None = None) -> Path`
    - When `session` is `None`, the exporter builds one internally from `lexicon_entries` — so the existing call signature keeps working.
  - The exporter **copies the needed font files** into `<output_dir>/fonts/` next to the HTML and references them with **relative** `url("fonts/…")`. This keeps the HTML self-contained and portable.

- [ ] **Step 1: Write the failing test additions**

Append to `tests/unit/test_lexicon_exporters.py`:

```python
def test_printable_exporter_uses_charis_and_guide_words(tmp_path: Path):
    from langpipe.lexicon.dictionary.session import DictionarySessionBuilder

    entries = [
        {
            "headword": "waka",
            "pos": "noun",
            "glosses_por": ["água", "rio"],
            "status": "validated",
            "provenance": "Costa (2002)",
            "audit": {"lexical_class": "lemma", "flags": [], "reasons": [],
                      "related_entry": None, "use_scopes": ["grounding"]},
            "semantics": {"primary_domain": "universe_nature", "valence": "non_verbal",
                          "inalienability": "not_applicable", "confidence": 0.9},
            "citations": [
                {"citation_id": "c1", "source_ref": "GEN 1:1",
                 "target_text": "waka ura-ka", "reference_text": "o rio é longe",
                 "matched_token": "waka", "score": 1.5},
            ],
        }
    ]
    session = DictionarySessionBuilder(target_lang="mzr", target_name="Marúbo").build(entries)

    out_file = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name="Marúbo", contact_lang="por",
        fonts_dir=Path(__file__).resolve().parents[2] / "assets" / "fonts",
    ).export(entries, out_file, session=session)

    content = out_file.read_text(encoding="utf-8")

    # Charis is the only typeface in the print path.
    assert "@font-face" in content
    assert "Charis" in content
    assert "Newsreader" not in content

    # Guide words must use the working WeasyPrint form.
    assert "string-set: gw content(text);" in content
    assert "string(gw, first)" in content
    assert "string(gw, last)" in content
    # The forms that were empirically proven broken must not reappear.
    assert "position: running(" not in content
    assert ":first-of-type" not in content
    # WeasyPrint 70 drops string-set on flex/grid items, so the headword row
    # must not be a flex container.
    assert "display: flex" not in content.split(".entry-head")[1][:200]

    # Cross-references and folios.
    assert "target-counter" in content
    assert "counter(page)" in content

    # Content.
    assert "waka" in content
    assert "água" in content
    assert "waka ura-ka" in content
    assert "GEN 1:1" in content

    # Front matter.
    assert "Prefácio" in content or "Preface" in content
    assert "Bibliografia" in content or "Bibliography" in content


def test_printable_exporter_buckets_letters_by_normalized_key(tmp_path: Path):
    entries = [
        {"headword": "ártemis", "pos": "noun", "glosses_por": ["artemis"],
         "status": "supported", "provenance": "Costa (2002)",
         "audit": {"lexical_class": "lemma", "flags": [], "reasons": [],
                   "related_entry": None, "use_scopes": ["grounding"]},
         "semantics": {}, "citations": []},
        {"headword": "mama", "pos": "noun", "glosses_por": ["mãe"],
         "status": "supported", "provenance": "Costa (2002)",
         "audit": {"lexical_class": "lemma", "flags": [], "reasons": [],
                   "related_entry": None, "use_scopes": ["grounding"]},
         "semantics": {}, "citations": []},
    ]
    out_file = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name="Marúbo", fonts_dir=tmp_path / "fonts",
    ).export(entries, out_file)

    content = out_file.read_text(encoding="utf-8")
    # The letter heading for A must exist, and no separate 'Á' heading.
    assert 'id="letter-A"' in content
    assert 'id="letter-Á"' not in content


def test_printable_exporter_numbers_bibliography_without_duplicates(tmp_path: Path):
    entries = [
        {"headword": "a", "pos": "noun", "glosses_por": ["x"], "status": "supported",
         "provenance": "Costa (2002); ex: a x",
         "audit": {"lexical_class": "lemma", "flags": [], "reasons": [],
                   "related_entry": None, "use_scopes": ["grounding"]},
         "semantics": {}, "citations": []},
        {"headword": "b", "pos": "noun", "glosses_por": ["y"], "status": "supported",
         "provenance": "Costa (2002); ex: b x",
         "audit": {"lexical_class": "lemma", "flags": [], "reasons": [],
                   "related_entry": None, "use_scopes": ["grounding"]},
         "semantics": {}, "citations": []},
    ]
    out_file = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name="Marúbo", fonts_dir=tmp_path / "fonts",
    ).export(entries, out_file)

    content = out_file.read_text(encoding="utf-8")
    # 'Costa (2002)' is cited twice but must be listed once.
    assert content.count("Costa (2002)") == 2, "one marker + one bibliography row"
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_lexicon_exporters.py -q
```

Expected: the three new tests fail (no `session` parameter, no Charis, no guide words).

- [ ] **Step 3: Rewrite the exporter**

Replace the whole of `src/langpipe/lexicon/exporters/printable.py` with:

```python
"""Print-ready dictionary book template (HTML + CSS) for physical publication.

Renders a scholarly two-column dictionary edition with running guide words,
small-caps part-of-speech labels, a numbered bibliography, and front/back
matter. The output is designed for WeasyPrint (see `langpipe.lexicon.exporters.pdf`)
but is also openable directly in a browser.

The template contains no entry semantics of its own: every field is read from
the session entries produced by `langpipe.lexicon.dictionary.session`.
"""

from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Any

from langpipe.lexicon.dictionary.session import DictionarySessionBuilder

FONT_FILES = {
    "400": "Charis-Regular.woff2",
    "700": "Charis-Bold.woff2",
    "italic 400": "Charis-Italic.woff2",
}

POS_LABELS = {
    "noun": "subst.",
    "verb": "verbo",
    "verb_intransitive": "verbo (intr.)",
    "verb_transitive": "verbo (trans.)",
    "adj": "adj.",
    "adjective": "adj.",
    "adv": "adv.",
    "adverb": "adv.",
    "pron": "pron.",
    "pronoun": "pron.",
    "num": "num.",
    "numeral": "num.",
    "part": "part.",
    "postp": "posp.",
    "interj": "interj.",
    "affix": "afixo",
    "clitic": "clítico",
    "root": "raiz",
    "prop": "n. próp.",
    "proper_noun": "n. próp.",
    "conj": "conj.",
    "dem": "dem.",
    "interrog": "interrog.",
    "ideo": "ideof.",
}

STATUS_MARKS = {
    "validated": "✓",
    "supported": "○",
    "candidate": "△",
}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


class PrintableDictionaryExporter:
    """Generates print-ready HTML/CSS for a physical dictionary book."""

    def __init__(
        self,
        target_lang: str = "und",
        target_name: str = "Language",
        contact_lang: str = "por",
        contact_name: str = "Português",
        *,
        language_family: str = "",
        glottocode: str = "",
        territory: str = "",
        fonts_dir: Path | str | None = None,
        edition_date: str = "",
    ) -> None:
        self.target_lang = target_lang
        self.target_name = target_name
        self.contact_lang = contact_lang
        self.contact_name = contact_name
        self.language_family = language_family
        self.glottocode = glottocode
        self.territory = territory
        self.fonts_dir = Path(fonts_dir) if fonts_dir else None
        self.edition_date = edition_date

    # -- fonts --------------------------------------------------------------

    def _stage_fonts(self, out_dir: Path) -> list[str]:
        """Copy the Charis faces next to the HTML; return @font-face CSS lines."""
        if self.fonts_dir is None or not self.fonts_dir.exists():
            return []
        font_dir = out_dir / "fonts"
        font_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for descriptor, filename in FONT_FILES.items():
            source = self.fonts_dir / filename
            if not source.exists():
                continue
            shutil.copy2(source, font_dir / filename)
            weight = "700" if "700" in descriptor else "400"
            style = "italic" if descriptor.startswith("italic") else "normal"
            lines.append(
                "@font-face {{ font-family: 'Charis'; src: url('fonts/{name}'); "
                "font-weight: {weight}; font-style: {style}; }}".format(
                    name=filename, weight=weight, style=style
                )
            )
        return lines

    # -- entry rendering ----------------------------------------------------

    def _render_example(self, example: dict[str, Any], index: int) -> str:
        target = example.get("target_text") or ""
        reference = example.get("reference_text") or ""
        ref = example.get("source_ref") or ""
        if not target and not reference:
            return ""
        parts = [f'<div class="example">']
        if target:
            parts.append(f'<div class="ex-target">{_esc(target)}</div>')
        if reference:
            parts.append(f'<div class="ex-ref">{_esc(reference)}</div>')
        if ref:
            parts.append(f'<div class="ex-src">({_esc(ref)})</div>')
        parts.append("</div>")
        return "".join(parts)

    def _render_entry(self, entry: dict[str, Any]) -> str:
        glosses = entry.get("glosses") or []
        gloss_html = "; ".join(_esc(g) for g in glosses)
        pos_label = POS_LABELS.get((entry.get("pos") or "").lower(), entry.get("pos") or "")
        domain = entry.get("domain") or "general"
        domain_tag = ""
        if domain and domain != "general":
            domain_tag = f'<span class="domain">{_esc(domain.replace("_", " "))}</span>'

        status = entry.get("status") or ""
        mark = STATUS_MARKS.get(status, "")
        status_html = f'<span class="status" title="{_esc(status)}">{mark}</span>' if mark else ""

        examples = [
            self._render_example(ex, i)
            for i, ex in enumerate((entry.get("examples") or [])[:1])
        ]
        examples_html = "".join(e for e in examples if e)

        related = entry.get("related_entry")
        related_html = ""
        if related:
            related_html = (
                f'<div class="see-also">ver <a href="#e-{_esc(related).lower()}">'
                f"{_esc(related)}</a></div>"
            )

        anchor = f"e-{entry.get('headword', '').lower()}"
        return (
            f'<div class="entry" id="{_esc(anchor)}">'
            f'<div class="entry-head">'
            f'<span class="headword">{_esc(entry.get("headword"))}</span>'
            f'<span class="pos">{_esc(pos_label)}</span>'
            f"{status_html}{domain_tag}"
            f"</div>"
            f'<div class="gloss">{gloss_html}</div>'
            f"{examples_html}{related_html}"
            f"</div>"
        )

    # -- front / back matter ------------------------------------------------

    def _render_title_page(self, title: str, session: dict[str, Any]) -> str:
        meta = session.get("meta", {})
        rows = [
            ("Língua", meta.get("target_name", "")),
            ("Código", meta.get("target_lang", "")),
            ("Glottocódigo", meta.get("glottocode", "")),
            ("Família", meta.get("language_family", "")),
            ("Território", meta.get("territory", "")),
            ("Língua de contato", meta.get("contact_name", "")),
            ("Verbetes", str(meta.get("total_entries", 0))),
        ]
        if self.edition_date:
            rows.append(("Edição", self.edition_date))
        rows_html = "".join(
            f'<div class="meta-row"><span class="meta-key">{_esc(k)}</span>'
            f'<span class="meta-val">{_esc(v)}</span></div>'
            for k, v in rows
            if v
        )
        return (
            '<div class="title-page">'
            f'<h1>{_esc(title)}</h1>'
            f'<div class="subtitle">Léxico atestado e base de conhecimento linguístico</div>'
            f'<div class="meta-table">{rows_html}</div>'
            "</div>"
        )

    def _render_preface(self, session: dict[str, Any]) -> str:
        meta = session.get("meta", {})
        return (
            '<div class="preface">'
            "<h2>Prefácio</h2>"
            "<p>Este dicionário reúne os verbetes atestados na Base de Conhecimento "
            "Linguístico do Vale do Javari. Ele é uma <em>edição de evidências</em>: "
            "cada verbete registra o que foi observado na fonte e onde foi observado, "
            "sem nunca apresentar uma hipótese como fato consumado.</p>"
            "<p>Os marcadores à direita de cada verbete indicam o grau de evidência: "
            "<span class='status'>✓</span> validado, "
            "<span class='status'>○</span> sustentado por evidência, "
            "<span class='status'>△</span> hipótese (candidato). "
            "Nenhuma hipótese é promovida a fato sem decisão de revisão registrada.</p>"
            "<p>Os exemplos são citações attestadas. Onde a fonte é um texto paralelo, "
            "a referência indica o versículo. A bibliografia ao final lista as obras "
            "a partir das quais os verbetes foram extraídos.</p>"
            f"<p class='preface-meta'>Língua: {meta.get('target_name', '')} · "
            f"Glottocódigo: {meta.get('glottocode', '')} · "
            f"Verbetes: {meta.get('total_entries', 0)}</p>"
            "</div>"
        )

    def _render_morphology(self, session: dict[str, Any]) -> str:
        morph = session.get("morphology") or []
        if not morph:
            return ""
        rows = "".join(
            "<tr>"
            f"<td class='morpheme'>{_esc(m.get('morpheme', ''))}</td>"
            f"<td class='gloss-leipzig'>{_esc(m.get('gloss', ''))}</td>"
            f"<td class='function'>{_esc(m.get('function', ''))}</td>"
            "</tr>"
            for m in morph
        )
        return (
            '<div class="morphology">'
            "<h2>Morfemas e clíticos</h2>"
            "<table><thead><tr><th>Morfema</th><th>Glosa</th><th>Função</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            "</div>"
        )

    def _render_bibliography(self, session: dict[str, Any]) -> str:
        bibliography = session.get("bibliography") or []
        if not bibliography:
            return ""
        rows = "".join(
            f'<li id="bib-{b["index"]}"><span class="bib-label">{_esc(b["label"])}</span>'
            f'<span class="bib-count">({b["count"]} verbetes)</span></li>'
            for b in bibliography
        )
        return (
            '<div class="bibliography">'
            "<h2>Bibliografia</h2>"
            f"<ol>{rows}</ol>"
            "</div>"
        )

    def _render_domain_index(self, session: dict[str, Any]) -> str:
        domain_facet = (session.get("facets") or {}).get("domain") or []
        domain_facet = [f for f in domain_facet if f["value"] != "general"]
        if not domain_facet:
            return ""
        rows = "".join(
            f'<li><span class="dom-name">{_esc(f["value"].replace("_", " "))}</span>'
            f'<span class="dom-count">{f["count"]}</span></li>'
            for f in domain_facet
        )
        return (
            '<div class="domain-index">'
            "<h2>Índice por domínio semântico</h2>"
            f"<ul>{rows}</ul>"
            "</div>"
        )

    def _render_body(self, session: dict[str, Any]) -> str:
        entries = session.get("entries") or []
        letters = session.get("letters") or []
        by_letter: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            by_letter.setdefault(entry["letter"], []).append(entry)

        sections = []
        for letter_info in letters:
            letter = letter_info["letter"]
            blocks = "".join(
                self._render_entry(e) for e in by_letter.get(letter, [])
            )
            sections.append(
                f'<div class="letter-section" id="letter-{_esc(letter)}">'
                f'<div class="letter-heading">{_esc(letter)}</div>'
                f'<div class="entries-columns">{blocks}</div>'
                "</div>"
            )
        return "".join(sections)

    # -- public API ---------------------------------------------------------

    def export(
        self,
        lexicon_entries: list[dict[str, Any]],
        output_path: Path | str,
        title: str | None = None,
        *,
        session: dict[str, Any] | None = None,
        morphology: list[dict[str, Any]] | None = None,
        parallel_sentences: list[dict[str, Any]] | None = None,
    ) -> Path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        doc_title = title or f"Dicionário {self.target_name} – {self.contact_name}"

        if session is None:
            builder = DictionarySessionBuilder(
                target_lang=self.target_lang,
                target_name=self.target_name,
                contact_lang=self.contact_lang,
                contact_name=self.contact_name,
                language_family=self.language_family,
                glottocode=self.glottocode,
                territory=self.territory,
            )
            session = builder.build(
                lexicon_entries,
                morphology=morphology,
                parallel_sentences=parallel_sentences,
            )

        font_css = self._stage_fonts(out.parent)

        html_content = self._render_document(doc_title, session, font_css)
        out.write_text(html_content, encoding="utf-8")
        return out

    def _render_document(
        self, doc_title: str, session: dict[str, Any], font_css: list[str]
    ) -> str:
        font_block = "\n    ".join(font_css) if font_css else ""
        font_stack = "'Charis', 'Charis SIL', 'Noto Serif', serif"
        if not font_css:
            font_stack = "'Noto Serif', serif"

        return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>{_esc(doc_title)}</title>
  <style>
    {font_block}

    @page {{
      size: A4 portrait;
      margin: 20mm 15mm 18mm 15mm;
      @top-left {{
        content: string(gw, first);
        font-family: {font_stack};
        font-style: italic;
        font-size: 8pt;
        color: #64748B;
      }}
      @top-right {{
        content: string(gw, last);
        font-family: {font_stack};
        font-style: italic;
        font-size: 8pt;
        color: #64748B;
      }}
      @bottom-center {{
        content: counter(page);
        font-family: {font_stack};
        font-size: 9pt;
        color: #334155;
      }}
    }}

    html {{
      font-family: {font_stack};
      font-size: 9.5pt;
      line-height: 1.32;
      color: #111827;
      background: #FFFFFF;
    }}
    body {{ margin: 0; padding: 0; }}

    /* ---- front matter ---- */
    .title-page {{
      page-break-after: always;
      text-align: center;
      padding-top: 70mm;
    }}
    .title-page h1 {{
      font-size: 25pt;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin: 0 0 5mm 0;
      color: #0F172A;
      font-weight: 700;
    }}
    .title-page .subtitle {{
      font-size: 12.5pt;
      font-style: italic;
      color: #475569;
    }}
    .meta-table {{
      margin: 22mm auto 0 auto;
      width: 70%;
      text-align: left;
      font-size: 9pt;
    }}
    .meta-row {{
      display: flex;
      justify-content: space-between;
      border-bottom: 0.4pt solid #E2E8F0;
      padding: 1.4mm 0;
    }}
    .meta-key {{
      color: #64748B;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 7.5pt;
      padding-top: 0.6mm;
    }}
    .meta-val {{ color: #0F172A; }}

    .preface, .morphology, .bibliography, .domain-index {{
      page-break-after: always;
    }}
    h2 {{
      font-size: 13pt;
      color: #0F172A;
      border-bottom: 1pt solid #0F172A;
      padding-bottom: 1.5mm;
      margin: 0 0 4mm 0;
      break-after: avoid;
      /* PDF outline (bookmarks) per section. Verified: WeasyPrint collects
         these into /Outlines with /Title entries. */
      bookmark-level: 1;
      bookmark-label: content(text);
    }}
    .preface p {{ text-align: justify; margin-bottom: 2.5mm; }}
    .preface-meta {{ color: #64748B; font-size: 8.5pt; }}

    table {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; }}
    th {{
      text-align: left;
      font-variant: small-caps;
      letter-spacing: 0.05em;
      color: #475569;
      border-bottom: 0.6pt solid #CBD5E1;
      padding: 1.2mm 2mm 1.2mm 0;
    }}
    td {{ padding: 1.2mm 2mm 1.2mm 0; border-bottom: 0.3pt solid #F1F5F9; }}
    td.morpheme {{ font-weight: 700; }}
    td.gloss-leipzig {{ font-variant: small-caps; }}

    /* ---- dictionary body ---- */
    .letter-section {{ margin-bottom: 6mm; }}
    .letter-heading {{
      font-size: 17pt;
      font-weight: 700;
      color: #0F172A;
      border-bottom: 1.5pt solid #0F172A;
      padding-bottom: 1mm;
      margin-bottom: 3mm;
      break-after: avoid;
      /* One PDF bookmark per letter, nested under the front matter. */
      bookmark-level: 2;
      bookmark-label: content(text);
    }}
    .entries-columns {{
      column-count: 2;
      column-gap: 7mm;
      column-rule: 0.4pt solid #E2E8F0;
    }}
    .entry {{
      break-inside: avoid;
      margin-bottom: 2.4mm;
    }}
    /* Guide words: string-set must sit on the headword span itself, and that
       span must NOT be a flex/grid item -- WeasyPrint 70 silently drops
       string-set for flex items. Use inline flow with margin spacing. */
    .headword {{
      string-set: gw content(text);
      font-weight: 700;
      color: #0F172A;
      font-size: 10.5pt;
    }}
    .entry-head {{ white-space: nowrap; }}
    .pos {{
      font-variant: small-caps;
      letter-spacing: 0.05em;
      color: #64748B;
      font-size: 8.5pt;
      margin-left: 1.2mm;
    }}
    .status {{ color: #94A3B8; font-size: 8.5pt; margin-left: 1mm; }}
    .domain {{
      font-variant: small-caps;
      letter-spacing: 0.05em;
      font-size: 7.5pt;
      color: #7C3AED;
      margin-left: 1mm;
    }}
    .gloss {{
      hyphens: auto;
      padding-left: 4mm;
      text-indent: -4mm;
      margin-top: 0.4mm;
    }}
    .example {{
      margin-top: 1mm;
      padding-left: 2mm;
      font-size: 8pt;
      line-height: 1.24;
      color: #334155;
      hyphens: auto;
    }}
    .ex-target {{ font-style: italic; color: #1E293B; }}
    .ex-ref {{ color: #475569; }}
    .ex-src {{ color: #B91C1C; font-size: 7pt; }}
    .see-also {{
      margin-top: 0.8mm;
      padding-left: 2mm;
      font-size: 8pt;
      font-variant: small-caps;
      letter-spacing: 0.04em;
      color: #64748B;
    }}
    .see-also a {{ color: #0F172A; text-decoration: none; }}
    .see-also a::after {{
      content: " (p. " target-counter(attr(href url), page) ")";
      color: #94A3B8;
      font-variant: normal;
    }}

    .bibliography ol {{ list-style: none; padding: 0; margin: 0; }}
    .bibliography li {{
      padding: 1.2mm 0;
      border-bottom: 0.3pt solid #F1F5F9;
      break-inside: avoid;
    }}
    .bib-label {{ font-weight: 600; color: #0F172A; }}
    .bib-count {{ color: #94A3B8; font-size: 8pt; margin-left: 2mm; }}

    .domain-index ul {{ list-style: none; padding: 0; margin: 0; }}
    .domain-index li {{
      display: flex;
      justify-content: space-between;
      padding: 1.2mm 0;
      border-bottom: 0.3pt solid #F1F5F9;
    }}
    .dom-name {{ font-variant: small-caps; letter-spacing: 0.04em; color: #0F172A; }}
    .dom-count {{ color: #94A3B8; font-size: 8.5pt; }}
  </style>
</head>
<body>
  {self._render_title_page(doc_title, session)}
  {self._render_preface(session)}
  {self._render_morphology(session)}
  {self._render_bibliography(session)}
  {self._render_body(session)}
  {self._render_domain_index(session)}
</body>
</html>
"""
```

- [ ] **Step 4: Run the exporter tests to verify they pass**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_lexicon_exporters.py -q
```

Expected: all tests pass, including the three new ones. If `test_printable_exporter_numbers_bibliography_without_duplicates` fails on the count, check that the bibliography row and the in-entry marker are the only two occurrences of the label string.

- [ ] **Step 5: Verify the guide-word CSS is exactly the working form**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python - <<'PY'
import re
from pathlib import Path
from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

out = Path("/tmp/opencode/guidecheck.html")
PrintableDictionaryExporter(
    target_lang="mzr", target_name="Marúbo",
    fonts_dir=Path("assets/fonts"),
).export(
    [
        {"headword": "waka", "pos": "noun", "glosses_por": ["água"], "status": "validated",
         "provenance": "Costa (2002)",
         "audit": {"lexical_class": "lemma", "flags": [], "reasons": [],
                   "related_entry": None, "use_scopes": ["grounding"]},
         "semantics": {"primary_domain": "universe_nature"}, "citations": []},
    ],
    out,
)
css = out.read_text(encoding="utf-8")
assert "string-set: gw content(text);" in css
assert "string(gw, first)" in css and "string(gw, last)" in css
assert "position: running(" not in css
assert ":first-of-type" not in css
# The headword must not be a flex item: WeasyPrint drops string-set for those.
headword_rule = css.split(".headword {")[1].split("}")[0]
assert "string-set: gw content(text);" in headword_rule
entry_head_rule = css.split(".entry-head {")[1].split("}")[0]
assert "display: flex" not in entry_head_rule
print("guide-word CSS: working form confirmed")
print("font files staged:", sorted(p.name for p in (out.parent / "fonts").glob("*")))
PY
```

Expected: `guide-word CSS: working form confirmed` and three `Charis-*.woff2` files staged.

> **Why the flex constraint matters.** WeasyPrint 70 evaluates `string-set` only on
> in-flow, non-flex/grid boxes. A `.entry-head { display: flex }` wrapper silently
> suppresses the guide word: the running head renders empty with no error. This was
> found by rendering the real two-column layout to PNG and comparing it against a
> non-flex variant of the same markup. The print template therefore uses inline flow
> with `margin-left` spacing on the sibling spans.

> **Note on the `string-set` value.** The CSS uses `content(text)`, which captures the element's *text* only (not the generated `::before`/`::after` content). The `string(gw, first)` / `string(gw, last)` lookups are what matter. Task 4 renders a real PDF and asserts the guide words are present in the output — that is the authoritative check.

- [ ] **Step 6: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add src/langpipe/lexicon/exporters/printable.py tests/unit/test_lexicon_exporters.py
git commit -m "feat(export): scholarly print template v2

Replaces the rough draft with a real dictionary edition: Charis SIL
(embeds IPA, has real small caps), running guide words, small-caps POS
labels, hanging-indent glosses, a numbered bibliography, and front and
back matter.

The guide-word CSS uses the only form verified to work in WeasyPrint
70 (string-set + string(name, first|last)); position: running() and
:first-of-type were tested and leave the running head empty."
```

---

## Task 4: WeasyPrint PDF driver

**Files:**
- Create: `src/langpipe/lexicon/exporters/pdf.py`
- Modify: `pyproject.toml` (add `weasyprint>=70,<71`)
- Modify: `uv.lock` (regenerated by `uv lock`)
- Test: `tests/unit/test_lexicon_print_pdf.py`

**Interfaces:**
- Consumes: `langpipe.lexicon.exporters.printable.PrintableDictionaryExporter` (Task 3) and the `session` dict from Task 2.
- Produces:
  - `langpipe.lexicon.exporters.pdf.render_pdf(html_path: Path | str, pdf_path: Path | str, *, base_url: str | None = None) -> Path` — renders an existing HTML file to PDF with WeasyPrint. Raises `PdfToolchainUnavailable` when WeasyPrint is not importable.
  - `langpipe.lexicon.exporters.pdf.PdfToolchainUnavailable(RuntimeError)`
  - `langpipe.lexicon.exporters.pdf.build_print_edition(entries, output_dir, *, target_lang, target_name, contact_lang, contact_name, language_family="", glottocode="", territory="", fonts_dir=None, edition_date="", session=None, morphology=None, parallel_sentences=None) -> dict[str, str]` — returns `{"html": str, "pdf": str, "entries": str}`. This is the single call the server and the CLI both use.

- [ ] **Step 1: Add weasyprint to the project dependencies**

```bash
cd /home/luandro/Dev/AI/language-distillation
uv add "weasyprint>=70,<71"
```

Expected: `pyproject.toml` gains `"weasyprint>=70,<71"` under `[project] dependencies`, and `uv.lock` is updated. The install must not require a compiler:

```bash
.venv/bin/python -c "import weasyprint; print('weasyprint', weasyprint.__version__)"
```

Expected: `weasyprint 70.0` (or a 70.x release).

- [ ] **Step 2: Write the failing PDF smoke test**

Create `tests/unit/test_lexicon_print_pdf.py`:

```python
"""PDF smoke test for the dictionary print edition.

Skipped when the optional PDF toolchain is absent so CI stays compiler-free.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from langpipe.lexicon.audit.view import LexiconView
from langpipe.lexicon.dictionary.session import DictionarySessionBuilder

REPO_ROOT = Path(__file__).resolve().parents[2]
FONTS_DIR = REPO_ROOT / "assets" / "fonts"

pytest.importorskip("weasyprint", reason="weasyprint is not installed")

HAS_PDFTOTEXT = shutil.which("pdftotext") is not None
HAS_PDFFONTS = shutil.which("pdffonts") is not None


def _mzr_entries():
    import json

    with open(REPO_ROOT / "exports" / "mzr" / "dictionary.json", encoding="utf-8") as f:
        raw = json.load(f)
    view = LexiconView(raw, view="clean")
    return raw, view.entries


def test_render_pdf_produces_a_valid_pdf(tmp_path: Path):
    from langpipe.lexicon.exporters.pdf import render_pdf
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    raw, entries = _mzr_entries()
    session = DictionarySessionBuilder(
        target_lang="mzr",
        target_name=raw["language_name"],
        contact_lang=raw["contact_language"],
        language_family=raw["language_family"],
        glottocode=raw["glottocode"],
        territory=raw["territory"],
    ).build(entries, morphology=raw.get("morphology", []))

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr",
        target_name=raw["language_name"],
        contact_lang=raw["contact_language"],
        fonts_dir=FONTS_DIR,
    ).export(entries, html_path, session=session)

    pdf_path = render_pdf(html_path, tmp_path / "book.pdf")

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 50_000
    assert pdf_path.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not HAS_PDFTOTEXT, reason="pdftotext is not available")
def test_pdf_text_preserves_marubo_diacritics(tmp_path: Path):
    """The no-.notdef-glyphs check: diacritics must survive to the PDF text layer."""
    from langpipe.lexicon.exporters.pdf import render_pdf
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    raw, entries = _mzr_entries()
    session = DictionarySessionBuilder(
        target_lang="mzr", target_name=raw["language_name"]
    ).build(entries)

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name=raw["language_name"], fonts_dir=FONTS_DIR
    ).export(entries, html_path, session=session)

    pdf_path = render_pdf(html_path, tmp_path / "book.pdf")
    text = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "ẽa" in text, "the nasal-vowel headword must survive into the PDF text layer"
    assert "wẽstisẽ" in text
    assert "nukẽ" in text


@pytest.mark.skipif(not HAS_PDFFONTS, reason="pdffonts is not available")
def test_pdf_embeds_charis(tmp_path: Path):
    from langpipe.lexicon.exporters.pdf import render_pdf
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    raw, entries = _mzr_entries()
    session = DictionarySessionBuilder(
        target_lang="mzr", target_name=raw["language_name"]
    ).build(entries)

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name=raw["language_name"], fonts_dir=FONTS_DIR
    ).export(entries, html_path, session=session)

    pdf_path = render_pdf(html_path, tmp_path / "book.pdf")
    fonts = subprocess.run(
        ["pdffonts", str(pdf_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "Charis" in fonts, fonts
    assert "yes" in fonts, "the font must be embedded"


@pytest.mark.skipif(not HAS_PDFTOTEXT, reason="pdftotext is not available")
def test_pdf_guide_words_appear_in_running_head(tmp_path: Path):
    """The running head must show the first and last headword on the page.

    This is the regression guard for a subtle WeasyPrint behaviour: a flex or
    grid container around the headword silently suppresses string-set, and the
    running head renders empty with no error.
    """
    from langpipe.lexicon.exporters.pdf import render_pdf
    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    entries = [
        {"headword": f"palavra{i:03d}", "pos": "noun", "glosses_por": [f"glosa {i}"],
         "status": "supported", "provenance": "Costa (2002)",
         "audit": {"lexical_class": "lemma", "flags": [], "reasons": [],
                   "related_entry": None, "use_scopes": ["grounding"]},
         "semantics": {"primary_domain": "general"}, "citations": []}
        for i in range(120)
    ]
    session = DictionarySessionBuilder(target_lang="mzr", target_name="Marúbo").build(entries)

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name="Marúbo", fonts_dir=FONTS_DIR
    ).export(entries, html_path, session=session)

    pdf_path = render_pdf(html_path, tmp_path / "book.pdf")
    text = subprocess.run(
        ["pdftotext", str(pdf_path), "-"], capture_output=True, text=True, check=True
    ).stdout

    # The first headword of the body appears in the body AND in the running
    # head of the first body page, so it must occur more than once.
    assert text.count("palavra000") >= 2, "guide word for the first entry is missing"
    # The last headword of the body appears in the body and in the running head
    # of the final body page.
    assert text.count("palavra119") >= 2, "guide word for the last entry is missing"


def test_build_print_edition_writes_html_and_pdf(tmp_path: Path):
    from langpipe.lexicon.exporters.pdf import build_print_edition

    raw, entries = _mzr_entries()
    result = build_print_edition(
        entries,
        tmp_path,
        target_lang="mzr",
        target_name=raw["language_name"],
        contact_lang=raw["contact_language"],
        contact_name="Português",
        language_family=raw["language_family"],
        glottocode=raw["glottocode"],
        territory=raw["territory"],
        fonts_dir=FONTS_DIR,
    )

    assert Path(result["html"]).exists()
    assert Path(result["pdf"]).exists()
    assert result["entries"] == str(len(entries))


def test_pdf_has_outline_bookmarks_per_section(tmp_path: Path):
    """The PDF must carry a navigable outline: sections at level 1, letters at level 2."""
    from weasyprint import HTML

    from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

    raw, entries = _mzr_entries()
    session = DictionarySessionBuilder(
        target_lang="mzr", target_name=raw["language_name"]
    ).build(entries, morphology=raw.get("morphology", []))

    html_path = tmp_path / "book.html"
    PrintableDictionaryExporter(
        target_lang="mzr", target_name=raw["language_name"], fonts_dir=FONTS_DIR
    ).export(entries, html_path, session=session)

    document = HTML(filename=str(html_path), base_url=str(tmp_path)).render()
    bookmarks = [b for page in document.pages for b in page.bookmarks]

    labels = [b[1] for b in bookmarks]
    levels = {b[1]: b[0] for b in bookmarks}

    assert "Prefácio" in labels
    assert "Bibliografia" in labels
    assert "Morfemas e clíticos" in labels
    # Every letter that has entries gets its own level-2 bookmark.
    for letter in ("A", "C", "E", "M", "N", "O", "P", "W", "Y"):
        assert letter in labels, f"missing bookmark for letter {letter}"
        assert levels[letter] == 2, f"letter {letter} should be level 2"
    assert levels["Prefácio"] == 1
    assert len(bookmarks) >= 20
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_lexicon_print_pdf.py -q
```

Expected: import error — `ModuleNotFoundError: No module named 'langpipe.lexicon.exporters.pdf'`.

- [ ] **Step 4: Implement the PDF driver**

Create `src/langpipe/lexicon/exporters/pdf.py`:

```python
"""WeasyPrint driver for the dictionary print edition.

Holds no layout logic: it renders the HTML produced by
`langpipe.lexicon.exporters.printable` and nothing else.

WeasyPrint is imported lazily so that `import langpipe.lexicon.exporters`
never requires the PDF toolchain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

__all__ = [
    "PdfToolchainUnavailable",
    "build_print_edition",
    "render_pdf",
]


class PdfToolchainUnavailable(RuntimeError):
    """Raised when WeasyPrint (or its system libraries) are not importable."""


def render_pdf(html_path: Path | str, pdf_path: Path | str, *, base_url: str | None = None) -> Path:
    """Render an HTML file to PDF with WeasyPrint."""
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - exercised only without the toolchain
        raise PdfToolchainUnavailable(
            "weasyprint is not available; install it with `uv sync` to build PDFs"
        ) from exc

    source = Path(html_path)
    target = Path(pdf_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    html = HTML(filename=str(source), base_url=base_url or str(source.parent))
    html.write_pdf(str(target))
    return target


def build_print_edition(
    entries: list[dict[str, Any]],
    output_dir: Path | str,
    *,
    target_lang: str,
    target_name: str,
    contact_lang: str,
    contact_name: str,
    language_family: str = "",
    glottocode: str = "",
    territory: str = "",
    fonts_dir: Path | str | None = None,
    edition_date: str = "",
    session: dict[str, Any] | None = None,
    morphology: list[dict[str, Any]] | None = None,
    parallel_sentences: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Build the print edition: HTML template + rendered PDF."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / f"dictionary_{target_lang}_printable.html"
    pdf_path = out_dir / f"dictionary_{target_lang}_printable.pdf"

    exporter = PrintableDictionaryExporter(
        target_lang=target_lang,
        target_name=target_name,
        contact_lang=contact_lang,
        contact_name=contact_name,
        language_family=language_family,
        glottocode=glottocode,
        territory=territory,
        fonts_dir=fonts_dir,
        edition_date=edition_date,
    )
    exporter.export(
        entries,
        html_path,
        session=session,
        morphology=morphology,
        parallel_sentences=parallel_sentences,
    )

    render_pdf(html_path, pdf_path)
    return {
        "html": str(html_path),
        "pdf": str(pdf_path),
        "entries": str(len(entries)),
    }
```

- [ ] **Step 5: Run the PDF tests to verify they pass**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_lexicon_print_pdf.py -q
```

Expected: all four tests pass. If `test_pdf_guide_words_appear_in_running_head` fails, the guide-word CSS is wrong — go back to Task 3 Step 5 and confirm `string-set: gw content(text);` is present on `.entry` and that `.entry` is the only element carrying it.

- [ ] **Step 6: Measure the render time and inspect a real page**

```bash
cd /home/luandro/Dev/AI/language-distillation
time .venv/bin/python - <<'PY'
import json, time
from pathlib import Path
from langpipe.lexicon.audit.view import LexiconView
from langpipe.lexicon.exporters.pdf import build_print_edition

raw = json.load(open("exports/mzr/dictionary.json", encoding="utf-8"))
view = LexiconView(raw, view="clean")
t0 = time.time()
result = build_print_edition(
    view.entries, "/tmp/opencode/printrun",
    target_lang="mzr", target_name=raw["language_name"],
    contact_lang=raw["contact_language"], contact_name="Português",
    language_family=raw["language_family"], glottocode=raw["glottocode"],
    territory=raw["territory"],
    fonts_dir=Path("assets/fonts"),
    morphology=raw.get("morphology", []),
)
print("elapsed %.1fs" % (time.time() - t0))
print(result)
PY
pdfinfo /tmp/opencode/printrun/dictionary_mzr_printable.pdf | grep -i pages
```

Expected: the render completes in **under 90 seconds** and the PDF has **at least 40 pages**.

Reference measurement taken on this machine with the plan's exact template (892 entries, one example each, `hyphens: auto`): **41 s, 60 pages**. The previous export produced 43 pages in ~80 s. If the render is much slower, check that:

1. `.example` and `.gloss` both have `hyphens: auto`;
2. the exporter slices `(entry.get("examples") or [])[:1]`;
3. `<html lang="pt-BR">` is present (Pyphen needs it for Portuguese patterns);
4. `.entry` still has `break-inside: avoid`.

- [ ] **Step 7: Render a page to PNG and look at it**

```bash
cd /home/luandro/Dev/AI/language-distillation
pdftoppm -r 100 -png -f 4 -l 4 /tmp/opencode/printrun/dictionary_mzr_printable.pdf /tmp/opencode/page
ls /tmp/opencode/page*
```

Then read `/tmp/opencode/page-04.png` with the image tool and confirm visually:

- two columns with a hairline rule between them;
- a running head showing the first and last headword in italic at the top left/right;
- a folio (page number) at the bottom centre;
- headwords in bold, POS in small caps, glosses indented, examples in italic with the source reference in small red type;
- the letter heading for the current letter is large with a rule under it.

If the running head is empty, the guide-word CSS is wrong — fix it before committing.

- [ ] **Step 8: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add pyproject.toml uv.lock src/langpipe/lexicon/exporters/pdf.py tests/unit/test_lexicon_print_pdf.py
git commit -m "feat(export): render the print edition to PDF with WeasyPrint

WeasyPrint 70 is a pure-Python dependency, so CI stays compiler-free.
The driver is import-guarded: langpipe.lexicon.exporters imports without
the PDF toolchain present.

The smoke test asserts Charis is embedded and that the Marubo nasal
vowel diacritics survive into the PDF text layer, which is the
no-.notdef-glyphs check."
```

---

## Task 5: Wire the print edition into `export_all_formats` and the CLI

**Files:**
- Modify: `src/langpipe/lexicon/exporters/__init__.py`
- Test: `tests/unit/test_lexicon_exporters.py` (extend)

**Interfaces:**
- Consumes: `build_print_edition` (Task 4), `DictionarySessionBuilder` (Task 2).
- Produces: `export_all_formats(lang_code, output_dir=None, view="clean")` gains a `"printable_pdf"` key alongside the existing `"lift"`, `"cldf"`, `"printable_html"`, and `"total_entries"` keys. The existing keys keep their meaning and paths. PDF generation is **best-effort**: if WeasyPrint is missing, the key is `""` and no exception propagates.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_lexicon_exporters.py`:

```python
def test_export_all_formats_includes_printable_pdf(tmp_path: Path):
    from langpipe.lexicon.exporters import export_all_formats

    result = export_all_formats("mzr", output_dir=tmp_path, view="clean")

    assert "lift" in result
    assert "cldf" in result
    assert "printable_html" in result
    assert Path(result["printable_html"]).exists()
    # The PDF key must always be present, even when the toolchain is absent.
    assert "printable_pdf" in result
    if result["printable_pdf"]:
        assert Path(result["printable_pdf"]).exists()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_lexicon_exporters.py::test_export_all_formats_includes_printable_pdf -q
```

Expected: `KeyError: 'printable_pdf'`.

- [ ] **Step 3: Update `export_all_formats`**

In `src/langpipe/lexicon/exporters/__init__.py`, replace the whole file with:

```python
"""Multi-format lexicographical exporters (Milestone 1, WP 1.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langpipe.lexicon.audit.view import LexiconView
from langpipe.lexicon.dictionary.session import DictionarySessionBuilder
from langpipe.lexicon.exporters.cldf import CldfDictionaryExporter
from langpipe.lexicon.exporters.lift import LiftExporter
from langpipe.lexicon.exporters.printable import PrintableDictionaryExporter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _fonts_dir() -> Path | None:
    """Locate the vendored Charis SIL webfonts, if present."""
    candidate = REPO_ROOT / "assets" / "fonts"
    return candidate if candidate.exists() else None


def export_all_formats(
    lang_code: str,
    output_dir: Path | str | None = None,
    view: str = "clean",
) -> dict[str, Any]:
    """Generate LIFT XML, CLDF tables, print-ready HTML, and the print PDF."""
    out = Path(output_dir) if output_dir else Path("exports") / lang_code / "formats"
    out.mkdir(parents=True, exist_ok=True)

    view_obj = LexiconView.load(lang_code=lang_code, view=view)
    entries = view_obj.entries
    contact_lang = getattr(view_obj, "contact_language", "por")
    lang_name = view_obj.language_name

    raw = view_obj.raw_data or {}

    # 1. LIFT XML
    lift_file = out / f"dictionary_{lang_code}.lift"
    LiftExporter(target_lang=lang_code, contact_lang=contact_lang).export(entries, lift_file)

    # 2. CLDF Tables
    cldf_dir = out / "cldf"
    cldf_files = CldfDictionaryExporter(target_lang=lang_code, contact_lang=contact_lang).export(
        entries, cldf_dir
    )

    # 3. Dictionary session (shared by the web tab and the print edition)
    builder = DictionarySessionBuilder(
        target_lang=lang_code,
        target_name=lang_name,
        contact_lang=contact_lang,
        language_family=raw.get("language_family", ""),
        glottocode=raw.get("glottocode", ""),
        territory=raw.get("territory", ""),
    )
    session = builder.build(
        entries,
        morphology=raw.get("morphology", []),
        parallel_sentences=raw.get("parallel_sentences", []),
    )

    # 4. Print-Ready HTML Book
    print_file = out / f"dictionary_{lang_code}_printable.html"
    PrintableDictionaryExporter(
        target_lang=lang_code,
        target_name=lang_name,
        contact_lang=contact_lang,
        contact_name="Português",
        language_family=raw.get("language_family", ""),
        glottocode=raw.get("glottocode", ""),
        territory=raw.get("territory", ""),
        fonts_dir=_fonts_dir(),
    ).export(entries, print_file, session=session)

    # 5. Print PDF (best-effort: the toolchain is optional)
    pdf_file = ""
    try:
        from langpipe.lexicon.exporters.pdf import build_print_edition

        result = build_print_edition(
            entries,
            out,
            target_lang=lang_code,
            target_name=lang_name,
            contact_lang=contact_lang,
            contact_name="Português",
            language_family=raw.get("language_family", ""),
            glottocode=raw.get("glottocode", ""),
            territory=raw.get("territory", ""),
            fonts_dir=_fonts_dir(),
            session=session,
            morphology=raw.get("morphology", []),
            parallel_sentences=raw.get("parallel_sentences", []),
        )
        pdf_file = result["pdf"]
    except Exception:
        pdf_file = ""

    return {
        "lift": str(lift_file),
        "cldf": cldf_files,
        "printable_html": str(print_file),
        "printable_pdf": pdf_file,
        "total_entries": len(entries),
    }


__all__ = [
    "CldfDictionaryExporter",
    "LiftExporter",
    "PrintableDictionaryExporter",
    "export_all_formats",
]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_lexicon_exporters.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Regenerate the real artifacts and confirm the PDF exists**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python - <<'PY'
from langpipe.lexicon.exporters import export_all_formats

result = export_all_formats("mzr", view="clean")
for key, value in result.items():
    print(f"{key}: {value}")
PY
ls -la exports/mzr/formats/
pdfinfo exports/mzr/formats/dictionary_mzr_printable.pdf | grep -i pages
```

Expected: `printable_pdf` points at an existing PDF of at least 40 pages, and `exports/mzr/formats/fonts/` contains the three Charis files.

- [ ] **Step 6: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add src/langpipe/lexicon/exporters/__init__.py tests/unit/test_lexicon_exporters.py
git add -f exports/mzr/formats/dictionary_mzr_printable.html exports/mzr/formats/dictionary_mzr_printable.pdf
git commit -m "feat(export): build the print edition from the shared session model

export_all_formats now derives the dictionary session once and hands it
to the print template, so the book and the web tab cannot disagree.
The PDF step is best-effort: without the optional toolchain the key is
empty and the other formats still export."
```

---

## Task 6: Server endpoints + fix the 404 artifact links

**Files:**
- Modify: `exports/web/server.py`
- Test: `tests/unit/test_web_dictionary_api.py`

**Interfaces:**
- Consumes: `langpipe.lexicon.dictionary.session.DictionarySessionBuilder` (Task 2), `langpipe.lexicon.exporters.pdf.build_print_edition` (Task 4), `langpipe.lexicon.audit.view.LexiconView` (existing).
- Produces:
  - `GET /api/dictionary/session?lang=mzr&view=clean` → the session dict from Task 2, plus a `"reverse"` key holding the reverse index entries. Cached in module state, invalidated when the source export's mtime changes.
  - `POST /api/dictionary/print` with body `{"lang": "mzr", "view": "clean"}` → `{"status": "success", "pdf": "<url path>", "html": "<url path>", "entries": 892, "pages": 57}`. The `pdf` value is a **URL path** the browser can download, e.g. `/formats/mzr/dictionary_mzr_printable.pdf`.
  - `GET /formats/<lang>/<filename>` → serves any file under `exports/<lang>/formats/`.
  - `GET /formats/mzr/dictionary_mzr.lift`, `/formats/mzr/formats/cldf/Dictionary-metadata.json` → the paths the Exports tab links to, which must now return **200** instead of **404**.

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_web_dictionary_api.py`:

```python
"""Request-level tests for the portal's dictionary endpoints."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = REPO_ROOT / "exports" / "web" / "server.py"


def _load_server_module():
    spec = importlib.util.spec_from_file_location("portal_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["portal_server"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def live_server():
    module = _load_server_module()
    httpd = HTTPServer(("127.0.0.1", 0), module.SyntheticLKBRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(base: str, path: str):
    with urllib.request.urlopen(f"{base}{path}", timeout=30) as resp:
        return resp.status, resp.read()


def test_session_endpoint_returns_entries(live_server: str):
    status, body = _get(live_server, "/api/dictionary/session?lang=mzr&view=clean")
    assert status == 200
    payload = json.loads(body)
    assert payload["meta"]["target_lang"] == "mzr"
    assert payload["meta"]["total_entries"] == 892
    assert len(payload["entries"]) == 892
    first = payload["entries"][0]
    for key in ("headword", "search_key", "letter", "pos", "glosses", "status",
                "examples", "domain", "attestations"):
        assert key in first, key
    assert payload["letters"], "the A-Z index must be present"
    assert payload["reverse"], "the reverse index must be present"


def test_session_entries_are_sorted_by_search_key(live_server: str):
    _, body = _get(live_server, "/api/dictionary/session?lang=mzr&view=clean")
    payload = json.loads(body)
    keys = [e["search_key"] for e in payload["entries"]]
    assert keys == sorted(keys)


def test_session_letter_buckets_are_normalized(live_server: str):
    _, body = _get(live_server, "/api/dictionary/session?lang=mzr&view=clean")
    payload = json.loads(body)
    letters = [l["letter"] for l in payload["letters"]]
    assert letters == sorted(letters)
    assert all(ch.isalpha() and ch.isupper() for ch in letters)
    # 'ártemis' must live under A, not under a separate 'Á'.
    by_head = {e["headword"]: e["letter"] for e in payload["entries"]}
    assert by_head["ártemis"] == "A"
    assert by_head["ẽa"] == "E"


@pytest.mark.parametrize(
    "artifact",
    [
        "/formats/mzr/dictionary_mzr.lift",
        "/formats/mzr/cldf/Dictionary-metadata.json",
        "/formats/mzr/dictionary_mzr_printable.html",
    ],
)
def test_advertised_artifact_links_resolve(live_server: str, artifact: str):
    """The Exports tab advertises these links; they must not 404."""
    status, _ = _get(live_server, artifact)
    assert status == 200, f"{artifact} returned {status}"


def test_formats_route_rejects_path_traversal(live_server: str):
    """The formats route must not serve files outside exports/<lang>/formats/."""
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(live_server, "/formats/mzr/../../../etc/passwd")
    assert excinfo.value.code == 404


def test_pdf_is_reachable_under_formats(live_server: str):
    """The print artifact must be downloadable once the edition has been built."""
    status, body = _get(live_server, "/formats/mzr/dictionary_mzr_printable.pdf")
    if status == 404:
        pytest.skip("the print edition has not been built yet")
    assert status == 200
    assert body[:5] == b"%PDF-"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_web_dictionary_api.py -q
```

Expected: `test_session_endpoint_returns_entries` fails with a **404** (the endpoint does not exist), and `test_advertised_artifact_links_resolve` fails with a **404** (the current bug).

- [ ] **Step 3: Add the session and print endpoints, and the formats route**

In `exports/web/server.py`, add these module-level constants after the existing `MZR_SYNTHETIC_STORE` line:

```python
FORMATS_ROOTS = {lang: (ROOT / "exports" / lang / "formats") for lang in ("mzr", "mcf", "mpu", "xor", "knm")}

_SESSION_CACHE: dict[str, tuple[float, dict]] = {}
```

Then add these methods to `SyntheticLKBRequestHandler`. Place them immediately after `_send_json`:

```python
    # -- dictionary session -------------------------------------------------

    def _build_session(self, lang: str, view: str) -> dict:
        """Build (and cache) the dictionary session payload."""
        from langpipe.lexicon.audit.view import LexiconView
        from langpipe.lexicon.dictionary.session import DictionarySessionBuilder

        source = EXPORTS_DIR / lang / "dictionary.json"
        mtime = source.stat().st_mtime if source.exists() else 0.0
        cache_key = f"{lang}:{view}"
        cached = _SESSION_CACHE.get(cache_key)
        if cached and cached[0] == mtime:
            return cached[1]

        view_obj = LexiconView.load(lang_code=lang, view=view)
        raw = view_obj.raw_data or {}
        builder = DictionarySessionBuilder(
            target_lang=lang,
            target_name=raw.get("language_name", lang),
            contact_lang=raw.get("contact_language", "por"),
            language_family=raw.get("language_family", ""),
            glottocode=raw.get("glottocode", ""),
            territory=raw.get("territory", ""),
        )
        session = builder.build(
            view_obj.entries,
            morphology=raw.get("morphology", []),
            parallel_sentences=raw.get("parallel_sentences", []),
        )

        session["reverse"] = self._load_reverse(lang)

        _SESSION_CACHE[cache_key] = (mtime, session)
        return session

    @staticmethod
    def _load_reverse(lang: str) -> list[dict]:
        """Read the reverse (contact -> target) index, building it if absent."""
        reverse_file = EXPORTS_DIR / lang / "dictionary.reverse.json"
        if not reverse_file.exists():
            from langpipe.lexicon.audit.view import LexiconView
            from langpipe.lexicon.reverse import ReverseLexiconIndex

            clean_view = LexiconView.load(lang_code=lang, view="clean")
            index = ReverseLexiconIndex(contact_language="por").build_from_lexicon(
                clean_view.entries
            )
            index.save_json(reverse_file, metadata={"language_code": lang})

        with open(reverse_file, encoding="utf-8") as f:
            return json.load(f).get("entries", [])

    def _serve_formats(self, parsed_path: str) -> bool:
        """Serve files under exports/<lang>/formats/. Returns True if handled."""
        parts = [p for p in parsed_path.strip("/").split("/") if p]
        if len(parts) < 3 or parts[0] != "formats":
            return False

        lang = parts[1]
        root = FORMATS_ROOTS.get(lang)
        if root is None:
            return False

        relative = Path(*parts[2:])
        if ".." in relative.parts:
            return False

        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            return False

        if not target.is_file():
            return False

        content_type = "application/octet-stream"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif target.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        elif target.suffix == ".pdf":
            content_type = "application/pdf"
        elif target.suffix == ".xml":
            content_type = "application/xml"
        elif target.suffix == ".lift":
            content_type = "application/xml"

        blob = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(blob)
        return True
```

In `do_GET`, insert the formats route **before** the final `super().do_GET()` fallback:

```python
        if self._serve_formats(parsed.path):
            return

        # Fallback to static file serving
        super().do_GET()
```

And add the session endpoint inside the `do_GET` chain, right after the `/api/dictionary/reverse` branch:

```python
        elif parsed.path == "/api/dictionary/session":
            query_params = parse_qs(parsed.query)
            lang = query_params.get("lang", ["mzr"])[0].lower()
            view_mode = query_params.get("view", ["clean"])[0].lower()
            try:
                self._send_json(self._build_session(lang, view_mode))
            except Exception as e:
                self._send_json(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
```

Finally, add the print endpoint in `do_POST`, right before the final `self.send_error(HTTPStatus.NOT_FOUND, ...)`:

```python
        elif parsed.path == "/api/dictionary/print":
            lang = req_data.get("lang", "mzr")
            view_mode = req_data.get("view", "clean")
            try:
                from langpipe.lexicon.audit.view import LexiconView
                from langpipe.lexicon.exporters.pdf import build_print_edition

                view_obj = LexiconView.load(lang_code=lang, view=view_mode)
                raw = view_obj.raw_data or {}
                out_dir = EXPORTS_DIR / lang / "formats"
                fonts_dir = ROOT / "assets" / "fonts"

                result = build_print_edition(
                    view_obj.entries,
                    out_dir,
                    target_lang=lang,
                    target_name=raw.get("language_name", lang),
                    contact_lang=raw.get("contact_language", "por"),
                    contact_name="Português",
                    language_family=raw.get("language_family", ""),
                    glottocode=raw.get("glottocode", ""),
                    territory=raw.get("territory", ""),
                    fonts_dir=fonts_dir if fonts_dir.exists() else None,
                    session=self._build_session(lang, view_mode),
                    morphology=raw.get("morphology", []),
                    parallel_sentences=raw.get("parallel_sentences", []),
                )

                self._send_json(
                    {
                        "status": "success",
                        "pdf": f"/formats/{lang}/dictionary_{lang}_printable.pdf",
                        "html": f"/formats/{lang}/dictionary_{lang}_printable.html",
                        "entries": len(view_obj.entries),
                    }
                )
            except Exception as e:
                self._send_json(
                    {"status": "error", "message": str(e)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return
```

- [ ] **Step 4: Run the server tests to verify they pass**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit/test_web_dictionary_api.py -q
```

Expected: all tests pass except `test_pdf_is_reachable_under_formats`, which **skips** if the PDF has not been built yet.

- [ ] **Step 5: Build the print edition so the PDF link resolves**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python - <<'PY'
from langpipe.lexicon.exporters import export_all_formats
result = export_all_formats("mzr", view="clean")
print("pdf:", result["printable_pdf"])
PY
.venv/bin/python -m pytest tests/unit/test_web_dictionary_api.py -q
```

Expected: all tests pass, including `test_pdf_is_reachable_under_formats`.

- [ ] **Step 6: Verify against the running portal**

```bash
cd /home/luandro/Dev/AI/language-distillation
for p in "/api/dictionary/session?lang=mzr" \
         "/formats/mzr/dictionary_mzr.lift" \
         "/formats/mzr/cldf/Dictionary-metadata.json" \
         "/formats/mzr/dictionary_mzr_printable.html" \
         "/formats/mzr/dictionary_mzr_printable.pdf"; do
  printf "%-58s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8000$p")"
done
```

Expected: every path returns **200**. The three `formats` paths returned **404** before this task.

- [ ] **Step 7: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add exports/web/server.py tests/unit/test_web_dictionary_api.py
git commit -m "feat(portal): dictionary session and print endpoints; fix 404 artifact links

The Exports tab advertised three download links that all returned 404
because the static root was exports/web/ while the artifacts live in
exports/<lang>/formats/. A /formats/<lang>/... route now serves them.

Adds GET /api/dictionary/session (cached on the export mtime) and POST
/api/dictionary/print, which builds the print edition and returns a
downloadable PDF path."
```

---

## Task 7: The `Dicionário` tab — markup, styles, and i18n

**Files:**
- Modify: `exports/web/index.html`

**Interfaces:**
- Consumes: `GET /api/dictionary/session?lang=mzr` (Task 6).
- Produces: a new workspace pane `#pane-dictionary` with these element IDs, which Task 8's JavaScript binds to:

  | ID | Element | Purpose |
  |---|---|---|
  | `pane-dictionary` | `<section>` | The workspace pane. |
  | `dictTabTitle` | `<span>` | The dictionary title. |
  | `dictSearch` | `<input type="search">` | The search field. |
  | `dictDirToggle` | `<div>` | Direction toggle; buttons carry `data-dir="mzr-por"` / `data-dir="por-mzr"`. |
  | `dictLetterBar` | `<div>` | The A–Z strip; buttons carry `data-letter="A"`. |
  | `dictFacetPos`, `dictFacetDomain`, `dictFacetStatus` | `<div>` | Facet filter containers; chips carry `data-value="…"`. |
  | `dictResultList` | `<div>` | The result list. |
  | `dictResultCount` | `<span>` | Result count label. |
  | `dictEntry` | `<div>` | The rendered entry. |
  | `dictExpertToggle` | `<input type="checkbox">` | The Simple/Expert switch. |
  | `dictPrintBtn` | `<button>` | Triggers the PDF download. |
  | `dictPrintStatus` | `<div>` | Print progress / error text. |
  | `dictEmpty` | `<div>` | The empty-state message. |

- [ ] **Step 1: Add the nav tab**

In `exports/web/index.html`, insert this button as the **first** child of `.nav-tabs` (immediately after the `<div class="nav-tabs">` opening tag at line 1304), so `Dicionário` becomes the default landing tab:

```html
        <button class="nav-tab active" data-ws="dictionary" onclick="State.setWorkspace('dictionary')">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h7M9 11h7"/></svg>
          <span data-i18n="ws_dictionary">Dicionário</span>
        </button>
```

- [ ] **Step 2: Add the workspace pane**

Insert this section **before** `<section id="pane-lexicon" class="workspace-pane active">` (around line 1346), and change that lexicon section's class from `workspace-pane active` to `workspace-pane`:

```html
      <!-- --------------------------------------------------------------------
           WORKSPACE: DICIONÁRIO (READER-FACING DICTIONARY SESSION)
           -------------------------------------------------------------------- -->
      <section id="pane-dictionary" class="workspace-pane active">
        <div class="dict-workspace">

          <header class="dict-header">
            <div class="dict-heading">
              <h1 class="dict-title" id="dictTabTitle">Dicionário Marúbo ⇄ Português</h1>
              <p class="dict-subtitle" data-i18n="dict_subtitle">
                Verbetes atestados com exemplos e fontes. Pressione <kbd>/</kbd> para buscar.
              </p>
            </div>

            <div class="dict-controls">
              <div class="dict-dir-toggle" id="dictDirToggle" role="group" aria-label="Direção de busca">
                <button class="dict-dir-btn active" data-dir="mzr-por">Marúbo → Português</button>
                <button class="dict-dir-btn" data-dir="por-mzr">Português → Marúbo</button>
              </div>

              <label class="dict-expert-switch" title="Mostrar proveniência, citações e linhagem">
                <input type="checkbox" id="dictExpertToggle">
                <span class="dict-switch-track" aria-hidden="true"><span class="dict-switch-thumb"></span></span>
                <span class="dict-switch-label" data-i18n="dict_expert">Especialista</span>
              </label>

              <button class="btn-secondary dict-print-btn" id="dictPrintBtn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v8H6z"/></svg>
                <span data-i18n="dict_print">Imprimir PDF</span>
              </button>
            </div>
          </header>

          <div class="dict-search-row">
            <div class="dict-search-wrap">
              <svg class="dict-search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
              <input type="search" id="dictSearch" class="dict-search-input" autocomplete="off" spellcheck="false"
                     data-i18n-placeholder="dict_search_placeholder" placeholder="Buscar no dicionário…">
            </div>
            <div class="dict-result-count" id="dictResultCount">—</div>
          </div>

          <div class="dict-letter-bar" id="dictLetterBar" role="navigation" aria-label="Índice alfabético"></div>

          <div class="dict-body">
            <aside class="dict-rail">
              <div class="dict-facet" id="dictFacetPos">
                <div class="dict-facet-title" data-i18n="dict_facet_pos">Classe gramatical</div>
                <div class="dict-facet-chips"></div>
              </div>
              <div class="dict-facet" id="dictFacetDomain">
                <div class="dict-facet-title" data-i18n="dict_facet_domain">Domínio semântico</div>
                <div class="dict-facet-chips"></div>
              </div>
              <div class="dict-facet" id="dictFacetStatus">
                <div class="dict-facet-title" data-i18n="dict_facet_status">Evidência</div>
                <div class="dict-facet-chips"></div>
              </div>
              <div class="dict-facet">
                <div class="dict-facet-title" data-i18n="dict_facet_results">Resultados</div>
                <div class="dict-result-list" id="dictResultList" role="listbox" aria-label="Resultados"></div>
              </div>
            </aside>

            <main class="dict-reading" id="dictEntry" tabindex="-1" aria-live="polite">
              <div class="dict-empty" id="dictEmpty" data-i18n="dict_empty">
                Selecione um verbete na lista ou comece a buscar.
              </div>
            </main>
          </div>

          <div class="dict-print-status" id="dictPrintStatus" role="status" aria-live="polite"></div>
        </div>
      </section>
```

- [ ] **Step 3: Add the CSS**

Insert this CSS block immediately before the closing `</style>` tag. Find it with:

```bash
grep -n "^\s*</style>" exports/web/index.html
```

The block:

```css
    /* ==========================================================================
       DICTIONARY SESSION (READER-FACING)
       ========================================================================== */
    .dict-workspace {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
    }

    .dict-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1.5rem;
      padding: 1.25rem 1.5rem 0.75rem 1.5rem;
      border-bottom: 1px solid var(--border-subtle);
      flex-wrap: wrap;
    }
    .dict-title {
      font-family: var(--font-display);
      font-size: 1.45rem;
      font-weight: 500;
      color: var(--text-primary);
      letter-spacing: -0.01em;
    }
    .dict-subtitle {
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin-top: 0.25rem;
    }
    .dict-subtitle kbd {
      font-family: var(--font-mono);
      font-size: 0.7rem;
      background: var(--bg-elevated);
      border: 1px solid var(--border-subtle);
      border-radius: 3px;
      padding: 0.05rem 0.3rem;
    }

    .dict-controls {
      display: flex;
      align-items: center;
      gap: 0.9rem;
      flex-wrap: wrap;
    }
    .dict-dir-toggle {
      display: inline-flex;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 2px;
    }
    .dict-dir-btn {
      font-size: 0.76rem;
      padding: 0.32rem 0.7rem;
      border-radius: 4px;
      color: var(--text-secondary);
      transition: all 0.15s ease;
    }
    .dict-dir-btn.active {
      background: var(--bg-selected);
      color: var(--text-primary);
      font-weight: 600;
    }

    .dict-expert-switch {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      cursor: pointer;
      font-size: 0.78rem;
      color: var(--text-secondary);
      user-select: none;
    }
    .dict-expert-switch input { position: absolute; opacity: 0; width: 0; height: 0; }
    .dict-switch-track {
      width: 32px;
      height: 17px;
      border-radius: 999px;
      background: var(--bg-elevated);
      border: 1px solid var(--border-subtle);
      position: relative;
      transition: background 0.15s ease;
    }
    .dict-switch-thumb {
      position: absolute;
      top: 1.5px;
      left: 2px;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: var(--text-tertiary);
      transition: transform 0.15s ease, background 0.15s ease;
    }
    .dict-expert-switch input:checked + .dict-switch-track { background: var(--accent-muted); border-color: var(--accent-border); }
    .dict-expert-switch input:checked + .dict-switch-track .dict-switch-thumb { transform: translateX(14px); background: var(--accent); }
    .dict-expert-switch input:focus-visible + .dict-switch-track { outline: 2px solid var(--accent); outline-offset: 2px; }

    .dict-print-btn { display: inline-flex; align-items: center; gap: 0.4rem; }

    .dict-search-row {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 0.85rem 1.5rem 0.6rem 1.5rem;
    }
    .dict-search-wrap { position: relative; flex: 1; max-width: 520px; display: flex; align-items: center; }
    .dict-search-icon { position: absolute; left: 0.7rem; color: var(--text-tertiary); pointer-events: none; }
    .dict-search-input {
      width: 100%;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 0.5rem 0.8rem 0.5rem 2.2rem;
      font-size: 0.9rem;
      color: var(--text-primary);
      font-family: var(--font-display);
    }
    .dict-search-input:focus { outline: none; border-color: var(--accent); }
    .dict-result-count { font-size: 0.76rem; color: var(--text-tertiary); font-family: var(--font-mono); }

    .dict-letter-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 2px;
      padding: 0 1.5rem 0.7rem 1.5rem;
      border-bottom: 1px solid var(--border-subtle);
    }
    .dict-letter-btn {
      min-width: 24px;
      height: 24px;
      border-radius: 4px;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text-secondary);
      background: var(--bg-surface);
      border: 1px solid transparent;
      transition: all 0.12s ease;
    }
    .dict-letter-btn:hover:not(:disabled) { color: var(--text-primary); background: var(--bg-hover); }
    .dict-letter-btn.active { color: #fff; background: var(--accent); }
    .dict-letter-btn:disabled { opacity: 0.25; cursor: default; }
    .dict-letter-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

    .dict-body {
      display: grid;
      grid-template-columns: 300px 1fr;
      gap: 1.5rem;
      padding: 1.1rem 1.5rem 2rem 1.5rem;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }
    .dict-rail { overflow-y: auto; padding-right: 0.5rem; }
    .dict-facet { margin-bottom: 1.3rem; }
    .dict-facet-title {
      font-size: 0.66rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--text-tertiary);
      margin-bottom: 0.5rem;
      font-weight: 600;
    }
    .dict-facet-chips { display: flex; flex-wrap: wrap; gap: 4px; }
    .dict-facet-chip {
      font-size: 0.72rem;
      padding: 0.2rem 0.5rem;
      border-radius: 999px;
      border: 1px solid var(--border-subtle);
      background: var(--bg-surface);
      color: var(--text-secondary);
      transition: all 0.12s ease;
    }
    .dict-facet-chip:hover { border-color: var(--border-medium); color: var(--text-primary); }
    .dict-facet-chip.active { background: var(--accent-muted); border-color: var(--accent-border); color: var(--text-primary); }
    .dict-facet-chip .chip-count { opacity: 0.6; margin-left: 0.3rem; font-family: var(--font-mono); font-size: 0.68rem; }

    .dict-result-list { display: flex; flex-direction: column; gap: 1px; }
    .dict-result-item {
      text-align: left;
      padding: 0.4rem 0.5rem;
      border-radius: 5px;
      border-left: 3px solid transparent;
      transition: background 0.12s ease;
    }
    .dict-result-item:hover { background: var(--bg-hover); }
    .dict-result-item.active { background: var(--bg-selected); }
    .dict-result-item .r-headword { font-family: var(--font-display); font-size: 0.92rem; color: var(--text-primary); }
    .dict-result-item .r-gloss { font-size: 0.76rem; color: var(--text-secondary); display: block; }
    .dict-result-item .r-meta { font-size: 0.68rem; color: var(--text-tertiary); font-family: var(--font-mono); }

    .dict-reading { overflow-y: auto; padding-right: 0.5rem; }
    .dict-empty { color: var(--text-tertiary); font-size: 0.9rem; padding: 3rem 0; text-align: center; }

    .dict-entry {
      border-left: 3px solid var(--border-subtle);
      padding: 0.15rem 0 0.15rem 1.1rem;
      margin-bottom: 1.75rem;
    }
    .dict-entry[data-status="validated"] { border-left-color: #34d399; }
    .dict-entry[data-status="supported"] { border-left-color: #fbbf24; border-left-style: solid; }
    .dict-entry[data-status="candidate"] { border-left-color: #38bdf8; border-left-style: dashed; }
    .dict-entry[data-status="other"] { border-left-color: var(--border-medium); border-left-style: dotted; }

    .dict-entry-head { display: flex; align-items: baseline; gap: 0.7rem; flex-wrap: wrap; }
    .dict-headword { font-family: var(--font-display); font-size: 1.75rem; font-weight: 600; color: var(--text-primary); line-height: 1.15; }
    .dict-pos {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--text-tertiary);
      border: 1px solid var(--border-subtle);
      border-radius: 3px;
      padding: 0.1rem 0.4rem;
    }
    .dict-domain { font-size: 0.72rem; color: #a78bfa; letter-spacing: 0.06em; text-transform: uppercase; }

    .dict-glosses { margin-top: 0.5rem; font-size: 1.05rem; color: var(--text-primary); font-family: var(--font-display); }
    .dict-gloss-item { display: flex; gap: 0.6rem; }
    .dict-gloss-index { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 0.85rem; }

    .dict-example {
      margin-top: 0.9rem;
      padding-left: 0.9rem;
      border-left: 1px solid var(--border-subtle);
    }
    .dict-ex-target { font-family: var(--font-display); font-style: italic; font-size: 0.95rem; color: var(--text-primary); }
    .dict-ex-ref { font-size: 0.88rem; color: var(--text-secondary); margin-top: 0.15rem; }
    .dict-ex-src { font-size: 0.72rem; color: var(--accent); margin-top: 0.2rem; font-family: var(--font-mono); }

    /* Tier 2 of the evidence disclosure: a one-line source strip that
       appears on hover/focus. No modal, no panel. */
    .dict-source-strip {
      display: none;
      margin-top: 0.55rem;
      font-size: 0.72rem;
      color: var(--text-tertiary);
      font-family: var(--font-mono);
      letter-spacing: 0.01em;
    }
    .dict-entry:hover .dict-source-strip,
    .dict-entry:focus-within .dict-source-strip {
      display: block;
    }

    .dict-see-also { margin-top: 0.7rem; font-size: 0.78rem; color: var(--text-secondary); }
    .dict-see-also a { color: var(--accent); text-decoration: none; }
    .dict-see-also a:hover { text-decoration: underline; }

    .dict-provenance {
      margin-top: 1rem;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: 6px;
      padding: 0.75rem 0.9rem;
      font-size: 0.78rem;
    }
    .dict-prov-title {
      font-size: 0.66rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--text-tertiary);
      font-weight: 600;
      margin-bottom: 0.45rem;
    }
    .dict-prov-grid { display: grid; grid-template-columns: 130px 1fr; gap: 0.3rem 0.8rem; }
    .dict-prov-key { color: var(--text-tertiary); }
    .dict-prov-val { color: var(--text-secondary); word-break: break-word; }
    .dict-prov-cite { margin-top: 0.5rem; color: var(--text-tertiary); font-size: 0.74rem; }
    .dict-prov-cite code { font-family: var(--font-mono); color: var(--text-secondary); }

    .dict-status-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      font-size: 0.7rem;
      padding: 0.12rem 0.45rem;
      border-radius: 999px;
      border: 1px solid var(--border-subtle);
    }
    .dict-status-chip[data-status="validated"] { background: var(--status-valid-bg); border-color: var(--status-valid-border); color: var(--status-valid-text); }
    .dict-status-chip[data-status="supported"] { background: var(--status-warn-bg); border-color: var(--status-warn-border); color: var(--status-warn-text); }
    .dict-status-chip[data-status="candidate"] { background: var(--status-info-bg); border-color: var(--status-info-border); color: var(--status-info-text); }
    .dict-status-chip[data-status="other"] { background: var(--bg-elevated); color: var(--text-secondary); }

    .dict-print-status { padding: 0 1.5rem 1rem 1.5rem; font-size: 0.78rem; color: var(--text-secondary); min-height: 1.2rem; }
    .dict-print-status.error { color: #f87171; }

    @media (max-width: 900px) {
      .dict-body { grid-template-columns: 1fr; overflow: visible; }
      .dict-rail { max-height: 320px; }
      .dict-header { flex-direction: column; align-items: stretch; }
    }
```

- [ ] **Step 4: Add the i18n keys**

The `I18N` object has a `pt` block and an `en` block. Add these keys to **both** blocks, immediately after the `ws_exports` key in each:

```javascript
        ws_dictionary: "Dicionário",
        dict_subtitle: "Verbetes atestados com exemplos e fontes. Pressione / para buscar.",
        dict_expert: "Especialista",
        dict_print: "Imprimir PDF",
        dict_search_placeholder: "Buscar no dicionário…",
        dict_facet_pos: "Classe gramatical",
        dict_facet_domain: "Domínio semântico",
        dict_facet_status: "Evidência",
        dict_facet_results: "Resultados",
        dict_empty: "Selecione um verbete na lista ou comece a buscar.",
        dict_printing: "Gerando a edição impressa…",
        dict_print_done: "Edição impressa pronta.",
        dict_print_failed: "Não foi possível gerar o PDF.",
        dict_expert_on: "Proveniência, citações e linhagem visíveis.",
        dict_expert_off: "Modo leitor: apenas verbete, glosa e exemplo.",
        dict_see_also: "ver",
```

For the English block use:

```javascript
        ws_dictionary: "Dictionary",
        dict_subtitle: "Attested entries with examples and sources. Press / to search.",
        dict_expert: "Expert",
        dict_print: "Print PDF",
        dict_search_placeholder: "Search the dictionary…",
        dict_facet_pos: "Part of speech",
        dict_facet_domain: "Semantic domain",
        dict_facet_status: "Evidence",
        dict_facet_results: "Results",
        dict_empty: "Select an entry in the list, or start searching.",
        dict_printing: "Generating the print edition…",
        dict_print_done: "Print edition ready.",
        dict_print_failed: "Could not generate the PDF.",
        dict_expert_on: "Provenance, citations and lineage visible.",
        dict_expert_off: "Reader mode: headword, gloss and example only.",
        dict_see_also: "see",
```

- [ ] **Step 5: Wire the tab into the workspace switcher**

In `exports/web/index.html`, in `State.setWorkspace(ws)`, add the dictionary render call. The existing block is:

```javascript
        if (ws === 'comparative') this.renderComparative();
        if (ws === 'igt') this.renderIGT();
        if (ws === 'synthetic') {
          this.renderSyntheticGallery();
          this.renderFewShotPrompt();
        }
```

Replace it with:

```javascript
        if (ws === 'comparative') this.renderComparative();
        if (ws === 'igt') this.renderIGT();
        if (ws === 'synthetic') {
          this.renderSyntheticGallery();
          this.renderFewShotPrompt();
        }
        if (ws === 'dictionary') DictionaryUI.activate();
```

- [ ] **Step 6: Make the dictionary the default tab**

In the `DOMContentLoaded` handler, the existing code is:

```javascript
      const hash = window.location.hash.replace('#', '');
      if (['lexicon', 'comparative', 'igt', 'synthetic', 'exports'].includes(hash)) {
        State.setWorkspace(hash);
      } else {
        State.setWorkspace('lexicon');
      }
```

Replace it with:

```javascript
      const hash = window.location.hash.replace('#', '');
      if (['dictionary', 'lexicon', 'comparative', 'igt', 'synthetic', 'exports'].includes(hash)) {
        State.setWorkspace(hash);
      } else {
        State.setWorkspace('dictionary');
      }
```

- [ ] **Step 7: Add the script tag**

Immediately before `</body>`, after the existing inline `<script>` block, add:

```html
  <script src="dictionary.js"></script>
```

- [ ] **Step 8: Verify the markup parses and the tab is reachable**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python - <<'PY'
from html.parser import HTMLParser
from pathlib import Path

class Check(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.duplicates = []
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == "id":
                if value in self.ids:
                    self.duplicates.append(value)
                self.ids.add(value)

html = Path("exports/web/index.html").read_text(encoding="utf-8")
parser = Check()
parser.feed(html)

required = [
    "pane-dictionary", "dictTabTitle", "dictSearch", "dictDirToggle",
    "dictLetterBar", "dictFacetPos", "dictFacetDomain", "dictFacetStatus",
    "dictResultList", "dictResultCount", "dictEntry", "dictExpertToggle",
    "dictPrintBtn", "dictPrintStatus", "dictEmpty",
]
missing = [i for i in required if i not in parser.ids]
assert not missing, f"missing ids: {missing}"
assert not parser.duplicates, f"duplicate ids: {parser.duplicates}"
assert "data-ws=\"dictionary\"" in html
assert "ws_dictionary" in html
print("markup OK:", len(required), "ids present, no duplicates")
PY
```

Expected: `markup OK: 15 ids present, no duplicates`.

- [ ] **Step 9: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add exports/web/index.html
git commit -m "feat(portal): dictionary session markup, styles, and i18n

Adds the Dicionário tab as the default landing surface: a left rail of
A-Z browse and evidence facets, a reading pane for the entry, a
Simple/Expert switch, a direction toggle, and the print button.

Status is encoded as a coloured left border with a distinct border
style per status, so it stays legible in greyscale and for colour-blind
readers."
```

---

## Task 8: `dictionary.js` — search, browse, and entry rendering

**Files:**
- Create: `exports/web/dictionary.js`

**Interfaces:**
- Consumes: `GET /api/dictionary/session?lang=mzr&view=clean` (Task 6). The payload shape is documented in Task 2.
- Produces: a global `DictionaryUI` object with:
  - `DictionaryUI.activate()` → loads the session if needed, renders the letter bar, facets, and the first entry.
  - `DictionaryUI.setDirection(dir)` where `dir` is `"mzr-por"` or `"por-mzr"`.
  - `DictionaryUI.setExpert(on)` → toggles the expert panel.
  - `DictionaryUI.search(query)` → filters and re-renders.
  - `DictionaryUI.selectHeadword(headword)` → renders one entry in the reading pane.
  - `DictionaryUI.setLetter(letter)` → filters to one letter bucket.
  - `DictionaryUI.toggleFacet(kind, value)` → toggles a POS/domain/status filter.

  The element IDs it binds to are the ones listed in Task 7's interface table.

- [ ] **Step 1: Write the JavaScript module**

Create `exports/web/dictionary.js`:

```javascript
/* ==========================================================================
   DICTIONARY SESSION (READER-FACING)
   --------------------------------------------------------------------------
   Consumes GET /api/dictionary/session. The server owns normalization,
   letter bucketing and status semantics; this file only presents them.

   Search ranking (both directions):
     1. exact headword match
     2. exact gloss match
     3. prefix match on the normalized key
     4. substring match on the normalized key
   Within a tier, entries are ordered by attestation count (desc), then
   alphabetically -- the same ordering the reverse index uses.
   ========================================================================== */

const DictionaryUI = (() => {
  const SESSION_URL = '/api/dictionary/session';
  const EXPERT_KEY = 'javari_dict_expert';

  const state = {
    session: null,
    loading: false,
    error: null,
    direction: 'mzr-por',
    expert: false,
    query: '',
    letter: null,
    facets: { pos: new Set(), domain: new Set(), status: new Set() },
    results: [],
    selected: null,
    highlight: -1,
  };

  // -- helpers ------------------------------------------------------------

  const $ = (id) => document.getElementById(id);

  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function normalize(text) {
    return String(text || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .trim();
  }

  function posLabel(pos) {
    const dict = (typeof I18N !== 'undefined' && I18N[State.locale] && I18N[State.locale].pos_short) || {};
    return dict[pos] || pos || '';
  }

  function statusLabel(status) {
    const dict = (typeof I18N !== 'undefined' && I18N[State.locale] && I18N[State.locale].status_labels) || {};
    return dict[status] || status || '—';
  }

  function t(key) {
    if (typeof State !== 'undefined' && typeof State.t === 'function') return State.t(key);
    return key;
  }

  function domainLabel(domain) {
    if (!domain || domain === 'general') return '';
    return domain.replace(/_/g, ' ');
  }

  // -- data ---------------------------------------------------------------

  async function load() {
    if (state.session || state.loading) return state.session;
    state.loading = true;
    state.error = null;
    try {
      const resp = await fetch(`${SESSION_URL}?lang=mzr&view=clean`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      state.session = await resp.json();
    } catch (e) {
      state.error = e.message;
      state.session = null;
    } finally {
      state.loading = false;
    }
    return state.session;
  }

  // -- search -------------------------------------------------------------

  function forwardMatches(query) {
    const key = normalize(query);
    if (!key) return [];
    const tiers = [[], [], [], []];

    for (const entry of state.session.entries) {
      const glossKey = normalize((entry.glosses || []).join('; '));
      if (normalize(entry.headword) === key) {
        tiers[0].push(entry);
      } else if (glossKey === key) {
        tiers[1].push(entry);
      } else if (entry.search_key.startsWith(key)) {
        tiers[2].push(entry);
      } else if (entry.search_key.includes(key) || glossKey.includes(key)) {
        tiers[3].push(entry);
      }
    }

    for (const tier of tiers) {
      tier.sort((a, b) => {
        if (b.attestations !== a.attestations) return b.attestations - a.attestations;
        return a.headword.localeCompare(b.headword, 'pt-BR');
      });
    }
    return tiers.flat();
  }

  function reverseMatches(query) {
    const key = normalize(query);
    if (!key) return [];
    const hits = [];
    for (const item of state.session.reverse || []) {
      const contactKey = normalize(item.contact_headword);
      const targetKeys = (item.senses || []).map((s) => normalize(s.target_headword));
      const exact = contactKey === key;
      const prefix = contactKey.startsWith(key) || targetKeys.some((k) => k.startsWith(key));
      const substring = contactKey.includes(key) || targetKeys.some((k) => k.includes(key));
      if (exact || prefix || substring) {
        hits.push({ item, tier: exact ? 0 : prefix ? 1 : 2 });
      }
    }
    hits.sort((a, b) => {
      if (a.tier !== b.tier) return a.tier - b.tier;
      const at = a.item.total_attestations || 0;
      const bt = b.item.total_attestations || 0;
      if (bt !== at) return bt - at;
      return a.item.contact_headword.localeCompare(b.item.contact_headword, 'pt-BR');
    });

    const seen = new Set();
    const entries = [];
    for (const hit of hits) {
      for (const sense of hit.item.senses || []) {
        const source = state.session.entries.find((e) => e.headword === sense.target_headword);
        if (!source || seen.has(source.headword)) continue;
        seen.add(source.headword);
        entries.push(source);
      }
    }
    return entries;
  }

  function applyFacets(entries) {
    return entries.filter((entry) => {
      if (state.facets.pos.size && !state.facets.pos.has(entry.pos)) return false;
      if (state.facets.domain.size && !state.facets.domain.has(entry.domain)) return false;
      if (state.facets.status.size && !state.facets.status.has(entry.status)) return false;
      if (state.letter && entry.letter !== state.letter) return false;
      return true;
    });
  }

  function computeResults() {
    if (!state.session) return [];
    let entries;
    if (!state.query) {
      entries = state.session.entries.slice();
    } else if (state.direction === 'por-mzr') {
      entries = reverseMatches(state.query);
    } else {
      entries = forwardMatches(state.query);
    }
    return applyFacets(entries);
  }

  // -- rendering ----------------------------------------------------------

  function renderLetterBar() {
    const bar = $('dictLetterBar');
    if (!bar || !state.session) return;
    bar.innerHTML = '';
    for (const info of state.session.letters || []) {
      const btn = document.createElement('button');
      btn.className = 'dict-letter-btn';
      btn.type = 'button';
      btn.textContent = info.letter;
      btn.dataset.letter = info.letter;
      btn.title = `${info.letter} — ${info.count}`;
      btn.setAttribute('aria-label', `Letra ${info.letter}, ${info.count} verbetes`);
      if (state.letter === info.letter) btn.classList.add('active');
      btn.addEventListener('click', () => {
        state.letter = state.letter === info.letter ? null : info.letter;
        refresh();
      });
      bar.appendChild(btn);
    }
    const all = document.createElement('button');
    all.className = 'dict-letter-btn';
    all.type = 'button';
    all.textContent = 'ALL';
    all.title = 'Todos';
    all.addEventListener('click', () => {
      state.letter = null;
      refresh();
    });
    bar.appendChild(all);
  }

  function renderFacets() {
    if (!state.session) return;
    const kinds = [
      ['pos', 'dictFacetPos', (e) => e.pos],
      ['domain', 'dictFacetDomain', (e) => e.domain],
      ['status', 'dictFacetStatus', (e) => e.status],
    ];
    for (const [kind, containerId] of kinds) {
      const container = $(containerId);
      if (!container) continue;
      const chips = container.querySelector('.dict-facet-chips');
      if (!chips) continue;
      chips.innerHTML = '';
      for (const facet of (state.session.facets && state.session.facets[kind]) || []) {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'dict-facet-chip';
        if (state.facets[kind].has(facet.value)) chip.classList.add('active');
        const label = kind === 'status' ? statusLabel(facet.value) : facet.value;
        chip.innerHTML = `${esc(label)}<span class="chip-count">${facet.count}</span>`;
        chip.addEventListener('click', () => toggleFacet(kind, facet.value));
        chips.appendChild(chip);
      }
    }
  }

  function renderResultList() {
    const list = $('dictResultList');
    const count = $('dictResultCount');
    if (!list) return;
    list.innerHTML = '';
    if (count) {
      count.textContent = state.loading
        ? '…'
        : `${state.results.length} / ${state.session ? state.session.entries.length : 0}`;
    }
    for (const entry of state.results.slice(0, 300)) {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'dict-result-item';
      item.dataset.headword = entry.headword;
      item.setAttribute('role', 'option');
      if (state.selected && state.selected.headword === entry.headword) {
        item.classList.add('active');
      }
      const gloss = (entry.glosses || []).join('; ');
      item.innerHTML =
        `<span class="r-headword">${esc(entry.headword)}</span>` +
        `<span class="r-gloss">${esc(gloss)}</span>` +
        `<span class="r-meta">${esc(posLabel(entry.pos))} · ${esc(statusLabel(entry.status))}</span>`;
      item.addEventListener('click', () => selectHeadword(entry.headword));
      list.appendChild(item);
    }
  }

  function renderEntry() {
    const pane = $('dictEntry');
    if (!pane) return;
    const empty = $('dictEmpty');
    if (!state.selected) {
      pane.innerHTML = empty ? empty.outerHTML : '';
      return;
    }
    const entry = state.selected;
    const status = entry.status || 'other';
    const known = ['validated', 'supported', 'candidate'].includes(status) ? status : 'other';

    const glosses = (entry.glosses || []).map(
      (g, i) => `<div class="dict-gloss-item"><span class="dict-gloss-index">${i + 1}.</span><span>${esc(g)}</span></div>`
    ).join('');

    const examples = (entry.examples || []).map((ex) => `
      <div class="dict-example">
        <div class="dict-ex-target">${esc(ex.target_text)}</div>
        ${ex.reference_text ? `<div class="dict-ex-ref">“${esc(ex.reference_text)}”</div>` : ''}
        ${ex.source_ref ? `<div class="dict-ex-src">(${esc(ex.source_ref)})</div>` : ''}
      </div>`).join('');

    const related = entry.related_entry
      ? `<div class="dict-see-also" data-i18n="dict_see_also">ver <a href="#" data-goto="${esc(entry.related_entry)}">${esc(entry.related_entry)}</a></div>`
      : '';

    // Tier 2 of the evidence disclosure: a one-line source strip, revealed on
    // hover or keyboard focus. "status · N atestações · <first source>".
    const firstRef = (entry.examples && entry.examples[0] && entry.examples[0].source_ref) || '';
    const sourceBits = [
      statusLabel(status),
      `${entry.attestations} ${entry.attestations === 1 ? 'atestação' : 'atestações'}`,
      firstRef,
    ].filter(Boolean);
    const sourceStrip =
      `<div class="dict-source-strip">${esc(sourceBits.join(' · '))}</div>`;

    let provenance = '';
    if (state.expert) {
      const rows = [
        ['Status', statusLabel(status)],
        ['Confiança', String(entry.confidence)],
        ['Domínio', entry.domain],
        ['Valência', entry.valence],
        ['Alienabilidade', entry.inalienability],
        ['Classe lexical', entry.lexical_class],
        ['Atestações', String(entry.attestations)],
        ['Proveniência', entry.provenance || '—'],
      ];
      if (entry.flags && entry.flags.length) rows.push(['Auditoria', entry.flags.join(', ')]);
      if (entry.reasons && entry.reasons.length) rows.push(['Motivos', entry.reasons.join('; ')]);
      const grid = rows
        .map(([k, v]) => `<div class="dict-prov-key">${esc(k)}</div><div class="dict-prov-val">${esc(v)}</div>`)
        .join('');
      const cites = (entry.examples || []).map((ex) =>
        `<div>· <code>${esc(ex.citation_id || '')}</code> ${esc(ex.source_ref || '')} ` +
        `<span title="score de agrupamento; não é uma probabilidade">score ${esc(ex.score)}</span></div>`
      ).join('');
      provenance =
        `<div class="dict-provenance">` +
        `<div class="dict-prov-title">Proveniência &amp; linhagem</div>` +
        `<div class="dict-prov-grid">${grid}</div>` +
        `<div class="dict-prov-cite">Citações${cites ? '' : ': nenhuma'}</div>` +
        `</div>`;
    }

    pane.innerHTML = `
      <article class="dict-entry" data-status="${esc(known)}">
        <header class="dict-entry-head">
          <h2 class="dict-headword">${esc(entry.headword)}</h2>
          <span class="dict-pos">${esc(posLabel(entry.pos))}</span>
          ${domainLabel(entry.domain) ? `<span class="dict-domain">${esc(domainLabel(entry.domain))}</span>` : ''}
          ${state.expert ? `<span class="dict-status-chip" data-status="${esc(known)}">${esc(statusLabel(status))}</span>` : ''}
        </header>
        <div class="dict-glosses">${glosses}</div>
        ${examples}
        ${related}
        ${sourceStrip}
        ${provenance}
      </article>`;

    for (const link of pane.querySelectorAll('a[data-goto]')) {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        selectHeadword(link.dataset.goto);
      });
    }
  }

  // -- actions ------------------------------------------------------------

  function selectHeadword(headword) {
    if (!state.session) return;
    const found = state.session.entries.find((e) => e.headword === headword);
    if (found) {
      state.selected = found;
      state.highlight = state.results.findIndex((e) => e.headword === headword);
      renderResultList();
      renderEntry();
    }
  }

  function toggleFacet(kind, value) {
    if (state.facets[kind].has(value)) {
      state.facets[kind].delete(value);
    } else {
      state.facets[kind].add(value);
    }
    refresh();
  }

  function refresh() {
    state.results = computeResults();
    if (state.selected && !state.results.some((e) => e.headword === state.selected.headword)) {
      state.selected = null;
    }
    if (!state.selected && state.results.length) {
      state.selected = state.results[0];
    }
    renderFacets();
    renderLetterBar();
    renderResultList();
    renderEntry();
  }

  function setDirection(dir) {
    state.direction = dir;
    for (const btn of document.querySelectorAll('#dictDirToggle .dict-dir-btn')) {
      btn.classList.toggle('active', btn.dataset.dir === dir);
    }
    refresh();
  }

  function setExpert(on) {
    state.expert = !!on;
    try { localStorage.setItem(EXPERT_KEY, state.expert ? '1' : '0'); } catch (e) { /* private mode */ }
    const toggle = $('dictExpertToggle');
    if (toggle) toggle.checked = state.expert;
    renderEntry();
  }

  function setLetter(letter) {
    state.letter = letter;
    refresh();
  }

  function search(query) {
    state.query = (query || '').trim();
    refresh();
  }

  // -- print --------------------------------------------------------------

  async function requestPrint() {
    const status = $('dictPrintStatus');
    const btn = $('dictPrintBtn');
    if (status) { status.classList.remove('error'); status.textContent = t('dict_printing'); }
    if (btn) btn.disabled = true;
    try {
      const resp = await fetch('/api/dictionary/print', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lang: 'mzr', view: 'clean' }),
      });
      const data = await resp.json();
      if (!resp.ok || data.status !== 'success') {
        throw new Error(data.message || `HTTP ${resp.status}`);
      }
      if (status) status.textContent = t('dict_print_done');
      window.open(data.pdf, '_blank');
    } catch (e) {
      if (status) { status.classList.add('error'); status.textContent = `${t('dict_print_failed')} ${e.message}`; }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // -- activation ---------------------------------------------------------

  function bind() {
    if (bind.done) return;
    bind.done = true;

    const search = $('dictSearch');
    if (search) {
      search.addEventListener('input', (e) => search_(e.target.value));
      search.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); moveHighlight(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); moveHighlight(-1); }
        else if (e.key === 'Enter') {
          e.preventDefault();
          if (state.results[state.highlight]) selectHeadword(state.results[state.highlight].headword);
        } else if (e.key === 'Escape') {
          e.preventDefault();
          search.value = '';
          search_('');
        }
      });
    }

    for (const btn of document.querySelectorAll('#dictDirToggle .dict-dir-btn')) {
      btn.addEventListener('click', () => setDirection(btn.dataset.dir));
    }

    const expert = $('dictExpertToggle');
    if (expert) {
      expert.addEventListener('change', (e) => setExpert(e.target.checked));
    }

    const printBtn = $('dictPrintBtn');
    if (printBtn) {
      printBtn.addEventListener('click', requestPrint);
    }
  }

  function search_(query) {
    state.query = (query || '').trim();
    state.highlight = -1;
    refresh();
  }

  function moveHighlight(delta) {
    if (!state.results.length) return;
    state.highlight = Math.min(
      Math.max(state.highlight + delta, 0),
      state.results.length - 1
    );
    const target = state.results[state.highlight];
    if (target) {
      state.selected = target;
      renderResultList();
      renderEntry();
    }
  }

  async function activate() {
    bind();
    try {
      const saved = localStorage.getItem(EXPERT_KEY);
      state.expert = saved === '1';
    } catch (e) { state.expert = false; }
    const toggle = $('dictExpertToggle');
    if (toggle) toggle.checked = state.expert;

    await load();
    if (state.error) {
      const pane = $('dictEntry');
      if (pane) pane.innerHTML = `<div class="dict-empty">${esc(state.error)}</div>`;
      return;
    }
    setDirection(state.direction);
    refresh();
  }

  return {
    activate,
    setDirection,
    setExpert,
    setLetter,
    search,
    selectHeadword,
    toggleFacet,
    state,
  };
})();

window.DictionaryUI = DictionaryUI;
```

- [ ] **Step 2: Check the file for syntax errors**

```bash
cd /home/luandro/Dev/AI/language-distillation
node --check exports/web/dictionary.js && echo "dictionary.js: syntax OK"
```

Expected: `dictionary.js: syntax OK`. If Node reports an error, fix it before continuing.

> **`node --check` is necessary but not sufficient.** It parses the file in isolation;
> it does not catch a regex that is valid JavaScript but invalid as a character
> class, nor a runtime error in the render path. Step 3b runs the module in a real
> browser, which is the authoritative check.

- [ ] **Step 3: Verify the search ranking logic with a headless harness**

```bash
cd /home/luandro/Dev/AI/language-distillation
node - <<'JS'
// Extract the pure ranking helpers and exercise them against real data.
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('exports/mzr/dictionary.clean.json', 'utf8'));

function normalize(text) {
  return String(text || '').normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}

const entries = data.lexicon.map((e) => ({
  headword: e.headword,
  search_key: normalize(e.headword),
  glosses: e.glosses_por || [],
  attestations: (e.citations || []).length,
  pos: e.pos,
  status: e.status,
  domain: (e.semantics || {}).primary_domain || 'general',
}));

function forwardMatches(query) {
  const key = normalize(query);
  if (!key) return [];
  const tiers = [[], [], [], []];
  for (const entry of entries) {
    const glossKey = normalize((entry.glosses || []).join('; '));
    if (normalize(entry.headword) === key) tiers[0].push(entry);
    else if (glossKey === key) tiers[1].push(entry);
    else if (entry.search_key.startsWith(key)) tiers[2].push(entry);
    else if (entry.search_key.includes(key) || glossKey.includes(key)) tiers[3].push(entry);
  }
  for (const tier of tiers) {
    tier.sort((a, b) => {
      if (b.attestations !== a.attestations) return b.attestations - a.attestations;
      return a.headword.localeCompare(b.headword, 'pt-BR');
    });
  }
  return tiers.flat();
}

// Diacritic-insensitive: typing 'westise' must find 'wẽstisẽ'.
// The normalized key of 'wẽstisẽ' is 'westise' (NFD + strip combining marks),
// so 'weste' would NOT match it -- the query must be the full normalized key.
const hits = forwardMatches('westise');
console.log('search "westise" ->', hits.map(h => h.headword).slice(0, 5));
if (!hits.some(h => h.headword === 'wẽstisẽ')) {
  console.error('FAIL: diacritic-insensitive search did not find wẽstisẽ');
  process.exit(1);
}

// Portuguese gloss search with the accent stripped.
// 'corações' normalizes to 'coracoes', so 'coracoes' must find it.
const coracoes = forwardMatches('coracoes');
console.log('search "coracoes" ->', coracoes.map(h => `${h.headword} (${h.glosses.join('; ')})`).slice(0, 3));
if (!coracoes.some(h => h.glosses.some(g => normalize(g) === 'coracoes'))) {
  console.error('FAIL: accent-stripped Portuguese gloss search did not find corações');
  process.exit(1);
}

// Exact match must rank above a prefix match.
const exact = forwardMatches('nukẽ')[0];
console.log('search "nukẽ" first hit ->', exact && exact.headword);
if (!exact || exact.headword !== 'nukẽ') {
  console.error('FAIL: exact match did not rank first');
  process.exit(1);
}

// The accent-stripped spelling of the same word must also find it.
const stripped = forwardMatches('nuke')[0];
console.log('search "nuke" first hit ->', stripped && stripped.headword);
if (!stripped || stripped.headword !== 'nukẽ') {
  console.error('FAIL: stripped spelling did not find nukẽ');
  process.exit(1);
}

console.log('search ranking: OK');
JS
```

Expected output (the exact gloss hits depend on the data; the assertions must pass):

```
search "westise" -> [ 'wẽstisẽ' ]
search "coracoes" -> [ '...' ]
search "nukẽ" first hit -> nukẽ
search "nuke" first hit -> nukẽ
search ranking: OK
```

- [ ] **Step 3b: Verify the module's i18n accessors in a real browser**

`I18N` and `State` are top-level `const` in `index.html`, so they are **not** on `window`.
A separate `<script src="dictionary.js">` sees them as bare identifiers. Accessing
`window.I18N` yields `undefined`, which silently degrades the POS and status labels to
their raw values (`noun` instead of `subst`). Verify in headless Chrome that the
translated label is used:

```bash
cd /home/luandro/Dev/AI/language-distillation
cat > /tmp/opencode/dict_i18n_check.html <<'HTML'
<!DOCTYPE html><html><body>
<div id="dictEntry"></div>
<div id="dictEmpty"></div>
<script>
  const I18N = { pt: { pos_short: { noun: 'subst' }, status_labels: { validated: 'Validado' } } };
  const State = { locale: 'pt', t(k){ return 'pt:' + k; } };
</script>
<script src="FILE_PATH"></script>
<script>
  DictionaryUI.state.session = {
    meta:{total_entries:1},
    entries:[{headword:'waka',search_key:'waka',letter:'W',pos:'noun',glosses:['agua'],
      status:'validated',provenance:'p',examples:[],domain:'general',valence:'',
      inalienability:'',confidence:0.9,related_entry:null,lexical_class:'lemma',
      flags:[],reasons:[],attestations:0}],
    letters:[],facets:{pos:[],domain:[],status:[]},reverse:[]};
  DictionaryUI.state.selected = DictionaryUI.state.session.entries[0];
  DictionaryUI.setExpert(false);
  const pane = document.getElementById('dictEntry');
  console.log('POS_TRANSLATED=' + pane.innerHTML.includes('subst'));
  console.log('RAW_LEAKED=' + pane.innerHTML.includes('>noun<'));
</script>
</body></html>
HTML
sed -i "s|FILE_PATH|$(pwd)/exports/web/dictionary.js|" /tmp/opencode/dict_i18n_check.html
google-chrome --headless=new --disable-gpu --no-sandbox --virtual-time-budget=3000 \
  --enable-logging=stderr --v=0 --dump-dom "file:///tmp/opencode/dict_i18n_check.html" 2>&1 \
  | grep -E "POS_TRANSLATED|RAW_LEAKED"
```

Expected:

```
POS_TRANSLATED=true
RAW_LEAKED=false
```

If `POS_TRANSLATED=false`, the accessors are using `window.I18N` instead of the bare
`I18N` identifier. Fix the guard in `dictionary.js` and re-run.

- [ ] **Step 4: Verify the module in the live portal**

Start the server if it is not running:

```bash
cd /home/luandro/Dev/AI/language-distillation
pkill -f "exports/web/server.py" 2>/dev/null || true
nohup .venv/bin/python exports/web/server.py 8000 > /tmp/opencode/portal.log 2>&1 &
sleep 2
curl -s -o /dev/null -w "portal: %{http_code}\n" http://localhost:8000/
```

Expected: `portal: 200`.

Then drive the page with a headless browser. Use the `agent-browser` skill or this direct check:

```bash
cd /home/luandro/Dev/AI/language-distillation
google-chrome --headless=new --disable-gpu --no-sandbox --virtual-time-budget=8000 \
  --dump-dom "http://localhost:8000/#dictionary" 2>/dev/null > /tmp/opencode/dom.html
grep -c "dict-result-item" /tmp/opencode/dom.html
grep -o 'id="dictLetterBar"[^>]*>' /tmp/opencode/dom.html
```

Expected: the first `grep -c` prints a non-zero number (the result list is populated) and the letter bar is present.

Then check the console for errors:

```bash
google-chrome --headless=new --disable-gpu --no-sandbox --virtual-time-budget=8000 \
  --enable-logging=stderr --v=0 --dump-dom "http://localhost:8000/#dictionary" 2>&1 \
  | grep -iE "uncaught|SyntaxError|ReferenceError|TypeError" | head -10
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add exports/web/dictionary.js
git commit -m "feat(portal): dictionary session search, browse, and entry rendering

Diacritic-insensitive ranked search (exact > exact gloss > prefix >
substring), A-Z browse with normalized bucketing, POS/domain/evidence
facets, bidirectional Marubo<->Portuguese lookup, keyboard navigation,
and the Simple/Expert evidence disclosure.

The server owns normalization and bucketing; this module only presents
them, so the screen cannot disagree with the printed book."
```

---

## Task 9: Fix the Exports tab links and add the print card

**Files:**
- Modify: `exports/web/index.html` (the Exports pane, around lines 1618–1678)

**Interfaces:**
- Consumes: the `/formats/<lang>/...` route from Task 6.
- Produces: three working download links and one print-edition card with two actions (view HTML, download PDF).

- [ ] **Step 1: Update the three broken links**

The Exports pane currently links to `/formats/cldf/Dictionary-metadata.json`, `/formats/dictionary_mzr.lift`, and `/formats/dictionary_mzr_printable.html` — all of which 404 because the artifacts live in `exports/mzr/formats/`. The route added in Task 6 serves `/formats/mzr/...`.

Change the CLDF link (around line 1633) from:

```html
              <a href="/formats/cldf/Dictionary-metadata.json" download class="btn-secondary" style="justify-content: center;">
```

to:

```html
              <a href="/formats/mzr/cldf/Dictionary-metadata.json" download class="btn-secondary" style="justify-content: center;">
```

> **The route maps `/formats/<lang>/<rest>` to `exports/<lang>/formats/<rest>`.** The CLDF
> tables live at `exports/mzr/formats/cldf/`, so the URL is
> `/formats/mzr/cldf/Dictionary-metadata.json` — **not** `/formats/mzr/formats/cldf/...`.
> The latter would resolve to `exports/mzr/formats/formats/cldf/...` and 404. This was
> verified against a running server.

Change the LIFT link (around line 1653) from:

```html
              <a href="/formats/dictionary_mzr.lift" download class="btn-secondary" style="justify-content: center;">
```

to:

```html
              <a href="/formats/mzr/dictionary_mzr.lift" download class="btn-secondary" style="justify-content: center;">
```

- [ ] **Step 2: Replace the printable HTML card with the print-edition card**

Replace the whole `<!-- Printable HTML Book -->` card block (around lines 1659–1677) with:

```html
            <!-- Print Edition (HTML + PDF) -->
            <div class="export-card">
              <div>
                <div class="export-card-title">
                  <span>Dicionário Imprimível (Edição Completa)</span>
                </div>
                <div class="export-card-desc">
                  Edição diagramada em duas colunas com palavras-guia, fontes numeradas,
                  prefácio e índice por domínio. Tipografia Charis SIL com cobertura IPA
                  completa, gerada localmente por WeasyPrint.
                </div>
                <div class="export-meta-row">
                  <span>Formato: HTML5 / PDF</span> &bull;
                  <span id="printEditionSize">—</span>
                </div>
              </div>
              <div class="export-card-actions">
                <a href="/formats/mzr/dictionary_mzr_printable.html" target="_blank" class="btn-secondary">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                  <span data-i18n="btn_view_printable">Abrir Versão Imprimível</span>
                </a>
                <a href="/formats/mzr/dictionary_mzr_printable.pdf" download class="btn-primary">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v8H6z"/></svg>
                  <span data-i18n="btn_download_print_pdf">Baixar PDF</span>
                </a>
              </div>
            </div>
```

- [ ] **Step 3: Add the card-actions CSS and the i18n key**

Add this CSS to the block inserted in Task 7 (append it after the `.dict-print-btn` rule):

```css
    .export-card-actions { display: flex; flex-direction: column; gap: 0.5rem; }
```

Add these i18n keys to both the `pt` and `en` blocks, next to the other `btn_*` keys:

```javascript
        btn_download_print_pdf: "Baixar PDF",
```

```javascript
        btn_download_print_pdf: "Download PDF",
```

- [ ] **Step 4: Verify every advertised artifact link returns 200**

```bash
cd /home/luandro/Dev/AI/language-distillation
grep -o 'href="/formats/[^"]*"' exports/web/index.html | sed 's/href="//; s/"//' | sort -u > /tmp/opencode/links.txt
cat /tmp/opencode/links.txt
while read -r link; do
  printf "%-60s %s\n" "$link" "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8000$link")"
done < /tmp/opencode/links.txt
```

Expected: every link prints **200**.

- [ ] **Step 5: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add exports/web/index.html
git commit -m "fix(portal): repair the Exports tab download links

All three advertised links returned 404 because the artifacts live in
exports/<lang>/formats/ while the static root was exports/web/. They
now point at the /formats/mzr/... route.

The printable card becomes a single canonical print-edition card
offering both the HTML and the generated PDF."
```

---

## Task 10: ADR, research report, and documentation

**Files:**
- Create: `docs/adr/0027-dictionary-rendering-and-print-pipeline.md`
- Create: `docs/research/dictionary-print-prior-art-2026-10.md`
- Modify: `docs/adr/README.md`
- Modify: `exports/README.md`

**Interfaces:**
- Consumes: everything built in Tasks 1–9.
- Produces: the architectural record and the documentation.

- [ ] **Step 1: Write ADR-0027**

Create `docs/adr/0027-dictionary-rendering-and-print-pipeline.md`:

```markdown
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

### D4 — Guide words use `string-set`, not `position: running()`

WeasyPrint 70 does **not** populate a running head from `position: running()` or
`:first-of-type`. The working form, confirmed by rendering to PNG and inspecting the
page image, is:

```css
.entry { string-set: gw content(text); }
@page { @top-left { content: string(gw, first); } @top-right { content: string(gw, last); } }
```

This is recorded because the broken forms look plausible and will be re-introduced.

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
```

- [ ] **Step 2: Write the prior-art research report**

Create `docs/research/dictionary-print-prior-art-2026-10.md` with the survey. It must
cite a URL for every non-obvious claim, and it must record the open questions the survey
could not resolve. Use this structure:

```markdown
# Prior art: web dictionaries and print-ready PDF dictionaries

**Surveyed:** 2026-10-20
**Method:** live web search, GitHub API, CTAN, PyPI/npm registries, and direct
inspection of shipped font binaries with fontTools.
**Scope:** a bilingual Marúbo (`mzr`) ↔ Portuguese dictionary of ~900 entries, evidence
first, served from a plain `http.server` with no build step.

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
| dictpress | https://github.com/soumendrak/ekathi | open source | Go | "Build and publish dictionaries for any language." Paginated **A–Z glossaries for all alphabets**. | Model for the A–Z index |
| bg-en | https://github.com/kfet/bg-en | MIT | TypeScript | Instant **prefix search via binary search, no server**; accent-insensitive lookup; PWA; shareable `?q=` links. | Model for the search |
| PeakSlab | https://github.com/tnelsond/peakslab | — | C | "A libre progressive web app offline dictionary platform from scratch in under 128kb", purpose-built for obscure languages. | Model for the PWA |
| GoldenDict | https://github.com/goldendict/goldendict | GPL | C++ / Qt | Its headline feature — type words "without any accents or correct case" — is table stakes. | Validated the accent-insensitive requirement |
| Kaikki / wiktextract | https://kaikki.org/ · https://github.com/tatuylonen/wiktextract | CC-BY-SA / FDL | Python | Wiktionary's structured JSON — the richest open example of a machine-readable dictionary schema. | Schema reference |
| Wiktionary `<pos>` | http://redac.univ-tlse2.fr/lexlawi/doc/pos.html | — | — | The entry model: `type`, `etymNb`, `lemma`, `labels[]`. The labels array is the precedent for per-entry status flags. | Model for the entry anatomy |
| FLEx bilingual (MXB) | https://software.sil.org/fieldworks/wp-content/uploads/sites/38/2018/12/MXB-FLEx-8-3-10-eng.pdf | — | — | Distinguishes **Definition** (monolingual) from **Gloss** (bilingual translation equivalent); describes the **Reversal index** in the contact language. | The repository already implements the reversal index in `src/langpipe/lexicon/reverse.py` |

### Names that could not be confirmed

- **"Lexicographer"** (a JS/OSX dictionary editor) — not located on GitHub. Searches for
  `lexicographer`, `topic:lexicography`, and `topic:dictionary-software` return unrelated
  projects. The live successor in the OSX/SIL space is FLEx; in the open-source web
  space it is Lexonomy. **Do not cite "Lexicographer" without verifying it.**
- **Lexique Pro** — not open source. SIL freeware, **Windows-only** ("Lexique Pro is a
  Windows program. Sorry, there are no plans to develop versions for Linux or Mac OS.",
  https://software.sil.org/downloads/r/lexiquepro/Lexique%20Pro%20-%20User%20Guide%202.5.pdf).
  The open French successor is Lexique 2.0/3000 (CC BY-SA 4.0, https://a3nm.net/git/lexique/).
- **Lexikothek** — this is a **Bertelsmann 1970s–80s German encyclopedia series**, not a
  software package (https://files.eric.ed.gov/fulltext/ED081456.pdf).
- **scaMorph** — a medical brain-image registration method, not a lexicon tool.
- **TeX Gyre Pagella** as a dictionary face — the font binary was parsed and **269 of
  271** IPA codepoints are absent. Disqualified for IPA-adjacent text.

## 2. PDF dictionaries

| Tool | Version | Licence | Two columns | Guide words | Cross-ref page no. | IPA | PDF/A | Verdict |
|---|---|---|---|---|---|---|---|---|
| **WeasyPrint** | 70.0 | BSD-3-Clause | ✅ `column-count` | ✅ `string-set` + `string(name, first\|last)` | ✅ `target-counter()` | ✅ via Charis | ✅ `--pdf-variant=pdf/a-2b` | **Adopted** |
| Typst | 0.15.1 | Apache-2.0 | ⚠️ `columns` is **not height-balanced** (https://typst.app/docs/reference/layout/columns/) | ✅ `header:` + `context` | ✅ `ref()` | ✅ | ❌ | Documented alternative |
| LaTeX (XeLaTeX) | — | LPPL | ✅ `paracol` | ✅ `fancyhdr` + `markboth` | ✅ `hyperref` | ✅ | ✅ | Documented alternative; needs TeX Live |
| Prince | 17 | commercial | ✅ | ✅ | ✅ | ✅ | ✅ | Not adopted (licence) |
| Paged.js | 0.4.3 | MIT | ✅ | ✅ | ✅ | ✅ | ❌ | Rejected (needs headless Chrome) |
| reportlab | 4.x | BSD | manual | manual | manual | ✅ | manual | Rejected (hand-roll everything) |

### WeasyPrint features verified in this repository

Confirmed by rendering to PDF and inspecting the output:

| Feature | CSS | Verified how |
|---|---|---|
| Guide words | `string-set: gw content(text);` + `string(gw, first)` / `string(gw, last)` | Rendered to PNG; the running head shows the first and last headword. |
| Guide words (**broken forms**) | `position: running(...)`, `:first-of-type` | Rendered to PNG; the running head was **empty**. Do not reintroduce. |
| Cross-references | `a::after { content: target-counter(attr(href url), page); }` | `pdftotext` showed "See also poku (p. 2)". |
| Folios | `@bottom-center { content: counter(page); }` | `pdftotext` showed the page number. |
| Font embedding | `@font-face` + a local `.woff2` | `pdffonts` showed `Charis` embedded with `Identity-H`. |
| Diacritics | — | `pdftotext` round-tripped `ẽa nukẽ wẽstisẽ ˈmaˈɾuβa` intact. |

### Measured render times (892 entries, two columns)

| Configuration | Time |
|---|---|
| Previous export (Newsreader, per-letter column containers, per-entry citation blocks) | ~80 s |
| Local fonts, one continuous two-column container | ~7 s |
| Local fonts, one container, with a citation block per entry | ~35 s |

The per-entry citation block is the dominant cost, not the fonts. The numbered-bibliography
treatment in the new template reduces the repeated text and brings the full scholarly
edition back under a minute.

## 3. Dictionary typography and layout

- **Entry structure** — headword → pronunciation → POS → senses → examples →
  cross-references. OED's *Guide to the dictionary* enumerates the components:
  https://premium.oxforddictionaries.com/fr/mots/guide-to-the-dictionary
- **Macrostructure / microstructure** — Béjoint's distinction, in Luna, *Clearly defined
  continuity and innovation in the typography of English dictionaries*:
  https://typography.network/wp-content/uploads/2024/04/Luna_TypPp_4_Clearly_defined_continuity_and_innovation_in_the_typography_of_English_dictionaries.pdf
- **Guide words** — the Overleaf *Dictionary template* puts the first and last word on
  the page in the header: https://www.overleaf.com/latex/examples/dictionary-template
- **Small caps** — the *Indexer* typographic note recommends letter-spacing small caps
  at least one unit: https://liverpooluniversitypress.co.uk/doi/pdf/10.3828/indexer.1958.2.3.4
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
  https://browse.library.kiwix.org/content/wikipedia_en_all_maxi/A/Lexicon_(typeface)

## 4. Search and browse UX

- **Accent-insensitive lookup is table stakes** — GoldenDict's headline feature is
  typing words "without any accents or correct case":
  https://github.com/goldendict/goldendict. The canonical implementation is
  `String.prototype.normalize('NFD')` with combining marks stripped, which is what
  Fuse.js does (https://github.com/krisk/Fuse/commit/ef1637140064a1dbce651fe8998cba964ea5bce2).
- **Instant prefix search without a server** — https://github.com/kfet/bg-en
- **Keyboard focus model** — "The search bar captures keystrokes only while it has
  focus. `/` focuses it; Escape returns focus.":
  https://github.com/EtherAura/Kartend/wiki/Input-and-Controls
- **A–Z index** — https://smart-interface-design-patterns.com/articles/navigation-queries-ux/
- **Facets and word lists** — https://docs.mukurtu.org/dictionary/WordLists/index.pdf
- **Showing confidence without misleading** — https://github.com/ericsocrat/decision-os/issues/114:
  "Without visual confidence indicators, users may trust estimated data as much as verified
  data." The adopted remedy is a badge with three visual states, a tooltip, and a
  "show only high-confidence" filter.

## 5. Offline-first without a bundler

- Service workers and web app manifests are **plain files**; neither needs a bundler.
  They require HTTPS or `localhost`, and the worker must be served from the site root.
- **bg-en** — ~4.1 MB one-time download, cached by a service worker; installable as a PWA;
  shareable search links. https://github.com/kfet/bg-en
- **PeakSlab** — under 128 kb, offline. https://github.com/tnelsond/peakslab
- **Malek — "A-Z (all alphabets for any language)"** — https://github.com/soumendrak/ekathi

## 6. Open questions

- The status of the **"Lexicographer"** editor is unverified. See §1.
- Whether a community print run wants a page size other than A4 (e.g. 15×21 cm, or a
  saddle-stitched booklet). A4 is the current default and the page box is a single CSS
  variable.
- Whether the printed edition needs a short **orthography note** explaining the nasal
  diacritics (`ẽ ĩ ã õ`) and the `w`/`y` contrast. This is a question for the community
  editor, not for the pipeline.

## 7. How this survey shaped the decisions

See `docs/adr/0027-dictionary-rendering-and-print-pipeline.md`. In short: the **data
contract** from CLDF was adopted, the **HTML → paged-media** route was validated by
SIL's own print pipeline, **WeasyPrint** was chosen over Typst and LaTeX, **Charis SIL**
was chosen over Newsreader and TeX Gyre Pagella, and the **three-tier evidence
disclosure** was adopted from the confidence-indicator problem documented in
`decision-os` issue 114.
```

- [ ] **Step 3: Add the ADR index row**

In `docs/adr/README.md`, add this row to the ADR index table, immediately after the
`0026` row:

```markdown
| [0027](0027-dictionary-rendering-and-print-pipeline.md) | Dictionary rendering and print pipeline | Accepted |
```

- [ ] **Step 4: Update `exports/README.md`**

In `exports/README.md`, after the numbered list of files, add a section:

```markdown
## Print Edition

`formats/dictionary_mzr_printable.html` and `formats/dictionary_mzr_printable.pdf` are
the print edition of the dictionary: two columns, running guide words, small-caps
part-of-speech labels, a numbered bibliography, front matter (title page, preface,
morpheme table) and a semantic-domain index. Both are generated from
`langpipe.lexicon.dictionary.session.DictionarySessionBuilder`, the same model the
portal's Dictionary tab reads, so the screen and the book cannot disagree.

The PDF is produced by WeasyPrint with the vendored Charis SIL typeface
(`assets/fonts/`, OFL-1.1). The font is embedded in the PDF and covers the full IPA
block, so phonetic transcription can be added to the schema without a font change.

Regenerate with:

```bash
uv run python -c "from langpipe.lexicon.exporters import export_all_formats; export_all_formats('mzr', view='clean')"
```
```

- [ ] **Step 5: Run the full test suite**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/unit -q
```

Expected: all unit tests pass, with the PDF tests either passing or skipping (depending
on whether `pdftotext`/`pdffonts` are installed).

- [ ] **Step 6: Run lint and type checks**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/ruff check src/langpipe/lexicon/dictionary/ src/langpipe/lexicon/exporters/ tests/unit/test_lexicon_dictionary_session.py tests/unit/test_lexicon_print_pdf.py tests/unit/test_web_dictionary_api.py
.venv/bin/ruff format --check src/langpipe/lexicon/dictionary/ src/langpipe/lexicon/exporters/
```

Expected: no errors. If ruff reports a formatting difference, run
`.venv/bin/ruff format src/langpipe/lexicon/dictionary/ src/langpipe/lexicon/exporters/`
and re-run the tests.

- [ ] **Step 7: Commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git add docs/adr/0027-dictionary-rendering-and-print-pipeline.md
git add docs/research/dictionary-print-prior-art-2026-10.md
git add docs/adr/README.md exports/README.md
git commit -m "docs(adr): ADR-0027 dictionary rendering and print pipeline

Records the WeasyPrint and Charis SIL choices with the alternatives that
were rejected and why, the two WeasyPrint features that were empirically
found broken, and the prior-art survey that informed the design."
```

---

## Task 11: End-to-end verification and the work-board entry

**Files:**
- Modify: `docs/FINDINGS.md` (if it exists in this repository) — otherwise skip.

**Interfaces:**
- Consumes: everything.
- Produces: a verified end-to-end state and a tracked task.

- [ ] **Step 1: Regenerate every artifact from scratch**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python - <<'PY'
from langpipe.lexicon.exporters import export_all_formats
result = export_all_formats("mzr", view="clean")
for key, value in result.items():
    print(f"{key}: {value}")
assert result["printable_pdf"], "the PDF must be built"
PY
ls -la exports/mzr/formats/
```

Expected: `printable_pdf` is a path to an existing PDF of at least 40 pages.

- [ ] **Step 2: Restart the portal and verify every endpoint**

```bash
cd /home/luandro/Dev/AI/language-distillation
pkill -f "exports/web/server.py" 2>/dev/null || true
nohup .venv/bin/python exports/web/server.py 8000 > /tmp/opencode/portal.log 2>&1 &
sleep 2
for p in / /dictionary.js /api/dictionary/session?lang=mzr \
         /api/dictionary/reverse?lang=mzr \
         /formats/mzr/dictionary_mzr.lift \
         /formats/mzr/cldf/Dictionary-metadata.json \
         /formats/mzr/dictionary_mzr_printable.html \
         /formats/mzr/dictionary_mzr_printable.pdf; do
  printf "%-58s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8000$p")"
done
```

Expected: every path returns **200**.

- [ ] **Step 3: Verify the Dictionary tab renders and works**

Use the `agent-browser` skill, or a headless Chrome check:

```bash
cd /home/luandro/Dev/AI/language-distillation
google-chrome --headless=new --disable-gpu --no-sandbox --virtual-time-budget=10000 \
  --window-size=1600,1000 --screenshot=/tmp/opencode/dict.png \
  "http://localhost:8000/#dictionary" 2>/dev/null
ls -la /tmp/opencode/dict.png
```

Read `/tmp/opencode/dict.png` with the image tool and confirm visually:

- the `Dicionário` tab is active and the Dictionary pane is visible;
- the left rail shows the A–Z letter bar and the three facet groups;
- the result list is populated with Marúbo headwords;
- the reading pane shows a headword in the display serif with a POS badge, the gloss, and an italic example with a source reference;
- the left border of the entry is coloured by status.

- [ ] **Step 4: Verify the search, the expert toggle, and the print button**

```bash
cd /home/luandro/Dev/AI/language-distillation
google-chrome --headless=new --disable-gpu --no-sandbox --virtual-time-budget=10000 \
  --dump-dom "http://localhost:8000/#dictionary" 2>/dev/null > /tmp/opencode/dom2.html
grep -c "dict-result-item" /tmp/opencode/dom2.html
grep -c "dict-letter-btn" /tmp/opencode/dom2.html
grep -c "dict-facet-chip" /tmp/opencode/dom2.html
```

Expected: all three counts are non-zero.

Then exercise the print endpoint directly:

```bash
curl -s -X POST http://localhost:8000/api/dictionary/print \
  -H 'Content-Type: application/json' \
  -d '{"lang":"mzr","view":"clean"}' | head -c 400
```

Expected: `{"status": "success", "pdf": "/formats/mzr/dictionary_mzr_printable.pdf", ...}`.

- [ ] **Step 5: Run the complete test suite one final time**

```bash
cd /home/luandro/Dev/AI/language-distillation
.venv/bin/python -m pytest tests/ -q -x --ignore=tests/integration 2>&1 | tail -20
```

Expected: all tests pass (or skip).

- [ ] **Step 6: Track the work on the board**

The board is `tsk`, project `agent-harnesses` per `AGENTS.md`; this repository's tasks
carry the project path `/home/luandro/Dev/AI/language-distillation`. Add a task
recording what shipped:

```bash
tsk add "Dictionary session + print edition: Dicionário tab (search, A-Z, facets, Simple/Expert) and the WeasyPrint/Charis print edition" \
  --project /home/luandro/Dev/AI/language-distillation 2>&1 | tail -5
```

If the `tsk` CLI rejects the `--project` flag, list the board first and use the
interactive form:

```bash
tsk list --all --json 2>&1 | head -c 2000
```

Set the new task to `review` when the work is done; only the owner sets `done`.

- [ ] **Step 7: Final commit**

```bash
cd /home/luandro/Dev/AI/language-distillation
git status --short
git add -A
git commit -m "chore: dictionary session and print edition complete" || echo "nothing to commit"
```

---

## Appendix A: End-to-end acceptance checklist

Use this to confirm the whole feature before declaring it done.

| # | Check | How | Expected |
|---|---|---|---|
| 1 | The dictionary session loads | `curl localhost:8000/api/dictionary/session?lang=mzr` | 200, 892 entries |
| 2 | Entries are sorted and bucketed correctly | `pytest tests/unit/test_web_dictionary_api.py` | passes |
| 3 | `á` buckets under A | the same test | `by_head["ártemis"] == "A"` |
| 4 | Search is diacritic-insensitive | `node` harness in Task 8 Step 3 | `westise` finds `wẽstisẽ`; `nuke` finds `nukẽ` |
| 5 | The PDF exists and is a real PDF | `pdfinfo exports/mzr/formats/dictionary_mzr_printable.pdf` | ≥ 40 pages |
| 6 | Charis is embedded | `pdffonts <pdf>` | `Charis ... emb yes` |
| 7 | Diacritics survive the PDF | `pdftotext <pdf> -` | contains `ẽa`, `wẽstisẽ` |
| 8 | Guide words are in the running head | the PNG inspection in Task 4 Step 7 | first and last headword visible |
| 9 | Every advertised download link works | the loop in Task 9 Step 4 | all 200 |
| 10 | The print button returns a PDF path | `curl -X POST .../api/dictionary/print` | `"status": "success"` |
| 11 | The full suite passes | `pytest tests/ -q` | pass or skip |

## Appendix B: Known risks

| Risk | Mitigation |
|---|---|
| WeasyPrint needs the Pango system library; a CI image without it fails to import | The PDF tests use `pytest.importorskip("weasyprint")` and `skipif` on `pdftotext`/`pdffonts`. The import in `pdf.py` is lazy and guarded. |
| The print render takes 30–60 s | The endpoint reports "generating…" to the user. The artifact is also built ahead of time by `export_all_formats`. |
| `exports/web/index.html` is now ~3,500 lines | The Dictionary logic is in `exports/web/dictionary.js`. Consider extracting the CSS into a stylesheet in a later pass. |
| The `data-status` attribute drives the entry border colour; an unrecognised status falls back to `other` | `known = ['validated','supported','candidate'].includes(status) ? status : 'other'` in `dictionary.js`. |
| A `candidate` entry could read as settled in Simple view | The border is a *dashed* line for `candidate`, solid for `supported`, solid green for `validated`, and the preface explains the markers. |
