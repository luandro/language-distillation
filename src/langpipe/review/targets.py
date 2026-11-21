"""Entity-specific human review target handlers (M5-PLAN §7.11, WP5.13).

Provides `TargetHandler` implementations for each reviewed entity type:
- `lexeme` (LexemeTargetHandler)
- `sense` (SenseTargetHandler)
- `concept` (ConceptTargetHandler)
- `morpheme` (MorphemeTargetHandler)
- `morph_analysis` (MorphAnalysisTargetHandler)

Encapsulates status inspection, language/domain scoping, entity locking,
lifecycle status writes (recomputing lexical-v1 or morph-v1 score breakdowns),
dependent discovery (for stale flags), and successor validation on modify.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from langpipe.domain.enums import (
    EntityType,
    LifecycleStatus,
    ReviewDecisionKind,
    ReviewTaskType,
)
from langpipe.domain.errors import InvalidTransition, NotFound, SchemaViolation
from langpipe.domain.models.lexical import Lexeme, Sense
from langpipe.domain.models.morphology import (
    MorphAnalysis,
    Morpheme,
    MorphSegment,
)
from langpipe.lexicon.scoring import compute_score
from langpipe.morphology.scoring import score_analysis, score_morpheme
from langpipe.review.base import M4_TASK_TYPES
from langpipe.storage.repository import Repository

_UNSCOPED_LANGUAGE = "und"


class TargetHandler(Protocol):
    """Protocol for target-specific operations during human review."""

    entity_type: EntityType
    allowed_task_types: frozenset[ReviewTaskType]

    def status_of(self, repo: Repository, object_id: str) -> LifecycleStatus | None:
        """Return the target's current lifecycle status, or None if queue-only."""
        ...

    def language_of(self, repo: Repository, object_id: str) -> str:
        """Return the target's language code for authority checking."""
        ...

    def domain_of(self, repo: Repository, object_id: str) -> str | None:
        """Return the target's domain, or None if un-scoped."""
        ...

    def lock(self, repo: Repository, object_id: str) -> Any:
        """Lock the target row for update in the active transaction."""
        ...

    def set_status(
        self,
        repo: Repository,
        object_id: str,
        status: LifecycleStatus,
        language: str,
    ) -> None:
        """Write the new status and recompute the target's versioned score breakdown."""
        ...

    def dependents(self, repo: Repository, object_id: str) -> Sequence[str]:
        """Return IDs of directly dependent entities to be flagged stale."""
        ...

    def check_successor(
        self,
        repo: Repository,
        target_id: str,
        successor_id: str | None,
    ) -> Any:
        """Validate and return the successor entity for a modify decision."""
        ...

    def check_decision_legal(
        self,
        repo: Repository,
        target_id: str,
        decision: ReviewDecisionKind,
    ) -> None:
        """Validate whether the decision is permitted on this target."""
        ...


class LexemeTargetHandler:
    """Target handler for Lexeme entities."""

    entity_type = EntityType.LEXEME
    allowed_task_types = M4_TASK_TYPES

    def status_of(self, repo: Repository, object_id: str) -> LifecycleStatus:
        return repo.get_lexeme(object_id).status

    def language_of(self, repo: Repository, object_id: str) -> str:
        return repo.get_lexeme(object_id).language

    def domain_of(self, repo: Repository, object_id: str) -> str | None:
        return repo.get_lexeme(object_id).domain

    def lock(self, repo: Repository, object_id: str) -> Lexeme:
        return repo.get_lexeme(object_id)

    def set_status(
        self,
        repo: Repository,
        object_id: str,
        status: LifecycleStatus,
        language: str,
    ) -> None:
        evidence = repo.list_evidence_for_target(object_id)
        breakdown = compute_score(evidence, language)
        repo.set_lexeme_status(object_id, status, breakdown)

    def dependents(self, repo: Repository, object_id: str) -> Sequence[str]:
        return [s.id for s in repo.list_senses_for_lexeme(object_id)]

    def check_successor(
        self,
        repo: Repository,
        target_id: str,
        successor_id: str | None,
    ) -> Lexeme:
        if successor_id is None or successor_id == target_id:
            raise SchemaViolation()
        succ_type = repo.entity_type_of(successor_id)
        if succ_type is None:
            raise NotFound(EntityType.LEXEME.value, successor_id)
        if succ_type is not EntityType.LEXEME:
            raise SchemaViolation()
        target = repo.get_lexeme(target_id)
        successor = repo.get_lexeme(successor_id)
        if successor.language != target.language:
            raise SchemaViolation()
        return successor

    def check_decision_legal(
        self,
        repo: Repository,
        target_id: str,
        decision: ReviewDecisionKind,
    ) -> None:
        pass


class SenseTargetHandler:
    """Target handler for Sense entities."""

    entity_type = EntityType.SENSE
    allowed_task_types = M4_TASK_TYPES

    def status_of(self, repo: Repository, object_id: str) -> LifecycleStatus:
        return repo.get_sense(object_id).status

    def language_of(self, repo: Repository, object_id: str) -> str:
        sense = repo.get_sense(object_id)
        return repo.get_lexeme(sense.lexeme_id).language

    def domain_of(self, repo: Repository, object_id: str) -> str | None:
        return repo.get_sense(object_id).domain

    def lock(self, repo: Repository, object_id: str) -> Sense:
        return repo.get_sense(object_id)

    def set_status(
        self,
        repo: Repository,
        object_id: str,
        status: LifecycleStatus,
        language: str,
    ) -> None:
        evidence = repo.list_evidence_for_target(object_id)
        breakdown = compute_score(evidence, language)
        repo.set_sense_status(object_id, status, breakdown)

    def dependents(self, repo: Repository, object_id: str) -> Sequence[str]:
        return ()

    def check_successor(
        self,
        repo: Repository,
        target_id: str,
        successor_id: str | None,
    ) -> Sense:
        if successor_id is None or successor_id == target_id:
            raise SchemaViolation()
        succ_type = repo.entity_type_of(successor_id)
        if succ_type is None:
            raise NotFound(EntityType.SENSE.value, successor_id)
        if succ_type is not EntityType.SENSE:
            raise SchemaViolation()
        target = repo.get_sense(target_id)
        successor = repo.get_sense(successor_id)
        if successor.lexeme_id != target.lexeme_id:
            raise SchemaViolation()
        return successor

    def check_decision_legal(
        self,
        repo: Repository,
        target_id: str,
        decision: ReviewDecisionKind,
    ) -> None:
        pass


class ConceptTargetHandler:
    """Target handler for Concept entities (queue-only, no lifecycle status)."""

    entity_type = EntityType.CONCEPT
    allowed_task_types = M4_TASK_TYPES

    def status_of(self, repo: Repository, object_id: str) -> LifecycleStatus | None:
        return None

    def language_of(self, repo: Repository, object_id: str) -> str:
        return _UNSCOPED_LANGUAGE

    def domain_of(self, repo: Repository, object_id: str) -> str | None:
        return None

    def lock(self, repo: Repository, object_id: str) -> Any:
        return repo.get_concept(object_id)

    def set_status(
        self,
        repo: Repository,
        object_id: str,
        status: LifecycleStatus,
        language: str,
    ) -> None:
        raise SchemaViolation()

    def dependents(self, repo: Repository, object_id: str) -> Sequence[str]:
        return ()

    def check_successor(
        self,
        repo: Repository,
        target_id: str,
        successor_id: str | None,
    ) -> Any:
        raise SchemaViolation()

    def check_decision_legal(
        self,
        repo: Repository,
        target_id: str,
        decision: ReviewDecisionKind,
    ) -> None:
        if decision not in (ReviewDecisionKind.UNCERTAIN, ReviewDecisionKind.DEFER):
            raise SchemaViolation()


class MorphemeTargetHandler:
    """Target handler for Morpheme entities."""

    entity_type = EntityType.MORPHEME
    allowed_task_types = frozenset({ReviewTaskType.MORPHEME_FUNCTION})

    def status_of(self, repo: Repository, object_id: str) -> LifecycleStatus:
        return repo.get_morpheme(object_id).status

    def language_of(self, repo: Repository, object_id: str) -> str:
        return repo.get_morpheme(object_id).language

    def domain_of(self, repo: Repository, object_id: str) -> str | None:
        return None

    def lock(self, repo: Repository, object_id: str) -> Morpheme:
        return repo.get_morpheme_for_update(object_id)

    def set_status(
        self,
        repo: Repository,
        object_id: str,
        status: LifecycleStatus,
        language: str,
    ) -> None:
        evidence = repo.list_evidence_for_target(object_id)
        _, breakdown = score_morpheme(evidence_items=evidence)
        repo.set_morpheme_status(object_id, status, breakdown)
        for allomorph in repo.list_allomorphs_for_morpheme(object_id):
            repo.set_allomorph_status(allomorph.id, status)

    def dependents(self, repo: Repository, object_id: str) -> Sequence[str]:
        return [a.id for a in repo.list_analyses_linking_morpheme(object_id)]

    def check_successor(
        self,
        repo: Repository,
        target_id: str,
        successor_id: str | None,
    ) -> Morpheme:
        if successor_id is None or successor_id == target_id:
            raise SchemaViolation()
        succ_type = repo.entity_type_of(successor_id)
        if succ_type is None:
            raise NotFound(EntityType.MORPHEME.value, successor_id)
        if succ_type is not EntityType.MORPHEME:
            raise SchemaViolation()
        target = repo.get_morpheme(target_id)
        successor = repo.get_morpheme_for_update(successor_id)
        if successor.language != target.language:
            raise SchemaViolation()
        return successor

    def check_decision_legal(
        self,
        repo: Repository,
        target_id: str,
        decision: ReviewDecisionKind,
    ) -> None:
        pass


class MorphAnalysisTargetHandler:
    """Target handler for MorphAnalysis entities."""

    entity_type = EntityType.MORPH_ANALYSIS
    allowed_task_types = frozenset({ReviewTaskType.MORPHOLOGY_SEGMENTATION})

    def status_of(self, repo: Repository, object_id: str) -> LifecycleStatus:
        return repo.get_morph_analysis(object_id).status

    def language_of(self, repo: Repository, object_id: str) -> str:
        analysis = repo.get_morph_analysis(object_id)
        token = repo.get_token(analysis.target_token_id)
        segment = repo.get_segment(token.segment_id)
        return segment.language

    def domain_of(self, repo: Repository, object_id: str) -> str | None:
        return None

    def lock(self, repo: Repository, object_id: str) -> MorphAnalysis:
        return repo.get_morph_analysis_for_update(object_id)

    def set_status(
        self,
        repo: Repository,
        object_id: str,
        status: LifecycleStatus,
        language: str,
    ) -> None:
        analysis = repo.get_morph_analysis(object_id)
        segments: list[MorphSegment] = repo.list_morph_segments(object_id)
        linked_m: list[Morpheme] = []
        for seg in segments:
            if seg.morpheme_id is not None:
                linked_m.append(repo.get_morpheme(seg.morpheme_id))
        evidence = repo.list_evidence_for_target(object_id)
        token_analyses = repo.list_morph_analyses_for_token(analysis.target_token_id)
        distinct_sigs = len({a.signature for a in token_analyses})
        _, breakdown = score_analysis(
            method=analysis.method,
            linked_morphemes=linked_m,
            segments=segments,
            evidence_items=evidence,
            distinct_signatures_on_token=distinct_sigs,
        )
        repo.set_morph_analysis_status(object_id, status, breakdown)

    def dependents(self, repo: Repository, object_id: str) -> Sequence[str]:
        return ()

    def check_successor(
        self,
        repo: Repository,
        target_id: str,
        successor_id: str | None,
    ) -> MorphAnalysis:
        if successor_id is None or successor_id == target_id:
            raise SchemaViolation()
        succ_type = repo.entity_type_of(successor_id)
        if succ_type is None:
            raise NotFound(EntityType.MORPH_ANALYSIS.value, successor_id)
        if succ_type is not EntityType.MORPH_ANALYSIS:
            raise SchemaViolation()
        target = repo.get_morph_analysis(target_id)
        successor = repo.get_morph_analysis_for_update(successor_id)
        if successor.target_token_id != target.target_token_id:
            raise SchemaViolation()
        if successor.signature == target.signature:
            raise SchemaViolation()
        succ_m_ids = sorted(
            {
                seg.morpheme_id
                for seg in repo.list_morph_segments(successor.id)
                if seg.morpheme_id is not None
            }
        )
        for m_id in succ_m_ids:
            m = repo.get_morpheme_for_update(m_id)
            if m.status in (LifecycleStatus.REJECTED, LifecycleStatus.DEPRECATED):
                raise InvalidTransition()
        return successor

    def check_decision_legal(
        self,
        repo: Repository,
        target_id: str,
        decision: ReviewDecisionKind,
    ) -> None:
        if decision is ReviewDecisionKind.ACCEPT:
            segments = repo.list_morph_segments(target_id)
            linked_m_ids = sorted(
                {seg.morpheme_id for seg in segments if seg.morpheme_id is not None}
            )
            for m_id in linked_m_ids:
                m = repo.get_morpheme_for_update(m_id)
                if m.status in (LifecycleStatus.REJECTED, LifecycleStatus.DEPRECATED):
                    raise InvalidTransition()


_HANDLERS: dict[EntityType, TargetHandler] = {
    EntityType.LEXEME: LexemeTargetHandler(),
    EntityType.SENSE: SenseTargetHandler(),
    EntityType.CONCEPT: ConceptTargetHandler(),
    EntityType.MORPHEME: MorphemeTargetHandler(),
    EntityType.MORPH_ANALYSIS: MorphAnalysisTargetHandler(),
}


def get_target_handler(entity_type: EntityType) -> TargetHandler:
    """Retrieve the target handler for a given entity type, or raise NotFound."""
    handler = _HANDLERS.get(entity_type)
    if handler is None:
        raise NotFound("handler", entity_type.value)
    return handler


__all__ = [
    "ConceptTargetHandler",
    "LexemeTargetHandler",
    "MorphAnalysisTargetHandler",
    "MorphemeTargetHandler",
    "SenseTargetHandler",
    "TargetHandler",
    "get_target_handler",
]
