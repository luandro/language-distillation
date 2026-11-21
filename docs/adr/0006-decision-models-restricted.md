# ADR-0006: Restrict decision-model use on unseen target language

**Status:** Accepted for cold start

## Context
Jev/Clef-class bounded decision models may be useful, but confidence on unseen-language text cannot be assumed calibrated.

## Decision
They MAY classify supported pivot-language/document tasks but MUST NOT be final authorities on target-language meaning or grammaticality until a local benchmark/calibration gate is passed.

## Consequences
Use a provider-neutral interface with target-language permissions gated by configuration/benchmark status.
