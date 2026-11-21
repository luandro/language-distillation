from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from pydantic import TypeAdapter, ValidationError

from langpipe.domain.enums import (
    LineageKind,
    Operation,
    RunIoRole,
    RunStage,
    RunStatus,
    SegmentStatus,
    SpanRepresentation,
)
from langpipe.domain.errors import InvalidLineage, SchemaViolation
from langpipe.domain.ids import IdFactory, IdPrefix
from langpipe.domain.models.base import VERSIONED_NAME, DomainModel
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.observation import Form, Segment, Span, TokenOccurrence
from langpipe.governance import effective_policy
from langpipe.governance.guard import require
from langpipe.governance.policy import PolicyLike
from langpipe.storage.repository import Repository

_VERSIONED = TypeAdapter(VERSIONED_NAME)


@dataclass(frozen=True)
class SegmentInput:
    ordinal: int
    language: str
    locator: dict[str, str | int]
    raw_text: str


@dataclass(frozen=True)
class NormalizedSegmentInput:
    raw_segment_id: str
    normalized_text: str | None  # None ⇔ failed
    failed: bool


@dataclass(frozen=True)
class TokenInput:
    ordinal: int
    raw_surface: str
    raw_start: int | None
    raw_end: int | None
    form_text: str | None  # supplied NFC orthographic text; never generated here; None → no form
    normalized_surface: str | None = None
    norm_start: int | None = None
    norm_end: int | None = None


class ObservationRecorder:
    """Writes raw segments and tokens. The caller owns run start and finish."""

    def __init__(self, repo: Repository, clock: Callable[[], datetime], new_id: IdFactory) -> None:
        self._repo = repo
        self._clock = clock
        self._new_id = new_id
        self._in_unit_of_work = False

    @contextmanager
    def unit_of_work(self) -> Iterator[None]:
        """One repository transaction shared by every record_* call in the block."""
        if self._in_unit_of_work:
            raise RuntimeError("nested unit of work is not supported")
        with self._repo.transaction():
            self._in_unit_of_work = True
            try:
                yield
            finally:
                self._in_unit_of_work = False

    def record_segments(
        self,
        *,
        run_id: str,
        source_object_id: str,
        segments: Sequence[SegmentInput],
    ) -> list[Segment]:
        with self._write_scope():
            run = self._repo.get_run(run_id)
            _require_running(run.status, run.stage, RunStage.EXTRACTION)
            obj = self._repo.get_source_object(source_object_id)
            self._repo.lock_sources([obj.source_id])
            require(
                _policy_of(self._repo, obj.source_id),
                Operation.EXTRACT,
                source_id=obj.source_id,
            )
            _reject_duplicate_ordinals([item.ordinal for item in segments])

            now = self._clock()
            built = [
                _build(
                    Segment,
                    id=self._new_id(IdPrefix.SEGMENT),
                    source_id=obj.source_id,
                    source_object_id=obj.id,
                    run_id=run_id,
                    ordinal=item.ordinal,
                    language=item.language,
                    locator=item.locator,
                    raw_text=item.raw_text,
                    created_at=now,
                )
                for item in segments
            ]

            for segment in built:
                self._repo.add_segment(segment)
            self._repo.add_run_io(run_id, obj.id, RunIoRole.INPUT)
            for segment in built:
                self._repo.add_run_io(run_id, segment.id, RunIoRole.OUTPUT)
                self._repo.add_lineage_edge(
                    _edge(self._new_id, segment.id, obj.id, LineageKind.EXTRACTED_FROM, run_id, now)
                )
            return built

    def record_normalized_segments(
        self,
        *,
        run_id: str,
        normalization_profile: str,
        items: Sequence[NormalizedSegmentInput],
    ) -> list[Segment]:
        with self._write_scope():
            run = self._repo.get_run(run_id)
            _require_running(run.status, run.stage, RunStage.NORMALIZATION)
            _check_versioned(normalization_profile)
            raw_ids = [item.raw_segment_id for item in items]
            if len(set(raw_ids)) != len(raw_ids):
                raise SchemaViolation()
            raw_segments = [self._repo.get_segment(raw_id) for raw_id in raw_ids]
            for raw in raw_segments:
                if (
                    raw.status is not SegmentStatus.OK
                    or raw.normalization_profile is not None
                    or self._repo.get_run(raw.run_id).stage is not RunStage.EXTRACTION
                ):
                    raise InvalidLineage()
            # Policy before work under lock: NORMALIZE must be allowed for every input source.
            source_ids = sorted({raw.source_id for raw in raw_segments})
            self._repo.lock_sources(source_ids)
            for source_id in source_ids:
                require(_policy_of(self._repo, source_id), Operation.NORMALIZE, source_id=source_id)

            now = self._clock()
            built: list[Segment] = []
            for item, raw in zip(items, raw_segments, strict=True):
                if item.failed != (item.normalized_text is None):
                    raise SchemaViolation()
                if item.failed:
                    built.append(
                        _build(
                            Segment,
                            id=self._new_id(IdPrefix.SEGMENT),
                            source_id=raw.source_id,
                            source_object_id=raw.source_object_id,
                            run_id=run_id,
                            ordinal=raw.ordinal,
                            language=raw.language,
                            locator=raw.locator,
                            raw_text=raw.raw_text,
                            status=SegmentStatus.NORMALIZATION_FAILED,
                            created_at=now,
                        )
                    )
                else:
                    built.append(
                        _build(
                            Segment,
                            id=self._new_id(IdPrefix.SEGMENT),
                            source_id=raw.source_id,
                            source_object_id=raw.source_object_id,
                            run_id=run_id,
                            ordinal=raw.ordinal,
                            language=raw.language,
                            locator=raw.locator,
                            raw_text=raw.raw_text,
                            normalized_text=item.normalized_text,
                            normalization_profile=normalization_profile,
                            created_at=now,
                        )
                    )

            for raw, segment in zip(raw_segments, built, strict=True):
                self._repo.add_segment(segment)
                self._repo.add_run_io(run_id, raw.id, RunIoRole.INPUT)
                self._repo.add_run_io(run_id, segment.id, RunIoRole.OUTPUT)
                self._repo.add_lineage_edge(
                    _edge(
                        self._new_id,
                        segment.id,
                        raw.id,
                        LineageKind.NORMALIZED_FROM,
                        run_id,
                        now,
                    )
                )
            return built

    def record_tokens(
        self,
        *,
        run_id: str,
        segment_id: str,
        tokenizer: str,
        orthography_profile: str,
        tokens: Sequence[TokenInput],
    ) -> list[TokenOccurrence]:
        """M1-compatible path: accepts a raw or a normalized segment (ADR-0010 decision 5)."""
        return self._record_tokens(
            run_id=run_id,
            segment_id=segment_id,
            tokenizer=tokenizer,
            orthography_profile=orthography_profile,
            tokens=tokens,
            require_normalized=False,
        )

    def record_normalized_tokens(
        self,
        *,
        run_id: str,
        segment_id: str,
        tokenizer: str,
        orthography_profile: str,
        tokens: Sequence[TokenInput],
    ) -> list[TokenOccurrence]:
        """M2 strict path: only an OK normalized segment with a matching profile is tokenizable."""
        return self._record_tokens(
            run_id=run_id,
            segment_id=segment_id,
            tokenizer=tokenizer,
            orthography_profile=orthography_profile,
            tokens=tokens,
            require_normalized=True,
        )

    def _record_tokens(
        self,
        *,
        run_id: str,
        segment_id: str,
        tokenizer: str,
        orthography_profile: str,
        tokens: Sequence[TokenInput],
        require_normalized: bool,
    ) -> list[TokenOccurrence]:
        with self._write_scope():
            run = self._repo.get_run(run_id)
            _require_running(run.status, run.stage, RunStage.TOKENIZATION)
            segment = self._repo.get_segment(segment_id)
            is_normalized = (
                segment.normalization_profile is not None and segment.status is SegmentStatus.OK
            )
            if segment.status is SegmentStatus.NORMALIZATION_FAILED or (
                require_normalized and not is_normalized
            ):
                raise InvalidLineage()
            if is_normalized and orthography_profile != segment.normalization_profile:
                raise SchemaViolation()
            self._repo.lock_sources([segment.source_id])
            require(
                _policy_of(self._repo, segment.source_id),
                Operation.NORMALIZE,
                source_id=segment.source_id,
            )
            _reject_duplicate_ordinals([item.ordinal for item in tokens])
            _check_versioned(tokenizer)
            _check_versioned(orthography_profile)

            now = self._clock()
            built: list[TokenOccurrence] = []
            forms: dict[str, Form] = {}
            self._repo.add_run_io(run_id, segment.id, RunIoRole.INPUT)
            for item in tokens:
                if (
                    item.form_text is not None
                    and item.normalized_surface is not None
                    and item.form_text != item.normalized_surface
                ):
                    raise SchemaViolation()
                form_id = None
                if item.form_text is not None:
                    form = self._form_for(segment, item.form_text, orthography_profile, run_id, now)
                    forms[form.id] = form
                    form_id = form.id
                    self._repo.add_lineage_edge(
                        _edge(
                            self._new_id, form.id, segment.id, LineageKind.DERIVED_FROM, run_id, now
                        )
                    )
                token = _build(
                    TokenOccurrence,
                    id=self._new_id(IdPrefix.TOKEN),
                    segment_id=segment.id,
                    run_id=run_id,
                    ordinal=item.ordinal,
                    raw_surface=item.raw_surface,
                    normalized_surface=item.normalized_surface,
                    raw_span=_raw_span(item.raw_start, item.raw_end),
                    normalized_span=_normalized_span(item.norm_start, item.norm_end),
                    tokenizer=tokenizer,
                    form_id=form_id,
                    created_at=now,
                )
                token.check_against(segment)
                built.append(token)
                self._repo.add_token(token)
                self._repo.add_run_io(run_id, token.id, RunIoRole.OUTPUT)
                self._repo.add_lineage_edge(
                    _edge(self._new_id, token.id, segment.id, LineageKind.DERIVED_FROM, run_id, now)
                )
            for form_id in forms:
                self._repo.add_run_io(run_id, form_id, RunIoRole.OUTPUT)
            return built

    @contextmanager
    def _write_scope(self) -> Iterator[None]:
        """Join an open `unit_of_work` transaction, or open one for a standalone call."""
        if self._in_unit_of_work:
            yield
        else:
            with self._repo.transaction():
                yield

    def _form_for(
        self,
        segment: Segment,
        text: str,
        orthography_profile: str,
        run_id: str,
        now: datetime,
    ) -> Form:
        candidate = _build(
            Form,
            id=self._new_id(IdPrefix.FORM),
            language=segment.language,
            orthography_profile=orthography_profile,
            text=text,
            run_id=run_id,
            created_at=now,
        )
        # Returns the existing Form for the same (language, profile, text); never merges variants.
        return self._repo.get_or_create_form(candidate)


def _require_running(status: RunStatus, stage: RunStage, expected: RunStage) -> None:
    if status is not RunStatus.RUNNING or stage is not expected:
        raise InvalidLineage()


def _policy_of(repo: Repository, source_id: str) -> PolicyLike:
    return effective_policy(repo, source_id)


def _reject_duplicate_ordinals(ordinals: list[int]) -> None:
    if len(set(ordinals)) != len(ordinals):
        raise SchemaViolation()


def _check_versioned(value: str) -> None:
    try:
        _VERSIONED.validate_python(value)
    except ValidationError as exc:
        raise SchemaViolation() from exc


def _raw_span(start: int | None, end: int | None) -> Span | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise SchemaViolation()
    return _build(Span, representation=SpanRepresentation.RAW, start=start, end=end)


def _normalized_span(start: int | None, end: int | None) -> Span | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise SchemaViolation()
    return _build(Span, representation=SpanRepresentation.NORMALIZED, start=start, end=end)


def _build[M: DomainModel](model: type[M], **data: object) -> M:
    """Validate through the domain model; Pydantic errors never leak field values."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise SchemaViolation() from exc


def _edge(
    new_id: IdFactory,
    from_id: str,
    to_id: str,
    kind: LineageKind,
    run_id: str,
    now: datetime,
) -> LineageEdge:
    return LineageEdge(
        id=new_id(IdPrefix.LINEAGE),
        from_id=from_id,
        to_id=to_id,
        kind=kind,
        run_id=run_id,
        created_at=now,
    )
