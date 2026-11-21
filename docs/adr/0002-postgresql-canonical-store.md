# ADR-0002: PostgreSQL as canonical store

**Status:** Accepted

## Context
The domain is graph-shaped, but v1 needs transactions, constraints, migrations and operational simplicity.

## Decision
Use PostgreSQL as canonical persistence. Represent the logical graph with typed tables/relations and lineage edges. Do not introduce Neo4j in v1.

## Consequences
One datastore, strong constraints, recursive lineage queries, and room for later graph projections.
