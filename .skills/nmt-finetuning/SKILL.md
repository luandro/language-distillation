---
name: nmt-finetuning
description: NLLB-200 600M LoRA parameter-efficient fine-tuning, vocabulary expansion, and cross-lingual transfer for low-resource indigenous languages
version: 1.0.0
---

# NMT Fine-Tuning: NLLB-200 600M LoRA

Standardized procedures for fine-tuning Meta's `facebook/nllb-200-distilled-600M` for bidirectional translation between extremely low-resource indigenous languages (e.g., Marúbo `mzr_Latn`, Tikuna `tca_Latn`) and contact languages (Portuguese `por_Latn`).

## Key Methodological Principles

1. **Panoan Family Cross-Lingual Transfer:**
   - Initialize new language token embeddings (`mzr_Latn`) by transferring embedding weights from related Panoan languages already in NLLB-200 (such as Shipibo-Konibo `shp_Latn`) blended with contact language embeddings (`por_Latn`).
2. **Dataset Gating:**
   - Consume only validated synthetic and attested parallel data exported from `uv run langpipe synth export`.
   - Never ingest raw uncurated sentences or quarantined Clef failures.
3. **LoRA Configuration:**
   - Target Modules: `q_proj`, `v_proj`, `k_proj`, `out_proj` (optional: `encoder.layers.*`, `decoder.layers.*`).
   - Rank: `r = 16` or `32`, `lora_alpha = 32` or `64`, `lora_dropout = 0.05`.
   - Precision: `bfloat16` if supported, otherwise `float16`.
4. **Evaluation Benchmarks:**
   - chrF++ (primary for agglutinative/polysynthetic morphology), spBLEU (Flores-200 tokenizer), and token-level lexical grounding audit.

## Artifacts & Notebooks

- Reference training notebook: `notebooks/Marubo_NLLB_600M_Finetune.ipynb`
- Export command: `uv run langpipe synth export --lang mzr --output-dir exports/mzr/datasets/`
