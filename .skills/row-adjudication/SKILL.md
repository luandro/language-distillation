---
name: row-adjudication
description: Check candidate rows against the printed page - adjudicate citation conflicts (clean_evidence == conflict) in clean-refs JSONL by deterministic grouping, optional XERJ context lookup, two independent free-reader pixel reads, a 400 dpi zoom round and a compare report. Use when verifying candidate spellings or conflicts against scanned pages, or before any promotion of a machine-read row.
---

# Row adjudication

Decide which printed spelling a conflicted row has by reading pixels, without promoting
anything. Output is a worklist, per-reader picks and `compare.json`; the owner decides.

## When to use

- Rows with `clean_evidence: conflict` (candidates cited from several references disagree).
- Any "does the printed page say X" check on a row whose crop exists (`review/img/`).
- Not for: phonology, majority-vote resolution, rewriting `src`, or rows without a crop.

## Pre-flight (stop if it fails)

1. `var/external/<src>/policy.yaml` has `access_class: public`. Anything else: stop and ask
   before any crop goes to a third-party vision model.
2. Crops and `geometry.json` exist (`scripts/build_clean_ref_review.py` writes both).
3. Use `.venv/bin/*`; write only under a fresh `var/artifacts/<task>/` dir.

## Steps

1. **Group deterministically.** `var/artifacts/t1/triage/group.py` (NFD) types each conflict:
   `a` marks only, `ac` marks+case/punct, `b` base letters. Report counts and distinct
   candidate sets. All-mark conflicts are the usual case.
2. **Worklist, split.** One reader must fit its context; parts of at most ~100 rows.
   `.venv/bin/python .skills/row-adjudication/scripts/build_worklist.py --refs exports/parallel_candidates/cesarino_2013_clean_refs.jsonl --img-dir var/artifacts/cesarino_2013/review/img --out var/artifacts/<task>/`
   writes `worklist.json` and `part<i>.json` (global `idx`, `ref`, `src`, `candidates`, `crop`).
3. **Context lookup (optional).** For a refrain, what else the sources print: see XERJ below.
   Context for the reviewer, never a vote.
4. **Two independent free readers, tight crops, accept on agreement.** Benchmarked in
   `var/artifacts/row_adjudication_probe/reader_benchmark.md` (local only; headline numbers
   below and in `exports/parallel_candidates/README.md`). Runner: `scripts/run_reader.py`
   (shipped; sequential only, no `--jobs`, opencode throttle default and minimum 3 s). Readers: `opencode/glm-5.3-flash-free` then
   `opencode/mimo-v2.6-flash-free` (both read images). Crop: a tight 300 dpi crop of the
   source-column line only (`geometry.json` `source_pt` + 4 pt pad; tight beat the 200 dpi
   context crop). Prompt: candidates as A, B, C, answer one letter or NONE (`--prompt pick`).
   Measured on 174 rows where two Claude readers agreed (a proxy, not ground truth): glm 97.1%,
   mimo 96.6%, and 163/163 correct (100%) when both gave the same letter (93.7% coverage).
   Accept only on agreement; empty, NONE and disagreement go to the zoom round, then the owner.
   Run readers ONE process at a time with `--throttle 3` or more, never in parallel: OpenCode
   free models block the IP ("abusive traffic") for an hour or more after a burst, and the
   block is shared with every other opencode session on the machine (never touch those). Plan
   for back-off and a resumable chain script (one reader process at a time, results written per
   row, e.g. `chain2.sh` in the probe dir); resume when the block lifts, mark rows unread meanwhile. Run opencode from a cwd outside the repo (`RUNNER_CWD`) so it loads no project skills.
   Do not use gemma4 (local, 78% tight / 60% context, 30-120 s a row), local OCR (rapidocr strips
   every tilde and accent: 18%), nemotron-3.5-super-vl, ornith-1.5:9b or longcat. Each reader
   writes `picks_<reader>_<i>.json`:
   `.venv/bin/python .skills/row-adjudication/scripts/run_reader.py --reader opencode:opencode/glm-5.3-flash-free --worklist var/artifacts/<task>/part0.json --crop-key tight --out var/artifacts/<task>/raw_glm_0.json --picks-out var/artifacts/<task>/picks_glm_0.json`
   (worklist items need the crop path under `--crop-key`; default key `crop` is the review crop). Judge pixels only, no phonology. Claude (Sonnet/Haiku) only
   as a calibration audit of at most 20 rows, or for the final disputed residue.
5. **Compare.**
   `.venv/bin/python .skills/row-adjudication/scripts/compare_picks.py --worklist var/artifacts/<task>/worklist.json --reader <readerA>=<p0>,<p1> --reader <readerB>=<p0>,<p1> --out var/artifacts/<task>/compare.json`
6. **Zoom round** on disputed, low-confidence and none-of-the-candidates rows only:
   `.venv/bin/python .skills/row-adjudication/scripts/render_zoom.py --pdf var/external/marubo_sources/<book>.pdf --geometry var/artifacts/cesarino_2013/review/geometry.json --worklist var/artifacts/<task>/worklist.json --only-idx 23,29,30 --out var/artifacts/<task>/zoom`
   (400 dpi, offsets and size scaled by 400/200). Readers re-read the zoom crops; re-run
   step 5 on the new picks.
7. **Evidence record.** Keep per row: reader, crop path, pick, conf, note. A row whose print
   matches no candidate is stored as an OBSERVATION of the printed form with provenance
   (reader, crop path), `clean_src` left null, listed for review (`observations` in
   `compare.json`). Default is evidence-only: never write into `src` or `clean_src`.
   Whether to fill `clean_src` from agreed picks is an open owner choice.
   The committed record for the 191 t1 conflicts is
   `exports/parallel_candidates/cesarino_2013_conflict_reads.jsonl` (163 agreed, 11 disputed,
   17 unread), built by `scripts/build_conflict_reads.py` (command in the README there).
   **Resume for unread rows:** when the block lifts (an hour or more; test with one row), re-run
   `run_reader.py` for the missing reader on the unread idx (`--rows`, same `--out` file: rows
   already read are skipped, an `exit 3` run is simply re-run), add the new picks to the
   `conflicts_picks_<reader>.json` files, and regenerate the evidence file.
8. **Decision list for the owner.** Disagreements and every none-of-the-candidates row are
   routed here, with agreed picks; each none row with the printed form quoted. Promotion only through
   `.venv/bin/langpipe review decide --task-id ... --decision ... --reviewer ... --role ...`.

## Schemas

- Pick file: `[{"idx": 0, "pick": 1, "conf": "high|med|low", "note": "optional", "printed": "optional"}]`.
  `pick` is the 0-based index into `candidates`; `-1` means none of them.
- `compare.json`: `totals {total, agree_picked, agree_none, disagree, low_conf_any[], unread[]}`,
  `picks {reader: {idx: pick}}`, `observations [{idx, ref, crop, clean_src: null, printed{reader: {form, conf, none}}, status}]`, `disagreements [{idx, ref, candidates, picks{reader: {pick, form, conf, note}}}]`.
- Run on the 191 t1 conflicts, the script reproduces the earlier totals exactly
  (174 agreed, 1 agreed-none, 16 disagree, low-conf idx 30,102,131,134,136,139,187,190).
- Crops: review packet `p<page>-l<row>.png`; `render_zoom.py` uses the same name. The older
  t1 zoom dir (`var/artifacts/t1/adjudication/zoom/`) used `<page>-ll<row>.png`; do not mix.

## Lessons

- "None of the candidates" is a real outcome: the print can show a third spelling (for
  example plain final `o` where every candidate has `õ`). Keep the row an unresolved conflict
  with the printed form noted; do not force the nearest candidate.
- Readers disagree most where the mark is small at 200 dpi (acute on `a`, tilde on `i`):
  that is what the zoom round is for. Low-confidence picks are not votes.
- Geometry rows are keyed by the FULL ref (`cesarino-2013:p100:l11`), crops by
  `p100-l11.png`. A short key silently finds nothing; the scripts report missing refs.
- `crop_px` is `[x, y, w, h]` at the geometry's own `dpi` (200). A zoom scales all four values.
- Machine reads are evidence. Majority vote across readers or references is forbidden.
- OpenCode free models differ a lot as readers. Text-only ones (nemotron-3-ultra says it cannot
  see images; minimax-m3.1-flash-free and deepseek-v4.1-flash-free go looking for files and
  invent text) must not read crops. Calibrate any new model on the gold set first.

## XERJ and Clef: what they are for here

Tested 2026-10-19 on a scratch index of the decoded 2008 thesis, the Villada 2018 text and
the clean-refs JSONL (`var/artifacts/row_adjudication_probe/`, never index `var/external/` in place).

- XERJ is for cross-source context. `xerj autoindex <dir> --prefix p` works on `.txt` and `.jsonl`.
  Use the REST DSL (`match_phrase` on `text`); `xerj search` and `xerj_search` with a plain
  string fail on non-code indexes (`unknown field defs`).
  Phrases are exact per spelling, not diacritic-insensitive (`awe aki amaino`: 0 hits,
  `awẽ aki amaĩnõ`: 2). Hits are overlapping line-window chunks (`start_line`/`end_line`, no
  page field), so counts are inflated and the page needs a line-to-page map. A per-page file
  split failed to ingest (`title` mapped as long). The Villada text indexes as one chunk.
- Not XERJ: "all occurrences of this refrain, counts per spelling, with page". The in-script
  index (`scripts/recover_chant_orthography.py` `build_index`, `fold`, `reference_key`)
  already does it: folded key, one occurrence per line, locator `cesarino-2008:p387`, surface
  per hit. Use it or the stored `clean_citations`; use XERJ for prose around a refrain.
- Clef L0/L1 are local and offline: `src/langpipe/synthesis/grounding.py:79`
  (`GroundingValidator.validate`) and `src/langpipe/synthesis/structural.py:15`. They may
  see Marúbo forms. L0 has 892 stems and rejected every chant line tested (even `aki`):
  useless for chant rows, a weak "attested spelling" probe for everyday single words.
  `HeuristicClefJudge` (`src/langpipe/synthesis/clef.py:40`) is also local.
- Clef L2 and any network Clef (the `clef` proxy skill, `https://clef-proxy.mangadl.workers.dev`,
  body `{state, model, questions, images?}` with Bearer `CLEF_TOKEN`) are Portuguese-side
  only. Whatever goes in `state` leaves the machine: never a Marúbo surface form (invariant 10).
  Clef cannot read pixels for this task; the print-versus-candidate call needs a vision reader.

## Checklist

- [ ] policy `access_class: public` checked
- [ ] parts of at most ~100 rows, global `idx`
- [ ] two independent free/cheap readers (not Claude/Codex bulk), picks saved per part
- [ ] zoom round on disputed, low-confidence and none rows
- [ ] `compare.json` written; none-of-the-candidates rows listed with printed form
- [ ] Claude used only for a ≤20-row audit or the disputed residue
- [ ] nothing written to `src`, `clean_src` or `exports/`; decisions left to the owner
