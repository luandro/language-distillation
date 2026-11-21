"""Knowledge revocation impact over the relational lineage graph (WP4.9, WP5.15, ADR-0015).

Revocation impact is computed dynamically from the lineage DAG, never materialized:
`revocation_impact` walks the lineage DAG with `impact_of` and summarizes what a source
revocation reaches across lexical, morphology, and IGT entities.

No downstream row is mutated: linguistic status stays an observation of evidence,
while governance eligibility is decided by `lineage_eligibility` at read time.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langpipe.domain.enums import EntityType, LifecycleStatus, SourceStatus
from langpipe.domain.errors import InvalidLineage, NotFound
from langpipe.lineage.impact import ImpactEntry, impact_of
from langpipe.storage.repository import Repository


@dataclass(frozen=True)
class RevocationImpact:
    """Downstream lineage impact of a source revocation."""

    source_id: str
    source_status: SourceStatus
    entries: tuple[ImpactEntry, ...]
    by_type: Mapping[EntityType, tuple[str, ...]]
    validated_affected: tuple[str, ...]
    feature_assignments: tuple[tuple[str, str], ...] = ()

    @property
    def revoked(self) -> bool:
        return self.source_status is SourceStatus.REVOKED

    # --- M4 lexical buckets ---------------------------------------------------------------

    @property
    def lexemes(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.LEXEME, ())

    @property
    def senses(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.SENSE, ())

    @property
    def form_lexemes(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.FORM_LEXEME, ())

    @property
    def concepts(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.CONCEPT, ())

    @property
    def review_tasks(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.REVIEW_TASK, ())

    @property
    def review_decisions(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.REVIEW_DECISION, ())

    @property
    def artifacts(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.ARTIFACT, ())

    @property
    def evidence_items(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.EVIDENCE_ITEM, ())

    # --- M5 morphology & IGT buckets ------------------------------------------------------

    @property
    def igt_observations(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.IGT_OBSERVATION, ())

    @property
    def morphemes(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.MORPHEME, ())

    @property
    def allomorphs(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.ALLOMORPH, ())

    @property
    def morph_analyses(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.MORPH_ANALYSIS, ())

    @property
    def morph_segments(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.MORPH_SEGMENT, ())

    @property
    def segment_features(self) -> tuple[tuple[str, str], ...]:
        return self.feature_assignments

    # --- Observation buckets --------------------------------------------------------------

    @property
    def segments(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.SEGMENT, ())

    @property
    def tokens(self) -> tuple[str, ...]:
        return self.by_type.get(EntityType.TOKEN_OCCURRENCE, ())

    @property
    def total(self) -> int:
        return len(self.entries)

    def to_dict(self) -> dict[str, Any]:
        """IDs, statuses, and enum values only. Never contains raw text, forms, or glosses."""
        return {
            "source_id": self.source_id,
            "source_status": self.source_status.value,
            "revoked": self.revoked,
            "total": self.total,
            "validated_affected": list(self.validated_affected),
            "feature_assignments": [list(pair) for pair in self.feature_assignments],
            "by_type": {
                entity_type.value: list(ids)
                for entity_type, ids in sorted(self.by_type.items(), key=lambda item: item[0].value)
            },
            "entries": [
                {
                    "object_id": entry.object_id,
                    "entity_type": entry.entity_type.value,
                    "depth": entry.depth,
                }
                for entry in self.entries
            ],
        }


def revocation_impact(repo: Repository, source_id: str) -> RevocationImpact:
    """Computes the downstream lineage impact of revoking `source_id`.

    Traverses the relational lineage graph from `source_id` to all dependent entities.
    Works whether the source is already REVOKED or not (enabling what-if analysis).
    Raises NotFound if source_id is not found.
    Raises InvalidLineage if source_id is found but is not a SOURCE.
    """
    entity_type = repo.entity_type_of(source_id)
    if entity_type is None:
        raise NotFound(EntityType.SOURCE.value, source_id)
    if entity_type is not EntityType.SOURCE:
        raise InvalidLineage()
    source = repo.get_source(source_id)

    entries_list = list(impact_of(repo, source_id))
    analysis_depths = {
        entry.object_id: entry.depth
        for entry in entries_list
        if entry.entity_type is EntityType.MORPH_ANALYSIS
    }

    # Group by type: ensure every EntityType has a key (empty tuple if none)
    by_type_dict: dict[EntityType, list[str]] = {et: [] for et in EntityType}
    for entry in entries_list:
        by_type_dict[entry.entity_type].append(entry.object_id)

    # Include morph_segments belonging to impacted analyses
    seen_entry_ids = {entry.object_id for entry in entries_list}
    for analysis_id in list(by_type_dict[EntityType.MORPH_ANALYSIS]):
        depth = analysis_depths.get(analysis_id, 1) + 1
        for seg in repo.list_morph_segments(analysis_id):
            if seg.id not in seen_entry_ids:
                seen_entry_ids.add(seg.id)
                by_type_dict[EntityType.MORPH_SEGMENT].append(seg.id)
                entries_list.append(
                    ImpactEntry(object_id=seg.id, entity_type=EntityType.MORPH_SEGMENT, depth=depth)
                )

    entries = tuple(sorted(entries_list, key=lambda entry: (entry.depth, entry.object_id)))
    by_type: dict[EntityType, tuple[str, ...]] = {
        et: tuple(sorted(ids)) for et, ids in by_type_dict.items()
    }

    # Find validated affected entities across lexical and morphology domains
    validated: list[str] = []
    for lexeme_id in by_type.get(EntityType.LEXEME, ()):
        lexeme = repo.get_lexeme(lexeme_id)
        if lexeme.status is LifecycleStatus.VALIDATED:
            validated.append(lexeme_id)
    for sense_id in by_type.get(EntityType.SENSE, ()):
        sense = repo.get_sense(sense_id)
        if sense.status is LifecycleStatus.VALIDATED:
            validated.append(sense_id)
    for morpheme_id in by_type.get(EntityType.MORPHEME, ()):
        morpheme = repo.get_morpheme(morpheme_id)
        if morpheme.status is LifecycleStatus.VALIDATED:
            validated.append(morpheme_id)
    for analysis_id in by_type.get(EntityType.MORPH_ANALYSIS, ()):
        analysis = repo.get_morph_analysis(analysis_id)
        if analysis.status is LifecycleStatus.VALIDATED:
            validated.append(analysis_id)

    # Collect governed feature assignments (segment_id, feature_id) for impacted segments
    assignments: list[tuple[str, str]] = []
    for seg_id in by_type.get(EntityType.MORPH_SEGMENT, ()):
        for sf in repo.list_segment_features(seg_id):
            assignments.append((sf.segment_id, sf.feature_id))
    feature_assignments = tuple(sorted(set(assignments)))

    return RevocationImpact(
        source_id=source_id,
        source_status=source.status,
        entries=entries,
        by_type=by_type,
        validated_affected=tuple(sorted(validated)),
        feature_assignments=feature_assignments,
    )
