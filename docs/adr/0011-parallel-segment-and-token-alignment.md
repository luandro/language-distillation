# ADR-0011: Parallel segment and token alignment evidence

**Status:** Accepted  
**Date:** 2026-10-13  
**Implementation design:** [M3-PLAN](../implementation/M3-PLAN.md)

## Context

M1/M2 provide immutable source objects, raw and normalized Segments, TokenOccurrences,
ProcessingRuns, relational lineage and two Repository implementations. Stage 4 requires n:m
segment evidence; Stage 5 requires token evidence behind the statistical adapter selected in
ADR-0004. Neither stage produces lexical truth. PostgreSQL remains canonical (ADR-0002).

The current contracts leave group membership, run selection, approval semantics, null links,
score availability and adapter index mapping unspecified. Two golden requirements conflict
with M2 observations: TXT.1.4 has one Portuguese TSV cell containing two sentences, while
TXT.1.3 contains the single token `wesa-ra`, not an independent `-ra` token. M2 observations
and snapshots MUST remain unchanged.

## Proposed decisions

### 1. Ordered binary n:m groups

`SegmentAlignment` is one addressable evidence object with two nonempty ordered lists of
segment IDs, `source_segment_ids` and `target_segment_ids`. Each side is homogeneous in
language and selected normalization run; the two sides have distinct languages. Different
sources are usual, but two language sides of a registered bilingual source are permitted.
More than two languages are represented by explicit pairwise groups; no implicit multiway
translation equivalence is asserted.

Membership is relational: `segment_alignment_member(alignment_id, side, position,
segment_id)`. One group is a hyperedge, not the Cartesian product of its members. A segment
MAY participate in competing groups in different runs. Membership order is source document
order (source object original_path, segment ordinal), not random ID order. Positions are
zero-based and contiguous. Duplicates within a side and across sides are forbidden.

The parent records `method` as `name@version`, `mode` (`canonical`, `heuristic`,
`experimental`), `status`, nullable `score`, typed raw score components, `run_id`,
`group_key` and UTC creation time. `sal_` and `tal_` extend opaque ULID identities. Natural
keys and successful-run reuse provide stable IDs inside an installation; IDs are not
content hashes and are not identical across fresh installations (ADR-0008).

### 2. Alignment disposition is not linguistic validation

Alignment `status` has the requested values `structural | inferred | candidate | approved |
rejected`. This is an operational evidence disposition, explicitly distinct from the
`candidate → supported → validated` lifecycle of linguistic hypotheses. No alignment
status grants validated translation, sense or morphology status.

The canonical matcher emits `structural` only when coordinates are compatible and explicit;
it asserts coordinate correspondence, not translation correctness. Heuristic/neural adapters
emit `candidate`; `inferred` is reserved for a versioned method-specific quality gate, never
an unconditional score threshold. Only `structural` and `approved` are Stage 5 eligible.

M3 does not implement the M4 review subsystem or a mutable status setter. An `approved` or
`rejected` replacement requires a registered authorization-basis Artifact from a permitted
local importer, a succeeded producing run, `Operation.HUMAN_REVIEW` approval on all source
ancestors, and an explicit actor match in that artifact. It is a new alignment row linked
`supersedes` to its predecessor; original rows remain immutable. The basis is an input and
an `imported_from` parent. A user-supplied string or statistical confidence cannot authorize
approval. Neither successor becomes eligible when its governing source is revoked.

### 3. Canonical locator importer

`CanonicalLocatorAligner` (`canonical_locator@0.1.0`) groups already persisted normalized
segments; it never reads source files or creates segments. Keys use a caller-selected
coordinate namespace. TSV keys are `(namespace, ref)`; language, row, column and sentence
part do not enter correspondence keys. Empty refs are unmatched. Scripture keys use
`(namespace, versification_id, book, chapter, verse position)` and only `unit=verse`.
Headings, introductions, notes and unknown blocks remain unmatched and reported.

Simple numeric verse labels and inclusive numeric bridges such as `3-4` map to coordinate
sets. Construct the bipartite overlap graph of source and target segment nodes and emit
one connected component per n:m group, exactly once. Multiple pieces sharing a coordinate
join the same component. Numeric chapter and book identity are exact; published labels
are retained diagnostics, not replacement coordinates. Suffix labels such as `3a` match
only that exact opaque label; they are not collapsed into `3`. Malformed labels are
unmatched. Overlapping distinct verse claims within one edition are ambiguous and MUST
fail preflight unless they are pieces sharing the exact original label. Different declared
versification IDs require a separately registered reviewed mapping; M3 has no automatic
mapping and rejects incompatible IDs.

A component is structural only if each side covers the same coordinate set. Partial bridge
coverage emits `candidate` with a fixed `partial_coordinate_coverage` diagnostic, excluded
from Stage 5. Missing opposite-side keys are reported without empty-sided groups. Duplicate
book identity across source objects is an input error, not silently merged editions.

Canonical import means matching preserved coordinate metadata into internal groups. It
is not CLDF import (M4) or import of arbitrary aligner text as trusted approval.

### 4. Explicit M2 run selection and optional sentence extraction

Every alignment request pins one succeeded normalization run per side and one succeeded
tokenization run per side for Stage 5. If a CLI default finds exactly one applicable run,
it may select it; zero is an input error and multiple runs raise `AmbiguousInput`. No
"latest" selection and no mixture of generations. Ordered side roles and input selection
are included in the run config as well as the sorted input IDs in the existing run key.

To exercise actual 1:2 golden membership, add opt-in `tsv_sentences@0.1.0` as an extraction
adapter wrapping M2 TSV parsing. Only explicitly configured `por` columns are split at
`.!?` followed by whitespace/end; maximal delimiter runs stay with the sentence, inter-unit
whitespace is removed from units and retained in source bytes. Other languages remain
unchanged. Each unit retains ref/row/column plus `sentence_part`, `cell_start`, `cell_end`
(Unicode half-open cell offsets). This deliberately conservative adapter is not a general
Portuguese sentence recognizer and is never the default. It produces a separate extraction
run, followed by ordinary normalization/tokenization. Stage 4 creates no observations.

### 5. Corpus-level token alignment and exact occurrence mapping

`TokenAligner` consumes an ordered batch of segment groups and returns directional sets of
zero-based source-target index pairs. Flatten each side's tokens in member order then token
ordinal, including punctuation and numbers; no deduplication by Form/surface and no inserted
separator token. Maintain an explicit index-to-TokenOccurrence-ID array for each side and
each group. Selected tokenization runs must consume the selected normalization run and
cover every selected OK segment, including legitimate empty token arrays.

`TokenAlignmentEdge` carries `segment_alignment_id`, `source_token_id`, `target_token_id`,
`direction` (`forward`, `reverse`, `symmetrized`), `algorithm` (`name@version`), nullable
`score`, raw scores, `symmetrization` (`none`, `intersection`, `union`), `run_id` and UTC
creation time. Both directional outputs always use the selected source-target coordinate
order; reverse means reverse estimation, not reversed IDs. Preserve forward and reverse
rows and create the selected symmetrized set; the default is intersection. Union is explicit.
No grow-diag implementation or new fast_align dependency in M3.

Natural uniqueness is `(run_id, segment_alignment_id, source_token_id, target_token_id,
direction, symmetrization)`. Both endpoints must belong to the indicated group's sides,
to the pinned tokenization runs, and to registered observations. An empty link set is
valid. No nullable endpoint or invented NULL token is persisted. Report complements of
linked tokens per group/direction as unaligned token IDs; report empty-side groups as
`empty_token_side`, excluded from the native batch and retained as unaligned.

### 6. Statistical baseline, honest scores and reproducibility

Use adapter identity `eflomal@0.1.0` with upstream distribution `eflomal==2.0.0` pinned in
an optional `alignment` extra and the lockfile. Adapter version is not upstream version.
Native build/support verification is an implementation gate, not presumed from availability.
The upstream [README](https://github.com/robertostling/eflomal#output-data-format) documents
index-pair output, omitted NULL links and source-target ordering for both directions.
The [2.0.0 release metadata](https://pypi.org/pypi/eflomal/2.0.0/json) identifies the source
archive SHA-256 `b71183dcf85bf4f59f44ef7a59f5268df1c17c0c8d8093f77b220025ffdba100`.

Do not manufacture per-link probabilities from hard links or sentence-level scores. Default
edge score is null, raw scores are empty, with report reason `score_unavailable`. Structural
segment score is likewise null with `coordinate_match` evidence metadata. Any future score
aggregation/calibration needs versioned policy and benchmark provenance.

Native eflomal operates locally on the complete ordered corpus batch, not independently per
verse. Temporary files are private (directory 0700, files 0600), outside tracked paths,
removed through scoped temporary-directory lifecycle. Process errors/stderr never enter
logs or artifacts verbatim. Pin model/options, upstream identity, thread count, batch order,
and any actual supported seed. Do not claim deterministic sampling when upstream exposes
no seed control: record `random_seed=null` and `stochastic_unseeded`; reuse persisted results
for identical successful requests. Independent installations may produce different links.

A test-only `MockTokenAligner` in `tests/fixtures/alignment.py` implements the same protocol
with explicit link matrices. It is never registered in the production registry, cannot
satisfy native acceptance, and is never substituted automatically for missing eflomal.
A pure-Python production baseline is deferred; introducing one needs a separately named
adapter and measured comparison, not masquerading as eflomal.

### 7. Governance, run atomicity and lineage

Both services resolve `Operation.ALIGN` for every governing source before reading surfaces,
calling adapters or reusing a run. Missing source ancestry, non-allow decisions, and revoked
sources fail closed. Recheck under the semantic transaction before commit. PostgreSQL
locks governing source rows in sorted ID order until commit, so concurrent revocation cannot
race publication of new eligible outputs. A revocation after commit blocks subsequent use;
historical evidence is retained. No restricted text goes to a third-party service.

Run lifecycle follows M2 `RunRecorder`: preflight failures create no run; start commits a
running row; adapter/output failure marks that row failed with redacted fixed diagnostics;
semantic rows, members, run I/O, report metadata and terminal success commit in one UnitOfWork.
There are no partially successful alignment runs or per-group semantic commits. Content-store
bytes written before rollback may remain orphaned, as permitted by ADR-0008.

Every alignment points `derived_from` to each member segment. Every token edge points
`derived_from` to both endpoint tokens and its SegmentAlignment. Reports point to all
selected source-bearing inputs even when there are no links. `run_id` and run I/O record
created_by/input/output independently; no parent-to-child lineage or run/output cycles.
Approval successors additionally point to predecessor and basis. Evaluation reports depend
on predicted run outputs and gold input artifacts. All new entities enter object_registry.

Combined source ancestry applies to DIRECT_TRAINING and other outward operations, not
merely ALIGN. An alignment cannot launder `distill_only` prose or reverse a source denial.
M3 supplies lineage-aware denial and no training exporter; the full contamination firewall
remains a downstream requirement.

### 8. Persistence and benchmark semantics

Migration `0003_m3_alignment.py` adds parent/member/token-edge tables, object-registry entity
types, CHECK constraints, endpoint/run foreign keys, uniqueness/indexes and append-only
triggers. Domain/service validation and deferred PostgreSQL constraint triggers enforce
nonempty homogeneous sides, contiguous membership and endpoint membership at commit.
Publication immutability of membership is enforced by comparing the parent's internal
`creating_txid` marker — stamped by a database trigger at INSERT with the epoch-aware
top-level transaction identity, which is constant across savepoints — with the current
top-level transaction: membership may be assembled anywhere within the creating
transaction, but never appended by a later one. The marker is database-owned storage
bookkeeping, not domain metadata, and is not exposed by the public model or API.
No M1/M2 data rewrite. Downgrade refuses if any M3 rows, registry entries or run I/O/lineage
references survive; an empty disposable database supports upgrade/downgrade/upgrade.

Gold matrices carry sure links S, possible links P with S ⊆ P, ordered occurrence selectors,
explicit null annotations, tokenizer/config identities and a frozen split manifest. For
predicted set A (symmetrized direction by default): precision = |A ∩ P|/|A|, recall =
|A ∩ S|/|S|, F1 is their harmonic mean, AER = 1 − (|A ∩ S| + |A ∩ P|)/(|A| + |S|).
Undefined denominators yield null and an explicit reason, never invented perfect accuracy.
Corpus results use micro sums and disclose per-group empty cases. Duplicate links count once;
out-of-bounds links and S not contained in P are errors. Null handling is measured separately
against explicitly annotated null tokens. No universal quality threshold is introduced.

Gold is never passed into native induction, options or priors. M3 native corpus alignment
is transductive: held-out text may participate in unsupervised fitting, which must be labeled
in reports. Gold labels remain isolated. Strict inductive evaluation using frozen priors is
outside M3 and cannot be claimed by this harness.

## Alternatives considered

1. Pairwise segment edges: simpler storage, but fabricate Cartesian correspondence and lose
   the original 1:n/n:m group. Rejected.
2. JSON membership arrays only: easy serialization, weak referential integrity and graph
   querying. Rejected in favor of relational members and explicit lineage.
3. Mutable status and eager review subsystem: larger scope and audit risks. Immutable
   successors plus authorized import leave M4 review design intact.
4. Silent mock fallback: easy compiler-free tests, misleading baseline evidence. Rejected.

## Consequences and acceptance boundary

M3 adds evidence only. Machine links cannot validate translations. M1/M2 APIs, raw bytes and
snapshots remain stable. The plan includes a narrowly scoped optional extraction adapter;
its addition is explicit here rather than hidden in Stage 4. Native compatibility, Portuguese
rights/availability, versification compatibility and target-language quality remain gates.

Phenomenon 3 becomes an executable 1:2 group using the opt-in adapter. Phenomenon 4 cannot
honestly assert a standalone `-ra` occurrence at TXT.1.3: golden coverage preserves `wesa-ra`,
checks absence of forced links for a configured whole-token null case, and adds a separate
permission-safe synthetic null case with `foo -ra` (separate `-` and `ra` occurrences under
M2 tokenization). The fixture description must state
that suffix-level null interpretation remains M5. Native smoke tests do not claim linguistic
accuracy on ScriptureEarth without authorized gold annotations.

This ADR was Proposed until the architecture owner accepted it on 2026-10-13; implementation
of its persisted interfaces/status exception proceeds under that acceptance. Writing the
original proposal did not accept prior ADRs or authorize corpus acquisition/processing.
