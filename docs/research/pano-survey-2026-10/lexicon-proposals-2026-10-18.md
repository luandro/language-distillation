# Lexicon proposals — Proto-Panoan CLDF (2026-10-18)

The highest-yield *lexical* resource identified by the survey is now acquired, registered and
extracted into a reviewable proposal artifact. Nothing was merged into the dictionary: that is a
lexicon change and must pass the Clef gloss pipeline first (ADR-0020/0021).

## Source

- **Dataset:** `oliveiraprotopanoan` — CLDF Wordlist derived from Sanderson Castro Soares de
  Oliveira's *Contribuições para a Reconstrução do Protopáno* (Lexibank).
- **DOI:** `10.5281/zenodo.10214016` · **Licence:** CC-BY-4.0.
- **Files:** `forms.csv` (7,305 rows), `languages.csv` (19 Panoan varieties + Proto-Panoan),
  `parameters.csv`, `sources.bib`, all in `var/external/cldf_oliveiraprotopanoan/` with
  `SHA256SUMS`, `SOURCE.md` and a `langpipe-manifest.yaml`.
- **Governed store:** `source_id = src_01M581WXCKXG1K1BCH67GWV83W`, registration run
  `run_01M581WXBYAT9RHSB8R6W622GF`, ingest run `run_01M581X3H6PRGJVM2JWJYZ598X`; all four
  objects verified `status=ok` with matching SHA-256.

## Extraction

`scripts/extract_cldf_forms.py` filters the CLDF to `Language_ID = Marubo` and writes
`exports/lexicon_proposals/cldf_marubo_forms.jsonl`:

- **324 proposals / 266 distinct concepts** (CLDF `Parameter_ID`), each carrying `ref` (CLDF row
  ID), `form`, `value`, `segments`, `cognacy`, per-row `source`, and lineage
  (`dataset_id`, `dataset_doi`, `language_id`); `status: candidate`.
- Per-row provenance, which is the real value here — every form says where it came from:

  | Source in CLDF | Rows |
  |---|---:|
  | Cesarino 2008 | 95 |
  | Oliveira 2014 | 81 |
  | Anonby 2010 (SIL Javari survey) | 70 |
  | Costa 1992 | 27 |
  | Cabral 2010 | 21 |
  | Kennell 1978 | 15 |
  | Costa 2000 | 1 |

  `Kennell 1978` and `Cabral 2010` were not in the repo's known-source inventory; the CLDF row
  count also confirms the SIL Javari wordlist as a significant Marúbo source (70 rows here, ~375
  concepts unextracted — see the survey digest).

## Overlap with the current lexicon

Measured against `var/external/marubo_vocab/marubo_lexicon.tsv` (1,099 entries) with a normalised
comparison (strip stress/hyphen, `ɨ→3`, `ɐ̃→ã`, deaccent fallback):

- 31 forms already present exactly,
- 21 more present after deaccenting,
- **272 have no form match** in the current lexicon.

So this is not a marginal addition, but it is also not 272 brand-new lexemes: the CLDF is
IPA-style transcription of the same sources the lexicon partly came from, so a share of the
"new" forms are additional pronunciations/inflections of known lemmas.

## Why nothing was promoted

1. **Orthography.** The CLDF is IPA-ish (`ˈɐ̃ni-`, `ʔak-`); the repo uses Costa's practical
   orthography (`3` for `ɨ`). An explicit IPA→orthography mapping must be recorded as a
   normalisation step — inventing mappings would violate invariant 9.
2. **Provenance variability.** The 95 Cesarino-2008 rows and 27 Costa-1992 rows overlap sources
   already held; the 21 Cabral-2010 and 15 Kennell-1978 rows come from publications not yet in
   the repo. Promotion should not collapse these into one undifferentiated set.
3. **Clef.** Dictionary/lexicon changes must pass `src/langpipe/lexicon/audit/clef_gloss.py`
   gloss classification. That is the next gate, not a formality.

## Siblings to ingest next (same method)

| Dataset | Marúbo volume | Note |
|---|---|---|
| `zariquieypano` | 187 forms / 181 concepts | all rows `Source=fleck2005` (unpublished fieldnotes) — candidate-only |
| `panobodyparts` | 26 body-part forms | overlaps `zariquieypano`; dedupe by concept+form |
| `valenzuelazariquieypanotakana` | 25 forms (`Language_ID=Mar`) | best provenance, small |
| `keypano` | 0 (no Marúbo) | 23,232 forms of Panoan comparanda — hypotheses only (invariant 8) |

Reproduce:

```bash
.venv/bin/python scripts/extract_cldf_forms.py \
    --dataset-dir var/external/cldf_oliveiraprotopanoan \
    --language-id Marubo \
    --dataset-id oliveiraprotopanoan \
    --dataset-doi 10.5281/zenodo.10214016 \
    --out exports/lexicon_proposals/cldf_marubo_forms.jsonl \
    --qa var/artifacts/cldf_oliveiraprotopanoan/extraction_qa.json
.venv/bin/pytest tests/unit/test_extract_cldf_forms.py -q
```
