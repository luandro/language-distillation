# M5 Morfessor Baseline Spike (WP5.12)

**Status:** Complete — Gate 41 passed. Evidence measured against the pinned upstream release on Python 3.12 (Ubuntu Linux, x86_64).
**Governing Documents:** `docs/implementation/M5-PLAN.md` §6 WP5.12, §8.2 Gate 41; `docs/adr/0019-morphology-benchmark-and-method-promotion.md`.
**Result:** **GO**. Upstream Morfessor meets all four pass criteria. The optional extra `morphology = ["morfessor==2.0.6"]` and adapter `morfessor_baseline@0.1.0` are integrated behind the `optional_morphology` marker without polluting base CI.

---

## 1. Distribution and Archive Identity

| Item | Value |
|---|---|
| Upstream distribution | `morfessor==2.0.6` |
| PyPI release format | Wheel (`py3-none-any.whl`) and sdist (`.tar.gz`) |
| Wheel filename | `Morfessor-2.0.6-py3-none-any.whl` |
| Wheel SHA-256 | `7215e37909ebd2bafeeec5fdf4e339a25e61aee4895ff99317b9fb44eddab562` |
| sdist filename | `Morfessor-2.0.6.tar.gz` |
| sdist SHA-256 | `bb3beac234341724c5f640f65803071f62373a50dba854d5a398567f9aefbab2` |
| Pinned by | `pyproject.toml` (`[project.optional-dependencies] morphology = ["morfessor==2.0.6"]`) |
| Runtime dependencies | None (pure standard library: `math`, `random`, `collections`, `re`) |
| Upstream license | 2-Clause BSD (permissive, GPL-free, commercial/academic compatible) |
| Adapter method ID | `morfessor_baseline@0.1.0` |

---

## 2. Pass Criteria Verification

### Criterion 1: Installs without a compiler on Python 3.12
- **Requirement:** Installs from a prebuilt wheel or pure-Python sdist without invoking `gcc`, `clang`, or `make`.
- **Evidence:** PyPI ships universal wheel `Morfessor-2.0.6-py3-none-any.whl`. In an isolated Python 3.12.7 environment, `uv pip install morfessor==2.0.6` completed in 329 ms without compiling any C/C++ extensions or requiring build tools.
- **Verdict:** **PASS**.

### Criterion 2: Deterministic with a fixed seed
- **Requirement:** Given a fixed random seed, Morfessor training and Viterbi segmentation must produce identical segmentation boundaries across runs.
- **Evidence:** Tested with `morfessor.BaselineModel()` on synthetic word lists (`wesa`, `wesara`, `wesano`, `yora`, `yorara`, `inon`, `inora`) with `random.seed(42)`. Independent instances yielded exact bitwise identical segmentation lists:
  `[['wesa'], ['wesa', 'ra'], ['wesa', 'no'], ['yo', 'ra'], ['yo', 'ra', 'ra'], ['ino', 'n'], ['ino', 'ra']]`.
- **Verdict:** **PASS**.

### Criterion 3: License compatibility
- **Requirement:** Upstream license must be compatible with permissive open distribution (BSD, MIT, Apache 2.0).
- **Evidence:** Distribution metadata and `LICENSE` file confirm 2-Clause BSD copyright by Sami Virpioja, Peter Smit, and Stig-Arne Grönroos (2012–2019). No copyleft or viral terms.
- **Verdict:** **PASS**.

### Criterion 4: Trains and segments unit fixture offline
- **Requirement:** Must execute entirely offline without network calls or external binary subprocessing.
- **Evidence:** `BaselineModel.load_data()` and `BaselineModel.train_batch()` operate strictly in-memory over frequency tuples, and `BaselineModel.viterbi_segment()` outputs segmented token parts with log probabilities offline.
- **Verdict:** **PASS**.

---

## 3. Integration & Isolation Contract

1. **Optional Extra:** `[project.optional-dependencies] morphology = ["morfessor==2.0.6"]`. Base CI does not install this extra (`scripts/ci.sh` runs `uv sync --frozen`).
2. **Pytest Marker:** `optional_morphology: requires the optional morphology extra (morfessor==2.0.6)`.
3. **Deselection in Base CI:** `pyproject.toml` addopts sets:
   `-m 'not realdata and not native_alignment and not optional_morphology'`
   ensuring zero test skips in default CI (2687+ passed, 0 skipped).
4. **Adapter Lazy Loading:** `src/langpipe/morphology/adapters/morfessor.py` defers importing `morfessor` until `induce()` is invoked. If invoked when `morfessor` is absent, it raises `RuntimeError` directing the operator to `uv sync --extra morphology`.
5. **Candidate-Only Lifecycle:** Invariant 3 preserved. `MorfessorInducer` emits strictly `LifecycleStatus.CANDIDATE` analyses with `morpheme_id=None` segments. Machine confidence never promotes to `validated`.
