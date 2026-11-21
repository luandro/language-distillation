---
name: clef
description: Pivot-side semantic quality judge, structural constraint validator, and lexicon audit for low-resource language synthesis (ADR-0020, ADR-0021)
version: 1.0.0
---

# Clef: Semantic Quality Judge & Dictionary Audit

Clef is the quality enforcement gateway for synthetic parallel corpora and lexical knowledge in the Language Knowledge Base (LKB).

## Three-Layer Evaluation Architecture (ADR-0020)

1. **L0: Grounding Guard (Mandatory Hard Gate):**
   - Every target-language token must decompose into attested LKB stems and affixes.
   - Any hallucinated morpheme or stem triggers an immediate `rejected` status (Invariant 9).
2. **L1: Deterministic Structural Checks:**
   - Token alignment between target phrase and Leipzig Interlinear Glossed Text (IGT).
   - Ergative/Absolutive case consistency (e.g., `-n` ERG marking matching transitive predicates).
   - TAM alignment: Tense/Aspect/Modality suffixes must strictly match Portuguese translation features (e.g. negation `-ma`, future `-katsai`).
3. **L2: Pivot-Side Plausibility Judge:**
   - Operates **strictly on the pivot language (Portuguese)** semantic frame (`agente`, `paciente`, `verbo`, `traducao`, `glosa`).
   - Checks selectional restrictions (e.g., preventing inverted animacy violations such as "peixe mata menino").
   - Complies with Invariant 10 & ADR-0006: target-language surface forms never leak to external, uncalibrated APIs.

## Quarantining Semantics ("Put Aside")

- Phrases failing L1 or L2 checks receive `QualityStatus.QUARANTINED` with structured `FailureReason` codes:
  - `selectional_violation`
  - `semantic_implausibility`
  - `tam_mismatch`
  - `gloss_mismatch`
- Quarantined data is segregated from `synthetic_trainable.json` and presented in dedicated audit UI tabs.

## Lexicon Audit & Gloss Classification (ADR-0021)

- Evaluates Portuguese glosses in `src/langpipe/lexicon/audit/clef_gloss.py`.
- Classifies entries into canonical clean lemmas, onomastics/proper nouns, and affixed forms requiring quarantine.
- Supports the bilingual reverse search index (`src/langpipe/lexicon/reverse.py`).
