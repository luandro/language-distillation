# ADR-0001: Evidence-first architecture

**Status:** Accepted

## Context
Source material may be linguistically valuable while unsuitable as training prose. Automated analyses are uncertain and improve over time.

## Decision
Separate immutable observations from evidence, hypotheses and validated knowledge. Processing stages create evidence/hypotheses instead of overwriting observations.

## Consequences
Algorithms can be rerun, uncertainty survives, provenance remains auditable and source revocation can be traced. Cost: more explicit entities and lineage.

## Alternatives rejected
Corpus-first cleaned datasets collapse provenance; one canonical analysis per token destroys ambiguity.
