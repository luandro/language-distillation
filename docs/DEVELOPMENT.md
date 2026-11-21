# Development Guide

## Initial stack

Unless the repository already has an equivalent established stack:

- Python 3.12+
- `uv`
- Pydantic v2
- SQLAlchemy 2
- Alembic
- PostgreSQL 16+
- Typer
- pytest
- Hypothesis
- Ruff
- mypy or pyright
- Docker Compose

Consistency with an existing equivalent stack is preferable to gratuitous migration.

## Suggested package structure

```text
src/langpipe/
├── cli/
├── config/
├── domain/
├── governance/
├── storage/
│   ├── db/
│   └── objects/
├── ingestion/
├── extraction/
├── normalization/
├── segmentation/
├── alignment/
├── lexicon/
├── morphology/
├── igt/
├── review/
├── exports/
├── evaluation/
└── lineage/
```

Keep external-tool adapters separate from domain logic, e.g. `alignment/adapters/eflomal.py`.

## M1 — Evidence substrate

Deliver:
- source policy models;
- source registry;
- immutable raw object-store abstraction;
- ProcessingRun/Artifact;
- Segment;
- TokenOccurrence;
- Form;
- initial EvidenceItem/LineageEdge;
- DB migrations;
- source add/ingest CLI;
- golden fixture skeleton;
- governance tests.

Do not implement model training.

## M2 — Text processing

Deliver extractor interface, simple source adapters, normalization profile interface, tokenizer interface, Marúbo profile stub and idempotent run behavior.

## M3 — Parallel evidence

Deliver SegmentAlignment, canonical alignment importer, token-alignment adapter protocol, eflomal adapter, TokenAlignmentEdge persistence and benchmark harness.

## M4 — Lexical evidence

Delivered (2026-10-16):

- Lexeme/Sense/Concept/FormLexemeLink domain models and M4 enums (WP4.1);
- migration 0004 lexical and review tables with append-only triggers; migration 0005 `stale_dependent` lineage kind (WP4.2);
- lexical and review repository layer with row locking and shared memory/PostgreSQL contracts (WP4.3);
- `lexical-v1` evidence scoring policy — `candidate` → `supported` only (WP4.4);
- lexical induction protocol and alignment co-occurrence adapter (WP4.5);
- governed wordlist source adapter and raw ingestion (WP4.6);
- Stage 6 `LexicalService` and `langpipe lexicon induce` (WP4.7);
- review queue service, authority registry and `langpipe review list`/`decide` (WP4.8);
- revocation impact over lexical lineage (WP4.9);
- governed CLDF import/export with pycldf (WP4.10);
- golden fixture M4 (WP4.11);
- contract documentation and CI accounting (WP4.12).

## M5 — IGT and morphology graph

Deliver Xigt-compatible IGT import, Morpheme/Allomorph/MorphAnalysis/MorphSegment/Feature models, competing analyses, morphology benchmark harness and first morphology adapter.

Only after M5 should synthetic generation be designed in code.

## Tests

### Unit
Pure domain rules, policies, parsers and serializers.

### Property
Useful for normalization idempotence, span preservation, policy monotonicity and serialization round trips.

### Integration
PostgreSQL, migrations, object store and CLI.

### Golden
End-to-end semantics from tiny corpus to expected graph.

## Migration rules

Every persisted schema change uses Alembic. Preserve lineage. Run forward/backward tests when practical. Destructive semantic changes need an ADR.

## Logging

Logs include IDs rather than restricted raw text by default.

## Errors

Prefer typed errors such as `PolicyDenied`, `UnsupportedSource`, `ExtractionFailed`, `NormalizationFailed`, `AlignmentFailed`, `InvalidLineage`, `SchemaViolation`.

Failed stages must not leave partially valid semantic outputs.

## CI baseline

```text
ruff
static type check
pytest unit
pytest integration
schema generation/check
golden fixture
migration check
cldf validation — in-process inside CLDFExporter (pycldf validate on the staging dir before commit)
```

Decision (WP4.12): there is no separate `cldf validate` CI step. The exporter validates the staged dataset with pycldf before anything is committed, so it cannot publish an invalid dataset; a second validator invocation in CI would only add a redundant dependency path. Coverage comes from the CLDF service and golden tests.

## Definition of done

A change is done when contract, tests, docs and migrations are aligned; no invariant is weakened; golden output changes only intentionally; ADRs exist for architecture changes.

## Local commands (M1)

`scripts/ci.sh` runs the whole gate in this order. Each step can also be run on its own:

```sh
export LANGPIPE_TEST_DATABASE_URL="${LANGPIPE_TEST_DATABASE_URL:-postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe_test}"
uv sync --frozen                                   # install locked dependencies
uv run ruff check .                                # lint
uv run ruff format --check .                       # formatting
uv run mypy src                                    # static types
uv run python -m langpipe.schemas check            # committed schemas/ match the generated models
docker compose up -d --wait db                     # PostgreSQL 16 (localhost:55432)
uv run alembic -x url="$LANGPIPE_TEST_DATABASE_URL" upgrade head   # migrate the test database
LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -q       # unit, contract, service, golden and integration tests
```

- The `export` line matters when running the block by hand. If `LANGPIPE_TEST_DATABASE_URL` is unset, `-x url=""` is empty and Alembic falls back to the application settings, so the export must come first.
- `scripts/ci.sh` checks the URL before any Alembic call: the parsed database name must end in `_test`, and `dbname`, `database` or `service` query parameters are rejected. Other or malformed URLs exit nonzero without printing the URL. The test fixtures apply the same `_test` rule before migrating or truncating. Other Alembic invocations are not restricted by this check, so never point any migration at the application database.
- Optional local mode: without `LANGPIPE_REQUIRE_POSTGRES=1`, integration tests skip when PostgreSQL is unreachable. Those skips are expected.
- Required CI mode: with `LANGPIPE_REQUIRE_POSTGRES=1` (as in `scripts/ci.sh`), an unreachable PostgreSQL fails the test run, and any skipped test makes pytest exit nonzero. Start the database first (`docker compose up -d db`).
- Because *any* skip is fatal in required mode, a test that conditionally imports a tool must have that tool in the `dev` dependency group, or the gate becomes unpassable while still looking green locally. `sacrebleu` is there for exactly this reason: `test_scorer_matches_sacrebleu_corpus_score` checks our BLEU/chrF against the reference implementation, and it used to `importorskip` a package declared nowhere (tsk #277). Do not add an `importorskip` without also declaring its package.
- If `docker` itself reports the daemon is unreachable, check `DOCKER_HOST` before concluding the daemon is down: it may be pinned to a failed rootless socket (`/run/user/<uid>/docker.sock`) while the system daemon is healthy at `/var/run/docker.sock`.
- To regenerate schemas after a model change: `uv run python -m langpipe.schemas generate`. Commit the result.

## Local commands (M2)

`scripts/ci.sh` is unchanged from M1 and remains the whole gate: the same command order, with the M2 tests (unit, contract, service, golden, integration) picked up by the single `pytest -q` call. The `realdata` marker stays deselected in the default gate — `pyproject.toml` sets `addopts = "-ra --strict-markers -m 'not realdata'"` and the script never passes a `-m` override (`tests/unit/test_ci_script.py` guards this).

Stage processing commands (`extract`, `normalize`, `tokenize`) write concise `key=value` lines to stdout and never print segment text, token surfaces, TSV cell values, titles or file names. Helper commands (`scriptureearth manifest`, `profiles list`) output metadata and destination file paths (e.g. `manifest_path=...`).

```sh
uv run langpipe extract SOURCE_REF [--extractor NAME[@VER]] [--language ISO]
uv run langpipe normalize SOURCE_REF [--extraction-run RUN_ID] [--profile ISO=NAME@VER]...
uv run langpipe tokenize SOURCE_REF [--extraction-run RUN_ID] [--profile ISO=NAME@VER]... [--tokenizer ISO=NAME@VER]...
uv run langpipe profiles list
uv run langpipe scriptureearth manifest PACKAGE_DIR --key KEY --language ISO --policy POLICY_YAML \
    --acquired-from URI --rights-holder TEXT --acquired-at ISO8601 [--include-timing]
```

- `tokenize` runs normalize first (reusing an identical earlier normalization run) and then tokenize, producing two runs.
- Migration forward/backward roundtrip exercises upgrade and downgrade against the configured disposable test database (`LANGPIPE_TEST_DATABASE_URL`):
  ```sh
  LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest tests/integration/test_migrations.py -q
  ```
  The migration fixture downgrades the test database during testing and re-applies migrations; therefore, all database-backed acceptance commands (`scripts/ci.sh`, migration tests, realdata PostgreSQL tests) must be run **sequentially**, not concurrently against the same test database. Never downgrade the populated M2 production database: migration 0002 must reject new artifact kinds.
- Opt-in real data (operator machine only; never in default CI). Requires the locally acquired ScriptureEarth Marúbo package and reviewed manifest (acquisition steps in `docs/languages/mzr.md`):
  ```sh
  export LANGPIPE_MZR_SE_DIR="$PWD/var/external/scriptureearth/mzr"
  export LANGPIPE_MZR_SE_MANIFEST="$LANGPIPE_MZR_SE_DIR/langpipe-manifest.yaml"
  LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -m realdata -q
  ```
  Selecting `-m realdata` explicitly overrides the default deselection (pytest applies the last `-m`).

## Local commands (M3)

`scripts/ci.sh` remains the authoritative local CI gate, running all M1–M4 test suites (unit, contract, service, golden, and integration). The default gate keeps both `realdata` and `native_alignment` deselected (`pyproject.toml` addopts `-m 'not realdata and not native_alignment'`), keeping base CI fast and compiler-free. Zero-skip rule: with `LANGPIPE_REQUIRE_POSTGRES=1` (as in `scripts/ci.sh`), *any* skipped test — not only database skips — fails the session (`tests/fixtures/db.py` checks skipped item ids at session end), so "zero skips" is enforced, not hoped for. Informational baseline measured 2026-10-16: ≈2053 passed / 41 deselected in ≈10 minutes — a measurement, not a contract.

Stage 4 and Stage 5 alignment commands:

```sh
uv run langpipe align segments SOURCE_A_REF SOURCE_B_REF --namespace NAME \
  [--method canonical_locator@0.1.0] [--source-language LANG] [--target-language LANG] \
  [--source-normalization-run RUN_A] [--target-normalization-run RUN_B] \
  [--versification-id ID] [--threads N] [--timeout-seconds SEC]

uv run langpipe align tokens SEGMENT_ALIGNMENT_RUN_ID \
  [--method eflomal@0.1.0] [--source-tokenization-run TOK_RUN_A] [--target-tokenization-run TOK_RUN_B] \
  [--symmetrization none|intersection|union] [--threads N] [--timeout-seconds SEC] [--seed INT]
```

- **Segment alignment** (`align segments`):
  - `--namespace` is **required**; if `--namespace scripture`, `--versification-id` is also required.
  - `--source-normalization-run` and `--target-normalization-run` may be omitted only under unique selection (exactly one candidate normalization run per side); if multiple exist, the CLI raises `AmbiguousInput` (exit 11).
  - Establishes n:m hyperedges between segments matching structural coordinates or human disposition records.
- **Token alignment** (`align tokens`):
  - Aligns tokens between approved/structural segment alignment groups using statistical alignment behind the eflomal adapter protocol.
  - `--source-tokenization-run` and `--target-tokenization-run` derive from recorded normalization sides; omitted flags require exactly one candidate tokenization run per side (or `AmbiguousInput` exit 11).
  - `--symmetrization` accepts lowercase `none`, `intersection`, or `union` (default `intersection`). Heuristic grow-diag is explicitly excluded.
  - Unsupported seeds fail with `AlignmentFailed(unsupported_seed)` (exit 12).
- **Output format**: Prints `run_id`, `report_id`, counts, and `reused` as key=value lines. No source prose or token strings are printed.
- **Compiler-free baseline**: By default, `scripts/ci.sh` runs compiler-free with `eflomal` uninstalled. Tests requiring native compilation are isolated and marked `native_alignment`.
- **Native alignment testing**: Requires the optional `alignment` extra to compile eflomal C extensions:
  ```sh
  uv sync --extra alignment
  LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -m native_alignment -q
  ```
- **Sequential database execution**: The migration fixture in `tests/integration/test_migrations.py` downgrades and upgrades the database; all database-backed test commands (`scripts/ci.sh`, migration tests, realdata tests) MUST be executed sequentially, never concurrently against the same test database.
- **CI database refusal guard**: `scripts/ci.sh` enforces that `LANGPIPE_TEST_DATABASE_URL` must end in `_test` and rejects `dbname`, `database`, or `service` query overrides without printing credentials.
- **Opt-in parallel real data (operator only)**: Dual-source real-data integration test for ScriptureEarth Marúbo and Portuguese USFM packages:
  ```sh
  export LANGPIPE_MZR_SE_DIR="$PWD/var/external/scriptureearth/mzr"
  export LANGPIPE_MZR_SE_MANIFEST="$LANGPIPE_MZR_SE_DIR/langpipe-manifest.yaml"
  export LANGPIPE_POR_SE_DIR="$PWD/var/external/ebible/porbr2018"
  export LANGPIPE_POR_SE_MANIFEST="$LANGPIPE_POR_SE_DIR/langpipe-manifest.yaml"
  LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -m realdata tests/integration/test_scriptureearth_parallel.py -q
  ```
  Missing packages, missing rights, or unsigned metadata expectations fail safely with content-free diagnostics.

## Local commands (M4)

`scripts/ci.sh` is unchanged and picks up the M4 suites in the same single `pytest -q` call. Stage 6, review, interchange and lineage commands:

```sh
uv run langpipe lexicon induce --run-id RUN_ID [--method alignment_cooccurrence@0.1.0] \
    [--target-language ISO] [--contact-language ISO]
uv run langpipe review list [--type TASK_TYPE] [--role ROLE] [--status STATUS] \
    [--min-priority FLOAT] [--language ISO] [--limit N]
uv run langpipe review decide --task-id TASK_ID --decision accept|reject|modify|uncertain|defer \
    --reviewer ID --role ROLE [--notes TEXT] [--superseding OBJECT_ID]
uv run langpipe cldf import SOURCE_REF [--target-language ISO] [--contact-language ISO] [--extract-only]
uv run langpipe cldf export --language ISO --output-dir DIR [--include-supported]
uv run langpipe lineage descendants OBJECT_ID
```

- `lexicon induce` consumes exactly one succeeded predecessor run — a Stage 5 token-alignment run, a wordlist extraction run, or a CLDF extraction run (`--extract-only` import). The method family must match the input run type; a mismatch refuses before any write. A non-succeeded or ambiguous input exits 11 (`AmbiguousInput`).
- `review decide` checks the reviewer against the authority registry built from language profiles before any write; `modify` requires `--superseding`. Review roles come from profile configuration — there is no built-in reviewer.
- `cldf export` stages the dataset, validates it with pycldf, then commits; `--output-dir` refuses a non-empty directory, so an existing dataset is never overwritten.
- `lineage descendants` prints `depth`, `object_id` and `entity_type` per reachable descendant.
- Output rule: every command prints `key=value` lines of IDs, enum values and counts only — no forms, glosses or source prose on stdout.
