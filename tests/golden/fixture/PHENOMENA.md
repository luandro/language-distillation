# Phenomena map

Each phenomenon from `docs/GOLDEN-FIXTURE.md` is listed with the fixture location that exercises
it and the milestone that first checks it. Paths are relative to `tests/golden/fixture/sources/`.
M1 checks only the source and evidence substrate, so most phenomena are data-only until their
milestone.

| # | Phenomenon | Location (file:line) | Milestone |
|---|---|---|---|
| 1 | Same surface form in multiple occurrences | `01-parallel-distill/parallel.tsv:2,4` (`kanu`); `01-parallel-distill/parallel.tsv:2` and `02-educational-direct/lessons.tsv:3` (`mabi`) | M2 (tokens) — checked |
| 2 | One form with two candidate senses | `03-wordlist/wordlist.tsv:3` (`mabi`: canoa; tronco) | M4 (lexical) — checked |
| 3 | One 1:n segment alignment | `01-parallel-distill/parallel.tsv:5` (TXT.1.4, one `qaa` segment ↔ two `por` sentence segments under `tsv_sentences@0.1.0`) | M3 |
| 4 | Whole-token null evidence and standalone punctuation | `01-parallel-distill/parallel.tsv:4` (`wesa-ra` stays one occurrence and is left unaligned by the explicit mock); `alignment/null-token.tsv:2` (`-` and `ra` are separate occurrences, both unaligned) | M3 |
| 5 | One competing morphology segmentation | `04-igt/igt.txt:8-10` (`wesa-ra`); `01-parallel-distill/parallel.tsv:4` | M5 (morphology) |
| 6 | One validated morpheme from IGT | `04-igt/igt.txt:2-4` (`-ki`, glossed in IGT-1) | M5 |
| 7 | One unknown morpheme | Pending M5. The fixed corpus does not explicitly identify an unglossed component. `04-igt/igt.txt:8-10` (`wesa-ra`, glossed `ir-NEG`) is a candidate for future ambiguity analysis only, not observed missing-gloss evidence | M5 |
| 8 | One orthographic variant | `02-educational-direct/lessons.tsv:2` (`kanú`) vs `01-parallel-distill/parallel.tsv:2` (`kanu`) | M2 (normalization) — checked |
| 9 | One domain-specific lexical item | `03-wordlist/wordlist.tsv:4` (`rumi`, ritual/traditional); `01-parallel-distill/parallel.tsv:5` | M4 — checked |
| 10 | One review accept | `04-igt/igt.txt:1-5` (IGT-1, candidate for an accept decision) | M5 (IGT targets); M4 infrastructure checked on lexical senses |
| 11 | One reject/uncertain review | `04-igt/igt.txt:7-11` (IGT-2, candidate for reject or uncertain) | M5 (IGT targets); M4 infrastructure checked on lexical senses |
| 12 | One revoked source used for lineage impact | `01-parallel-distill/manifest.yaml` (source to revoke); M1 scaffold is `impact_of` in `test_golden_lineage_impact_from_source` | M4 — checked (revocation impact over lexical lineage and exports) |

Related M1 checks, all in `tests/golden/test_golden_m1.py`:

- `distill_only` is not trainable: `01-parallel-distill/manifest.yaml:12`.
- The excluded source is not ingested: `06-excluded/manifest.yaml:10`.
- Idempotence and reproducibility: `test_golden_m1_rerun_creates_no_duplicates`.

Related M2 checks, all in `tests/golden/test_golden_m2.py` (phenomena 1 and 8, plus the NFD line):

- Phenomenon 1 (shared surface forms): forms `qaa/default_text@0.1.0/kanu` (attested in `01` and `05`) and
  `qaa/default_text@0.1.0/mabi` (attested in `01`, `02` and `05`) in `expected/m2/forms.json`.
- Phenomenon 8 (orthographic variant): `kanu` and `kanú` are distinct `qaa` Forms; the NFD line in
  `05-monolingual/text.txt:3` normalizes to the same NFC `kanú` Form as `02-educational-direct/lessons.tsv:2`.
- The NFD line's token carries a 5-code-point `raw_span` and a 4-code-point `normalized_span`.

Related M3 checks, in `tests/golden/test_golden_m3.py`:

- Phenomenon 3 asserts one relational group with exactly one source member and two target members.
- Phenomenon 4 treats `wesa-ra` as an infrastructure whole-token null case, not a linguistic
  suffix analysis. The separate `foo -ra` fixture confirms `whitespace_punct@0.1.0` preserves
  punctuation `-` and word `ra` as distinct occurrences. Suffix-level interpretation remains M5.
- Golden 03 (`wordlist.tsv`) is an intentionally ragged TSV (WP2.3) and cannot enter the M2 pipeline;
  `test_golden_m2_wordlist_03_is_malformed` pins that.

Related M4 checks, in `tests/golden/test_golden_m4.py`:

- Phenomenon 2: the 03 `mabi` lexeme keeps two sense hypotheses (`canoa`, `tronco`), each with its
  own evidence; the 01 `mabi` lexeme stays a separate id and nothing merges across sources.
- Phenomenon 9: the `ritual/traditional` tag stays on the 03 sense (never on the lexeme), does not
  leak to 01, and gates review authority (`golden-fauna-only` is refused on T8).
- Phenomena 10/11 infrastructure: immutable accept/reject decisions over lexical senses move
  lifecycle status to `validated`/`rejected` under the in-test authority registry.
- Phenomenon 12: revoking `01-parallel-distill` reaches its lexemes, senses, review records and a
  validated pair, flips computed eligibility to DENY, and leaves every stored row unchanged;
  revoking the export source instead makes its published CLDF artifacts ineligible and fails a
  fresh export closed (`NoEligibleRecords`).
