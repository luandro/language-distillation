# ADR-0003: CLDF as interchange, not canonical persistence

**Status:** Accepted

## Context
CLDF is excellent for interoperable lexical/cross-linguistic resources but does not model every internal review/governance/hypothesis workflow.

## Decision
Use CLDF for appropriate import/export while retaining internal evidence state in PostgreSQL.

## Consequences
External interoperability without forcing the internal domain into CLDF. Export mappings must be explicit and tested.
