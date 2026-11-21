"""WP3.13: governed ScriptureEarth mzr–por paired alignment (opt-in ``realdata``).

Nothing here downloads. Both directions are supplied by the operator as local
packages (``LANGPIPE_MZR_SE_DIR``/``MANIFEST`` and ``LANGPIPE_POR_SE_DIR``/``MANIFEST``), and a
missing package, manifest or sign review is a **failure, never a skip** (M2 E9,
M3-PLAN WP3.13). No corpus bytes are committed, logged or written into reports: the committed
expectations file holds package hash inventories, editions, versification ids, ``reviewed_by``
and metadata-only counts, and the count tests fail until a senior has independently rescanned
the corpus and signed it.

The pre-work check is manifest-only (ADR-0025): a manifest must record where the package came
from, every required local operation (ingest, read_raw, extract, normalize, align) must resolve
allow, and every outward operation must resolve deny — all checked **before** any package
scan, registration, ingestion or extraction. Licences, authorities, rights holders, and
permission notes are records and are not checked. Each package's manifest is checked
independently (C11); a Portuguese package is not covered by the Marúbo package's record.

The coordinate oracle is independent of the production aligner. It expands numeric bridges,
keeps verse-only locators, and builds the bipartite overlap graph itself from persisted
locators, so an expected count cannot inherit ``CanonicalLocatorAligner``'s answer.

The native token stage runs over the **full eligible batch**: every ``structural`` (or
``approved``) group of the Stage 4 run whose two token sides are nonempty, exactly as
``TokenAlignmentService`` selects them (ADR-0011 §2/§5). There is no subset selection here; a
documented bounded selection would have to be persisted in the run config, and this module
asserts the complete eligible batch instead. A full native local batch with recorded backend
options and batch sizes is the completion gate; the test mock never satisfies it.

Report unmatched counts and the oracle are deliberately kept apart: the oracle reasons about
verse locators only, while ``CanonicalLocatorAligner`` additionally reports every non-verse
unit (headings, titles, notes, front matter) as unmatched with a fixed reason. ``_unmatched_split``
and ``_assert_unmatched_agrees`` implement that separation; ``test_paired_usfm_synthetic.py``
imports them so missing operator inputs cannot conceal a regression in their semantics.

Content-free diagnostics only. Surface text, book paths and native process output never enter
an assertion, a log line or a report: failures carry ids, locators, hashes and counts, and
``tests/integration/conftest.py`` already sanitizes ``realdata`` reports. Every safe-marked
diagnostic is built from fixed prose, internal pipeline ids, narrative counts or *numeric entry
positions* — never from an arbitrary metadata key, so a distinctive book code or digest injected
into the expectations file cannot be rendered even though the message is marked safe.

The expectations file has exactly two legal states, and the committed record is validated **by its
status**: an unsigned template must stay structurally valid and must fail the review gate, while a
senior-signed complete record must pass it. Signing the checked-in file therefore cannot break the
default suite. The negative tests never depend on the disk file: they build both states in memory
(``_unsigned_template_record``/``_complete_reviewed_record``), and separate tests patch
``Path.read_text`` — never writing to disk — to prove the gate's verdict for each state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import unquote, urlsplit

import pytest

from langpipe.alignment.base import AlignmentConfig, AlignmentSide
from langpipe.alignment.canonical import UNMATCHED_REASONS
from langpipe.alignment.segment_service import SegmentAlignmentService
from langpipe.alignment.token_service import TokenAlignmentService
from langpipe.app_context import AppContext
from langpipe.domain.enums import (
    AlignmentDirection,
    AlignmentStatus,
    EntityType,
    LineageKind,
    Operation,
    PolicyDecision,
    PolicyMode,
    RunIoRole,
    RunStage,
    RunStatus,
    Symmetrization,
)
from langpipe.domain.errors import AlignmentFailed
from langpipe.domain.ids import new_id
from langpipe.domain.models.source import (
    AccessClass,
    PolicySpec,
    Provenance,
    SourceManifest,
)
from langpipe.extraction.service import extract_source
from langpipe.governance.lineage_policy import ancestor_source_ids, effective_decision
from langpipe.governance.policy import resolve
from langpipe.ingestion.adapters.scriptureearth import (
    SE_MEDIA_TIMING,
    SE_MEDIA_USFM,
    build_manifest,
    scan_package,
)
from langpipe.ingestion.ingest import ingest_source
from langpipe.ingestion.registration import load_manifest, register_source
from langpipe.normalization.service import normalize_extraction
from langpipe.storage.memory import InMemoryRepository
from langpipe.storage.objects.local import LocalContentStore
from langpipe.tokenization.service import tokenize_normalization
from tests.integration.conftest import SAFE_DIAGNOSTIC_PREFIX
from tests.integration.test_paired_usfm_synthetic import VERSIFICATION
from tests.integration.test_paired_usfm_synthetic import _pair as _synthetic_pair
from tests.integration.test_paired_usfm_synthetic import _stage4 as _synthetic_stage4
from tests.service.manifests import write_manifest

MZR_DIR_ENV = "LANGPIPE_MZR_SE_DIR"
MZR_MANIFEST_ENV = "LANGPIPE_MZR_SE_MANIFEST"
POR_DIR_ENV = "LANGPIPE_POR_SE_DIR"
POR_MANIFEST_ENV = "LANGPIPE_POR_SE_MANIFEST"
EXPECTED_PATH = Path(__file__).with_name("expected") / "scriptureearth_parallel_counts.json"

REALDATA = pytest.mark.realdata
SCRIPTURE_NAMESPACE = "scripture"
STRUCTURAL = AlignmentStatus.STRUCTURAL

_ID_CODE = re.compile(rb"\\id\s+([A-Za-z0-9]{3})")
# Opaque suffix verse labels: digits followed by letters, never collapsed into the bare number
# (ADR-0011 §3). Any letter suffix is a distinct coordinate, not only ``a``.
_SUFFIX_LABEL = re.compile(r"[0-9]+[a-z]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PLACEHOLDER_VALUES = frozenset(
    {"placeholder", "todo", "tbd", "changeme", "test", "unknown", "fill in"}
)
_PLACEHOLDER_WORDS = re.compile(r"\b(?:placeholder|todo|tbd|changeme)\b", re.IGNORECASE)
_TEMPLATE_FIELD = re.compile(
    r"<\s*(?:fill[ _-]*in(?:[ _-]+here)?|name|value|date|operator|authority|"
    r"rights[ _-]*holder|notes?|here)\s*>"
    r"|\{\{[^{}]{0,50}\}\}",
    re.IGNORECASE,
)
# Outward operations must resolve deny for both manifests: restricted prose never leaves the
# operator's infrastructure through a third-party API or a raw/derived redistribution.
# Training and synthetic support are allowed by ADR-0025 and are no longer part of this list.
_OUTWARD_DENIED = (
    Operation.THIRD_PARTY_API,
    Operation.CLOUD_PROCESSING,
    Operation.REDISTRIBUTE_RAW,
    Operation.REDISTRIBUTE_DERIVED,
)
# Local operations this package's pipeline needs under the reviewed policy.
_LOCAL_REQUIRED = (
    Operation.INGEST,
    Operation.READ_RAW,
    Operation.EXTRACT,
    Operation.NORMALIZE,
    Operation.ALIGN,
)
# The deliberately induced adapter-side failure: eflomal exposes no seed control (ADR-0011 §6).
_NATIVE_SEED_CODE = "unsupported_seed"
# Upstream distribution identity of the pinned native backend (ADR-0011 §6, WP3.0 spike).
_NATIVE_ARCHIVE_SHA256 = "b71183dcf85bf4f59f44ef7a59f5268df1c17c0c8d8093f77b220025ffdba100"
# A distinctive key injected into operator-controlled metadata in the leak regressions. It is not
# a real book code and must never reach an assertion, a log line, a report or any output channel.
_METADATA_SENTINEL = "PRIVATE_SENTINEL"
# Top-level keys the signed expectations file may carry; anything else is a review error.
_EXPECTED_KEYS = frozenset(
    {
        "schema",
        "schema_version",
        "status",
        "reviewed_by",
        "reviewed_at",
        "review_note",
        "source_mzr",
        "source_por",
        "expected_counts",
        "notes",
    }
)
# Count names of the signed expectations, with one unambiguous meaning on both backends:
# every unmatched entry of the canonical report (verse and non-verse units), which equals
# the oracle's verse-only unmatched count plus the side's non-verse unit count.
_COUNT_KEYS = ("common_groups", "unmatched_source", "unmatched_target", "book_inventory")
# Backend options the pinned adapter reports for the recorded native run (ADR-0011 §6).
_NATIVE_OPTIONS = frozenset(
    {
        "model",
        "n_samplers",
        "threads",
        "omp_dynamic",
        "omp_max_active_levels",
        "timeout_seconds",
        "score_model",
        "random_seed",
        "randomness",
        "native_preprocessing",
        "scores",
    }
)


def _safe_fail(message: str, *, pytrace: bool = False) -> NoReturn:
    """``pytest.fail`` whose fixed diagnostic survives realdata report sanitization.

    Same contract as WP2.15: every message must already be content-free (ids, locators,
    hashes, counts, fixed prose) and ``pytrace`` must stay False.
    """
    if pytrace:
        raise AssertionError("safe diagnostics are content-free; pytrace must be False")
    pytest.fail(SAFE_DIAGNOSTIC_PREFIX + message, pytrace=False)


def _is_placeholder(value: str | None) -> bool:
    """True for blank values, standalone placeholders, placeholder words or template fields."""
    if value is None:
        return True
    stripped = value.strip()
    if not stripped or stripped.lower() in _PLACEHOLDER_VALUES:
        return True
    if _PLACEHOLDER_WORDS.search(stripped):
        return True
    return bool(_TEMPLATE_FIELD.search(stripped))


# ---------------------------------------------------------------------------------------------
# Manifest gate (policy before work)
# ---------------------------------------------------------------------------------------------


def _require_env() -> tuple[Path, Path, Path, Path]:
    """Both operator-supplied package directories and reviewed manifests, or a failure.

    Missing operator input is a failure, never a skip (M2 E9, WP3.13): this suite is a gate on
    governed dual-source processing, so it can never silently pass.
    """
    missing = [
        name
        for name, env in (
            ("mzr package directory", MZR_DIR_ENV),
            ("mzr manifest", MZR_MANIFEST_ENV),
            ("por package directory", POR_DIR_ENV),
            ("por manifest", POR_MANIFEST_ENV),
        )
        if not os.environ.get(env)
    ]
    if missing:
        _safe_fail(
            "missing operator input: " + ", ".join(missing) + "; this test never skips",
            pytrace=False,
        )
    mzr_dir = Path(os.environ[MZR_DIR_ENV])
    mzr_manifest = Path(os.environ[MZR_MANIFEST_ENV])
    por_dir = Path(os.environ[POR_DIR_ENV])
    por_manifest = Path(os.environ[POR_MANIFEST_ENV])
    for directory, label in ((mzr_dir, "mzr"), (por_dir, "por")):
        if not directory.is_dir():
            _safe_fail(f"the {label} package directory does not exist", pytrace=False)
    for path, label in ((mzr_manifest, "mzr"), (por_manifest, "por")):
        if not path.is_file():
            _safe_fail(f"the {label} reviewed manifest does not exist", pytrace=False)
    return mzr_dir, mzr_manifest, por_dir, por_manifest


def _reviewed_manifest(path: Path, label: str) -> SourceManifest:
    """Load and authorize one reviewed manifest before any package work happens."""
    try:
        manifest = load_manifest(path)
    except Exception:
        _safe_fail(f"the {label} manifest is not a valid source manifest", pytrace=False)
    _assert_authorized(manifest, label)
    return manifest


def _assert_authorized(manifest: SourceManifest, label: str) -> None:
    """Pre-work sanity check for one manifest, with content-free diagnostics.

    ADR-0025: a source present in the repository is authorized, so this checks only that the
    manifest records where the package came from, that every required local pipeline operation
    resolves allow, and that every outward operation resolves deny. Licences, authorities,
    rights holders, and permission notes are records and are not checked here.
    """
    policy = manifest.resolved_policy
    provenance = manifest.provenance
    if not provenance.acquired_from:
        _safe_fail(
            f"the {label} manifest must record where the package was acquired from", pytrace=False
        )
    for operation in _LOCAL_REQUIRED:
        if resolve(policy, operation) is not PolicyDecision.ALLOW:
            _safe_fail(
                f"required local pipeline operation {operation.value} must resolve allow "
                f"under the {label} manifest policy",
                pytrace=False,
            )
    for operation in _OUTWARD_DENIED:
        if resolve(policy, operation) is not PolicyDecision.DENY:
            _safe_fail(
                f"outward operation {operation.value} must resolve deny under the "
                f"{label} manifest policy",
                pytrace=False,
            )


def _declared_versification(manifest: SourceManifest, label: str) -> str:
    """The versification this package declares, from the reviewed manifest's restrictions.

    ScriptureEarth packages carry no internal versification table and the M3 model stores no
    versification field, so the operator records the declared edition in the reviewed manifest's
    opaque ``policy.restrictions`` map as ``versification_id``. A package that declares none
    cannot be coordinate-matched and fails closed rather than guessing an edition.
    """
    raw = manifest.resolved_policy.restrictions.get("versification_id")
    if not isinstance(raw, str) or not raw or _is_placeholder(raw):
        _safe_fail(
            f"the {label} manifest must declare a real versification in "
            "policy.restrictions.versification_id",
            pytrace=False,
        )
    return str(raw)


def _book_code(data: bytes) -> str | None:
    match = _ID_CODE.search(data)
    return match.group(1).decode("ascii").upper() if match else None


def _origin_path(origin_uri: str) -> Path:
    return Path(unquote(urlsplit(origin_uri).path))


# ---------------------------------------------------------------------------------------------
# Independent coordinate oracle (test-only; expands bridges, filters verse-only locators)
# ---------------------------------------------------------------------------------------------


def _positions(label: str) -> tuple[int | str, ...] | None:
    """Coordinate positions claimed by one verse label; ``None`` when malformed.

    Suffix labels (``3a``, ``8b``) keep their opaque label and never collapse into the bare
    number, exactly as ``CanonicalLocatorAligner`` does; they match only that exact label.
    """
    text = label.strip()
    if text.isdigit():
        return (int(text),)
    if _SUFFIX_LABEL.fullmatch(text):
        return (text,)  # opaque suffix label, never collapsed into the bare number
    if "-" in text:
        start, _, end = text.partition("-")
        if start.isdigit() and end.isdigit() and int(start) <= int(end):
            return tuple(range(int(start), int(end) + 1))
    return None


def _coordinates(segment: Any) -> tuple[str, ...]:
    """Coordinate keys of one persisted segment; ``()`` for non-verse or malformed locators."""
    locator = segment.locator
    if locator.get("unit") != "verse":
        return ()  # headings, introductions, notes and unknown blocks are excluded
    book = locator.get("book")
    chapter = locator.get("chapter")
    label = locator.get("verse")
    if not isinstance(book, str) or not book:
        return ()
    if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
        return ()
    if not isinstance(label, str):
        return ()
    positions = _positions(label)
    if positions is None:
        return ()
    return tuple(f"{book}|{chapter}|{value}" for value in positions)


@dataclass(frozen=True)
class _Piece:
    segment_id: str
    coordinates: tuple[str, ...]


@dataclass(frozen=True)
class _OracleSide:
    """One side's keyed verse-only segments as read back from persisted locators."""

    pieces: tuple[_Piece, ...]
    inventory: Mapping[str, int]
    declared_books: frozenset[str]

    @classmethod
    def of(cls, segments: Iterable[Any]) -> _OracleSide:
        pieces: list[_Piece] = []
        inventory: Counter[str] = Counter()
        declared: set[str] = set()
        for segment in segments:
            book = str(segment.locator.get("book", ""))
            if book:
                # A book is "declared" when it produced any segment, verse-shaped or not, so a
                # verse-free edition such as XXF stays visible in the inventory.
                declared.add(book)
            coordinates = _coordinates(segment)
            if not coordinates:
                continue
            pieces.append(_Piece(segment.id, coordinates))
            inventory[book] += 1
        return cls(tuple(pieces), dict(inventory), frozenset(declared))

    def book_count(self, book: str) -> int:
        """Verse-piece count for one book, retaining zero-verse books."""
        return self.inventory.get(book, 0)

    @property
    def segment_ids(self) -> set[str]:
        return {piece.segment_id for piece in self.pieces}

    def coverage(self, segment_id: str) -> frozenset[str]:
        """Coordinate coverage of one segment of this side."""
        return frozenset(
            coordinate
            for piece in self.pieces
            if piece.segment_id == segment_id
            for coordinate in piece.coordinates
        )


@dataclass(frozen=True)
class PairOracle:
    """Expected pair structure computed without the production aligner."""

    source: _OracleSide
    target: _OracleSide
    components: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]

    @classmethod
    def of(cls, source_segments: Iterable[Any], target_segments: Iterable[Any]) -> PairOracle:
        source = _OracleSide.of(source_segments)
        target = _OracleSide.of(target_segments)
        parent: dict[str, str] = {}

        def find(item: str) -> str:
            while parent.setdefault(item, item) != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        shared: dict[str, list[str]] = {}
        for piece in source.pieces:
            for coordinate in piece.coordinates:
                shared.setdefault(coordinate, []).append(piece.segment_id)
        target_shared: dict[str, list[str]] = {}
        for piece in target.pieces:
            for coordinate in piece.coordinates:
                target_shared.setdefault(coordinate, []).append(piece.segment_id)
        common = sorted(set(shared) & set(target_shared))
        for coordinate in common:
            nodes = sorted(set(shared[coordinate]) | set(target_shared[coordinate]))
            for other in nodes[1:]:
                union(nodes[0], other)
        groups: dict[str, tuple[set[str], set[str]]] = {}
        for piece in source.pieces:
            members = groups.setdefault(find(piece.segment_id), (set(), set()))
            members[0].add(piece.segment_id)
        for piece in target.pieces:
            members = groups.setdefault(find(piece.segment_id), (set(), set()))
            members[1].add(piece.segment_id)
        components = tuple(
            (tuple(sorted(left)), tuple(sorted(right)))
            for left, right in groups.values()
            if left and right
        )
        return cls(source, target, components)

    @property
    def group_count(self) -> int:
        return len(self.components)

    @property
    def matched_source(self) -> int:
        return sum(len(left) for left, _ in self.components)

    @property
    def matched_target(self) -> int:
        return sum(len(right) for _, right in self.components)

    @property
    def unmatched_source(self) -> int:
        return len(self.source.segment_ids) - self.matched_source

    @property
    def unmatched_target(self) -> int:
        return len(self.target.segment_ids) - self.matched_target

    def coverage_pairs(self) -> list[tuple[frozenset[str], frozenset[str]]]:
        """Per-component coordinate coverage of the source and the target side."""
        return [
            (
                frozenset().union(*(self.source.coverage(item) for item in left))
                if left
                else frozenset(),
                frozenset().union(*(self.target.coverage(item) for item in right))
                if right
                else frozenset(),
            )
            for left, right in self.components
        ]

    def structural_components(self) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
        """Components whose two sides claim exactly the same coordinate set."""
        return [
            component
            for component, (left, right) in zip(self.components, self.coverage_pairs(), strict=True)
            if left == right
        ]

    def partial_components(self) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
        """Components whose two sides claim different coordinate sets: candidate, not structural."""
        return [
            component
            for component, (left, right) in zip(self.components, self.coverage_pairs(), strict=True)
            if left != right
        ]

    @property
    def book_inventory(self) -> dict[str, list[int]]:
        """(source, target) verse counts per declared book, zero-retaining.

        A book is declared on a side when that side produced any segment for it, so a verse-free
        edition such as XXF is reported as ``[0, 0]`` rather than disappearing from the inventory.
        """
        declared = set(self.source.declared_books) | set(self.target.declared_books)
        return {
            book: [self.source.book_count(book), self.target.book_count(book)]
            for book in sorted(declared)
        }


# ---------------------------------------------------------------------------------------------
# Paired corpus fixture (function scoped; one local pipeline build per test)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Flow:
    source_id: str
    language: str
    manifest: SourceManifest
    normalization_run_id: str
    tokenization_run_id: str
    segments: tuple[str, ...]


@dataclass
class PairedCorpus:
    """Two reviewed language packages pinned for Stage 4 and Stage 5."""

    ctx: AppContext
    expected: dict[str, Any]
    source_language: str
    target_language: str
    versification_id: str
    flows: tuple[_Flow, _Flow]
    segment_alignment_run_id: str = ""
    token_alignment_run_id: str = ""

    @property
    def source(self) -> _Flow:
        return self.flows[0]

    @property
    def target(self) -> _Flow:
        return self.flows[1]

    @property
    def config(self) -> AlignmentConfig:
        return AlignmentConfig(
            namespace=SCRIPTURE_NAMESPACE, versification_id=self.versification_id
        )

    def side(self, language: str) -> AlignmentSide:
        flow = self.source if language == self.source_language else self.target
        return AlignmentSide(
            flow.source_id,
            flow.language,
            flow.normalization_run_id,
            flow.tokenization_run_id,
        )

    def segments(self, language: str) -> list[Any]:
        ctx = self.ctx
        flow = self.source if language == self.source_language else self.target
        return list(ctx.repo.list_segments_for_run(flow.normalization_run_id))


def _stepping_clock():
    ticks = count()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return lambda: start + timedelta(seconds=next(ticks))


def _memory_context(tmp_path: Path) -> AppContext:
    return AppContext(
        repo=InMemoryRepository(),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=_stepping_clock(),
        new_id=new_id,
        actor="realdata-actor",
        code_revision="realdata-rev",
    )


def _require_pair() -> tuple[Path, Path, Path, Path, SourceManifest, SourceManifest]:
    """Operator input plus both reviewed, authorized manifests (fail closed before any work)."""
    mzr_dir, mzr_manifest, por_dir, por_manifest = _require_env()
    return (
        mzr_dir,
        mzr_manifest,
        por_dir,
        por_manifest,
        _reviewed_manifest(mzr_manifest, "mzr"),
        _reviewed_manifest(por_manifest, "por"),
    )


def _pair_compatibility(
    mzr: SourceManifest, por: SourceManifest
) -> tuple[str, list[str], list[str]]:
    """The one pair-compatibility gate: declared languages and matching versification.

    Both packages must declare real, distinct languages and the **same** non-placeholder
    ``policy.restrictions.versification_id``. M3 has no automatic versification mapping
    (ADR-0011 §3), and neither language compatibility nor a versification match is something the
    generic segment service inspects. This is the only place the pair is validated, and it is
    called by *both* entry points — the memory ``_paired_corpus`` and the separate PostgreSQL
    path — before either one registers, ingests, extracts or aligns anything (senior review
    item 3).
    """
    mzr_languages = [str(language) for language in mzr.languages]
    por_languages = [str(language) for language in por.languages]
    if not mzr_languages or not por_languages:
        _safe_fail("both manifests must declare their package language", pytrace=False)
    if mzr_languages[0] == por_languages[0]:
        _safe_fail("the two packages declare the same language", pytrace=False)
    versification = _declared_versification(mzr, "mzr")
    if _declared_versification(por, "por") != versification:
        _safe_fail(
            "the mzr and por manifests declare different versification ids; M3 has no "
            "automatic versification mapping",
            pytrace=False,
        )
    return versification, mzr_languages, por_languages


def _build_flow(
    ctx: AppContext,
    manifest_path: Path,
    manifest: SourceManifest,
    language: str,
    label: str,
) -> _Flow:
    """Register, ingest, extract, normalize and tokenize one reviewed language package.

    Registration takes the reviewed manifest *path*: the loader re-reads it inside
    ``register_source``, so the bytes hashed at registration are the operator's file.
    """
    registration = register_source(ctx, manifest_path)
    ingest_source(ctx, registration.source.id)
    extraction = extract_source(ctx, registration.source.id)
    normalization = normalize_extraction(ctx, extraction.run.id)
    tokenization = tokenize_normalization(ctx, normalization.run.id)
    segments = tuple(
        segment.id
        for segment in ctx.repo.list_segments_for_run(normalization.run.id)
        if str(segment.locator.get("unit")) == "verse"
    )
    if not segments:
        _safe_fail(f"the {label} package produced no verse segments", pytrace=False)
    return _Flow(
        source_id=registration.source.id,
        language=language,
        manifest=manifest,
        normalization_run_id=normalization.run.id,
        tokenization_run_id=tokenization.run.id,
        segments=segments,
    )


def _paired_corpus(ctx: AppContext, tmp_path: Path) -> PairedCorpus:
    """The governed pair: both packages through Stage 2 and one canonical Stage 4 run."""
    (
        _mzr_dir,
        mzr_manifest_path,
        _por_dir,
        por_manifest_path,
        mzr,
        por,
    ) = _require_pair()
    versification, mzr_languages, por_languages = _pair_compatibility(mzr, por)
    del tmp_path
    source = _build_flow(ctx, mzr_manifest_path, mzr, mzr_languages[0], "mzr")
    target = _build_flow(ctx, por_manifest_path, por, por_languages[0], "por")
    if source.language == target.language:
        _safe_fail("the two packages declare the same language", pytrace=False)
    return PairedCorpus(
        ctx=ctx,
        expected=_load_expected(),
        source_language=source.language,
        target_language=target.language,
        versification_id=versification,
        flows=(source, target),
    )


def _stage4(corpus: PairedCorpus) -> Any:
    """Stage 4 over the reviewed pair under one declared versification."""
    service = SegmentAlignmentService(corpus.ctx)
    return service.align(
        corpus.side(corpus.source_language),
        corpus.side(corpus.target_language),
        config=corpus.config,
    )


def _group_tokens(
    ctx: AppContext, corpus: PairedCorpus, group: Any, side: str
) -> dict[str, list[Any]]:
    """Token occurrences of one group's side, pinned to the side's tokenization run.

    ``side`` is ``"source"`` or ``"target"``; tokens are returned per member segment in group
    order, each in token ordinal order — the same flattening the service performs.
    """
    flow = corpus.source if side == "source" else corpus.target
    segment_ids = group.source_segment_ids if side == "source" else group.target_segment_ids
    per_segment: dict[str, list[Any]] = {}
    for segment_id in segment_ids:
        tokens = sorted(
            (
                token
                for token in ctx.repo.list_tokens(segment_id)
                if token.run_id == flow.tokenization_run_id
            ),
            key=lambda item: item.ordinal,
        )
        per_segment[segment_id] = tokens
    return per_segment


def _flat_tokens(ctx: AppContext, corpus: PairedCorpus, group: Any, side: str) -> list[Any]:
    """One group side's token occurrences flattened in member order then token ordinal."""
    return [
        token for tokens in _group_tokens(ctx, corpus, group, side).values() for token in tokens
    ]


def _eligible_groups(corpus: PairedCorpus) -> tuple[list[Any], list[Any]]:
    """The groups ``TokenAlignmentService`` aligns: eligible status and two nonempty token sides.

    Eligibility is ``structural`` (or ``approved``) and nonempty tokens on both sides
    (ADR-0011 §2/§5); groups with an empty token side are reported as ``empty_token_side`` and
    excluded from the native batch. Groups excluded by status never reach the adapter at all.
    """
    alignments = corpus.ctx.repo.list_segment_alignments_for_run(corpus.segment_alignment_run_id)
    eligible: list[Any] = []
    skipped: list[Any] = []
    for group in alignments:
        if group.status not in (STRUCTURAL, AlignmentStatus.APPROVED):
            continue
        if _flat_tokens(corpus.ctx, corpus, group, "source") and _flat_tokens(
            corpus.ctx, corpus, group, "target"
        ):
            eligible.append(group)
        else:
            skipped.append(group)
    return eligible, skipped


def _stage5(corpus: PairedCorpus, **config: Any) -> Any:
    """Stage 5 native token alignment over the full eligible batch of the Stage 4 run.

    Optional keyword arguments override the corpus configuration (used to induce a
    deterministic adapter-side failure); the default is the corpus's own configuration.
    """
    effective = corpus.config if not config else AlignmentConfig(**config)
    return TokenAlignmentService(corpus.ctx).align(
        corpus.segment_alignment_run_id,
        source_tokenization_run_id=corpus.source.tokenization_run_id,
        target_tokenization_run_id=corpus.target.tokenization_run_id,
        method="eflomal@0.1.0",
        config=effective,
    )


def _unmatched_split(
    ctx: AppContext, corpus: PairedCorpus, run_id: str
) -> tuple[set[str], set[str], set[str], set[str]]:
    """Split one Stage 4 report's unmatched entries into (verse-only, non-verse) per side.

    The canonical report lists every extracted non-verse unit (headings, titles, notes, XXF
    front matter) as unmatched with a fixed reason (ADR-0011 §3), while the coordinate oracle
    only models verse locators. This helper separates the two populations by locator, so
    verse-only expectations are never compared against all-unit report counts and vice versa.
    """
    payload = _report_of(corpus, run_id, "alignment_file")
    selected = {
        segment.id
        for language in (corpus.source_language, corpus.target_language)
        for segment in corpus.segments(language)
    }
    verse_ids = {
        segment_id for segment_id in selected if _coordinates(ctx.repo.get_segment(segment_id))
    }
    verse_source, verse_target, other_source, other_target = set(), set(), set(), set()
    for side, verse_bucket, other_bucket in (
        ("unmatched_source", verse_source, other_source),
        ("unmatched_target", verse_target, other_target),
    ):
        for entry in payload[side]:
            segment_id = entry["segment_id"]
            if segment_id not in selected:
                _safe_fail("a reported unmatched segment is not a selected segment", pytrace=False)
            (verse_bucket if segment_id in verse_ids else other_bucket).add(segment_id)
    return verse_source, verse_target, other_source, other_target


def _non_verse_ids(corpus: PairedCorpus, language: str) -> set[str]:
    """Segment ids of one side that produced no verse coordinate (non-verse units)."""
    return {segment.id for segment in corpus.segments(language) if not _coordinates(segment)}


def _assert_unmatched_agrees(
    corpus: PairedCorpus, oracle: PairOracle, *, run_id: str | None = None
) -> None:
    """Verse-only unmatched ids equal the oracle; non-verse ids are unmatched by construction.

    Also asserts the complete partition of the selected input segments into matched and
    unmatched, with no segment counted twice. Imported by the synthetic suite so its
    compiler-free regressions exercise the same semantics.
    """
    if run_id is None:
        run_id = corpus.segment_alignment_run_id
    verse_source, verse_target, other_source, other_target = _unmatched_split(
        corpus.ctx, corpus, run_id
    )
    expected_verse_source = oracle.source.segment_ids - {
        segment_id for left, _right in oracle.components for segment_id in left
    }
    expected_verse_target = oracle.target.segment_ids - {
        segment_id for _left, right in oracle.components for segment_id in right
    }
    if verse_source != expected_verse_source or verse_target != expected_verse_target:
        _safe_fail(
            "reported verse-only unmatched ids differ from the independent rescan", pytrace=False
        )
    non_verse_source = _non_verse_ids(corpus, corpus.source_language)
    non_verse_target = _non_verse_ids(corpus, corpus.target_language)
    if other_source != non_verse_source or other_target != non_verse_target:
        _safe_fail(
            "reported non-verse unmatched ids are not exactly the non-verse units of the side",
            pytrace=False,
        )
    alignments = corpus.ctx.repo.list_segment_alignments_for_run(run_id)
    matched_source = {member for group in alignments for member in group.source_segment_ids}
    matched_target = {member for group in alignments for member in group.target_segment_ids}
    selected_source = {segment.id for segment in corpus.segments(corpus.source_language)}
    selected_target = {segment.id for segment in corpus.segments(corpus.target_language)}
    if matched_source & verse_source or matched_target & verse_target:
        _safe_fail("a verse segment is both matched and unmatched", pytrace=False)
    if matched_source & other_source or matched_target & other_target:
        _safe_fail("a non-verse unit is both matched and unmatched", pytrace=False)
    if matched_source | verse_source | other_source != selected_source:
        _safe_fail("the source partition is not the selected input segments", pytrace=False)
    if matched_target | verse_target | other_target != selected_target:
        _safe_fail("the target partition is not the selected input segments", pytrace=False)


def _report_of(corpus: PairedCorpus, run_id: str, kind: str) -> dict[str, Any]:
    """Alignment report payload of one run; report bytes only, never surface text."""
    for object_id, role in corpus.ctx.repo.list_run_io(run_id):
        if role is not RunIoRole.OUTPUT:
            continue
        artifact = corpus.ctx.repo.get_artifact(object_id)
        if artifact.kind.value != kind:
            continue
        return json.loads(corpus.ctx.artifact_store.read_bytes(artifact.sha256))
    raise AssertionError("run has no alignment report artifact")


def _lineage_parents(ctx: AppContext, object_id: str, kind: Any) -> set[str]:
    return {
        edge.to_id for edge in ctx.repo.list_lineage_edges(object_id, "out") if edge.kind is kind
    }


def _assert_no_surfaces(records: Iterable[Any], forbidden: Iterable[str], what: str) -> None:
    """No forbidden surface text, book path or native output may appear in ``records``.

    The haystack is the caller's actual evidence — the setup/call log records and the
    serialized reports — never a filename list. Diagnostics name only the forbidden *category*
    and never render the restricted value that matched (senior review item 2).
    """
    values = [text for text in forbidden if text]
    if not values:
        return
    haystack = "\n".join(str(record) for record in records)
    for text in values:
        if text in haystack:
            _safe_fail(f"{what} contains restricted content of a forbidden category", pytrace=False)


def _sampled_surfaces(corpus: PairedCorpus, side: str, *, limit: int = 8) -> list[str]:
    """A deterministic, bounded per-side sample of verse and non-verse stored surfaces.

    ``_Flow.segments`` holds verse segment ids only, so every segment of the side's selected
    normalization run is considered here — including non-verse units such as headings, notes and
    front matter, which the pipeline also processes. Used only for leak detection.
    """
    samples: list[str] = []
    for segment in corpus.segments(side):
        if len(samples) >= limit:
            break
        text = corpus.ctx.repo.get_segment(segment.id).raw_text
        if text:
            samples.append(text)
    return samples


def _forbidden_surfaces(corpus: PairedCorpus) -> list[str]:
    """Every restricted value the leak check must not find: surfaces and book paths.

    Surfaces are sampled independently per side and bounded per side, so a large source edition
    cannot push the target edition out of the sample. Paths cover every package object's full
    origin path, relative path and basename (senior review item 2).
    """
    values: list[str] = []
    for side in (corpus.source_language, corpus.target_language):
        values.extend(_sampled_surfaces(corpus, side))
    values.extend(_book_paths(corpus))
    return values


def _book_paths(corpus: PairedCorpus) -> list[str]:
    """Every package object's full origin path, relative path and basename, per flow.

    Timing objects are included: the ingest log and the pipeline mention them, so the leak check
    must be able to detect their paths. Used only for leak detection.
    """
    paths: list[str] = []
    for flow in corpus.flows:
        for source_object in corpus.ctx.repo.list_source_objects(flow.source_id):
            origin = _origin_path(source_object.origin_uri)
            absolute = str(origin)
            candidates = (
                absolute,
                origin.as_posix(),
                origin.name,
                source_object.original_path,
            )
            for candidate in candidates:
                if candidate:
                    paths.append(candidate)
    return paths


def _leak_haystack(corpus: PairedCorpus, run_ids: Sequence[str]) -> list[str]:
    """Setup/call log records plus both serialized alignment reports (senior review item 2)."""
    haystack: list[str] = []
    for run_id in run_ids:
        payload = _report_of(corpus, run_id, "alignment_file")
        haystack.append(json.dumps(payload, sort_keys=True))
    return haystack


def _assert_no_leaks(
    corpus: PairedCorpus,
    caplog: pytest.LogCaptureFixture,
    *,
    run_ids: Sequence[str],
    extra_records: Sequence[str] = (),
) -> None:
    """The single leak check: forbidden surfaces and paths against logs *and* both reports.

    ``records`` is the setup/call log evidence (optionally extended with caller-supplied record
    lines for compiler-free negative tests), and both serialized alignment reports are checked
    separately. The check never substitutes a filename list for the real haystack.
    """
    records: list[str] = list(_caplog_records(caplog))
    records.extend(extra_records)
    _assert_no_surfaces(records, _forbidden_surfaces(corpus), "captured logs")
    reports = _leak_haystack(corpus, run_ids)
    _assert_no_surfaces(reports, _forbidden_surfaces(corpus), "alignment report")


# ---------------------------------------------------------------------------------------------
# Compiler-free negative tests for the compatibility gate and the leak check (no corpus input)
# ---------------------------------------------------------------------------------------------

_GOOD_PERMISSION_NOTE = (
    "Local-processing permission record: the operator checked the license for this synthetic "
    "package on 2026-10-14; local derivative processing is permitted; the license text is "
    "archived by the operator."
)


def _compat_manifest(
    tmp_path: Path,
    *,
    language: str,
    key: str,
    versification: str | None = None,
    drop_versification: bool = False,
) -> SourceManifest:
    """One synthetic manifest for the pair-compatibility gate: no corpus input required.

    ``versification`` is written into ``policy.restrictions`` when given; ``drop_versification``
    writes the package with the restriction removed entirely.
    """
    package = tmp_path / f"compat-{key}"
    usfm = package / "usfm"
    usfm.mkdir(parents=True, exist_ok=True)
    (usfm / "TST.usfm").write_bytes(b"\\id TST\n\\c 1\n\\v 1 alpha\n")
    restrictions: dict[str, object] = {} if drop_versification else {}
    if not drop_versification and versification is not None:
        restrictions = {"versification_id": versification}
    policy = PolicySpec(
        mode=PolicyMode.DISTILL_ONLY,
        access_class=AccessClass.COMMUNITY,
        authority="Synthetic Pair Authority",
        allow=[Operation.ALIGN],
        restrictions=restrictions,  # type: ignore[arg-type]
    )
    provenance = Provenance(
        acquired_from="https://www.scriptureearth.org/00por.php?iso=zzz",
        rights_holder="Synthetic Pair Rights Holder",
        notes=_GOOD_PERMISSION_NOTE,
    )
    return build_manifest(
        scan_package(package),
        key=f"synthetic-{key}",
        language=language,
        policy=policy,
        provenance=provenance,
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_pair_compatibility_rejects_missing_or_mismatched_declarations(tmp_path: Path) -> None:
    """A missing, placeholder or mismatched por declaration fails before any build flow runs.

    This is the test-local gate ``_pair_compatibility``: matching non-placeholder
    ``versification_id`` and two distinct declared languages. It is the only place the pair is
    validated and is called by both entry points (senior review item 3).
    """
    good_mzr = _compat_manifest(tmp_path, language="mzr", key="mzr", versification="vrs-1")
    good_por = _compat_manifest(tmp_path, language="por", key="por", versification="vrs-1")
    versification, languages_mzr, languages_por = _pair_compatibility(good_mzr, good_por)
    assert versification == "vrs-1"
    assert languages_mzr == ["mzr"]
    assert languages_por == ["por"]

    missing_por = _compat_manifest(
        tmp_path, language="por", key="por-missing", drop_versification=True
    )
    for por in (
        missing_por,
        _compat_manifest(tmp_path, language="por", key="por-none", versification=None),
        _compat_manifest(
            tmp_path, language="por", key="por-placeholder", versification="placeholder"
        ),
        _compat_manifest(tmp_path, language="por", key="por-other", versification="vrs-2"),
        _compat_manifest(tmp_path, language="mzr", key="por-same-language", versification="vrs-1"),
    ):
        with pytest.raises(pytest.fail.Exception):
            _pair_compatibility(good_mzr, por)


def test_pair_compatibility_failure_never_calls_build_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both entry points call the gate *before* ``_build_flow`` and any alignment service.

    A sentinel replaces ``_build_flow`` so a pair reaching the pipeline is an immediate
    failure: missing or mismatched por declarations must fail the compatibility gate without
    registering, ingesting, extracting, tokenizing or aligning anything. The memory
    ``_paired_corpus`` and the separate PostgreSQL entry point call the same
    ``_pair_compatibility`` first, and both read their manifests through ``_require_pair``, so
    the sentinel proves the memory path's ordering (senior review item 3).
    """

    def _sentinel(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("build flow must not be called before pair compatibility passes")

    monkeypatch.setattr("tests.integration.test_scriptureearth_parallel._build_flow", _sentinel)
    mzr_manifest = _compat_manifest(tmp_path, language="mzr", key="gate-mzr", versification="vrs-1")
    por_manifest = _compat_manifest(tmp_path, language="por", key="gate-por", versification="vrs-2")
    monkeypatch.setattr(
        "tests.integration.test_scriptureearth_parallel._require_pair",
        lambda: (
            tmp_path,
            tmp_path / "mzr.yaml",
            tmp_path,
            tmp_path / "por.yaml",
            mzr_manifest,
            por_manifest,
        ),
    )
    ctx = _memory_context(tmp_path)
    with pytest.raises(pytest.fail.Exception):
        _paired_corpus(ctx, tmp_path)


def _leak_stub_corpus(tmp_path: Path) -> Any:
    """A minimal stand-in carrying only the objects the leak helpers read.

    Built from a synthetic pipeline: two sides with verse and non-verse segments, registered
    source objects with origin URIs. The compiler-free negative tests inject forbidden values
    into log records and report payloads and prove the helper fails content-free (item 2).
    """

    ctx = AppContext(
        repo=InMemoryRepository(),
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=_stepping_clock(),
        new_id=new_id,
        actor="leak-stub-actor",
        code_revision="leak-stub-rev",
    )
    pair = _synthetic_pair(ctx, tmp_path, "leak-stub")
    summary = _synthetic_stage4(ctx, pair)
    return PairedCorpus(
        ctx=ctx,
        expected=_load_expected(),
        source_language=pair.source.language,
        target_language=pair.target.language,
        versification_id=VERSIFICATION,
        flows=(
            _Flow(
                source_id=pair.source.source_id,
                language=pair.source.language,
                manifest=None,  # type: ignore[arg-type]
                normalization_run_id=pair.source.normalization_run_id,
                tokenization_run_id=pair.source.tokenization_run_id,
                segments=pair.source.segment_ids,
            ),
            _Flow(
                source_id=pair.target.source_id,
                language=pair.target.language,
                manifest=None,  # type: ignore[arg-type]
                normalization_run_id=pair.target.normalization_run_id,
                tokenization_run_id=pair.target.tokenization_run_id,
                segments=pair.target.segment_ids,
            ),
        ),
        segment_alignment_run_id=summary.run.id,
    )


def test_leak_check_fails_on_injected_por_surface_without_rendering_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A por-side surface injected into a log record fails the check content-free."""
    corpus = _leak_stub_corpus(tmp_path)
    por_samples = _sampled_surfaces(corpus, corpus.target_language, limit=2)
    assert por_samples, "synthetic pair must produce por surfaces"
    leaked = por_samples[0]
    assert leaked not in _leak_haystack(corpus, (corpus.segment_alignment_run_id,))
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _assert_no_leaks(
            corpus,
            caplog,
            run_ids=(corpus.segment_alignment_run_id,),
            extra_records=(f"event=synthetic.leak value={leaked}",),
        )
    assert leaked not in str(excinfo.value)


def test_leak_check_fails_on_injected_non_verse_surface_without_rendering_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-verse unit's surface injected into a log record fails the check content-free."""
    corpus = _leak_stub_corpus(tmp_path)
    non_verse = [
        segment.raw_text
        for segment in corpus.segments(corpus.source_language)
        if not _coordinates(segment)
    ]
    assert non_verse, "synthetic pair must produce non-verse units"
    leaked = non_verse[0]
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _assert_no_leaks(
            corpus,
            caplog,
            run_ids=(corpus.segment_alignment_run_id,),
            extra_records=(f"event=synthetic.leak value={leaked}",),
        )
    assert leaked not in str(excinfo.value)


def test_leak_check_fails_on_injected_full_and_relative_book_paths(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A full origin path and a relative book path injected into logs both fail content-free."""
    corpus = _leak_stub_corpus(tmp_path)
    paths = _book_paths(corpus)
    assert paths, "synthetic pair must register book paths"
    full_paths = [path for path in paths if path.startswith("/")]
    relative_paths = [path for path in paths if not path.startswith("/") and "/" not in path]
    assert full_paths and relative_paths
    for leaked in (full_paths[0], relative_paths[0]):
        with pytest.raises(pytest.fail.Exception) as excinfo:
            _assert_no_leaks(
                corpus,
                caplog,
                run_ids=(corpus.segment_alignment_run_id,),
                extra_records=(f"event=synthetic.leak value={leaked}",),
            )
        assert leaked not in str(excinfo.value)


def test_leak_check_passes_on_clean_synthetic_logs_and_reports(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Clean synthetic input passes: no surface or path appears in the real haystacks."""
    corpus = _leak_stub_corpus(tmp_path)
    _assert_no_leaks(corpus, caplog, run_ids=(corpus.segment_alignment_run_id,))


@pytest.fixture
def paired_corpus(tmp_path: Path) -> PairedCorpus:
    """Fresh memory corpus per test (WP2.15 parity): function scoped, stores under tmp_path.

    The scope is load-bearing: each test's own pipeline run lands in that test's setup-phase
    caplog records, so the leak check covers the pipeline it caused and no test observes another
    test's state. The PostgreSQL case is a separate test with its own context.
    """
    ctx = _memory_context(tmp_path)
    corpus = _paired_corpus(ctx, tmp_path)
    summary = _stage4(corpus)
    corpus.segment_alignment_run_id = summary.run.id
    return corpus


@pytest.fixture
def aligned_pair(paired_corpus: PairedCorpus) -> PairedCorpus:
    """The governed pair after Stage 4 and one full native Stage 5 batch.

    The batch is the complete eligible set of the Stage 4 run — nothing is selected or
    dropped — so the fixture proves the native path end to end for the whole reviewed pair.
    """
    corpus = paired_corpus
    summary = _stage5(corpus)
    corpus.token_alignment_run_id = summary.run.id
    return corpus


# ---------------------------------------------------------------------------------------------
# Expectations file (metadata only)
# ---------------------------------------------------------------------------------------------


def _load_expected() -> dict[str, Any]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def _signed_count(value: Any, what: str, *, nullable: bool = False) -> int:
    """A nonnegative integer count, or a failure.

    Unsigned templates are rejected by the signature gate before any count is read, so
    ``_signed_count`` itself never tolerates ``None``: only the explicit unsigned-template
    self-check passes ``nullable=True`` to validate that the template keeps ``null`` counts
    (senior review item 1). Anything else — a bool, a float, a negative number, a placeholder
    string, ``None`` — is rejected here before the value is interpolated into a diagnostic.

    ``what`` is a *fixed* label built from a constant field name or a numeric entry position.
    Callers never pass an untrusted metadata value (a book code, a digest, an edition string),
    because the resulting ``_safe_fail`` message is marked safe and would otherwise render it
    (senior review item 2).
    """
    if value is None:
        if nullable:
            return -1
        _safe_fail(f"{what} must be a nonnegative integer count", pytrace=False)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _safe_fail(f"{what} must be a nonnegative integer count", pytrace=False)
    return value


def _signed_metadata(
    value: Any, what: str, *, nullable: bool = False, placeholder: bool = False
) -> str:
    """A nonempty non-placeholder string; unsigned templates keep the ``UNREVIEWED`` placeholder.

    ``nullable=True`` tolerates ``None`` (unsigned template) and ``placeholder=True``
    additionally accepts the reviewed file's own ``UNREVIEWED`` edition/versification strings
    during structural validation, before the signature gate runs. The gate itself demands real
    values, so a signed file keeps neither.
    """
    if value is None:
        if nullable:
            return ""
        _safe_fail(f"{what} must be recorded before the counts are signed", pytrace=False)
    if placeholder and isinstance(value, str) and value.startswith("UNREVIEWED"):
        return value  # structural validation only: the signature gate rejects this below
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.startswith("UNREVIEWED")
        or _is_placeholder(value)
    ):
        _safe_fail(f"{what} must be a real reviewed value, not a placeholder", pytrace=False)
    return value


def _reviewed_gate(expected: dict[str, Any]) -> None:
    """The expectations file must be structurally valid *and* signed before it is used.

    Three separate failures: a malformed file is rejected by ``_validate_expected`` with fixed
    diagnostics; an unsigned but well-formed template fails the signature gate, because a senior
    must independently rescan and sign the counts (WP3.13); and a *reviewed* file whose
    reviewed fields are incomplete or whose counts/editions are still template placeholders
    fails the completed-record gate. An unsigned template is the only legal state carrying
    ``null`` counts and ``UNREVIEWED`` edition/versification placeholders, and it must not pass
    this gate even when ``reviewed_by`` is set (senior review item 1). Every diagnostic is built
    from fixed prose, constant field names and numeric entry positions only, so validating an
    operator-supplied record can never render that record's metadata (item 2).
    """
    _validate_expected(expected)
    status = expected["status"]
    if status != "reviewed":
        _safe_fail(
            "scriptureearth_parallel_counts.json is unsigned: a senior must run both packages, "
            "cross-check the counts against an independent rescan and set reviewed_by",
            pytrace=False,
        )
    reviewer = expected.get("reviewed_by")
    if not isinstance(reviewer, str) or _is_placeholder(reviewer):
        _safe_fail(
            "a reviewed counts file must name a real, non-placeholder reviewer",
            pytrace=False,
        )
    _signed_timestamp(expected.get("reviewed_at"), "reviewed_at")
    for side in ("source_mzr", "source_por"):
        entry = expected[side]
        for key in ("edition", "versification"):
            value = entry[key]
            if not isinstance(value, str) or not value.strip():
                _safe_fail(
                    f"{side}.{key} must be recorded before the counts are signed", pytrace=False
                )
            if value.startswith("UNREVIEWED"):
                _safe_fail(
                    f"{side}.{key} is still the unsigned placeholder; a senior must record the "
                    "reviewed value before signing",
                    pytrace=False,
                )
    counts = expected["expected_counts"]
    for key in _COUNT_KEYS:
        if counts.get(key) is None:
            _safe_fail(
                f"expected_counts.{key} must be reviewed and recorded before the file is signed",
                pytrace=False,
            )
    inventory = counts.get("book_inventory")
    if isinstance(inventory, dict):
        for _book, pair in inventory.items():
            if not isinstance(pair, list) or len(pair) != 2 or any(item is None for item in pair):
                _safe_fail(
                    "expected_counts.book_inventory must record reviewed counts for every book "
                    "before the file is signed",
                    pytrace=False,
                )


def _validate_expected(expected: dict[str, Any]) -> None:
    """Strict structural validation of the metadata-only expectations file.

    Rejects unknown keys, placeholder or blank strings, non-datetime review stamps, bad
    statuses, non-integer counts and malformed hash inventories *before* any value is
    interpolated into a diagnostic. Hash inventories are checked for shape only; the byte
    comparison against the packages happens in ``test_pair_hashes_unchanged``.
    """
    unknown = sorted(set(expected) - _EXPECTED_KEYS)
    if unknown:
        _safe_fail(f"expected counts file has {len(unknown)} unknown top-level keys", pytrace=False)
    for key in ("schema", "schema_version", "status", "review_note"):
        if key not in expected:
            _safe_fail(f"expected counts file is missing {key}", pytrace=False)
    if expected["schema"] != "scriptureearth-parallel-counts" or expected["schema_version"] != 1:
        _safe_fail("expected counts file declares an unexpected schema or version", pytrace=False)
    _signed_metadata(expected["review_note"], "review_note")
    status = expected["status"]
    if status not in ("unsigned", "reviewed"):
        _safe_fail("expected counts file status must be unsigned or reviewed", pytrace=False)
    for side in ("source_mzr", "source_por"):
        entry = expected.get(side)
        if not isinstance(entry, dict):
            _safe_fail(f"expected counts file is missing {side}", pytrace=False)
        unknown_side = sorted(
            set(entry)
            - {"declared_edition_language", "edition", "versification", "package_sha256_inventory"}
        )
        if unknown_side:
            _safe_fail(f"{side} has {len(unknown_side)} unknown keys", pytrace=False)
        for key in ("declared_edition_language", "edition", "versification"):
            if key not in entry:
                _safe_fail(f"expected counts file is missing {side}.{key}", pytrace=False)
            # The unsigned template keeps ``UNREVIEWED - ...`` placeholders; anything else must
            # be a real value, never a silent placeholder. The signature gate then demands real
            # values, so a signed file keeps no placeholder (senior review item 1).
            _signed_metadata(entry[key], f"{side}.{key}", placeholder=True)
        if {"source_mzr": "mzr", "source_por": "por"}[side] != entry["declared_edition_language"]:
            _safe_fail(f"{side} declares an unexpected edition language", pytrace=False)
        inventory = entry["package_sha256_inventory"]
        if not isinstance(inventory, dict):
            _safe_fail(f"{side}.package_sha256_inventory must be a hash-to-size map", pytrace=False)
        for digest, size in inventory.items():
            if not _SHA256.fullmatch(digest):
                _safe_fail(
                    f"{side} inventory contains a key that is not a sha256 digest", pytrace=False
                )
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                _safe_fail(
                    f"{side} inventory contains a malformed size for one registered object",
                    pytrace=False,
                )
    counts = expected.get("expected_counts")
    if not isinstance(counts, dict):
        _safe_fail("expected counts file is missing expected_counts", pytrace=False)
    unknown_counts = sorted(set(counts) - set(_COUNT_KEYS))
    if unknown_counts:
        _safe_fail(f"expected_counts has {len(unknown_counts)} unknown keys", pytrace=False)
    for key in _COUNT_KEYS:
        if key not in counts:
            _safe_fail(f"expected counts file is missing expected_counts.{key}", pytrace=False)
        if key == "book_inventory":
            continue
        # Null is the unsigned template's marker; every other shape is a shape error. The
        # signature gate rejects null counts on a reviewed file (senior review item 1).
        _signed_count(counts[key], f"expected_counts.{key}", nullable=True)
    inventory_counts = counts["book_inventory"]
    if not isinstance(inventory_counts, dict):
        _safe_fail(
            "expected_counts.book_inventory must be a book to [source, target] map", pytrace=False
        )
    for position, (_book, pair) in enumerate(inventory_counts.items()):
        if not isinstance(pair, list) or len(pair) != 2:
            _safe_fail("expected_counts.book_inventory has a malformed entry", pytrace=False)
        for side_value in pair:
            # The book key is untrusted review metadata, so the label names the entry's numeric
            # position only (senior review item 2).
            _signed_count(
                side_value,
                f"expected_counts.book_inventory entry {position}",
                nullable=True,
            )


def _signed_timestamp(value: Any, what: str) -> str:
    """An RFC 3339 UTC timestamp string, or a failure."""
    if not isinstance(value, str) or not value.strip():
        _safe_fail(f"{what} must be an RFC 3339 timestamp", pytrace=False)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _safe_fail(f"{what} must be an RFC 3339 timestamp", pytrace=False)
        raise AssertionError from None  # unreachable: _safe_fail never returns
    if parsed.tzinfo is None:
        _safe_fail(f"{what} must be timezone-aware", pytrace=False)
    return value


def _complete_reviewed_record() -> dict[str, Any]:
    """A synthetic *complete* reviewed record: every gate field real, no placeholder anywhere.

    This fixture proves the gate's positive case without the governed corpus: it is metadata
    only (hashes, sizes, edition ids, versification ids, counts and book codes) and carries no
    package bytes, surface text or operator path. It never stands in for a senior's independent
    rescan of the real pair and is never written into the committed expectations file.
    """
    digest_a = hashlib.sha256(b"wp313-synthetic-mzr-inventory-a").hexdigest()
    digest_b = hashlib.sha256(b"wp313-synthetic-por-inventory-b").hexdigest()
    return {
        "schema": "scriptureearth-parallel-counts",
        "schema_version": 1,
        "status": "reviewed",
        "reviewed_by": "named-reviewer",
        "reviewed_at": "2026-10-14T12:00:00Z",
        "review_note": "Synthetic complete record used only to prove the gate's positive case.",
        "source_mzr": {
            "declared_edition_language": "mzr",
            "edition": "scriptureearth-mzr-2026",
            "versification": "synthetic-vrs-1",
            "package_sha256_inventory": {digest_a: 12},
        },
        "source_por": {
            "declared_edition_language": "por",
            "edition": "scriptureearth-por-2026",
            "versification": "synthetic-vrs-1",
            "package_sha256_inventory": {digest_b: 34},
        },
        "expected_counts": {
            "common_groups": 3,
            "unmatched_source": 7,
            "unmatched_target": 9,
            "book_inventory": {"TST": [7, 7], "XXF": [0, 0]},
        },
        "notes": "Synthetic record; no corpus content is recorded here.",
    }


def _unsigned_template_record() -> dict[str, Any]:
    """The unsigned template state built in memory, independent of any file on disk.

    Negative tests never read (or write) the committed expectations file: they build the
    template here, so changing the disk state — including a senior signing it — cannot change a
    negative verdict. The record is metadata only: placeholders, null counts and empty
    inventories, exactly like the committed template.
    """
    return {
        "schema": "scriptureearth-parallel-counts",
        "schema_version": 1,
        "status": "unsigned",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_note": (
            "Metadata-only synthetic template for the negative tests; never written to disk."
        ),
        "source_mzr": {
            "declared_edition_language": "mzr",
            "edition": "UNREVIEWED - operator must record the mzr edition",
            "versification": "UNREVIEWED - operator must record the mzr versification",
            "package_sha256_inventory": {},
        },
        "source_por": {
            "declared_edition_language": "por",
            "edition": "UNREVIEWED - operator must record the por edition",
            "versification": "UNREVIEWED - operator must record the por versification",
            "package_sha256_inventory": {},
        },
        "expected_counts": {
            "common_groups": None,
            "unmatched_source": None,
            "unmatched_target": None,
            "book_inventory": {},
        },
        "notes": "Synthetic template; no corpus content is recorded here.",
    }


@REALDATA
def test_unsigned_template_fails_the_review_gate_even_when_a_reviewer_is_named() -> None:
    """Senior reproduction 1: a reviewer name on an unsigned template must not open the gate.

    Only a ``status == "reviewed"`` record with real reviewer, timestamp, editions,
    versification ids and counts passes; the unsigned template keeps ``null`` counts and
    ``UNREVIEWED`` placeholders and is rejected with the safe unsigned diagnostic — even when a
    reviewer name and timestamp are set. The template is built in memory, so the negative verdict
    never depends on the committed file's state (senior review item 1).
    """
    template = _unsigned_template_record()
    _validate_expected(template)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _reviewed_gate(template)
    assert "is unsigned" in str(excinfo.value)

    named = json.loads(json.dumps(template))
    named["reviewed_by"] = "named-reviewer"
    named["reviewed_at"] = "2026-10-14T12:00:00Z"
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _reviewed_gate(named)
    assert "is unsigned" in str(excinfo.value)


@pytest.mark.parametrize(
    ("read_source", "status"),
    [
        ("template", "unsigned"),
        ("complete", "reviewed"),
        ("complete", "unsigned"),
    ],
)
def test_review_gate_verdict_follows_the_patched_disk_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str, read_source: str
) -> None:
    """Gate verdict by status, with the disk record supplied through ``Path.read_text``.

    No test writes to the expectations file: ``Path.read_text`` is patched to return either the
    unsigned template or the complete reviewed record, and the gate's verdict follows the record
    the *reader* would serve — not what happens to be on disk today. A template (``unsigned``)
    is rejected even when the file otherwise satisfies its structural contract, a complete record
    (``reviewed``) passes, and a complete record carrying an ``unsigned`` status is still
    rejected. Signing the checked-in file therefore cannot break this suite in either direction
    (senior review item 1).
    """
    payload = (
        _unsigned_template_record() if read_source == "template" else _complete_reviewed_record()
    )
    payload["status"] = status
    payload_text = json.dumps(payload)

    real_read_text = Path.read_text

    def _patched_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == EXPECTED_PATH:
            return payload_text
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)
    loaded = _load_expected()
    _validate_expected(loaded)
    if status == "reviewed":
        _reviewed_gate(loaded)
    else:
        with pytest.raises(pytest.fail.Exception) as excinfo:
            _reviewed_gate(loaded)
        assert "is unsigned" in str(excinfo.value)
    del tmp_path


@REALDATA
def test_reviewed_record_with_null_counts_or_placeholder_editions_fails_the_gate() -> None:
    """Senior reproduction 2: ``status: reviewed`` never substitutes for complete fields.

    Every individually incomplete field of an otherwise complete reviewed record is rejected,
    and the fully complete record passes.
    """
    complete = _complete_reviewed_record()
    _reviewed_gate(complete)

    incomplete: list[tuple[str, dict[str, Any]]] = [
        ("null common_groups", _patch(complete, "expected_counts", "common_groups", None)),
        ("null unmatched_source", _patch(complete, "expected_counts", "unmatched_source", None)),
        ("null unmatched_target", _patch(complete, "expected_counts", "unmatched_target", None)),
        (
            "null book inventory pair",
            _patch(complete, "expected_counts", "book_inventory", {"TST": [None, None]}),
        ),
        ("bool count", _patch(complete, "expected_counts", "common_groups", True)),
        ("negative count", _patch(complete, "expected_counts", "common_groups", -1)),
        ("float count", _patch(complete, "expected_counts", "common_groups", 1.5)),
        (
            "placeholder mzr edition",
            _patch(complete, "source_mzr", "edition", "UNREVIEWED - operator must record it"),
        ),
        (
            "placeholder por versification",
            _patch(complete, "source_por", "versification", "UNREVIEWED - operator records"),
        ),
        ("blank por edition", _patch(complete, "source_por", "edition", "   ")),
        ("missing reviewer", _patch(complete, "reviewed_by", "reviewed_by", None)),
        ("placeholder reviewer", _patch(complete, "reviewed_by", "reviewed_by", "placeholder")),
        ("missing timestamp", _patch(complete, "reviewed_at", "reviewed_at", None)),
        ("naive timestamp", _patch(complete, "reviewed_at", "reviewed_at", "2026-10-14T12:00:00")),
        ("malformed timestamp", _patch(complete, "reviewed_at", "reviewed_at", "not a timestamp")),
        ("unsigned status", _patch(complete, "status", "status", "unsigned")),
    ]
    for what, broken in incomplete:
        with pytest.raises(pytest.fail.Exception) as excinfo:
            _reviewed_gate(broken)
        message = str(excinfo.value)
        assert message.startswith(SAFE_DIAGNOSTIC_PREFIX), what
        # A content-free diagnostic never renders the restricted value that triggered it: only
        # fixed diagnostics survive sanitization, so no injected value that is not itself a
        # word of the fixed prose appears in the message.
        for value in _injected_values(broken):
            if value in {"placeholder", "unsigned", "True", "False", "3", "-1", "1.5", "   "}:
                continue  # ordinary diagnostic vocabulary, never restricted material
            assert value not in message, what


@REALDATA
def test_distinctive_metadata_keys_never_reach_a_safe_diagnostic() -> None:
    """Senior reproduction 3: an arbitrary book key in ``book_inventory`` is never rendered.

    The count validator's field label names a *numeric entry position*, never the book code, so
    a distinctive injected key is absent from the gate's safe-marked exception. The safe marker
    bypasses realdata redaction, so this is the only channel that could carry it.
    """
    record = _complete_reviewed_record()
    record["expected_counts"]["book_inventory"] = {_METADATA_SENTINEL: [-1, 0]}
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _reviewed_gate(record)
    message = str(excinfo.value)
    assert message.startswith(SAFE_DIAGNOSTIC_PREFIX)
    assert _METADATA_SENTINEL not in message
    assert "book_inventory" in message  # the fixed field name survives


@REALDATA
def test_distinctive_metadata_key_never_reaches_realdata_output(tmp_path: Path) -> None:
    """Full-output regression: the sentinel key stays out of the realdata report channels.

    Runs a generated realdata test in a pytest subprocess (``test_scriptureearth_marubo.py``
    WP2.15 pattern): the test applies the gate to a record whose ``book_inventory`` carries the
    distinctive key and fails. Both the complete stdout/stderr and the serialized JUnit XML must
    stay free of the sentinel, while the failure still fails and keeps the safe diagnostic.
    """
    test_source = (
        "import pytest\n"
        "\n"
        "from tests.integration.test_scriptureearth_parallel import (\n"
        "    _complete_reviewed_record,\n"
        "    _reviewed_gate,\n"
        ")\n"
        "\n"
        "\n"
        "@pytest.mark.realdata\n"
        "def test_gate_rejects_sentinel_metadata_key() -> None:\n"
        "    record = _complete_reviewed_record()\n"
        f"    record['expected_counts']['book_inventory'] = {{{_METADATA_SENTINEL!r}: [-1, 0]}}\n"
        "    _reviewed_gate(record)\n"
    )
    assert "_reviewed_gate" in test_source  # the generated module uses the real gate, not a copy
    code, output = _run_pytest_subprocess(tmp_path, test_source, select_realdata=True, junit=True)
    junit = (tmp_path / "junit.xml").read_text(encoding="utf-8")
    assert _METADATA_SENTINEL not in output
    assert _METADATA_SENTINEL not in junit
    assert code == 1, output
    assert "safe-diagnostic" in output
    assert "safe-diagnostic" in junit


def _run_pytest_subprocess(
    tmp_path: Path, source: str, *, select_realdata: bool, junit: bool = False
) -> tuple[int, str]:
    """One generated synthetic test under a real pytest subprocess (WP2.15 pattern).

    The generated conftest re-exports the production ``realdata`` report-sanitization hook, so the
    run exercises the exact capture/report behavior real-data tests get. Returns the exit code and
    the complete stdout+stderr; with ``junit`` reports are also serialized to
    ``tmp_path/"junit.xml"`` so every rendering channel can be asserted content-free.
    """
    repo_root = Path(__file__).resolve().parents[2]
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "conftest.py").write_text(
        "from tests.integration.conftest import pytest_runtest_makereport  # noqa: F401\n",
        encoding="utf-8",
    )
    test_file = case_dir / "test_generated.py"
    test_file.write_text(source, encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "-c", str(repo_root / "pyproject.toml")]
    if select_realdata:
        command += ["-m", "realdata"]
    command += [str(test_file), "-q"]
    if junit:
        command.append(f"--junitxml={tmp_path / 'junit.xml'}")
    completed = subprocess.run(
        command, cwd=repo_root, capture_output=True, text=True, timeout=600, check=False
    )
    return completed.returncode, completed.stdout + completed.stderr


def _injected_values(record: dict[str, Any]) -> list[str]:
    """The non-canonical operator values one gate probe injected, for content-free assertions."""
    complete = json.loads(json.dumps(_complete_reviewed_record()))
    clone = json.loads(json.dumps(record))
    values: list[str] = []

    def _walk(original: Any, changed: Any) -> None:
        if isinstance(original, dict) and isinstance(changed, dict):
            for key in set(original) | set(changed):
                _walk(original.get(key), changed.get(key))
        elif isinstance(original, list) and isinstance(changed, list):
            for left, right in zip(original, changed, strict=False):
                _walk(left, right)
        elif original != changed and changed is not None:
            values.append(str(changed))

    _walk(complete, clone)
    return values


def _patch(record: dict[str, Any], section: str, key: str, value: Any) -> dict[str, Any]:
    """A deep copy of ``record`` with one field replaced, for per-field gate probes.

    ``section`` is a top-level key holding a dict (``source_mzr``, ``expected_counts``) or a
    scalar field itself (``reviewed_by``, ``reviewed_at``, ``status``), so both levels can be
    probed individually.
    """
    clone = json.loads(json.dumps(record))
    target = clone[section]
    if isinstance(target, dict):
        target[key] = value
    else:
        clone[section] = value
    return clone


@REALDATA
def test_signed_validators_reject_unsigned_shapes_and_accept_real_values() -> None:
    """The signed validators are strict on their own: null counts and placeholder editions fail.

    ``_signed_count`` and ``_signed_metadata`` are called directly (never through copies), so
    the compiler-free negative tests exercise the realdata gate's own validators. Only the
    explicit unsigned-template self-check tolerates ``None``/``UNREVIEWED``.
    """
    assert _signed_count(0, "x") == 0
    assert _signed_count(5594, "x") == 5594
    for bad in (None, True, False, -1, "5", 1.5, [1]):
        with pytest.raises(pytest.fail.Exception):
            _signed_count(bad, "x")
    assert _signed_count(None, "x", nullable=True) == -1

    assert _signed_metadata("scriptureearth-mzr-2026", "x")
    for bad in (None, "", "   ", "placeholder", "TODO", "changeme", "<name>", "{{authority}}"):
        with pytest.raises(pytest.fail.Exception):
            _signed_metadata(bad, "x")
    assert _signed_metadata(None, "x", nullable=True) == ""
    assert _signed_metadata("UNREVIEWED - operator records", "x", placeholder=True)
    with pytest.raises(pytest.fail.Exception):
        _signed_metadata("UNREVIEWED - operator records", "x")
    assert _signed_timestamp("2026-10-14T12:00:00Z", "x") == "2026-10-14T12:00:00Z"
    for bad in (None, "", "2026-10-14", "2026-10-14T12:00:00", "not a timestamp"):
        with pytest.raises(pytest.fail.Exception):
            _signed_timestamp(bad, "x")


@REALDATA
def test_expected_counts_file_is_metadata_only() -> None:
    """The expectations file records hash inventories, editions, versification and counts —
    never surface text, book content or operator paths, in either of its two legal states.

    Validated by its own status: an unsigned template is structurally valid and fails the review
    gate; a signed record is structurally valid and passes it. Neither state may record surface
    text, corpus bytes, book content or operator paths — the strict validator only accepts hashes,
    sizes, editions, versification ids, counts and book codes.
    """
    expected = _load_expected()
    _validate_expected(expected)
    if expected["status"] == "unsigned":
        with pytest.raises(pytest.fail.Exception) as excinfo:
            _reviewed_gate(expected)
        assert "is unsigned" in str(excinfo.value)
    else:
        _reviewed_gate(expected)


@REALDATA
def test_manifest_gate_authorizes_both_packages_independently() -> None:
    """Both manifests pass the policy-before-work gate on their own, before any pipeline work.

    Also pins the versification contract: both packages must declare the same edition, because
    M3 has no automatic versification mapping (ADR-0011 §3).
    """
    _mzr_dir, _mzr_path, _por_dir, _por_path, mzr, por = _require_pair()
    versification = _declared_versification(mzr, "mzr")
    if _declared_versification(por, "por") != versification:
        _safe_fail("the mzr and por manifests declare different versification ids", pytrace=False)
    assert mzr.languages and por.languages
    assert mzr.languages[0] != por.languages[0]


# ---------------------------------------------------------------------------------------------
# Mandatory real-data tests
# ---------------------------------------------------------------------------------------------


def _usfm_objects(ctx: AppContext, source_id: str) -> list[tuple[Any, str, bytes]]:
    """Registered USFM objects with book codes, rejecting duplicate book codes.

    USFM parsing only: timing and other media objects stay registered and preserved, but they
    are never parsed as USFM and never contribute book codes. Book code uniqueness over USFM
    objects is a parsing concern and is separate from package immutability, which is verified
    over *every* registered object by ``_registered_inventory`` (senior review item 3).
    """
    result: list[tuple[Any, str, bytes]] = []
    owners: dict[str, str] = {}
    for source_object in ctx.repo.list_source_objects(source_id):
        if source_object.media_type != SE_MEDIA_USFM:
            continue  # timing objects are preserved and hash-checked but never parsed as USFM
        data = ctx.raw_store.read_bytes(source_object.sha256)
        code = _book_code(data)
        if code is None:
            _safe_fail("a registered USFM object has no \\id book code", pytrace=False)
        if code in owners:
            # The book code itself is package-derived metadata, so only internal object ids and
            # a count are rendered (senior review item 2).
            _safe_fail(
                f"two registered USFM objects of this package carry the same book code "
                f"(second object {source_object.id})",
                pytrace=False,
            )
        owners[code] = source_object.id
        result.append((source_object, code, data))
    return result


def _registered_inventory(ctx: AppContext, source_id: str) -> dict[str, str]:
    """``{sha256: size_bytes}`` over **every** registered object of one source.

    Package immutability is verified per registered object, whatever its media type: the stored
    bytes must hash to the registered digest, the origin file must hash to the same digest, and
    the registered size must equal the observed length. Timing objects and any future media type
    are therefore included in the signed hash-to-integer-size inventory (senior review item 3).
    """
    inventory: dict[str, str] = {}
    for source_object in ctx.repo.list_source_objects(source_id):
        data = ctx.raw_store.read_bytes(source_object.sha256)
        if hashlib.sha256(data).hexdigest() != source_object.sha256:
            _safe_fail(
                f"stored bytes of object {source_object.id} do not hash to its registered sha256",
                pytrace=False,
            )
        origin = _origin_path(source_object.origin_uri)
        origin_bytes = origin.read_bytes()
        if hashlib.sha256(origin_bytes).hexdigest() != source_object.sha256:
            _safe_fail(
                f"origin file of object {source_object.id} does not hash to its registered sha256",
                pytrace=False,
            )
        if len(data) != source_object.size_bytes or len(origin_bytes) != source_object.size_bytes:
            _safe_fail(
                f"object {source_object.id} byte length differs from its registered size",
                pytrace=False,
            )
        inventory[source_object.sha256] = str(len(data))
    if not inventory:
        _safe_fail("no registered objects were found for one package", pytrace=False)
    return inventory


def _timing_package_source(ctx: AppContext, tmp_path: Path, key: str) -> Any:
    """One registered source carrying a USFM book, a timing object and a third object.

    The package is built with the production ScriptureEarth manifest builder
    (``build_manifest(scan_package(...))``, ``include_timing=True``) so the registered objects,
    their media types and their origin URIs are exactly the ones the real pipeline registers.
    """
    package = tmp_path / f"timing-{key}"
    usfm = package / "usfm"
    timing = package / "timing"
    usfm.mkdir(parents=True)
    timing.mkdir(parents=True)
    (usfm / "TST.usfm").write_bytes(b"\\id TST\n\\c 1\n\\v 1 alpha\n")
    (timing / "C01-TST.timing.txt").write_bytes(b"00:00:01.000\t00:00:02.000\t1:1\n")
    (package / "README.txt").write_bytes(b"synthetic package note, no corpus content\n")
    manifest = build_manifest(
        scan_package(package),
        key=f"synthetic-timing-{key}",
        language="mzr",
        policy=PolicySpec(
            mode=PolicyMode.DISTILL_ONLY,
            access_class=AccessClass.COMMUNITY,
            authority="Synthetic Timing Authority",
            allow=[Operation.ALIGN],
            restrictions={"versification_id": "synthetic-vrs-1"},
        ),
        provenance=Provenance(
            acquired_from="https://www.scriptureearth.org/00por.php?iso=zzz",
            rights_holder="Synthetic Timing Rights Holder",
            notes=_GOOD_PERMISSION_NOTE,
        ),
        acquired_at=datetime(2026, 1, 1, tzinfo=UTC),
        include_timing=True,
    )
    manifest_path = write_manifest(package, manifest.model_dump(mode="json"), "manifest.yaml")
    registration = register_source(ctx, manifest_path)
    ingest_source(ctx, registration.source.id)
    return registration


def test_package_inventory_covers_every_registered_object(tmp_path: Path) -> None:
    """A timing object is inside the signed inventory, not only USFM books (senior item 3)."""
    ctx = _memory_context(tmp_path)
    registration = _timing_package_source(ctx, tmp_path, "inventory")
    media_types = {
        source_object.media_type
        for source_object in ctx.repo.list_source_objects(registration.source.id)
    }
    assert SE_MEDIA_TIMING in media_types, media_types
    assert SE_MEDIA_USFM in media_types, media_types
    inventory = _registered_inventory(ctx, registration.source.id)
    objects = ctx.repo.list_source_objects(registration.source.id)
    assert len(inventory) == len(objects)
    assert set(inventory) == {source_object.sha256 for source_object in objects}


def test_timing_object_origin_mutation_fails_content_free(tmp_path: Path) -> None:
    """Mutating any non-USFM object's origin bytes fails with a content-free diagnostic.

    Compiler-free regression for the senior's item-3 reproduction: the package inventory is
    verified per registered object, so the mutation is detected whatever its media type and the
    diagnostic carries only the internal object id, never file, byte or path content.
    """
    ctx = _memory_context(tmp_path)
    registration = _timing_package_source(ctx, tmp_path, "mutation")
    source_objects = ctx.repo.list_source_objects(registration.source.id)
    timing = [
        source_object
        for source_object in source_objects
        if source_object.media_type == SE_MEDIA_TIMING
    ]
    assert timing, "the synthetic package must register a timing object"
    origin = _origin_path(timing[0].origin_uri)
    digest_before = hashlib.sha256(origin.read_bytes()).hexdigest()
    origin.write_bytes(origin.read_bytes() + b"mutated")

    with pytest.raises(pytest.fail.Exception) as excinfo:
        _registered_inventory(ctx, registration.source.id)
    message = str(excinfo.value)
    assert message.startswith(SAFE_DIAGNOSTIC_PREFIX)
    # Only the internal object id is rendered: the origin path, the file name, the mutated bytes
    # and their length appear nowhere, so the diagnostic names no content.
    assert timing[0].id in message
    for forbidden in (str(origin), origin.name, "mutated", "timing", timing[0].sha256):
        assert forbidden not in message
    assert hashlib.sha256(origin.read_bytes()).hexdigest() != digest_before


@REALDATA
def test_pair_hashes_unchanged(
    paired_corpus: PairedCorpus, caplog: pytest.LogCaptureFixture
) -> None:
    """Every registered object of both packages keeps its stored and origin bytes, and the
    committed inventories match the packages as reviewed and signed.

    The inventory covers every registered ``SourceObject`` of the side — USFM books and timing
    objects alike — and the USFM parsing checks (``\\id`` book code, duplicate rejection) are
    stated separately, so a mutated timing file can never hide behind a USFM-only inventory.
    """
    ctx = paired_corpus.ctx
    expected = paired_corpus.expected
    for flow, side in ((paired_corpus.source, "source_mzr"), (paired_corpus.target, "source_por")):
        # USFM parsing/duplicate-book checks: every parsed book is a distinct registered object.
        for _source_object, code, _data in _usfm_objects(ctx, flow.source_id):
            assert code
        inventory = _registered_inventory(ctx, flow.source_id)
        recorded = expected[side]["package_sha256_inventory"]
        # Sizes are compared as integers: JSON carries integers, the live inventory strings.
        normalized = {digest: int(size) for digest, size in recorded.items()}
        observed = {digest: int(size) for digest, size in inventory.items()}
        if observed != normalized:
            differing = sorted(set(observed) ^ set(normalized))[:4]
            _safe_fail(
                f"{side} hash inventory differs from the signed expectation for "
                f"{len(differing)} object keys",
                pytrace=False,
            )
        if expected[side]["versification"] != paired_corpus.versification_id:
            _safe_fail(f"{side} versification differs from the signed expectation", pytrace=False)
    records = _caplog_records(caplog)
    _assert_no_surfaces(records, _forbidden_surfaces(paired_corpus), "captured logs")


def _caplog_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Setup-phase and call-phase captured messages (pytest resets caplog.text per phase)."""
    records = caplog.get_records("setup") + caplog.get_records("call")
    return [record.getMessage() for record in records]


@REALDATA
def test_common_coordinate_components_independent_rescan(paired_corpus: PairedCorpus) -> None:
    """Stage 4 groups equal the independent rescan oracle's connected components."""
    corpus = paired_corpus
    _reviewed_gate(corpus.expected)
    oracle = PairOracle.of(
        corpus.segments(corpus.source_language), corpus.segments(corpus.target_language)
    )

    alignments = corpus.ctx.repo.list_segment_alignments_for_run(corpus.segment_alignment_run_id)
    if not alignments:
        _safe_fail("no segment alignment groups were produced", pytrace=False)
    if len(alignments) != oracle.group_count:
        _safe_fail(
            f"observed {len(alignments)} groups, independent rescan found {oracle.group_count}",
            pytrace=False,
        )
    structural = [group for group in alignments if group.status is STRUCTURAL]
    if len(structural) != len(oracle.structural_components()):
        _safe_fail("structural group count differs from the independent rescan", pytrace=False)
    if len(alignments) - len(structural) != len(oracle.partial_components()):
        _safe_fail(
            "partial-coverage group count differs from the independent rescan", pytrace=False
        )

    expected_groups = {
        (tuple(sorted(left)), tuple(sorted(right))) for left, right in oracle.components
    }
    observed_groups = {
        (tuple(sorted(group.source_segment_ids)), tuple(sorted(group.target_segment_ids)))
        for group in alignments
    }
    if observed_groups != expected_groups:
        _safe_fail(
            "observed groups differ from the independent rescan: "
            f"{len(observed_groups ^ expected_groups)} differing groups",
            pytrace=False,
        )

    expected_counts = corpus.expected["expected_counts"]
    if expected_counts["common_groups"] != oracle.group_count:
        _safe_fail(
            f"signed common_groups={expected_counts['common_groups']} but independent rescan "
            f"found {oracle.group_count}",
            pytrace=False,
        )
    # Signed unmatched counts are all-unit (verse plus non-verse) entries of the report; the
    # oracle is verse-only, so the difference is exactly the side's non-verse unit count.
    for side, oracle_count in (
        ("unmatched_source", oracle.unmatched_source),
        ("unmatched_target", oracle.unmatched_target),
    ):
        non_verse = len(
            _non_verse_ids(
                corpus,
                corpus.source_language if side == "unmatched_source" else corpus.target_language,
            )
        )
        if expected_counts[side] != oracle_count + non_verse:
            _safe_fail(
                f"signed {side}={expected_counts[side]} but the independent verse-only rescan "
                f"plus the side's non-verse units gives {oracle_count + non_verse}",
                pytrace=False,
            )
    if expected_counts["book_inventory"] != oracle.book_inventory:
        _safe_fail("signed book_inventory differs from the independent rescan", pytrace=False)


@REALDATA
def test_absent_coordinates_reported(paired_corpus: PairedCorpus) -> None:
    """Verses present on only one side are reported unmatched, never as empty-sided groups.

    Verse-only expectations come from the independent oracle; the report's non-verse
    unmatched ids are checked independently and never mixed into the verse comparison,
    because the canonical report also lists headings, titles, notes and front matter
    (ADR-0011 §3). The complete selected input is partitioned into matched and unmatched.
    """
    corpus = paired_corpus
    _reviewed_gate(corpus.expected)
    oracle = PairOracle.of(
        corpus.segments(corpus.source_language), corpus.segments(corpus.target_language)
    )
    alignments = corpus.ctx.repo.list_segment_alignments_for_run(corpus.segment_alignment_run_id)
    for group in alignments:
        if not group.source_segment_ids or not group.target_segment_ids:
            _safe_fail(f"group {group.id} was published with an empty side", pytrace=False)

    payload = _report_of(corpus, corpus.segment_alignment_run_id, "alignment_file")
    expected_counts = corpus.expected["expected_counts"]
    # The signed all-unit counts equal the oracle's verse-only counts plus the non-verse units.
    oracle_unmatched_source = oracle.unmatched_source + len(
        _non_verse_ids(corpus, corpus.source_language)
    )
    oracle_unmatched_target = oracle.unmatched_target + len(
        _non_verse_ids(corpus, corpus.target_language)
    )
    if len(payload["unmatched_source"]) != oracle_unmatched_source:
        _safe_fail(
            "the report's all-unit unmatched source count differs from the oracle's verse "
            "unmatched count plus the side's non-verse unit count",
            pytrace=False,
        )
    if len(payload["unmatched_target"]) != oracle_unmatched_target:
        _safe_fail(
            "the report's all-unit unmatched target count differs from the oracle's verse "
            "unmatched count plus the side's non-verse unit count",
            pytrace=False,
        )
    if expected_counts["unmatched_source"] != len(payload["unmatched_source"]):
        _safe_fail(
            f"signed unmatched_source={expected_counts['unmatched_source']} but the report "
            f"lists {len(payload['unmatched_source'])} all-unit unmatched entries",
            pytrace=False,
        )
    if expected_counts["unmatched_target"] != len(payload["unmatched_target"]):
        _safe_fail(
            f"signed unmatched_target={expected_counts['unmatched_target']} but the report "
            f"lists {len(payload['unmatched_target'])} all-unit unmatched entries",
            pytrace=False,
        )
    _assert_unmatched_agrees(corpus, oracle)
    reasons = {
        entry["reason"] for entry in payload["unmatched_source"] + payload["unmatched_target"]
    }
    unknown = reasons - UNMATCHED_REASONS
    if unknown:
        _safe_fail(
            f"{len(unknown)} unmatched reason codes are outside the documented set", pytrace=False
        )


@REALDATA
def test_native_edges_map_to_selected_occurrences(aligned_pair: PairedCorpus) -> None:
    """The native batch covers every eligible group and maps only to selected occurrences.

    Asserts structure — every endpoint inside its group's sides, in the pinned tokenization
    runs, and the batch equal to the complete eligible set of the Stage 4 run — never a fixed
    link matrix or a word-accuracy claim.
    """
    corpus = aligned_pair
    _reviewed_gate(corpus.expected)
    eligible, skipped = _eligible_groups(corpus)
    skipped_ids = {group.id for group in skipped}
    if not eligible:
        _safe_fail("the reviewed pair produced no eligible native groups", pytrace=False)

    alignments = {
        group.id: group
        for group in corpus.ctx.repo.list_segment_alignments_for_run(
            corpus.segment_alignment_run_id
        )
    }
    report = _report_of(corpus, corpus.token_alignment_run_id, "alignment_file")
    # The batch is exactly the eligible set, compared as sets of ids (the report's group
    # entries and the alignment rows are different containers for the same populations).
    batched = {
        str(group["alignment_id"])
        for group in report["groups"]
        if group.get("reason") != "empty_token_side"
    }
    if {group.id for group in eligible} != batched:
        _safe_fail(
            f"native batch covers {len(batched)} groups, the run has {len(eligible)} "
            "eligible groups",
            pytrace=False,
        )
    reported_skipped = {
        str(group["alignment_id"])
        for group in report["groups"]
        if group.get("reason") == "empty_token_side"
    }
    if reported_skipped != skipped_ids:
        _safe_fail(
            "the report's empty-token-side groups differ from the run's eligible status "
            "computation",
            pytrace=False,
        )

    # Backend identity and options are recorded, never guessed: the pinned upstream
    # distribution, the archive digest, the adapters' options and no seed support.
    backend = report["backend"]
    if backend["version"] != "2.0.0":
        _safe_fail("the native report names an unexpected upstream version", pytrace=False)
    if backend["archive_sha256"] != _NATIVE_ARCHIVE_SHA256:
        _safe_fail("the native report names an unexpected upstream archive digest", pytrace=False)
    if backend["seed_supported"] is not False:
        _safe_fail("the native report claims seed support", pytrace=False)
    if set(backend["options"]) - _NATIVE_OPTIONS:
        _safe_fail("the native report carries options outside the documented set", pytrace=False)
    if backend["options"].get("randomness") != "stochastic_unseeded":
        _safe_fail("the native report does not record unseeded sampling", pytrace=False)
    if backend["options"].get("scores") != "score_unavailable":
        _safe_fail("the native report does not record the missing per-link scores", pytrace=False)
    if backend["options"].get("model") != corpus.config.model:
        _safe_fail("the native report does not record the requested model", pytrace=False)
    if backend["options"].get("threads") != corpus.config.threads:
        _safe_fail("the native report does not record the requested thread count", pytrace=False)
    if report["totals"]["groups"] != len(report["groups"]):
        _safe_fail("the native report totals disagree with its group list", pytrace=False)

    edges = corpus.ctx.repo.list_token_alignment_edges_for_run(corpus.token_alignment_run_id)
    eligible_ids = {group.id for group in eligible}
    for edge in edges:
        if edge.segment_alignment_id not in eligible_ids:
            _safe_fail("an edge was produced for a group outside the eligible set", pytrace=False)
        group = alignments[edge.segment_alignment_id]
        source_tokens = {item.id for item in _flat_tokens(corpus.ctx, corpus, group, "source")}
        target_tokens = {item.id for item in _flat_tokens(corpus.ctx, corpus, group, "target")}
        if edge.source_token_id not in source_tokens:
            _safe_fail("an edge source token is outside its group's source side", pytrace=False)
        if edge.target_token_id not in target_tokens:
            _safe_fail("an edge target token is outside its group's target side", pytrace=False)
        if edge.direction is AlignmentDirection.SYMMETRIZED:
            continue
        if edge.score is not None:
            _safe_fail("the native adapter reported a per-link score", pytrace=False)


@REALDATA
def test_ancestry_reaches_both_sources(aligned_pair: PairedCorpus) -> None:
    """Every group, edge and both reports carry exactly the two package sources as ancestry.

    Each token edge derives from both endpoint tokens and its ``SegmentAlignment``; the Stage 5
    report reaches the same inputs as the Stage 4 report. An empty link set keeps the lineage.
    """
    corpus = aligned_pair
    _reviewed_gate(corpus.expected)
    expected_sources = {corpus.source.source_id, corpus.target.source_id}
    segment_alignments = corpus.ctx.repo.list_segment_alignments_for_run(
        corpus.segment_alignment_run_id
    )
    alignments_by_id = {group.id: group for group in segment_alignments}
    if not segment_alignments:
        _safe_fail("no segment alignment groups were produced", pytrace=False)
    for group in segment_alignments:
        parents = _lineage_parents(corpus.ctx, group.id, LineageKind.DERIVED_FROM)
        if parents != set((*group.source_segment_ids, *group.target_segment_ids)):
            _safe_fail(f"group {group.id} does not derive from exactly its members", pytrace=False)
        if set(ancestor_source_ids(corpus.ctx.repo, group.id)) != expected_sources:
            _safe_fail(f"group {group.id} does not reach both package sources", pytrace=False)

    edges = corpus.ctx.repo.list_token_alignment_edges_for_run(corpus.token_alignment_run_id)
    for edge in edges:
        group = alignments_by_id[edge.segment_alignment_id]
        parents = _lineage_parents(corpus.ctx, edge.id, LineageKind.DERIVED_FROM)
        expected = {
            edge.segment_alignment_id,
            edge.source_token_id,
            edge.target_token_id,
        }
        if parents != expected:
            _safe_fail(
                f"edge {edge.id} does not derive from exactly its group and both endpoints",
                pytrace=False,
            )
        source_tokens = _flat_tokens(corpus.ctx, corpus, group, "source")
        target_tokens = _flat_tokens(corpus.ctx, corpus, group, "target")
        if edge.source_token_id not in {item.id for item in source_tokens}:
            _safe_fail(
                f"edge {edge.id} derives from a source token outside its group", pytrace=False
            )
        if edge.target_token_id not in {item.id for item in target_tokens}:
            _safe_fail(
                f"edge {edge.id} derives from a target token outside its group", pytrace=False
            )
        if set(ancestor_source_ids(corpus.ctx.repo, edge.id)) != expected_sources:
            _safe_fail(f"edge {edge.id} does not reach both package sources", pytrace=False)

    for run_id in (corpus.segment_alignment_run_id, corpus.token_alignment_run_id):
        report = _report_of(corpus, run_id, "alignment_file")
        if not isinstance(report["groups"], list):
            _safe_fail("the alignment report carries no group list", pytrace=False)
        # Run ancestry is recorded as run I/O, not lineage edges (ADR-0011 §7): the run's
        # inputs must include both package sources on both stages.
        run_inputs = {
            object_id
            for object_id, role in corpus.ctx.repo.list_run_io(run_id)
            if role is RunIoRole.INPUT
        }
        run_sources = {
            object_id
            for object_id in run_inputs
            if corpus.ctx.repo.entity_type_of(object_id) is EntityType.SOURCE
        }
        if run_sources != expected_sources:
            _safe_fail("the alignment run does not record both package sources", pytrace=False)
        report_ids = {
            object_id
            for object_id, role in corpus.ctx.repo.list_run_io(run_id)
            if role is RunIoRole.OUTPUT
            and corpus.ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT
        }
        if len(report_ids) != 1:
            _safe_fail("the alignment run published more than one report artifact", pytrace=False)
        report_id = next(iter(report_ids))
        report_sources = set(ancestor_source_ids(corpus.ctx.repo, report_id))
        if report_sources != expected_sources:
            _safe_fail("the alignment report does not reach both package sources", pytrace=False)


@REALDATA
def test_pair_distill_only_egress_denied_and_training_allowed(aligned_pair: PairedCorpus) -> None:
    """Both packages are distill_only: alignment evidence trains (ADR-0025) but cannot egress.

    Runs the native Stage 5 batch first, so token edges and the token report are produced and
    are checked too: an alignment cannot open an operation that every ancestor keeps closed.
    """
    corpus = aligned_pair
    _reviewed_gate(corpus.expected)
    outputs: list[Any] = list(
        corpus.ctx.repo.list_segment_alignments_for_run(corpus.segment_alignment_run_id)
    )
    outputs.extend(
        corpus.ctx.repo.list_token_alignment_edges_for_run(corpus.token_alignment_run_id)
    )
    if not outputs:
        _safe_fail("no alignment outputs were produced for the pair", pytrace=False)
    report_ids = {
        object_id
        for object_id, role in corpus.ctx.repo.list_run_io(corpus.token_alignment_run_id)
        if role is RunIoRole.OUTPUT
        and corpus.ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT
    }
    outputs.extend(corpus.ctx.repo.get_artifact(report_id) for report_id in report_ids)
    for value in outputs:
        for operation in _OUTWARD_DENIED:
            if effective_decision(corpus.ctx.repo, value.id, operation) is not PolicyDecision.DENY:
                _safe_fail(
                    f"{operation.value} resolved a non-deny decision for an alignment output",
                    pytrace=False,
                )
        if effective_decision(corpus.ctx.repo, value.id, Operation.DIRECT_TRAINING) is not (
            PolicyDecision.ALLOW
        ):
            _safe_fail("alignment evidence is not trainable under ADR-0025", pytrace=False)


@REALDATA
def test_native_failure_keeps_segment_evidence(paired_corpus: PairedCorpus) -> None:
    """A failing native token run rolls its own rows back and leaves Stage 4 groups intact.

    The production ``eflomal@0.1.0`` adapter exposes no seed control (ADR-0011 §6), so a pinned
    seed is a deterministic adapter-side failure inside the real native path — not a mock. The
    failed run is the new ``TOKEN_ALIGNMENT`` run: it fails closed, keeps no edges, publishes no
    report artifact, and leaves the Stage 4 segments, groups and reports exactly as they were.
    """
    corpus = paired_corpus
    _reviewed_gate(corpus.expected)
    alignments = corpus.ctx.repo.list_segment_alignments_for_run(corpus.segment_alignment_run_id)
    if not alignments:
        _safe_fail("no segment alignment groups were produced", pytrace=False)
    successful_runs_before = {
        run.id
        for run in corpus.ctx.repo.list_runs_with_input(
            corpus.segment_alignment_run_id, RunStage.TOKEN_ALIGNMENT, RunStatus.SUCCEEDED
        )
    }
    edges_before = {
        run_id: len(corpus.ctx.repo.list_token_alignment_edges_for_run(run_id))
        for run_id in successful_runs_before
    }
    failed_runs_before = corpus.ctx.repo.count_runs(RunStatus.FAILED)

    # A failed run carries no run I/O, so it cannot be found through run listing: the
    # service's own recorder call is the only witness of its identity. Capturing that call
    # is the existing service-test convention (tests/service/test_token_alignment_service.py).
    service = TokenAlignmentService(corpus.ctx)
    failed_ids: list[str] = []
    original_fail = service.recorder.fail

    def capture_failure(run_id: str, error: BaseException, *args: Any, **kwargs: Any) -> Any:
        failed_ids.append(run_id)
        return original_fail(run_id, error, *args, **kwargs)

    service.recorder.fail = capture_failure  # type: ignore[method-assign]
    try:
        service.align(
            corpus.segment_alignment_run_id,
            source_tokenization_run_id=corpus.source.tokenization_run_id,
            target_tokenization_run_id=corpus.target.tokenization_run_id,
            method="eflomal@0.1.0",
            config=AlignmentConfig(
                namespace=SCRIPTURE_NAMESPACE,
                versification_id=corpus.versification_id,
                random_seed=11,
            ),
        )
    except AlignmentFailed as exc:
        # The induced failure is the adapter's fixed unsupported-seed code, never an
        # interpreted message: ``str(exc)`` renders the text, the code is ``exc.code``.
        if exc.code != _NATIVE_SEED_CODE:
            _safe_fail(
                "the pinned-seed native alignment failed with an unexpected fixed code",
                pytrace=False,
            )
    else:
        _safe_fail(
            "the native adapter accepted a pinned seed; eflomal exposes no seed control",
            pytrace=False,
        )
    finally:
        service.recorder.fail = original_fail  # type: ignore[method-assign]

    if corpus.ctx.repo.count_runs(RunStatus.FAILED) != failed_runs_before + 1:
        _safe_fail(
            "the failed native request recorded an unexpected number of failed runs", pytrace=False
        )
    if len(failed_ids) != 1:
        _safe_fail(f"the native service reported {len(failed_ids)} failing runs", pytrace=False)
    failed_run_id = failed_ids[0]
    failed_run = corpus.ctx.repo.get_run(failed_run_id)
    if failed_run.status is not RunStatus.FAILED:
        _safe_fail("the failed token alignment run was not recorded as failed", pytrace=False)
    if failed_run.stage is not RunStage.TOKEN_ALIGNMENT:
        _safe_fail("the failing run was recorded under a different stage", pytrace=False)
    if failed_run.error_type != "AlignmentFailed":
        _safe_fail("the failed run recorded an unexpected error type", pytrace=False)
    if failed_run.error_message is not None:
        _safe_fail("the failed run stored a raw error message", pytrace=False)
    if corpus.ctx.repo.list_token_alignment_edges_for_run(failed_run_id):
        _safe_fail("the failed token run persisted token edges", pytrace=False)
    published = [
        object_id
        for object_id, role in corpus.ctx.repo.list_run_io(failed_run_id)
        if role is RunIoRole.OUTPUT
    ]
    if published:
        _safe_fail("the failed token run published output rows", pytrace=False)

    # The Stage 4 evidence and its run survive the Stage 5 failure untouched, and earlier
    # successful token runs keep exactly their edges.
    if (
        corpus.ctx.repo.list_segment_alignments_for_run(corpus.segment_alignment_run_id)
        != alignments
    ):
        _safe_fail("a failed token run modified the segment alignment evidence", pytrace=False)
    if corpus.ctx.repo.get_run(corpus.segment_alignment_run_id).status is not RunStatus.SUCCEEDED:
        _safe_fail("a failed token run changed the segment alignment run status", pytrace=False)
    for previous_run, edge_count in edges_before.items():
        if len(corpus.ctx.repo.list_token_alignment_edges_for_run(previous_run)) != edge_count:
            _safe_fail("a failed token run changed the edges of a succeeded run", pytrace=False)


@REALDATA
def test_rerun_reuses_both_alignment_runs(aligned_pair: PairedCorpus) -> None:
    """An identical Stage 4 and Stage 5 rerun reuses both runs and publishes no extra rows."""
    corpus = aligned_pair
    _reviewed_gate(corpus.expected)
    token_run_id = corpus.token_alignment_run_id
    edges_before = corpus.ctx.repo.list_token_alignment_edges_for_run(token_run_id)

    segment = SegmentAlignmentService(corpus.ctx).align(
        corpus.side(corpus.source_language),
        corpus.side(corpus.target_language),
        config=corpus.config,
    )
    if not segment.reused:
        _safe_fail("an identical segment alignment request was not reused", pytrace=False)
    token = _stage5(corpus)
    if not token.reused:
        _safe_fail("an identical token alignment request was not reused", pytrace=False)
    if token.run.id != token_run_id:
        _safe_fail("a reused token alignment request produced a new run", pytrace=False)
    alignments = corpus.ctx.repo.list_segment_alignments_for_run(corpus.segment_alignment_run_id)
    if len(alignments) != len(set(group.group_key for group in alignments)):
        _safe_fail("duplicate segment alignment groups were published", pytrace=False)
    if corpus.ctx.repo.list_token_alignment_edges_for_run(token_run_id) != edges_before:
        _safe_fail("a reused token alignment request persisted additional edges", pytrace=False)


@REALDATA
def test_no_surface_leaks(aligned_pair: PairedCorpus, caplog: pytest.LogCaptureFixture) -> None:
    """No surface text, book path or native process output reaches setup logs or either report.

    The Stage 5 native run happens in the fixture setup, so the setup-phase caplog records
    cover the pipeline *and* the native invocation. The single focused helper checks the
    forbidden surfaces and every book-path form of both packages against the actual log records
    and against both serialized reports (Stage 4 and Stage 5) — never against a filename list.
    """
    corpus = aligned_pair
    _assert_no_leaks(
        corpus,
        caplog,
        run_ids=(corpus.segment_alignment_run_id, corpus.token_alignment_run_id),
    )


@REALDATA
def test_parallel_postgres_persistence(pg_repository: Any, tmp_path: Path) -> None:
    """One governed pair persists the full pipeline, including native Stage 5, on PostgreSQL.

    Builds exactly one PostgreSQL pair — registration, ingestion, extraction, normalization,
    tokenization, segment alignment, native token alignment (``eflomal@0.1.0``) and the stored
    report — then verifies persisted token endpoints pinned to the selected tokenization runs,
    directional and symmetrized edge metadata, report access and lineage, policy denials and
    rerun reuse. The memory pipeline is not built here: the memory case is a separate test.
    """
    _reviewed_gate(_load_expected())
    (
        _mzr_dir,
        mzr_manifest_path,
        _por_dir,
        por_manifest_path,
        mzr,
        por,
    ) = _require_pair()
    versification, mzr_languages, por_languages = _pair_compatibility(mzr, por)
    ctx = AppContext(
        repo=pg_repository,
        raw_store=LocalContentStore(tmp_path / "raw"),
        artifact_store=LocalContentStore(tmp_path / "artifacts"),
        clock=_stepping_clock(),
        new_id=new_id,
        actor="realdata-actor",
        code_revision="realdata-rev",
    )
    corpus = PairedCorpus(
        ctx=ctx,
        expected=_load_expected(),
        source_language=mzr_languages[0],
        target_language=por_languages[0],
        versification_id=versification,
        flows=(
            _build_flow(ctx, mzr_manifest_path, mzr, mzr_languages[0], "mzr"),
            _build_flow(ctx, por_manifest_path, por, por_languages[0], "por"),
        ),
    )
    summary = SegmentAlignmentService(ctx).align(
        corpus.side(corpus.source_language),
        corpus.side(corpus.target_language),
        config=corpus.config,
    )
    corpus.segment_alignment_run_id = summary.run.id
    token = _stage5(corpus)
    corpus.token_alignment_run_id = token.run.id

    expected = corpus.expected["expected_counts"]
    alignments = ctx.repo.list_segment_alignments_for_run(summary.run.id)
    if not alignments:
        _safe_fail("no segment alignment groups were persisted on PostgreSQL", pytrace=False)
    if len(alignments) != expected["common_groups"]:
        _safe_fail(
            f"PostgreSQL persisted {len(alignments)} groups, signed expectation is "
            f"{expected['common_groups']}",
            pytrace=False,
        )
    report = _report_of(corpus, summary.run.id, "alignment_file")
    if len(report["groups"]) != expected["common_groups"]:
        _safe_fail("the PostgreSQL segment report lists an unexpected group count", pytrace=False)
    if len(report["unmatched_source"]) != expected["unmatched_source"]:
        _safe_fail(
            "the PostgreSQL segment report lists an unexpected unmatched source count",
            pytrace=False,
        )
    if len(report["unmatched_target"]) != expected["unmatched_target"]:
        _safe_fail(
            "the PostgreSQL segment report lists an unexpected unmatched target count",
            pytrace=False,
        )
    expected_sources = {corpus.source.source_id, corpus.target.source_id}
    for group in alignments:
        parents = _lineage_parents(ctx, group.id, LineageKind.DERIVED_FROM)
        if parents != set((*group.source_segment_ids, *group.target_segment_ids)):
            _safe_fail(
                "PostgreSQL persisted group members that do not match their lineage", pytrace=False
            )
        if set(ancestor_source_ids(ctx.repo, group.id)) != expected_sources:
            _safe_fail(
                "PostgreSQL group ancestry does not reach both package sources", pytrace=False
            )
    for value in alignments:
        for operation in _OUTWARD_DENIED:
            if effective_decision(ctx.repo, value.id, operation) is not PolicyDecision.DENY:
                _safe_fail(
                    f"{operation.value} resolved a non-deny decision on PostgreSQL", pytrace=False
                )

    # --- Stage 5 persisted evidence -------------------------------------------------------
    edges = ctx.repo.list_token_alignment_edges_for_run(token.run.id)
    if not edges:
        _safe_fail("the native PostgreSQL run persisted no token edges", pytrace=False)
    alignments_by_id = {group.id: group for group in alignments}
    directions: set[Any] = set()
    for edge in edges:
        group = alignments_by_id[edge.segment_alignment_id]
        source_tokens = {item.id for item in _flat_tokens(ctx, corpus, group, "source")}
        target_tokens = {item.id for item in _flat_tokens(ctx, corpus, group, "target")}
        if edge.source_token_id not in source_tokens or edge.target_token_id not in target_tokens:
            _safe_fail(
                "a PostgreSQL token edge endpoint is outside its group's sides", pytrace=False
            )
        source_token = ctx.repo.get_token(edge.source_token_id)
        target_token = ctx.repo.get_token(edge.target_token_id)
        if source_token.run_id != corpus.source.tokenization_run_id:
            _safe_fail(
                "a PostgreSQL token edge source endpoint is not in the selected tokenization run",
                pytrace=False,
            )
        if target_token.run_id != corpus.target.tokenization_run_id:
            _safe_fail(
                "a PostgreSQL token edge target endpoint is not in the selected tokenization run",
                pytrace=False,
            )
        if edge.run_id != token.run.id:
            _safe_fail("a PostgreSQL token edge belongs to another run", pytrace=False)
        parents = _lineage_parents(ctx, edge.id, LineageKind.DERIVED_FROM)
        if parents != {edge.segment_alignment_id, edge.source_token_id, edge.target_token_id}:
            _safe_fail("a PostgreSQL token edge has unexpected lineage", pytrace=False)
        if set(ancestor_source_ids(ctx.repo, edge.id)) != expected_sources:
            _safe_fail("a PostgreSQL token edge does not reach both package sources", pytrace=False)
        if edge.direction in (AlignmentDirection.FORWARD, AlignmentDirection.REVERSE):
            if edge.symmetrization is not Symmetrization.NONE:
                _safe_fail("a directional edge carries a symmetrization value", pytrace=False)
        elif edge.symmetrization is not corpus.config.symmetrization:
            _safe_fail("a symmetrized edge carries an unexpected symmetrization", pytrace=False)
        if edge.score is not None:
            _safe_fail("the native adapter reported a per-link score on PostgreSQL", pytrace=False)
        for operation in _OUTWARD_DENIED:
            if effective_decision(ctx.repo, edge.id, operation) is not PolicyDecision.DENY:
                _safe_fail(
                    f"{operation.value} resolved a non-deny decision for a PostgreSQL edge",
                    pytrace=False,
                )
        directions.add(edge.direction)
    required_directions = {
        AlignmentDirection.FORWARD,
        AlignmentDirection.REVERSE,
        AlignmentDirection.SYMMETRIZED,
    }
    if not required_directions <= directions:
        _safe_fail("the PostgreSQL native run did not persist all three directions", pytrace=False)

    token_report = _report_of(corpus, token.run.id, "alignment_file")
    if token_report["method"] != "eflomal@0.1.0":
        _safe_fail("the PostgreSQL token report names an unexpected method", pytrace=False)
    if token_report["segment_run_id"] != summary.run.id:
        _safe_fail("the PostgreSQL token report does not pin the segment run", pytrace=False)
    if token_report["source_tokenization_run_id"] != corpus.source.tokenization_run_id:
        _safe_fail(
            "the PostgreSQL token report does not pin the source tokenization run", pytrace=False
        )
    if token_report["target_tokenization_run_id"] != corpus.target.tokenization_run_id:
        _safe_fail(
            "the PostgreSQL token report does not pin the target tokenization run", pytrace=False
        )
    report_ids = {
        object_id
        for object_id, role in ctx.repo.list_run_io(token.run.id)
        if role is RunIoRole.OUTPUT and ctx.repo.entity_type_of(object_id) is EntityType.ARTIFACT
    }
    if len(report_ids) != 1:
        _safe_fail("the PostgreSQL native run published more than one report", pytrace=False)
    report_id = next(iter(report_ids))
    artifact = ctx.repo.get_artifact(report_id)
    if artifact.run_id != token.run.id:
        _safe_fail("the PostgreSQL report artifact records a different creating run", pytrace=False)
    if set(ancestor_source_ids(ctx.repo, report_id)) != expected_sources:
        _safe_fail("the PostgreSQL token report does not reach both package sources", pytrace=False)
    for operation in _OUTWARD_DENIED:
        if effective_decision(ctx.repo, report_id, operation) is not PolicyDecision.DENY:
            _safe_fail(
                f"{operation.value} resolved a non-deny decision for the PostgreSQL report",
                pytrace=False,
            )

    # --- rerun reuse ----------------------------------------------------------------------
    reused_segment = SegmentAlignmentService(ctx).align(
        corpus.side(corpus.source_language),
        corpus.side(corpus.target_language),
        config=corpus.config,
    )
    if not reused_segment.reused or reused_segment.run.id != summary.run.id:
        _safe_fail(
            "an identical PostgreSQL segment alignment request was not reused", pytrace=False
        )
    reused_token = _stage5(corpus)
    if not reused_token.reused or reused_token.run.id != token.run.id:
        _safe_fail("an identical PostgreSQL token alignment request was not reused", pytrace=False)
    if ctx.repo.list_token_alignment_edges_for_run(token.run.id) != edges:
        _safe_fail("a reused PostgreSQL token alignment published additional edges", pytrace=False)
