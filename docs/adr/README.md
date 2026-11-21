# Architecture Decision Records

ADRs preserve architectural reasoning.

Each ADR contains Status, Context, Decision, Consequences, Alternatives and supersession links when applicable.

Accepted ADRs are not rewritten to hide history. A changed decision gets a new ADR that supersedes the old one.

ADRs do not replace normative docs; update current docs when architecture changes.

## ADR Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-evidence-first-architecture.md) | Evidence-first architecture | Accepted |
| [0002](0002-postgresql-canonical-store.md) | PostgreSQL as canonical store | Accepted |
| [0003](0003-cldf-interchange.md) | CLDF for interchange | Accepted |
| [0004](0004-eflomal-cold-start-baseline.md) | Eflomal cold-start baseline | Accepted as baseline, not permanent winner |
| [0005](0005-deterministic-synthesis-first.md) | Deterministic synthesis first | Accepted for cold start |
| [0006](0006-decision-models-restricted.md) | Decision models restricted | Accepted for cold start |
| [0007](0007-source-policy-resolution.md) | Source policy resolution | Proposed |
| [0008](0008-identity-idempotency-raw-storage.md) | Identity, idempotency, raw storage | Proposed |
| [0009](0009-relational-lineage-and-append-only-observations.md) | Relational lineage and append-only observations | Proposed |
| [0010](0010-text-processing-derived-segments.md) | Text processing and derived segments | Proposed (Decided for Milestone 2) |
| [0011](0011-parallel-segment-and-token-alignment.md) | Parallel segment and token alignment | Accepted |
| [0012](0012-ebible-acquisition-host.md) | eBible as a second acquisition host for parallel Portuguese Scripture | Proposed |
| [0013](0013-lexical-model-and-review-authority.md) | Lexical domain model, relation mapping, and review authority | Accepted (under delegated authority, owner ratification pending) |
| [0014](0014-review-staleness-and-authority-config.md) | Review staleness and authority config | Accepted (under delegated authority, owner ratification pending) |
| [0015](0015-computed-revocation-impact.md) | Computed revocation impact | Accepted (under delegated authority, owner ratification pending) |
| [0016](0016-cldf-interchange-and-export-eligibility.md) | CLDF interchange mapping and export eligibility | Accepted (under delegated authority, owner ratification pending) |
| [0017](0017-igt-observation-and-morphology-graph.md) | IGT observation and morphology graph | Accepted (under delegated authority, owner ratification pending) |
| [0018](0018-source-use-approvals.md) | Source-use approvals for `review_required` operations | Accepted (under delegated authority, owner ratification pending) |
| [0019](0019-morphology-benchmark-and-method-promotion.md) | Morphology benchmark and method promotion | Accepted (under delegated authority, owner ratification pending) |
| [0020](0020-clef-pivot-quality-judge.md) | Clef pivot-side quality judge | Accepted |
| [0021](0021-lexicon-audit-and-consumer-views.md) | Lexicon audit and consumer views | Accepted |
| [0022](0022-training-eligibility-for-scripture-derived-pairs.md) | Training eligibility for scripture-derived pairs | Superseded by ADR-0025 |
| [0023](0023-source-intake-quality-criteria.md) | Source intake quality criteria | Superseded by ADR-0025 |
| [0024](0024-direct-training-hard-deny-revision.md) | Direct-training hard-deny revision | Superseded by ADR-0025 |
| [0025](0025-presence-based-source-authorization.md) | Presence-based source authorization | Accepted (owner decision, 2026-10-18) |
| [0026](0026-derived-full-phrase-training-rows.md) | Derived full-phrase training rows | Accepted |
| [0027](0027-dictionary-rendering-and-print-pipeline.md) | Dictionary rendering and print pipeline | Accepted |
| [0028](0028-language-profiles-own-corpus-data.md) | Language profiles own corpus-specific data | Accepted (under delegated authority, owner ratification pending) |
