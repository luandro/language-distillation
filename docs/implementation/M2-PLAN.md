# M2 Implementation Plan — Text Processing (Extraction, Normalization, Tokenization)

> **Superseded policy note (ADR-0025).** Any rule below that blocks processing or
> training because of a source's classification, licence, rights holder, or register is
> historical. Presence in the repository authorizes processing and training; licences
> and ownership are records, not gates.

Status: cross-reviewed; blocking decisions remain (see §13 Review log) · Author: senior architect pass · Date: 2026-10-12
Baseline: `main` at `3aaf102` (M1 complete: 415 tests, zero skips, PostgreSQL 16).

This plan is written for junior implementers. **Every name, field, enum value, file path, CLI flag and output line below is decided. Do not rename or "improve" them.** If something seems wrong or missing, stop and report it instead of inventing an alternative. M1 conventions (M1-PLAN §5) still apply unless this plan overrides them.

---

## 1. Scope

`DEVELOPMENT.md` § M2: *extractor interface, simple source adapters, normalization profile interface, tokenizer interface, Marúbo profile stub and idempotent run behavior.*

This plan delivers:

1. Stage 2 (Extraction): `Extractor` protocol and registry; `tsv`, `plain_lines` and `usfm` extractors; `ExtractionService`.
2. Stage 3 (Normalization and tokenization): `NormalizationProfile` with an offset map and `NormalizationEvent`s; `Tokenizer` protocol; registries keyed by `name@version`; `NormalizationService` and `TokenizationService`.
3. Language profiles: the generic `LanguageProfile` registry and the Marúbo (`mzr`) stub under `src/langpipe/languages/mzr/`.
4. A ScriptureEarth source adapter that turns a **locally acquired** package into a source manifest. Registration and ingestion stay on the M1 path.
5. CLI commands `extract`, `normalize`, `tokenize`, `profiles list` and `scriptureearth manifest`.
6. Golden M2 expectations, invariant tests, and an opt-in real-data integration test against ScriptureEarth Marúbo.

Out of scope: segment alignment (M3), lexical candidates (M4), IGT import and morphology (M5), audio and timing-file processing, Proskomma `.pkf` decoding, training exports, and network access from pipeline code.

---

## 2. Conflicts and gaps found (read before coding)

| # | Source | Gap / conflict | M2 handling |
|---|---|---|---|
| C1 | Request ("NormalizationTokenizationService updates segments") vs ADR-0009 §5 | Segments are append-only. DB triggers reject `UPDATE`, so normalization cannot fill `segment.normalized_text` in place. | **ADR-0010 (Proposed):** a normalization run writes a **new** `Segment` row per input segment. It copies `raw_text`, `locator`, `language`, `source_object_id` and `ordinal` verbatim, sets `normalized_text` and `normalization_profile`, and adds the edge `seg_norm --normalized_from--> seg_raw`. Uses existing columns, the existing `normalized_from` lineage kind and the existing `normalization_failed` status. **No segment schema change.** |
| C2 | `PIPELINE-CONTRACTS.md` Stage 3 lists normalization and tokenization as one stage; `ARCHITECTURE.md` says stages must not write through several semantic layers at once; `RunStage` has both `normalization` and `tokenization` | One run or two? | **Two runs.** Normalization writes normalized segments. Tokenization writes tokens and forms. `langpipe tokenize` drives both and reuses the normalization run through `run_key`. |
| C3 | Request: Marúbo clitic handling (`-ki`, `-ra`, `txipo`, `shovimakĩ`) vs `mzr.md` § Open items ("define tokenizer behavior around punctuation/clitics" is **OPEN**), § Morphology ("Do not pre-populate them as facts") and AGENTS invariant 9 | Splitting clitics in the tokenizer would hard-code unverified morphology into observations. | **The M2 tokenizer never splits words.** Word-internal hyphens and apostrophes stay inside the token, so `mabi-ki` is one token with one raw span. Clitic and suffix boundaries are M5 `MorphAnalysis` candidates. No clitic list is shipped. `txipo` and `shovimakĩ` are ordinary words to the tokenizer. Recorded in ADR-0010 and `mzr.md`. |
| C4 | Request: "character inventory verification" vs `mzr.md` ("verify character inventory" is OPEN) | No verified Marúbo inventory exists. | M2 ships the **mechanism**: an inventory file with `status: unverified` and report-only diagnostics, never rejection or rewriting. WP2.15 produces an *observed* inventory report from real data for human review. The junior MUST NOT type an inventory from memory. |
| C5 | ScriptureEarth data rights and community governance (`GOVERNANCE.md`, `mzr.md` § Religious corpus default) | License terms of the ScriptureEarth Marúbo text were not verified in this pass, and community authority has not been consulted. | **No ScriptureEarth bytes are committed to git**, not even an excerpt. Before local processing, record the rights holder and license/permission in `provenance.rights_holder`/`notes` and satisfy the C5 governance gate. The real-data test reads from a local directory (`LANGPIPE_MZR_SE_DIR`) under `var/` (gitignored). Policy must be operator-supplied, with a named authority and recorded permission for local processing; `distill_only`/`community` is a proposed template, not authorization (§WP2.12). No placeholder authority may unlock real-data processing. |
| C6 | Request: `.pkf` (Proskomma succinct) as the package format | No Python decoder exists. Decoding needs the Proskomma JS stack, which would be a new foundational dependency. | **M2 accepts USFM only.** `.pkf` is OPEN; adding Node/Proskomma needs an ADR. The adapter rejects a package that has no `*.usfm`/`*.sfm` files with `UnsupportedSource`. |
| C7 | Local corpus at `/tmp/mzr_usfm/` (9 files; user reports 5,594 verses) | Second review counted 5,389 `\v` markers: ACT 996, EXO 540, GEN 1,526, JAS 108, JHN 875, LUK 1,135, NEH 124, RUT 85, XXF 0. Marker counts are not expanded verse-range counts. XXF contains non-verse material. | Preserve all nine files, including XXF. An independent range expansion gives 5,435 numeric verse positions; distinct `(chapter, verse-label)` counts equal the 5,389 marker counts. Treat 5,594 as an unresolved discrepancy, not an acceptance constant. WP2.15 separately records verse-marker counts and distinct verse locators after independent senior review. No timing-file count was verified. |
| C8 | Golden fixture `04-igt/igt.txt` has media type `text/plain`, the same as `05-monolingual/text.txt` | Choosing an extractor by media type alone would line-split IGT, which is Stage 7 (M5). | The default extractor is chosen by **(source_type, media_type)** (§4.3). `igt` has no M2 extractor, so those objects are skipped and reported, not failed. |
| C9 | `ObservationRecorder.record_segments` / `record_tokens` each open their own transaction, and nested transactions are unsupported | A multi-object extraction would commit partial outputs if a later object fails. That breaks "failed stages must not leave partially valid semantic outputs". | WP2.8 adds `ObservationRecorder.unit_of_work()`. Inside it, `record_*` calls do not open a transaction and the caller's single transaction covers every write plus `RunRecorder.succeed`. |
| C10 | `PIPELINE-CONTRACTS.md` Stage 2 failure: "Emit extraction error artifact" vs M1 `RunRecorder.fail` (no outputs) | A failed run cannot carry an artifact today. | WP2.8 extends `RunRecorder.fail(run_id, error, artifact=None)`. The artifact, its run I/O and its lineage are written in the same transaction as the failure. |
| C11 | `TokenInput` (M1) has no normalized-surface or normalized-span fields, although the `TokenOccurrence` model and table do | Tokens cannot record normalized spans. | WP2.8 adds optional fields with defaults (backward compatible). |
| C12 | New artifact kinds needed | `ArtifactKind` values are check-constrained in migration 0001 (`test_migration_enum_literals`). | Migration `0002_m2_text_processing.py` widens the constraint. Regenerate `artifact.v1.schema.json` (additive enum; version stays v1). |

---

## 3. Decisions for M2

| # | Decision | Classification |
|---|---|---|
| E1 | Normalization produces derived Segment rows linked by `normalized_from` (C1). Two runs for Stage 3 (C2). | **ADR-0010 (Proposed)** |
| E2 | The tokenizer never splits words at hyphens, apostrophes or suspected clitics (C3). | **ADR-0010** + `mzr.md` edit |
| E3 | Registries are keyed by `name@version` (`VERSIONED_NAME`). A behavior change requires a version bump. Registries are import-time constants, not plugins. | Reversible |
| E4 | Extractors are pure: `bytes → ExtractionOutput`. Only `ExtractionService` reads bytes, and only from `ctx.raw_store` after hash verification. Extractors never touch the origin path, the repository or the network. | Reversible |
| E5 | One extraction run per source (inputs = the extracted source objects). One normalization run per extraction run. One tokenization run per normalization run. | Reversible |
| E6 | A segment whose normalization fails becomes a derived segment with `status=normalization_failed`, `normalized_text=None` and `normalization_profile=None`. It is not tokenized. The profile is recoverable from the run config. | Uses M1 model rules |
| E7 | Punctuation and number tokens are recorded as `TokenOccurrence`s **without** a Form. Only `word` tokens get a Form. The Form's `text` is the normalized surface, with case preserved, and its `orthography_profile` is the normalization profile's versioned name. | Reversible |
| E8 | `ExtractionService` requires `Operation.EXTRACT`. Normalization and tokenization services require `Operation.NORMALIZE`. Anything other than `allow` (including `review_required`) is a denial: one `policy_denied` audit event, no run, no rows (same pattern as M1 ingest, D13). A source with `status=revoked` is denied the same way. | Matches ADR-0007 |
| E9 | Real-data tests use pytest marker `realdata` and are deselected by default (`addopts` gains `-m "not realdata"`). When selected explicitly, a missing `LANGPIPE_MZR_SE_DIR` is a **failure, not a skip**, so the zero-skip CI rule holds. | Reversible |
| E10 | Reports (extraction/normalization/tokenization artifacts) contain IDs, counts, code-point offsets, marker names and `U+XXXX` labels only, never text, file names or TSV cell values. | M1 logging rule extended |

---

## 4. Target architecture

### 4.1 Data flow

```text
SourceObject (ingested, raw_blob verified)
   │  ExtractionService  [run: extraction, tool langpipe.extract]
   ▼
Segment(raw)  ──extracted_from──▶ SourceObject           + extraction_report artifact
   │  NormalizationService [run: normalization, tool langpipe.normalize]
   ▼
Segment(normalized | normalization_failed) ──normalized_from──▶ Segment(raw)   + normalization_report
   │  TokenizationService [run: tokenization, tool langpipe.tokenize]
   ▼
TokenOccurrence ──derived_from──▶ Segment(normalized)
Form (get_or_create by language+profile+text) ──derived_from──▶ Segment(normalized)       + tokenization_report
```

Raw text is never rewritten. `Segment(normalized).raw_text == Segment(raw).raw_text` holds byte for byte (a mandatory test).

### 4.2 Module layout (new and changed files only)

```text
docs/adr/0010-text-processing-derived-segments.md      # NEW (WP2.0)
migrations/versions/0002_m2_text_processing.py         # NEW (WP2.1)
src/langpipe/
  domain/enums.py                     # CHANGE: ArtifactKind += 4 values (WP2.1)
  domain/errors.py                    # CHANGE: 5 new errors (WP2.1)
  storage/repository.py               # CHANGE: 2 query methods (WP2.1)
  storage/memory.py                   # CHANGE (WP2.1)
  storage/db/repository.py            # CHANGE (WP2.1)
  storage/db/tables.py                # CHANGE: check-constraint literal list (WP2.1)
  text/__init__.py                    # NEW (WP2.2)
  text/registry.py                    # NEW: VersionedRegistry[T] (WP2.2)
  text/offsets.py                     # NEW: OffsetMap (WP2.2)
  extraction/__init__.py              # NEW
  extraction/base.py                  # NEW: Extractor, ExtractedUnit, ExtractionContext, ExtractionOutput (WP2.2)
  extraction/registry.py              # NEW: EXTRACTORS, default_extractor_for (WP2.2/2.3/2.4)
  extraction/tsv.py                   # NEW (WP2.3)
  extraction/plain_lines.py           # NEW (WP2.3)
  extraction/usfm.py                  # NEW (WP2.4)
  extraction/service.py               # NEW: ExtractionService (WP2.9)
  normalization/__init__.py           # NEW
  normalization/base.py               # NEW: NormalizationRule, NormalizationProfile, NormalizationEvent, NormalizationResult (WP2.2)
  normalization/rules.py              # NEW: nfc, whitespace (WP2.5)
  normalization/profiles.py           # NEW: unicode_nfc@1.0.0, default_text@0.1.0 + GENERIC_NORMALIZATION_PROFILES (WP2.5)
  normalization/service.py            # NEW: NormalizationService (WP2.10)
  tokenization/__init__.py            # NEW
  tokenization/base.py                # NEW: Tokenizer, TokenOutput, TokenKind (WP2.2)
  tokenization/whitespace_punct.py    # NEW (WP2.6)
  tokenization/registry.py            # NEW: GENERIC_TOKENIZERS (WP2.6); final TOKENIZERS lives in languages/base.py
  tokenization/service.py             # NEW: TokenizationService (WP2.10)
  languages/__init__.py               # NEW
  languages/base.py                   # NEW: LanguageProfile, LANGUAGE_PROFILES, profile_for (WP2.2/2.7)
  languages/inventory.py              # NEW: Inventory model + diagnostics (WP2.7)
  languages/mzr/__init__.py           # NEW (WP2.7)
  languages/mzr/profile.py            # NEW: marubo_standard@0.1.0, marubo_pilot@0.1.0, MZR_PROFILE (WP2.7)
  languages/mzr/inventory.yaml        # NEW: status: unverified (WP2.7; remains unverified throughout M2)
  segmentation/recorder.py            # CHANGE: unit_of_work, record_normalized_segments, TokenInput fields (WP2.8)
  ingestion/runs.py                   # CHANGE: fail(..., artifact=None) (WP2.8)
  ingestion/adapters/__init__.py      # NEW
  ingestion/adapters/scriptureearth.py# NEW: build_manifest (WP2.12)
  governance/lineage_policy.py        # NEW: effective_decision (WP2.11)
  cli/app.py                          # CHANGE: register commands (WP2.13)
  cli/text.py                         # NEW: extract/normalize/tokenize/profiles (WP2.13)
  cli/scriptureearth.py               # NEW (WP2.13)
tests/
  fixtures/text/qaa_sample.usfm       # NEW synthetic USFM (WP2.4)
  fixtures/text/README.md             # NEW: says every fixture here is synthetic `qaa`
  unit/text/test_registry.py, test_offsets.py
  unit/extraction/test_tsv.py, test_plain_lines.py, test_usfm.py, test_default_extractor.py
  unit/normalization/test_rules.py, test_profiles.py, test_normalization_properties.py
  unit/tokenization/test_whitespace_punct.py, test_tokenizer_properties.py
  unit/languages/test_mzr_profile.py, test_inventory.py, test_language_isolation.py
  unit/ingestion/test_scriptureearth_adapter.py
  unit/cli/test_cli_text.py, test_cli_scriptureearth.py
  unit/storage/test_migration_enum_literals.py        # CHANGE
  contract/test_repository_contract.py                # CHANGE
  service/test_observation_recorder.py                # CHANGE (new cases)
  service/test_extraction_service.py, test_normalization_service.py,
          test_tokenization_service.py, test_text_governance.py
  integration/test_migrations.py                      # CHANGE (0002 up/down)
  integration/test_cli_text_postgres.py
  integration/test_scriptureearth_marubo.py           # opt-in realdata (WP2.15)
  integration/expected/scriptureearth_mzr_counts.json # numbers only, committed after senior review
  golden/expected/m2/{runs,segments,tokens,forms,lineage,reports}.json
  golden/test_golden_m2.py
```

Rule: no module outside `src/langpipe/languages/mzr/` may contain the string `mzr`, `marubo` or `Marúbo`, except `languages/base.py` (one registry import line) and the CLI help text. `test_language_isolation.py` enforces this with a grep-style test (C3, AGENTS § Language-specific code).

### 4.3 Default extractor resolution

`extraction/registry.py`:

```python
EXTRACTORS: VersionedRegistry[Extractor]   # "tsv@0.1.0", "plain_lines@0.1.0", "usfm@0.1.0"

_DEFAULTS: Mapping[tuple[SourceType | None, str], str] = {
    (None, "text/tab-separated-values"): "tsv@0.1.0",
    (None, "text/x-usfm"): "usfm@0.1.0",
    (SourceType.MONOLINGUAL_TEXT, "text/plain"): "plain_lines@0.1.0",
    (SourceType.PARALLEL_TEXT, "text/plain"): "plain_lines@0.1.0",
    (SourceType.EDUCATIONAL_PUBLICATION, "text/plain"): "plain_lines@0.1.0",
    (SourceType.PUBLICATION, "text/plain"): "plain_lines@0.1.0",
}

def default_extractor_for(source_type: SourceType, media_type: str) -> str | None:
    # exact (source_type, media_type) first, then (None, media_type); else None
    # igt/audio/video/dictionary-with-text/plain → None (skipped, reported)
```

A CLI `--extractor NAME@VERSION` override applies to every object of the source, and it is **still refused** (`UnsupportedSource`) for `source_type=igt` in M2.

---

## 5. Global conventions (in addition to M1-PLAN §5)

- Extractors, normalization rules, tokenizers and language profiles are **pure and deterministic**: no I/O, no clock, no randomness, no repository, no logging of content. They are frozen dataclasses or classes with `ClassVar` name/version.
- Every registered component exposes `name: ClassVar[str]` and `version: ClassVar[str]`, and `versioned_name` = `f"{name}@{version}"`, which must validate as `VERSIONED_NAME`.
- **Any behavior change to a registered component requires a version bump** and a new registry entry. A golden test pins every M2 component's versioned name (`test_registered_component_versions_are_pinned`).
- Offsets are Unicode code points, half-open `[start, end)` (M1 D7).
- Language-specific behavior lives only in `languages/<iso>/`.
- Services take `AppContext` (like M1 ingestion). Pure components never do.
- Test markers: `integration` (PostgreSQL), plus new `realdata` (local ScriptureEarth package; never in default CI).

---

## 6. Work packages

Dependency graph and parallel groups:

```text
G1: WP2.0 (senior: ADR + docs), then WP2.1 (enums/errors/migration/repo queries)
G2: WP2.2 (interfaces, registries, OffsetMap)
G3: WP2.3 ‖ WP2.4 ‖ WP2.5 ‖ WP2.6        (disjoint files; need WP2.2)
G4: WP2.7 (needs WP2.5, WP2.6) ‖ WP2.8 (needs WP2.1)
G5: WP2.9 (needs WP2.3, WP2.4, WP2.8) ‖ WP2.11 (needs WP2.1)
G6: WP2.10 (needs WP2.7, WP2.8, WP2.9) ‖ WP2.12 (needs WP2.4)
G7: WP2.13 (needs WP2.9, WP2.10, WP2.12)
G8: WP2.14 golden ‖ WP2.15 ScriptureEarth real data (both need WP2.13)
G8b: WP2.17 InMemoryRepository internal indexing (resolves R3 unindexed bottleneck for large corpus)
G9: WP2.16 docs + CI
```

Lint/type gate for every WP: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`.

---

### WP2.0 — ADR-0010 and documentation alignment (senior-owned)

**Files:** `docs/adr/0010-text-processing-derived-segments.md` (status **Proposed**), `docs/adr/README.md`, `docs/PIPELINE-CONTRACTS.md` (Stage 2/3 clarifications only), `docs/languages/mzr.md`, `docs/README.md`.

ADR-0010 records E1, E2, E4, E5 and E6 with the alternatives that were rejected:
- *Update `segment.normalized_text` in place*: violates ADR-0009.
- *A separate `segment_normalization` table*: needs a new entity, a new prefix and a token FK change, which costs more than reusing existing columns.
- *Normalize during extraction*: writes two semantic layers in one stage.
- *Split clitics in the tokenizer*: invariant 9 and `mzr.md`.

`mzr.md` edits (append only; claims marked as working assumptions):
- § Open items: "tokenizer behavior around punctuation/clitics" becomes "M2 decision: no splitting (ADR-0010); clitic boundaries are M5 candidates". The item stays open for M5.
- New § "M2 text-processing profile": names `marubo_standard@0.1.0` and `marubo_pilot@0.1.0`, the inventory file path and its `unverified` status.
- New § "ScriptureEarth pilot corpus": USFM-only intake, `distill_only` default, the rights and authority check required before local processing; real corpus bytes never committed, timing files preserved but unprocessed.

**Acceptance:** the link check from M1 (every backtick path resolves); the orchestrator approves the ADR before WP2.8 merges.

**Do NOT:** edit `GOVERNANCE.md` vocabulary (M1 G1 is still pending governance-owner approval); mark the ADR Accepted.

---

### WP2.1 — Enums, errors, migration 0002, repository queries

**Files:** `domain/enums.py`, `domain/errors.py`, `storage/repository.py`, `storage/memory.py`, `storage/db/repository.py`, `storage/db/tables.py`, `migrations/versions/0002_m2_text_processing.py`, `schemas/artifact.v1.schema.json` (regenerated); tests `tests/unit/domain/test_enums.py`, `tests/unit/domain/test_errors.py`, `tests/unit/storage/test_migration_enum_literals.py`, `tests/contract/test_repository_contract.py`, `tests/integration/test_migrations.py`.

```python
class ArtifactKind(StrEnum):          # append; never reorder or reuse
    ...
    EXTRACTION_REPORT = "extraction_report"
    EXTRACTION_ERROR = "extraction_error"
    NORMALIZATION_REPORT = "normalization_report"
    TOKENIZATION_REPORT = "tokenization_report"

class UnsupportedSource(LangpipeError):  exit_code = 9   # __init__(self, reason: str)  reason ∈ fixed codes below
class SourceNotIngested(LangpipeError):  exit_code = 9   # __init__(self, source_id: str)
class ExtractionFailed(LangpipeError):   exit_code = 10  # __init__(self, code: str, source_object_id: str, line: int | None)
class NormalizationFailed(LangpipeError):exit_code = 10  # __init__(self, code: str)  (raised by rules; service converts to segment status)
class AmbiguousInput(LangpipeError):     exit_code = 11  # __init__(self, stage: RunStage, count: int)
```
Messages are fixed `key=value` strings of codes, IDs and integers only. `UnsupportedSource.reason` ∈ `{"no_extractor", "igt_not_in_m2", "pkf_not_supported", "no_usfm_files", "language_ambiguous"}`. `ExtractionFailed.code` ∈ `{"decode_error", "tsv_header_invalid", "tsv_language_column_unknown", "tsv_ragged_row", "usfm_missing_id", "usfm_verse_before_chapter", "usfm_unclosed_note", "usfm_bad_chapter", "usfm_bad_verse"}`.

Repository additions (both implementations, contract-tested on memory and PostgreSQL):
```python
def list_segments_for_run(self, run_id: str) -> list[Segment]: ...
    # ordered by (source_object_id, ordinal)
def list_runs_with_input(self, object_id: str, stage: RunStage, status: RunStatus | None = None) -> list[ProcessingRun]: ...
    # via processing_run_io role=input; ordered by (started_at, id)
```

Migration `0002`: drop and recreate the `artifact.kind` check constraint with the widened literal list. Downgrade restores the M1 list and **fails loudly** if rows with new kinds exist (no silent deletion). No table or column changes.

**Tests first:**
- `test_artifact_kind_values_are_append_only` (M1 values unchanged, in their M1 order)
- `test_new_errors_have_safe_messages` (no free text; each exit code as above)
- `test_migration_enum_literals_match_enums` (existing test; extended for 0002)
- contract: `test_list_segments_for_run_orders_by_object_then_ordinal`, `test_list_runs_with_input_filters_stage_and_status`
- integration: `test_migration_0002_upgrade_downgrade_roundtrip`, `test_downgrade_0002_refuses_when_new_artifact_kinds_exist`

**Acceptance:** `uv run alembic -x url="$LANGPIPE_TEST_DATABASE_URL" upgrade head && uv run alembic -x url="$LANGPIPE_TEST_DATABASE_URL" downgrade 0001 && uv run alembic -x url="$LANGPIPE_TEST_DATABASE_URL" upgrade head`; `uv run python -m langpipe.schemas check`.

**Do NOT:** add columns to `segment`/`token_occurrence`; add an `update_*` repository method; add a new ID prefix.

---

### WP2.2 — Text-processing interfaces, registries, offset map

**Files:** `text/__init__.py`, `text/registry.py`, `text/offsets.py`, `extraction/__init__.py`, `extraction/base.py`, `extraction/registry.py` (empty registry plus `default_extractor_for`), `normalization/__init__.py`, `normalization/base.py`, `tokenization/__init__.py`, `tokenization/base.py`, `languages/__init__.py`, `languages/base.py`; tests `tests/unit/text/test_registry.py`, `tests/unit/text/test_offsets.py`, `tests/unit/extraction/test_default_extractor.py`.

```python
# text/registry.py
class Versioned(Protocol):
    name: ClassVar[str]; version: ClassVar[str]
def versioned_name(c: type[Versioned] | Versioned) -> str          # validates VERSIONED_NAME else SchemaViolation
class VersionedRegistry[T: Versioned]:
    def __init__(self, items: Iterable[T]) -> None                   # duplicate versioned name → ValueError at import
    def get(self, ref: str) -> T                                      # "name@ver" exact; bare "name" → the single highest version (packaging-free semver tuple compare); unknown → UnsupportedSource("no_extractor")
    def names(self) -> list[str]                                      # sorted versioned names

# text/offsets.py
@dataclass(frozen=True)
class OffsetMap:
    """boundary[i] = raw code-point index of normalized boundary i; len == len(normalized)+1;
    0 <= boundary[i] <= len(raw); non-decreasing. Trimmed prefixes/suffixes need not be mapped.
    For identity only: boundary[0] == 0 and boundary[-1] == len(raw)."""
    boundary: tuple[int, ...]
    @classmethod
    def identity(cls, length: int) -> "OffsetMap"
    def raw_span(self, start: int, end: int) -> tuple[int, int]      # (boundary[start], boundary[end])
    def compose(self, inner: "OffsetMap") -> "OffsetMap"             # self maps mid→raw, inner maps new→mid ⇒ new→raw
    def validate(self, raw_len: int, norm_len: int) -> None          # raises SchemaViolation

# extraction/base.py
@dataclass(frozen=True)
class ExtractionContext:
    source_id: str; source_object_id: str; source_type: SourceType; media_type: str
    source_languages: tuple[str, ...]; language: str | None          # explicit --language override
@dataclass(frozen=True)
class ExtractedUnit:
    ordinal: int; language: str; locator: Mapping[str, str | int]; raw_text: str   # raw_text non-empty
@dataclass(frozen=True)
class ExtractionOutput:
    units: tuple[ExtractedUnit, ...]          # ordinals 0..n-1 contiguous, document order
    stats: Mapping[str, int]                  # counters only; snake_case or unknown_marker:<marker>
    empty_units: tuple[Mapping[str, str | int], ...]   # locators of structurally present but empty units (e.g. omitted verse)
class Extractor(Versioned, Protocol):
    def extract(self, data: bytes, ctx: ExtractionContext) -> ExtractionOutput: ...  # ExtractionFailed on malformed input

# normalization/base.py
@dataclass(frozen=True)
class NormalizationEvent:
    rule: str                     # rule name, e.g. "nfc", "whitespace"
    raw_start: int; raw_end: int  # span in the raw text
    norm_start: int; norm_end: int  # span in the normalized text
@dataclass(frozen=True)
class RuleOutput:
    text: str; offsets: OffsetMap; events: tuple[NormalizationEvent, ...]   # events in this rule's input/output coordinates
    diagnostics: Mapping[str, int]           # required, {} when none; chain sums matching counters
class NormalizationRule(Protocol):
    name: ClassVar[str]
    def apply(self, text: str) -> RuleOutput: ...       # NormalizationFailed(code) if the input cannot be normalized
@dataclass(frozen=True)
class NormalizationResult:
    raw: str; normalized: str; offsets: OffsetMap; events: tuple[NormalizationEvent, ...]   # events in raw/final coordinates
    diagnostics: Mapping[str, int]       # e.g. {"char_outside_inventory:U+00E7": 3}; report-only
class NormalizationProfile(Versioned, Protocol):
    rules: ClassVar[tuple[NormalizationRule, ...]]
    def normalize(self, raw: str) -> NormalizationResult: ...

# tokenization/base.py
class TokenKind(StrEnum): WORD = "word"; NUMBER = "number"; PUNCT = "punct"
@dataclass(frozen=True)
class TokenOutput:
    ordinal: int; kind: TokenKind; norm_start: int; norm_end: int; surface: str   # surface == normalized[norm_start:norm_end]
class Tokenizer(Versioned, Protocol):
    def tokenize(self, normalized: str) -> tuple[TokenOutput, ...]: ...         # pure; never sees raw text

# languages/base.py
@dataclass(frozen=True)
class LanguageProfile:
    language: str                 # ISO 639-3
    name: str; version: str       # e.g. "mzr_pilot", "0.1.0"
    normalization: str            # versioned name in NORMALIZATION_PROFILES
    tokenizer: str                # versioned name in TOKENIZERS
GENERIC_PROFILE = LanguageProfile("und", "generic", "0.1.0", "default_text@0.1.0", "whitespace_punct@0.1.0")
LANGUAGE_PROFILES: Mapping[str, LanguageProfile]   # {"mzr": MZR_PROFILE}; filled in WP2.7
def profile_for(language: str) -> LanguageProfile   # registered profile, else GENERIC_PROFILE
```

`RuleChainProfile` constructor and pure interface: `__init__(self) -> None`, `normalize(self, raw: str) -> NormalizationResult`; concrete subclasses expose ClassVar name/version/rules. The rule-chain sums `RuleOutput.diagnostics`. `OffsetMap.validate` checks length, bounds and monotonicity, not endpoint coverage. Whitespace trimming slices away deleted edge boundaries: `"  kanu  " → "kanu"` maps `(2,3,4,5,6)`, so its token raw span is `[2,6)`. Empty normalization fails before a usable map is returned. Add `test_trimmed_edges_do_not_enter_token_raw_span`.

A shared `NormalizationProfile` base implementation (`normalization/base.py::RuleChainProfile`) applies `rules` in order, composes the `OffsetMap`s and re-projects every rule's events into raw and final coordinates. `normalize()` then calls `result.offsets.validate(len(raw), len(normalized))`.

Event re-projection: a later rule's event span `[a, b)` in its input coordinates maps to raw via the accumulated map. Its normalized coordinates map forward via the later rules' maps (use the inverse lookup: the smallest normalized boundary whose raw index ≥ the target). Write this as one tested helper, not inline.

**Interval contract (clarification, WP2.2 senior decision; reversible, no persisted schema change, does not accept ADR-0010).** Event spans are conservative audit envelopes, not exact character attribution. For a later rule's input span: a nonempty `[a, b)` starts at the first output boundary of the greatest mapped input value ≤ a and ends at the last output boundary of the least mapped input value ≥ b; positions outside coverage clamp to output 0 or output length. A zero-width span stays zero-width at the first output boundary ≥ its position, clamped. Wholly deleted nonempty spans may therefore become zero-width. Pinned examples: contraction `(0,2)`: `[1,2)`→`[0,1)`; expansion plateau `(0,0,1)`: `[0,1)`→`[0,2)`; whole-segment fallback `(0,0,0,4)`: `[1,2)`→`[0,3)`; trim `(2,3,4,5,6)` on length 8: `[0,2)`→`[0,0)`, `[6,8)`→`[4,4)`, `[2,6)`→`[0,4)`; zero-width `0` through `(0,0,1)`→`[0,0)`. Raw projection is an exact index lookup on each rule's input positions. Token offset-map semantics are unchanged.

**Tests first:**
- `test_registry_rejects_duplicate_versioned_names`
- `test_registry_bare_name_resolves_highest_version`
- `test_registry_unknown_name_raises_unsupported_source`
- `test_offset_identity_and_validate`
- `test_offset_compose_associative` (Hypothesis: three random monotone maps)
- `test_offset_validate_rejects_decreasing_or_wrong_length`
- `test_default_extractor_table` (golden fixture pairs: 01/02/03 → tsv; 05 → plain_lines; 04 igt → None; `text/x-usfm` → usfm)

**Do NOT:** implement concrete rules or extractors here; import anything from `languages/mzr`.

---

### WP2.3 — TSV and plain-lines extractors

**Files:** `extraction/tsv.py`, `extraction/plain_lines.py`, registry entries; tests `tests/unit/extraction/test_tsv.py`, `tests/unit/extraction/test_plain_lines.py`.

Shared decoding (`extraction/base.py::decode_utf8(data, source_object_id) -> tuple[str, dict[str,int]]`): strict UTF-8. A leading BOM is removed and counted (`stats["bom_removed"]=1`). Invalid UTF-8 raises `ExtractionFailed("decode_error", ...)`. `\r\n` and `\r` are treated as line terminators and counted (`crlf_lines`). Terminators never appear in `raw_text`.

**`tsv@0.1.0`**
- Line 1 is the header. Column headers are trimmed of ASCII spaces only for matching; cell text is **not** trimmed.
- A **language column** is a header equal to a code in `ctx.source_languages`. Zero language columns raises `ExtractionFailed("tsv_header_invalid")`. A header that looks like a 3-letter code but is not in `source_languages` raises `tsv_language_column_unknown`.
- A **ref column** is column 0 when it is not a language column. The other non-language columns (e.g. `note`) are **metadata columns**: not extracted, counted in `stats["metadata_cells"]` (no silent deletion; their text stays in raw storage).
- Each non-empty language cell produces one unit in row-major, column order, with `locator = {"row": <1-based file line>, "column": <header>}` plus `{"ref": <ref cell>}` when a ref column exists. Empty cells go into `empty_units` (`{"row", "column"}`). Rows with a different field count raise `tsv_ragged_row`. Trailing empty lines are ignored and counted.
- `language` = the column header.

**`plain_lines@0.1.0`**
- `language` = `ctx.language`, or the single entry of `source_languages`. Otherwise raise `UnsupportedSource("language_ambiguous")`.
- Each non-blank line becomes one unit with `locator = {"line": <1-based>}`. Blank lines are counted (`blank_lines`). Line text is kept verbatim (no trim).

**Tests first:**
- `test_tsv_parallel_fixture_units` (golden 01: 8 units, `ref` `TXT.1.1`… in the locator, languages qaa/por)
- `test_tsv_wordlist_without_ref_column_counts_note_metadata` (golden 03)
- `test_tsv_empty_cell_is_reported_not_emitted`
- `test_tsv_ragged_row_fails_with_line_only` (the exception message contains no cell text)
- `test_tsv_unknown_language_column_fails`
- `test_tsv_bom_and_crlf_counted_and_absent_from_text`
- `test_plain_lines_preserves_nfd_and_internal_spacing` (golden 05 line 3 stays NFD in `raw_text`)
- `test_plain_lines_requires_single_language`
- `test_extractors_are_deterministic` (Hypothesis: same bytes ⇒ equal outputs)
- `test_invalid_utf8_raises_decode_error`

**Do NOT:** trim, NFC, lowercase or collapse anything in extracted text; extract the `note` column as target-language text; read files from disk.

---

### WP2.4 — USFM extractor

**Files:** `extraction/usfm.py`, registry entry, `tests/fixtures/text/qaa_sample.usfm`, `tests/fixtures/text/README.md`; tests `tests/unit/extraction/test_usfm.py`.

**`usfm@0.1.0`** is a hand-written, line-independent marker scanner (no new dependency). Language is resolved as in `plain_lines`.

Units and locators (all locators include `"book"` and `"unit"`):

| Unit | Trigger markers | Locator keys |
|---|---|---|
| `verse` | text after `\v N` until the next `\v`, `\c`, paragraph/heading marker or note opener | `book, chapter:int, verse:str, unit, para:str, para_index:int, part:int` |
| `heading` | `\s#`, `\ms#`, `\mr`, `\sr`, `\r`, `\sp`, `\d`, `\mt#`, `\mte#`, `\cl` | `book, chapter:int (0 before first \c), unit, marker, para_index` |
| `footnote` | `\f … \f*`, `\fe … \fe*` | `book, chapter, verse (current, or "" if none), unit, note_index:int (per book, 0-based), caller` |
| `introduction` | `\ip`, `\is#`, `\imt#`, `\io#`, `\ipr`, `\iq#`, `\im`, `\imq` | `book, unit, marker, para_index` |

Rules:
- `\id XXX` gives `book` (the 3-character code, upper case). A missing `\id` raises `usfm_missing_id`. `\c` must parse as a positive int (`usfm_bad_chapter`). A `\v` value must match `^\d+[a-z]?(-\d+[a-z]?)?$` (`usfm_bad_verse`), so `"1-2"` and `"3a"` are kept as strings. `\v` before any `\c` raises `usfm_verse_before_chapter`.
- **Verse spanning paragraphs:** each contiguous piece of a verse inside one paragraph, also split at notes is a separate unit with the same `(chapter, verse)` and `part` = 0, 1, … Pieces are never joined, because joining would invent whitespace.
- Paragraph markers (`\p \m \pi# \q# \qm# \qc \qr \li# \pc \pm \mi \nb \cls \pmo \pmc \pmr`) start a new `para_index` (per book, 0-based). `\b` and `\ib` start nothing and are counted.
- Character markers (`\jmp` included; its `|attributes` are dropped and counted as `jmp_attributes_dropped`, with visible text preserved; `\add \nd \wj \bk \qt \k \tl \sc \it \bd \bdit \em \no \sup \pn \png \qs \qac \w \+…` nested) are removed; their content is kept. `\w word|attrs\w*` keeps `word` and counts the dropped attributes (`w_attributes_dropped`).
- Inside notes, `\fr` goes to the locator `note_ref` (a string) and is not part of the text. `\fq \fqa \ft \fk \fl \fw \fp \fv \fdc` content is kept and the markers are removed. A note left open at a paragraph or chapter boundary or at end of file raises `usfm_unclosed_note`. Note text never appears in the host verse's `raw_text`. The host verse piece ends at the note opener; emit that piece, then the note unit, then any resumed verse text as the next `part`. Multiple notes follow this same rule. Never concatenate text across a removed note or invent separators. A note at the beginning has no empty host Segment; note ordinals remain document ordered.
- **Skipped but counted** (stats key in parentheses, never silent): `\x … \x*` (`xref_notes`), `\fig … \fig*` (`figures`), `\rq … \rq*` (`inline_refs`), `\ca \va \vp` (`alt_numbering`; `\vp` value → locator `published_verse`), `\h \toc# \toca# \ide \rem \sts \usfm \periph` (`metadata_markers`), `\cp` (`published_chapter`; value → locator `published_chapter`).
- Bare paragraph/heading markers accept optional numeric suffixes (`\q` and `\q1`, `\pi` and `\pi1`); do not require digits.
- **Unknown markers** are counted as `unknown_marker:<name>` (the marker name only). If an unknown marker starts a line, its text becomes a unit `unit="unknown"` with `marker` in the locator. Inline unknown open/close markers are removed while retaining their content in the current unit; a matching close never creates a second unit. If a line-start unknown block has continuation lines, retain them until the next structural marker. XXF `\zvideo` content is an unknown observation, not a download instruction. Never follow URLs or paths found in markup. Nothing is dropped.
- Text assembly follows USFM whitespace semantics: each line break inside a unit becomes exactly one U+0020 (counted as `newline_folds`); `~` becomes U+00A0 (`tilde_nbsp`); `//` is removed (`optional_breaks`). Other characters are kept exactly. Leading and trailing whitespace of a unit is stripped (counted as `edge_whitespace_stripped`). These are the **only** text changes the extractor makes. They are USFM markup decoding, not normalization, and are listed in ADR-0010.
- A verse with no text (an omitted verse) goes into `empty_units`.

`tests/fixtures/text/qaa_sample.usfm` is a **synthetic** `qaa` book (`\id RUT` is acceptable as a code, but the text must be invented and use the golden fixture's vocabulary). It must exercise: `\id`, `\h`, `\toc1`, `\mt1`, `\c 1`, `\s1`, `\p`, `\v 1`, `\v 2-3`, a verse continuing across `\p` → `\q1`, `\f + \fr 1:2 \ft …\f*`, `\x …\x*`, `\w kanu|lemma="x"\w*`, `\add …\add*`, nested `\+nd`, `~`, `//`, an omitted `\v 5`, an unknown `\zfoo` marker, an NFD `kanú`, a hyphenated `mabi-ki`, and `\c 2` with `\v 1`.

**Tests first:**
- `test_usfm_sample_unit_sequence` (exact expected list of `(unit, locator, raw_text)` written in the test, not snapshotted from output)
- `test_usfm_verse_across_paragraphs_has_parts`
- `test_usfm_footnote_separate_unit_and_absent_from_verse`
- `test_usfm_multiple_midverse_notes_preserve_piece_order`
- `test_usfm_bare_q_pi_and_jmp_attributes`
- `test_usfm_verse_free_book_preserves_unknown_blocks`
- `test_usfm_character_markers_removed_content_kept`
- `test_usfm_skipped_markers_are_counted`
- `test_usfm_unknown_marker_preserved_as_unit`
- `test_usfm_omitted_verse_in_empty_units`
- `test_usfm_nfd_text_preserved` (no NFC in extraction)
- `test_usfm_verse_range_and_letter_suffix_kept_as_strings`
- `test_usfm_errors_have_line_numbers_and_no_text` (one test per error code)
- `test_usfm_text_conservation` (Hypothesis over generated simple USFM: concatenating unit texts plus skipped-note texts accounts for every non-marker, non-whitespace character of the input)

**Do NOT:** add a USFM library without asking (if you think one is needed, stop and report); parse `.pkf`, SFM Toolbox (IGT) or USX; emit paragraph-level duplicate segments; normalize Unicode.

---

### WP2.5 — Normalization rules and generic profiles

**Files:** `normalization/rules.py`, `normalization/profiles.py`; tests `tests/unit/normalization/test_rules.py`, `test_profiles.py`, `test_normalization_properties.py`.

**Rule `nfc`:**
1. Split the raw text into chunks that start at a character with `unicodedata.combining(ch) == 0`. Leading combining marks join the first chunk.
2. NFC each chunk. If `"".join(NFC(chunk)) != unicodedata.normalize("NFC", text)`, fall back to treating the whole text as one chunk. That is correct but coarse; count it as `diagnostics["nfc_whole_segment_fallback"]`.
3. Every changed chunk emits one event (`rule="nfc"`). Boundaries inside a changed chunk map to the chunk's raw start, and its end boundary maps to the raw chunk end.

**Rule `whitespace`:** every maximal run of `str.isspace()` characters (this covers TAB, LF, NBSP U+00A0, U+2000–U+200A, U+3000 and similar) becomes one U+0020, then leading/trailing whitespace is removed. A run that was already a single U+0020 emits no event; every other changed run emits an event. Zero-width characters (U+200B, U+200C, U+200D, U+FEFF) are **not** whitespace and are kept, with a diagnostic `zero_width:U+XXXX`.

**Failure** (`NormalizationFailed`): the raw text contains U+FFFD (`replacement_char`) or a C0/C1 control character other than TAB/LF/CR (`control_char`), or the result is empty (`empty_after_normalization`). The service turns this into `status=normalization_failed`.

**Profiles:**
- `unicode_nfc@1.0.0`: rules `(nfc,)`
- `default_text@0.1.0`: rules `(nfc, whitespace)`

No case folding, punctuation mapping, quote folding or diacritic stripping exists in M2. Such rules would be destructive and need explicit configuration plus an ADR.

**Tests first:**
- `test_nfc_composes_decomposed_tilde_with_event_and_spans` (`"kanú"` → `"kanú"`, event raw `[3,5)` → norm `[3,4)`)
- `test_nfc_already_composed_emits_no_event`
- `test_whitespace_collapses_nbsp_and_tabs_with_events`
- `test_zero_width_kept_and_diagnosed`
- `test_failure_codes` (U+FFFD, control char, whitespace-only)
- Properties (Hypothesis, `text()` strategy including combining marks and Zs):
  - `test_profile_idempotent`: `normalize(normalize(x).normalized).normalized == normalize(x).normalized`, and the second pass has no events
  - `test_offset_map_valid_and_monotone`
  - `test_result_is_nfc`
  - `test_span_roundtrip`: for any normalized span `[s,e)` whose boundaries are not inside an event, `profile.normalize(raw[map[s]:map[e]]).normalized == normalized[s:e]` (modulo edge whitespace)
  - `test_raw_never_mutated` (the input string object is equal before and after; `result.raw is raw`)

**Do NOT:** lowercase; strip diacritics; map apostrophes or hyphens; use `NFKC`/`NFKD`.

---

### WP2.6 — Generic tokenizer `whitespace_punct@0.1.0`

**Files:** `tokenization/whitespace_punct.py`, `tokenization/registry.py`; tests `tests/unit/tokenization/test_whitespace_punct.py`, `test_tokenizer_properties.py`.

Character classes over **normalized** text:
- word-char: Unicode category `L*` or `M*`
- digit: `Nd`
- joiner: configurable `ClassVar[frozenset[str]]`, default `{"-", "‐", "'", "’"}` (U+02BC is `Lm`, so it is already a word-char)
- space: U+0020 (the only whitespace left after normalization; any other `isspace` char is treated as a separator)
- everything else: punct

Tokens:
- `WORD` = a maximal run matching `word-char+ (joiner word-char+)*`. A joiner is kept only *between* word-chars. Leading/trailing joiners are `PUNCT`.
- `NUMBER` = a maximal `Nd+` run. A run that mixes letters and digits (e.g. `2a`) is split into NUMBER and WORD; this is documented as a known limitation for mixed alphanumeric strings; real verse text may contain them.
- `PUNCT` = each punct character as its own token; `...` gives three tokens.

The class is parameterized so `marubo_pilot` (WP2.7) can subclass with its own name, version and joiner set.

Registry wiring (avoids import cycles and keeps language code out of generic modules): `tokenization/registry.py` defines `GENERIC_TOKENIZERS = (WhitespacePunctTokenizer(),)` and `normalization/profiles.py` defines `GENERIC_NORMALIZATION_PROFILES`. Neither imports `languages`. `languages/base.py` builds the final `TOKENIZERS` and `NORMALIZATION_PROFILES` (`VersionedRegistry` instances) from the generic tuples plus each language package's exported components. Services and CLI import the registries **only** from `languages/base.py`.

**Tests first:**
- `test_hyphenated_word_is_one_token` (`"mabi-ki nawa"` → `["mabi-ki", "nawa"]`)
- `test_trailing_hyphen_is_punct` (`"wesa-"` → `["wesa", "-"]`)
- `test_apostrophe_internal_vs_quote`
- `test_punctuation_each_char_token`
- `test_combining_marks_stay_in_word` (NFD input still yields one WORD; the tokenizer is robust even though normalization feeds it NFC)
- Properties: `test_tokens_cover_all_non_space_chars_in_order_without_overlap`; `test_surface_equals_slice`; `test_deterministic`

**Do NOT:** split on hyphens/apostrophes inside words; lowercase; drop punctuation; look at raw text; use regex `\w` (it includes `_` and digits and differs from the spec above).

---

### WP2.7 — Marúbo language profile stub

**Files:** `languages/inventory.py`, `languages/mzr/__init__.py`, `languages/mzr/profile.py`, `languages/mzr/inventory.yaml`, `languages/base.py` (register); tests `tests/unit/languages/test_mzr_profile.py`, `test_inventory.py`, `test_language_isolation.py`.

```python
# languages/inventory.py
class Inventory(DomainModel):
    language: LANG_CODE
    status: Literal["unverified", "provisional", "verified"]
    characters: tuple[str, ...]        # each item one NFC grapheme string; may be multi-codepoint
    digraphs: tuple[str, ...] = ()     # informational only in M2 (e.g. reviewed "tx", "sh")
    reviewed_by: str | None = None     # required unless status == "unverified"
    notes: str | None = None
def load_inventory(path: Path) -> Inventory                      # SchemaViolation on bad YAML
def inventory_diagnostics(text: str, inv: Inventory) -> dict[str, int]
    # counts "char_outside_inventory:U+XXXX" for code points not covered by inv.characters;
    # ASCII space and characters in the punct class are ignored; empty dict if inv.characters == ()

# languages/mzr/profile.py
class MaruboStandardProfile(RuleChainProfile):   # name "marubo_standard", version "0.1.0"
    rules = (NFC, WHITESPACE)
    # normalize() = RuleChainProfile.normalize + inventory_diagnostics(normalized, MZR_INVENTORY)
class MaruboPilotTokenizer(WhitespacePunctTokenizer):   # name "marubo_pilot", version "0.1.0"
    joiners = frozenset({"-", "‐", "'", "’"})   # same as generic in 0.1.0; separate name so it can version independently
MZR_PROFILE = LanguageProfile("mzr", "mzr_pilot", "0.1.0", "marubo_standard@0.1.0", "marubo_pilot@0.1.0")
```

`inventory.yaml` ships as:
```yaml
language: mzr
status: unverified
characters: []
digraphs: []
reviewed_by: null
notes: "Populate only from the WP2.15 observed-inventory report after senior and community review. See docs/languages/mzr.md."
```
With `characters: []`, diagnostics are disabled. **The junior MUST NOT fill this list.**

Orthographic-variant awareness in M2 means: NFC unifies precomposed and decomposed nasal vowels (`ã`/`a+◌̃`, `õ`, `ĩ`, `ẽ`, `ũ`); digraphs like `tx`/`sh` are never split, because they are word-chars; distinct spellings stay distinct Forms. **No variant merging, no `ts`/`tx` mapping, no accent stripping.**

**Tests first:**
- `test_mzr_profile_registered_and_versioned`
- `test_mzr_nfc_unifies_decomposed_nasal_vowels` (`"shovimakĩ"` and `"shovimakĩ"` → same normalized text)
- `test_mzr_tokenizer_keeps_hyphen_attached_suffix` (`"mabi-ki"`, `"wesa-ra"` stay one WORD each)
- `test_mzr_profile_does_not_split_listed_clitic_examples` (`"txipo"`, `"shovimakĩ"` → one token each; guards C3)
- `test_mzr_variants_remain_distinct` (`"kanu"` vs `"kanú"` → different normalized surfaces)
- `test_inventory_unverified_disables_diagnostics`
- `test_inventory_requires_reviewer_unless_unverified`
- `test_inventory_diagnostics_counts_codepoints_not_text`
- `test_language_isolation`: scan `src/langpipe/**/*.py` outside `languages/mzr/` for `mzr|marubo|marúbo` (case-insensitive); only `languages/base.py` and `cli/*.py` help strings are allowlisted.

**Do NOT:** encode morphology, clitic lists, stems, suffix inventories, or typological assumptions (SOV, ergativity) anywhere; use Shipibo or other Pano data; generate or "correct" Marúbo spellings.

---

### WP2.8 — Recorder and run-recorder extensions

**Files:** `segmentation/recorder.py`, `ingestion/runs.py`; tests `tests/service/test_observation_recorder.py` (new cases), `tests/service/test_run_recorder_fail_artifact.py`.

```python
@dataclass(frozen=True)
class TokenInput:                          # M1 fields unchanged, new optional fields appended
    ordinal: int; raw_surface: str; raw_start: int | None; raw_end: int | None; form_text: str | None
    normalized_surface: str | None = None
    norm_start: int | None = None
    norm_end: int | None = None

@dataclass(frozen=True)
class NormalizedSegmentInput:
    raw_segment_id: str
    normalized_text: str | None            # None ⇔ failed
    failed: bool

class ObservationRecorder:
    @contextmanager
    def unit_of_work(self) -> Iterator[None]: ...
        # opens ONE repo.transaction(); inside it, record_* do not open their own; nesting → RuntimeError
    def record_normalized_segments(self, *, run_id: str, normalization_profile: str,
                                   items: Sequence[NormalizedSegmentInput]) -> list[Segment]: ...
        # run must be running with stage NORMALIZATION; NORMALIZE allowed for every raw segment's source;
        # each raw segment must have status OK, normalization_profile None and a creating run with stage EXTRACTION;
        # a failed derived segment is never a raw input; new Segment copies raw_text/locator/
        # language/source_id/source_object_id/ordinal; ok → normalized_text+profile, failed → status normalization_failed;
        # run io: raw seg input, new seg output; edge new --normalized_from--> raw
```

`record_tokens` / `record_normalized_tokens` contract (ADR-0010 decision 5 preserves the M1 path):
- `record_tokens` stays **M1-compatible**: it accepts a raw segment (M1 synthetic/evidence fixtures) or a normalized segment. A `normalization_failed` segment is rejected in either path (`InvalidLineage`). When the target segment is normalized, `orthography_profile` **must equal** `segment.normalization_profile`, else `SchemaViolation`.
- `record_normalized_tokens` is the **strict M2 entry point** with the same keyword signature; it requires an OK normalized segment (`normalization_profile is not None` and `status == ok`) else `InvalidLineage`, and a matching `orthography_profile` else `SchemaViolation`.
- Shared implementation: a normalized span is built when `norm_start`/`norm_end` are given; both-or-neither, as for raw spans. `normalized_surface` is stored on the token and `form_text`, when given together with a `normalized_surface`, must equal it.
- **Caller requirement (WP2.10):** NormalizationService/TokenizationService MUST call `record_normalized_tokens`; the M2 raw-rejection test targets that entry point. M1 evidence-service fixtures keep calling `record_tokens` with raw segments unchanged.

`RunRecorder.fail(run_id, error, artifact: Artifact | None = None, artifact_inputs: Sequence[str] = ())`: in one transaction, `finish_run(failed)`; if an artifact is given, `add_artifact`, `add_run_io(output)` and edges `artifact --derived_from--> each input`. M1 call sites stay unchanged.

**Tests first:**
- `test_unit_of_work_rolls_back_all_objects_on_late_failure` (two `record_segments` calls; the second raises; zero segments, edges and run I/O remain)
- `test_unit_of_work_nesting_raises`
- `test_record_normalized_segments_copies_raw_text_exactly`
- `test_record_normalized_segments_failed_has_status_and_no_text`
- `test_record_normalized_segments_rejects_already_normalized_input`
- `test_record_tokens_rejects_raw_segment` (M2 rule; targets the strict `record_normalized_tokens` entry point)
- `test_record_tokens_rejects_profile_mismatch`
- `test_record_tokens_checks_normalized_span` (a mismatched normalized surface → `SchemaViolation`, atomic)
- `test_fail_with_artifact_records_output_and_lineage`
- Existing M1 recorder tests: `record_tokens` fixtures now go through a normalized segment. **Update the fixtures, not the assertions.** If an M1 assertion has to change, stop and report.

**Do NOT:** add update paths; let the recorder compute normalization or tokens; relax policy checks.

---

### WP2.9 — ExtractionService (Stage 2)

**Files:** `extraction/service.py`; tests `tests/service/test_extraction_service.py`.

```python
EXTRACT_TOOL = "langpipe.extract"
@dataclass(frozen=True)
class ExtractionResult:
    source: Source; run: ProcessingRun; segments: int; skipped_objects: tuple[str, ...]
    report: Artifact | None; reused: bool
def extract_source(ctx: AppContext, source_ref: str, *, extractor: str | None = None,
                   language: str | None = None) -> ExtractionResult
```

Algorithm:
1. `source = resolve_source(ctx, source_ref)`; `policy = get_policy`.
2. **Gate first.** If `source.status is REVOKED` or `resolve(policy, EXTRACT) is not ALLOW`: audit `policy_denied` (details `{"operation":"extract","decision":…}`) in its own transaction, then `PolicyDenied`. No run.
3. `source.status is not INGESTED` → `SourceNotIngested`. No run.
4. Plan per object (ordered by `original_path`): `ext = extractor or default_extractor_for(source.source_type, obj.media_type)`. `source_type == IGT` → every object is skipped with reason `igt_not_in_m2`. If no object has an extractor → `UnsupportedSource("no_extractor")`, no run. Resolve versioned names through `EXTRACTORS.get` (an unknown name fails before any run).
5. `config = {"extractors": {obj_id: versioned_name, …}, "language": language}`; `input_ids` = the planned object ids. `find_reusable(EXTRACTION, EXTRACT_TOOL, config, input_ids)` → return `reused=True`, no writes. The count and report come from the stored run.
6. `run = start(...)`. Inside a try block, for each planned object: `blob = repo.get_raw_blob(obj.sha256)` (absent → `ObjectMissing`), `raw_store.verify(sha)`, read bytes from `raw_store`, `output = extractor.extract(data, ExtractionContext(...))`. Language codes in units must be in `source.languages`, else `SchemaViolation`. Validate an explicit language override against that set before starting the run.
7. Build the `extraction-report` JSON: `{"schema":"extraction-report","schema_version":1,"source_id","run_id","objects":[{"source_object_id","extractor","units":n,"stats":{…},"empty_units":[locators]}],"skipped":[{"source_object_id","reason"}]}`. IDs, counts and locators only. Project report locators through the allowlist `book, chapter, verse, unit, marker, para_index, part, note_index, line, row, column_index`; textual metadata such as `ref`, `note_ref`, `caller`, published numbering and titles is omitted (retained on governed Segment rows). Book/marker/verse values must pass the parser grammar; `unit` is a fixed enum. Never copy arbitrary locator dictionaries into reports. Store it in `artifact_store`; `access_class` = most restrictive of the objects.
8. `with recorder.unit_of_work():` `record_segments` per object, add the artifact plus run I/O plus edges `artifact --derived_from--> sobj`, then `RunRecorder.succeed`.
9. On `ExtractionFailed`: write an `extraction_error` artifact (`{"schema":"extraction-error","schema_version":1,"source_object_id","code","line"}`) through `RunRecorder.fail(run.id, e, artifact=…, artifact_inputs=[obj.id])`, then re-raise. On any other exception: `fail(run.id, e)` and re-raise. No segments survive.
10. `log_event(logger, "extraction.succeeded", source_id=…, run_id=…, segments=n)` (counts only).

**Tests first** (the `ctx` fixture runs on memory and PostgreSQL):
- **`test_extract_exclude_and_archive_only_denied_before_any_work`** (spy on `raw_store`; no run; one audit event)
- `test_extract_review_required_denied` (golden 04's mode; also IGT)
- `test_extract_revoked_source_denied`
- `test_extract_requires_ingestion`
- **`test_extract_creates_segments_lineage_run_io_and_report`** (golden 01: 8 segments; `seg --extracted_from--> sobj`; report parses and contains no `raw_text` or cell text — sentinel check)
- **`test_extract_rerun_is_idempotent`** (every count unchanged, `reused=True`)
- `test_extract_new_extractor_version_creates_new_run_and_keeps_old_segments` (monkeypatch a `tsv@0.1.1` registry entry)
- **`test_extract_failure_leaves_no_segments_and_records_error_artifact`** (two objects, the second malformed)
- **`test_extract_reads_only_from_raw_store`**: after ingest, delete or modify the origin file; extraction still succeeds with identical output.
- **`test_raw_store_bytes_unchanged_by_extraction`**: hash every stored blob before and after.
- `test_extract_igt_source_unsupported` (synthetic IGT with EXTRACT allowed; golden 04 must remain PolicyDenied)
- `test_extract_logs_no_text` (sentinel approach from M1 `test_log_redaction`)

**Do NOT:** read `origin_uri`; normalize; tokenize; write partial outputs; put file names or text into config, report, logs or errors.

---

### WP2.10 — NormalizationService and TokenizationService (Stage 3)

**Files:** `normalization/service.py`, `tokenization/service.py`; tests `tests/service/test_normalization_service.py`, `tests/service/test_tokenization_service.py`.

```python
NORMALIZE_TOOL = "langpipe.normalize"; TOKENIZE_TOOL = "langpipe.tokenize"
@dataclass(frozen=True)
class NormalizationResultSummary:
    run: ProcessingRun; segments: int; failed: int; report: Artifact | None; reused: bool
def normalize_extraction(ctx: AppContext, extraction_run_id: str, *,
                         profiles: Mapping[str, str] | None = None) -> NormalizationResultSummary
    # profiles: language → normalization versioned name; default profile_for(lang).normalization
@dataclass(frozen=True)
class TokenizationSummary:
    run: ProcessingRun; tokens: int; forms: int; skipped_failed_segments: int
    report: Artifact | None; reused: bool
def tokenize_normalization(ctx: AppContext, normalization_run_id: str, *,
                           tokenizers: Mapping[str, str] | None = None) -> TokenizationSummary
def select_extraction_run(ctx: AppContext, source: Source, run_id: str | None) -> ProcessingRun
    # explicit id must be a succeeded extraction run whose inputs ⊆ source objects; else
    # unique succeeded extraction run among list_runs_with_input(obj, EXTRACTION, SUCCEEDED) over the source's objects;
    # 0 → NotFound("processing_run", source.id); >1 → AmbiguousInput(EXTRACTION, n)
```

**Normalization algorithm:**
1. The extraction run must be `succeeded` with stage `extraction` (`InvalidLineage`). `raw_segments = list_segments_for_run`.
2. Resolve governed source ancestry from the extraction run's registered SourceObject inputs, even when there are zero segments; validate all segments belong to those sources. Gate: `NORMALIZE` must be `allow` for every source (revoked → denied); audit plus `PolicyDenied`, no run. Missing/empty source ancestry → `InvalidLineage`.
3. Resolve the per-language profile; every versioned name must exist. `config = {"extraction_run_id": extraction_run_id, "profiles": {lang: name@ver …sorted}}`; `input_ids` = the raw segment ids. Reuse check.
4. Start the run. For each raw segment (pure, outside the transaction): `profile.normalize(raw_text)`; `NormalizationFailed` → failed item with its code counted.
5. Report `normalization-report` v1: per segment `{"segment_id" (new id), "raw_segment_id", "status", "events":[{rule, raw_start, raw_end, norm_start, norm_end}], "diagnostics":{…}}`, plus totals `failure_codes`. The report holds the offset events **only**. The offset map itself is rebuilt deterministically by re-running the pinned profile; `test_offset_map_reproducible_from_profile` guards this.
6. `unit_of_work`: `record_normalized_segments` per profile group; build the report with the returned new Segment ids, then store its bytes; add the report artifact with run I/O output; add edges `artifact --derived_from--> seg_norm` for each new normalized segment (runs are never lineage parents); then `succeed`.

**Tokenization algorithm:**
1. The normalization run must be `succeeded` with stage `normalization`. `segments = list_segments_for_run(normalization_run_id)`.
2. Gate `NORMALIZE` for sources of all normalized outputs, including failed ones. If there are no outputs, recover ancestry via normalization run input segments and its configured extraction run; empty ancestry → `InvalidLineage`. Include **all** segment ids, including failed ones, in run inputs and reuse identity; only OK ones are tokenized.
3. The per-language tokenizer default is `profile_for(lang).tokenizer`. `config = {"normalization_run_id": normalization_run_id, "tokenizers": {...}}`; `input_ids` = all normalized segment ids, including failed ones. Reuse check.
4. For each ok segment, rebuild the offset map with the profile named in `segment.normalization_profile` (it must still be registered, else `UnsupportedSource("no_extractor")`; `test_retired_profile_blocks_tokenization`). Assert that the rebuilt `normalized == segment.normalized_text`, else `SchemaViolation` (it guards non-reproducible profiles). Tokenize, then map each token: `raw_start, raw_end = offsets.raw_span(norm_start, norm_end)`; `raw_surface = raw_text[raw_start:raw_end]`. **If `raw_start == raw_end` or the raw surface is empty or whitespace**, the whole segment is recorded as `token_span_unmappable` in the report and gets **no** tokens (never fabricate). `form_text = surface` only for `WORD`.
5. `unit_of_work`: `record_tokens` per segment with `orthography_profile = segment.normalization_profile`; report artifact `tokenization-report` v1 (per segment `{segment_id, tokens, words, punct, numbers}` plus `skipped`); `artifact --derived_from--> each tokenized segment`; `succeed`.

All work after `RunRecorder.start`, including pure processing, report storage and semantic writes, is inside a try/except: rollback the unit of work, call `RunRecorder.fail` in its own transaction, then re-raise. A per-segment `NormalizationFailed` is the sole handled partial-success case. Artifact blobs left by rollback are permissible orphans, as in M1. Reused summary counts come from stored report totals; `forms` means distinct Form ids attested by this run, including reused Forms. Failed/skipped totals cover every input segment.

**Tests first:**
- `test_normalization_and_tokenization_failure_finish_run_without_outputs`
- `test_empty_and_all_failed_runs_keep_source_identity_and_policy_gate`
- **`test_normalized_segment_raw_text_identical_to_extracted`** (all golden sources)
- `test_normalization_creates_normalized_from_edges_and_run_io`
- `test_normalization_failed_segment_status_and_report_code` (U+FFFD input)
- **`test_normalization_rerun_idempotent`** and `test_tokenization_rerun_idempotent`
- `test_profile_version_change_creates_new_run_leaves_old_rows`
- **`test_token_raw_and_normalized_spans_slice_correctly`** (NFD `kanú` in golden 05: `raw_span` covers 5 code points, `normalized_span` 4)
- **`test_same_surface_across_sources_shares_form`** (phenomenon 1: `kanu` in 01 and 05; `mabi` in 01 and 02)
- **`test_orthographic_variant_distinct_forms`** (phenomenon 8: `kanu` ≠ `kanú`)
- `test_nfd_and_nfc_attestations_share_one_form` (05 line 3 NFD `kanú` and 02 NFC `kanú` → the same Form)
- `test_punct_tokens_have_no_form`
- `test_hyphenated_token_single_occurrence_with_full_raw_span` (`mabi-ki`)
- `test_unmappable_segment_gets_no_tokens` (craft a profile whose fallback NFC chunk swallows a token boundary)
- `test_select_extraction_run_ambiguous_raises`
- `test_normalize_denied_for_review_required_source_writes_nothing`
- `test_extraction_tokens_unchanged_after_renormalization` (observation immutability: tokens from profile v1 stay byte-identical after a v2 run)

**Do NOT:** update or delete segments; tokenize raw segments; let a tokenizer see raw text; create Forms for punct/number; merge Forms; store offset maps in the DB.

---

### WP2.11 — Lineage-aware policy helper and governance invariants

**Files:** `governance/lineage_policy.py`; tests `tests/service/test_text_governance.py`.

```python
def ancestor_source_ids(repo: Repository, object_id: str) -> list[str]   # sorted; via ancestors() + entity_type_of
def effective_decision(repo: Repository, object_id: str, op: Operation) -> PolicyDecision
    # resolve_many(policies of ancestor sources (+ object itself if a source), op); no sources → DENY
```

This is **not** an export or eligibility engine (the training firewall is a later milestone). It is the M2 proof that governance follows lineage through the new layers.

**Tests first:**
- **`test_distill_only_segments_tokens_forms_not_trainable`**: for golden 01, every raw segment, normalized segment and token gives `effective_decision(…, DIRECT_TRAINING) == DENY`.
- **`test_shared_form_inherits_most_restrictive_decision`**: the Form for `mabi` (attested in 01 distill_only and 02 direct) → `DENY` for `DIRECT_TRAINING`.
- `test_direct_only_token_allows_direct_training_decision` (02-only token → `ALLOW`. This states the policy decision only, not export eligibility.)
- `test_excluded_source_has_no_descendants_after_text_pipeline`
- `test_impact_of_source_reaches_normalized_segments_tokens_and_forms` (`descendants(src)` covers the new layers)
- `test_third_party_api_denied_for_all_m2_outputs` (every M2 output of a `distill_only`/`community` source → `DENY`; guards the future ScriptureEarth pipeline)

**Do NOT:** build export or eligibility views; add new policy operations.

---

### WP2.12 — ScriptureEarth source adapter (manifest builder)

**Files:** `ingestion/adapters/__init__.py`, `ingestion/adapters/scriptureearth.py`; tests `tests/unit/ingestion/test_scriptureearth_adapter.py`.

The adapter **does not download, register or ingest**. It inspects a directory the operator acquired by hand and writes a standard `SourceManifest` YAML (`manifest_version: 1`). The operator then runs `source add`/`source ingest` (the M1 path, unchanged).

```python
SE_MEDIA_USFM = "text/x-usfm"
SE_MEDIA_TIMING = "text/x-sab-timing"
@dataclass(frozen=True)
class ScriptureEarthPackage:
    root: Path; usfm_files: tuple[Path, ...]; timing_files: tuple[Path, ...]; pkf_files: tuple[Path, ...]
def scan_package(root: Path) -> ScriptureEarthPackage
    # recursive; usfm = *.usfm|*.sfm|*.SFM (case-insensitive); timing = *.timing.txt; pkf = *.pkf;
    # symlinks are not followed; paths sorted; no usfm and pkf present → UnsupportedSource("pkf_not_supported");
    # no usfm at all → UnsupportedSource("no_usfm_files")
def build_manifest(pkg: ScriptureEarthPackage, *, key: str, language: str, policy: PolicySpec,
                   provenance: Provenance, acquired_at: datetime, include_timing: bool = False,
                   title: str | None = None) -> SourceManifest
    # source_type=SourceType.PUBLICATION (monolingual package; parallel pairing is M3); languages=[language]; domains=["religious"];
    # registers=["religious"]; title = supplied title or f"ScriptureEarth {language}";
    # objects = ObjectSpec(path=p.relative_to(pkg.root).as_posix(), media_type=SE_MEDIA_USFM or SE_MEDIA_TIMING)
    # in sorted relative-path order; access_class omitted so source policy applies; manifest_version=1;
    # the manifest must be written INSIDE pkg.root (M1 path-escape rule) → caller writes to root/"langpipe-manifest.yaml"
def write_manifest(m: SourceManifest, path: Path) -> None    # canonical YAML; refuses to overwrite a different file (SourceConflict)
```

**Policy is never invented by code.** The CLI requires `--policy FILE` (a YAML `PolicySpec`); real-data tests require `LANGPIPE_MZR_SE_MANIFEST` pointing to an operator-reviewed M1 manifest with a named authority, recorded rights holder, acquisition timestamp and local-processing permission. No test may manufacture authority or relax policy to make processing succeed. `docs/languages/mzr.md` supplies a template that matches § Religious corpus default:
```yaml
mode: distill_only
access_class: community
authority: "<named Marúbo governance authority — REQUIRED, no default>"
allow: [align, distill_lexicon, distill_morphology, audio_align]
deny: [synthetic_generation_support, third_party_api, cloud_processing, redistribute_raw, redistribute_derived]
```
`provenance.acquired_from` must parse with `urllib.parse.urlsplit` as scheme `https`, hostname exactly `www.scriptureearth.org`, no credentials and no nondefault port; `rights_holder` is required by the adapter (not by the M1 model) and is checked → `SchemaViolation` if missing.

**Tests first** (tmp dirs with synthetic files only):
- `test_scan_finds_usfm_timing_pkf_sorted`
- `test_pkf_only_package_unsupported`
- `test_manifest_validates_and_roundtrips_through_load_manifest`
- `test_manifest_paths_relative_and_inside_root`
- `test_timing_files_excluded_by_default`
- `test_rights_holder_required`
- `test_write_manifest_refuses_conflicting_overwrite`
- `test_adapter_never_opens_network` (monkeypatch `socket.socket` to raise; the adapter runs)

**Do NOT:** add HTTP code anywhere under `src/`; hard-code a policy; mark the source `direct`; unpack `.pkf`; include audio.

---

### WP2.13 — CLI

**Files:** `cli/app.py`, `cli/text.py`, `cli/scriptureearth.py`; tests `tests/unit/cli/test_cli_text.py`, `tests/unit/cli/test_cli_scriptureearth.py`, `tests/integration/test_cli_text_postgres.py`.

Commands (stdout `key=value`; errors as in M1 `guarded`; never echo text, file names or refs that failed validation):

```text
langpipe extract SOURCE_REF [--extractor NAME[@VER]] [--language ISO]
  → source_id=… run_id=… segments=N skipped_objects=N report_id=…|none reused=true|false
langpipe normalize SOURCE_REF [--extraction-run RUN_ID] [--profile ISO=NAME@VER]...
  → extraction_run_id=… run_id=… segments=N failed=N report_id=… reused=…
langpipe tokenize SOURCE_REF [--extraction-run RUN_ID] [--profile ISO=NAME@VER]... [--tokenizer ISO=NAME@VER]...
  → extraction_run_id=… normalization_run_id=… run_id=… tokens=N forms=N skipped_segments=N report_id=… reused=…
     # runs normalize (reused if identical) then tokenize; two runs (E1/C2)
langpipe profiles list
  → kind=extractor name=tsv@0.1.0 … / kind=normalization … / kind=tokenizer … / kind=language language=mzr profile=mzr_pilot@0.1.0 normalization=… tokenizer=…
langpipe scriptureearth manifest PACKAGE_DIR --key KEY --language ISO --policy POLICY_YAML
        --acquired-from URI --rights-holder TEXT --acquired-at ISO8601 [--include-timing]
  → manifest_path=<PACKAGE_DIR>/langpipe-manifest.yaml usfm=N timing=N pkf_ignored=N
     # the manifest path is printed because the operator supplied the directory; no file contents are printed
```

**Tests first:** `test_extract_normalize_tokenize_happy_path` (golden 01+05 in memory), `test_tokenize_reuses_normalization_run`, `test_extract_denied_exits_3`, `test_extract_not_ingested_exits_9`, `test_ambiguous_extraction_run_exits_11`, `test_cli_text_output_never_contains_segment_text` (sentinel), `test_profiles_list_includes_pinned_versions`, `test_scriptureearth_manifest_command_writes_valid_manifest`, `test_scriptureearth_manifest_requires_policy_and_rights`; integration `test_cli_text_pipeline_against_postgres`.

**Do NOT:** add commands that print segment/token text (a viewer is a separate, governed decision); put logic in the CLI.

---

### WP2.14 — Golden fixture M2 expectations

**Files:** `tests/golden/test_golden_m2.py`, `tests/golden/expected/m2/*.json`, `tests/golden/normalize.py` (extend), `tests/golden/fixture/PHENOMENA.md` (mark the M2 rows as checked), `tests/golden/expected/README.md`.

Pipeline: register plus ingest all six sources (M1). Then for 01, 02, 03 and 05: extract → normalize → tokenize with default profiles (`qaa`/`por` → generic). 04 → `PolicyDenied` (review_required blocks before format selection) and 06 → `PolicyDenied`. Separately use a synthetic IGT source with EXTRACT allowed to assert `UnsupportedSource`; never loosen golden 04's policy. Both are asserted.

**Source list resolution (senior, 2026-10-13).** The "01, 02, 03 and 05" list conflicts with the merged WP2.3 contract, which pins golden 03 (`03-wordlist/wordlist.tsv`) as a malformed ragged TSV and keeps its bytes unchanged so the M1 golden `sha256` still holds. Resolution: source 03 stays malformed; its explicit `ExtractionFailed(code="tsv_ragged_row")` is the approved outcome. The fixture is **not** repaired and WP2.3's assertions are not weakened. WP2.14 asserts the failure (`test_golden_m2_wordlist_03_is_malformed`) instead of driving 03 through the pipeline; the M2 snapshot covers 01, 02 and 05.

Expected snapshots (IDs normalized to labels, as in M1): runs (stage, tool, config, status), segments (label, source, ordinal, language, locator, raw_text, normalized_text, profile, status), tokens (segment label, ordinal, raw_surface, raw_span, normalized_surface, normalized_span, tokenizer, form label|null), forms (language, profile, text, attesting sources), lineage (kinds by layer), report summaries (counts only).

**Tests first:**
- `test_golden_m2_snapshot` (hand-verified expectations; the senior reviews the diff line by line before commit, per `GOLDEN-FIXTURE.md` § Updating)
- `test_golden_m2_rerun_creates_no_duplicates`
- `test_golden_m2_m1_snapshot_unchanged` (the M1 golden still passes byte-for-byte)
- `test_golden_m2_form_identity` (token-derived Form identity before projection: each `(language, normalization_profile, normalized_surface)` key maps to exactly one Form ID and vice versa, `count(EntityType.FORM)` equals the distinct keys and referenced IDs, `kanu` is shared by 01/05, `mabi` by 01/02/05, NFC/NFD `kanú` by 02/05, and `kanu` ≠ `kanú`)
- `test_form_identity_rejects_two_ids_for_one_key`, `test_form_identity_rejects_count_mismatch` (negative cases)
- `test_registered_component_versions_are_pinned` (exact sorted list of every versioned name)

**Do NOT:** add a new fixture source (M1 golden asserts the exact source set); regenerate snapshots blindly.

---

### WP2.15 — ScriptureEarth Marúbo real-data integration test

**Files:** `tests/integration/test_scriptureearth_marubo.py`, `tests/integration/expected/scriptureearth_mzr_counts.json`, `pyproject.toml` (marker plus `addopts`), `docs/languages/mzr.md` (acquisition steps), `.gitignore` (confirm `var/`).

**Acquisition (manual, operator-run, documented in `mzr.md`; not code):**
1. Check and record the license and rights holder for the Marúbo text on `https://www.scriptureearth.org/00por.php?iso=mzr`. **If local derivative processing is not permitted, stop and escalate. Redistribution permission is not required for authorized local processing; redistribution remains denied and corpus bytes never enter git.**
2. The nine files already acquired in `/tmp/mzr_usfm/` are ACT, EXO, GEN, JAS, JHN, LUK, NEH, RUT and XXF. After recording local-processing authorization, copy their bytes unchanged (never move or edit originals) to `var/external/scriptureearth/mzr/usfm/`. Timing files may go to `var/external/scriptureearth/mzr/timing/`. **Do not** commit any of it.
3. Build and review `var/external/scriptureearth/mzr/langpipe-manifest.yaml` using the WP2.12 CLI and an operator-supplied policy. Export `LANGPIPE_MZR_SE_DIR=$PWD/var/external/scriptureearth/mzr` and `LANGPIPE_MZR_SE_MANIFEST=$LANGPIPE_MZR_SE_DIR/langpipe-manifest.yaml`. A corpus under a tests directory is also acceptable only in a gitignored local subdirectory with the same manifest/path restrictions; committed tests contain synthetic data only.

**Configuration:**
```toml
markers = ["integration: requires PostgreSQL (docker compose up -d db)",
           "realdata: requires a locally acquired ScriptureEarth package (LANGPIPE_MZR_SE_DIR); never run in default CI"]
addopts = "-ra --strict-markers -m 'not realdata'"
```
Selecting it explicitly (`-m realdata`) overrides the default deselection (pytest uses the last `-m`).

**Test module** (every test `@pytest.mark.realdata`; DB tests also `integration`, using a dedicated function-scoped memory `AppContext` unless noted):
- Function-scoped `real_corpus` fixture: require both environment variables and USFM files, else fail with a fixed diagnostic (never skip). Load the supplied manifest via the M1 loader; assert `distill_only`, outward-flow denials and explicit non-placeholder authority/rights records. Register, ingest, extract, normalize and tokenize using a fresh memory repository, stores under `tmp_path`, and the existing clock/id conventions. This scope matches M1 fixtures and prevents test-order effects. A separate PostgreSQL test explicitly requests the function-scoped `pg_repository` fixture; do not make a module fixture depend on `ctx`, `repo` or `tmp_path`. No realdata test parametrizes the full corpus over both backends.
- `test_package_scan_finds_expected_books`: the set of `\id` codes equals `expected["books"]`.
- `test_every_usfm_object_extracts_without_failure`: one succeeded extraction run; no `extraction_error` artifacts.
- `test_verse_counts_match_reviewed_expectations`: count `\v` markers independently from stored bytes and compare `expected["verse_markers_by_book"]`; count distinct `(book, chapter, verse)` from verse units and `empty_units` per book; compare to `expected["verses_by_book"]`. The sum is checked against `expected["verses_total"]` (cross-check against independently observed counts; the discrepancy with reported 5,594 stays documented, C7). XXF must be present with zero verses and nonempty non-verse units.
- `test_locators_complete_and_monotone`: every verse unit has book, int chapter ≥ 1 and a verse string matching the USFM rule; within a book, `(chapter, first verse number)` is non-decreasing in ordinal order.
- `test_unknown_markers_reported_not_dropped`: the report's `unknown_marker:*` counters are listed in `expected["unknown_markers"]` (reviewed), and each such marker produced either units or counted skips.
- **`test_raw_text_conservation_against_source_bytes`**: for every verse segment, compare ordered verse-piece texts against an independent test-only rescan of stored bytes with the same explicit USFM decoding rules (newline folding, edge stripping, note and attribute removal, tilde and optional breaks). Locate each piece by `(book, chapter, verse, part)`; never demand literal contiguous matches in undecoded bytes or match by text alone. The oracle must not import production scanner helpers; its synthetic tests cover repeated verse text, two midverse notes, a continued paragraph and XXF. Unknown blocks and note content have separate conservation checks; skipped metadata content is accounted for by the documented skip counters, never emitted into public reports.
- **`test_raw_blobs_unchanged_after_full_pipeline`**: re-hash every stored blob plus only manifest-listed origin USFM/timing files (not policy/manifest/report files); compare each origin and stored blob with its corresponding registered SourceObject `sha256`. Never alter acquired files.
- **`test_normalized_raw_text_identity`**: every normalized segment's `raw_text` equals its `normalized_from` parent's.
- `test_normalization_failures_zero_or_reviewed`: `failed == expected["normalization_failed"]` (expected 0; any other value needs senior sign-off).
- **`test_token_spans_roundtrip_all_segments`**: for every token, `raw_text[raw_span] == raw_surface` and `normalized_text[normalized_span] == normalized_surface`; no `token_span_unmappable`, unless listed in expected.
- `test_hyphenated_and_nasal_forms_not_split`: no WORD token surface starts or ends with a joiner; every WORD containing `-` has both sides non-empty; no Form text contains U+0303 as a separate combining mark after a base that has a precomposed NFC form.
- `test_observed_inventory_report`: compute code-point counts over all normalized verse text and write them to a caller-selected local report directory (`LANGPIPE_MZR_SE_REPORT_DIR`, default a test `tmp_path`), as `mzr_observed_inventory.json` (**gitignored, not asserted against a guessed list**). Assert only that every code point is in `L*`, `M*`, `Zs`, `P*`, `Nd` or `S*`, and record outliers in the failure message by `U+XXXX` label only.
- **`test_idempotent_full_rerun`**: rerunning all five stages → every stage `reused=True`; `count(...)` for segment, token and form, `count_lineage_edges` and `count_runs` unchanged.
- **`test_distill_only_governance_on_real_data`**: sample 100 tokens deterministically (ordinal stride) → `effective_decision(DIRECT_TRAINING) == DENY` and `effective_decision(THIRD_PARTY_API) == DENY`.
- `test_no_text_in_logs_or_reports` (caplog plus report artifacts: none of 50 sampled verse texts (≥ 20 chars) appear).
- `@pytest.mark.integration` **`test_full_pipeline_on_postgres_with_one_book`**: RUT only (copy the registered RUT bytes and reviewed policy/provenance into a fresh tmp directory; hash-equality with the full-corpus object is required; write the single-object manifest inside that directory), with the same core assertions on the real DB, plus a measured runtime printed as `elapsed_s=` for the performance risk (R3).

`scriptureearth_mzr_counts.json` (committed, **numbers and marker names only**):
```json
{"books": ["ACT","EXO","GEN","JAS","JHN","LUK","NEH","RUT","XXF"],
 "verse_markers_by_book": {"ACT":996,"EXO":540,"GEN":1526,"JAS":108,"JHN":875,"LUK":1135,"NEH":124,"RUT":85,"XXF":0},
 "verses_by_book": {"ACT":0,"EXO":0,"GEN":0,"JAS":0,"JHN":0,"LUK":0,"NEH":0,"RUT":0,"XXF":0}, "verses_total": 0,
 "unknown_markers": [], "normalization_failed": 0, "token_span_unmappable": 0,
 "reviewed_by": null, "reviewed_at": null}
```
The junior commits it with `reviewed_by: null`, and the count tests **fail** while `reviewed_by` is null (a forcing function). The senior fills in the counts from a run, cross-checks them against all nine local files and independent verse-marker counts (5,389 observed in this review), records why distinct/expanded counts differ if applicable, and signs `reviewed_by`.

**Acceptance:**
```sh
export LANGPIPE_MZR_SE_DIR=$PWD/var/external/scriptureearth/mzr
export LANGPIPE_MZR_SE_MANIFEST=$LANGPIPE_MZR_SE_DIR/langpipe-manifest.yaml
LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -m realdata tests/integration/test_scriptureearth_marubo.py -q
```

**Do NOT:** commit any ScriptureEarth bytes, verse text, or an inventory derived from it (only counts); download inside tests; relax an assertion to make real data pass (report the anomaly instead; it may be an extractor bug or a real source anomaly that must be preserved); send any of it to an LLM or third-party service; use it in golden tests.

### WP2.17 — InMemoryRepository internal indexing (performance risk R3)

**Files:** `src/langpipe/storage/memory.py`, `tests/contract/test_repository_contract.py` (dedicated rollback, idempotency, duplicate, and graph traversal contract tests).

**Context & Scope:**
The 9-book Marúbo corpus in WP2.15 produces ~121k tokens and ~140k lineage edges. In `InMemoryRepository`, unindexed scans in `add_lineage_edge`, `ancestors`/`descendants` traversals, `add_segment`, `add_token`, and `get_or_create_form` produce $O(N^2)$ quadratic scanning bottlenecks, causing function-scoped corpus builds to take >20 minutes each.
This package introduces internal helper indexes on `_State` (`forms_by_key`, `segments_by_ordinal`, `tokens_by_ordinal`, `lineage_by_triple`, `lineage_out`, `lineage_in`, `lineage_edges_out`, `lineage_edges_in`, `tokens_by_segment`).
Because `_State` is snapshotted via `copy.deepcopy` upon entering a transaction, all index structures roll back atomically with domain entities on transaction rollback or failure.

**Acceptance:**
```sh
uv run pytest tests/contract/test_repository_contract.py -q
uv run pytest -q -m "not realdata"
```

---

### WP2.16 — Documentation and CI

**Files:** `docs/DEVELOPMENT.md` (§ Local commands (M2)), `docs/PIPELINE-CONTRACTS.md` (link ADR-0010 from Stages 2–3), `docs/SCHEMAS.md` (report artifact schemas `extraction-report`, `extraction-error`, `normalization-report`, `tokenization-report` v1 described; JSON Schema generation for reports deferred: they are artifacts, not domain models), `scripts/ci.sh` (unchanged gate; confirm `realdata` stays deselected), `tests/unit/test_ci_script.py` (assert `-m realdata` is not in `ci.sh`), `docs/implementation/M2-PLAN.md` § Status.

**Acceptance (full M2 gate):**
```sh
export LANGPIPE_TEST_DATABASE_URL="${LANGPIPE_TEST_DATABASE_URL:-postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe_test}"
scripts/ci.sh                         # ruff, format, mypy, schemas check, migrate, pytest (zero skips)
LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest tests/integration/test_migrations.py -q
# The migration fixture exercises upgrade/downgrade on its isolated test schema.
# Do not downgrade the populated M2 database: 0002 must reject new artifact kinds.
# opt-in, operator machine only:
LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -m realdata -q
```

---

## 7. Mandatory M2 test coverage map

| # | Invariant / requirement | Tests |
|---|---|---|
| 1 | Raw source bytes immutable | `test_raw_store_bytes_unchanged_by_extraction`, `test_raw_blobs_unchanged_after_full_pipeline` |
| 2 | Raw segment text never mutated; normalized keeps raw | `test_normalized_segment_raw_text_identical_to_extracted`, `test_record_normalized_segments_copies_raw_text_exactly`, `test_normalized_raw_text_identity` |
| 3 | Governance before work (extract/normalize) | `test_extract_exclude_and_archive_only_denied_before_any_work`, `test_extract_review_required_denied`, `test_normalize_denied_for_review_required_source_writes_nothing`, `test_extract_revoked_source_denied` |
| 4 | `distill_only` outputs not trainable through lineage | `test_distill_only_segments_tokens_forms_not_trainable`, `test_shared_form_inherits_most_restrictive_decision`, `test_distill_only_governance_on_real_data` |
| 5 | Lineage complete across new layers | `test_extract_creates_segments_lineage_run_io_and_report`, `test_normalization_creates_normalized_from_edges_and_run_io`, `test_impact_of_source_reaches_normalized_segments_tokens_and_forms` |
| 6 | Idempotent reruns | `test_extract_rerun_is_idempotent`, `test_normalization_rerun_idempotent`, `test_tokenization_rerun_idempotent`, `test_golden_m2_rerun_creates_no_duplicates`, `test_idempotent_full_rerun` |
| 7 | Failed stage leaves no partial outputs | `test_unit_of_work_rolls_back_all_objects_on_late_failure`, `test_extract_failure_leaves_no_segments_and_records_error_artifact` |
| 8 | Ambiguity and variants preserved | `test_orthographic_variant_distinct_forms`, `test_mzr_variants_remain_distinct`, `test_mzr_profile_does_not_split_listed_clitic_examples` |
| 9 | No content in logs/reports/CLI | `test_extract_logs_no_text`, `test_cli_text_output_never_contains_segment_text`, `test_no_text_in_logs_or_reports` |
| 10 | Language isolation | `test_language_isolation` |
| 11 | Spans correct | `test_token_raw_and_normalized_spans_slice_correctly`, `test_token_spans_roundtrip_all_segments`, normalization properties |
| 12 | Migration forward/back | `test_migration_0002_upgrade_downgrade_roundtrip` |

---

## 8. Global "Do NOT" list

- Do NOT update or delete any segment, token, form, lineage edge or artifact; derive new rows.
- Do NOT read source bytes from anywhere but `ctx.raw_store` after hash verification.
- Do NOT split words at hyphens, apostrophes or suspected clitics; do NOT ship clitic/suffix lists, stems, or a typed-in character inventory.
- Do NOT lowercase, strip diacritics, NFKC, map `tx`/`ts`, or merge orthographic variants.
- Do NOT put Marúbo-specific logic outside `src/langpipe/languages/mzr/`.
- Do NOT commit ScriptureEarth data, verse text, or real-data-derived inventories; do NOT download from tests or `src/`.
- Do NOT treat `review_required` as allowed.
- Do NOT log, print, or write into errors/reports any segment text, token surface, TSV cell, title or file name.
- Do NOT add dependencies (USFM libraries, Proskomma, ICU, regex) without an ADR or orchestrator approval.
- Do NOT implement alignment, lexicon, morphology, IGT import, audio/timing processing, export or training.
- Do NOT change M1 golden expectations.
- Do NOT use an LLM to produce, correct or "fill in" Marúbo text, glosses or inventories.

---

## 9. Senior review checklist (every WP)

1. Invariants in §7 still pass; no M1 test assertion changed (fixtures may change only per WP2.8).
2. Every new component has a pinned `name@version`; behavior changes bumped the version.
3. No text in logs, errors, reports or CLI output (grep the diff for `raw_text`, `surface`, `text=` in log calls).
4. Every service: gate → reuse check → start → pure work → single `unit_of_work` → succeed; failure path records a failed run and no semantic rows.
5. `language` and `mzr` strings confined per §4.2.
6. Migrations reversible; schemas regenerated and committed.
7. Real-data anomalies were reported, not patched over.

## 10. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | ScriptureEarth license or community governance forbids processing | C5 gate before acquisition; adapter requires rights holder; nothing committed |
| R2 | The real package has USFM dialect features beyond the WP2.4 marker table | Unknown markers preserved and counted; extractor version bump per fix; expectations reviewed |
| R3 | Row-by-row inserts (~4 rows per token, ~100k+ tokens) are slow on PostgreSQL | One-book PostgreSQL test measures `elapsed_s`; bulk insert is a follow-up WP if > 10 min for the full corpus (repository-internal, no contract change) |
| R4 | NFC chunk fallback produces unmappable token spans | Reported per segment (`token_span_unmappable`); real-data expectation pins the count at 0 |
| R5 | Re-derivable offset maps depend on profiles staying registered forever | Profiles are never removed from the registry (pinned-version test); `test_retired_profile_blocks_tokenization` makes the dependency explicit |
| R6 | Multiple extraction or normalization runs per source cause selection ambiguity | `AmbiguousInput` with explicit `--extraction-run`; a "current view" selection is OPEN for M3 |

## 11. OPEN items (do not resolve silently)

- `.pkf` decoding (Proskomma) → ADR if wanted (C6).
- Verified Marúbo character inventory and digraph list → `mzr.md` reviewers (C4).
- Footnote language in Marúbo Scripture (assumed to be the source language) → verify on real data.
- Selection of a "current" extraction/normalization run per source for downstream stages → M3 design.
- Timing files (`C01-*.timing.txt`) → audio alignment milestone; registered optionally, never extracted in M2.
- Governance-owner approval of the `mzr.md` operation-vocabulary mapping (M1 G1) still pending; the WP2.12 policy template uses the canonical governance vocabulary.

## 12. Status

Milestone 2 implementation is complete. Work packages WP2.0 through WP2.15, WP2.17 (storage indexing), and WP2.16 (documentation & CI) have passing acceptance suites and senior reviews. ADR-0010 text-processing derived segment architecture is implemented and decided for Milestone 2. Open architectural and community governance items in §11 remain explicitly tracked for downstream milestones.


## 13. Review log

### Second senior cross-review — 2026-10-12

Scope: AGENTS.md, LOCAL-AGENT-HANDOFF.md, DEVELOPMENT §M2, M1-PLAN,
M2-PLAN, mzr profile, PIPELINE-CONTRACTS; cross-check against live M1 models,
recorder/run APIs, fixtures, ADR-0007/0009 and local USFM marker/count metadata.
Only this plan was changed; no corpus bytes, registrations, policies or implementation
were modified. No content was sent to an external service. Required browser-harness
and parent Tessl instruction paths supplied in the handoff were absent; browser work
was not needed. M1's stated 415-test baseline was not independently rerun.

1. **OK — scope and ADR-0010 direction.** New derived Segment rows, child-to-parent
   `normalized_from` edges and tokens referencing the normalized row preserve
   append-only triggers and stage separation. Existing `segment`, `token_occurrence`,
   `form`, `lineage_edge`, `processing_run_io` and `object_registry` tables suffice;
   natural segment uniqueness includes run_id. No validated linguistic claims,
   alignment, training or morphology belong in M2. ADR acceptance remains pending.
2. **Fixed — governance and corpus setup.** Removed fabricated pending authority;
   real tests load a reviewed registered-source manifest through M1. All nine local
   files are included, including verse-free XXF; 5,389 observed verse markers replace
   the unverified eight-book assumption. 5,594 remains an unresolved source claim,
   not silently rewritten into a passing expectation. Local rights and community
   permission remain a prerequisite independent of public download availability.
3. **Fixed — USFM and tests.** Specified midverse-note piece ordering, bare paragraph
   suffixes, jmp attributes and unknown blocks. Added synthetic coverage for XXF-like
   structures. Conservation uses a decoded independent rescan. Hash tests cover
   registered objects only; fixtures avoid module/function scope conflicts. Real data
   remains local and uncommitted; schemas/synthetic fixtures use no real text.
4. **Fixed — junior contracts.** Added rule diagnostics, trimmed offset endpoints,
   failed-parent exclusion, run identity for empty inputs, report locator allowlisting,
   service failure handling, adapter title/ObjectSpec mapping, exact URI host checks,
   correct policy-before-format expectations for golden IGT, and migration acceptance
   on isolated test state rather than a populated M2 database. These changes are
   reversible clarifications and do not accept ADR-0010.
5. **BLOCKER — WP2.8 M1 compatibility.** Strictly rejecting raw segments in the existing
   `record_tokens` API changes a deliberate M1 contract used by observation-recorder
   and evidence-service fixtures. The plan only permits updating recorder fixtures,
   yet evidence tests also create raw tokens. Before Haiku implementation, the senior
   must choose and specify either a backward-compatible M1 recording path plus a
   strict M2 entry point, or an explicit revised API contract and complete test-fixture
   migration across all callers. Do not weaken assertions or change golden M1 output.
6. **BLOCKER — WP2.2 event projection (resolved as an interval clarification in WP2.2; see its "Interval contract" paragraph).** A single monotone inverse lookup with
   smallest boundary >= target is underspecified for NFC plateaus/expansions and
   later deletions. A deleted suffix event can have no such normalized boundary.
   The senior must define start/end tie-breaking and clamping, with exact composed
   examples for leading/trailing trim, combining-character contraction, reordered
   combining marks, expansion and whole-segment fallback. Raw/final event spans
   must remain valid and auditable; no junior may invent this interval algebra.
7. **RISK — language-profile purity/versioning.** Loading a mutable inventory during
   profile import and changing it under the same profile version changes diagnostics
   and reproducibility. Keep the M2 inventory empty/unverified. A later inventory
   release needs a pinned identity in profile configuration and reviewed governance;
   neither senior review alone nor this corpus establishes linguistic truth.
8. **Verification.** Static cross-checks and an independent local UTF-8 marker scan
   completed. No runtime pipeline, PostgreSQL, migration or realdata pytest run was
   performed: this is a plan review, not M2 implementation validation. The
   independent corpus scan also found 5,389 distinct chapter/verse labels and 5,435 numeric
   verse positions after range expansion; neither reconciles 5,594. License rights
   and expected processing output still require review.

Verdict: NOT READY until items 5–6 have concrete contracts and ADR-0010's decision
is recorded. Unaffected pure-extractor work can proceed under the existing synthetic
fixture rules; real-data processing remains gated on item 2.
