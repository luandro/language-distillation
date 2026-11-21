# Architecture

## Architectural style

The system is an **evidence-first modular pipeline** backed by a canonical relational store.

It exposes a logical linguistic graph, but the initial implementation stores explicit entities/relations in PostgreSQL.

```text
Governance + Source Registry
            │
            ▼
     Immutable Raw Store
            │
            ▼
 Extraction / Normalization
            │
            ▼
 Segments / Token Occurrences
            │
            ├──────────────► Parallel Segment Evidence
            │                         │
            │                         ▼
            │                  Token Alignment Evidence
            │                         │
            ▼                         ▼
 Monolingual Evidence ───────► Lexical Hypotheses
                                      │
                         ┌────────────┴────────────┐
                         ▼                         ▼
                    Morphology                   IGT
                         │                         │
                         └────────────┬────────────┘
                                      ▼
                           Language Knowledge Base
                                      │
                             Human validation
                                      │
                                      ▼
                            Eligible knowledge view
```

## Components

### Source Registry
Owns source identity, hashes, languages, type, governance policy, processing restrictions and domains/registers.

### Raw Store
Stores exact source bytes or immutable source-object references. It is hash-verified, access-controlled and never queried by a training exporter.

### Processing Run Registry
Every stage records stage, tool/version, config hash, code revision, input/output IDs, timestamps, status/error and random seed when relevant.

### Evidence Store / LKB
PostgreSQL stores observations and inferences with explicit semantics.

### Artifact Store
Stores larger generated artifacts: extracted text snapshots, alignment files, CLDF exports, TextGrid/EAF, benchmark reports and datasets.

### Review Service
Creates typed review tasks and immutable review decisions.

### Exporters
Consume explicit eligible views: CLDF, Xigt/LIFT, evaluation sets and future training datasets.

## Dependency direction

Correct:

```text
extractor → segment → token → alignment evidence → lexical hypothesis → morphology hypothesis
```

Incorrect:

```text
aligner → writes dictionary entry directly
```

A stage may only create objects owned by its contract.

## Persistence baseline

- PostgreSQL 16+
- SQLAlchemy 2
- Alembic
- Pydantic v2 at boundaries

SQLite MAY be used for isolated unit tests; use PostgreSQL integration tests for DB-specific behavior.

## IDs

Use stable opaque IDs with readable prefixes, e.g.:

```text
src_<ulid> seg_<ulid> tok_<ulid> form_<ulid>
lex_<ulid> sense_<ulid> ma_<ulid> morph_<ulid>
review_<ulid> run_<ulid> artifact_<ulid>
```

IDs MUST NOT depend on row position or mutable text.

## Idempotency

A stage MUST be safely rerunnable with the same inputs/config.

Raw ingestion deduplicates bytes by hash while preserving distinct provenance when needed.

## Text

Retain raw and normalized text plus normalization profile/version. Never rely on normalized text to reconstruct raw source.

## Lineage

Core lineage MUST use explicit relations, not only arbitrary JSON:

```text
Hypothesis ─supported_by─► EvidenceItem
EvidenceItem ─derived_from─► Observation / Artifact / Run
```

Tool-specific score details MAY use JSONB.

## Search

Initial search MAY use PostgreSQL full-text/trigram capabilities. No Elasticsearch/OpenSearch in v1.

## Security

Minimum access classes:

```text
public
community
restricted
highly_restricted
```

Derived resources may be more permissive than their sources only when policy explicitly permits it.

## Deployment

v1 SHOULD run locally with Docker Compose: app/CLI + PostgreSQL + optional object-store abstraction.

## Explicitly deferred

- graph DB;
- distributed workflow engine;
- Kubernetes;
- vector DB as primary evidence store;
- unrestricted target-language generation;
- production model serving.
