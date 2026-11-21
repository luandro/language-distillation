---
name: harvest
description: Universal indigenous resource harvesting, academic repository spidering, and provenance-tracked raw ingestion
version: 1.0.0
---

# Universal Indigenous Resource Harvester

Harvests linguistic resources (theses, grammars, dictionaries, wordlists, bilingual texts) from academic archives and digital repositories across indigenous Amazonian languages.

## Invariant Directives

1. **Raw Sources Are Immutable:** Downloaded artifacts are saved directly to `var/external/<lang_code>_sources/` with verified SHA-256 digests.
2. **Strict Provenance & Licensing:** Every resource record must specify title, author, year, URI, SHA-256 hash, and access/distillation governance.
3. **Registry Grounding:** All indexed resources are tracked in `docs/research/universal_sources_registry.json`.

## Supported Archives & Repositories

- Curt Nimuendajú Digital Library (`etnolinguistica.org` spider)
- OpenAlex Global Scholarly Graph (`api.openalex.org`)
- IBICT / BDTD (Brazilian National Digital Library of Theses and Dissertations)
- Zenodo Open Science Archive & Language Science Press publications
- Glottolog Typology Reference (`glottolog.org`)
- Wikipedia Reference Graph (`pt.wikipedia.org`)
- ScriptureEarth & Global Recordings Network (parallel scripture & timed audio)

## CLI Operations

```bash
# Search for candidate resources for an ISO-639-3 language code
uv run langpipe harvest search --lang mzr --family Pano

# Search for the next language (e.g. Tikuna 'tca')
uv run langpipe harvest search --lang tca --name Tikuna --family "Ticuna-Yurí"

# List all tracked resources in the registry
uv run langpipe harvest list --lang mzr

# Download an asset to immutable storage with SHA-256 verification
uv run langpipe harvest download --source-id openalex_w12345
```
