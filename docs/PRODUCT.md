# Product Definition

## Product statement

Build a reusable system that turns heterogeneous language resources into a community-governed, versioned, auditable **Language Knowledge Base (LKB)**.

Inputs may include religious parallel text, school/community publications, NGO/government publications, dictionaries, grammars, IGT, monolingual corpora, and aligned or alignable audio.

Outputs include observed forms, lexemes/senses/concepts, bilingual lexical hypotheses, morphemes/allomorphs, competing morphological analyses, paradigms/features, grammar constructions, pronunciation/aligned speech, sociolinguistic labels, evidence, provenance, confidence, and review decisions.

## Why

Extremely low-resource languages can have substantial linguistic knowledge embedded in material that is not suitable as balanced direct fine-tuning data.

The pipeline separates:

```text
source material
    ↓
observations
    ↓
evidence
    ↓
linguistic hypotheses
    ↓
validated language knowledge
    ↓
eligible downstream datasets
```

A source can inform a dictionary or grammar without its prose becoming training data.

## Primary users

- community/language stewards;
- linguists and language-resource engineers;
- ML/NLP engineers;
- coding/automation agents.

## Core promises

The system MUST make these statements defensible:

1. We know which sources support a linguistic claim.
2. An interpretation is explicitly a hypothesis until validated.
3. A source may be allowed for distillation while denied for direct training.
4. Source revocation can identify affected descendants.
5. Synthetic examples can be traced to the knowledge that produced them.
6. Future models can reuse the LKB without reconstructing the corpus.

## Non-goals for v1

v1 is not:

- a general-purpose LLM platform;
- an autonomous linguist;
- a replacement for speaker validation;
- a model-training framework first;
- a graph-database research project;
- a public corpus portal by default.

## v1 success

v1 can:

- govern multiple source types;
- ingest raw material immutably;
- extract normalized segments without losing originals;
- represent token occurrences and cross-lingual alignment evidence;
- induce hypotheses without collapsing ambiguity;
- import IGT;
- export lexical CLDF;
- maintain complete lineage;
- produce review queues;
- demonstrate revocation impact;
- pass a golden fixture;
- keep every training row traceable: a row is eligible only when it carries a trace id
  (`source_id`, `policy_id`, or `provenance`), and only an explicit `exclude` policy blocks a
  source. A `distill_only` label never blocks training; it only keeps raw redistribution
  closed (ADR-0025).

> **Optimize for durable linguistic infrastructure, not maximum generated token count.**
