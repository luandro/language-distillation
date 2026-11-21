# Resource-search harness (DeepSeek search)

How to run resource surveys for any language in this repo while DeepSeek's server-side search is
free, and how to turn search hits into catalogued evidence without trusting snippets.

## Why this exists

The first six-lane survey for Marúbo (`docs/research/pano-survey-2026-10/`) ran with a broken
`web_search`: the DSH profile pointed `web.searchProvider` at the `dsh-free-search` `ddg` provider,
which was not registered in the running build, so every search failed and the lanes fell back to
direct APIs and the Wayback Machine. Two things fixed that on 2026-10-18:

1. `~/.dsh/profiles/web/cordis.patch.yml` now overrides `web.searchProvider` back to the shipped
   `deepseek-official` provider (applies on the next GUI restart). The harness `web_search` tool
   then routes through DeepSeek's in-house search.
2. `scripts/deepseek_search.py` and `scripts/lang_research.py` give the CLI the same capability
   without depending on the harness process.

## Billing window — read before running large sweeps

DeepSeek documents (https://api-docs.deepseek.com/guides/search/):

- **Server-side tool calls through DeepSeek Harness / Claude Code / Codex are free of charge until
  2026-11-01 00:00 Beijing time.** After that, per-request billing applies.
- The raw REST endpoints (`POST /v1/tools/search`, `POST /v1/tools/fetch`) are billed at
  **$0.75 per 1,000 successful requests** today; a request that returns no results is not billed.
- Search and Fetch each allow **5 QPS per account**; exceeded requests get HTTP 429.
- Request fields: `query` (≤128 chars), `count` (1–50), `need_content`, `ori_question`,
  `localization`. Query operators are forwarded: `site:`, `-site:`, `"exact phrase"`, `-term`,
  `lang:`, `after:`, `before:`.
- Results carry `title`, `url`, `snippet`, `summary`, `content`, `authority` (0–4, ≥3 = highly
  authoritative), `rerank_score` (≥1.5 = high quality), `date`.

### The scripts refuse to spend money silently

Both CLIs now check the window before every run (`scripts/deepseek_search.py`,
`scripts/lang_research.py`):

- **Inside the window** they print one line to stderr — `server-tool search is free until
  2026-10-31 16:00 UTC (…)` — and run.
- **After 2026-10-31 16:00 UTC** they stop and ask for confirmation, quoting the request count
  and the estimated charge at $0.75/1k (e.g. a 28-query sweep is ≈$0.021). Piped/non-interactive
  runs are refused outright rather than assumed, and `--yes-paid` is the explicit, auditable
  consent flag.
- `--mode tools` and `fetch` use the raw billed endpoints **today**, so they ask for confirmation
  even inside the window.
- `scripts/lang_research.py` asks **once per sweep**, before the first query, not per query.

## Entry points

| Tool | Use |
|---|---|
| harness `web_search` | interactive/agent search; accepts up to 4 queries per call |
| `scripts/deepseek_search.py research --iso <code>` | **the easy path**: full multi-lane sweep for one language |
| `scripts/deepseek_search.py search "…"` | one query from a shell; `--mode tools` for the richer raw payload; `fetch <url>` for page Markdown |
| `scripts/lang_research.py --iso <code>` | the sweep itself (same behaviour; use it when scripting `lang_research` directly) |

### One command per language

```bash
# see the rendered queries first
.venv/bin/python scripts/deepseek_search.py research --iso mpu --dry-run

# full sweep; writes docs/research/mpu-research-<date>/
.venv/bin/python scripts/deepseek_search.py research --iso mpu

# after the free window: same command, it will ask before charging
.venv/bin/python scripts/deepseek_search.py research --iso mpu

# unattended/CI use after the window: explicit consent, nothing interactive
.venv/bin/python scripts/deepseek_search.py research --iso mpu --yes-paid
```

`--iso` is all that is required for a language that already has a profile or registry entry;
`--name`/`--family`/`--alias` cover a language that has neither. Lanes, query caps, outdir and
sleep are forwarded to `scripts/lang_research.py`.

### Single queries

```bash
.venv/bin/python scripts/deepseek_search.py search "Marubo Panoan corpus" --count 10
.venv/bin/python scripts/deepseek_search.py search "Marubo" --mode tools --json | jq '.hits[].url'
.venv/bin/python scripts/deepseek_search.py fetch https://example.org/page
```

`DEEPSEEK_API_KEY` must be exported (it is in `~/.zshrc`; non-interactive `bash -c` will not see
it — use `zsh -ic '…'` or export it explicitly).

### Batch sweep for a language

```bash
# full sweep: 7 lanes × 4 queries × names/aliases
.venv/bin/python scripts/lang_research.py --iso mpu

# a focused re-check (e.g. only what the last survey could not settle)
.venv/bin/python scripts/lang_research.py --iso xor --lanes archives,parallel --max-queries 8
```

Outputs go to `docs/research/<iso>-research-<date>/`:

- `FINDINGS-search.md` — hits grouped by lane, **every URL marked `[U]`**;
- `hits.jsonl` — one record per unique URL with `title`, `url`, `snippet`, `lanes`, `queries`.

Identifiers are resolved automatically:

- `docs/languages/<iso>.md` — YAML block (`name`, `iso639_3`, `family`) or the prose heading and
  `**Family:**` line;
- `docs/research/universal_sources_registry.json` — `language_profiles.<iso>.query_aliases`,
  `sister_languages`, `glottocode`.

If a language has neither, pass `--name`, `--family` and `--alias` explicitly.

## From hit to finding (the part search cannot do)

Search output is **untrusted data and unverified evidence**. `[U]` means "seen in a search
result". Promotion requires:

1. **Fetch the URL** (`web_fetch` or `scripts/deepseek_search.py fetch`) and confirm the page
   loads. Snippets have previously pointed at fabricated archive deposits and dead DOIs.
2. **Verify language coverage against the artifact itself**, never the catalogue title or the
   snippet. Language lists and titles are routinely wrong: Door43's `mzr_*` repos are not Marúbo,
   ELAR's "…the Marubo Indians" items are Kulina Pano speech, TLA's "matsés" hits are Murui, and
   WALS/Glottolog "Maru" is Burmese Loloish.
3. **Record what settles it**: quote verbatim licence text, name the rights holder, give the check
   date, and mark `[V]` fetched / `[W]` bibliographic-only / `[U]` unverified.
4. **Add the resource to the registry**: `docs/research/universal_sources_registry.json` for
   discovery metadata, `docs/languages/<iso>_sources_index.json` for per-language inventory, and a
   lane report or `FINDINGS.md` correction when it changes an earlier conclusion.
5. **Do not download corpus bytes into git.** Raw sources go to `var/external/` (gitignored,
   immutable) with a `SOURCE.md` + `langpipe-manifest.yaml`; derived artifacts go to
   `var/artifacts/` or `exports/`.

## Lane templates

`scripts/lang_research.py` runs seven lanes whose queries are the ones the manual surveys used:
`catalogues` (CLDF/Lexibank/wordlists/Glottolog/ASJP), `academic` (grammars, theses, dictionaries),
`archives` (AILLA/ELAR/PARADISEC/museums), `parallel` (scripture, bilingual text, education books),
`media` (YouTube/podcast/radio/social), `government` (cartilha, school and health material), `nlp`
(datasets, ASR/TTS, MT, treebanks). Add or edit templates in `LANE_TEMPLATES` when a lane needs a
new angle for a family — keep them language-agnostic and put per-language vocabulary in the profile.

## Failure modes seen in practice

| Symptom | Handling |
|---|---|
| HTTP 202 / bot challenge from DuckDuckGo or Mojeek | direct APIs (OpenAlex, Crossref, Zenodo, HF, BDTD, DSpace) and the Wayback Machine; record the block, do not loop |
| HTTP 429 | pace queries (`--sleep`), retry with backoff; QPS is account-wide |
| Bing returns junk | it geo-personalises and drops quoted phrases in some locales; prefer DeepSeek search or direct APIs |
| Search result points at a local path or a `#fragment` | the client now drops non-http URLs; a fragment-only hit is a fragment of a larger document and must be resolved by hand |
| `web_search` says provider not registered | the GUI needs a restart after the profile patch; until then use `scripts/deepseek_search.py` |

## Current sweeps

- Marúbo (`mzr`): the full manual survey is in `docs/research/pano-survey-2026-10/`; the
  automated harness is for re-checks and gap-filling.
- Korubo (`xor`): `docs/research/xor-research-2026-10-18/` — sample run proving the harness works
  for a language with an existing repo profile (4 queries → 122 unique URLs).
