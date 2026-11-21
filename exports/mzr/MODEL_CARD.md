# Model Card: Marúbo (mzr) ↔ Portuguese (por) NLLB-200 600M LoRA

**Model Name**: `mzr-nllb-600m-lora`  
**Base Architecture**: `facebook/nllb-200-distilled-600M` (Meta AI)  
**Tuning Method**: Parameter-Efficient Fine-Tuning (PEFT) via Low-Rank Adaptation (LoRA)  
**Target Language**: Marúbo (`mzr`, Glottocode: [`maru1252`](https://glottolog.org/resource/languoid/id/maru1252))  
**Language Family**: Panoan (Pano-Tacanan)  
**Territory**: Terra Indígena Vale do Javari (Amazonas, Brazil)  
**Contact Language**: Portuguese (`por`, `por_Latn`)  
**Panoan Seed Language**: Shipibo-Konibo (`shp`, `shp_Latn`)  
**Date**: October 2026  
**Pipeline Framework**: [Language Distillation Pipeline (`langpipe`)](file:///home/luandro/Dev/AI/language-distillation)

---

## 1. Model Summary

`mzr-nllb-600m-lora` is a bidirectional neural machine translation (NMT) model fine-tuned for high-precision translation between **Marúbo** (an endangered Panoan language of the Javari Valley) and **Portuguese**.

To overcome the extreme low-resource bottleneck while avoiding catastrophic forgetting:
1. **Panoan Transfer Learning**: The newly added token `mzr_Latn` is initialized from the weighted embedding representation of its closest phylogenetic relative in NLLB-200, **Shipibo-Konibo** (`shp_Latn`), combined with the contact language **Portuguese** (`por_Latn`):
   $$\mathbf{e}_{\text{mzr}} = 0.75 \cdot \mathbf{e}_{\text{shp}} + 0.25 \cdot \mathbf{e}_{\text{por}}$$
2. **Trainable Token Embedding with Frozen Backbone**: Only the Marúbo token embedding row and the low-rank adaptation matrices ($\sim 1.2\text{M}$ parameters, $\approx 0.20\%$ of total parameters) are optimized, preserving cross-lingual transfer while adapting to Marúbo syntax and morphology.
3. **Dual-Register Benchmark**: Unlike single-domain models, evaluation is conducted across both **traditional secular oral mythology** and **scriptural corpora**, ensuring stylistic generality.

---

## 2. Strict Governance & Ethical Invariants (AGENTS.md)

This model adheres strictly to the non-negotiable architectural invariants of the **Vale do Javari Language Knowledge Base**:

* **Invariant 1 (Raw Source Immutability)**: Raw sources (`var/external/marubo_sources/`) are write-protected and verified with SHA-256 checksums.
* **Invariant 2 (Zero-Leakage Gold Standard)**: The evaluation splits (`test.hf.jsonl` and `val.hf.jsonl`) consist **strictly of 100% human-attested translations**. Synthetic data is **permanently blocked** from test and validation benchmarks ($0.0\%$ synthetic contamination).
* **Invariant 4 (Lineage Retention)**: Every training and evaluation example retains explicit provenance back to its published citation or academic manuscript.
* **Invariant 6 (Distill-Only Protection)**: Running academic thesis prose (e.g. Costa 1992, 2000) is quarantined for morphological extraction only and never directly injected into training pairs.
* **Invariant 9 (Zero LLM Hallucination of Indigenous Morphology)**: No large language model was permitted to invent target-language vocabulary or grammar rules. Synthetic data was synthesized exclusively using a deterministic valence grammar verified by the Clef 3-gate filter (ADR-0020, ADR-0021).
* **Invariant 10 (Restricted Material Protection)**: No restricted ritual or shamanic texts were transmitted to external third-party APIs.

---

## 3. Dataset Composition & Provenance

Datasets are exported from the canonical Language Knowledge Base (LKB) into HuggingFace NMT (`.hf.jsonl`), Alpaca Instruction (`.alpaca.jsonl`), and ChatML (`.chatml.jsonl`) formats.

### Partition Breakdown

| Partition | Total Pairs | Human-Attested Pairs | Harvested Secular Oral (Cesarino 2017) | Scriptural Verses (ScriptureEarth) | Clef Synthetic Curriculum | Human Purity |
|---|---|---|---|---|---|---|
| **Train** | **4,725** | 4,701 | 30 | 4,671 | 24 | 99.49% |
| **Validation** | **543** | 543 | 25 | 518 | 0 | **100.0%** |
| **Gold Test** | **250** | 250 | 50 | 200 | 0 | **100.0%** |
| **Total** | **5,518** | **5,494** | **105** | **5,389** | **24** | — |

*When bidirectional expansion (`por→mzr` and `mzr→por`) is applied, the effective datasets comprise **9,402 train**, **1,086 validation**, and **500 gold test** pairs.*

### Cryptographic Manifest (`exports/mzr/datasets/manifest.json`)

| File Name | SHA-256 Checksum | Format Description |
|---|---|---|
| `train.hf.jsonl` | `13b34966768e113b390d57d743d113ff5283857640f7f2adf49878145ad595ff` | HuggingFace parallel translation jsonl |
| `val.hf.jsonl` | `c7112001ebdc9a7c3d12eebc47c1686c7189f1730b344c78415decce4c542f84` | Pure human validation benchmark |
| `test.hf.jsonl` | `a714c0a66b83b11a05bdf6f8cc1c83820a932ea82dca9b14470aa73066176259` | Pure human gold test benchmark |
| `train.alpaca.jsonl` | `d1dab6bb3314621b572ad157b3b895ddb9f1412eadd923785ee9ada70bc4c6f3` | Alpaca instruction-tuning format |
| `val.alpaca.jsonl` | `98beb615d2d16b2b03375225960b6974f24b2d48cdc3ac71f72ab14dbf069a82` | Alpaca validation format |
| `test.alpaca.jsonl` | `765e00181fcd2ec5e2742f923715f6b1e3847caa57ee53fc6f661e4304824d43` | Alpaca evaluation format |
| `train.chatml.jsonl` | `b7571ea270d9f53de5bb27fd8823b6472c2770885d59c9fa8d95ece4e04feaad` | OpenAI ChatML conversational format |
| `val.chatml.jsonl` | `4182e3e1d6f26a6375aeeb6040356593493cac17a1bc23aa01d330c8c8648cbe` | ChatML validation format |
| `test.chatml.jsonl` | `d714340fcdaf65e9b43c9b19c0ab7937528b40ff0829ce655de2de37a889cbf1` | ChatML evaluation format |

---

## 4. Training Hyperparameters

The training configuration reproduces the validated pipeline from [`notebooks/Marubo_NLLB_600M_Finetune.ipynb`](file:///home/luandro/Dev/AI/language-distillation/notebooks/Marubo_NLLB_600M_Finetune.ipynb) and [`scripts/train_nllb_lora.py`](file:///home/luandro/Dev/AI/language-distillation/scripts/train_nllb_lora.py):

* **Base Model**: `facebook/nllb-200-distilled-600M`
* **Optimizer**: AdamW ($\beta_1=0.9, \beta_2=0.999, \epsilon=10^{-8}$)
* **Learning Rate**: $2 \times 10^{-4}$ with linear warmup
* **Batch Size**: 4 per device (effective batch size 16 with gradient accumulation steps = 4)
* **Epochs**: 3
* **Precision**: bfloat16 / fp16 auto-detected
* **Max Source Length**: 256 tokens (covers 100% of corpus sentences, mean length: 18.76 words)
* **Max Target Length**: 256 tokens
* **LoRA Target Modules**: `["q_proj", "v_proj"]`
* **LoRA Rank ($r$)**: 16
* **LoRA Alpha ($\alpha$)**: 32
* **LoRA Dropout**: 0.05
* **Trainable Token Indices**: `[mzr_Latn]` (token ID 256,206)

---

## 5. Evaluation & Quality Metrics

Evaluation is performed using **SacreBLEU** with post-processing to strip language special tags:

1. **chrF++ (Primary Metric)**:
   - Config: `word_order=2` (character n-gram F-score + word bigrams).
   - *Rationale*: Marúbo is an agglutinative Panoan language with complex nominal case marking (ergative `-n` / `-nin`, locative `-ano`, comitative `-bëte`) and verbal aspectual suffixes (`-ai`, `-ke`, `-baon`, `-kan`). Traditional word-level BLEU severely penalizes correct roots with inflectional variations; `chrF++` accurately reflects morphological accuracy.
2. **spBLEU (Secondary Metric)**:
   - Uses Flores-200 SentencePiece tokenization baseline.
3. **Elder & Speaker Review**:
   - Model generations on the gold test set are automatically serialized to `evaluation_predictions.jsonl` with full source IDs for human review by native Marúbo community members and linguists.

---

## 6. How to Run

### Interactive Notebook
Open [`notebooks/Marubo_NLLB_600M_Finetune.ipynb`](file:///home/luandro/Dev/AI/language-distillation/notebooks/Marubo_NLLB_600M_Finetune.ipynb) in Google Colab, RunPod, or JupyterLab.

### Headless CLI Runner
Execute via the reproducible runner script:

```bash
# 1. Fast dry-run / integrity gate verification (0 MB weight download)
uv run python scripts/train_nllb_lora.py --dry-run

# 2. Full fine-tuning run on GPU
uv run python scripts/train_nllb_lora.py \
    --base-model facebook/nllb-200-distilled-600M \
    --output-dir checkpoints/mzr-nllb-600m-lora \
    --epochs 3 \
    --batch-size 4 \
    --grad-accum 4 \
    --lr 2e-4

# 3. Evaluation only on gold test set
uv run python scripts/train_nllb_lora.py \
    --output-dir checkpoints/mzr-nllb-600m-lora \
    --eval-only
```

---

## Access and data status

- The Hugging Face repo `luandro/marubo-nllb-600m-lora` is private. Checked on 2026-10-18 via the HF API: it reported `private=True`, and anonymous access returned not found. It was already private at check time, so no visibility change was made that day.
- Reason for private status (as stated by the maintainer): `evaluation_predictions.jsonl` contained scripture source/reference pairs from a `distill_only` source. Under ADR-0025 the concern that applies here is raw-text redistribution (`redistribute_raw`, still hard-denied under `distill_only`); the `distill_only` label itself does not block training.
- The adapter was trained on that source.
- No public redistribution of those pairs is intended.

---

## 7. Citations & Attribution

If you utilize this model or the Marúbo Language Knowledge Base, please cite the foundational sources:

```bibtex
@incollection{cesarino2017marubo,
  author    = {Cesarino, Pedro de Niemeyer and Marubo Cherõpapa Txano, Armando Mariano and Doles Marubo, Robson Dionísio},
  title     = {Marubo: The teachings of the Death-Path},
  booktitle = {Texts in Indigenous Languages of the Americas},
  publisher = {Language Science Press},
  year      = {2017},
  doi       = {10.5281/zenodo.1008779}
}

@phdthesis{costa2000fonologia,
  author    = {Costa, Raquel Guimarães Romankevicius},
  title     = {Aspectos da Fonologia Marubo (Pano): uma visão não-linear},
  school    = {Universidade Federal do Rio de Janeiro (UFRJ)},
  year      = {2000}
}

@mastersthesis{costa1992padroes,
  author    = {Costa, Raquel Guimarães Romankevicius},
  title     = {Padrões rítmicos e marcação de caso em Marubo (Pano)},
  school    = {Universidade Federal do Rio de Janeiro (UFRJ)},
  year      = {1992}
}
```
