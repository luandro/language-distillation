# Language Distillation Pipeline

An evidence-first system for turning heterogeneous, community-governed language resources into an auditable language knowledge base: lexical forms, senses, concepts, morphology, grammar, aligned speech, provenance, and eventually controlled synthetic training data.

The first pilot language is Marúbo (`mzr`), but the architecture is explicitly reusable for other extremely low-resource languages.

## Start here

- Coding agents: read [`AGENTS.md`](AGENTS.md) first.
- Humans/new contributors: read [`docs/PRODUCT.md`](docs/PRODUCT.md), then [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
- Changing persisted linguistic entities: read [`docs/DOMAIN-MODEL.md`](docs/DOMAIN-MODEL.md).
- Changing a pipeline stage: read [`docs/PIPELINE-CONTRACTS.md`](docs/PIPELINE-CONTRACTS.md).
- Touching morphology: read [`docs/MORPHOLOGY.md`](docs/MORPHOLOGY.md).
- Touching source use, consent, access, lineage, or export: read [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md).

## Core principle

> Sources are evidence. Evidence becomes structured linguistic knowledge. Only explicitly eligible material becomes training data.

The canonical product is the **versioned language knowledge base**, not a particular fine-tuned model.

## Documentation authority

In case of conflict:

1. community/governance restrictions;
2. root `AGENTS.md` invariants;
3. normative domain and pipeline contracts under `docs/`;
4. checked schemas and golden tests once implemented;
5. ADRs explain why decisions were made, but may be superseded;
6. README prose is orientation, not a contract.

See [`docs/README.md`](docs/README.md) for the complete documentation map.

## Licence and data availability

The code and documentation in this repository are MIT licensed (see
[`LICENSE`](LICENSE)).

**No language data is published here.** Source material lives outside the
repository, and every derived export is a local, regenerable artifact:

| Path | What it holds | How to get it |
|---|---|---|
| `var/` | source PDFs, raw text, harvest caches | operator-supplied, never committed |
| `exports/` | datasets, dictionaries, CLDF, IGT, chant rows, probes | `uv run langpipe synth export`, `langpipe lexicon`, `langpipe cldf` |
| `tests/golden/expected/m5/` | WP5.16 fixtures | local work in progress; `tsk` #221 |

The exporters read locally acquired inputs from `var/`, so a fresh clone can
rebuild an export only after the sources are in place. A clone is fully testable
without them: tests that need local data are marked `pytest.mark.realdata` and
deselected by default.

This is not only tidiness. Some sources carry licences that permit local
processing and training but not redistribution (ADR-0025 changed what the
pipeline enforces internally; it did not grant onward rights). The pipeline
records every source, licence status and register label in
[`docs/governance/source-license-audit.md`](docs/governance/source-license-audit.md),
and `var/` never enters git.

What is pending, and who owns it, is tracked in
[`docs/PENDING.md`](docs/PENDING.md).

## Development quickstart

Requirements: Python 3.12, `uv`, and Docker Compose.

```sh
uv sync --frozen                      # install locked dependencies
docker compose up -d --wait db        # PostgreSQL 16 on localhost:55432
./scripts/ci.sh                       # full local gate (lint, types, schemas, migrations, tests)
```

`.skills/impeccable/` is a git submodule. It is not needed to run the pipeline; to fetch it:

```sh
git submodule update --init --recursive
```

`scripts/ci.sh` is the reference for what must pass before a change is done. See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md#local-commands-m1) for the individual commands.
