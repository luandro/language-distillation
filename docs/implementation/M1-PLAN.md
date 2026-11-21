# M1 Implementation Plan — Evidence Substrate

> **Superseded policy note (ADR-0025).** Any rule below that blocks processing or
> training because of a source's classification, licence, rights holder, or register is
> historical. Presence in the repository authorizes processing and training; licences
> and ownership are records, not gates.

Status: reviewed; orchestrator decisions pending (see Review log) · Author: senior architect pass · Date: 2026-10-11

This plan is written for junior implementers. **Every name, field, enum value, table and file path below is decided. Do not rename or "improve" them.** If something here seems wrong or missing, stop and report it instead of inventing an alternative.

---

## 1. Current repository state

- Greenfield. One commit (`29428bd docs: import language-distillation docs bundle v0.3`) containing only documentation: `AGENTS.md`, `README.md`, `LOCAL-AGENT-HANDOFF.md`, `BUNDLE-MANIFEST.json`, `docs/**` (25 Markdown files).
- No `pyproject.toml`, source tree, tests, migrations or Docker configuration.
- Local tools: `uv`, CPython 3.12.7 (uv-managed), Docker and Docker Compose v5. There is no local `psql`; all database access goes through Docker Compose service `db` (postgres:16).

## 2. Documentation integration

- The bundle already sits at its intended paths, so nothing needed merging and no pre-existing docs conflicted with it.
- **Link check:** every Markdown link in `README.md` resolves. Every backtick path in the `AGENTS.md` routing table, `docs/README.md` and `LOCAL-AGENT-HANDOFF.md` resolves to an existing file. `docs/languages/<iso>.md` is a template path and resolves for `mzr`. No broken links were found.
- **Edits made in this pass (no architecture change):**
  - `AGENTS.md` routing table: added a row for `docs/implementation/` (milestone work packages).
  - `docs/README.md`: added an "Implementation plans" section and listed ADR proposals 0007–0009.
  - Added ADR proposals `docs/adr/0007…0009` (status **Proposed**).
- `BUNDLE-MANIFEST.json` records bundle SHA-256 hashes. `AGENTS.md` and `docs/README.md` now differ from those hashes on purpose. The manifest describes the imported bundle and is not a live checksum, so it was left unchanged.

## 3. Conflicts and gaps found

| # | Doc § | Gap / conflict | M1 handling |
|---|---|---|---|
| G1 | `languages/mzr.md` § Religious corpus default vs `GOVERNANCE.md` § Operation permissions | The profile's allow/deny names (`structural_alignment`, `lexical_distillation`, `morphology_evidence`, `audio_alignment`, `style_seed_generation`) are not in the governance vocabulary. | Governance vocabulary is canonical. ADR-0007 proposes a mapping. **The mzr.md fix needs governance-owner approval; not edited.** |
| G2 | `GOVERNANCE.md` § Source policy modes | No mapping from mode to per-operation defaults. `review_required` and `restricted` are underspecified. No default for unlisted operations. | ADR-0007 baseline matrix, fail-closed. |
| G3 | `GOVERNANCE.md` § Operation permissions; `PIPELINE-CONTRACTS.md` Stage 1 | No operation covers storing raw bytes. `archive_only` ("preserve") cannot be told apart from `exclude`. | ADR-0007 adds `ingest`. |
| G4 | `SCHEMAS.md` § Initial schemas | Missing `source-object`, `lineage-edge` and `source-manifest`, all of which M1 needs. The list also includes 15 non-M1 schemas. | M1 generates 11 schemas (§6, WP12). The rest are deferred to their milestones. |
| G5 | `ARCHITECTURE.md` § IDs | No prefixes for policy, source object, evidence, lineage edge or audit event. | ADR-0008: `pol_ sobj_ ev_ lin_ aud_`. |
| G6 | `DOMAIN-MODEL.md` § Source | Source `type` and `status` value sets are not defined. | Enums in WP2. Additive changes only (reversible). |
| G7 | `ARCHITECTURE.md` § Processing Run Registry, § Lineage | How run input/output IDs are stored and which way lineage edges point are unspecified. | ADR-0009. |
| G8 | `ARCHITECTURE.md` § Idempotency | The rerun mechanism is unspecified. | ADR-0008 `run_key` reuse plus natural keys. |
| G9 | `DOMAIN-MODEL.md` § Versioning | "Explicit administrative correction" of observations has no defined mechanism. | M1 provides none; observations are strictly append-only (ADR-0009). A future ADR is required. |
| G10 | `DOMAIN-MODEL.md` § Lifecycle vs `AGENTS.md` § State rules | The full transition graph is unspecified, for example `candidate→validated` directly, or `validated→rejected`. | WP4b strict table (no direct `candidate→validated`; `validated→deprecated` only). Reversible: pure function, nothing persisted in M1. |
| G11 | `DOMAIN-MODEL.md` § Evidence | The representation of the "target claim" is unspecified. | `target_id` (FK to object registry) plus optional `claim` JSON. Reversible. |
| G12 | `GOVERNANCE.md` § Third-party services / `DEVELOPMENT.md` § Logging | Which access classes count as "restricted content" for logging is not defined. | M1 never logs raw/segment/token text **of any class**. Only IDs, hashes, enum values and counts are logged. |
| G13 | `PIPELINE-CONTRACTS.md` Stage 0 | "Language set known or explicitly unknown": no representation is defined. | ISO 639-3 `und` means unknown. Reversible. |
| G14 | `GOLDEN-FIXTURE.md` | Needs alignment, IGT, morphology, review and revocation, which are all post-M1. | M1 ships the full 5-source fixture *data* and M1-stage expectations only (WP13). Later-stage expectations are listed as pending. |
| G15 | `ARCHITECTURE.md` § Security | Derived-artifact access class is not defined. | An artifact's access class is the **most restrictive** class among its inputs. Reversible. |
| G16 | `DEVELOPMENT.md` § M1 vs `LOCAL-AGENT-HANDOFF.md` § M1 | DEVELOPMENT omits schema generation and Pydantic models, which the handoff includes. | Handoff is the superset; this plan follows it. No conflict. |
| G17 | `AGENTS.md` § Scope for the first implementation | Lists extraction, parallel segments, alignment and CLDF, which belong to milestones M2–M4. | Treated as an ordering hint. M1 scope follows `DEVELOPMENT.md` and the handoff. |
| G18 | `GOVERNANCE.md` § Mandatory tests | "Restricted raw endpoint rejects unauthorized actor", "revoked source blocks dependent export" and "policy change triggers recalculation" need actors, exports and revocation, none of which are in M1. | Deferred (M2+). M1 supplies the prerequisites: policy resolution and the `descendants()` query. |

Implementation defects are corrected below. Open architecture disagreements in the Review log prevent an unconditional readiness verdict for affected work packages.

## 4. Decisions for M1

| # | Decision | Classification |
|---|---|---|
| D1 | Policy resolution matrix, `ingest` operation, fail-closed defaults, combining multiple ancestors | **Needs ADR → ADR-0007 (Proposed)** |
| D2 | `<prefix>_<ULID>` IDs and new prefixes; natural keys; `run_key` reuse; manifest `key` and `SourceConflict`; content-addressed raw store; `raw_blob` table | **Needs ADR → ADR-0008 (Proposed)** |
| D3 | `object_registry` with FK-checked polymorphic references; lineage edges point child→parent; `processing_run_io`; append-only DB triggers | **Needs ADR → ADR-0009 (Proposed)** |
| D4 | Repository protocol with two implementations: in-memory (unit tests) and PostgreSQL (integration). Tests that depend on the backend run on both through the parametrized `repo` fixture. **SQLite is not used.** | Reversible implementation detail |
| D5 | Source manifest is YAML (`manifest_version: 1`), with the policy inline (§WP4a) | Reversible (the schema is versioned) |
| D6 | Source type enum, source status enum, artifact kind enum, run stage enum, audit event enum (values in WP2) | Reversible (additive only; values never reused) |
| D7 | Spans use Unicode code points `[start, end)` and carry an explicit `representation` (`raw` or `normalized`), as recommended in `SCHEMAS.md` | Adopts a doc recommendation |
| D8 | Unknown language is `und`. The golden fixture's synthetic target language is `qaa` (ISO 639-3 private-use range), so fixture data never pretends to be Marúbo | Reversible |
| D9 | Configuration comes only from environment variables (no pydantic-settings dependency) | Reversible |
| D10 | Postgres host port `55432` to avoid colliding with any local Postgres. Database `langpipe` for the app and `langpipe_test` for tests | Reversible |
| D11 | Lifecycle transition table as a pure function (WP4b). No entity persists lifecycle state in M1 | Reversible |
| D12 | An artifact's access class is the most restrictive of its inputs (G15) | Reversible |
| D13 | Denied operations write an `audit_event` (`policy_denied`) and no other rows | Reversible |
| D14 | `exclude` sources may be registered (source and policy only; objects are neither hashed nor recorded) | Part of ADR-0007 |

## 5. Global conventions (apply to every WP)

- Python 3.12; `from __future__ import annotations` is **not** used (Pydantic v2 is fine without it).
- All Pydantic domain models inherit `langpipe.domain.models.base.DomainModel`:
  `model_config = ConfigDict(frozen=True, extra="forbid")`. Field assignment is frozen; nested containers are not immutable. Deep-copy models on repository write/read to prevent caller mutations changing persisted observations. Build permitted changed copies by revalidating merged data with `type(model).model_validate(...)`; `model_copy(update=...)` bypasses validation.
- All datetimes are timezone-aware UTC. Naive datetimes are rejected by a validator in `DomainModel` (WP2 creates `base.py`; WP4a and WP4b only import it).
- **Never log, print (except the explicit metadata-only `source show` command) or put into exception messages any raw bytes, segment text, token surface, title or file name.** Use IDs, hashes, enum values and counts. Use `langpipe.logging.log_event` (WP6) for all logging.
- Errors are subclasses of `langpipe.domain.errors.LangpipeError` (WP2). Do not raise bare `Exception`/`ValueError` from services, except for Pydantic validation, which callers wrap into `SchemaViolation`.
- Lint/type gates for every WP: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`.
- Test markers: `integration` means PostgreSQL is needed. A test without the marker MUST NOT touch a database or network.
- Write tests first. The listed test names are mandatory; you may add more.

## 6. Target file layout (end of M1)

```text
pyproject.toml
uv.lock
.python-version                      # "3.12"
.gitignore                           # adds: var/, .venv/, __pycache__/, .pytest_cache/, .mypy_cache/, .ruff_cache/
compose.yaml
docker/postgres/init/01-create-test-db.sql
alembic.ini
migrations/
  env.py
  script.py.mako
  versions/0001_m1_evidence_substrate.py
schemas/                              # generated, committed
  source-manifest.v1.schema.json
  source-policy.v1.schema.json
  source.v1.schema.json
  source-object.v1.schema.json
  processing-run.v1.schema.json
  artifact.v1.schema.json
  segment.v1.schema.json
  token-occurrence.v1.schema.json
  form.v1.schema.json
  evidence-item.v1.schema.json
  lineage-edge.v1.schema.json
scripts/ci.sh
src/langpipe/
  __init__.py                        # __version__ = "0.1.0"
  py.typed
  app_context.py
  logging.py
  config/__init__.py
  config/settings.py
  config/revision.py
  domain/__init__.py
  domain/ids.py
  domain/enums.py
  domain/errors.py
  domain/hashing.py
  domain/lifecycle.py
  domain/models/__init__.py
  domain/models/base.py
  domain/models/source.py           # SourcePolicy, Source, SourceObject, RawBlob, SourceManifest (+specs)
  domain/models/run.py              # ProcessingRun, Artifact, AuditEvent
  domain/models/observation.py      # Span, Segment, TokenOccurrence, Form
  domain/models/evidence.py         # EvidenceItem, LineageEdge
  governance/__init__.py
  governance/policy.py              # baseline matrix + resolve
  governance/guard.py               # require()
  storage/__init__.py
  storage/repository.py             # Repository Protocol
  storage/memory.py                 # InMemoryRepository
  storage/objects/__init__.py
  storage/objects/base.py           # ContentStore Protocol, StoredObject
  storage/objects/local.py          # LocalContentStore
  storage/db/__init__.py
  storage/db/tables.py              # SQLAlchemy 2 ORM tables
  storage/db/engine.py              # make_engine()
  storage/db/repository.py          # PostgresRepository
  ingestion/__init__.py
  ingestion/runs.py                 # RunRecorder
  ingestion/registration.py         # register_source (Stage 0)
  ingestion/ingest.py               # ingest_source (Stage 1)
  ingestion/verify.py               # verify_source
  segmentation/__init__.py
  segmentation/recorder.py          # ObservationRecorder (segments/tokens/forms)
  lineage/__init__.py
  lineage/evidence.py               # EvidenceService
  lineage/impact.py                 # descendants report
  schemas/__init__.py
  schemas/registry.py
  schemas/generate.py               # generate/check + __main__
  schemas/__main__.py
  cli/__init__.py
  cli/app.py
  cli/context.py
  cli/source.py
  cli/lineage.py
  cli/schemas.py
tests/
  __init__.py
  conftest.py
  fixtures/__init__.py
  fixtures/db.py                    # pg availability, migrated engine, cleanup
  fixtures/backends.py              # `backend`/`ctx` fixtures (memory + postgres)
  unit/...                          # pure tests, listed per WP
  contract/test_repository_contract.py
  service/...                       # backend-parametrized service tests
  integration/...                   # postgres-only tests
  golden/
    fixture/...                     # synthetic sources (WP13)
    expected/m1/*.json
    normalize.py
    test_golden_m1.py
```

## 7. Work packages

Dependency graph and parallel groups (a group may start when every earlier group it depends on is merged):

```text
G1: WP1
G2: WP2
G3: WP3 ‖ WP4b ‖ WP5 ‖ WP6 ‖ WP8           (disjoint files; all need only WP2)
G4: WP4a                                     (needs WP3)
G5: WP7 ‖ WP12                               (need WP4a+WP4b)
G6: WP9 (needs WP7, WP8)
G7: WP10 (needs WP5, WP6, WP7, WP9)
G8: WP10b (needs WP6, WP7, WP10 service fixtures)
G9: WP11 ‖ WP13 (both need WP10, WP10b, WP12; WP9 already merged)
G10: WP14
```

---

### WP1 — Project skeleton and tooling

**Goal:** an installable empty package, the toolchain, compose DB and test harness.

**Files (create):** `pyproject.toml`, `.python-version`, `.gitignore`, `compose.yaml`, `docker/postgres/init/01-create-test-db.sql`, `src/langpipe/__init__.py`, `src/langpipe/py.typed`, `tests/__init__.py`, `tests/conftest.py`, `tests/fixtures/__init__.py`, `tests/fixtures/db.py`, `tests/fixtures/backends.py` (placeholder), `tests/unit/test_smoke.py`, `tests/unit/__init__.py`, `tests/unit/storage/__init__.py`, `tests/integration/__init__.py`, `tests/service/__init__.py`, `uv.lock` (generated by `uv sync`). Shared test package initializers belong to WP1 only.

**pyproject.toml (exact requirements):**
- `[project] name="langpipe" version="0.1.0" requires-python=">=3.12"`.
- deps: `pydantic>=2.8,<3`, `sqlalchemy>=2.0.30,<3`, `alembic>=1.13`, `psycopg[binary]>=3.2`, `typer>=0.12`, `pyyaml>=6`, `python-ulid>=2.7,<4`.
- `[dependency-groups] dev = ["pytest>=8", "hypothesis>=6.100", "ruff>=0.6", "mypy>=1.11", "types-PyYAML"]`.
- `[project.scripts] langpipe = "langpipe.cli.app:main"`.
- build backend: hatchling, with `packages = ["src/langpipe"]`.
- `[tool.ruff] line-length=100 target-version="py312"`, `[tool.ruff.lint] select=["E","F","I","UP","B","SIM"]`.
- `[tool.mypy] strict=true plugins=["pydantic.mypy"] python_version="3.12" mypy_path="src"`.
- `[tool.pytest.ini_options] testpaths=["tests"] pythonpath=["."] markers=["integration: requires PostgreSQL (docker compose up -d db)"] addopts="-ra --strict-markers"`.

**compose.yaml:** a single service `db`: image `postgres:16`; env `POSTGRES_USER=langpipe`, `POSTGRES_PASSWORD=langpipe`, `POSTGRES_DB=langpipe`; ports `"55432:5432"`; volume `pgdata:/var/lib/postgresql/data` and `./docker/postgres/init:/docker-entrypoint-initdb.d:ro`; healthcheck `pg_isready -U langpipe -d langpipe` (interval 2s, retries 30).
`01-create-test-db.sql`: `CREATE DATABASE langpipe_test OWNER langpipe;`

**tests/conftest.py:** `pytest_plugins = ["tests.fixtures.db", "tests.fixtures.backends"]`. Nothing else.

**tests/fixtures/db.py (WP1 part):**
- `TEST_DB_URL = os.environ.get("LANGPIPE_TEST_DATABASE_URL", "postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe_test")`.
- `def pg_available() -> bool` attempts `psycopg.connect(<url converted to libpq form>, connect_timeout=2)`, caches the result with `functools.cache`, and never raises.
- fixture `pg_url` (session): calls `pytest.skip("PostgreSQL unreachable; run `docker compose up -d db`")` when unavailable; otherwise returns `TEST_DB_URL`.
- WP8 extends this file. WP1 leaves `# WP8: migrated_engine, clean_db` as the only placeholder.

**tests/fixtures/backends.py:** an empty module with a docstring. WP7 fills it.

**Tests first:** `tests/unit/test_smoke.py::test_package_version` asserts `langpipe.__version__ == "0.1.0"`.

**Acceptance:** `uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy src && docker compose up -d db && docker compose ps db` (healthy).

**Do NOT:** add dependencies not listed here; add a `src/langpipe/main.py`; configure SQLite; add CI YAML (WP14 adds `scripts/ci.sh`).

---

### WP2 — IDs, enums, errors, hashing

**Goal:** the stable primitive vocabulary every other WP imports.

**Files:** `src/langpipe/domain/__init__.py`, `domain/ids.py`, `domain/enums.py`, `domain/errors.py`, `domain/hashing.py`, `domain/models/__init__.py` (empty), `domain/models/base.py` (spec under WP4a "base.py", implemented here so WP4a and WP4b can run in parallel); tests `tests/unit/domain/test_base_model.py` (`test_naive_datetime_rejected`, `test_domain_model_frozen_and_forbids_extra`, `test_id_field_pattern`), plus `tests/unit/domain/test_ids.py`, `test_enums.py`, `test_errors.py`, `test_hashing.py` (plus `tests/unit/domain/__init__.py`).

**ids.py**
```python
class IdPrefix(StrEnum):
    SOURCE="src"; POLICY="pol"; SOURCE_OBJECT="sobj"; RUN="run"; ARTIFACT="artifact"
    SEGMENT="seg"; TOKEN="tok"; FORM="form"; EVIDENCE="ev"; LINEAGE="lin"; AUDIT="aud"
    # reserved for later milestones (define now, unused in M1):
    LEXEME="lex"; SENSE="sense"; MORPH_ANALYSIS="ma"; MORPHEME="morph"; REVIEW="review"
ID_PATTERN: re.Pattern[str]  # r"^(?P<prefix>[a-z]+)_(?P<ulid>[0-9A-HJKMNP-TV-Z]{26})$"
def new_id(prefix: IdPrefix) -> str            # f"{prefix.value}_{ULID()}"
def parse_id(value: str) -> tuple[IdPrefix, str]  # raises InvalidId
def is_id(value: str, prefix: IdPrefix | None = None) -> bool
class IdFactory(Protocol):
    def __call__(self, prefix: IdPrefix) -> str: ...
```

**enums.py** (all `StrEnum`; **values are serialized and frozen**):
- `PolicyMode`: `direct, distill_only, review_required, restricted, archive_only, exclude`
- `Operation`: `ingest, read_raw, extract, normalize, align, distill_lexicon, distill_morphology, distill_grammar, audio_align, human_review, third_party_api, cloud_processing, redistribute_raw, redistribute_derived, direct_training, synthetic_generation_support, evaluation`
- `PolicyDecision`: `allow, review_required, deny`
- `AccessClass`: `public, community, restricted, highly_restricted`. Add the function `access_rank(a: AccessClass) -> int` (0..3 in that order) and `most_restrictive(classes: Iterable[AccessClass]) -> AccessClass` (raises `ValueError` on empty input).
- `SourceType`: `parallel_text, educational_publication, publication, dictionary, wordlist, grammar_description, igt, monolingual_text, audio, video, other`
- `SourceStatus`: `registered, ingested, revoked`
- `RunStage`: `source_registration, raw_ingestion, extraction, normalization, tokenization, segment_alignment, token_alignment, lexical_induction, igt_import, morphology_induction, grammar_extraction, human_review, manual_annotation, export, evaluation`
- `RunStatus`: `running, succeeded, failed`
- `RunIoRole`: `input, output`
- `ArtifactKind`: `ingest_report, extraction_snapshot, alignment_file, cldf_export, benchmark_report, dataset, other`
- `SegmentStatus`: `ok, normalization_failed`
- `SpanRepresentation`: `raw, normalized`
- `EvidenceKind`: `dictionary_assertion, token_alignment, segment_cooccurrence, igt_assertion, grammar_description, speaker_review, morphology_induction, related_language_comparison, monolingual_distribution, manual_annotation`
- `EvidencePolarity`: `supports, contradicts, context_only`
- `LineageKind`: `derived_from, generated_from, normalized_from, extracted_from, imported_from, supersedes`
- `LifecycleStatus`: `candidate, supported, validated, rejected, deprecated`
- `ValidationBasisKind`: `authorized_reviewer, authoritative_import, editorial_decision`. **There is no model-confidence kind, on purpose.**
- `EntityType`: `source, source_object, processing_run, artifact, segment, token_occurrence, form, evidence_item`
- `AuditEventType`: `policy_created, source_registered, raw_ingested, policy_denied`

**errors.py**: `LangpipeError(Exception)` with an `exit_code: ClassVar[int] = 1`. Subclasses and exit codes:
- `PolicyDenied(source_id: str, operation: Operation, decision: PolicyDecision)` → 3
- `SchemaViolation` → 4
- `PolicyConflict(SchemaViolation)` → 4
- `HashMismatch(sha256_expected: str, sha256_actual: str | None)` → 5
- `SourceChanged(HashMismatch)` → 5
- `ObjectMissing(sha256: str)` → 5
- `SourceConflict(key: str)` → 6
- `NotFound(entity_type: str, id: str)` → 7
- `InvalidLineage` → 8
- `InvalidTransition` → 8
- `InvalidId` → 4
- `ImmutableViolation` → 8

Messages contain only the constructor arguments shown, which are IDs, enum values and hashes.

**hashing.py**
```python
def canonical_json(value: Any) -> str  # json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False); datetimes → isoformat; enums → .value; Pydantic models → model_dump(mode="json")
def sha256_bytes(data: bytes) -> str   # lowercase hex
def sha256_file(path: Path, chunk_size: int = 1 << 20) -> tuple[str, int]  # (hex, size)
def config_hash(config: Mapping[str, Any]) -> str  # sha256 of canonical_json(config)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
```

**Tests first:**
- `test_ids.py`: `test_new_id_has_prefix_and_ulid`, `test_parse_id_roundtrip` (Hypothesis over every `IdPrefix`), `test_parse_id_rejects_lowercase_ulid`, `test_ids_are_unique_over_10k`.
- `test_enums.py`: `test_enum_values_are_frozen`. A literal dict in the test maps each enum class to its exact value list from above; the test asserts equality. This test is the guard against renames.
- `test_errors.py`: `test_exit_codes`, `test_policy_denied_message_contains_only_ids_and_enums`.
- `test_hashing.py`: `test_canonical_json_key_order_independent` (Hypothesis dicts), `test_sha256_file_matches_bytes`, `test_config_hash_stable_known_vector` (assert `config_hash({}) == sha256_bytes(b"{}")`).

**Acceptance:** `uv run pytest tests/unit/domain -q` plus the lint gates.

**Do NOT:** add enum values not listed; use `Enum` instead of `StrEnum`; put any business logic here.

---

### WP3 — Governance policy resolution (ADR-0007)

**Files:** `src/langpipe/governance/__init__.py`, `governance/policy.py`, `governance/guard.py`; tests `tests/unit/governance/__init__.py`, `tests/unit/governance/test_policy_matrix.py`, `test_policy_properties.py`, `test_guard.py`.

WP3 must not depend on WP4a, so it defines a minimal **structural protocol** for policies:
```python
class PolicyLike(Protocol):
    @property
    def mode(self) -> PolicyMode: ...
    @property
    def allow(self) -> tuple[Operation, ...]: ...
    @property
    def deny(self) -> tuple[Operation, ...]: ...

class Baseline(StrEnum): ALLOW="allow"; DEFAULT_DENY="default_deny"; REVIEW="review"; HARD_DENY="hard_deny"
BASELINE: Mapping[PolicyMode, Mapping[Operation, Baseline]]   # exactly the ADR-0007 matrix; every (mode, op) pair present
def baseline(mode: PolicyMode, op: Operation) -> Baseline
def validate_policy_lists(mode: PolicyMode, allow: Iterable[Operation], deny: Iterable[Operation]) -> None  # raises PolicyConflict if any allow op is HARD_DENY for mode
def resolve(policy: PolicyLike, op: Operation) -> PolicyDecision
def resolve_many(policies: Iterable[PolicyLike], op: Operation) -> PolicyDecision   # most restrictive; empty → deny
```
`guard.py`:
```python
def require(policy: PolicyLike, op: Operation, *, source_id: str) -> None  # raises PolicyDenied unless allow
def require_all(policies: Mapping[str, PolicyLike], op: Operation) -> None  # key = source_id; first non-allow raises (iterate keys sorted)
```
Resolution (exact): `if op in deny → DENY; b = baseline(mode, op); if b is HARD_DENY → DENY; if op in allow → ALLOW; ALLOW→ALLOW, DEFAULT_DENY→DENY, REVIEW→REVIEW_REQUIRED`.

**Tests first:**
- `test_policy_matrix.py`:
  - `test_matrix_is_total`: every mode × operation pair is present.
  - `test_matrix_matches_adr_0007`: a literal table in the test is copied from the ADR, row by row.
  - `test_exclude_denies_everything`.
  - `test_distill_only_direct_training_is_hard_denied`.
  - `test_explicit_allow_cannot_lift_hard_deny`: `validate_policy_lists` raises `PolicyConflict`.
  - `test_explicit_allow_lifts_default_deny` (for example `direct` plus `allow third_party_api`).
  - `test_deny_overrides_allow`.
  - `test_outward_ops_never_baseline_allow`.
- `test_policy_properties.py` (Hypothesis):
  - `test_adding_deny_never_increases_permission`.
  - `test_resolve_many_is_monotonic`: adding any policy to the set never moves the result toward `allow`.
  - `test_resolve_many_empty_is_deny`.
- `test_guard.py`:
  - `test_require_raises_policy_denied_with_ids_only`.
  - `test_require_review_required_is_not_allow`.

Use a tiny frozen dataclass `_P(mode, allow, deny)` in the tests as the `PolicyLike`.

**Do NOT:** import from `langpipe.domain.models`; read config files; implement actor or `restrictions` enforcement; add a "force" flag.

---

### WP4a — Source, run and audit boundary models

**Depends:** WP2, WP3.
**Files:** `domain/models/source.py`, `domain/models/run.py`; tests `tests/unit/domain/test_models_source.py`, `test_models_run.py`. (`base.py` already exists from WP2. Do not modify it.)

**base.py (implemented in WP2; reproduced here for reference)**
```python
class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    SCHEMA_NAME: ClassVar[str | None] = None
    SCHEMA_VERSION: ClassVar[int] = 1
    # field_validator on every datetime field via model_validator(mode="after"): tzinfo must be UTC-aware else ValueError
UTC_NOW: Callable[[], datetime]  # lambda: datetime.now(UTC)
LANG_CODE = Annotated[str, StringConstraints(pattern=r"^[a-z]{3}$")]   # ISO 639-3 or "und"/"qaa"
VERSIONED_NAME = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.-]*@[0-9A-Za-z_.-]+$")]  # "name@version"
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
def id_field(prefix: IdPrefix) -> Any  # returns Annotated str with pattern f"^{prefix}_[0-9A-HJKMNP-TV-Z]{{26}}$"
```

**source.py** (field: type; all required unless a default is shown):
- `Provenance`: `acquired_from: str (min 1)`, `rights_holder: str | None = None`, `collector: str | None = None`, `notes: str | None = None`.
- `PolicySpec` (manifest input): `mode: PolicyMode`, `access_class: AccessClass`, `authority: str (min 1)`, `allow: list[Operation] = []`, `deny: list[Operation] = []`, `restrictions: dict[str, JsonValue] = {}`. A validator calls `validate_policy_lists`.
- `ObjectSpec`: `path: str` (relative POSIX; reject absolute paths, `..` segments and backslashes), `media_type: str (pattern r"^[a-z]+/[a-z0-9.+-]+$")`, `access_class: AccessClass | None = None`.
- `SourceManifest` (`SCHEMA_NAME="source-manifest"`): `manifest_version: Literal[1]`, `key: str (pattern r"^[a-z0-9][a-z0-9-]{1,62}$")`, `title: str (min 1)`, `source_type: SourceType`, `languages: list[LANG_CODE] (min 1, unique)`, `provenance: Provenance`, `acquired_at: datetime`, `domains: list[str] = []`, `registers: list[str] = []`, `policy: PolicySpec`, `objects: list[ObjectSpec] = []`.
  - Validators: object `path`s unique. Each `access_class` must be at least as restrictive as `policy.access_class` (`access_rank(obj) >= access_rank(policy)`), otherwise `ValueError`. `objects` must be non-empty unless `policy.mode == exclude`.
  - Method `def manifest_sha256(self) -> str` = `sha256_bytes(canonical_json(self.model_dump(mode="json")).encode())`.
- `SourcePolicy` (`SCHEMA_NAME="source-policy"`): `id: pol_`, `mode`, `access_class`, `authority`, `allow: tuple[Operation, ...]` (sorted, deduplicated by a validator), `deny: tuple[Operation, ...]` (same), `restrictions: dict[str, JsonValue] = {}`, `policy_version: int = 1 (ge 1)`, `created_at`. Validator calls `validate_policy_lists`. It satisfies `PolicyLike`.
- `Source` (`SCHEMA_NAME="source"`): `id: src_`, `key`, `title`, `source_type`, `languages: tuple[LANG_CODE, ...]`, `provenance`, `policy_id: pol_`, `acquired_at`, `status: SourceStatus = registered`, `domains: tuple[str, ...]`, `registers: tuple[str, ...]`, `manifest_sha256: SHA256`, `registration_run_id: run_`, `created_at`, `updated_at`.
- `SourceObject` (`SCHEMA_NAME="source-object"`): `id: sobj_`, `source_id: src_`, `original_path: str`, `origin_uri: str` (`file://` absolute URI), `sha256: SHA256`, `size_bytes: int (ge 0)`, `media_type`, `access_class`, `registration_run_id: run_`, `created_at`.
- `RawBlob` (no schema): `sha256`, `size_bytes`, `storage_backend: Literal["local"]`, `stored_at`, `ingestion_run_id: run_`.

**run.py**
- `ProcessingRun` (`SCHEMA_NAME="processing-run"`): `id: run_`, `stage: RunStage`, `tool_name: str`, `tool_version: str`, `config: dict[str, JsonValue]`, `config_hash: SHA256`, `code_revision: str`, `run_key: SHA256`, `random_seed: int | None = None`, `status: RunStatus`, `started_at`, `finished_at: datetime | None = None`, `error_type: str | None = None`, `error_message: str | None = None`.
  - Validators: `config_hash == config_hash(config)`. If status is `running`, `finished_at`, `error_type` and `error_message` are all None. If `succeeded`, `finished_at` is set and the error fields are None. If `failed`, `finished_at` and `error_type` are set.
  - `@staticmethod def compute_run_key(stage, tool_name, tool_version, config_hash, input_ids: Iterable[str]) -> str` = sha256 of `canonical_json({"stage":…, "tool_name":…, "tool_version":…, "config_hash":…, "inputs": sorted(input_ids)})`.
- `Artifact` (`SCHEMA_NAME="artifact"`): `id: artifact_`, `run_id: run_`, `kind: ArtifactKind`, `media_type`, `sha256`, `size_bytes`, `access_class`, `schema_name: str | None = None`, `schema_version: int | None = None`, `created_at`.
- `AuditEvent` (no schema file): `id: aud_`, `event_type: AuditEventType`, `actor: str`, `subject_id: str | None`, `run_id: str | None`, `details: dict[str, str | int | bool]` (a validator applies `langpipe.logging`-style safety: keys are limited to `mode`, `operation`, `decision`, `objects`; values respectively validate against PolicyMode, Operation, PolicyDecision, nonnegative int. No arbitrary strings, even lowercase single words. Do not import from logging), `occurred_at`.

**Tests first:**
- `test_models_source.py`:
  - `test_source_object_is_frozen` (assignment raises `ValidationError`; **mandatory test 1, part**).
  - `test_manifest_rejects_parent_path`.
  - `test_manifest_rejects_absolute_path`.
  - `test_manifest_object_access_class_cannot_be_more_permissive`.
  - `test_manifest_exclude_may_have_no_objects`.
  - `test_manifest_sha256_stable_under_yaml_key_order`.
  - `test_policy_rejects_allow_of_hard_denied_op`.
  - `test_policy_lists_sorted_and_deduped`.
  - `test_languages_accept_und`.
- `test_models_run.py`:
  - `test_run_key_independent_of_input_order`.
  - `test_run_key_ignores_code_revision`: `compute_run_key` has no revision parameter; assert this by signature inspection.
  - `test_config_hash_must_match_config`.
  - `test_running_run_cannot_have_finished_at`.
  - `test_failed_run_requires_error_type`.
  - `test_audit_details_reject_free_text` (e.g. `"some raw sentence"` → error).

**Do NOT:** add ORM code here; add mutable defaults (`[]`/`{}` must be `Field(default_factory=...)`); add fields not listed.

---

### WP4b — Observation, evidence, lineage models and lifecycle guard

**Depends:** WP2 (which provides `base.py`). Import `from langpipe.domain.models.base import DomainModel, id_field, LANG_CODE, VERSIONED_NAME, UTC_NOW`. **WP4b MUST NOT modify `base.py`.**

**Files:** `domain/models/observation.py`, `domain/models/evidence.py`, `domain/lifecycle.py`; tests `tests/unit/domain/test_models_observation.py`, `test_models_evidence.py`, `test_lifecycle.py`.

**observation.py**
- `Span`: `representation: SpanRepresentation`, `start: int (ge 0)`, `end: int (ge 0)`. Validator: `start <= end`. Method `def slice(self, text: str) -> str: return text[self.start:self.end]`.
- `Segment` (`SCHEMA_NAME="segment"`): `id: seg_`, `source_id: src_`, `source_object_id: sobj_`, `run_id: run_`, `ordinal: int (ge 0)`, `language: LANG_CODE`, `locator: dict[str, str | int]` (structural locator, e.g. `{"ref": "GEN.1.1"}`; may be empty), `raw_text: str`, `normalized_text: str | None = None`, `normalization_profile: VERSIONED_NAME | None = None`, `status: SegmentStatus = ok`, `created_at`.
  - Validators: `normalized_text` and `normalization_profile` are either both None or both set. If status is `normalization_failed`, `normalized_text` is None.
- `TokenOccurrence` (`SCHEMA_NAME="token-occurrence"`): `id: tok_`, `segment_id: seg_`, `run_id: run_`, `ordinal: int (ge 0)`, `raw_surface: str (min 1)`, `normalized_surface: str | None = None`, `raw_span: Span | None = None`, `normalized_span: Span | None = None`, `tokenizer: VERSIONED_NAME`, `form_id: str | None` (form_ pattern), `created_at`.
  - Validators: `raw_span.representation == raw` and `normalized_span.representation == normalized` when present.
  - `def check_against(self, segment: Segment) -> None`: raises `SchemaViolation` if `segment_id != segment.id`, if a span exceeds the corresponding text length, if a normalized span lacks normalized text/surface, or if `raw_span` is present and `raw_span.slice(segment.raw_text) != raw_surface`, or the same check applies to the normalized span against `segment.normalized_text`.
- `Form` (`SCHEMA_NAME="form"`): `id: form_`, `language`, `orthography_profile: VERSIONED_NAME`, `text: str (min 1)`, `run_id: run_`, `created_at`. Validator: `unicodedata.is_normalized("NFC", text)`, otherwise error.

**evidence.py**
- `EvidenceItem` (`SCHEMA_NAME="evidence-item"`): `id: ev_`, `kind: EvidenceKind`, `polarity: EvidencePolarity`, `target_id: str` (any valid ID per `ID_PATTERN`), `claim: dict[str, JsonValue] | None = None`, `source_id: str | None` (src_), `run_id: run_`, `strength: dict[str, float] = {}`, `policy_version: str | None = None`, `independence_group: str | None = None`, `domain: str | None = None`, `register: str | None = None`, `extensions: dict[str, dict[str, JsonValue]] = {}`, `created_at`. Validator: extension keys match `^[a-z0-9_.-]+$`.
- `LineageEdge` (`SCHEMA_NAME="lineage-edge"`): `id: lin_`, `from_id: str`, `to_id: str` (both valid IDs), `kind: LineageKind`, `run_id: run_`, `created_at`. Validator: `from_id != to_id`. Docstring: "`from_id` depends on `to_id` (child → parent). ADR-0009."

**lifecycle.py**
```python
class ValidationBasis(DomainModel):
    kind: ValidationBasisKind; actor: str; review_decision_id: str | None = None; evidence_ids: tuple[str, ...] = ()
ALLOWED: Mapping[LifecycleStatus, frozenset[LifecycleStatus]] = {
  candidate: {supported, rejected, deprecated},
  supported: {validated, rejected, deprecated},
  validated: {deprecated},
  rejected: frozenset(), deprecated: frozenset() }
def check_transition(current: LifecycleStatus, new: LifecycleStatus, basis: ValidationBasis | None = None) -> None
   # raises InvalidTransition if new not in ALLOWED[current]; if new is validated and basis is None → InvalidTransition
```

**Tests first:**
- `test_models_observation.py`:
  - `test_token_span_must_match_segment_raw_text`.
  - `test_span_slice_codepoints` (text containing `"ú"` both precomposed and as a combining sequence; asserts code-point semantics).
  - `test_span_end_exclusive`.
  - `test_form_rejects_non_nfc`.
  - `test_segment_normalized_requires_profile`.
  - `test_normalization_failed_has_no_normalized_text`.
  - Hypothesis `test_span_slice_roundtrip`.
- `test_models_evidence.py`:
  - `test_lineage_rejects_self_edge`.
  - `test_evidence_extensions_namespaced`.
  - `test_evidence_is_frozen`.
- `test_lifecycle.py`:
  - `test_validated_requires_basis`.
  - `test_candidate_cannot_jump_to_validated`.
  - `test_deprecated_is_terminal`.
  - `test_rejected_is_terminal`.
  - `test_no_model_confidence_basis_kind`.

**Do NOT:** add Lexeme/Sense/MorphAnalysis models; add mutable defaults; normalize text inside models (Form only *checks* NFC).

---

### WP5 — Immutable content store (raw and artifacts)

**Depends:** WP2. **Files:** `storage/__init__.py`, `storage/objects/__init__.py`, `storage/objects/base.py`, `storage/objects/local.py`; tests `tests/unit/storage/test_local_content_store.py`.

```python
@dataclass(frozen=True)
class StoredObject: sha256: str; size_bytes: int; uri: str   # uri = "file://<abs path>"
class ContentStore(Protocol):
    def put_bytes(self, data: bytes) -> StoredObject: ...
    def put_file(self, path: Path) -> StoredObject: ...
    def exists(self, sha256: str) -> bool: ...
    def open(self, sha256: str) -> BinaryIO: ...      # opened "rb"; ObjectMissing if absent
    def read_bytes(self, sha256: str) -> bytes: ...
    def verify(self, sha256: str) -> None: ...        # ObjectMissing | HashMismatch
class LocalContentStore:  # implements ContentStore
    def __init__(self, root: Path) -> None   # creates root/"sha256", root/"tmp"
    def path_for(self, sha256: str) -> Path   # root/sha256/h[0:2]/h[2:4]/h
```
Behavior:
- Write to `root/tmp/<uuid4>`, flush, `os.fsync`, then `os.link(tmp, final)`.
- If that raises `FileExistsError`, call `verify(sha)` on the existing file: if it is intact, return the existing object; if it is corrupt, raise `HashMismatch`. Never overwrite.
- Unlink the tmp file afterwards.
- `os.chmod(final, 0o444)`.
- `put_file` streams with `sha256_file`-style chunking into tmp.
- There is **no** delete, overwrite, rename or write API.

**Tests first** (mandatory tests 1 and 6):
- `test_put_is_content_addressed_and_idempotent`: same bytes put twice return the same `StoredObject`, and the file's `st_ino` and `st_mtime_ns` are unchanged.
- `test_stored_file_is_read_only` (mode `0o444`).
- `test_open_returns_read_only_stream`: `.write` raises `io.UnsupportedOperation`.
- `test_store_has_no_mutation_api`: `not hasattr(store, name)` for `delete`, `remove`, `overwrite`, `write`, `put_at`.
- `test_read_bytes_returns_immutable_bytes` (`type(...) is bytes`).
- `test_verify_detects_corruption`: chmod `0o644`, append a byte, then `verify` raises `HashMismatch`. **Mandatory test 6.**
- `test_verify_missing_raises_object_missing`.
- `test_put_over_corrupted_existing_raises_hash_mismatch`.
- `test_put_file_streams_large_file` (5 MiB random bytes).

**Do NOT:** add S3; add a cache; catch broad exceptions.

---

### WP6 — Settings, code revision and safe logging

**Depends:** WP2. **Files:** `config/__init__.py`, `config/settings.py`, `config/revision.py`, `src/langpipe/logging.py`; tests `tests/unit/test_settings.py`, `tests/unit/test_logging.py`.

```python
@dataclass(frozen=True)
class Settings:
    database_url: str     # LANGPIPE_DATABASE_URL, default "postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe"
    data_dir: Path        # LANGPIPE_DATA_DIR, default Path("var")
    actor: str            # LANGPIPE_ACTOR, default getpass.getuser() or "unknown"
    log_level: str        # LANGPIPE_LOG_LEVEL, default "INFO"
    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings"
    @property
    def raw_dir(self) -> Path: return self.data_dir / "raw"
    @property
    def artifact_dir(self) -> Path: return self.data_dir / "artifacts"
def code_revision() -> str   # env LANGPIPE_CODE_REVISION, else `git rev-parse --short=12 HEAD` (subprocess, timeout 2s, no shell), else "unknown"
```
`logging.py`:
```python
LOGGER_NAME = "langpipe"
SAFE_VALUE = re.compile(r"^([a-z]+_[0-9A-HJKMNP-TV-Z]{26}|[0-9a-f]{64})$")
def configure_logging(level: str = "INFO") -> None   # stderr handler, format "%(levelname)s %(name)s %(message)s"; idempotent
def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: str | int | bool | None) -> None
    # event must match ^[a-z][a-z0-9_.]{1,63}$; field keys must be from the fixed event field allowlist; string values must be validated IDs/hashes or members of the exact enum associated with that field, else UnsafeLogValue(ValueError). Arbitrary slugs, filenames and lowercase words are forbidden
    # message: "event=<event> k1=v1 k2=v2" (keys sorted)
```
The string-field allowlist is `source_id`, `source_object_id`, `run_id`, `artifact_id`, `policy_id`, `sha256`, `operation`, `decision`, `mode`, `status` (status must be an exact SourceStatus or RunStatus). Count fields are `objects`, `blobs`, `count` and accept nonnegative ints; `reused` accepts bool. Reject other keys/types. Event names are code constants, never source-derived.

Add `UnsafeLogValue` to `langpipe/logging.py` (not `errors.py`; it is a programming error, not a domain error).

**Tests first:**
- `test_settings.py`: `test_defaults`, `test_env_overrides`.
- `test_logging.py`:
  - `test_log_event_formats_sorted_fields` (caplog).
  - `test_log_event_rejects_free_text` (`"o homem vê"` raises).
  - `test_log_event_rejects_uppercase_sentinel`
- `test_log_event_rejects_lowercase_word_filename_and_unknown_key`.
  - `test_log_event_accepts_ids_and_hashes`.
  - `test_configure_logging_idempotent`.

**Do NOT:** log through `print`; add structlog or another dependency; read `.env` files.

---

### WP7 — Repository protocol and in-memory implementation

**Depends:** WP4a, WP4b. **Files:** `storage/repository.py`, `storage/memory.py`, `tests/fixtures/backends.py` (fill in), `tests/contract/__init__.py`, `tests/contract/test_repository_contract.py`.

**Protocol (exact):**
```python
class Repository(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...   # nesting not supported: RuntimeError
    # every add_*/set_*/finish_* MUST be called inside transaction(); else RuntimeError("write outside transaction")
    def add_policy(self, p: SourcePolicy) -> None: ...
    def get_policy(self, policy_id: str) -> SourcePolicy: ...                 # NotFound
    def add_source(self, s: Source) -> None: ...                               # registers EntityType.source
    def get_source(self, source_id: str) -> Source: ...
    def find_source_by_key(self, key: str) -> Source | None: ...
    def set_source_status(self, source_id: str, status: SourceStatus, at: datetime) -> Source: ...
    def add_source_object(self, o: SourceObject) -> None: ...                  # unique (source_id, original_path) else SourceConflict
    def get_source_object(self, object_id: str) -> SourceObject: ...
    def list_source_objects(self, source_id: str) -> list[SourceObject]: ...   # ordered by original_path
    def add_raw_blob(self, b: RawBlob) -> RawBlob: ...                         # idempotent: returns existing row if sha256 exists
    def get_raw_blob(self, sha256: str) -> RawBlob | None: ...
    def add_run(self, r: ProcessingRun) -> None: ...
    def finish_run(self, run_id: str, status: RunStatus, finished_at: datetime,
                   error_type: str | None = None, error_message: str | None = None) -> ProcessingRun: ...
                   # ImmutableViolation if run not running or status == running
    def get_run(self, run_id: str) -> ProcessingRun: ...
    def find_succeeded_run(self, run_key: str) -> ProcessingRun | None: ...
    def add_run_io(self, run_id: str, object_id: str, role: RunIoRole) -> None: ...   # object must exist in registry else InvalidLineage; duplicate ignored
    def list_run_io(self, run_id: str) -> list[tuple[str, RunIoRole]]: ...            # sorted
    def add_artifact(self, a: Artifact) -> None: ...
    def get_artifact(self, artifact_id: str) -> Artifact: ...
    def add_segment(self, s: Segment) -> None: ...                 # unique (run_id, source_object_id, ordinal)
    def get_segment(self, segment_id: str) -> Segment: ...
    def list_segments(self, source_object_id: str) -> list[Segment]: ...
    def add_token(self, t: TokenOccurrence) -> None: ...           # unique (run_id, segment_id, ordinal)
    def get_token(self, token_id: str) -> TokenOccurrence: ...
    def list_tokens(self, segment_id: str) -> list[TokenOccurrence]: ...
    def get_or_create_form(self, f: Form) -> Form: ...             # natural key (language, orthography_profile, text)
    def add_evidence(self, e: EvidenceItem) -> None: ...           # target_id must exist in registry else InvalidLineage
    def get_evidence(self, evidence_id: str) -> EvidenceItem: ...
    def list_evidence_for_target(self, target_id: str) -> list[EvidenceItem]: ...
    def add_lineage_edge(self, e: LineageEdge) -> LineageEdge: ...  # endpoints must exist; idempotent on (from,to,kind) → returns existing; cycle → InvalidLineage
    def list_lineage_edges(self, object_id: str, direction: Literal["out", "in"]) -> list[LineageEdge]: ...
    def ancestors(self, object_id: str) -> list[tuple[str, int]]: ...    # (id, min depth ≥1), sorted (depth, id)
    def descendants(self, object_id: str) -> list[tuple[str, int]]: ...  # reverse edges, same format
    def entity_type_of(self, object_id: str) -> EntityType | None: ...
    def add_audit_event(self, e: AuditEvent) -> None: ...
    def list_audit_events(self) -> list[AuditEvent]: ...                 # ordered by occurred_at, id
    def count(self, entity_type: EntityType) -> int: ...
    def count_lineage_edges(self) -> int: ...
    def count_raw_blobs(self) -> int: ...
    def count_runs(self, status: RunStatus | None = None) -> int: ...
```
Every `add_*` for an entity in `EntityType` also inserts the object-registry entry. `add_run` registers `processing_run`. Cycle rule: reject if `e.from_id == e.to_id` or `e.from_id` is in `{to_id} ∪ ancestors(to_id)`.

**There is no update or delete method for anything except `set_source_status` and `finish_run`.**

**InMemoryRepository:** plain dicts. `transaction()` deep-copies the state on entry and restores it on exception. All stored inputs and returned models, including nested containers, are deep copies.

**tests/fixtures/backends.py:**
```python
BACKENDS = ["memory", pytest.param("postgres", marks=pytest.mark.integration)]
@pytest.fixture(params=BACKENDS)
def repo(request) -> Iterator[Repository]
    # "memory" → InMemoryRepository(); "postgres" → request.getfixturevalue("pg_repository") (fixture provided by WP9 in tests/fixtures/db.py)
```
Until WP9 lands, the postgres param uses `pytest.skip("PostgresRepository not implemented (WP9)")` when `pg_repository` is missing. Detect this with `request.getfixturevalue` inside `try/except pytest.FixtureLookupError`.

**Tests first** (`tests/contract/test_repository_contract.py`, all using `repo`):
- `test_write_outside_transaction_raises`
- `test_transaction_rollback_discards_all_writes`
- `test_nested_model_mutation_does_not_change_repository_state` (mutate input and returned config/locator/provenance maps; fresh reads remain unchanged)
- `test_registry_tracks_entity_types`
- `test_source_object_unique_path`
- `test_raw_blob_add_is_idempotent`
- `test_finish_run_only_once`
- `test_find_succeeded_run_ignores_failed`
- `test_get_or_create_form_returns_existing`
- `test_lineage_requires_existing_endpoints`
- `test_lineage_rejects_cycle`
- `test_lineage_edge_idempotent`
- `test_descendants_transitive_with_min_depth` (chain a←b←c plus a←c gives c at depth 1)
- `test_repository_has_no_observation_mutators`: asserts there are no attributes matching `^(update|delete|remove|set)_(segment|token|source_object|evidence|lineage|form|artifact)`
- **`test_observations_unchanged_when_evidence_changes`** (mandatory test 7):
  1. Create source, policy, source object, a `manual_annotation` run, a segment and two tokens.
  2. Snapshot `model_dump()` of the segment and tokens.
  3. Add a `supports` EvidenceItem on token 1 with a `derived_from` edge to it.
  4. Add a `contradicts` EvidenceItem plus a `supersedes` edge from the new evidence to the old one.
  5. Assert the snapshots are equal to fresh `get_*` results.

Helper builders live in `tests/contract/builders.py` (create this file in this WP): `make_policy()`, `make_source(policy)`, `make_source_object(source)`, `make_run(stage=...)`, `make_segment(...)`, `make_token(...)`, all using fixed UTC datetimes.

**Do NOT:** add SQLAlchemy here; share mutable state between `InMemoryRepository` instances; return mutable containers that alias internal state.

---

### WP8 — Database schema: ORM tables and the Alembic migration (ADR-0009)

**Depends:** WP2 (enum values). It is parallel with WP4a and WP4b because the column spec is fully given here.
**Files:** `storage/db/__init__.py`, `storage/db/tables.py`, `storage/db/engine.py`, `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0001_m1_evidence_substrate.py`; extend `tests/fixtures/db.py`; tests `tests/integration/test_migrations.py`, `tests/integration/test_append_only_triggers.py`, `tests/unit/storage/test_migration_enum_literals.py`.

**Conventions:**
- IDs are `text` primary keys with `CHECK (id ~ '^<prefix>_[0-9A-HJKMNP-TV-Z]{26}$')`.
- Timestamps are `timestamptz NOT NULL`.
- Enums are `text` with `CHECK (col IN (...))`. In the migration, write each value list as **literal module-level tuples** (`_POLICY_MODES = (...)`, and so on); never import app enums.
- JSON columns are `jsonb NOT NULL DEFAULT '{}'`.
- Arrays are `text[] NOT NULL DEFAULT '{}'`.
- ORM `tables.py` uses SQLAlchemy 2 `DeclarativeBase` and `Mapped[...]`, with column types matching. CHECK constraints may live only in the migration. Mirror column nullability, server defaults, UNIQUE constraints and all indexes (including ux_run_key_succeeded) in ORM metadata so compare_metadata can return []. Nullable columns override the generic NOT NULL rules; unspecified text columns are text, size columns bigint, ordinal/offset/version columns int; unspecified FKs target the named entity id with default NO ACTION. All size/ordinal columns are nonnegative. Add run-state CHECKs matching the ProcessingRun validator, so raw SQL cannot finish a run without a timestamp or required error_type.

**Tables (exact names/columns):**
1. `object_registry(id text PK, entity_type text CHECK in EntityType, created_at)`
2. `source_policy(id PK pol_, mode, access_class, authority text, allow text[], deny text[], restrictions jsonb, policy_version int CHECK >=1, created_at)`
3. `processing_run(id PK run_ FK→object_registry.id, stage, tool_name, tool_version, config jsonb, config_hash char(64), code_revision text, run_key char(64), random_seed bigint NULL, status, started_at, finished_at NULL, error_type NULL, error_message NULL)`. Partial unique index `ux_run_key_succeeded ON processing_run(run_key) WHERE status='succeeded'`. Index on `run_key`.
4. `source(id PK src_ FK→object_registry, key text UNIQUE, title, source_type, languages text[], provenance jsonb, policy_id FK→source_policy, acquired_at, status, domains text[], registers text[], manifest_sha256 char(64), registration_run_id FK→processing_run, created_at, updated_at)`
5. `source_object(id PK sobj_ FK→object_registry, source_id FK→source, original_path, origin_uri, sha256 char(64), size_bytes bigint CHECK>=0, media_type, access_class, registration_run_id FK→processing_run, created_at, UNIQUE(source_id, original_path))`; index on `sha256`.
6. `raw_blob(sha256 char(64) PK, size_bytes bigint, storage_backend text CHECK in ('local'), stored_at, ingestion_run_id FK→processing_run)`
7. `processing_run_io(run_id FK→processing_run, object_id FK→object_registry, role CHECK in ('input','output'), PK(run_id, object_id, role))`
8. `artifact(id PK artifact_ FK→object_registry, run_id FK, kind, media_type, sha256 char(64), size_bytes, access_class, schema_name NULL, schema_version int NULL, created_at)`
9. `segment(id PK seg_ FK→object_registry, source_id FK, source_object_id FK, run_id FK, ordinal int CHECK>=0, language char(3), locator jsonb, raw_text text, normalized_text NULL, normalization_profile NULL, status, created_at, UNIQUE(run_id, source_object_id, ordinal), CHECK((normalized_text IS NULL) = (normalization_profile IS NULL)))`
10. `form(id PK form_ FK→object_registry, language char(3), orthography_profile, text, run_id FK, created_at, UNIQUE(language, orthography_profile, text))`
11. `token_occurrence(id PK tok_ FK→object_registry, segment_id FK, run_id FK, ordinal, raw_surface, normalized_surface NULL, raw_start int NULL, raw_end int NULL, norm_start NULL, norm_end NULL, tokenizer, form_id FK→form NULL, created_at, UNIQUE(run_id, segment_id, ordinal), CHECK((raw_start IS NULL) = (raw_end IS NULL)), CHECK(raw_start IS NULL OR (raw_start>=0 AND raw_end>=raw_start)), CHECK((norm_start IS NULL) = (norm_end IS NULL)), CHECK(norm_start IS NULL OR (norm_start>=0 AND norm_end>=norm_start)))`
12. `evidence_item(id PK ev_ FK→object_registry, kind, polarity, target_id FK→object_registry, claim jsonb NULL, source_id FK→source NULL, run_id FK, strength jsonb, policy_version NULL, independence_group NULL, domain NULL, register NULL, extensions jsonb, created_at)`; index on `target_id`.
13. `lineage_edge(id PK lin_, from_id FK→object_registry, to_id FK→object_registry, kind, run_id FK, created_at, UNIQUE(from_id, to_id, kind), CHECK(from_id <> to_id))`; indexes on `from_id` and `to_id`.
14. `audit_event(id PK aud_, event_type, actor, subject_id text NULL (no FK), run_id text NULL (no FK), details jsonb, occurred_at)`

**Triggers (in the migration, plain SQL via `op.execute`):**
- `langpipe_forbid_mutation()`: `RAISE EXCEPTION 'append-only table: %', TG_TABLE_NAME USING ERRCODE = 'restrict_violation'`. Attach it `BEFORE UPDATE OR DELETE FOR EACH ROW` to `object_registry, source_policy, source_object, raw_blob, processing_run_io, artifact, segment, form, token_occurrence, evidence_item, lineage_edge, audit_event`.
- `langpipe_source_guard()`: on DELETE, raise. On UPDATE, raise if any column other than `status`/`updated_at` differs (compare `NEW` and `OLD` with `status` and `updated_at` blanked, using `jsonb` of the row minus those keys).
- `langpipe_run_guard()`: on DELETE, raise. On UPDATE, raise if `OLD.status <> 'running'`, or `NEW.status = 'running'`, or any column other than `status, finished_at, error_type, error_message` differs.
- `downgrade()` drops the triggers, the functions and all tables in reverse order.

**engine.py:** `def make_engine(url: str) -> Engine` (`future`, `pool_pre_ping=True`).
**alembic.ini / env.py:** `script_location = migrations`. The URL comes from `config.attributes["url"]`, else `-x url=...`, else `LANGPIPE_DATABASE_URL`, else the Settings default. `target_metadata = langpipe.storage.db.tables.Base.metadata`.

**tests/fixtures/db.py additions:**
- `migrated_engine` (session): depends on `pg_url`. Runs alembic `downgrade base` and then `upgrade head` programmatically (`alembic.config.Config("alembic.ini")` with `attributes["url"]`; `env.py` resolves that attribute before `-x url`, environment and default). Yields the engine.
- `clean_db` (function): `TRUNCATE <all tables> RESTART IDENTITY CASCADE` before each test.

**Tests first:**
- `tests/unit/storage/test_migration_enum_literals.py::test_migration_literals_match_enums`: load the migration module with `importlib.util.spec_from_file_location` and compare each literal tuple to its enum's values. This needs no DB.
- `tests/integration/test_migrations.py`:
  - `test_upgrade_downgrade_upgrade`: after downgrade, no `langpipe` tables remain in `information_schema.tables` for schema `public` except `alembic_version`.
  - `test_metadata_matches_migration`: `alembic.autogenerate.compare_metadata` returns `[]` (ignore CHECK constraints).
- `tests/integration/test_append_only_triggers.py` (insert minimal rows with raw SQL):
  - `test_source_object_update_rejected` (mandatory 1)
  - `test_raw_blob_update_rejected`
  - `test_token_occurrence_update_rejected` (mandatory 7)
  - `test_segment_delete_rejected`
  - `test_lineage_edge_update_rejected`
  - `test_source_title_update_rejected`
  - `test_source_status_update_allowed`
  - `test_finished_run_update_rejected`
  - `test_running_run_can_finish_once`
  - `test_half_specified_token_offsets_rejected`
  - `test_terminal_run_requires_finished_at_and_valid_error_fields`

**Do NOT:** call `Base.metadata.create_all` anywhere (schemas are created only by the migration, including in tests); use native PG enum types; add tables not listed; import `langpipe.domain.enums` inside the migration.

---

### WP9 — PostgreSQL repository

**Depends:** WP7, WP8. **Files:** `storage/db/repository.py`; modify `tests/fixtures/db.py` (add `pg_repository`); tests `tests/integration/test_pg_repository_specific.py`.

- `class PostgresRepository(Repository)`, constructed with `__init__(self, engine: Engine)`. `transaction()` opens a `Session(engine)` with `session.begin()`, stores it on `self._session`, and clears it on exit. Writes outside a transaction raise `RuntimeError` (same as memory). Reads outside a transaction use a short-lived session.
- Map rows to and from domain models explicitly with `_to_<entity>()` / `_from_<entity>()` helpers. Do not store Pydantic JSON blobs in place of columns.
- Natural-key conflicts: catch `sqlalchemy.exc.IntegrityError` on the specific unique constraint and translate it (`SourceConflict` for source key and object path; for idempotent methods, re-select and return the existing row). Use `INSERT ... ON CONFLICT DO NOTHING RETURNING` for `add_raw_blob`, `get_or_create_form`, `add_lineage_edge` and `add_run_io`.
- Translate trigger violations (`restrict_violation` SQLSTATE 23001) into `ImmutableViolation`.
- `descendants`/`ancestors`: one `WITH RECURSIVE` query returning `(id, min(depth))` grouped by id, ordered `(depth, id)`. The cycle check runs `ancestors(to_id)` inside the same transaction.
- `pg_repository` fixture: depends on `migrated_engine` and `clean_db`, returns `PostgresRepository(migrated_engine)`.

**Tests first:** with WP9 merged, the whole `tests/contract` suite runs for `postgres` (the backend fixture param now resolves). Additional tests:
- `test_pg_descendants_uses_single_query` (count statements with an SQLAlchemy event listener; at most 1 for `descendants`).
- `test_pg_trigger_violation_maps_to_immutable_violation`.

**Acceptance:** `docker compose up -d db && uv run pytest tests/contract tests/integration -q`. All tests must pass with **zero skips** when the DB is up.

**Do NOT:** call `session.commit()` outside `transaction()`; use the ORM `relationship()` lazy loading in hot paths; swallow `IntegrityError` generically.

---

### WP10 — Application context, run recorder, registration, ingestion, verification

**Depends:** WP5, WP6, WP7, WP9 (`build_context` imports the PostgreSQL implementation; WP3/WP4a are transitive). **Files:** `src/langpipe/app_context.py`, `ingestion/__init__.py`, `ingestion/runs.py`, `ingestion/registration.py`, `ingestion/ingest.py`, `ingestion/verify.py`; modify `tests/fixtures/backends.py` (add `ctx` fixture); tests `tests/service/test_registration.py`, `tests/service/test_ingest.py`, `tests/service/test_verify.py`, `tests/service/test_log_redaction.py`, `tests/service/manifests.py` (helper that writes tmp manifests and files).

**app_context.py**
```python
@dataclass(frozen=True)
class AppContext:
    repo: Repository; raw_store: ContentStore; artifact_store: ContentStore
    clock: Callable[[], datetime]; new_id: IdFactory; actor: str; code_revision: str
def build_context(settings: Settings) -> AppContext   # PostgresRepository(make_engine(settings.database_url)), LocalContentStore(settings.raw_dir), LocalContentStore(settings.artifact_dir)
```
`ctx` fixture: `AppContext(repo=repo, raw_store=LocalContentStore(tmp_path/"raw"), artifact_store=LocalContentStore(tmp_path/"artifacts"), clock=<fixed-step UTC clock starting 2026-01-01T00:00:00Z, +1s per call>, new_id=new_id, actor="test-actor", code_revision="test-rev")`.

**runs.py**
```python
TOOL_VERSION = langpipe.__version__
@dataclass(frozen=True)
class RunOutcome: run: ProcessingRun; reused: bool
class RunRecorder:
    def __init__(self, ctx: AppContext) -> None
    def find_reusable(self, stage: RunStage, tool_name: str, config: Mapping[str, JsonValue], input_ids: Iterable[str]) -> ProcessingRun | None
    def start(self, stage: RunStage, tool_name: str, config: Mapping[str, JsonValue], input_ids: Iterable[str]) -> ProcessingRun
        # NOTE: committed in its own transaction; status running
    def succeed(self, run_id: str) -> ProcessingRun      # call INSIDE the caller's semantic transaction
    def fail(self, run_id: str, error: BaseException) -> ProcessingRun
        # own transaction; error_type = type(error).__name__; error_message = None; persist no arbitrary exception strings, including domain exceptions
```

**registration.py (Stage 0)**
```python
@dataclass(frozen=True)
class RegistrationResult: source: Source; policy: SourcePolicy; objects: tuple[SourceObject, ...]; run: ProcessingRun; reused: bool
def load_manifest(path: Path) -> SourceManifest      # yaml.safe_load → SourceManifest.model_validate; YAML/Unicode/I/O/Pydantic errors → SchemaViolation with a fixed code only; never render input, paths, error `ctx`/`msg` or exception strings
def register_source(ctx: AppContext, manifest_path: Path) -> RegistrationResult
```
Algorithm:
1. `m = load_manifest(path)`, then `msha = m.manifest_sha256()`.
2. If `existing = repo.find_source_by_key(m.key)` exists: if `existing.manifest_sha256 == msha`, return the existing source, policy, objects and registration run with `reused=True`; otherwise raise `SourceConflict(m.key)`.
3. If `m.policy.mode != exclude`: for each object spec, resolve `path = (manifest_dir / spec.path).resolve()`, which must stay inside `manifest_dir` (else `SchemaViolation`). Compute `sha256_file`. Missing file → `SchemaViolation`. For `exclude`, compute nothing. This is preflight: missing/escaping paths or hash-read errors create no run. Before hashing, require `Operation.ingest == allow`; deny performs no byte read and creates no source/object/run. The `exclude` metadata-only registration exception reads no bytes.
4. `run = RunRecorder.start(source_registration, "langpipe.register", config={"manifest_sha256": msha}, input_ids=[])`.
5. In one `repo.transaction()`, add:
   - the policy;
   - the source (`status=registered`);
   - the source objects (`access_class = spec.access_class or policy.access_class`, `origin_uri = path.as_uri()`);
   - a lineage edge `sobj --imported_from--> src` for each object (run = registration run);
   - run I/O outputs: the source and every object;
   - audit events `policy_created` (subject = policy id) and `source_registered` (subject = source id, details `{"mode": ..., "objects": n}`);
   - `RunRecorder.succeed(run.id)`.
6. On any exception in step 5: the transaction rolls back, then `RunRecorder.fail(run.id, e)`, then re-raise.
7. Log `log_event(..., "source.registered", source_id=..., run_id=..., objects=n)`.

**ingest.py (Stage 1)**
```python
@dataclass(frozen=True)
class IngestResult: source: Source; run: ProcessingRun; blobs: tuple[RawBlob, ...]; report: Artifact | None; reused: bool
def ingest_source(ctx: AppContext, source_ref: str) -> IngestResult   # source_ref = source id or key
```
Algorithm:
1. Resolve the source (`NotFound` if absent) and its policy.
2. **Policy gate first.** If `resolve(policy, Operation.ingest) != allow`: add audit event `policy_denied` (details `{"operation": "ingest", "decision": ...}`) in its own transaction, log `policy.denied`, and raise `PolicyDenied`. **No run row, no store write, no other rows.**
3. `objects = list_source_objects`, `input_ids = [o.id for o in objects]`. If `find_reusable(raw_ingestion, "langpipe.ingest", {}, input_ids)` returns a run, return the result with `reused=True` and no writes (load blobs by object sha256; the report is the run's output artifact).
4. `run = start(...)`.
5. For each object, outside the transaction: open `origin_uri`'s path, then `stored = raw_store.put_file(path)`. If `stored.sha256 != obj.sha256`, raise `SourceChanged(obj.sha256, stored.sha256)` (the stored blob is an orphan; that is accepted). Then `raw_store.verify(stored.sha256)`.
6. Build the ingest report JSON bytes:
   `canonical_json({"schema":"ingest-report","schema_version":1,"source_id":…,"run_id":…,"objects":[{"source_object_id":…,"sha256":…,"size_bytes":…}…]})`
   It contains **IDs, hashes and sizes only**. Store it with `artifact_store.put_bytes`. `access_class = most_restrictive(obj.access_class for obj in objects)`.
7. In one transaction, add:
   - one `raw_blob` per object (idempotent);
   - the artifact (`kind=ingest_report`, `media_type="application/json"`, `schema_name="ingest-report"`, `schema_version=1`);
   - run I/O: each object as input, the artifact as output;
   - a lineage edge `artifact --derived_from--> sobj` for each object;
   - `set_source_status(ingested)`;
   - audit event `raw_ingested`;
   - `succeed(run)`.
8. Wrap all of steps 5–7 in the failure handler: read/store/hash/report failures and semantic transaction failures finish the committed run as failed in a separate transaction, then re-raise. No semantic output rows survive; orphan bytes are allowed.

**verify.py**
```python
@dataclass(frozen=True)
class ObjectCheck: source_object_id: str; sha256: str; status: Literal["ok", "missing", "mismatch", "not_ingested"]
def verify_source(ctx: AppContext, source_ref: str) -> list[ObjectCheck]  # never raises for per-object store problems; ordered by original_path
    # resolve id/key as ingest does; no raw_blob row → not_ingested; blob row but absent file → missing; HashMismatch → mismatch; verified file → ok; unknown source → NotFound. Read authorization remains an open disagreement below.
```

**Tests first** (all use the `ctx` fixture, so each runs on memory and, as integration, on postgres):
- `test_registration.py`:
  - `test_register_creates_source_policy_objects_run_and_edges`
  - `test_register_same_manifest_twice_is_noop` (row counts unchanged; `reused=True`)
  - `test_register_changed_manifest_same_key_raises_source_conflict`
  - `test_register_missing_file_rolls_back_atomically` (counts of source/policy/object/run are 0; missing files fail in preflight)
  - `test_register_rejects_path_escaping_manifest_dir`
  - `test_register_exclude_records_source_without_objects` (no file reads: point the object path at a nonexistent file and assert success)
- `test_ingest.py`:
  - **`test_exclude_policy_denies_before_any_work`** (mandatory 2): spy on origin reads and both stores (`put_file`, `put_bytes`, `open`, `verify`) and assert zero calls; after `PolicyDenied`, `count_runs()` is unchanged from after registration, `raw_store` root has no files under `sha256/`, `count_raw_blobs()==0`, and exactly one new audit event with type `policy_denied`.
  - `test_archive_only_allows_ingest`
  - **`test_ingest_creates_complete_source_run_lineage_records`** (mandatory 3). Asserts: source status `ingested`; 2 succeeded runs (registration and ingestion) with correct stages, tool names, `config_hash`, `code_revision="test-rev"` and `run_key`; ingestion run I/O equals objects in plus artifact out; one raw blob per distinct sha256; edges `sobj→src imported_from` and `artifact→sobj derived_from`; `descendants(src)` contains every object and the artifact; the report artifact bytes parse and contain no `raw_text`; audit events, in order, are `policy_created, source_registered, raw_ingested`.
  - **`test_rerun_identical_registration_and_ingestion_is_idempotent`** (mandatory 4): run register plus ingest twice; every `count(...)`, `count_lineage_edges`, `count_raw_blobs` and `count_runs` is equal after the first and second pass, and the second results have `reused=True`.
  - `test_two_objects_with_identical_bytes_share_one_blob_but_keep_two_source_objects`
  - **`test_source_changed_after_registration_fails_run`** (mandatory 6, part): modify the origin file after registration; ingest raises `SourceChanged`; a failed run is recorded; no raw_blob rows; source still `registered`.
- `test_verify.py`:
  - **`test_verify_source_reports_corrupted_object`** (mandatory 6): ingest, corrupt the stored file (chmod and append), then `verify_source` returns `mismatch` for that object and `ok` for the others.
  - `test_verify_not_ingested`
- `test_log_redaction.py`:
  - **`test_restricted_raw_content_absent_from_default_logs`** (mandatory 5):
    1. Write a source file containing the sentinel `"SENTINEL-RESTRICTED-7f3a9c"` with `policy.access_class=restricted` and a title and filename that contain `"SENTINEL-TITLE-55"`.
    2. Using `caplog.at_level(logging.DEBUG, logger="langpipe")` plus `capsys`, run register, ingest and verify successfully. For the failing ingest, register a second source and corrupt its origin BEFORE its first ingest; assert `SourceChanged` and a failed run. Reusing a succeeded run bypasses origin reads. Repeat with lowercase single-word content, filename-like sentinels, malformed YAML and custom validator failures.
    3. Assert no sentinel appears in `caplog.text`, captured stdout/stderr, any `error_message` of runs, or any audit event details.

**Do NOT:**
- extract segments from files (that is M2);
- read the origin file in registration for `exclude`;
- write to the store or create a run before the policy gate;
- put text, titles or file names in `error_message`, logs or the report;
- catch exceptions without re-raising.

---

### WP10b — Observation recorder and evidence service (M1 foundation, no extraction logic)

**Depends:** WP6, WP7, WP10. Service tests use the `ctx` fixture owned by WP10.
**Files:** `segmentation/__init__.py`, `segmentation/recorder.py`, `lineage/__init__.py`, `lineage/evidence.py`, `lineage/impact.py`; tests `tests/service/test_observation_recorder.py`, `tests/service/test_evidence_service.py`.

These services take a `Repository` plus the explicit `clock`/`new_id`. They do **not** take `AppContext`, which keeps them independent of WP10's file.

```python
# segmentation/recorder.py
@dataclass(frozen=True)
class SegmentInput: ordinal: int; language: str; locator: dict[str, str | int]; raw_text: str
@dataclass(frozen=True)
class TokenInput: ordinal: int; raw_surface: str; raw_start: int | None; raw_end: int | None; form_text: str | None  # form_text NFC; None → no form
class ObservationRecorder:
    def __init__(self, repo: Repository, clock: Callable[[], datetime], new_id: IdFactory) -> None
    def record_segments(self, *, run_id: str, source_object_id: str, segments: Sequence[SegmentInput]) -> list[Segment]
        # policy gate: resolve(policy_of(source_object), Operation.extract) must be allow else PolicyDenied (no rows)
        # one transaction; lineage edge seg --extracted_from--> sobj; run io input sobj / output seg
    def record_tokens(self, *, run_id: str, segment_id: str, tokenizer: str, orthography_profile: str, tokens: Sequence[TokenInput]) -> list[TokenOccurrence]
        # policy gate Operation.normalize; checks spans via TokenOccurrence.check_against(segment); get_or_create_form per form_text;
        # lineage tok --derived_from--> seg; one transaction
```
```python
# lineage/evidence.py
class EvidenceService:
    def __init__(self, repo: Repository, clock: Callable[[], datetime], new_id: IdFactory) -> None
    def add_evidence(self, *, run_id: str, kind: EvidenceKind, polarity: EvidencePolarity, target_id: str,
                     derived_from: Sequence[str], source_id: str | None = None, claim: dict[str, JsonValue] | None = None,
                     strength: dict[str, float] | None = None, independence_group: str | None = None) -> EvidenceItem
        # derived_from must be non-empty (InvalidLineage); one transaction: evidence + edges ev --derived_from--> each id
    def supersede_evidence(self, *, run_id: str, old_id: str, kind: EvidenceKind, polarity: EvidencePolarity,
                           target_id: str, derived_from: Sequence[str], source_id: str | None = None,
                           claim: dict[str, JsonValue] | None = None, strength: dict[str, float] | None = None,
                           independence_group: str | None = None) -> EvidenceItem
        # adds new evidence + edge new --supersedes--> old; old row untouched
# lineage/impact.py
@dataclass(frozen=True)
class ImpactEntry: object_id: str; entity_type: EntityType; depth: int
def impact_of(repo: Repository, object_id: str) -> list[ImpactEntry]   # descendants with types, sorted (depth, object_id)
```

**Recorder details (no extraction implementation):**
- Resolve policy via SourceObject → Source → SourcePolicy (tokens via Segment.source_id). Require a running run with stage `extraction` for segments, `tokenization` for tokens. Caller owns run start/finish; each recorder performs one semantic transaction. Reject duplicate ordinals atomically.
- Segments are raw-only with no normalization fields. Tokens are raw-only, offsets must both be present or both absent; `form_text` is supplied NFC orthographic text, never generated here. Derive Form language from Segment; tokenizer and orthography_profile are VERSIONED_NAME values.
- Add token run I/O: Segment input, all tokens and Forms outputs. Add `form --derived_from--> seg` for each attestation (including reused Forms), and `tok --derived_from--> seg`. A reused Form retains its creating run. Test impact from two sources reaches their shared Form from both.
- Evidence adds derivation inputs/new evidence output to run I/O. Require nonempty governed source ancestry and policy before writes. M1 service production is `manual_annotation` evidence from a running `manual_annotation` run with `human_review` permission for all ancestor sources; other kinds remain model/repository vocabulary for later producers. Denied evidence creates no semantic rows.
- Supersession checks old evidence exists and has the same target, then inserts new evidence/edges in one transaction using a private insertion helper; do not call public `add_evidence` inside another transaction.

**Tests first:**
- `test_observation_recorder.py`:
  - **`test_extract_denied_for_archive_only_creates_nothing`** (mandatory 2, second instance)
  - `test_record_segments_creates_edges_and_run_io`
  - `test_record_tokens_rejects_span_mismatch_atomically`
  - `test_shared_form_retains_lineage_to_each_source`
- `test_same_form_text_reuses_form` ("same surface in multiple occurrences")
  - `test_orthographic_variant_creates_distinct_forms` (`"kanu"` vs `"kanú"` → two Forms; nothing merges them)
- `test_evidence_service.py`:
  - `test_evidence_requires_derivation`
- `test_evidence_denied_ancestor_creates_no_rows`
- `test_supersede_is_atomic_without_nested_transactions`
  - **`test_superseding_evidence_leaves_tokens_unchanged`** (mandatory 7, service level)
  - `test_impact_of_source_reaches_tokens_and_evidence` (source → sobj → seg → tok → ev)

**Do NOT:** implement a tokenizer or splitter; touch language profiles; use `AppContext`; add a CLI.

---

### WP11 — CLI

**Depends:** WP10, WP10b, WP12. **Files:** `cli/__init__.py`, `cli/app.py`, `cli/context.py`, `cli/source.py`, `cli/lineage.py`, `cli/schemas.py`; tests `tests/unit/cli/__init__.py`, `tests/unit/cli/test_cli_source.py`, `tests/unit/cli/test_cli_schemas.py`, `tests/integration/test_cli_postgres.py`.

- `cli/context.py`: a module-level `_factory: Callable[[], AppContext] | None`; `set_context_factory(f)`, `reset_context_factory()`, `get_context()` (default: `build_context(Settings.from_env())`).
- `cli/app.py`: `app = typer.Typer(no_args_is_help=True)`. Sub-apps `source`, `lineage` and `schemas`. A callback option `--log-level` calls `configure_logging`. Set `pretty_exceptions_enable=False` to prevent local-variable dumps; input errors use fixed safe diagnostics. Test the console entry point as well as CliRunner. `main()` runs `app()` and maps any `LangpipeError` to `typer.Exit(code=e.exit_code)`, printing `error=<ClassName>` plus validated IDs to stderr. Apply a shared error wrapper to each command so `CliRunner.invoke(app, ...)` and the console entry point behave identically; a catch only around `main()` cannot cover CliRunner. Never echo arbitrary keys, source refs, parser input or exception strings.
- Commands and their **stdout** (key=value lines except the explicit JSON `source show` command):
  - `langpipe source add MANIFEST_PATH` → `source_id=… key=… objects=N run_id=… reused=true|false`
  - `langpipe source ingest SOURCE_REF` → `source_id=… run_id=… blobs=N report_id=… reused=…`
  - `langpipe source verify SOURCE_REF` → one line per object, `source_object_id=… sha256=… status=…`. Exit 5 if any status is not `ok`.
  - `langpipe source show SOURCE_REF` → JSON: `{"source": Source.model_dump(mode="json"), "policy": …, "objects": [...]}`. This is metadata, so the title is allowed **here only**; no raw bytes.
  - `langpipe lineage descendants OBJECT_ID` → `depth=… object_id=… entity_type=…` lines.
  - `langpipe schemas generate [--dir schemas]` / `langpipe schemas check [--dir schemas]` (exit 1 on drift; prints the drifted file names).

**Tests first** (CliRunner with an in-memory `AppContext` via `set_context_factory`; reset in teardown):
- `test_cli_source.py`:
  - `test_add_ingest_verify_happy_path`
  - `test_add_twice_reports_reused`
  - `test_ingest_exclude_exits_3`
  - `test_invalid_manifest_exits_4_without_echoing_values`
  - `test_cli_output_never_contains_raw_content` (mandatory 5, CLI variant, with the same sentinel approach)
  - `test_verify_corrupted_exits_5`
- `test_cli_schemas.py`:
  - `test_schemas_check_passes_on_repo`
  - `test_schemas_check_fails_on_drift` (copy to tmp and edit one file)
- `tests/integration/test_cli_postgres.py::test_cli_happy_path_against_postgres`: run the commands with the real `build_context` pointed at the test DB URL (`LANGPIPE_DATABASE_URL`) and a tmp data dir.

**Do NOT:** add commands not listed (no `db` wrapper; use `uv run alembic upgrade head`); print raw content; put business logic in the CLI.

---

### WP12 — Schema registry, generation and check

**Depends:** WP4a, WP4b. Parallel with WP7.
**Files:** `schemas/__init__.py`, `schemas/registry.py`, `schemas/generate.py`, `schemas/__main__.py`, all 11 `schemas/*.v1.schema.json` (generated, committed); tests `tests/unit/schemas/__init__.py`, `tests/unit/schemas/test_schema_artifacts.py`.

```python
# registry.py
SCHEMA_MODELS: tuple[type[DomainModel], ...] = (SourceManifest, SourcePolicy, Source, SourceObject, ProcessingRun,
    Artifact, Segment, TokenOccurrence, Form, EvidenceItem, LineageEdge)
# generate.py
def schema_filename(model: type[DomainModel]) -> str     # f"{SCHEMA_NAME}.v{SCHEMA_VERSION}.schema.json"
def render_schema(model: type[DomainModel]) -> str
    # s = model.model_json_schema(mode="serialization"); add "$id": f"urn:langpipe:schema:{name}:{version}",
    # "$schema": "https://json-schema.org/draft/2020-12/schema", "x-schema-name": name, "x-schema-version": version;
    # return json.dumps(s, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
def generate(schema_dir: Path) -> list[Path]            # writes all; removes nothing
def check(schema_dir: Path) -> list[str]                # names of missing/different/unexpected *.schema.json files; [] means OK
def main(argv: Sequence[str] | None = None) -> int      # "generate"|"check" [--dir]; check → 1 on drift
```

**Tests first:**
- **`test_committed_schemas_match_generated`** (mandatory 8): `check(REPO_ROOT/"schemas") == []`.
- `test_every_schema_model_has_unique_name`
- `test_schema_has_id_and_version`
- `test_check_reports_unexpected_file`
- `test_render_is_deterministic`
- `test_serialization_roundtrip_for_all_schema_models` (all 11 models; `model_validate_json(model.model_dump_json())` is equal to the original). Exported-object schema name/version shape remains an open disagreement below; x-schema metadata does not fulfill that contract.

**Acceptance:** `uv run python -m langpipe.schemas generate && git diff --exit-code -- schemas/` (after the first schema commit; also assert all 11 files are tracked with `git ls-files`, because diff ignores untracked files) and `uv run python -m langpipe.schemas check`.

**Do NOT:** hand-edit JSON files; generate schemas for non-M1 entities; include the `AuditEvent`/`RawBlob` models.

---

### WP13 — Golden fixture scaffold and M1 golden test

**Depends:** WP10, WP10b, WP12 (Postgres variant via WP9). **Files:**
```text
tests/golden/__init__.py
tests/golden/fixture/README.md                 # purpose, synthetic-data statement, language codes
tests/golden/fixture/PHENOMENA.md              # GOLDEN-FIXTURE.md phenomenon → file:line → milestone that exercises it
tests/golden/fixture/sources/01-parallel-distill/manifest.yaml + parallel.tsv
tests/golden/fixture/sources/02-educational-direct/manifest.yaml + lessons.tsv
tests/golden/fixture/sources/03-wordlist/manifest.yaml + wordlist.tsv
tests/golden/fixture/sources/04-igt/manifest.yaml + igt.txt
tests/golden/fixture/sources/05-monolingual/manifest.yaml + text.txt
tests/golden/fixture/sources/06-excluded/manifest.yaml        # mode exclude, no objects (governance check)
tests/golden/normalize.py
tests/golden/expected/m1/sources.json, source_objects.json, runs.json, artifacts.json, lineage.json, audit.json, eligibility.json
tests/golden/expected/README.md               # pending expectations by milestone; update rules
tests/golden/test_golden_m1.py
```
**Fixture data rules:** synthetic language `qaa` and pivot `por`, all invented. All files UTF-8 NFC except one deliberate NFD line in `05-monolingual/text.txt`, which documents a normalization case for M2. Use the content below exactly.

`01-parallel-distill/parallel.tsv` (policy `distill_only`, access `community`, source_type `parallel_text`, domains `[religious]`, registers `[religious]`, explicit `allow: [align, distill_lexicon, distill_morphology]`):
```text
ref	qaa	por
TXT.1.1	kanu mabi tesa.	O homem vê a canoa.
TXT.1.2	mabi-ki nawa wesa.	A canoa foi ao rio.
TXT.1.3	kanu nawa wesa-ra.	O homem não foi ao rio.
TXT.1.4	rumi tesa mabi-ki.	O pajé vê a canoa. Ele sorri.
```
(TXT.1.4 is the 1:n alignment case: one `qaa` segment ↔ two Portuguese sentences.)

`02-educational-direct/lessons.tsv` (`direct`, `public`, `educational_publication`, registers `[pedagogical]`):
```text
lesson	qaa	por
L1	kanú tesa.	O homem vê.
L2	mabi shara.	A canoa é boa.
```
(`kanú` is the orthographic variant of `kanu`.)

`03-wordlist/wordlist.tsv` (`direct`, `public`, `wordlist`):
```text
qaa	por	note
kanu	homem
mabi	canoa; tronco	two candidate senses
rumi	pajé	domain-specific (ritual/traditional)
```

`04-igt/igt.txt` (`review_required`, `community`, `igt`):
```text
\ref IGT-1
\t mabi-ki nawa wesa
\m mabi-ki nawa wesa
\g canoa-ERG rio ir.PST
\f A canoa foi ao rio.

\ref IGT-2
\t wesa-ra
\m wesa-ra
\g ir-NEG
\f não foi
```

`05-monolingual/text.txt` (`direct`, `community`, `monolingual_text`, languages `[qaa]`): three lines, `kanu mabi tesa.`, `rumi shara.` and the NFD line `kanú wesa.` (written with `u` + U+0301).

`06-excluded/manifest.yaml`: `mode: exclude`, `access_class: highly_restricted`, `source_type: other`, languages `[und]`, no objects.

All manifests set `authority: "synthetic fixture steward"` and `acquired_at: 2026-01-01T00:00:00Z`; provenance `acquired_from: "synthetic"`.

**normalize.py:**
- `def normalize_snapshot(ctx: AppContext, registrations: Sequence[RegistrationResult], ingestions: Sequence[IngestResult]) -> dict[str, JsonValue]` uses result IDs to fetch sources, objects, runs and artifacts; uses list_lineage_edges and list_audit_events for remaining rows. No nonexistent list-all repository methods. eligibility.json is a mapping; row snapshots are lists.
- It replaces every ID with a stable label: sources `src:<key>`, objects `sobj:<key>/<path>`, runs `run:<stage>:<key>`, artifacts `artifact:ingest_report:<key>`, policies `pol:<key>`.
- It replaces datetimes with `"<ts>"` and `code_revision`/`tool_version` with `"<rev>"`/`"<ver>"`.
- Label lineage IDs `lin:<from-label>:<kind>:<to-label>` and audit IDs `aud:<subject-label>:<event_type>` for the single-success fixture pass. Replace references everywhere, including nested run configs, then replace derived config_hash/run_key with `<hash>` (real correctness is asserted in service tests). Manifest hashes remain real. Normalize origin_uri to `fixture:<source-key>/<original_path>` so machine paths do not affect expectations.
- Sort row snapshots by label; preserve schema arrays with semantic ordering. Collect existing outputs after each registration/ingest, including reusable results; no ID generator assumptions.

**test_golden_m1.py** (uses `ctx`, so it runs on both backends):
- `test_golden_m1_snapshot`: register and ingest sources 01–05 and register 06. Keep the snapshot path success-only; test ingest denial for 06 separately because every denial deliberately appends an audit event and would invalidate rerun equality. Compare `normalize_snapshot` against each `expected/m1/*.json`. On mismatch, print a unified diff. If `LANGPIPE_UPDATE_GOLDEN=1`, write the files **and still fail** with "golden files rewritten; review the diff and commit intentionally".
- `test_golden_m1_rerun_creates_no_duplicates`: running the whole fixture twice gives an identical snapshot.
- `test_golden_distill_only_sentence_not_trainable`: `resolve(policy_of("01-parallel-distill"), direct_training) == deny`, and `eligibility.json` records `{"src:01-parallel-distill": {"direct_training": "deny", …}}` for the operations `direct_training, synthetic_generation_support, third_party_api`, for all 6 sources.
- `test_golden_excluded_source_not_ingested`.
- `test_golden_lineage_impact_from_source`: `impact_of(src:01)` equals the objects plus the ingest report (this is the M1 scaffold for the "revoked source" phenomenon).

`expected/README.md` lists pending expectations: M2 segments/tokens/forms (including the NFD line and the `kanu`/`kanú` variant); M3 the TXT.1.4 1:n alignment and the unaligned token `-ra`; M4 `mabi` with two senses, domain item `rumi`, CLDF; M5 IGT-validated morpheme `-ki`, competing segmentation of `wesa-ra`, unknown morpheme; review accept/reject; revocation of 01. **Do not create skip-marked placeholder tests.**

**Acceptance:** `uv run pytest tests/golden -q` (memory). With the DB up: `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest tests/golden -q` with 0 skips.

**Do NOT:** use real Marúbo data or the code `mzr` in fixtures; generate expected files and commit them without reading them (the senior reviews them); add later-stage logic.

---

### WP14 — Developer documentation and CI script

**Depends:** all. **Files:** `scripts/ci.sh`, `README.md` (append a "Development quickstart" section), `docs/DEVELOPMENT.md` (append "Local commands (M1)"), `docs/implementation/M1-PLAN.md` (tick off the status table at the end).

`scripts/ci.sh` (`set -euo pipefail`):
```text
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run python -m langpipe.schemas check
docker compose up -d --wait db
uv run alembic -x url="$LANGPIPE_TEST_DATABASE_URL" upgrade head
LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -q  # unit + contract + service + golden + integration
```
Export `LANGPIPE_TEST_DATABASE_URL` with the WP1 test default before migration/tests. WP1 pg_url fails (rather than skips) when `LANGPIPE_REQUIRE_POSTGRES=1` and PostgreSQL is unavailable. CI also fails on any skipped tests (pytest sessionfinish in tests/fixtures/db.py, owned initially by WP1); this turns the zero-skips requirement into a gate. Migrations/cleanup only accept a database name ending `_test`; never downgrade or truncate the application database.

**Do NOT:** add GitHub Actions YAML (no remote CI decision yet); edit normative docs beyond the commands sections.

---

## 8. Mandatory M1 test coverage map

| # | Requirement (LOCAL-AGENT-HANDOFF.md) | Primary test | Supporting tests |
|---|---|---|---|
| 1 | raw source bytes cannot be mutated through the domain API | `tests/unit/storage/test_local_content_store.py::test_store_has_no_mutation_api`, `::test_open_returns_read_only_stream`, `::test_put_is_content_addressed_and_idempotent` | `tests/unit/domain/test_models_source.py::test_source_object_is_frozen`; `tests/integration/test_append_only_triggers.py::test_source_object_update_rejected`, `::test_raw_blob_update_rejected` |
| 2 | denied policy prevents processing before work begins | `tests/service/test_ingest.py::test_exclude_policy_denies_before_any_work` | `tests/service/test_observation_recorder.py::test_extract_denied_for_archive_only_creates_nothing`; `tests/unit/governance/*`; `tests/unit/cli/test_cli_source.py::test_ingest_exclude_exits_3` |
| 3 | ingest creates complete source/run/lineage records | `tests/service/test_ingest.py::test_ingest_creates_complete_source_run_lineage_records` | `tests/service/test_registration.py::test_register_creates_source_policy_objects_run_and_edges`; golden snapshot |
| 4 | rerunning identical ingestion is idempotent | `tests/service/test_ingest.py::test_rerun_identical_registration_and_ingestion_is_idempotent` | `tests/golden/test_golden_m1.py::test_golden_m1_rerun_creates_no_duplicates`; `tests/service/test_registration.py::test_register_same_manifest_twice_is_noop` |
| 5 | restricted raw content absent from default logs | `tests/service/test_log_redaction.py::test_restricted_raw_content_absent_from_default_logs` | `tests/unit/cli/test_cli_source.py::test_cli_output_never_contains_raw_content`; `tests/unit/test_logging.py::test_log_event_rejects_free_text` |
| 6 | source-object hash verification detects corruption | `tests/service/test_verify.py::test_verify_source_reports_corrupted_object` | `tests/unit/storage/test_local_content_store.py::test_verify_detects_corruption`; `tests/service/test_ingest.py::test_source_changed_after_registration_fails_run` |
| 7 | observations unchanged when downstream hypotheses change | `tests/contract/test_repository_contract.py::test_observations_unchanged_when_evidence_changes` | `tests/service/test_evidence_service.py::test_superseding_evidence_leaves_tokens_unchanged`; `tests/integration/test_append_only_triggers.py::test_token_occurrence_update_rejected`. *M1 has no MorphAnalysis/Lexeme; EvidenceItem supersession stands in for "hypothesis change". The full MorphAnalysis variant is added in M5 (GOLDEN-FIXTURE § Observation/inference separation).* |
| 8 | serialized schema artifacts match generated models | `tests/unit/schemas/test_schema_artifacts.py::test_committed_schemas_match_generated` | `tests/unit/cli/test_cli_schemas.py::test_schemas_check_fails_on_drift` |

Tests that depend on the backend (rows 2, 3, 4, 5, 6 and 7) run against the in-memory repository in the unit pass and against PostgreSQL in the integration pass, through the `repo`/`ctx` fixtures.

## 9. Senior review checklist (applied to every WP before merge)

- Names, enum values, columns and file paths match this plan exactly.
- The tests listed for the WP exist, were written first and assert what is described. No assertion was weakened.
- No raw, segment or token text, title or filename appears in logs, errors, audit details or report artifacts.
- No update or delete path exists for observations, evidence or lineage.
- Policy gates run before any I/O or run creation.
- Ruff, format, mypy (strict) and pytest are green. The integration pass is green with 0 skips when `docker compose up -d db` is running.

## 10. Risks

1. **ADR-0007 matrix not ratified.** The governance owner may disagree, for example on `evaluation` or `synthetic_generation_support` under `distill_only`. Mitigation: the matrix is one table plus one literal test, so a change touches two files.
2. **Divergence between the two repository implementations.** The in-memory and Postgres repositories can drift apart. Mitigation: one shared contract suite; the integration pass must have zero skips before M1 is declared done.
3. **Trigger and TRUNCATE semantics.** Tests depend on TRUNCATE bypassing row triggers. If a future statement-level trigger is added, test cleanup breaks. This is documented in ADR-0009.
4. **Sentinel-based redaction tests prove absence only for the paths exercised.** `log_event`'s field-specific ID/hash/enum allowlist is the structural protection. Reviewers must reject any `logger.info(f"...")`.
5. **Orphan blobs on failed transactions** (ADR-0008). They are harmless but accumulate; GC is deferred.
6. **Shared-file coupling.** `base.py` (WP2), `tests/fixtures/backends.py` (WP7, then WP10) and `tests/fixtures/db.py` (WP1, then WP8, then WP9) are edited by sequential WPs only. Parallel WPs must not touch them.
7. **Junior over-reach into M2.** For example, adding a TSV extractor to make golden segments appear. The "Do NOT" lists forbid this, and review must enforce it.

## 11. Status

| WP | Status |
|---|---|
| WP1–WP13 | merged per git history; not re-verified by WP14 |
| WP14 | implemented, including senior-review repairs (required-PostgreSQL and zero-skip enforcement, `_test` guard before migration); `scripts/ci.sh` green (415 passed, 0 skipped with PostgreSQL up); senior re-review approved 2026-10-12 |


## Review log

Second senior review, 2026-10-11. Only this plan changed; implementation code and ADR proposals were not edited. Existing unrelated working changes were preserved.

### Changes made

1. Replaced unconditional readiness wording with a reference to unresolved orchestrator decisions; corrected the deferred-schema count (15) and the repository fixture name.
2. Corrected WP dependencies: WP10 needs WP9 for build_context, WP10b needs WP10's service fixtures, and WP13 needs WP10b/WP12. Assigned shared test initializers and uv.lock to WP1 to remove parallel file ownership collisions.
3. Required repository deep copies and revalidated state changes: Pydantic frozen models permit nested-container mutation, and model_copy(update=...) skips validation. Added a contract test for aliasing.
4. Added span bounds/representation checks and paired nullable SQL offsets. Required ORM/migration defaults, nullability, uniqueness and indexes to agree; added terminal-run SQL state checks and regression tests.
5. Aligned missing-file registration tests with preflight (no run exists), gated registration hashing, and expanded ingestion failure handling to cover store/hash/report errors as well as transactions.
6. Replaced unrestricted exception/error rendering with fixed diagnostics and empty persisted error_message. Replaced permissive lowercase log/audit regexes with field-specific ID/hash/enum/count allowlists; added lowercase/filename/parser failure cases.
7. Fixed the failed-ingest redaction recipe: corrupt a second origin before its first ingest so run reuse cannot hide the error path. Strengthened the denied-ingest test with I/O/store spies.
8. Supplied explicit run/evidence signatures, policy ancestry lookup, recorder run ownership, atomic supersession, raw-only recorder semantics and Form/run-I/O lineage, including reused Forms and a multi-source impact test.
9. Applied CLI error handling at command boundaries for CliRunner and the console entry point; disabled exception locals and clarified the JSON metadata-output exception. Quoted Settings' self-return annotation under the no-future-import convention.
10. Specified verification statuses; corrected Alembic programmatic URL precedence; required test-only database guards, exported CI URL and an executable zero-skips gate. Schema acceptance also checks tracked files; added model serialization roundtrips.
11. Made golden normalization implementable using result IDs and existing repository methods; added artifacts snapshots, labels for lineage/audits, nested references and machine-path normalization. Removed denied-ingest auditing from the success rerun snapshot so idempotence assertions can pass.

### Mandatory test assessment

| Handoff test | Assessment after corrections |
|---|---|
| 1. Immutable raw bytes | Provable through read-only streams/write-once API plus DB triggers; host filesystem tampering is intentionally outside the domain API. Nested observation mutation also receives a contract test. |
| 2. Denied policy before work | I/O spies and row assertions prove the exercised ingest/recorder paths; actor/restrictions and revoked sources remain unresolved below. |
| 3. Complete source/run/lineage | Source/object/report edges and run I/O are explicit; Form/evidence recorder lineage was added. Concurrency guarantees remain unresolved below. |
| 4. Identical ingestion idempotent | Sequential successful reruns are provable. Deliberate policy-denial audit attempts are separate; concurrent/recovery guarantees are not proved. |
| 5. No restricted content in default logs | Field allowlists plus successful, failing, parser and CLI cases provide meaningful coverage. Raw exception strings and exception locals are prohibited. |
| 6. Corruption detection | Store and verify service tests exercise stored corruption; source-change failure uses a first ingest, avoiding reuse. |
| 7. Hypothesis changes preserve observations | Evidence supersession proves evidence/observation separation only. It cannot literally prove changes to a linguistic hypothesis absent an inference model; orchestrator decision required. |
| 8. Schema artifacts match models | Deterministic generation/check and roundtrip tests prove model/schema drift detection. Exported-object schema metadata is a separate unresolved contract. |

### Open disagreements for the orchestrator

1. **Actor restrictions and read access (ADR-0007 §8, WP3/WP10/WP10b).** Storing opaque restrictions without enforcing them conflicts with GOVERNANCE's named users/workflows/locations. Explicit allow lifts restricted mode's default denial; direct/community sources with restrictions also pass. Registration/ingestion and verify perform byte reads despite read_raw denial, and low-level stores expose ungated reads. Choose a minimal authorization context/guard or reject unsupported restrictions and define a distinct permitted preservation/integrity-read capability. The proposed matrix/actor design is unchanged; affected processing must not be declared governance-complete.
2. **Revocation and policy changes (G18, WP7/WP10).** M1 already exposes revoked status but ingest and recorders consult only the unchanged policy, allowing revoked sources and ancestors to process; set_source_status can also un-revoke them. Deferring exporters does not resolve existing processing authorization. Decide fail-closed revoked-ancestor guards/status transitions and the minimal policy-version strategy. Full export rebuilding remains later scope.
3. **Run identity, concurrency and recovery (ADR-0008).** Excluding code_revision and using tool_version=0.1.0 permits changed code to reuse stale outputs. Two concurrent registrations/ingests may race on natural keys or succeeded-run uniqueness; ON CONFLICT/reselect after IntegrityError needs a savepoint or rollback. Crashed running runs have no recovery semantics. Decide the supported M1 concurrency contract, run serialization/recovery mechanism and whether revisions belong in the key. Add real PostgreSQL interleaving tests if concurrent use is supported; sequential reruns alone are insufficient.
4. **Persisted decisions not covered by proposals (D5/D6/G11).** Manifest format, entity field names/enums, target_id/claim representation and public schema shape are persisted interfaces, not merely reversible implementation details. AGENTS/handoff require ADR proposals for such decisions. Existing 0007–0009 do not specify all of them; orchestrator must record the additions and update normative docs before treating plan-only choices as canonical. Proposed ADRs are not ratification; docs/adr/README.md also requires current docs updates.
5. **Exported-object version metadata (WP4/WP11/WP12, SCHEMAS §Versioning).** SCHEMA_NAME/SCHEMA_VERSION ClassVars and JSON Schema x-schema annotations do not appear in model_dump; source show exports unversioned objects. Choose inline name/version fields or an explicit versioned export envelope, record the interface in an ADR, and add a serialization test. No envelope was invented during this review.
6. **Literal mandatory test 7 and lifecycle scope (WP4b/§8).** EvidenceItem is evidence, not a hypothesis. The stand-in test does not establish the literal handoff contract for downstream hypothesis changes. Resolve whether an explicit M1 test-double inference fixture is acceptable or whether a minimal candidate model is required; do not add MorphAnalysis production code just for this test. The generic lifecycle guard only checks presence of a claimed basis, not authority, and its strict transition graph is not fully normative; cut/defer it for M1 or record the graph/authority contract before future producers use it.
7. **Immutable Segments versus M2 normalization (WP4b/WP8, PIPELINE Stage 3).** M1 records raw-only immutable Segments; M2 must add normalized representations without updating them. Decide a versioned Segment/normalization-record boundary and lineage before M2 rather than bypassing triggers. This review preserves M1 immutability and does not invent M2 storage.
8. **Potential M1 over-engineering.** The pure lifecycle/validation guard, reserved later-stage vocabulary, six-file golden provenance snapshot machinery and two repository implementations add maintenance beyond the evidence substrate. Cut the lifecycle guard first unless its contract is explicitly accepted; keep meaningful mandatory behavior and PostgreSQL tests. Choice of an in-memory repository versus narrower fakes is left to the orchestrator, not silently reversed.

### Review limits

Documentation consistency review only; no implementation or runnable test suite exists yet. Missing instruction includes: ../.tessl/RULES.md and the SuperClaude COMMANDS/FLAGS/PRINCIPLES/RULES/MCP/PERSONAS/ORCHESTRATOR/MODES files are not present in this checkout. The supplied browser-harness path was stale; its actual local skill was read, and no browser action was needed. Acceptance commands are specified contracts, not independently passing evidence.
