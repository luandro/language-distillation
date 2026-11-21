# M3 eflomal native spike (WP3.0)

**Status:** Complete — pending senior gate. Evidence below was measured against the pinned
upstream release only (no upstream master), on the development machine. ADR references:
ADR-0004 (baseline choice), ADR-0011 §6 (identity, scores, reproducibility).

**Result:** the native baseline meets the interface the M3 plan assumes. No blocking
incompatibility found. The gate for eflomal integration (WP3.8) is passed.

## Archive and installed identity

| Item | Value |
|---|---|
| Upstream distribution | `eflomal==2.0.0` (PyPI sdist only; no wheels exist for 2.0.0) |
| sdist SHA-256 | `b71183dcf85bf4f59f44ef7a59f5268df1c17c0c8d8093f77b220025ffdba100` — matches ADR-0011 |
| Pinned by | `uv.lock` (`[project.optional-dependencies] alignment = ["eflomal==2.0.0"]`) |
| Runtime deps pulled in | `numpy==2.5.4`, `cython==3.3.0` (upstream declares both as install_requires) |
| Adapter identity (future) | `eflomal@0.1.0` — adapter version, not upstream version (ADR-0011 §6) |
| Upstream license | GNU GPLv3 — optional local extra only; flag to senior if distribution policy matters |

## Build requirements (verified 2026-10-13)

- `uv sync --frozen --extra alignment` builds the sdist in an isolated env; PEP 517
  `build-system.requires = ["setuptools", "wheel", "numpy", "Cython"]`.
- `setup.py` `build_py` runs `make -C src eflomal` + `make -C src python-install`:
  a C compiler and `make` are required at install time. Verified with
  gcc 13.3.0 (Ubuntu 24.04), make 4.x.
- `src/Makefile`: `CFLAGS=-Ofast -march=native -Wall --std=gnu99 -fopenmp`,
  `LDFLAGS=-lm -lgomp -fopenmp`. Consequences: the shipped binary is
  CPU-specific (`-march=native`, SSSE3-class SIMD), requires `libgomp` (verified via
  `ldd`), and independent installations produce independently built binaries.
- Build time on this machine: ~15 s. Sync without the extra removes eflomal/cython/numpy
  (base CI stays compiler-free; `scripts/ci.sh` runs `uv sync --frozen` with no extra).
- Python 3.12 compatibility: built and ran under CPython 3.12.7 (uv-managed). Cython
  module `eflomal.cython` imports cleanly; no 3.12 issues observed.

## Backend invocation contract (surface WP3.8's EflomalAligner must use)

Verified against the pinned sdist sources (`python/eflomal/__init__.py`,
`python/eflomal/eflomal.pyx`, `src/eflomal.c`) and operationally by
`tests/integration/test_eflomal_native.py`.

**Python API (preferred surface — it owns preprocessing):**

```python
import eflomal
aligner = eflomal.Aligner(model=3, n_samplers=1)   # explicit; class default is n_samplers=3
aligner.align(
    src_lines,            # iterable of lines: space-separated tokens (lowercased internally)
    trg_lines,            # same length required, else ValueError("Mismatched file sizes")
    links_filename_fwd=str(path),   # output PATHS, not file objects (written by the binary)
    links_filename_rev=str(path),
    priors_input=None, quiet=True,
)
```

- The Cython wrapper tokenizes (`read_text`: lowercases, splits on whitespace), encodes to
  its indexed format via `write_text`, and runs the bundled binary
  (`site-packages/eflomal/bin/eflomal`) with `subprocess.run(check=True)`.
- `Aligner.__init__` options: `model` (1=IBM1, 2=+HMM, 3=+fertility; default 3),
  `score_model` (default 0), `n_iterations` (3-tuple or auto), `n_samplers` (default 3),
  `rel_iterations` (default 1.0), `null_prior` (default 0.2),
  `source/target_prefix_len/suffix_len` (stemming; leave 0).
- Auto-iterations scale as `max(2, round(rel_iterations*5000/sqrt(n_sentences)))` per model
  stage — small batches still run hundreds/thousands of iterations and remain fast.
- **CLI binary options** (`getopt "s:t:p:f:r:S:F:R:1:2:3:n:qm:M:N:h"`): `-m model`,
  `-s/-t` inputs, `-p` priors, `-f/-r` forward/reverse links outputs, `-S` statistics,
  `-F/-R` sentence scores, `-M` score model, `-1/-2/-3` stage iterations, `-n` samplers,
  `-N` null prior, `-q` quiet. The `eflomal-align` wrapper script adds `--overwrite`
  (it refuses to overwrite existing outputs without it) and `-i` joint `|||` input
  (which rejects empty sentences — use separate `-s/-t`/two iterables instead).

**Output format (both directions, from `text_alignment_write_moses`):**

- One line per sentence pair, same count and order as the input batch.
- Moses-style `src-tgt` pairs, space separated (e.g. `1-0 2-1`).
- **Forward and reverse files both use corpus source-target index order** (README states
  it; verified in C: `align(reverse=1)` swaps `ta->source`/`ta->target`, and the writer
  prints the corpus-source index first in both branches). "Reverse" means reverse
  estimation, not reversed IDs — exactly ADR-0011 §5's reading.
- NULL links are omitted; a sentence with no links yields an **empty line** (verified
  deterministically with an empty-side sentence).
- Zero-based indices.

**Structural invariants the adapter may rely on (tested):**

- forward line: each target index appears at most once (source may repeat — fertility);
- reverse line: each source index appears at most once (target may repeat);
- every pair within that sentence's source/target lengths.

## Option support matrix (plan's AlignmentConfig mapping)

| AlignmentConfig field | Native support | Finding |
|---|---|---|
| `model` (default 3) | `-m` / `Aligner(model=)` | pass through explicitly (class default already 3) |
| `threads` (default 1) | partial | No thread-count option. Parallelism is `-n n_samplers` (independent samplers via OpenMP; forward/reverse also run in parallel). `Aligner` class default is **3**, raw `align()` default 1 — always pass explicitly. Map `threads`→`n_samplers` or pin `n_samplers=1`; decision for WP3.8/senior |
| `random_seed` | **none** | No seed option anywhere (C seeds from system entropy via `random_system_state`). Unsupported seed requests must fail with `unsupported_seed`; record `random_seed=null` + `stochastic_unseeded`. Do **not** patch native sampling (confirmed unpatched here) |
| `timeout_seconds` | none | No native timeout; adapter must enforce (`backend_timeout` on expiry) |
| `symmetrization` | none | Native emits directional link files only; intersection/union is ours (WP3.8 symmetrization module) |
| per-link `score` | **unavailable** | `-F/-R` with `-M>0` emit one float per **sentence** (negative log generation probability), not per link. Default edge `score=None`, empty `raw_scores`, report reason `score_unavailable` — as ADR-0011 §6 already assumes |

## Runtime

Batch of 10 varied synthetic sentence pairs, `model=3`, default auto-iterations,
`n_samplers=1`, both directions: **0.27 s** (fixture setup, measured via `--durations`).
Full acceptance command `uv run pytest -m native_alignment
tests/integration/test_eflomal_native.py -q`: 4 passed in ~0.6–1.0 s.

## Test-selection policy (verified)

- Marker `native_alignment` registered; `addopts = "-ra --strict-markers -m 'not realdata
  and not native_alignment'"` — deselected by default (4 items deselected in the default
  run; full default suite: 859 passed, 20 deselected, 0 skipped/failures).
- Explicit selection without the extra installed: **fails with a fixed diagnostic, never
  skips** (3 setup errors + 1 pass, exit≠0; message fixed, no chained import error):
  `eflomal==2.0.0 is not installed; build the optional native backend with: uv sync
  --frozen --extra alignment`.
- `scripts/ci.sh` passes no `-m` override (guarded by `tests/unit/test_ci_script.py`,
  now also for `native_alignment`); base CI remains compiler-free.

## Sharp edges the adapter must handle (recorded for WP3.8)

1. **Silent ≥1024-token truncation**: `write_text` (pyx) writes a `0`-length sentence for
   any sentence with ≥ 0x400 (1024) tokens — links for such a group would be silently
   empty. The adapter must reject over-long groups up front rather than lose evidence.
2. Python layer **lowercases** tokens (`read_text(..., True, ...)`); case distinctions
   cannot survive the native vocabulary boundary. Occurrence mapping remains index-based;
   original persisted surfaces must remain unchanged, regardless of normalization case.
3. Sentence-count mismatch raises `ValueError("Mismatched file sizes")`; adapter must
   validate group counts before invocation.
4. The binary is invoked with `subprocess.run(check=True)`; stderr may carry native text —
   never log verbatim (ADR-0011 §6); map nonzero exits to `backend_failed`.
5. Temporary files created by the wrapper use `NamedTemporaryFile` defaults; adapter-level
   files must follow ADR-0011 (0700/0600, outside tracked paths).
6. GPLv3 upstream: keep it an optional, locally built, never-redistributed extra.

## Acceptance commands and results (2026-10-13)

```
uv sync --frozen --extra alignment                  # OK (~15 s build)
uv run pytest -m native_alignment \
     tests/integration/test_eflomal_native.py -q    # 4 passed (~1 s)
uv run pytest -q                                    # 859 passed, 20 deselected (default gate)
uv run ruff check . && uv run ruff format --check . # clean
```
