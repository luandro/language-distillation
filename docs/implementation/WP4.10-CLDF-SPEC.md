# WP4.10 — CLDF Interchange: Architectural Specification

> **Superseded policy note (ADR-0025).** Any rule below that blocks processing or
> training because of a source's classification, licence, rights holder, or register is
> historical. Presence in the repository authorizes processing and training; licences
> and ownership are records, not gates.

**Status:** Decided by chief architect under delegated authority (2026-10-15).
**Depends:** WP4.9. **Gate:** 26.
**Governing records:** ADR-0003, ADR-0007, ADR-0013 §6, ADR-0015, new **ADR-0016** (this WP writes it).

This spec settles the open questions for WP4.10. Where it widens the M4-PLAN "Own" list,
the widening is explicit (§8) and MUST be recorded in M4-PLAN when the WP lands.

---

## 0. Decisions at a glance

| # | Question | Decision |
|---|---|---|
| D1 | Dependency | Add `pycldf>=1.39` as a **core** dependency (pure Python, keeps CI compiler-free). Add a mypy override `ignore_missing_imports` for `pycldf.*`, `csvw.*`, `clldutils.*`. Import pycldf **lazily** inside `langpipe.cldf` functions, never at CLI module import time. |
| D2 | Export module | **`Dictionary`** (EntryTable + SenseTable + LanguageTable). Wordlist export is deferred. |
| D3 | Import modules | Read **both** `Wordlist` and `Dictionary` datasets. |
| D4 | Import shape | Two stages, mirroring the wordlist path: a governed **EXTRACTION** run (`langpipe.cldf-extract`), then the existing **LexicalService** (Stage 6, `LEXICAL_INDUCTION`) using a new pure inducer `cldf_lexical@0.1.0`. A convenience `import_dataset()` runs both. |
| D5 | Importer input | An **already-registered** source id/key (`source_type` ∈ {`WORDLIST`, `DICTIONARY`}). The importer never registers sources and never reads the original directory. |
| D6 | Export run | `ProcessingRun(stage=EXPORT, tool="langpipe.cldf-export")`; one `CLDF_EXPORT` artifact per written file, plus a `cldf-export-report` v1 artifact (`ArtifactKind.OTHER`, same convention as the lexical induction report). |
| D7 | Eligibility | A row is exported only if `lineage_eligibility(..., REDISTRIBUTE_DERIVED)` is **`ALLOW`** for every entity contributing to it. `REVIEW_REQUIRED` counts as not eligible. |
| D8 | Nothing eligible | **Fail closed**: raise `NoEligibleRecords`, write no run, no artifact, and no output directory. Exit code is non-zero. |
| D9 | Invariant 6 | Handled by the structure of the code: the exporter **writes no ExampleTable** in M4 and has **no code path** that reads `Segment`, `TokenOccurrence`, `SourceObject` bytes, or the raw store. Tests prove both (§6). |
| D10 | Attribution | A convention for `SourcePolicy.restrictions["attribution"]`, emitted as CLDF `prov:wasDerivedFrom`, `dc:license`, and a per-row `Source` column backed by `sources.bib`. If a source requires attribution but its attribution data is missing, the export is **refused**. |
| D11 | CLI | `langpipe cldf export` and `langpipe cldf import`. |

---

## 1. Why a Dictionary for export (D2)

Our model is `Lexeme → Sense(glosses, concept_id?)`. CLDF Dictionary is `Entry → Sense`, so
it maps one to one:

- **Homonymy and polysemy are preserved** (Invariant 7). Two lexemes with the same form become
  two entries. One lexeme with two senses becomes one entry with two senses.
- **Wordlist would force us to invent concepts.** Every FormTable row needs a `Parameter_ID`.
  Most of our senses have no `Concept` (the wordlist and alignment inducers deliberately mint
  none: "no concept minted from a gloss"). A Wordlist export would have to create a parameter
  per gloss, which manufactures a comparative-concept claim we never made.
- Wordlist export can be added later behind its own ADR, once a concept-linking policy exists
  (Concepticon mapping review). Record this as **OPEN** in ADR-0016.

Import must accept Wordlists anyway, because most external lexical CLDF (for example
Lexibank) is Wordlist.

---

## 2. CLDFImporter contract

### 2.1 Module and API — `src/langpipe/cldf/importer.py`

```python
CLDF_EXTRACT_TOOL = "langpipe.cldf-extract"
SNAPSHOT_SCHEMA = "cldf-lexical-snapshot"      # v1, ArtifactKind.EXTRACTION_SNAPSHOT
REPORT_SCHEMA   = "cldf-extraction-report"     # v1, ArtifactKind.EXTRACTION_REPORT

@dataclass(frozen=True)
class CLDFExtractionResult:
    source: Source
    run: ProcessingRun
    snapshot: Artifact
    report: Artifact
    reused: bool

class CLDFImporter:
    def __init__(self, ctx: AppContext) -> None: ...

    def extract(self, source_ref: str, *, target_language: str | None = None,
                contact_language: str | None = None) -> CLDFExtractionResult: ...

    def import_dataset(self, source_ref: str, *, target_language: str | None = None,
                       contact_language: str | None = None,
                       policy: LexicalScorePolicy | None = None
                       ) -> tuple[CLDFExtractionResult, LexicalInductionResult]:
        """extract() then LexicalService.induce_lexicon(run.id, method="cldf_lexical@0.1.0")."""
```

### 2.2 Registration (operator step, outside the importer)

The operator writes a normal `SourceManifest` with `source_type: wordlist | dictionary` and
lists **every** dataset file under `objects`: the `*-metadata.json` (`application/json`), each
CSV (`text/csv`), and `sources.bib` if present (`application/x-bibtex`). Then
`langpipe source register` / `ingest` runs as usual. A CLDF dataset is a multi-object
source; no new registration path is needed.

### 2.3 `extract()` order. The order is part of the contract, as in `ingest/wordlist.py`.

1. Resolve the source. Require `source_type ∈ {WORDLIST, DICTIONARY}`; otherwise raise
   `UnsupportedSource("no_extractor")`. If the source is revoked: one audit event, then `PolicyDenied(INGEST)`.
2. Call `ingest_source(ctx, source.id)` under the `Operation.INGEST` gate.
3. **Structural check, metadata only, no bytes read yet.** There must be exactly one object whose
   `original_path` ends in `metadata.json`. Otherwise raise `SchemaViolation`.
4. Gate `Operation.EXTRACT`: same `_require_extract_allowed` semantics (one `POLICY_DENIED`
   audit event, nothing else written). **Factor the helper out of `ingest/wordlist.py`
   into a shared `ingest/governed.py`; do not copy it.**
5. **Materialize** every object into a fresh `tempfile.TemporaryDirectory`. Each object goes
   through `_read_verified` (blob row present, `raw_store.verify`, `read_bytes`) and is
   written at its registered relative `original_path`. pycldf only ever sees this temp copy.
6. **Containment check before parsing:** every table `url` in the metadata (and `sources.bib`)
   must resolve to one of the registered object paths. Reject `..`, absolute paths, and any URL
   scheme. Otherwise raise `SchemaViolation`. pycldf MUST NOT fetch anything over the network.
7. `pycldf.Dataset.from_metadata(tmp/metadata)`. Require the module to be `Wordlist` or
   `Dictionary` (otherwise `UnsupportedSource("no_extractor")`). Run `ds.validate()`; a
   failure raises `ExtractionFailed`. Exception messages are never persisted (run fails with
   the exception *type* only).
8. Normalize the dataset into a **lexical snapshot** (§2.4). It is canonical JSON with rows
   sorted by `(table, ID)`. Store it as an `EXTRACTION_SNAPSHOT` artifact whose `access_class`
   is the most restrictive of the source's objects.
9. Persist, in one transaction: the snapshot artifact, the IDs-only report artifact, run I/O
   (all objects are INPUT, both artifacts are OUTPUT), and `derived_from` edges from the
   snapshot and the report to every object. Mark the run succeeded.
10. Idempotency: `RunRecorder.find_reusable(EXTRACTION, CLDF_EXTRACT_TOOL, config, input_ids)`
    with `config = {target_language, contact_language, snapshot_schema_version, pycldf_major_minor}`.

Language resolution is the same as `_resolve_languages` in `ingest/wordlist.py`. Factor it out
into the same shared helper.

### 2.4 Snapshot normalization (pure function `snapshot_from_dataset(ds, target, contact)`)

The snapshot is the **only** thing Stage 6 reads, so pycldf never runs inside Stage 6.

| CLDF | Snapshot record |
|---|---|
| `LanguageTable` row | maps `Language_ID → ISO639P3code`. If there is no LanguageTable, `Language_ID` must itself be a 3-letter code. |
| Wordlist `FormTable` row | `{kind:"form", row_id, table_path, language, form (Form, else Value), parameter_id, cldf_sources[]}` |
| Dictionary `EntryTable` row | `{kind:"entry", row_id, table_path, language, headword, pos?, cldf_sources[]}` |
| Dictionary `SenseTable` row | `{kind:"sense", row_id, entry_id, description, cldf_sources[]}` |
| `ParameterTable` row | `{kind:"parameter", id, name, concepticon_id?}` |

Rules:

- Rows whose resolved language ≠ `target_language` are **skipped and counted**
  (`skipped.other_language`). A related-language form never becomes a target lexeme (Invariant 8).
  Rows with an unmappable language are counted under `skipped.unmapped_language`.
- **Upstream status, confidence, or validation columns are ignored.** Our own export's `Status` column
  is never read back. Nothing imported is ever above `CANDIDATE` before scoring (Invariant 3).
- `ExampleTable`, `CognateTable`, `BorrowingTable`, `CodeTable`, and `ValueTable` (StructureDataset) are
  **not imported in M4**. They are counted under `ignored_tables`. IGT import is M5.
- The text is NFC-normalized. Empty forms or headwords are skipped and counted, never repaired.
- `table_path` records which `SourceObject` (CSV) the row came from, so lineage can name it.

### 2.5 Pure inducer — `cldf_lexical@0.1.0`

This lives in `src/langpipe/lexicon/adapters/cldf.py` and is registered in `lexicon/registry.py`.
Input: `LexicalInductionInput.data` = snapshot bytes; `source_id`; `source_object_id` = metadata
object id; plus a `table_objects: Mapping[path, source_object_id]` carried inside the snapshot.

Mapping (aligned with `WordlistAdapter` behaviour so the two import paths agree):

- **Wordlist:** group FormTable rows by `form` and create **one `Lexeme`** per distinct target
  form. This is the same "one headword = one lexeme" rule as `wordlist_tabular`, and is recorded
  as such in the report. Each row creates one `Sense` with
  `glosses = {contact_language: [parameter.name]}`, linked to the `Concept` of its parameter.
- **Dictionary:** **one `Lexeme` per EntryTable row**, so homonymous entries stay separate. Each
  SenseTable row creates one `Sense` with `glosses = {contact_language: [description]}`. `pos`
  is copied from `Part_Of_Speech`, because it is an observed upstream assertion, not something
  we invent.
- **Concept:** one per referenced ParameterTable row:
  `concept_type="cldf_parameter"`, `canonical_label=Name`, `concepticon_id=Concepticon_ID`,
  `external_urn=f"cldf:{source.key}:parameter:{ID}"`. This is a recorded upstream claim, not a
  minted one, so it does not violate the "no concept from a gloss" rule.
- `lemma_form_id = None`. No `Form` is minted, which matches `wordlist_tabular`. The surface lives
  in the evidence claim (see the exporter §3.4).
- **Evidence:** one `EvidenceItem(kind=DICTIONARY_ASSERTION, polarity=SUPPORTS)` per row. Its
  `target_id` is the lexeme (Wordlist) or the sense (Dictionary sense rows). It sets
  `claim={"headword": form, "gloss": ..., "cldf_row_id": ..., "cldf_table": ..., "cldf_sources": [...]}`,
  `source_id`, and `independence_group` (defaulting to the source id, as for wordlists).
  The claim key is named **`headword`** in both adapters so the exporter has a single lookup.
- **Lineage:** each evidence item is `derived_from` its row's CSV `SourceObject`. Lexeme and sense
  edges follow the same pattern as `wordlist.py` lines 299–331 (to run, parent lexeme, and evidence).
  Each concept is `derived_from` the ParameterTable CSV object.
- **Status** comes from `LexicalScorePolicy` (`supported` at most). Never `validated`.

### 2.6 LexicalService change (scope widening)

Add a third mode, `_CLDF_MODE`: the input run has `stage is EXTRACTION and tool_name == CLDF_EXTRACT_TOOL`
and the method family is `cldf_lexical`. Plan:

- objects = the run's INPUT source objects
- `_ensure_lexicon_allowed` over them (`DISTILL_LEXICON` gate, unchanged)
- one input whose `data` is the **snapshot artifact bytes**, read via `artifact_store.verify`
  then `read_bytes`

Everything else (locking, reuse, atomic persist, report) is unchanged.

---

## 3. CLDFExporter contract

### 3.1 Module and API — `src/langpipe/cldf/exporter.py`

```python
CLDF_EXPORT_TOOL = "langpipe.cldf-export"
EXPORT_REPORT_SCHEMA = "cldf-export-report"   # v1, ArtifactKind.OTHER
EXPORTER_VERSION = "0.1.0"

@dataclass(frozen=True)
class CLDFExportResult:
    run: ProcessingRun
    output_dir: Path
    files: tuple[Artifact, ...]       # ArtifactKind.CLDF_EXPORT, one per file
    report: Artifact
    exported: Mapping[str, int]       # entries, senses, languages, sources
    omitted: Mapping[str, int]        # by reason (§3.3); describes this call, not the stored report
    reused: bool

class CLDFExporter:
    def __init__(self, ctx: AppContext) -> None: ...
    def export(self, *, language: str, output_dir: Path,
               include_supported: bool = False) -> CLDFExportResult: ...
```

Use a class, for symmetry with `CLDFImporter`, `WordlistExtractor`, and `LexicalService`.
All its dependencies come through `AppContext`.

### 3.2 Pipeline

1. **Preflight on the output directory.** `output_dir` must not exist, or must be an empty directory.
   Otherwise raise `SchemaViolation`. Never overwrite or merge.
2. **Select.** `repo.list_lexemes_by_language(language)`; for each, `list_senses_for_lexeme`.
   Status threshold: `{VALIDATED}`, or `{VALIDATED, SUPPORTED}` when `include_supported`.
   `CANDIDATE`, `REJECTED`, and `DEPRECATED` are never exported.
3. **Eligibility (D7).** For every candidate row, compute
   `lineage_eligibility(repo, id, Operation.REDISTRIBUTE_DERIVED)` for **each** contributing entity:
   the lexeme, each sense, the sense's concept (if any), and the form source (Form id or the
   evidence item used for the headword, §3.4). A row is kept only if **all** are `ALLOW`.
   Cache results per id for the duration of the call.
4. **Entry assembly.** Senses that fail status or eligibility are dropped. **An entry with zero
   exportable senses is omitted entirely**: a bare form with no meaning is noise, and dropping it
   avoids leaking a form whose only justification was ineligible.
5. **Nothing eligible (D8).** If zero entries remain, raise `NoEligibleRecords` (a new
   `LangpipeError`, fixed message, no payload). Before raising, write **one** `POLICY_DENIED`
   audit event per *denying source* (sorted, deduplicated, `run_id=None`,
   `details={"operation":"redistribute_derived","decision":...}`). Nothing else is written.
6. **Attribution collection (§3.5).** Collect the union of ancestor sources over every exported
   entity, using `ancestor_source_ids`.
7. **Write to staging.** Write into `output_dir.parent / f".{name}.staging-{run_id}"` using
   pycldf `Dictionary`: `ds.write(EntryTable=..., SenseTable=..., LanguageTable=...)`,
   plus `ds.add_sources(...)`. Rows are sorted by our ids, and the metadata carries **no
   timestamps**, so output is byte-deterministic for a given selection.
8. **Validate.** `pycldf.Dataset.from_metadata(staging / "Dictionary-metadata.json").validate()`
   must return True. On any failure: run FAILED (exception type only), staging removed, nothing renamed.
9. **Commit (TOCTOU guard).** In one transaction: `repo.lock_sources(sorted(contributing_sources))`,
   then **re-run eligibility and the status check** for every exported id. If anything changed
   (a source revoked mid-export, or a status flipped), abort: run FAILED, staging removed.
   Otherwise persist the file artifacts, the report, run I/O, and lineage, then mark the run succeeded.
10. **Publish.** `os.replace(staging, output_dir)`. If the target is an empty directory, remove
    it first. The rename happens **after** commit, so a crash leaves at most an orphan staging dir
    and never a published but unrecorded export.

### 3.3 Omission reasons in the report

The report counts these reasons, with ids only: `status_below_threshold`, `denied`,
`review_required`, `revoked` (any revoked ancestor; reported separately from `denied` using
`revoked_ancestor_ids`), `no_form`, `ambiguous_form`, `no_exportable_sense`. It also counts
`stale_dependent`: exported rows that carry an outgoing `STALE_DEPENDENT` edge. These are
**counted but not filtered in M4**. ADR-0014 cascading recalculation is still OPEN; add a TODO
linked to `REVIEW-WORKFLOW.md`.

### 3.4 Where the exported form text comes from (and why it cannot be prose)

Resolve the form in this order. **There is no other path.**

1. `lexeme.lemma_form_id` → `repo.get_form(id).text`, which is a lexical form observation.
   *Repository addition:* `get_form(form_id) -> Form` (NotFound). Add it to the protocol, the
   memory backend, and the PG backend, with a contract test.
2. Otherwise, take the `claim["headword"]` of `EvidenceItem`s with `kind=DICTIONARY_ASSERTION`,
   `polarity=SUPPORTS`, `target_id ∈ {lexeme} ∪ senses`, **each of which is itself `ALLOW`
   for REDISTRIBUTE_DERIVED**. If exactly one distinct NFC headword is found, use it. If several
   distinct headwords are found, the row is omitted as `ambiguous_form` (never pick one). If none
   are found, the row is omitted as `no_form`.

Any other `claim` key (`note`, the raw row) is **never** read by the exporter.

### 3.5 Invariant 6: how the firewall is built

The guarantee comes from the structure of the code, not from a filter:

- **No ExampleTable.** M4 export has no example sentences of any origin. Examples are deferred
  until IGT (M5), where an explicit `DIRECT`-only eligibility rule will be designed under its own ADR.
- **No access to raw or segment data.** `cldf/exporter.py` MUST NOT import or call `raw_store`,
  `get_segment`, `get_token`, `list_source_objects`, or any extraction module. This is enforced
  by an import/attribute guard test (§6) as well as by review.
- **Output fields are limited to:** the form text (§3.4), `Sense.glosses`, `Sense.domain/register`,
  `Lexeme.pos`, the `Concept` label and Concepticon id, ids, the status, and attribution
  metadata. Evidence `note` fields, `Provenance.notes`, and report contents are never emitted.
- Lexemes derived from a `distill_only` corpus are **derived knowledge** and may be exported,
  but only if the steward explicitly allowed `redistribute_derived` (its baseline is
  DEFAULT_DENY in every mode, `policy.py:58`). Their source sentences can never appear.

### 3.6 Attribution metadata (D10)

**Convention** (documented in `docs/GOVERNANCE.md`). It uses the existing JSON
`SourcePolicy.restrictions`, so there is **no schema migration**:

```yaml
policy:
  restrictions:
    attribution:
      required: true
      license: "CC-BY-4.0"            # SPDX id
      license_url: "https://creativecommons.org/licenses/by/4.0/"
      text: "Bíblia Livre (porbr2018), CC BY 4.0 BR, via eBible.org"
```

Emission:

- **`prov:wasDerivedFrom`** in the dataset metadata gets one object per contributing source,
  sorted by key: `{"rdf:about": "langpipe:source:<key>", "dc:title": title,
  "dc:license": license_url|license, "dc:rightsHolder": provenance.rights_holder,
  "dc:bibliographicCitation": attribution.text}`.
- **`dc:license`** at the dataset level is set only if every contributing source declares the
  same license. Otherwise it is omitted, and `rdfs:comment` states that licenses vary by source
  and points to `prov:wasDerivedFrom`.
- **Per-row attribution:** EntryTable and SenseTable get a `Source` column whose values are the
  contributing source keys of that row. `sources.bib` holds one `@misc{<key>, title=..., note=<attribution.text>, howpublished=<license_url>}` per contributing source.
- **Fail closed:** if `attribution.required` is true but `text` or `license` is missing, raise
  `SchemaViolation` before staging. Attribution is never silently dropped.
- `Provenance.notes`, `acquired_from` paths, `authority`, and internal ids are **never** exported.

### 3.7 Table layout

- **EntryTable:** `ID` (= lexeme id), `Language_ID`, `Headword`, `Part_Of_Speech`, `Source`, and
  `Status` (added only when `include_supported`).
- **SenseTable:** `ID` (= sense id), `Entry_ID`, `Description` (the contact-language glosses
  joined with `; `, using the sorted first gloss language), `Glosses` (a JSON-string column with the
  full `{lang: [..]}` map), `Concept_Label`, `Concepticon_ID`, `Domain`, `Register`, `Source`,
  and `Status` (only when `include_supported`).
- **LanguageTable:** one row: `ID=<lang>`, `ISO639P3code=<lang>`, `Name` taken from the language
  profile if one exists.

### 3.8 Run, artifacts, lineage, idempotency

- **Run:** `stage=EXPORT`, `tool=CLDF_EXPORT_TOOL`. Its config is
  `{language, include_supported, exporter_version, dataset_module:"Dictionary", selection_digest}`,
  where `selection_digest` = sha256 of canonical JSON of the sorted `(id, status)` pairs **plus**
  the attribution payload. This means a status flip or a changed license produces a new run, even
  though the input ids are the same.
- **Inputs:** the exported lexeme, sense, and concept ids (`RunIoRole.INPUT`).
- **Artifacts:** one `CLDF_EXPORT` artifact per file (`application/json`, `text/csv`,
  `application/x-bibtex`; `schema_name="cldf-dictionary"`). `access_class` = the most restrictive
  over the contributing sources' policies. The report is `ArtifactKind.OTHER`,
  `schema_name="cldf-export-report"`, v1, and contains ids, enum values, counts, and file digests only.
- **Lineage:** each table artifact is `derived_from` every entity whose rows it contains. The
  metadata JSON and `sources.bib` artifacts are `derived_from` the table artifacts. This is how
  WP4.9 `revocation_impact` reaches exports (C9: "… → export").
- **Reuse:** if `find_reusable` hits, re-materialize the files from the artifact store (each one
  verified) into `output_dir` and return `reused=True`. No new rows are written.
- **Which selection `exported` and `omitted` describe:** the selection of *this* call, for a reused
  export as well as a fresh one. The digest pins the exported rows, not the rows that were left
  out, so an ineligible, stale or revoked row can join or change reason after the original run
  while the run stays reusable; reporting the stored payload's counts would under-report the
  governance pressure ADR-0016 keeps visible. The run's stored report artifact is unchanged and
  remains the historical record of what its own run counted.
- **Logs:** ids and counts only.

---

## 4. CLI — `src/langpipe/cli/cldf.py`

Registered as `app.add_typer(cldf_app, name="cldf")`. Uses `get_context` and `@guarded`, like the other command groups.

```
langpipe cldf import <source-ref> [--target-language L] [--contact-language L] [--extract-only]
langpipe cldf export --language <lang> --output-dir <dir> [--include-supported]
```

- `import` by default runs `import_dataset` (extraction + Stage 6). `--extract-only` stops after
  the extraction run, matching the existing wordlist and lexicon two-step flow.
- Output is `key=value` lines with ids and counts only (run ids, artifact ids, exported or omitted
  counts). Forms and glosses are never printed.
- `NoEligibleRecords` and `PolicyDenied` map to the existing `guarded` non-zero exit codes. Add a
  code for `NoEligibleRecords` in the guard map.
- Do **not** add a `validate` subcommand. Validation is internal (§3.2 step 8), and pycldf ships
  `cldf validate` for operators.

---

## 5. ADR-0016 (write it in this WP)

Title: **"CLDF interchange mapping and export eligibility."** It records:

- Dictionary export and Wordlist+Dictionary import (with the OPEN item: Wordlist export).
- Two-stage import through a snapshot artifact, with pycldf confined to extraction.
- The ALLOW-only eligibility rule, the fail-closed empty export, and the staging-then-rename
  publish with an eligibility re-check under the lock.
- No examples in M4 export (Invariant 6 enforced structurally).
- The `restrictions.attribution` convention.
- The headword-resolution order and the `ambiguous_form` refusal.

Also update: `PIPELINE-CONTRACTS.md` (CLDF import/export stage contracts), `GOVERNANCE.md`
(the attribution convention and export eligibility), `docs/adr/README.md`, and an M4-PLAN WP4.10
note listing the scope widening in §8.

---

## 6. Acceptance tests

`LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest tests/unit/test_cldf_interchange.py tests/service/test_cldf_governance.py -q`

Build the fixtures in tests with `tests/service/manifests.py` and `tmp_path` CLDF datasets written
by pycldf in the test itself. Do **not** edit `tests/golden/fixture` (that belongs to WP4.11).

### 6.1 `tests/unit/test_cldf_interchange.py` (pure / memory backend)

1. `snapshot_from_dataset` on a Wordlist: rows are mapped, sorted, NFC-normalized, and other-language rows are skipped and counted.
2. Same for a Dictionary: EntryTable and SenseTable are mapped, and two homonymous entries stay two records.
3. Upstream `Status` / `Validated` columns are ignored. The snapshot carries no status.
4. `cldf_lexical` inducer on a Wordlist: one lexeme per distinct form, one sense per row, concepts carry the Concepticon id and `external_urn`, every status is ≤ `SUPPORTED`, and the evidence claim key is `headword`.
5. Same inducer on a Dictionary: one lexeme per entry, and `pos` is copied over.
6. Lineage: every evidence item is `derived_from` its CSV object, and every concept is `derived_from` the ParameterTable object.
7. Containment: a metadata table `url` of `../x.csv`, an absolute path, or `http://…` raises `SchemaViolation` before parsing.
8. Exporter table builder (pure part): the Entry and Sense rows, the `Status` column present only with `include_supported`, the `Glosses` JSON column, and deterministic ordering.
9. Headword resolution: `lemma_form_id` takes precedence; the evidence fallback works; two distinct headwords give `ambiguous_form`; none gives `no_form`.
10. Attribution builder: a single shared license sets `dc:license`; mixed licenses omit it and list each source; `required: true` with a missing `text` raises `SchemaViolation`; `Provenance.notes` never appears.
11. **Round-trip:** export then import produces equal (form, gloss) pairs, and every re-imported record is `CANDIDATE` or `SUPPORTED`. **Never `VALIDATED`.**
12. Determinism: two exports of the same selection into different directories give byte-identical files.
13. pycldf validation: the exported directory passes `Dataset.from_metadata(...).validate()`.
14. CLI (`CliRunner`): `cldf export` and `cldf import` print only `key=value` id/count lines (assert that no fixture gloss or form substring appears), and the non-zero exit code on `NoEligibleRecords`.

### 6.2 `tests/service/test_cldf_governance.py` (PostgreSQL)

1. Import governance: an `exclude` source is never ingested; an `archive_only` source is ingested but extraction is denied with one audit event and no run row; a revoked source gets `PolicyDenied`; a source of the wrong type (`parallel_text`) gets `UnsupportedSource`.
2. Import idempotency: a second `extract()` returns `reused=True` and writes no new rows.
3. Default export: only `VALIDATED` lexemes and senses appear. `SUPPORTED` and `CANDIDATE` are absent and there is no `Status` column.
4. `include_supported`: `SUPPORTED` rows appear with `Status`, and `CANDIDATE`/`REJECTED`/`DEPRECATED` stay absent.
5. REDISTRIBUTE_DERIVED default-deny: a validated lexeme from a `direct` source *without* the `redistribute_derived` allow is omitted (`denied`).
6. A mixed-ancestry lexeme (one allowed source and one default-deny source) is omitted, because the most restrictive decision wins.
7. `REVIEW_REQUIRED` ancestry is omitted and counted as `review_required`.
8. **All DENY:** `NoEligibleRecords` is raised; one `POLICY_DENIED` audit event per denying source; no run, no artifact; `output_dir` does not exist.
9. **Revocation (WP4.9 integration):** export succeeds, then the source is revoked, then a re-export omits the rows (`revoked`). `revocation_impact(source)` lists the first export's `CLDF_EXPORT` artifacts.
10. **TOCTOU:** revoke the source between selection and commit (inject a hook or monkeypatch the step 9 re-check). The run ends `FAILED`, the staging dir is removed, and `output_dir` is absent.
11. **Invariant 6 canary:** create a `distill_only` parallel source whose segment text contains a unique multi-word canary sentence, with `redistribute_derived` allowed, run alignment and lexicon induction, and validate some senses. The export succeeds, contains derived lexemes, and **no output file contains the canary sentence or any full segment string**. There is no `ExampleTable` in the metadata.
12. **Firewall guard:** monkeypatch `ctx.raw_store.read_bytes`, `repo.get_segment`, `repo.get_token`, and `repo.list_source_objects` to raise. The export still succeeds.
13. Attribution: a source with a CC-BY attribution block contributes. `prov:wasDerivedFrom` contains its citation, `sources.bib` contains its key, and every row it contributes to lists that key in `Source`.
14. Run records: one `EXPORT` run, one `CLDF_EXPORT` artifact per file with the correct sha256 matching the on-disk bytes, the lineage edges from §3.8, and a report with ids and counts only.
15. Export reuse: an identical second export gives `reused=True`, byte-identical files, and no new rows. A status flip produces a new run (selection digest).
16. Output-dir safety: a non-empty `output_dir` raises `SchemaViolation` and nothing is written.

Also run `scripts/ci.sh` (it must stay green with zero skips), the repository contract tests for
`get_form`, and the golden M1–M3 tests (unchanged semantics).

---

## 7. Remaining uncertainty

- Behaviour of pycldf `validate()` on custom columns (`Glosses`, `Status`) varies by version.
  Declare them explicitly via `ds.add_columns` with datatypes. If ≥1.39 rejects one, pin the minimum
  version that works and record it in ADR-0016.
- Exporting `stale_dependent` rows is a known gap (counted, not filtered) until the ADR-0014
  cascade lands.
- Wordlist export and example sentences are deliberately OPEN.

## 8. Scope widening beyond the M4-PLAN "Own" list (record in M4-PLAN)

- `src/langpipe/lexicon/adapters/cldf.py`, `lexicon/registry.py`, and `lexicon/service.py` (third mode).
- `src/langpipe/ingest/governed.py`: shared `_require_extract_allowed`, `_resolve_languages`,
  and `_read_verified`, extracted out of `ingest/wordlist.py` (no behaviour change).
- `storage/repository.py` and both backends: `get_form(form_id)`.
- `domain/errors.py`: `NoEligibleRecords`. `cli/app.py`: register `cldf`. `cli/context.py`: exit code.
- `pyproject.toml`: the dependency and the mypy override.
- Docs: ADR-0016, PIPELINE-CONTRACTS, GOVERNANCE, and the ADR index.
