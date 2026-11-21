# ADR-0016: CLDF interchange mapping and export eligibility

**Status:** Accepted (under delegated authority, owner ratification pending)

## Context

M4 delivers governed CLDF interchange (M4-PLAN WP4.10, ADR-0003, ADR-0013 §6). The
word-level data model is `Lexeme → Sense(glosses, concept_id?)`; most senses carry no
`Concept` because no adapter mints a concept from a gloss. External lexical CLDF is
mostly Wordlist. Exports must enforce the governance invariants: machine confidence
never validates (Invariant 3), ambiguity is preserved (Invariant 7), related-language
evidence never becomes target-language truth (Invariant 8), and `distill_only` source
prose never enters an export (the raw-redistribution rule; invariant 6 now means presence-based authorization, ADR-0025). Revocation (ADR-0015) must reach exports
through lineage.

`docs/implementation/WP4.10-CLDF-SPEC.md` settles the open questions; this ADR records
the decisions that outlive the work package.

## Decision

1. **Dictionary export; Wordlist and Dictionary import.** Our `Lexeme → Sense` model
   maps one-to-one onto the CLDF Dictionary (EntryTable + SenseTable): homonymy and
   polysemy are preserved without inventing comparative concepts. A Wordlist export
   would force a `Parameter_ID` onto every form, manufacturing a concept claim we never
   made; it stays an **OPEN** item until a concept-linking policy (Concepticon mapping
   review) exists under its own ADR. Import accepts both modules, because most external
   lexical CLDF (e.g. Lexibank) is Wordlist.

2. **Two-stage import through a snapshot artifact.** A CLDF import mirrors the wordlist
   path: a governed `EXTRACTION` run (`langpipe.cldf-extract`) registers-gates-reads the
   dataset, normalizes it into a versioned ``cldf-lexical-snapshot`` v1 artifact (rows
   sorted by ``(table, ID)``, NFC-normalized, other-language rows skipped and counted,
   upstream status columns ignored), and Stage 6 (`langpipe.lexicon-induce`, method
   ``cldf_lexical@0.1.0``) consumes only that snapshot. pycldf runs inside extraction
   and never inside Stage 6. Import mapping: Wordlist — one Lexeme per distinct form,
   one Sense per row glossed with the parameter name; Dictionary — one Lexeme per
   EntryTable row (homonyms stay separate), `pos` copied as an observed upstream
   assertion; Concepts for Wordlist parameters are recorded upstream claims
   (``concept_type="cldf_parameter"``, source-scoped ``external_urn``), never minted.
   No `Form` is minted on import; the surface lives in the evidence claim (``headword``).

3. **ALLOW-only export eligibility, fail-closed empty export, staged publish.** A row is
   exported only if `lineage_eligibility(..., REDISTRIBUTE_DERIVED)` is `ALLOW` for every
   contributing entity (lexeme, senses, concepts, headword source); `REVIEW_REQUIRED`
   counts as not eligible. If nothing is eligible the export fails closed:
   `NoEligibleRecords`, one `POLICY_DENIED` audit event per denying source, and no run,
   artifact or output directory. Files are written to a staging directory and renamed
   into place only after the run commits; the commit re-runs eligibility and status
   checks under `lock_sources`, so a revocation or status flip between selection and
   publish aborts the export. Run identity pins a ``selection_digest`` (sorted
   ``(id, status)`` pairs plus the attribution payload), so a status flip or changed
   license produces a new run; identical selections re-materialize stored artifacts
   without writing rows.

4. **No examples in M4 export (Invariant 6 enforced structurally).** The exporter writes
   no ExampleTable and has no code path that reads `Segment`, `TokenOccurrence`,
   `SourceObject` bytes or the raw store; an import/attribute guard test proves it. The
   form text comes only from a lemma `Form` observation or the single distinct NFC
   ``headword`` claim of eligible `DICTIONARY_ASSERTION` evidence — two distinct
   headwords are refused as ``ambiguous_form``, never picked among. Example sentences
   of any origin are deferred to M5 IGT work under their own ADR.

5. **The `restrictions["attribution"]` convention.** Source policies carry attribution
   in the existing JSON `restrictions` field — no schema migration:
   ``{required, license (SPDX), license_url, text}``. Exports emit
   `prov:wasDerivedFrom` (one object per contributing source, sorted by key), a
   dataset-level `dc:license` only when every contributing source declares the same
   license (otherwise an `rdfs:comment` points at `prov:wasDerivedFrom`), a per-row
   `Source` column of contributing source keys, and one ``@misc`` per source in
   ``sources.bib``. A source that requires attribution but lacks text or license
   refuses the export.

6. **Headword resolution order.** `lemma_form_id` → `repo.get_form(id).text` first;
   otherwise the evidence fallback above; otherwise the row is omitted (``no_form``).
   A lemma `Form` that is not ``ALLOW`` for `redistribute_derived` omits the row at
   selection and the fallback is not consulted (§3.4: there is no other path — the
   fallback would name a different text source than the lemma).
   The repository gains `get_form(form_id)` on the protocol and both backends.

## Consequences

- Exported datasets are byte-deterministic for a given selection; reuse is exact.
- Revocation walks reach exports: table artifacts derive from the entities whose rows
  they contain, and metadata/``sources.bib`` derive from the tables, so ADR-0015
  impact queries list export artifacts (C9). ``languages.csv`` derives from the
  exported lexemes as well — the language row exists only because those entries
  exist — so every published file is revocation-reachable.
- Exported `stale_dependent` rows are counted, not filtered, until the ADR-0014
  cascading recalculation lands (TODO in `REVIEW-WORKFLOW.md` terms).
- pycldf is a core dependency, imported lazily; pycldf 2.x `validate()` accepts the
  declared custom columns, so no version pin beyond ``>=1.39`` is needed today.

## Alternatives Rejected

- **Wordlist export with per-gloss parameters**: manufactures comparative-concept
  claims no adapter ever made (Invariant 7 pressure in the opposite direction).
- **One-stage import (pycldf inside Stage 6)**: couples the induction service to a
  third-party parser and re-reads raw bytes on every rerun.
- **Filtering `REVIEW_REQUIRED` rows silently**: a row dropped without a counted
  reason hides governance pressure from the report; omissions are enumerated.
- **Writing exports directly into `output_dir`**: a crash mid-write would publish an
  unrecorded or partial dataset; staging-then-rename bounds the failure to an orphan
  staging directory.
- **Carrying attribution in new database columns**: a migration for data the existing
  `restrictions` JSON already represents.

## OPEN items

- Wordlist export (needs a concept-linking policy).
- Example sentences / IGT in exports (M5, `DIRECT`-only eligibility under its own ADR).
- `stale_dependent` filtering (ADR-0014 cascade).
