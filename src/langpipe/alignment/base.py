"""Pure alignment DTOs and adapter protocols (M3-PLAN §5.2, ADR-0011).

These are in-memory contracts between selection, the aligners and the Stage 4/5
services. They never persist and never carry source text: index pairs, identifiers,
scores and fixed reason codes only.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from langpipe.domain.enums import AlignmentStatus, Symmetrization
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.text.registry import Versioned


@dataclass(frozen=True)
class AlignmentSide:
    """One pinned side of an alignment request (ADR-0011 §4)."""

    source_id: str
    language: str
    normalization_run_id: str
    tokenization_run_id: str | None = None  # None for Stage 4; Stage 5 pins a succeeded run


@dataclass(frozen=True)
class AlignmentConfig:
    """Adapter configuration shared by both stages. No text, paths or credentials."""

    namespace: str
    versification_id: str | None = None  # None for TSV coordinate namespaces
    symmetrization: Symmetrization = Symmetrization.INTERSECTION
    model: int = 3
    threads: int = 1
    timeout_seconds: float = 300.0
    random_seed: int | None = None  # None unless the native spike proves seed support

    def __post_init__(self) -> None:
        if not self.namespace:
            raise ValueError("namespace must be non-empty")
        if self.model < 1:
            raise ValueError("model must be a positive integer")
        if self.threads < 1:
            raise ValueError("threads must be a positive integer")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


@dataclass(frozen=True)
class SegmentGroup:
    """One n:m match over already persisted segments; evidence, never truth."""

    source_segments: tuple[Segment, ...]
    target_segments: tuple[Segment, ...]
    group_key: str  # canonical hash of ordered member IDs plus method/mode/namespace
    status: AlignmentStatus
    reason: str | None = None  # fixed diagnostic code; aligners never emit free text


@dataclass(frozen=True)
class SegmentMatchOutput:
    groups: tuple[SegmentGroup, ...]
    unmatched: tuple[tuple[str, str], ...]  # (segment_id, fixed reason code)


@dataclass(frozen=True)
class TokenGroup:
    """One alignment group's flattened occurrences in member order then token ordinal."""

    alignment_id: str
    source_tokens: tuple[TokenOccurrence, ...]
    target_tokens: tuple[TokenOccurrence, ...]


@dataclass(frozen=True)
class IndexLink:
    """One zero-based source-target index pair inside a TokenGroup."""

    source_index: int
    target_index: int
    score: float | None = None  # null when the backend emits hard links only
    raw_scores: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_index < 0 or self.target_index < 0:
            raise ValueError("link indices must be non-negative")


@dataclass(frozen=True)
class TokenLinks:
    """Directional link sets for one group; both use source-target index order."""

    alignment_id: str
    forward: tuple[IndexLink, ...]
    reverse: tuple[IndexLink, ...]


@dataclass(frozen=True)
class BackendMetadata:
    """Adapter/backend identity for a batch output; never carries text (ADR-0011 §6)."""

    version: str
    archive_sha256: str | None  # upstream distribution hash when known
    options: Mapping[str, str | int | float | bool | None]
    seed_supported: bool


@dataclass(frozen=True)
class TokenBatchOutput:
    groups: tuple[TokenLinks, ...]
    backend: BackendMetadata


class SegmentAligner(Versioned, Protocol):
    def align(
        self, source: Sequence[Segment], target: Sequence[Segment], config: AlignmentConfig
    ) -> SegmentMatchOutput: ...


class TokenAligner(Versioned, Protocol):
    def align(self, groups: Sequence[TokenGroup], config: AlignmentConfig) -> TokenBatchOutput: ...
