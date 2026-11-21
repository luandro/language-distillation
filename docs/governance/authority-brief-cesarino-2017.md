# Authority brief: Cesarino & Marúbo 2017, *Teachings of the Death-Path*

> **Superseded (ADR-0025).** This brief was written when a recorded authority decision was a
> precondition for training. It no longer is: a source present in the repository is
> authorized for processing and training, and licences, ownership, and register labels are
> records. The source facts below remain useful; the decision questions are historical.

**Purpose:** metadata-only record for the Cesarino & Marúbo 2017 text (formerly a decision
brief under ADR-0022). Contains no Marúbo text.

**Status:** historical. No decision is required to train on this source (ADR-0025). If a
reviewer wishes to record a register label (for example `traditional_public` or
`ritual_restricted`), it is descriptive metadata and does not gate processing or training.

## Source

- Title: *The teachings of the Death-Path* (Cesarino & Marúbo, 2017)
- Local file: `var/external/marubo_sources/Cesarino_Marubo_2017_TeachingsDeathPath.pdf` (and `.txt` extract)
- Registry entry: `docs/research/universal_sources_registry.json` — CC-BY-4.0 (verified on the
  publisher's Zenodo record 2026-10-18)
- Content type: Marúbo ritual and teaching text, interlinear or parallel with Portuguese
- Repo policy: registered with the repository default `direct`/`public`/`repo-owner`
- Harvested rows derived from it (`provenance: harvested:zenodo_1008779_cesarino_marubo_2017_parallel`):
  105 total; when it was the only harvested source it split 30 train / 25 val / 50 test (a
  second harvested file was added later, so totals change). They are trainable (ADR-0025); re-extracting
  them through a governed run for full lineage is still outstanding.

## Register question (optional, descriptive)

1. Should this text carry a register label (`traditional_public`, `ritual_restricted`, …)?
2. Is any attribution text required by the publisher's CC-BY-4.0 terms?
3. Do the 105 harvested rows share the same label?

None of the answers changes whether the source is processed or trained; they are recorded in
the source index/registry.

## Consequences (historical)

- Under the previous gates, "no" meant keeping the 105 rows out of every split. That gate no
  longer exists.
- If a community or publisher objects to use, the operational path is revocation (ADR-0015),
  which flips `lineage_eligibility` and makes the next lineage-governed (CLDF) export omit
  the rows. The file-based HF/Alpaca/ChatML exporter does not consult it yet.

## Governance references

- ADR-0025 (presence-based authorization): `docs/adr/0025-presence-based-source-authorization.md`
- ADR-0022 (training eligibility, superseded): `docs/adr/0022-training-eligibility-for-scripture-derived-pairs.md`
- Policy resolution: ADR-0007; hard denies in `src/langpipe/governance/policy.py`
