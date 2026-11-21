# M1 golden fixture

Purpose: a tiny corpus that the pipeline runs end to end. The golden test in
`tests/golden/test_golden_m1.py` checks the M1 outputs against `tests/golden/expected/m1/`.
The normative description of the fixture is `docs/GOLDEN-FIXTURE.md`.

## Synthetic data statement

Every word, sentence and gloss here is invented for testing. Nothing is taken from real
community material, and no real Marúbo data is used. Do not replace these files with real
language data.

## Language codes

- `qaa`: the synthetic target language (ISO 639-3 private-use code). Its forms are invented.
- `por`: the pivot language (Portuguese), used for the translations.
- `und`: undetermined. Used only by the excluded source, which has no content.

## Encoding

All files are UTF-8 NFC, except one deliberate NFD line in `sources/05-monolingual/text.txt`
(`kanu` + U+0301). That line documents a normalization case for M2.

## Sources

| Directory | Mode | Access | Type | Role |
|---|---|---|---|---|
| `01-parallel-distill` | `distill_only` | community | parallel_text | bilingual structured source; trainable (ADR-0025), raw redistribution still hard-denied |
| `02-educational-direct` | `direct` | public | educational_publication | bilingual lessons |
| `03-wordlist` | `direct` | public | wordlist | tiny dictionary |
| `04-igt` | `review_required` | community | igt | interlinear glossed text |
| `05-monolingual` | `direct` | community | monolingual_text | target-language text |
| `06-excluded` | `exclude` | highly_restricted | other | governance check; no objects |

Each manifest sets `authority: "synthetic fixture steward"`, `acquired_at: 2026-01-01T00:00:00Z`
and provenance `acquired_from: "synthetic"`.

Which fixture line exercises which phenomenon is listed in `PHENOMENA.md`.
