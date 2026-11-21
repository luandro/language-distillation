# Local Agent Handoff Prompt

Use the prompt below with the local implementation agent after placing this documentation bundle where the agent can read it.

---

You are the implementation agent for an evidence-first Indigenous language resource distillation system.

Your first task is to integrate the provided documentation bundle into the current repository and begin implementation **without inventing unresolved architecture**.

## Required workflow

1. Inspect the current repository before changing anything:
   - existing `AGENTS.md` or agent instructions;
   - README/docs;
   - package/dependency manager;
   - source tree and tests;
   - database/migration setup;
   - git status and recent relevant history.

2. Read the provided root `AGENTS.md` and treat its invariants as mandatory.

3. Integrate the documentation using the bundle's intended paths:
   - root `AGENTS.md`;
   - root `README.md` only when appropriate;
   - `docs/*.md`;
   - `docs/languages/*.md`;
   - `docs/adr/*.md`.

4. If equivalent files already exist:
   - compare them;
   - preserve correct repository-specific information;
   - merge rather than blindly overwrite;
   - report contradictions;
   - do not silently choose between conflicting architecture rules.

5. Validate internal documentation links and ensure root `AGENTS.md` routes tasks to the relevant docs without requiring every document to be read for every task.

6. Before implementation, produce a concise implementation note containing:
   - current repo state;
   - how docs were integrated;
   - conflicts/gaps found;
   - M1 implementation plan;
   - files/modules to create or change.

Do not stop for confirmation unless a real architecture conflict makes safe progress impossible. Otherwise proceed with the documented baseline.

## Development scope: M1 only

Implement the evidence substrate in `docs/DEVELOPMENT.md`.

M1 includes:

- typed IDs and enums;
- governance/source-policy model;
- Source and SourceObject;
- immutable raw object-store abstraction;
- ProcessingRun and Artifact;
- Segment;
- TokenOccurrence;
- Form;
- initial EvidenceItem and LineageEdge foundation;
- PostgreSQL persistence and Alembic migrations;
- Pydantic boundary models;
- CLI for source registration and ingestion;
- generated/checked schemas described by `docs/SCHEMAS.md`;
- golden fixture scaffold;
- governance/invariant tests.

M1 explicitly does **not** include:

- production morphology induction;
- synthetic generation;
- model fine-tuning;
- graph database;
- vector database;
- LLM-generated target-language forms;
- Jev/Clef target-language judgment.

## Implementation constraints

- Follow test-driven development for domain behavior.
- Preserve observation/inference separation.
- Raw source bytes are immutable.
- Every derived record carries ProcessingRun lineage.
- All processing is source-policy checked.
- Logs must not emit restricted content by default.
- Keep language-specific behavior behind a language-profile interface.
- Use PostgreSQL as canonical storage; do not introduce Neo4j.
- Keep external tools behind adapters.
- An aligner or morphology tool may create evidence/candidates, never validated linguistic truth directly.
- A persisted schema/interface decision not covered by the docs requires an ADR proposal.
- For behavior marked OPEN, implement only the smallest reversible abstraction; do not permanently resolve it without an ADR.
- Do not weaken tests or regenerate golden expected output simply to make failures disappear.

## Preferred stack

If the repository has no established equivalent:

- Python 3.12+
- uv
- Pydantic v2
- SQLAlchemy 2
- Alembic
- PostgreSQL 16+
- Typer
- pytest + Hypothesis
- Ruff
- mypy or pyright
- Docker Compose

If equivalent tooling already exists, prefer repository consistency and document deviations instead of performing unnecessary migrations.

## M1 tests that must exist

At minimum prove:

1. raw source bytes cannot be mutated through the domain API;
2. denied policy prevents processing before work begins;
3. ingest creates complete source/run/lineage records;
4. rerunning identical ingestion is idempotent;
5. restricted raw content is absent from default logs;
6. source-object hash verification detects corruption;
7. observation records remain unchanged when downstream hypotheses change;
8. serialized schema artifacts match generated models.

## Deliverables for this pass

1. integrated documentation;
2. architecture-consistent project skeleton;
3. migrations;
4. M1 domain models and services;
5. source registration/ingestion CLI happy path;
6. M1 invariant tests;
7. golden fixture scaffold;
8. generated schema artifacts;
9. updated developer commands/README where needed;
10. final implementation report with:
    - completed work;
    - commands/tests run and results;
    - decisions made;
    - ADRs added;
    - unresolved items;
    - recommended next task, which should be M2 unless M1 exposed a contract problem.

Do not begin M2 until M1 tests pass and the evidence-domain semantics are stable enough that future stages will not need to bypass them.
