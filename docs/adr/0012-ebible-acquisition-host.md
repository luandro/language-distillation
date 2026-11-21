# ADR-0012: eBible as a second acquisition host for parallel Portuguese Scripture

**Status:** Proposed

> **ADR-0025 note:** the licence wording in this ADR predates the presence-based
> authorization rule. The acquisition-host validation it discusses is an adapter input
> contract (provenance fidelity), not a rights gate; a Portuguese package placed under
> `var/external/` is processed because it is present.

## Context

Milestone 3 requires governed dual-source parallel alignment between Marúbo (`mzr`) and Portuguese (`por`).
The existing raw ingestion and validation path (`ScriptureEarthAdapter` in `src/langpipe/ingest/scriptureearth.py`) strictly enforces an acquisition host allow-list: `_ACQUIRED_FROM_HOST = "www.scriptureearth.org"`.

Live investigation (`scratch/research_por.md`) confirmed that ScriptureEarth does not host or publish Portuguese Scripture text bundles. The ScriptureEarth `por` portal (`https://www.scriptureearth.org/00por.php?iso=por`) contains only outbound referral links to third-party repositories, primarily eBible.org (`https://ebible.org`). Ingesting Portuguese Scripture with `acquired_from: https://www.scriptureearth.org/...` would therefore fabricate provenance and violate Invariants 1, 4, and 5 (raw sources are immutable; every derived object retains lineage; source governance is enforced in code).

To satisfy the real-data parallel alignment gate without faking ScriptureEarth provenance, the system requires a governed acquisition path for openly licensed Portuguese USFM corpora hosted on eBible.org.

## Decision

1. **Second Acquisition Host Allow-list**:
   Extend the source ingestion boundary to recognize `https://ebible.org` (and `https://eBible.org`) as an authorized acquisition host for external biblical corpora, implemented either via a dedicated `EBibleAdapter` or by broadening the biblical text adapter configuration with explicit host validation.

2. **Provenance & Manifest Invariants**:
   - Every eBible package manifest must declare `acquired_from` resolving directly to the edition details page on `https://ebible.org/find/details.php?id=<translation_id>`.
   - The package archive URL must resolve to `https://eBible.org/Scriptures/<translation_id>_usfm.zip`.
   - The manifest must capture exact publication metadata, dialect tag (e.g. `por-BR`), publisher/translator credits, and the cryptographic SHA-256 hash of the ingested archive.

3. **Per-Edition Rights Capture & Candidates**:
   - **Primary Candidate: `porbrbsl` (Bíblia Portuguesa Mundial / World Portuguese Bible)**:
     - Edition ID: `PORBSL` / `porbrbsl`
     - Declared License: Public Domain (`public_domain`)
     - Rights Notes: Draft translation undergoing revision. Public domain status eliminates downstream redistribution and attribution restrictions.
   - **Secondary Candidate: `porbr2018` (Bíblia Livre)**:
     - Edition ID: `PORBLJ` / `porbr2018`
     - Declared License: Creative Commons Attribution 4.0 International Brazil (`CC BY 4.0 BR`)
     - Copyright: © 2018 Diego Santos, Mario Sérgio, Marco Teles
     - Governance Impact: Permits adaptation and distillation, but mandates attribution in all derivative exports (e.g. CLDF releases).

4. **Coordinate Scope & Versification Alignment**:
   - The candidate eBible packages contain the 8 books present in the Marúbo corpus (ACT, EXO, GEN, JAS, JHN, LUK, NEH, RUT).
   - Six books (ACT, GEN, JHN, LUK, JAS, RUT) share identical chapter counts and near-identical verse structures with mzr.
   - Two books (EXO with 20 mzr chapters vs 40 standard, and NEH with 7 mzr chapters vs 13 standard) represent structural versification divergences.
   - Until an operator-authorized versification map is provided, the dual-source scope must be formally bounded to the 6 compatible books to prevent heuristic cross-chapter alignment fabrication.

## Consequences

- An eBible adapter will allow legal, auditable ingestion of Brazilian Portuguese Scripture without provenance misattribution.
- Expanding the trusted acquisition hosts requires explicit owner acceptance and strict host validation to prevent arbitrary web scraping.
- Milestone 3 real-data acceptance testing remains blocked until the human project owner accepts this ADR, stages the authorized `por` package with manifest, and signs `scriptureearth_parallel_counts.json`.

## Alternatives Rejected

- **Fabricating a ScriptureEarth Portuguese package**: Packaging eBible files under `acquired_from: https://www.scriptureearth.org/...` would falsely attribute provenance and violate project invariants.
- **Auto-signing counts without operator authorization**: Allowing an automated pipeline run to self-sign or self-authorize external rights violates Invariants 3, 5, and 10.
- **Unverified web scraping of proprietary Portuguese translations**: Scraping modern copyrighted Portuguese versions (e.g. NVI, ARC, ARA) from Bible gateways would violate source rights and licensing governance.
