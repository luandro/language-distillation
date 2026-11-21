---
name: language-distillation
description: Core architectural domain skill for the evidence-first Language Knowledge Base (LKB) distillation pipeline
version: 1.0.0
---

# Language Resource Distillation Pipeline

Architectural domain skill governing the end-to-end distillation of low-resource indigenous languages into a canonical, versioned, auditable Language Knowledge Base (LKB).

## Canonical 12 Non-Negotiable Invariants

1. **Raw sources are immutable** (`var/external/` and `var/raw/`).
2. **Observation and inference are different entities.** Never overwrite observed facts with linguistic interpretations.
3. **Hypotheses are not facts.** Machine confidence never silently promotes an entity to `validated`.
4. **Lineage:** Every derived object retains complete provenance to its evidence and processing run.
5. **Governance enforced in code.**
6. **Presence is authorization.** A source present in the repository is authorized for processing and training; licenses, ownership, rights holders, and register labels are recorded metadata, never gates, and only an explicit `exclude` policy blocks a source entirely (ADR-0025). Every training row still needs a trace id.
7. **Ambiguity preservation:** Unknown or ambiguous linguistic analyses must remain representable.
8. **Related-language evidence creates hypotheses, never target-language truth.**
9. **Zero LLM hallucinations:** Do not use an LLM to invent target-language morphology or lexical forms.
10. **Zero unauthorized egress:** No third-party API receives restricted material without explicit policy approval.
11. **Persisted format changes require migration, tests, and documentation.**
12. **Architectural decisions are recorded as ADRs.**

## Pipeline Stage Lifecycle

```
[Raw Ingest] ──> [Extract/Normalize] ──> [Tokenize] ──> [Parallel Alignment (eflomal)]
       │
       └──> [Lexical Induction] ──> [Morphology Graph] ──> [Clef Synthesis & Gating]
                                                                     │
                                                       [CLDF / NMT / Web Export]
```

## Entity Lifecycle States
`candidate → supported → validated` (or `rejected`); `deprecated` is terminal.
Only authorized human reviewers can promote entities to `validated`.
