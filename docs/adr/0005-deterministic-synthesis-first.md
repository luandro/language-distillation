# ADR-0005: Deterministic target-language synthesis first

**Status:** Accepted for cold start

## Context
Unrestricted generation in an unseen language risks invented morphology, calqued syntax and self-reinforcing back-translation errors.

## Decision
Initial target-language synthesis, when implemented, follows semantic frame → validated lexicon → morphology → grammar → surface form. LLMs may assist pivot-language frame creation, not invent target-language forms.

## Consequences
Lower volume, stronger inspectability and lineage. Constrained neural realization may be benchmarked later.
