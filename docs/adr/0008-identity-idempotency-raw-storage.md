# ADR-0008: Identity, idempotent reruns and raw object storage

**Status:** Proposed

## Context
`ARCHITECTURE.md` requires stable, opaque, prefixed IDs that do not depend on row position or mutable text. It requires stages that are safe to rerun, and raw ingestion that deduplicates bytes physically while keeping provenance distinct. `PIPELINE-CONTRACTS.md` separates Stage 0 (registration) from Stage 1 (raw ingestion). The docs do not specify:

- prefixes for policies, source objects, evidence items, lineage edges or audit events;
- how a rerun is recognized;
- how a source is identified across re-registration;
- the layout of the raw store.

## Decision
1. **ID format** is `<prefix>_<ULID>`, with the ULID as 26 Crockford base32 characters in upper case. New prefixes in addition to those in `ARCHITECTURE.md`: `pol` (SourcePolicy), `sobj` (SourceObject), `ev` (EvidenceItem), `lin` (LineageEdge), `aud` (AuditEvent). `artifact` and `run` are kept as listed. Code never parses meaning out of the ULID part.
2. **Natural keys** prevent semantic duplicates. IDs are not derived from content.
   - Source: a manifest `key` slug that is unique per installation.
   - SourceObject: (`source_id`, `original_path`).
   - Form: (`language`, `orthography_profile`, `text`).
   - LineageEdge: (`from_id`, `to_id`, `kind`).
   - Raw blob: `sha256`.
3. **Run reuse.** `run_key = sha256(canonical_json({stage, tool_name, tool_version, config_hash, sorted input IDs}))`. If a `succeeded` run with the same `run_key` exists, the stage returns that run and writes nothing. `code_revision` is recorded but excluded from `run_key`. Failed runs are kept and never reused.
4. **Re-registering a source.** If the key already exists and `manifest_sha256` matches (canonical JSON of the validated manifest), registration is a no-op that returns the existing source. If the manifest differs, it raises `SourceConflict`. Changing a policy or a manifest needs an explicit future command; it is not an implicit overwrite.
5. **Two-stage storage.**
   - Stage 0 records SourceObject metadata: `sha256`, `size_bytes`, `media_type`, `original_path` and `origin_uri`.
   - Stage 1 copies bytes into a content-addressed, write-once local store at `<data_dir>/raw/sha256/<h[0:2]>/<h[2:4]>/<h>`, re-hashes the bytes and records a `raw_blob` row keyed by `sha256`.
   - If the bytes at `origin_uri` no longer match the registered hash, ingestion fails with `SourceChanged`.
   - Artifacts use the same mechanism under `<data_dir>/artifacts/`.
6. **Write order.** Bytes are written to the store before the database transaction. A rolled-back transaction can leave an orphan blob. That is acceptable because blobs have no semantics without rows. Garbage collection is deferred.

## Consequences
Reruns create no new rows, and IDs stay stable within an installation. IDs differ between fresh installations, so golden snapshots normalize IDs to labels. S3-compatible stores can implement the same `ContentStore` protocol later.

## Alternatives rejected
- **Content-derived (hash) IDs.** They tie identity to text and normalization choices, which conflicts with the ID rule in `ARCHITECTURE.md`.
- **A new run record for every invocation.** Rerun audit history would grow without any semantic change. The audit log already records invocations that matter.
- **Mutating `source_object.storage_uri` after ingestion.** It breaks append-only observations, so a separate `raw_blob` row is used instead.
