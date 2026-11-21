# Candidate source licenses: Pano and Brazilian indigenous-language resources

> **ADR-0025:** licence findings below are records, not trainability gates. A source present in
> the repository is processed and trained on regardless; "not usable" here means "no verified
> licence on record", not "blocked by the pipeline".

Research date: 2026-10-18. Research only. No corpora were downloaded, no repo files were edited, nothing was committed.

Verification note: several pages returned errors or bot-check screens (OPUS corpus pages returned 404, a MINEDU record returned a Check Point challenge). Where a finding rests only on a search-result snippet, it is marked "snippet only".

## Summary table

| # | Resource | URL | License as stated | Access date | Parallel text | Training use explicitly permitted | Recommended status |
|---|----------|-----|-------------------|-------------|---------------|-----------------------------------|--------------------|
| 1a | OPUS corpora for Pano languages | https://opus.nlpl.eu/ , https://opus.nlpl.eu/datasets/ , https://opus.nlpl.eu/corpora.php | No Pano corpus found in fetched OPUS pages. Per-corpus licenses not visible. | 2026-10-18 | Unknown | No | Not usable (none confirmed). Re-check the OPUS per-corpus pages with a working browser. |
| 1b | Spanish–Shipibo-Konibo parallel corpus (Galarreta, Melgar, Oncevay, RANLP 2017) | https://aclanthology.org/people/andres-melgar/unverified/ (paper record only) | License not stated in any fetched source | 2026-10-18 | Yes (per paper description) | No | Candidate — verify with rights holder |
| 2a | MINEDU Shipibo-Konibo storybooks, *Kashi betan Awai iní* vols. 1 and 2 (2023) | https://repositorio.minedu.gob.pe/handle/20.500.12799/9867?show=full ; .../9886?show=full | CC BY 4.0 (snippet only; the record page was blocked) | 2026-10-18 | Unknown; likely monolingual storybooks | Not stated beyond the CC BY grant | Candidate — verify with rights holder (confirm record and text content) |
| 2b | MINEDU *Jaskaakin Shipibo joi wishati* (writing manual) | Listed in MINEDU repository (snippet only) | CC BY-NC-ND 2.5 PE (snippet only) | 2026-10-18 | Unknown | No. NC and ND terms block commercial use and derivatives | Not usable for training |
| 2c | MINEDU teacher's guide (2019) | https://repositorio.minedu.gob.pe/handle/20.500.12799/6715 | Not found | 2026-10-18 | Unknown | No | Not usable (license unstated) |
| 2d | Brazil MEC or FUNAI materials for Marubo, Matsés, Yaminahua | None found. UNESCO archive item for Marubo/Matis/Mayoruna teachers: https://www.unesco.org/archives/multimedia/document-2500 | None found; UNESCO item has no license statement | 2026-10-18 | Unknown | No | Not usable (license unstated; not confirmed as MEC) |
| 3 | NLLB-200 distilled 600M base model | https://huggingface.co/facebook/nllb-200-distilled-600M | CC-BY-NC-4.0 (YAML tag `cc-by-nc-4.0`; card text "License: CC-BY-NC") | 2026-10-18 | Not applicable (model) | No for production. Card says "not released for production deployment" and "not intended for document translation" | Not usable for commercial or production use. Research use only. Verify with counsel before fine-tuning and distributing weights. |
| 3b | shp_Latn training data in NLLB-200 | NLLB paper (not fetched) | Not verified | 2026-10-18 | Unknown | Unknown | Unverified. Check the paper appendix and NLLB-Seed/NLLB-MD. |
| 4 | Glottolog repository (metadata) | https://github.com/glottolog/glottolog (LICENSE file: https://github.com/glottolog/glottolog/blob/master/LICENSE) | CC BY 4.0 (LICENSE file text) | 2026-10-18 | No (metadata) | Attribution required. Not a corpus. | Candidate for metadata only, with attribution. Verify whether ISO 639-3-derived tables carry extra redistribution limits (2020 mailing-list post, snippet only). |
| 5 | Marúbo grammar or dictionary with CC-BY or open license | None found. Grammar Watch (https://linguistic-typology.org/grammarwatch) not checked for a Marúbo entry. | None found | 2026-10-18 | Unknown | No | Not usable (no open license found) |

## Notes

- Parallel text: Only the Galarreta et al. Spanish–Shipibo-Konibo corpus is described as parallel. Its license is not stated in the sources fetched.
- Licence status is a record, not a permission gate (ADR-0025): a source present in this repository is processed and trained on; "Not usable" in the tables means "no verified licence on record", not "blocked by the pipeline".
- NLLB base model: Fine-tuning produces a derivative of a CC-BY-NC model. Treat the outputs as non-commercial until a lawyer confirms otherwise. A third-party int8 repackage on Hugging Face is tagged MIT. That tag does not change the terms of the official checkpoint.
- Repo rule: AGENTS.md invariant 6 now says a source present in the repository is authorized for processing and training; licence and ownership are metadata. No source-governance classification is required before ingestion.
