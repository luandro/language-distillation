"""Native eflomal 2.0.0 baseline verification (WP3.0 bounded spike).

These tests exercise the *pinned upstream distribution directly* — not a langpipe
adapter — to prove the native backend satisfies the contract ADR-0011 assumes:

- one output line per input sentence pair, in batch order (README "Output data
  format": "the same number of lines as the input files");
- NULL links are omitted, so a sentence pair with no links yields an empty line;
- forward and reverse link files both use source-target index order (README:
  "the forward and reverse alignments both use source-target order"), verified
  here against index bounds and the per-direction uniqueness pattern of the
  samplers (forward: one link per target token; reverse: one link per source
  token);
- a missing optional dependency is a fixed failure, never a skip.

The corpus below is synthetic and varied (as required: no single sentence is
expected to yield any invented certainty). Alignment content itself is
stochastic and unseeded upstream, so assertions are structural only.

Selection is explicit: ``uv run pytest -m native_alignment
tests/integration/test_eflomal_native.py -q``. The marker is deselected by
default alongside ``realdata``; without the ``alignment`` extra native execution
tests fail with a fixed diagnostic (the simulated-absence test still passes).
"""

import importlib.metadata
import sys
import time
from datetime import UTC, datetime
from types import ModuleType
from typing import NamedTuple

import pytest

from langpipe.alignment.adapters.eflomal import EflomalAligner
from langpipe.alignment.base import AlignmentConfig, TokenGroup
from langpipe.domain.enums import Symmetrization
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.observation import TokenOccurrence

pytestmark = pytest.mark.native_alignment

# Fixed diagnostic for a missing optional dependency: content-stable, no paths,
# no environment details. WP3.8's adapter import boundary must mirror this
# behavior (AlignmentFailed code ``backend_unavailable``), never a skip.
NATIVE_BACKEND_UNAVAILABLE = (
    "eflomal==2.0.0 is not installed; build the optional native backend with: "
    "uv sync --frozen --extra alignment"
)


def require_native_eflomal() -> ModuleType:
    """Import the native distribution or fail the test with a fixed error."""
    try:
        import eflomal
    except ImportError:
        eflomal = None
    if eflomal is None:
        # Raised outside the except block so no chained import error is rendered.
        pytest.fail(NATIVE_BACKEND_UNAVAILABLE, pytrace=False)
    return eflomal


class AlignedCorpus(NamedTuple):
    """One native run over the synthetic batch, parsed for structural checks."""

    source_sentences: tuple[tuple[str, ...], ...]
    target_sentences: tuple[tuple[str, ...], ...]
    forward_links: tuple[tuple[tuple[int, int], ...], ...]
    reverse_links: tuple[tuple[tuple[int, int], ...], ...]
    runtime_seconds: float


# Synthetic parallel batch: varied asymmetric lengths, shared vocabulary for
# co-occurrence signal, and one empty-source pair whose links are necessarily
# NULL in both directions.
_BATCH: tuple[tuple[str, str], ...] = (
    ("alpha beta gamma", "alpha one beta two gamma three"),
    ("alpha delta", "alpha four delta five six seven"),
    ("beta epsilon zeta", "beta eight epsilon nine zeta ten"),
    ("", "orphan eleven twelve tokens here more extra stray"),
    ("gamma delta eta", "gamma delta eta twelve thirteen fourteen"),
    ("zeta eta theta", "zeta eta theta fifteen sixteen"),
    ("alpha", "alpha seventeen eighteen nineteen twenty twentyone"),
    ("theta iota kappa", "theta iota kappa"),
    ("delta kappa lambda", "delta kappa lambda twentytwo twentythree"),
    ("beta gamma lambda", "beta gamma lambda twentyfour twentyfive"),
    # Repeated surfaces and asymmetric lengths exercise occurrence-index mapping.
    ("alpha alpha beta alpha", "alpha beta alpha alpha six"),
)


def _parse_links(text: str) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Parse a links file: one line per sentence, ``src-tgt`` pairs per line."""
    lines = text.splitlines()
    parsed = []
    for line in lines:
        pairs = []
        for item in line.split():
            first, sep, second = item.partition("-")
            assert sep, f"link item is not src-tgt: {item!r}"
            pairs.append((int(first), int(second)))
        parsed.append(tuple(pairs))
    return tuple(parsed)


@pytest.fixture(scope="module")
def aligned_corpus(tmp_path_factory: pytest.TempPathFactory) -> AlignedCorpus:
    """Run one pinned native alignment (model=3, single sampler) over the batch."""
    eflomal = require_native_eflomal()
    out_dir = tmp_path_factory.mktemp("eflomal-native")
    forward_path = out_dir / "batch.fwd"
    reverse_path = out_dir / "batch.rev"
    aligner = eflomal.Aligner(model=3, n_samplers=1)
    started = time.perf_counter()
    aligner.align(
        [src for src, _ in _BATCH],
        [trg for _, trg in _BATCH],
        links_filename_fwd=str(forward_path),
        links_filename_rev=str(reverse_path),
    )
    runtime = time.perf_counter() - started
    return AlignedCorpus(
        source_sentences=tuple(tuple(src.split()) for src, _ in _BATCH),
        target_sentences=tuple(tuple(trg.split()) for _, trg in _BATCH),
        forward_links=_parse_links(forward_path.read_text(encoding="utf-8")),
        reverse_links=_parse_links(reverse_path.read_text(encoding="utf-8")),
        runtime_seconds=runtime,
    )


def test_native_batch_line_count(aligned_corpus: AlignedCorpus) -> None:
    """Both link files have exactly one line per sentence pair, in batch order."""
    assert len(aligned_corpus.forward_links) == len(_BATCH)
    assert len(aligned_corpus.reverse_links) == len(_BATCH)


def test_native_reverse_is_source_target_order(aligned_corpus: AlignedCorpus) -> None:
    """Reverse links are emitted in source-target index order, like forward links.

    Structural evidence, valid under the documented ordering and impossible to
    satisfy reliably under a swapped one:

    - every pair of both files stays within that sentence's source/target
      lengths (the batch contains several sentences whose target side is much
      longer, so a swapped reverse file would emit out-of-range first indices);
    - within one reverse line the first (source) index never repeats — the
      reverse sampler emits at most one link per source token — while within
      one forward line the second (target) index never repeats;
    - the check is non-vacuous: both files contain at least one link.
    """
    corpus = aligned_corpus
    for index, pairs in enumerate(corpus.reverse_links):
        source_len = len(corpus.source_sentences[index])
        target_len = len(corpus.target_sentences[index])
        first_indices = [a for a, _ in pairs]
        for a, b in pairs:
            assert 0 <= a < source_len, f"reverse pair ({a}, {b}) out of source range"
            assert 0 <= b < target_len, f"reverse pair ({a}, {b}) out of target range"
        assert len(set(first_indices)) == len(first_indices), "duplicate source index"
    for index, pairs in enumerate(corpus.forward_links):
        source_len = len(corpus.source_sentences[index])
        target_len = len(corpus.target_sentences[index])
        second_indices = [b for _, b in pairs]
        for a, b in pairs:
            assert 0 <= a < source_len, f"forward pair ({a}, {b}) out of source range"
            assert 0 <= b < target_len, f"forward pair ({a}, {b}) out of target range"
        assert len(set(second_indices)) == len(second_indices), "duplicate target index"
    assert any(corpus.reverse_links), "reverse output has no links at all"
    assert any(corpus.forward_links), "forward output has no links at all"


def test_native_empty_link_line(aligned_corpus: AlignedCorpus) -> None:
    """A sentence pair with no possible links produces an empty line in both files.

    Batch item 3 has an empty source side: every target token must be
    NULL-aligned in both directions, and omitted NULLs leave an empty line.
    """
    empty_index = 3
    assert aligned_corpus.source_sentences[empty_index] == ()
    assert len(aligned_corpus.target_sentences[empty_index]) > 0
    assert aligned_corpus.forward_links[empty_index] == ()
    assert aligned_corpus.reverse_links[empty_index] == ()


def test_native_optional_dependency_missing_fixed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing native distribution fails with a fixed diagnostic, never skips.

    Absence is simulated by poisoning ``sys.modules``; with the ``alignment``
    extra genuinely absent the same fixed failure is what every native test in
    this module reports (see ``require_native_eflomal``).
    """
    monkeypatch.setitem(sys.modules, "eflomal", None)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        require_native_eflomal()
    assert str(excinfo.value) == NATIVE_BACKEND_UNAVAILABLE


def test_native_adapter_maps_uneven_repeated_occurrences() -> None:
    require_native_eflomal()
    groups = []
    for index, (source, target) in enumerate(_BATCH):

        def occurrences(text: str) -> tuple[TokenOccurrence, ...]:
            return tuple(
                TokenOccurrence(
                    id=new_id(IdPrefix.TOKEN),
                    segment_id=new_id(IdPrefix.SEGMENT),
                    run_id=new_id(IdPrefix.RUN),
                    ordinal=ordinal,
                    raw_surface=surface,
                    normalized_surface=surface,
                    tokenizer="basic@0.1.0",
                    form_id=None,
                    created_at=datetime.now(UTC),
                )
                for ordinal, surface in enumerate(text.split())
            )

        groups.append(TokenGroup(f"sal_native_{index}", occurrences(source), occurrences(target)))
    output = EflomalAligner().align(
        tuple(groups),
        AlignmentConfig(namespace="native", symmetrization=Symmetrization.INTERSECTION),
    )
    expected = [group for group in groups if group.source_tokens and group.target_tokens]
    assert len(output.groups) == len(expected)
    assert [item.alignment_id for item in output.groups] == [
        group.alignment_id for group in expected
    ]
    assert all(item.alignment_id != groups[3].alignment_id for item in output.groups)
    for group, item in zip(expected, output.groups, strict=True):
        for link in (*item.forward, *item.reverse):
            assert 0 <= link.source_index < len(group.source_tokens)
            assert 0 <= link.target_index < len(group.target_tokens)
    metadata = importlib.metadata.version("eflomal")
    assert output.backend.version == metadata
    assert output.backend.options["n_samplers"] == 1
