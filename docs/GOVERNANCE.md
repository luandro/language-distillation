# Governance and Source-Use Enforcement

This document is normative.

## Principle

A source present in the repository is authorized for processing and training. Licenses,
ownership, rights holders, and register labels are recorded as metadata; they are never
authorization gates (ADR-0025). Only an explicit operator `exclude` blocks a source
entirely.

## Source policy modes

| Mode | Meaning |
|---|---|
| `direct` | The repository default: all local operations, including training. |
| `distill_only` | Distillation and training allowed; raw redistribution stays hard-denied. |
| `review_required` | Defined operations require review/approval. |
| `restricted` | Use limited to named workflows/users/locations (operator choice). |
| `archive_only` | Preserve but do not derive computational resources (operator choice). |
| `exclude` | Do not process (the only mode that blocks a source entirely). |

Per-operation restrictions may make a mode stricter. Modes are an operator's explicit
classification, not an inference from a license or a rights holder. A source with no
declared policy defaults to `direct` (`src/langpipe/domain/models/source.py`,
`default_policy_spec()`), and a `distill_only` label only keeps raw redistribution closed —
it never blocks training (ADR-0025).

## Operation permissions

Policy should resolve at least:

```text
read_raw
extract
normalize
align
distill_lexicon
distill_morphology
distill_grammar
audio_align
human_review
third_party_api
cloud_processing
redistribute_raw
redistribute_derived
direct_training
synthetic_generation_support
evaluation
```

Deny overrides allow.

## Access classes

```text
public
community
restricted
highly_restricted
```

## Register policy

A community-defined taxonomy may include:

```text
everyday
pedagogical
administrative
religious
traditional_public
ritual_restricted
historical
technical
unknown
```

Final assignment of sensitive/restricted register labels MAY be recorded by an authorized
reviewer, and automated classifiers MAY create candidates. A register label is metadata: it
does not block processing or training (ADR-0025).

## Derived-resource policy

Derived resources do not automatically inherit the exact access class of their sources, but allowed reuse MUST resolve through explicit policy.

## CLDF export eligibility and attribution

CLDF exports are derived knowledge released outside the pipeline, so every exported row is governed twice: at selection, and again under the source locks immediately before publication ([ADR-0016](adr/0016-cldf-interchange-and-export-eligibility.md)).

Eligibility (WP4.10 D7): a row is exported only if `lineage_eligibility(repo, object_id, REDISTRIBUTE_DERIVED)` is `allow` for **every** contributing entity — the lexeme, each sense, its concept, and the headword source (a `Form` observation or the evidence item whose claim supplies the headword). `REVIEW_REQUIRED` counts as not eligible. Because `REDISTRIBUTE_DERIVED` is default-deny in every policy mode (including `distill_only`), derived lexical knowledge is exportable only when a steward explicitly allowed `redistribute_derived`; the source sentences themselves can never appear, and the exporter writes no example sentences of any origin (the export schema has no example table, so this is structural, not a filter). If nothing is eligible the export fails closed: one `POLICY_DENIED` audit event per denying source and no output at all.

Attribution convention (WP4.10 D10) — recorded in the existing JSON `SourcePolicy.restrictions`, so no schema migration:

```yaml
policy:
  restrictions:
    attribution:
      required: true
      license: "CC-BY-4.0"            # SPDX id
      license_url: "https://creativecommons.org/licenses/by/4.0/"
      text: "Bíblia Livre (porbr2018), CC BY 4.0 BR, via eBible.org"
```

Exports carry this outward as `prov:wasDerivedFrom` (one object per contributing source), a dataset-level `dc:license` only when every contributing source declares the same license, a per-row `Source` column of contributing source keys, and one `@misc` per source in `sources.bib`. A source that requires attribution but lacks `text` or `license` refuses the export; attribution is never silently dropped. `Provenance.notes`, `acquired_from` paths, authority fields and internal ids are never exported. This is a redistribution-time rule (ADR-0016) and is outside ADR-0025's processing/training scope.

## Revocation

On revocation:
1. source access is immediately restricted according to policy;
2. lineage impact analysis identifies descendants;
3. downstream artifacts are marked affected;
4. export/training eligibility is recalculated;
5. affected datasets are rebuilt before reuse;
6. already released external artifacts are reported for governance action.

The system must not pretend already released copies were erased.

Revocation impact is computed over the lineage DAG, not materialized on downstream rows ([ADR-0015](adr/0015-computed-revocation-impact.md)): `revocation_impact` reports the affected descendants, and no `Lexeme`, `Sense`, `ReviewTask`, or `ReviewDecision` state is rewritten when a source is revoked. `lineage_eligibility` is the canonical gate for operational eligibility: it returns `deny` for an object with any revoked ancestor source.

## Training eligibility

A row enters a training run when the `filter_eligible` check accepts it:

```text
row carries a trace id (source_id, policy_id, or provenance)
```

That check is deliberately narrow: it rejects malformed exports, nothing else. Separate,
independent checks apply where they belong:

- the lineage layer (`lineage_eligibility`) denies any object with a revoked ancestor source
  and resolves the governing policies for the operation;
- the file-based HF/Alpaca/ChatML exporter applies a Clef quality filter (`valid`, not
  quarantined) and its own dataset-integrity checks; it does not yet consult
  `lineage_eligibility` or an `exclude` list, so wiring it to the store is outstanding.

License, ownership, rights-holder status, register label, and policy mode are **not** part of
any of these lists (ADR-0025). The "no ancestor is revoked" clause is evaluated by
`lineage_eligibility` at read time (ADR-0015); it is never a stored flag.

## `distill_only` raw-redistribution firewall

`distill_only` no longer blocks training (ADR-0025). It keeps one hard deny:
`redistribute_raw`. Raw or lightly transformed `distill_only` prose does not leave the
pipeline as raw text.

The training gate does not perform this check; it is a distribution rule. Export-level
checks remain the place for it:

Future checks should include exact substring overlap, token/character n-grams, fuzzy similarity, MinHash/LSH near-duplicates, rare source-specific phrases, and named entities where relevant.

Semantic similarity is supplementary only after local validation.

## Third-party services

Every external call must resolve source policy of the payload. If any ancestor denies `third_party_api`, data stays local.

Logs MUST NOT leak restricted content.

## CARE and FAIR

Support Collective Benefit, Authority to Control, Responsibility and Ethics while retaining interoperable technical formats.

The repository records provenance and attribution and keeps a revocation path, but it no
longer enforces community authority as an authorization gate (ADR-0025). If a community or
publisher objects to use of a source, revoke it: lineage impact analysis flags the
dependent objects and the next **lineage-governed** export (CLDF) omits their rows. The
file-based HF/Alpaca/ChatML exporter does not yet consult revocation or `exclude`; that is
tracked in `docs/governance/training-enablement-plan.md` §1a. Already-released artifacts are
reported rather than erased.

## Audit log

Record policy/authority changes, restricted raw access, exports, revocations, validation decisions and dataset publication.

## Mandatory tests

- a row without a trace id is rejected by the training gate, and `corpus:`/`harvested:` rows are accepted (ADR-0025);
- `distill_only` cannot redistribute raw text;
- `exclude` source cannot be processed;
- revoked source blocks dependent export;
- denied third-party payload never calls provider;
- restricted raw endpoint rejects unauthorized actor;
- lineage impact query finds transitive descendants;
- policy change triggers eligibility recalculation.

## Backlog

- **Reviewer and approver identity is asserted, not authenticated (M4/M5).** Reviewer and
  approver identity is an asserted string (`--reviewer`, `--approver`) checked against
  process-local configuration (`LanguageProfile.review_authority`); there is no cryptographic
  authentication. The same gap applies to the M5 source-use approval stewards (ADR-0018
  approvers). This is acceptable for single-operator synthetic work. It MUST be addressed with
  authenticated credentials before multi-reviewer community use or any real-data source approval.
