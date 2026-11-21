# ADR-0028: Language profiles own corpus-specific data

**Status:** Accepted (under delegated authority, owner ratification pending)

## Context

AGENTS.md requires that "language-specific behavior MUST be isolated behind a language
profile/adapter" and that generic pipeline code contain no language-specific rules.
`tests/unit/languages/test_language_isolation.py` enforces this by scanning `src/` for
`mzr`, `marubo` and `marúbo`, allowlisting only `languages/base.py` (which must name the
profiles it registers) and permitting help strings only under `cli/`.

That test failed. The offenders were in generic modules, and they were not one kind of
thing:

- **Corpus identifiers used as data.** `synthesis/derived_rows.py` carried the harvested
  file names, the derived output file names, the PDF path and page range, and the
  provenance strings written into every derived row's lineage, e.g.
  `"harvested:zenodo_1008779_cesarino_marubo_2017_parallel"`.
- **Language codes used as defaults.** `lang: str = "mzr"` on builder entry points.
- **Prose.** Docstrings and comments naming Marúbo where they meant the target language.

Two tempting fixes were rejected. Renaming the provenance constants would break lineage:
those strings identify real harvested artifacts and are persisted in derived rows and
export manifests. Extending the test's allowlist to `synthesis/` would have removed the
signal instead of the offenders, and the rule is not that synthesis is exempt — it is that
generic code carries no language rules.

## Decision

1. **Corpus-specific identifiers are data and live on the language profile.**
   `LanguageProfile` gains `harvested_sources: HarvestedSources` (harvested file names,
   derived output names, provenance strings, PDF location and page range for re-reading
   the printed page) and `chant_provenances: tuple[str, ...]` (provenances whose rows are
   ritual chant). Both default to empty, so `GENERIC_PROFILE` and every existing
   construction are unchanged.
2. **Generic code reaches that data through the registry**, via `profile_for(code)` /
   `LANGUAGE_PROFILES`. No generic module imports `langpipe.languages.mzr.*`.
   `languages/base.py` keeps its deferred `mzr` import to break the registration cycle.
3. **No generic module defaults to a language code.** A language code is supplied by the
   caller, because the code names fields of the caller's data. A silent `"mzr"` default is
   precisely the language rule the test forbids, and a `"und"` default would silently
   produce rows under the wrong language.
4. **Prose in generic modules speaks of the target and contact language**, not of Marúbo.
5. **The isolation allowlist does not grow.** `languages/base.py` remains the only
   allowlisted generic module.

## Consequences

- Provenance strings and file names are byte-identical to the constants they replaced; the
  move is a relocation, not a rename. Derived artifacts rebuild with identical records.
- Adding a language now means declaring its harvested sources on its profile, which is
  where a reader would look for them anyway.
- `synthesis/derived_rows.py` requires `--lang` on the CLI. Callers that relied on the
  implicit `"mzr"` default must pass it.
- Two corpus-specific literals remain in generic code and are acknowledged debt: the
  derived row id prefix `derived:cesarino-2018:` and the persisted report keys `"wenia"` /
  `"zenodo"`. Both are identity strings of already-written artifacts; genericising them
  needs a `DerivedSource.id_prefix` field plus a report-key migration, not a rename.

## Alternatives rejected

- **Allowlist `synthesis/` in the isolation test.** Removes the signal, keeps the coupling.
- **Rename the provenance constants in place.** Desynchronises lineage from the harvested
  artifacts those strings name.
- **Keep per-module copies of `CHANT_PROVENANCES`.** It was already duplicated between
  `synthesis/export_dataset.py` and `training/baseline_eval.py`, i.e. a drift risk; one
  profile-owned source removes it.
