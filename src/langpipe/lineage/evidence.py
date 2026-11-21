from collections.abc import Callable, Sequence
from datetime import datetime

from pydantic import JsonValue, ValidationError

from langpipe.domain.enums import (
    EntityType,
    EvidenceKind,
    EvidencePolarity,
    LineageKind,
    Operation,
    RunIoRole,
    RunStage,
    RunStatus,
)
from langpipe.domain.errors import InvalidLineage, SchemaViolation
from langpipe.domain.ids import IdFactory, IdPrefix
from langpipe.domain.models.base import DomainModel
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.governance import effective_policy
from langpipe.governance.guard import require
from langpipe.governance.policy import PolicyLike
from langpipe.storage.repository import Repository


class EvidenceService:
    """Records evidence about governed objects. Evidence is never a validation (ADR-0007)."""

    def __init__(self, repo: Repository, clock: Callable[[], datetime], new_id: IdFactory) -> None:
        self._repo = repo
        self._clock = clock
        self._new_id = new_id

    def add_evidence(
        self,
        *,
        run_id: str,
        kind: EvidenceKind,
        polarity: EvidencePolarity,
        target_id: str,
        derived_from: Sequence[str],
        source_id: str | None = None,
        claim: dict[str, JsonValue] | None = None,
        strength: dict[str, float] | None = None,
        independence_group: str | None = None,
    ) -> EvidenceItem:
        with self._repo.transaction():
            return self._record(
                run_id=run_id,
                kind=kind,
                polarity=polarity,
                target_id=target_id,
                derived_from=derived_from,
                source_id=source_id,
                claim=claim,
                strength=strength,
                independence_group=independence_group,
                supersedes=None,
            )

    def supersede_evidence(
        self,
        *,
        run_id: str,
        old_id: str,
        kind: EvidenceKind,
        polarity: EvidencePolarity,
        target_id: str,
        derived_from: Sequence[str],
        source_id: str | None = None,
        claim: dict[str, JsonValue] | None = None,
        strength: dict[str, float] | None = None,
        independence_group: str | None = None,
    ) -> EvidenceItem:
        with self._repo.transaction():
            old = self._repo.get_evidence(old_id)
            if old.target_id != target_id:
                raise InvalidLineage()
            return self._record(
                run_id=run_id,
                kind=kind,
                polarity=polarity,
                target_id=target_id,
                derived_from=derived_from,
                source_id=source_id,
                claim=claim,
                strength=strength,
                independence_group=independence_group,
                supersedes=old.id,
            )

    def _record(
        self,
        *,
        run_id: str,
        kind: EvidenceKind,
        polarity: EvidencePolarity,
        target_id: str,
        derived_from: Sequence[str],
        source_id: str | None,
        claim: dict[str, JsonValue] | None,
        strength: dict[str, float] | None,
        independence_group: str | None,
        supersedes: str | None,
    ) -> EvidenceItem:
        # Must run inside the caller's transaction; every check precedes the first write.
        if not derived_from:
            raise InvalidLineage()
        if kind is not EvidenceKind.MANUAL_ANNOTATION:
            # M1 produces manual annotation evidence only; other kinds await their producers.
            raise SchemaViolation()
        run = self._repo.get_run(run_id)
        if run.status is not RunStatus.RUNNING or run.stage is not RunStage.MANUAL_ANNOTATION:
            raise InvalidLineage()

        # A superseded item is a lineage parent of its replacement, so its ancestry is governed too.
        governed_ids = [target_id, *derived_from]
        if supersedes is not None:
            governed_ids.append(supersedes)
        sources = self._governed_sources(governed_ids)
        if not sources or (source_id is not None and source_id not in sources):
            raise InvalidLineage()
        for governed in sorted(sources):
            require(self._policy_of(governed), Operation.HUMAN_REVIEW, source_id=governed)

        now = self._clock()
        item = _build(
            EvidenceItem,
            id=self._new_id(IdPrefix.EVIDENCE),
            kind=kind,
            polarity=polarity,
            target_id=target_id,
            claim=claim,
            source_id=source_id,
            run_id=run_id,
            strength=strength or {},
            independence_group=independence_group,
            created_at=now,
        )
        self._repo.add_evidence(item)
        for input_id in sorted(set(derived_from)):
            self._repo.add_run_io(run_id, input_id, RunIoRole.INPUT)
        self._repo.add_run_io(run_id, item.id, RunIoRole.OUTPUT)
        for input_id in derived_from:
            self._repo.add_lineage_edge(
                _edge(self._new_id, item.id, input_id, LineageKind.DERIVED_FROM, run_id, now)
            )
        if supersedes is not None:
            self._repo.add_lineage_edge(
                _edge(self._new_id, item.id, supersedes, LineageKind.SUPERSEDES, run_id, now)
            )
        return item

    def _governed_sources(self, object_ids: Sequence[str]) -> set[str]:
        """Source ids reachable from the objects, directly or through lineage ancestors."""
        sources: set[str] = set()
        for object_id in object_ids:
            if self._repo.entity_type_of(object_id) is None:
                raise InvalidLineage()
            nodes = [object_id, *(node for node, _ in self._repo.ancestors(object_id))]
            for node in nodes:
                sources |= self._sources_of(node)
        return sources

    def _sources_of(self, node: str) -> set[str]:
        kind = self._repo.entity_type_of(node)
        if kind is EntityType.SOURCE:
            return {node}
        if kind is EntityType.SOURCE_OBJECT:
            return {self._repo.get_source_object(node).source_id}
        if kind is EntityType.SEGMENT:
            return {self._repo.get_segment(node).source_id}
        if kind is EntityType.TOKEN_OCCURRENCE:
            segment = self._repo.get_segment(self._repo.get_token(node).segment_id)
            return {segment.source_id}
        return set()

    def _policy_of(self, source_id: str) -> PolicyLike:
        return effective_policy(self._repo, source_id)


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
