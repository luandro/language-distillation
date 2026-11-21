# Documentation Map

This directory is split by **question**, so contributors and agents can load only the context they need.

Paths under `var/` and `exports/` that appear throughout these documents are **local build
artifacts**, not part of the repository: they embed third-party text that cannot be
redistributed. A fresh clone has the code, schemas, tests and docs only — see
[the data-availability section in the top-level README](../README.md#licence-and-data-availability)
for what is excluded and how to rebuild it.

## Normative documents

| Document | Answers |
|---|---|
| `PRODUCT.md` | What are we building and not building? |
| `ARCHITECTURE.md` | What are the subsystems and dependencies? |
| `DOMAIN-MODEL.md` | What entities/relations constitute the evidence/language graph? |
| `EVIDENCE-AND-CONFIDENCE.md` | How do evidence, scores, hypotheses and validation work? |
| `PIPELINE-CONTRACTS.md` | What does each stage consume and produce? |
| `MORPHOLOGY.md` | How is morphology and ambiguity represented? |
| `GOVERNANCE.md` | What may be done with each source and descendants? |
| `REVIEW-WORKFLOW.md` | How are human decisions requested and recorded? |
| `EVALUATION.md` | How do components get benchmarked/promoted? |
| `DEVELOPMENT.md` | How should the system be built/tested? |
| `SCHEMAS.md` | Which machine-readable schemas must exist? |
| `GOLDEN-FIXTURE.md` | What tiny corpus proves end-to-end semantics? |

## Language profiles

`languages/README.md` defines the language-adapter contract.

`languages/mzr.md` contains the Marúbo pilot profile. Facts there are labeled as documented, community-validated, working assumption, or open.

## ADRs

`adr/` contains Architecture Decision Records. ADRs explain why a decision was made. A later ADR may supersede an earlier one. ADR-0001 through ADR-0003 and ADR-0011 (parallel segment and token alignment) are **Accepted**; ADR-0004 to ADR-0006 are **Accepted for cold-start/baseline**; ADR-0007 to ADR-0009 are **Proposed** (awaiting ratification); ADR-0010 (derived segments) is **Proposed (Decided for Milestone 2)**.

## Implementation plans

`implementation/` contains milestone work-package plans for implementers (e.g. `implementation/M1-PLAN.md`, `M2-PLAN.md`, `M3-PLAN.md`). These plans are not normative. Where a plan and a normative doc disagree, the normative doc wins and the plan must be corrected.

## Recommended reading paths

### Ingestion
`AGENTS.md` → `ARCHITECTURE.md` → `DOMAIN-MODEL.md` → `GOVERNANCE.md` → `PIPELINE-CONTRACTS.md`

### Alignment
`AGENTS.md` → `ARCHITECTURE.md` → `DOMAIN-MODEL.md` → `PIPELINE-CONTRACTS.md` → `adr/0011-parallel-segment-and-token-alignment.md` → `EVALUATION.md`

### Morphology
`AGENTS.md` → `DOMAIN-MODEL.md` → `MORPHOLOGY.md` → `EVIDENCE-AND-CONFIDENCE.md` → `GOLDEN-FIXTURE.md`

### Review
`AGENTS.md` → `REVIEW-WORKFLOW.md` → `DOMAIN-MODEL.md` → `GOVERNANCE.md`

### New language
`AGENTS.md` → `languages/README.md` → nearest language profile → add benchmark fixtures.
