# ADR-0009: Relational lineage, object registry and append-only observations

**Status:** Proposed

## Context
`ARCHITECTURE.md` requires lineage to use explicit relations rather than only JSON, and to support transitive impact analysis. `DOMAIN-MODEL.md` lets EvidenceItems and lineage point at any kind of object, which is polymorphic. Plain PostgreSQL foreign keys cannot point at "any table". The docs also do not specify:

- which direction lineage edges point;
- how ProcessingRun input and output IDs are stored;
- how observation immutability is enforced in storage.

## Decision
1. **Object registry.** An `object_registry(id, entity_type, created_at)` table gets one row for every addressable entity: source, source_object, processing_run, artifact, segment, token_occurrence, form and evidence_item. The row is inserted in the same transaction as the entity. Polymorphic references use foreign keys to `object_registry.id`: lineage endpoints, evidence targets and run inputs and outputs.
2. **Edge direction.** A lineage edge points from the derived object to the object it depends on (`from_id` = child, `to_id` = parent), matching `EvidenceItem ─derived_from─► Observation`. For `supersedes`, `from_id` is the newer object. Self-edges and edges that would create a cycle are rejected with `InvalidLineage`.
3. **Impact query.** `descendants(id)` is a recursive query over reversed edges. It returns `(id, min_depth)`. In PostgreSQL it uses `WITH RECURSIVE`.
4. **Run inputs and outputs** are stored in `processing_run_io(run_id, object_id, role ∈ {input, output})`. Every derived row also carries a non-null `run_id` foreign key ("created_by").
5. **Append-only enforcement.**
   - The domain repository exposes no update or delete operations for observations, evidence, lineage, policies, artifacts, raw blobs, audit events or run I/O.
   - PostgreSQL `BEFORE UPDATE OR DELETE` triggers reject those operations.
   - `source` may change only `status` and `updated_at`.
   - `processing_run` may change only from `running` to a terminal state, and only once.
   - Administrative correction of observations is not supported in M1. It needs its own ADR.

## Consequences
Lineage has referential integrity across entity types, and impact analysis is a single query. Every insert costs one extra registry row. Tests can truncate tables, because TRUNCATE does not fire row-level triggers; production code never truncates.

## Alternatives rejected
- **One edge table per entity pair.** The number of tables explodes, and transitive queries become unions.
- **Unchecked `(type, id)` columns.** They allow dangling lineage.
- **Graph database.** It is out of scope by ADR-0002.
