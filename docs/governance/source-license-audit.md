# Source License Audit (Marúbo, mzr)

> **Historical record (superseded as a gate).** ADR-0025 removed licenses and ownership
> from the authorization path: a source present in the repository is processed and trained
> on regardless of its license status. The findings below are retained as factual records.
> Read "not trainable" as "license unrecorded", not as a pipeline restriction.

Audit date: 2026-10-18. Scope: local folders under `var/external/` and registry `docs/research/universal_sources_registry.json`.

Rule applied: a license is "verified" only when a primary page or file in the repo states it. Anything else is `UNVERIFIED — not trainable`. No license was inferred.

## Folder inventory

No `LICENSE` or `README` file exists in the source folders under `var/external/` (checked by name; the set has grown since this audit). No license string appears in the extracted `.txt` files (grep, 0 hits).

| Folder | Files (names) | Policy file |
|---|---|---|
| `var/external/marubo_sources/` | academic_lexicon.tsv, Cesarino_2013_QuandoATerraDeixouDeFalar_MitolMarubo.pdf, cesarino_2013.txt, cesarino_layout.txt, Cesarino_Marubo_2017_TeachingsDeathPath.pdf/.txt, costa_1992_padroes_ritmicos.pdf, costa_1992.txt, costa_2000_fonologia_marubo.pdf, costa_2000.txt, Costa_2002_ErgatividadeCindidaEmMarubo.pdf, costa_2002.txt, Costa_2017_InteracoesRestricoesMarubo_Abralin.pdf, costa_2017.txt | created (see below) |
| `var/external/marubo_vocab/` | marubo_lexicon.tsv | created |
| `var/external/parallel_por/` | ACT, EXO, GEN, JAS, JHN, LUK, NEH, RUT (.txt) | created |
| `var/external/glottolog/` | maru1252.json | created |
| `var/external/scriptureearth/` | mzr/ (ACT–XXF .usfm, langpipe-manifest.yaml, policy.yaml) | existing `mzr/policy.yaml` left untouched |

## Source table

Registry line numbers refer to `docs/research/universal_sources_registry.json`.

| Source | Files | Stated license | Evidence | Verified | Register if stated | Status |
|---|---|---|---|---|---|---|
| Cesarino & Marubo 2017, *Teachings of the Death-Path* (zenodo 1008779) | Cesarino_Marubo_2017_TeachingsDeathPath.pdf/.txt | CC-BY-4.0 | Registry :187; Zenodo record https://zenodo.org/records/1008779 shows License "Creative Commons Attribution 4.0 International" (fetched 2026-10-18) | yes (repository record) | CC-BY-4.0 | Stated and verified against repository record. Registry access_category `permissive_academic`. Local file itself carries no license text. |
| Costa 1992, *Padrões rítmicos e marcação de caso em Marubo* (UFRJ Pantheon 11422/3194) | costa_1992_padroes_ritmicos.pdf, costa_1992.txt | "Academic Research / Fair Use" | Registry :209 (and :401 area) | no | not a license statement | UNVERIFIED — not trainable |
| Costa 2000, *Aspectos da Fonologia Marubo* (UFRJ Pantheon 11422/3195) | costa_2000_fonologia_marubo.pdf, costa_2000.txt | "Academic Research / Fair Use" | Registry :231 | no | not a license statement | UNVERIFIED — not trainable |
| Costa 2017, *Interações entre restrições em Marubo* (Revista ABRALIN, doi 10.25189/rabralin.v1i1.727) | Costa_2017_InteracoesRestricoesMarubo_Abralin.pdf, costa_2017.txt | CC-BY-4.0 Open Access | Registry :253 | no (no page fetched; no license text in PDF/txt) | CC-BY-4.0 Open Access | UNVERIFIED — not trainable. Registry local_path (:255) names `costa_2017_abralin.pdf`, which does not exist; actual file is `Costa_2017_...pdf`. |
| Cesarino 2013, *Quando a Terra Deixou de Falar* (Editora 34) | Cesarino_2013_...pdf, cesarino_2013.txt, cesarino_layout.txt | "Monograph / Indigenous Orality Rights" | Registry :271 | no | not a license statement | UNVERIFIED — not trainable |
| Costa 2002, *Ergatividade cindida em Marubo* | Costa_2002_...pdf, costa_2002.txt | none in registry | no registry entry found by name | no | none | UNVERIFIED — not trainable |
| ScriptureEarth mzr corpus | var/external/scriptureearth/mzr/*.usfm | "ScriptureEarth Online Access / Fair Use Distillation" (registry :289). Manifest notes operator check 2026-10-12, "local pipeline distillation permitted; redistribution denied" (langpipe-manifest.yaml, provenance.notes) | Registry :289; manifest provenance | no (operator note only, no license page in repo) | ScriptureEarth Online Access / Fair Use Distillation | UNVERIFIED (no licence on record; informational). Policy at audit time `distill_only`, later rewritten to `direct`/`public` (ADR-0025). |
| parallel_por (ACT–RUT .txt) | 8 book files | none | no registry entry found | no | none | UNVERIFIED — not trainable |
| marubo_vocab lexicon | marubo_lexicon.tsv | none | no registry entry found; no license column/text | no | none | UNVERIFIED — not trainable |
| academic_lexicon.tsv (in marubo_sources) | academic_lexicon.tsv | none | 1 line matched a "source/licence" keyword search; not interpreted | no | none | UNVERIFIED — not trainable |
| Glottolog 5.0, Marúbo (maru1252) — metadata only | maru1252.json | CC BY 4.0 (Glottolog data) | https://glottolog.org/ states "licensed under a Creative Commons Attribution 4.0 International License", linking to https://creativecommons.org/licenses/by/4.0/ (fetched 2026-10-18). https://glottolog.org/meta/licenses returned HTTP 404 on 2026-10-18. | yes (homepage statement) | registry :516 lists policy `permissive_academic` | Verified for the Glottolog dataset. Registry policy label is not a license; used for metadata only. |

Notes:
- Only the Cesarino 2017 and Glottolog entries have a verified license.
- Registry `access_category` values (e.g. `distill_only`) are governance labels, not licenses. They were not used as license evidence.

## Policy files created

Created (local, gitignored under `var/`), all validated with `langpipe.cli.scriptureearth._load_policy` (PolicySpec) via `uv run python`:

- `var/external/marubo_sources/policy.yaml`
- `var/external/marubo_vocab/policy.yaml`
- `var/external/parallel_por/policy.yaml`
- `var/external/glottolog/policy.yaml`

At audit time each contained `mode: distill_only`, `access_class: highly_restricted`, `authority: "unassigned"`. They were later rewritten to `direct`/`public`/`repo-owner` (ADR-0025).

Deviations from the request:
- `access_class: unknown` is not in the `AccessClass` enum (public, community, restricted, highly_restricted). The most restrictive valid value, `highly_restricted`, was used.
- `authority` is a required non-empty field. `"unassigned"` follows the convention already used in `var/external/scriptureearth/mzr/policy.yaml`.
- `scriptureearth/` has no top-level policy file; its policy lives in `mzr/` and was left untouched.

## Open items

- The licence for Costa 1992, Costa 2000, Costa 2002, Costa 2017, Cesarino 2013, and the lexicons is still unrecorded. This is a record outstanding, **not** a condition on processing or training (ADR-0025).
- Registry `local_path` for Costa 2017 was corrected during the ADR-0025 pass.

## Processing status after ADR-0025 (2026-10-18)

Licence and rights findings above remain records only. Under ADR-0025 the presence of a
source in `var/external/` authorizes processing and training, so the pipeline was run over
everything in the repo:

- every source present at processing time registered and ingested (`direct`/`public`/`repo-owner` policies); the database currently holds 14;
- 8 extracted: Costa 1992 (11,094 segments), Costa 2000 (8,273), Costa 2002 (600),
  Costa 2017 (833), Cesarino 2013 (16,519), Cesarino & Marúbo 2017 (803), parallel_por
  (19,493), ScriptureEarth mzr (6,338) — 63,953 segments total;
- not extracted (6 sources at last check): `marubo-vocab` and `marubo-academic-lexicon` (no lexicon/TSV extractor is wired into the pipeline), `glottolog-maru1252` (metadata JSON, no running text), and `vana-rasi`, `smith-2021-twu`, `cldf-oliveiraprotopanoan` (added after the extraction pass; extraction not yet run);
- the 105 Cesarino & Marúbo pairs are still sourced from the loose harvested JSONL; a
  governed IGT run is outstanding.

The licence column below is therefore informational: `UNVERIFIED` means "no licence on
record", not "blocked". Re-check an item with a different access method, or for a new item,
rather than treating a negative as permanent.

## Records added 2026-11-04

These are records, not gates (ADR-0025). Nothing below changes what the pipeline processes or
trains on, and none of it was used to authorize anything.

- **Cesarino & Marubo 2017, *The teachings of the Death-Path*** — CC-BY-4.0 (Zenodo record
  https://zenodo.org/records/1008779, verified above). Status: verified.
- **Costa 2017, *Interações entre restrições em Marubo*** — CC-BY-4.0 per
  `docs/research/universal_sources_registry.json` only. No publisher page or licence file was
  fetched, so this remains **unverified as a record**.
- **Costa 1992, Costa 2000, Costa 2002, Cesarino 2013** — no licence stated in the registry or
  in the local files; copyright sits with the author and publisher. Status: licence unrecorded.
- **Glottolog 5.0 (maru1252)** — CC-BY-4.0 applies to the Glottolog *metadata* data set; the
  repository holds no running text for this source, so only metadata is used.
- **Register** — `registers: [ritual]` appears in the manifests of Cesarino 2013 and
  Cesarino & Marubo 2017. That label is intake metadata only; it does not restrict processing,
  training, or export.
- **Manifests are not edited here.** `manifest_sha256` covers `provenance.notes`, and
  `src/langpipe/ingestion/registration.py:74` raises `SourceConflict` when a registered
  manifest changes, so the `"License unrecorded"` note in the 2017 manifest is left as
  written even though the licence is recorded above. The audit section, not the manifest, is
  the licence record.
