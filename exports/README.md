# Marúbo (`mzr`) Distilled Language Artifacts

This directory contains the tangible outputs distilled from the pipeline:

## Files in this Directory

1. **[`dictionary.md`](./dictionary.md)**:
   - Formatted bilingual dictionary (Marúbo $\leftrightarrow$ Português).
   - Tables with headwords, parts of speech, Leipzig grammatical glosses, and attested sentence examples.
   - Ready to read in GitHub, VS Code, or convert to PDF/HTML.

2. **[`dictionary.json`](./dictionary.json)**:
   - Full machine-readable lexicon and grammar inventory.
   - Ideal for loading directly into applications, translation memories, or LLM contexts.

3. **[`cldf/`](./cldf/)**:
   - International standard **Cross-Linguistic Data Formats (CLDF)** Dictionary package:
     - `entries.csv`: Headwords, POS, source references.
     - `senses.csv`: Translated definitions and semantic domains.
     - `Dictionary-metadata.json`: Frictionless JSON table schemas.
     - `sources.bib`: BibTeX academic provenance.

4. **[`synthetic_data_generator.py`](./synthetic_data_generator.py)**:
   - Standalone Python tool (`chmod +x`).
   - Run directly: `python3 exports/synthetic_data_generator.py`
   - Features:
     - **Grounding Validator**: Automatically flags any LLM hallucinated words not present in the dictionary.
     - **Combinatorial Generator**: Constructs verified parallel training pairs.
     - **Prompt Builder**: Prepares constrained prompt payloads for LLMs.

5. **[`parallel_candidates/`](./parallel_candidates/)**:
   - Parallel-text extractions that are **structurally verified but not promotable yet** (each file
     has a README stating its blocker and promotion conditions).
   - Deliberately outside `harvested_parallel/` so they never enter a training split by accident:
     `load_harvested_parallel_sentences()` only reads `exports/harvested_parallel/*_parallel.jsonl`.

6. **[`harvested_parallel/`](./harvested_parallel/)**:
   - Attested `mzr` ↔ `por` pairs that are clean enough to train on: the Cesarino 2017 chapter
     (105 pairs) and the **born-digital Cesarino 2018 *Wenía* chant (921 pairs, diacritics
     intact)**. This is the directory `load_harvested_parallel_sentences()` reads; the 2013
     book's OCR-damaged rows live outside it in `parallel_candidates/`.

7. **[`llm_fewshot_prompt.json`](./llm_fewshot_prompt.json)**:
   - Ready-to-use API payload for ChatGPT, Claude, Gemini, or local models (Llama/Ollama).
   - Contains system constraints, vocabulary allowlists, and few-shot exemplars with Leipzig-compliant IGT glosses.

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
