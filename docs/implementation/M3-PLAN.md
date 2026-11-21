# M3 Parallel Evidence Implementation Plan

> **Superseded policy note (ADR-0025).** Any rule below that blocks processing or
> training because of a source's classification, licence, rights holder, or register is
> historical. Presence in the repository authorizes processing and training; licences
> and ownership are records, not gates.

> For agentic workers: execute work packages task-by-task using the executing-plans skill;
> senior review gates each package. No implementation is authorized by this document alone.

**Status:** Implementation in progress (WP3.0–WP3.12 completed; WP3.13 synthetic completed; ADR-0011 Accepted; WP3.14 contract documentation updated; dual-source ScriptureEarth realdata gate unsatisfied pending operator inputs and reviewed metadata).
**Date:** 2026-10-14
**Goal:** Persist auditable n:m segment and token alignment evidence, prove graph/governance
semantics on synthetic golden data and locally authorized ScriptureEarth mzr–por inputs.  
**Architecture:** Pure versioned segment matching and a local corpus-level token adapter feed
atomic services through the existing Repository/RunRecorder boundary. PostgreSQL is canonical;
in-memory behavior shares contract tests.  
**Tech stack:** Python 3.12+, uv, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16+, Typer,
pytest/Hypothesis, Ruff/mypy; optional pinned native eflomal.

## 1. Baseline and scope

The user reports M1/M2 complete, 858 passing tests, 16 mzr realdata tests and live PostgreSQL
16 verification. Those runs were not repeated during this documentation-only design pass.
Live source inspection confirms M2 derived segments, pure registries, UnitOfWork, run reuse,
lineage policy helpers and realdata redaction. Working tree was clean before these documents.

Deliver Stage 4 canonical coordinate import; Stage 5 adapter/persistence/report; requested CLI;
precision/recall/F1/AER/null benchmark harness; golden M3 and local mzr–por verification.
No lexical induction, senses, morphology splitting, synthetic generation, training exporter,
CLDF implementation, neural aligner, graph database or review UI. The opt-in sentence TSV
extractor is the sole M2 extension, explicitly covered by ADR-0011.

Applicable contracts: AGENTS.md; DEVELOPMENT §M3; DOMAIN-MODEL §Alignment entities, §Lineage,
§Lifecycle; PIPELINE-CONTRACTS Stages 4–5; GOLDEN-FIXTURE; PHENOMENA; ADR-0002/0004/0007–0010;
M1-PLAN/M2-PLAN conventions. Supporting confidence, governance, evaluation and mzr documents
were inspected. Referenced SuperClaude files, `../.tessl/RULES.md` and
`~/Dev/browser-harness/SKILL.md` are absent at the supplied paths; no browser task depends on
them. Memory registry lookup found no relevant project entry.

## 2. Conflicts and gaps (C1–C13)

| ID | Evidence / gap | Proposed resolution / owner |
|---|---|---|
| C1 | Alignment entities are prose-only; n:m storage unspecified | Ordered relational membership, one hyperedge per group; ADR-0011 / WP3.1–3.3 |
| C2 | Requested statuses differ from AGENTS linguistic lifecycle | Separate evidence disposition, never linguistic validation; acceptance of ADR exception required before coding |
| C3 | Stage 5 says approved inputs; request includes structural | Structural coordinate evidence is eligible without claiming translation truth; inferred/candidate excluded; update Stage 5 in WP3.14 |
| C4 | M2 deferred current-run selection; list_segments includes generations | Explicit normalization/tokenization run pins; unique-only defaults, AmbiguousInput on alternatives / WP3.5 |
| C5 | Golden TXT.1.4 por cell has two sentences but M2 emits one Segment | Separate opt-in tsv_sentences extraction run; real 1:2 group; M2 bytes/snapshots untouched / WP3.4,3.12 |
| C6 | PHENOMENA calls suffix `-ra` a token; M2 preserves `wesa-ra` | Correct milestone description during implementation; whole-token null + separate synthetic standalone `-ra` case, suffix interpretation deferred to M5 / WP3.12 |
| C7 | No guaranteed per-token statistical probabilities | Nullable score and raw components; null/score_unavailable, no manufactured confidence / WP3.1,3.8 |
| C8 | eflomal compiler, API, seed and score support unproven locally | Pin upstream 2.0.0; native compatibility spike; mock only in tests; no silent fallback / WP3.0,3.8 |
| C9 | Existing VersionedRegistry unknown lookup raises no_extractor | Alignment wrapper maps unknown refs to AlignmentFailed(unknown_method), leaves M2 registry unchanged / WP3.6,3.8 |
| C10 | Revocation isn't checked by effective_decision helper itself | Alignment guard explicitly checks SourceStatus plus ancestry, before reuse and under source-row locks at commit / WP3.5,3.9 |
| C11 | Only local mzr package directory observed; no local por directory | Operator-supplied reviewed por package/manifest, independent rights and versification checks; selected realdata tests fail on missing inputs / WP3.13 |
| C12 | No mzr–por gold matrices or quality threshold supplied | Synthetic exact metrics + native structural smoke; real linguistic-quality claims blocked until authorized gold exists; no guessed accuracy gate / WP3.11,3.13 |
| C13 | Existing IDs are opaque ULIDs, not deterministic content-derived IDs | Successful run reuse + natural uniqueness stabilize IDs within an installation; golden normalizes labels; concurrent duplicate work serialized / WP3.5,3.9 |

## 3. Global constraints and execution gates

- Raw sources, existing Segments and TokenOccurrences MUST remain immutable.
- Observations and inference are different entities; aligners produce evidence only.
- `distill_only` source prose/audio MUST NOT enter a trainable dataset directly.
- Every derived object MUST retain relational source lineage and its processing run.
- Restricted material MUST NOT reach third-party APIs without explicit source permission.
- Generic pipeline code MUST NOT contain Marúbo-specific rules or invented morphology.
- Persisted changes require migration, schemas, tests and documentation.
- ADR-0011 is Accepted (2026-10-13). Persisted model/service work proceeds under that
  acceptance.
- Native compatibility gate WP3.0 precedes eflomal integration; a failing spike blocks native
  completion, not compiler-free model/repository work after ADR acceptance.
- Source policy/authority, Portuguese availability and coordinate compatibility precede any
  realdata alignment. Public availability and M2 mzr permission do not authorize por use.
- All PostgreSQL acceptance/migration/realdata commands use a disposable `_test` database
  and run sequentially. Never downgrade the populated application database.
- Juniors (`glm-5.3`) implement one owned package per review. No unrelated refactors or fixes.
  Red tests first, smallest implementation, targeted checks, then senior contract review.
  Workers preserve other contributors' edits. Commits belong to implementation, not this pass.

## 4. Target architecture and data flow

```text
Registered, authorized, hash-verified sources (mzr + por OR bilingual qaa/por)
  -> M2 extraction [optional separate tsv_sentences@0.1.0 for golden]
  -> pinned normalized Segments -> pinned TokenOccurrences
  -> SegmentAlignmentService [Operation.ALIGN; canonical_locator@0.1.0]
       -> SegmentAlignment + ordered members + lineage + alignment_file report
  -> TokenAlignmentService [structural/approved only; Operation.ALIGN]
       -> corpus batch / index maps -> local EflomalAligner
       -> forward + reverse + intersection/union TokenAlignmentEdges
       -> alignment_file report, unaligned IDs, provenance, lineage
  -> BenchmarkService [Operation.EVALUATION; frozen gold artifact]
       -> benchmark_report (metrics only; no linguistic promotion)
```

Each arrow has its own run. Reports are infrastructure artifacts, not another semantic layer.
Stage 4 never produces Segments, Tokens, Forms or dictionary assertions. Stage 5 never rewrites
Stage 4 disposition. Failures leave original groups intact; failed token runs have no edges.

### Module layout (new paths unless marked modify)

```text
src/langpipe/domain/models/alignment.py             # persisted evidence models
src/langpipe/alignment/__init__.py
src/langpipe/alignment/base.py                       # pure DTOs/protocols
src/langpipe/alignment/registry.py                   # segment/token registries
src/langpipe/alignment/selection.py                  # pinned run resolution
src/langpipe/alignment/governance.py                 # policy/revocation preflight
src/langpipe/alignment/canonical.py                  # keys/components
src/langpipe/alignment/segment_service.py            # Stage 4 orchestration
src/langpipe/alignment/token_service.py              # Stage 5 orchestration
src/langpipe/alignment/report.py                     # allowlisted reports
src/langpipe/alignment/symmetrization.py             # set intersection/union
src/langpipe/alignment/adapters/__init__.py
src/langpipe/alignment/adapters/eflomal.py            # optional local backend
src/langpipe/extraction/tsv_sentences.py              # opt-in sentence units
src/langpipe/evaluation/__init__.py
src/langpipe/evaluation/alignment.py                 # metrics/gold schema
src/langpipe/evaluation/service.py                   # governed benchmark artifact
src/langpipe/cli/alignment.py                        # align subcommands
migrations/versions/0003_m3_alignment.py
```

Modified shared paths: `domain/enums.py`, `domain/ids.py`, `domain/errors.py`,
`domain/models/__init__.py`, `storage/repository.py`, `storage/memory.py`,
`storage/db/tables.py`, `storage/db/repository.py`, `schemas/registry.py`,
`extraction/registry.py`, `cli/app.py`, `pyproject.toml`, `uv.lock`, fixture cleanup and
migration tests. No foundational tooling switch or global registry rewrite.

## 5. Exact models, interfaces and persistence

### 5.1 Persisted models

All models extend frozen `DomainModel`, reject extra fields, validate prefixed IDs and UTC.
Schemas: `segment-alignment.v1.schema.json`, `token-alignment-edge.v1.schema.json`.

| Model | Fields |
|---|---|
| SegmentAlignment | id (`sal`), source_segment_ids / target_segment_ids (`tuple[str, ...]`, nonempty), method (`VERSIONED_NAME`), mode (`AlignmentMode`), status (`AlignmentStatus`), score (`float | None`), raw_scores (`dict[str, float]`), group_key (SHA256), run_id, created_at, authorization_basis_id (`artifact` ID or null), supersedes_id (`sal` ID or null) |
| TokenAlignmentEdge | id (`tal`), segment_alignment_id (`sal`), source_token_id / target_token_id (`tok`), direction (`AlignmentDirection`), algorithm (`VERSIONED_NAME`), score (`float | None`), raw_scores (`dict[str, float]`), symmetrization (`Symmetrization`), run_id, created_at |

Enums: AlignmentMode = canonical/heuristic/experimental; AlignmentStatus =
structural/inferred/candidate/approved/rejected; AlignmentDirection = forward/reverse/symmetrized;
Symmetrization = none/intersection/union. EntityType adds segment_alignment/token_alignment_edge;
IdPrefix adds SEGMENT_ALIGNMENT="sal", TOKEN_ALIGNMENT="tal". No new RunStage/ArtifactKind
needed: use SEGMENT_ALIGNMENT, TOKEN_ALIGNMENT, EVALUATION and ALIGNMENT_FILE/BENCHMARK_REPORT.

Scores are finite when present, never bool/NaN/infinity; raw components retain their own scale,
no forced [0,1] probability interpretation. Empty raw_scores permitted. Symmetrized direction
requires intersection/union; forward/reverse require none. Approved/rejected require both
basis and predecessor; others require neither. Service verifies authority and lineage.

### 5.2 DTOs and signatures (type sketches only)

`AlignmentSide` has source_id, language, normalization_run_id, tokenization_run_id (nullable
for Stage 4). `AlignmentConfig` has namespace, versification_id (nullable for TSV),
symmetrization (default intersection), model (default 3), threads (default 1), timeout_seconds
(default 300, positive), and random_seed (null unless native spike proves support).
`SegmentGroup` contains ordered source/target Segment tuples, group_key, status and reason
(enum or null). `SegmentMatchOutput` has groups and unmatched ID/reason tuples.
`TokenGroup` contains alignment_id and ordered source/target TokenOccurrence tuples.
`IndexLink` contains source_index, target_index, score (null), raw_scores (empty by default).
`TokenLinks` contains alignment_id, forward/reverse IndexLink tuples. `TokenBatchOutput`
contains groups and backend metadata (version/hash/options/seed-support; no text).

```python
class SegmentAligner(Versioned, Protocol):
    def align(self, source: Sequence[Segment], target: Sequence[Segment],
              config: AlignmentConfig) -> SegmentMatchOutput: ...

class TokenAligner(Versioned, Protocol):
    def align(self, groups: Sequence[TokenGroup],
              config: AlignmentConfig) -> TokenBatchOutput: ...

class SegmentAlignmentService:
    def __init__(self, ctx: AppContext) -> None: ...
    def align(self, source: AlignmentSide, target: AlignmentSide, *,
              method: str = "canonical_locator@0.1.0",
              config: AlignmentConfig) -> SegmentAlignmentSummary: ...

class TokenAlignmentService:
    def __init__(self, ctx: AppContext) -> None: ...
    def align(self, segment_run_id: str, *, source_tokenization_run_id: str,
              target_tokenization_run_id: str, method: str = "eflomal@0.1.0",
              config: AlignmentConfig) -> TokenAlignmentSummary: ...

class BenchmarkService:
    def __init__(self, ctx: AppContext) -> None: ...
    def evaluate(self, token_run_id: str, gold_artifact_id: str, *,
                 direction: AlignmentDirection = AlignmentDirection.SYMMETRIZED
                 ) -> BenchmarkSummary: ...
```

SegmentAlignmentSummary = run, alignment count, unmatched_source/target counts, report Artifact,
reused. TokenAlignmentSummary = run, edge count, unaligned_source/target counts for selected
symmetrization, skipped_groups count, report Artifact, reused. BenchmarkSummary = run,
metrics (`AlignmentMetrics`), report Artifact, reused. AlignmentMetrics stores counts,
precision/recall/F1/AER nullable floats, null precision/recall nullable floats, and reason codes.

Registries `SEGMENT_ALIGNERS` and `TOKEN_ALIGNERS` live in alignment/registry.py. Service
injection for tests uses a registry instance passed via a keyword-only constructor argument
`aligners: VersionedRegistry[SegmentAligner] | None = None` / token equivalent; production
defaults never include mocks. Eflomal import is lazy. Resolve unknown methods to fixed errors.

Add `AlignmentFailed(code: str)` exit code 12 with allowlist: unknown_method,
invalid_coordinates, incompatible_versification, duplicate_book, ambiguous_coordinates,
missing_tokenization, incompatible_runs, invalid_adapter_output, backend_unavailable,
backend_failed, backend_timeout, unsupported_seed, authorization_invalid, invalid_gold.
Never include user payload/exception text. Existing AmbiguousInput remains exit 11;
PolicyDenied 3, SchemaViolation 4, InvalidLineage 8 remain unchanged.

### 5.3 Repository additions

```python
def add_segment_alignment(self, alignment: SegmentAlignment) -> None: ...
def get_segment_alignment(self, alignment_id: str) -> SegmentAlignment: ...
def list_segment_alignments_for_run(self, run_id: str) -> list[SegmentAlignment]: ...
def add_token_alignment_edge(self, edge: TokenAlignmentEdge) -> None: ...
def get_token_alignment_edge(self, edge_id: str) -> TokenAlignmentEdge: ...
def list_token_alignment_edges_for_run(self, run_id: str) -> list[TokenAlignmentEdge]: ...
def lock_sources(self, source_ids: Sequence[str]) -> None: ...
def alignment_lock(self, request_key: str) -> AbstractContextManager[None]: ...
```

Add methods to Protocol and both implementations. No status setter. Reads return defensive
copies; lists deterministic by group_key/id then endpoint/direction. Writes require the caller's
transaction; group members are inserted internally by add_segment_alignment, not exposed as
independently valid entities. `lock_sources` requires transaction; PostgreSQL SELECT FOR UPDATE
in sorted order, memory validates existence under its transaction lock.

`alignment_lock` serializes one request over preflight/reuse/start/compute/commit. PostgreSQL
uses a dedicated session advisory lock keyed from request_key, released in finally; not a
transaction lock that vanishes after RunRecorder.start. Memory uses per-key lock. It must
not nest Repository.transaction. Lock scope includes failed completion; recheck reuse after
acquisition. This prevents two callers from both publishing an identical succeeded run.
No distributed worker/lease recovery: crashed running rows remain historical and retries
start new runs. Add bounded lock acquisition (same timeout_seconds), error backend_timeout.

Tables:

- `segment_alignment`: registry PK/FK, run FK, metadata above, UNIQUE(run_id, group_key).
- `segment_alignment_member`: alignment FK, segment FK, side CHECK(source/target), position
  >=0; PK(alignment_id, side, position), UNIQUE(alignment_id, segment_id); index segment_id.
- `token_alignment_edge`: registry PK/FK, group/token/run FKs; unique tuple from ADR-0011;
  indexes run_id, segment_alignment_id, source_token_id, target_token_id.
- Append-only triggers on all three. Deferred constraint triggers verify group completeness,
  member positions/languages/selected runs, token endpoint membership and producing run stage.
  Repository validates same rules eagerly on both backends. SQL checks null/finite scores and
  enum combinations; migration uses literal enum tuples, never imports live application enums.
- Expand object_registry entity-type CHECK; update clean_db truncation order for edge/member/
  parent tables. Downgrade checks data and references before any destructive DDL; refusal is
  transactional and preserves the schema. Empty 0002→0003→0002→0003 roundtrip is mandatory.

### 5.4 Run identity, failure and exact graph

Config stores ordered side descriptors, selected run IDs, namespace/versification, resolved
adapter refs, upstream version/hash/options, thread count, timeout and supported seed.
Input IDs contain source IDs, selected normalization/tokenization runs, actual member/token IDs
and segment-run ID as applicable. RunRecorder tool_version remains langpipe's version;
adapter/upstream identities are explicitly in config so their changes invalidate reuse.
Request_key uses the same canonical config/input identity; no origin filesystem paths or text.

Preflight metadata/authorization/selection precedes run creation. A missing backend is also
preflight. Under alignment_lock, repeat governance and reusable-run lookup. Native execution
is outside semantic transaction. Inside one transaction lock_sources, repeat governance,
insert complete outputs/report rows/lineage/run I/O and succeed. After an error roll back all
semantic rows and call RunRecorder.fail, storing only fixed error type and no raw message.
Adapter batch count, ID coverage, duplicate groups, index types/bounds, returned directions
and finite scores are validated before insertion; reject entire batch on malformed output.

Lineage exact assertions:

- sal → each member Segment via derived_from (no sal→sal Cartesian edges).
- tal → sal and both endpoint Tokens via derived_from.
- report → selected groups/segments/tokens and source inputs via derived_from; no report→run
  is required because run_id/run I/O already record ownership.
- successor sal → old sal via supersedes; → registered basis Artifact via imported_from.
- benchmark report → selected predicted edge objects and gold Artifact; also selected group
  inputs on zero-edge runs so it retains both source ancestries.
- Each semantic object/report has its creating run_id and OUTPUT run I/O. Selected dependencies
  are INPUT run I/O; no artificial output→run→output cycle.

## 6. Junior work packages

Each package owns exactly its listed files. Shared-file edits follow dependency order. Every
package follows: (1) add named red tests and run acceptance command; (2) implement only the
specified contracts; (3) rerun tests; (4) senior reviews invariant evidence and diff; (5) commit
only after review. Expected result is zero failures, with no database skips in required mode.
Commands below are acceptance commands for future implementation, not results of this pass.

### WP3.0 — Verify native baseline compatibility (bounded spike)

**Depends:** none; synthetic data only. **Size:** one junior session plus senior gate.
**Own:** create `docs/implementation/M3-EFLOMAL-SPIKE.md`,
`tests/integration/test_eflomal_native.py`; modify `pyproject.toml`, `uv.lock` only to add
optional `alignment = ["eflomal==2.0.0"]` and register `native_alignment` marker.
**Consumes:** ADR-0004 and upstream 2.0.0 archive.
**Produces:** reviewed backend invocation/options contract for EflomalAligner; records build
requirements, installed metadata/archive identity, forward/reverse ordering, no-link output,
thread/seed support, score availability, runtime and Python 3.12 compatibility.

- [x] Tests first: `test_native_batch_line_count`, `test_native_reverse_is_source_target_order`,
  `test_native_empty_link_line`, `test_native_optional_dependency_missing_fixed_error`.
  Use synthetic varied sentences, not a single sentence expected to yield invented certainty.
- [x] Verify native API/CLI against the pinned release, not mutable upstream master. Record
  supported options; unsupported seed requests fail. Do not patch native sampling to claim
  reproducibility. Default model=3, threads=1; native per-link scores remain unavailable unless
  proven. Archive checksum is in ADR-0011.
- [x] Native tests use `native_alignment` and explicit selection. Exclude them by default
  alongside realdata (`-m 'not realdata and not native_alignment'`); explicit selection with
  missing dependency fails, never skips. Base CI remains compiler-free; the native gate is
  separately mandatory for M3 completion. Update `tests/unit/test_ci_script.py` assertions to
  preserve no implicit marker override by scripts/ci.sh.
- [x] Acceptance: `uv sync --frozen --extra alignment`, then
  `uv run pytest -m native_alignment tests/integration/test_eflomal_native.py -q`.
  If upstream build/API cannot meet the interface, record concrete evidence and stop this
  adapter package; no substitution with mocks. Senior decides a separately versioned local
  invocation wrapper or an ADR amendment before native implementation continues.

### WP3.1 — Alignment domain/schema contracts

**Depends:** accepted ADR-0011. **Size:** one session.
**Own:** `src/langpipe/domain/models/alignment.py`; modify `domain/enums.py`, `domain/ids.py`,
`domain/errors.py`, `domain/models/__init__.py`, `schemas/registry.py`;
create `tests/unit/domain/test_models_alignment.py`, `tests/unit/domain/test_alignment_errors.py`,
`schemas/segment-alignment.v1.schema.json`, `schemas/token-alignment-edge.v1.schema.json`.
**Produces:** models/enums/errors exactly §5.1–5.2, schema registry exports.

- [x] Red tests: `test_nonempty_distinct_members`, `test_score_finite_nullable`,
  `test_direction_symmetrization_matrix`, `test_approval_requires_basis_and_predecessor`,
  `test_alignment_status_cannot_validate_translation`, `test_roundtrip_and_extra_forbidden`,
  `test_alignment_error_never_echoes_payload`. Include invalid prefix, UTC and nested mutation
  defensive-copy behavior at repository boundary in WP3.3.
- [x] Add models and schema generation without changing existing model semantics. Regenerate
  existing schemas only if additive enum references actually change their rendered content.
- [x] Acceptance: `uv run pytest tests/unit/domain tests/unit/schemas -q`;
  `uv run python -m langpipe.schemas generate`; `uv run python -m langpipe.schemas check`.

### WP3.2 — PostgreSQL schema/migration and low-level guards

**Depends:** WP3.1. **Size:** one to two sessions; schema and guard test gate together.
**Own:** `migrations/versions/0003_m3_alignment.py`, modify `storage/db/tables.py`,
`tests/fixtures/db.py`, `tests/integration/test_migrations.py`,
`tests/integration/test_append_only_triggers.py`, `tests/unit/storage/test_migration_enum_literals.py`;
create `tests/integration/test_alignment_constraints.py`.
**Produces:** §5.3 tables, indexes, check/deferred triggers and safe downgrade.

- [x] Red tests: `test_m3_empty_roundtrip`, `test_m3_downgrade_refuses_any_alignment_data`,
  `test_m3_registry_reference_blocks_downgrade`, `test_m3_metadata_parity`,
  `test_member_update_delete_rejected`, `test_empty_group_commit_rejected`,
  `test_noncontiguous_positions_rejected`, `test_wrong_language_or_run_rejected`,
  `test_edge_wrong_group_endpoint_rejected`. Exercise direct SQL bypass of repositories.
- [x] SQL exception mapping follows existing SQLSTATE/constraint-name conventions. Triggers
  validate at transaction end so a parent can precede members. No cascade delete path bypasses
  append-only rules. Keep 0001/0002 immutable; expand literals only in 0003.
- [x] Acceptance: `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest tests/integration/test_migrations.py
  tests/integration/test_append_only_triggers.py tests/integration/test_alignment_constraints.py
  tests/unit/storage/test_migration_enum_literals.py -q` (one shell command, sequential DB use).

### WP3.3 — Repository parity and alignment lock primitives

**Depends:** WP3.2. **Size:** two focused sessions: memory then PostgreSQL/shared contracts.
**Own:** modify `storage/repository.py`, `storage/memory.py`, `storage/db/repository.py`,
`tests/contract/builders.py`; create `tests/contract/test_alignment_repository_contract.py`,
`tests/integration/test_alignment_concurrency.py`.
**Consumes/produces:** exact additions in §5.3; registry and ancestry queries support both entities.

- [x] Red shared tests: `test_write_requires_transaction`, `test_group_roundtrip_order`,
  `test_duplicate_natural_key_rejected`, `test_foreign_member_and_edge_rejected`,
  `test_rollback_removes_rows_registry_indexes_and_members`, `test_defensive_copies`,
  `test_member_endpoint_ancestry_exact`, `test_competing_runs_coexist`.
- [x] Add memory indexes for group/run/token endpoints and uniqueness; participate in the
  existing rollback snapshot. Avoid corpus-size repeated whole-state scans. Preserve all M2
  indexing and `get_or_create_form` behavior.
- [x] Add session advisory request locks and sorted source row locks with bounded acquisition.
  Test `test_same_request_lock_serializes`, `test_lock_released_after_failure`,
  `test_revocation_and_commit_serialized` with independent PostgreSQL connections/barriers.
  Tests prove real interleavings, not sequential mocks. Memory equivalents are scoped locks;
  existing repository doesn't become a general concurrent transaction engine.
- [x] Acceptance: `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest
  tests/contract/test_alignment_repository_contract.py tests/contract/test_repository_contract.py
  tests/integration/test_alignment_concurrency.py -q`.

### WP3.4 — Opt-in sentence TSV extraction for actual golden 1:n

**Depends:** ADR acceptance; independent of storage packages. **Size:** one session.
**Own:** `src/langpipe/extraction/tsv_sentences.py`, modify `extraction/registry.py`;
create `tests/unit/extraction/test_tsv_sentences.py`.
**Produces:** `TsvSentencesExtractor` (`tsv_sentences@0.1.0`), existing Extractor signature
`extract(data: bytes, ctx: ExtractionContext) -> ExtractionOutput`.

- [x] Red tests: `test_txt14_one_qaa_two_por_units`, `test_cell_offsets_and_locator_preserved`,
  `test_unsplit_qaa_and_wesa_ra`, `test_delimiter_runs_and_final_fragment`,
  `test_ragged_input_same_failure`, `test_default_tsv_unchanged`. Exact por units are
  `O pajé vê a canoa.` and `Ele sorri.`; no unit is inferred from a translated paraphrase.
- [x] Compose existing TSV parser, preserve metadata/stats/empty_units, assign contiguous
  output ordinals after splitting. Only por split rule is enabled in this initial version;
  rule lives in this named opt-in source adapter, not generic alignment code. Offsets preserve
  direct cell slices; no new canonical persisted entity or modified M2 extraction default.
- [x] Acceptance: `uv run pytest tests/unit/extraction/test_tsv_sentences.py
  tests/unit/extraction/test_tsv.py tests/service/test_extraction_service.py -q`.

### WP3.5 — Run selection and policy preflight

**Depends:** WP3.1,3.3. **Size:** one session.
**Own:** `alignment/base.py`, `alignment/selection.py`, `alignment/governance.py`;
create `tests/unit/alignment/test_selection.py`, `tests/service/test_alignment_governance.py`.
**Produces:** DTOs §5.2;
`resolve_alignment_side(ctx, source_ref: str, language: str | None,
normalization_run_id: str | None, tokenization_run_id: str | None) -> AlignmentSide`;
`ensure_alignment_allowed(ctx, input_ids: Sequence[str]) -> tuple[str, ...]` (sorted sources).

- [x] Red tests: `test_unique_run_default`, `test_ambiguous_run_requires_pin`,
  `test_no_mixed_generations`, `test_side_language_must_be_explicit_if_ambiguous`,
  `test_token_run_must_consume_selected_normalization`, `test_bilingual_same_source_allowed`.
  Resolve source→extraction runs→normalization runs→tokenization runs through existing
  list_runs_with_input and run I/O; normalization inputs are segments rather than the source.
  No new implicit list-all interface.
- [x] Policy tests: deny either side, review_required, exclude, archive_only, revoked,
  missing ancestry; assert no adapter call/run/semantic rows, one existing denial audit event.
  `test_reuse_rechecks_both_sources`, `test_shared_form_cannot_launder_alignment` and
  `test_alignment_inputs_deny_direct_training` use effective_decision and full ancestry.
- [x] Acceptance: `uv run pytest tests/unit/alignment/test_selection.py
  tests/service/test_alignment_governance.py tests/service/test_text_governance.py -q`.

### WP3.6 — Canonical segment aligner and registry

**Depends:** WP3.5. **Size:** one session.
**Own:** `alignment/canonical.py`, `alignment/registry.py`;
create `tests/unit/alignment/test_canonical.py`, `tests/unit/alignment/test_registry.py`.
**Produces:** CanonicalLocatorAligner/SEGMENT_ALIGNERS, exact SegmentAligner signature §5.2.

- [x] Red matrix tests: 1:1, 1:2, 2:2, 2:3 overlap-connected bridge, verse pieces,
  duplicate edition book, malformed/missing locator, unrelated namespace, suffix `3a`
  versus `3`, published label mismatch, incompatible versification, headings/notes excluded.
  `test_bridge_partial_coverage_is_candidate` prevents structural overclaim.
- [x] Use indexed keys and connected components, stable document order, no sentence/text
  similarity or Cartesian expansion. Group key is canonical hash of ordered member IDs,
  mode/method and namespace metadata; diagnostic reasons use fixed enums.
- [x] Registry tests prove version pinning, latest numeric adapter resolution and fixed unknown
  method diagnostic without changing VersionedRegistry's existing M2 exceptions.
- [x] Acceptance: `uv run pytest tests/unit/alignment/test_canonical.py
  tests/unit/alignment/test_registry.py -q`.

### WP3.7 — Atomic Stage 4 service and governed approval import

**Depends:** WP3.3,3.5,3.6. **Size:** two sessions, matching then approval import.
**Own:** `alignment/segment_service.py`, `alignment/report.py`;
create `tests/service/test_segment_alignment_service.py`,
`tests/service/test_alignment_authorization.py`.
**Produces:** SegmentAlignmentService/summary §5.2; additional explicit method
`import_disposition(predecessor_id: str, basis_artifact_id: str,
status: Literal["approved", "rejected"]) -> SegmentAlignmentSummary`.

- [x] Red tests: `test_complete_group_run_io_and_lineage`, `test_zero_matches_report_has_sources`,
  `test_group_failure_rolls_back_all_outputs`, `test_rerun_stable_ids_and_counts`,
  `test_orientation_changes_key`, `test_configuration_changes_preserve_history`.
- [x] Approval basis artifact schema `alignment-authorization.v1`: predecessor ID, exact
  member IDs, actor, disposition, authorization basis kind (authorized_reviewer/editorial_decision),
  issuer authority reference, occurred_at, schema name/version. Basis must be registered with
  valid lineage, succeeded run, and a producing tool on an operator-configured trusted local
  importer allowlist. Empty allowlist is default. This path consumes existing trusted artifacts;
  M3 does not create a command that self-signs approvals or claim full review infrastructure.
- [x] Test untrusted producer, actor mismatch, denied HUMAN_REVIEW, revoked ancestor, changed
  members and failed producing run; all fail `authorization_invalid`/PolicyDenied before run.
  Success creates immutable successor and basis/predecessor input I/O + lineage. Duplicate
  disposition reuses its run. Rejection successor excludes its predecessor from active Stage 5
  selection; multiple conflicting active successors fail preflight, never pick latest.
- [x] Acceptance: `uv run pytest tests/service/test_segment_alignment_service.py
  tests/service/test_alignment_authorization.py -q`.

### WP3.8 — Token adapter, native index parser and symmetrization

**Depends:** WP3.0 native gate, WP3.5. **Size:** two sessions.
**Own:** `alignment/adapters/__init__.py`, `alignment/adapters/eflomal.py`,
`alignment/symmetrization.py`, token registry portion of `alignment/registry.py`,
`tests/fixtures/alignment.py`; create `tests/unit/alignment/test_eflomal_adapter.py`,
`tests/unit/alignment/test_symmetrization.py`; extend WP3.0 native tests.
**Produces:** EflomalAligner `eflomal@0.1.0`, TOKEN_ALIGNERS and TokenAligner interface.

- [x] Red tests: `test_batch_not_per_group_training`, `test_flatten_occurrences_not_forms`,
  `test_reverse_indices_not_swapped`, `test_empty_output_line_preserved`,
  `test_out_of_range_bool_negative_and_extra_lines_rejected`,
  `test_duplicate_links_deduplicated`, `test_no_null_tokens_created`,
  `test_scores_remain_null`, `test_intersection_union_exact`,
  `test_timeout_and_stderr_redacted`, `test_private_temp_files_cleanup`,
  `test_mock_never_registered`, `test_missing_native_never_falls_back`.
- [x] Adapter handles already-tokenized surfaces; reject embedded whitespace/control characters
  with invalid_adapter_output, not retokenization. Empty sides never sent natively. Both output
  files have exactly one line per nonempty group; parser preserves blank lines and validates
  every index against that group's arrays. No arbitrary subprocess shell interpolation.
- [x] Native acceptance extends batch to uneven n:m groups and repeated surfaces; assert valid
  occurrence mapping, not fixed linguistic link matrices. Adapter metadata includes observed
  native identity and randomness limitations from spike.
- [x] Acceptance: `uv run pytest tests/unit/alignment/test_eflomal_adapter.py
  tests/unit/alignment/test_symmetrization.py -q`; separately
  `uv run pytest -m native_alignment tests/integration/test_eflomal_native.py -q`.

### WP3.9 — Atomic Stage 5 service, reports and concurrent reuse

**Depends:** WP3.7,3.8. **Size:** two sessions including PostgreSQL concurrency verification.
**Own:** `alignment/token_service.py`, Stage 5 section of `alignment/report.py`;
create `tests/service/test_token_alignment_service.py`, `tests/service/test_alignment_reports.py`;
extend `tests/integration/test_alignment_concurrency.py`.
**Produces:** TokenAlignmentService/summary §5.2.

- [x] Red tests: `test_only_structural_or_active_approved_inputs`,
  `test_rejected_successor_excludes_predecessor`, `test_pinned_token_generations`,
  `test_n_m_index_mapping_exact_ids`, `test_forward_reverse_symmetrized_rows`,
  `test_unaligned_complements_per_direction`, `test_empty_side_report_no_forced_links`,
  `test_late_batch_failure_no_edges`, `test_artifact_store_failure_no_rows`,
  `test_retry_failed_run_new_id_successful_rerun_reused`, `test_two_requests_one_success`.
- [x] Reports are canonical JSON, schema_name `segment-alignment-report` or
  `token-alignment-report`, schema_version=1, ArtifactKind.ALIGNMENT_FILE. Include run/selected
  run IDs, methods/backend metadata, group/member/token ID arrays, index pairs, fixed reasons,
  counts, nullable scores, unaligned ID arrays. Never text, title, path, arbitrary locator ref
  or native stderr. Metadata schema allowlists fields and validates types recursively.
- [x] Artifact access class is most restrictive source access. Redaction tests inject payloads
  into adapter failures/options/native stderr and verify stdout/stderr/logs/report bytes.
  `test_revocation_during_native_compute_blocks_commit` uses a barrier and separate connection.
- [x] Acceptance: `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest
  tests/service/test_token_alignment_service.py tests/service/test_alignment_reports.py
  tests/service/test_alignment_governance.py tests/integration/test_alignment_concurrency.py -q`.

### WP3.10 — CLI alignment commands

**Depends:** WP3.7,3.9. **Size:** one session.
**Own:** `src/langpipe/cli/alignment.py`, modify `cli/app.py`;
create `tests/unit/cli/test_cli_alignment.py`, `tests/integration/test_cli_alignment_postgres.py`.
**Produces:** `align_app`, registered under `langpipe align`.

```sh
uv run langpipe align segments SOURCE_A_REF SOURCE_B_REF --method canonical_locator \
  --source-language mzr --target-language por --source-normalization-run RUN_A \
  --target-normalization-run RUN_B --namespace scripture --versification-id DECLARED_ID
uv run langpipe align tokens SEGMENT_ALIGNMENT_RUN_ID --method eflomal \
  --source-tokenization-run TOK_RUN_A --target-tokenization-run TOK_RUN_B \
  --symmetrization intersection
```

- [x] Options normalizations/tokenizations/languages may be omitted only under unique selection;
  token defaults derive from recorded selected normalization sides. `ALIGNMENT_RUN_REF` means
  an exact succeeded Stage 4 run ID, not arbitrary source key. Namespace is required;
  versification-id is required for Scripture. Config extras: --threads, --timeout-seconds,
  --seed (unsupported seed fails explicitly). No --approve or --force-policy flag.
- [x] Red tests: command help, default/pinned/versioned method, bilingual same source,
  ambiguity exit 11, governance exit 3, malformed/native error exit 12 and no content leaks.
  Success prints only run_id, report_id, counts, reused as key=value lines, like M2.
- [x] Acceptance: `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest
  tests/unit/cli/test_cli_alignment.py tests/integration/test_cli_alignment_postgres.py -q`.

### WP3.11 — Gold matrices, metric harness and evaluation artifact

**Depends:** WP3.9. **Size:** one session.
**Own:** `evaluation/__init__.py`, `evaluation/alignment.py`, `evaluation/service.py`,
`schemas/alignment-gold.v1.schema.json`; modify `schemas/registry.py`;
create `tests/unit/evaluation/test_alignment_metrics.py`,
`tests/service/test_alignment_benchmark.py`, `tests/fixtures/alignment/gold.v1.json`.
**Produces:**
`evaluate_links(predicted: set[tuple[int, int]], gold: GoldAlignment) -> AlignmentMetrics`;
GoldAlignment (frozen DomainModel, SCHEMA_NAME="alignment-gold")/BenchmarkService §5.2. Export `alignment-gold.v1.schema.json` via schema registry.

- [x] Gold schema records group ID or stable fixture locator selector plus normalization/tokenizer
  versions, ordered token occurrence selectors, sure/possible links, annotated null-source/null-
  target indices, split and annotation authority. ID-independent fixture selectors bind to
  occurrences before evaluation; exact array/version mismatch fails invalid_gold. Real gold
  must be separately registered as a governed input Artifact, never compiled into production.
- [x] Hand-calculated red test: S={(0,0),(1,1)}, P=S∪{(2,2)}, A={(0,0),(2,2),(2,1)};
  precision=2/3, recall=1/2, F1=4/7, AER=2/5. Add perfect sure-set, duplicates, empty A,
  empty S, both empty, impossible P/S, out-of-bounds, annotated-null confusion matrix,
  micro aggregate unequal group sizes and version mismatch.
- [x] Null precision/recall compare predicted complement to explicitly annotated null tokens;
  excluded/unannotated tokens are not assumed null. Report coverage/undefined reason. F1=0
  when defined precision+recall=0, null if either input undefined. Aggregate only defined counts,
  disclose groups contributing to each metric. Frozen split identity cannot be changed silently.
- [x] Evaluation preflight applies EVALUATION to gold and both predicted ancestries; no gold
  access from native adapter/priors. Persist benchmark report + lineage in one atomic run;
  report labels protocol `transductive_unsupervised`, not strict held-out inductive evaluation.
  No accuracy claim on unannotated mzr ScriptureEarth and no arbitrary promotion threshold.
- [x] Acceptance: `uv run pytest tests/unit/evaluation/test_alignment_metrics.py
  tests/service/test_alignment_benchmark.py -q`; `uv run python -m langpipe.schemas check`.

### WP3.12 — Golden M3 exact graph and null evidence

**Depends:** WP3.4,3.7,3.9,3.11. **Size:** one session.
**Own:** create `tests/golden/test_golden_m3.py`, `tests/golden/normalize_m3.py`,
`tests/golden/fixture/alignment/null-token.tsv`,
`tests/golden/fixture/alignment/null-token-manifest.yaml`,
`tests/golden/fixture/alignment/gold.v1.json`,
`tests/golden/expected/m3/segment_alignments.json`, `token_edges.json`, `reports.json`,
`lineage.json`, `benchmark.json` (last four under same expected/m3 directory);
modify only descriptions in `tests/golden/fixture/PHENOMENA.md` and expected/README.md;
narrow prerequisite corrections: `src/langpipe/alignment/segment_service.py` and
`tests/service/test_segment_alignment_service.py` (ADR-0011 §4 permits bilingual same-source
selection with a shared normalization run), and `tests/golden/test_golden_m2.py`
(acknowledging the opt-in `tsv_sentences@0.1.0` extractor already registered in WP3.4).
**Produces:** separate normalized M3 snapshots; M1/M2 snapshots/corpus bytes unchanged.

- [x] Drive registered source 01 through opt-in tsv_sentences extraction, ordinary normalization/
  tokenization, canonical alignment of qaa and por sides, test-injected explicit mock matrix,
  persistence and benchmark on both repo/ctx backends. Never compare exact statistical output
  to these mock snapshots.
- [x] `test_txt14_is_actual_one_to_two_members` asserts exactly one qaa and two por member IDs,
  not a string sentence count or pairwise duplicate groups. `test_txt13_no_suffix_token_fabricated`
  proves `wesa-ra` stays one occurrence, no source token `-ra` exists, and an explicit mock
  whole-token null case records the wesa-ra ID unaligned without a NULL edge. This case is an
  infrastructure challenge, not a linguistically justified claim that the whole word is null.
- [x] Standalone null fixture bytes: header `ref\tqaa\tpor`, row `NULL.1\tfoo -ra\tbar`.
  Synthetic permission-safe manifest uses direct policy and declared qaa/por languages.
  M2 `whitespace_punct@0.1.0` yields source tokens `foo`, `-`, `ra` and target `bar`:
  a leading hyphen is punctuation, whereas the internal hyphen in `wesa-ra` is retained.
  Gold/mock links are exactly source index 0→target index 0. The test
  `test_standalone_ra_spelling_preserves_two_unaligned_occurrences` asserts source indices 1
  and 2 remain unaligned, with their separate punctuation/word occurrence IDs in the report.
  It does not assert a nonexistent single `-ra` token. Snapshot exact token identities and
  identify this as a synthetic null challenge, not target-language morphology evidence.
- [x] Add rerun count/ID stability, bidirectional source impact, reversed lineage negative
  assertion, missing/trailing token handling, distill_only DIRECT_TRAINING denial for group,
  edges and report, and revocation blocks reused run. No exporter exists or is implied.
- [x] Expected snapshots normalize opaque IDs by side/group/member/token ordinal labels,
  like M1/M2; hash/run keys normalized only in snapshots. Correctness tests compare real keys.
- [x] Acceptance: `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest tests/golden -q`;
  `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest tests/service/test_segment_alignment_service.py
  tests/service/test_alignment_authorization.py tests/service/test_alignment_governance.py -q`;
  `git diff --exit-code -- tests/golden/expected/m1 tests/golden/expected/m2
  tests/golden/fixture/sources`.

### WP3.13 — ScriptureEarth mzr–por governed end-to-end verification

**Depends:** WP3.0,3.9,3.10; independent operator-input gate.
**Size:** two sessions: synthetic paired-USFM parity, then local authorized realdata.
**Own:** create `tests/integration/test_scriptureearth_parallel.py`,
`tests/integration/test_paired_usfm_synthetic.py`,
`tests/integration/expected/scriptureearth_parallel_counts.json`;
modify `docs/languages/mzr.md` only with operating instructions/explicit uncertainties.
**Produces:** required local dual-source test covering registration→ingest→extract→normalize→
 tokenize→segment align→native token align→stored report on memory and separate PostgreSQL runs.

- [x] Synthetic paired files cover bridges, note-separated pieces, absent verses, alternate labels,
  verse-free XXF and incompatible versification. Native synthetic suite remains native-marked;
  compiler-free structural suite uses the test mock explicitly and never calls it eflomal.
- [ ] Operator provides LANGPIPE_MZR_SE_DIR, LANGPIPE_MZR_SE_MANIFEST and new
  LANGPIPE_POR_SE_DIR, LANGPIPE_POR_SE_MANIFEST. Both manifests require independent rights/
  provenance, named non-placeholder authority, permitted local INGEST/EXTRACT/NORMALIZE/ALIGN,
  outward denials and matching declared versification. No downloads or authorization fabricated
  by junior. Both packages stay gitignored/untracked; test refuses absent inputs, never skips.
- [ ] `test_pair_hashes_unchanged`, `test_common_coordinate_components_independent_rescan`,
  `test_absent_coordinates_reported`, `test_native_edges_map_to_selected_occurrences`,
  `test_ancestry_reaches_both_sources`, `test_pair_distill_only_not_trainable`,
  `test_native_failure_keeps_segment_evidence`, `test_rerun_reuses_both_alignment_runs`,
  `test_no_surface_leaks` and `test_parallel_postgres_persistence` are mandatory.
- [ ] Coordinate oracle independently expands numeric bridges and filters verse-only locators;
  do not derive expected counts with CanonicalLocatorAligner. Count overlap/missing/partial
  coverage and book inventory for each declared edition. Do not reuse 5,594 or mzr marker
  counts as paired alignment counts. Metadata-only expected JSON records two package hash
  inventories, edition/versification, reviewed_by and observed common/unmatched/group counts;
  missing review fails. Senior signs observed counts after independent rescan, not self-generated
  passing snapshots. No guessed Portuguese edition or total.
- [ ] Use function-scoped fixtures compatible with existing ctx/pg_repository. A single local
  pipeline build per test, no full corpus Cartesian backend parametrization. PostgreSQL case
  is separate. Preserve existing realdata report/JUnit redaction in integration/conftest.py;
  do not add unredacted assertions containing surfaces/paths/native output.
- [ ] Native corpus can be a deterministic metadata-selected subset (book/chapter keys and
  documented budget) for PostgreSQL smoke, but the memory structural pass covers full paired
  coordinate intersection. Persist selection in config; assert nonempty native batch and
  bounded valid edges, not guessed word accuracy. A full native local batch is recorded as a
  completion gate with options/runtime; no mock may satisfy it.
- [ ] Acceptance, after operator input setup:
  `LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -m realdata
  tests/integration/test_scriptureearth_parallel.py -q`.
  Missing por/rights/native backend keeps this gate unsatisfied; synthetic success is separate.
  Actual mzr–por precision/recall/AER remain unavailable until an independently governed gold
  annotation set exists; this is explicitly a structural/integrity baseline, not quality proof.

**Operator Action Checklist to satisfy WP3.13 Realdata Gate:**
1. Accept or reject ADR-0012 (`docs/adr/0012-ebible-acquisition-host.md`) authorizing eBible as second acquisition host.
2. Supply authorized Portuguese Scripture USFM directory (`LANGPIPE_POR_SE_DIR`) and manifest (`LANGPIPE_POR_SE_MANIFEST`), citing real edition (`porbrbsl` or `porbr2018`) and verified license.
3. Supply rights decision and policy record under `GOVERNANCE.md` (no automated self-licensing).
4. Decide versification mapping strategy: either formally bound the dual-source scope to the 6 coordinate-compatible books (ACT, GEN, JHN, LUK, JAS, RUT), or provide an operator-judged chapter/verse mapping for EXO (20 vs 40 ch) and NEH (7 vs 13 ch).
5. Conduct independent rescan and supply human reviewer signature (`reviewed_by`) in `tests/integration/expected/scriptureearth_parallel_counts.json`.


### WP3.14 — Contract docs and complete milestone gate

**Depends:** all prior packages and senior acceptance evidence. **Size:** one session.
**Own:** modify `docs/DEVELOPMENT.md`, `docs/DOMAIN-MODEL.md`, `docs/PIPELINE-CONTRACTS.md`,
`docs/SCHEMAS.md`, `docs/EVALUATION.md`, `docs/GOLDEN-FIXTURE.md`, `docs/adr/README.md`,
`docs/README.md`, `docs/implementation/M3-PLAN.md`, `tests/unit/test_ci_script.py`;
update ADR-0011 status only when owner records acceptance.

- [x] Document pairwise n:m members, operational disposition exception, structural Stage 5
  eligibility, nullable raw scores, index direction, exact lineage, run pinning, opt-in sentence
  extraction, mock/native boundary, migration refusal and realdata requirements.
- [x] GOLDEN-FIXTURE/PHENOMENA distinguish whole-token null infrastructure from suffix-level
  interpretation; preserve M5 ownership. Evaluation docs name transductive protocol and
  undefined denominators. Record unresolved por/gold/native gates honestly.
- [x] Do not claim training firewall implementation, target-language validation, deterministic
  independent native sampling or M4 review completion.
- [ ] Acceptance: `uv run ruff check .`; `uv run ruff format --check .`;
  `uv run mypy src`; `uv run python -m langpipe.schemas check`; `bash scripts/ci.sh`;
  then explicit native and realdata commands from WP3.0/3.13, sequentially.
  Default suite must preserve all existing assertions, zero required-PostgreSQL skips.
  (Compiler-free CI and native test suites pass; full acceptance gate remains open while
  WP3.13 dual-source realdata gate awaits operator inputs).

## 7. Dependency and senior review order

1. WP3.0 native spike and ADR owner review establish gates. After ADR acceptance,
   WP3.1→3.2→3.3 establish persistence. WP3.4 is the independent source-view extension.
2. WP3.5→3.6→3.7 establish segment evidence. WP3.8 after native spike establishes token adapter.
3. WP3.9→3.10/3.11→3.12 establish end-to-end synthetic evidence and evaluation.
4. WP3.13 runs only with governed dual-source inputs; WP3.14 closes documented acceptance.

Senior review for every package checks exact file scope, tests-first evidence, both repository
semantics where applicable, forbidden observation mutations, source ancestry including empty
runs, redaction, natural uniqueness, n:m preservation and no linguistic promotion. Failed
acceptance stops dependent packages; unrelated accepted packages may continue. Each package
is rejectable independently; no blanket "all tests pass" substitutes for a named contract.

## 8. Completion evidence and remaining uncertainty

M3 completion requires ADR acceptance, schema/migration forward/backward proof on PostgreSQL,
shared repository/graph/governance contracts, golden 1:2 membership and honest null coverage,
compiler-free gate, real native adapter gate, and authorized mzr–por full structural/native
verification with reviewed metadata expectations. No unexplained skip counts as evidence.

### Milestone 3 gate ledger (as of 2026-10-14)

1. **Architecture decision (ADR-0011)**: **Accepted** (2026-10-13). Persisted models, relational membership, operational evidence disposition, and local token adapter contracts confirmed.
2. **PostgreSQL schema & migrations (WP3.2)**: **PASSED**. Migration 0003 roundtrip (0001→0002→0003→0002→0003) verified on disposable test database; append-only triggers and populated downgrade refusal verified.
3. **Repository & parity contracts (WP3.3)**: **PASSED**. Shared repository contract verified across both MemoryRepository and PostgresRepository, including advisory request locking and sorted source locks.
4. **Sentence TSV extractor (WP3.4)**: **PASSED**. `tsv_sentences@0.1.0` splits only `por` column, retaining cell slice offsets and parent locators.
5. **Stage 4 canonical segment aligner (WP3.5–3.7)**: **PASSED**. Structural locator matching, bridge expansions, and governed disposition imports verified.
6. **Native eflomal spike & adapter (WP3.0, WP3.8)**: **PASSED**. eflomal 2.0.0 compiled, verified under Python 3.12; `EflomalAligner` subprocess isolation and temporary directory cleanup verified.
7. **Stage 5 token alignment & concurrency (WP3.9)**: **PASSED**. Symmetrization (`none`, `intersection`, `union`), nullable scores, unaligned occurrence IDs, and concurrent run serialization verified on PostgreSQL.
8. **CLI alignment commands (WP3.10)**: **PASSED**. Both `align segments` and `align tokens` commands verified on PostgreSQL with zero text surface leaks.
9. **Evaluation harness & gold schema (WP3.11)**: **PASSED**. `evaluate_links` micro-metrics (precision, recall, AER, F1, null precision/recall) and `alignment-gold.v1.schema.json` verified.
10. **Golden fixture M3 (WP3.12)**: **PASSED**. 1:2 membership, whole-token null challenge, and exact lineage verified against normalized M3 snapshots with M1/M2 regression tests intact.
11. **Synthetic paired-USFM parity (WP3.13 synthetic)**: **PASSED**. Bridge handling, note extraction, and versification checks pass.
12. **Compiler-free CI gate (`scripts/ci.sh`)**: **PASSED** (1,383 passed, zero skips, 2026-10-14).
13. **Native alignment gate (`pytest -m native_alignment`)**: **PASSED** (8 passed, 2026-10-14).
14. **Dual-source ScriptureEarth mzr–por realdata gate (WP3.13 realdata)**: **UNSATISFIED** (external-input gate). Fails safely with content-free diagnostics. ScriptureEarth does not distribute raw Portuguese USFM text; candidate open corpora (`porbrbsl` Public Domain, `porbr2018` CC BY 4.0) have been researched on eBible.org and require operator authorization, Exodus/Nehemiah versification reconciliation, and senior review signatures before realdata counts can be signed.
15. **Target-language gold evaluation gate**: **UNMEASURED**. No target-language gold annotation set exists for mzr–por; structural coordinate matching confirms pipeline integrity, not translation truth.
