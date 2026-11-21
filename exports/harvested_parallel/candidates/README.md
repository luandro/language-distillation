# Candidates (evidence for owner admission)

This directory holds the output of the Costa (2002) example extractor:
- `costa_2002_candidates.jsonl` — accepted evidence rows
- `costa_2002_held_back.jsonl` — blocks refused with a machine-readable reason

**Admission is not automatic.** These candidates are evidence that the owner may
review and decide whether to admit into a training corpus. Admission consists of
copying accepted rows into the parallel training file
(`*_parallel.jsonl`); nothing is admitted automatically just because a row appears
here.

**Hold reasons** (why a block was refused):
- `no_gloss_tier` — no grammatical gloss tier present
- `no_translation` — no quoted Portuguese free translation
- `translation_not_sentence` — translation present but not a grammatical sentence
- `ocr_noise` — OCR noise characters or bare digit runs in the Marúbo line
- `starred_example` — leading `*`?`#` ungrammaticality mark on the Marúbo line
- `multiple_translations` — more than one quoted Portuguese translation
- `ambiguous_boundary` — uncertain example boundary or multiple candidate utterances
- `word_list_not_sentence` — only a word list or quoted phrase, no sentence translation

**File provenance:** source file `var/external/marubo_sources/costa_2002.txt`,
SHA-256 embedded in each row for integrity verification.

**Usage:** run `uv run python scripts/extract_costa_examples.py` to regenerate.

## Decision (2026-11-04)

Per senior review (Codex `gpt-6.1-sol`) and owner confirmation:
- Costa (1992, 2000, 2002, 2017) and Cesarino 2013 remain **segment-only evidence** for this iteration.
- Costa candidates are held back from training splits due to phonetic-orthography divergence from the practical NLLB target.
- Training proceeds on the 5,018 existing eligible rows (ScriptureEarth + Wenía + Cesarino & Marúbo 2017).