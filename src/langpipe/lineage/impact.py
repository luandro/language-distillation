from dataclasses import dataclass

from langpipe.domain.enums import EntityType
from langpipe.domain.errors import InvalidLineage
from langpipe.storage.repository import Repository


@dataclass(frozen=True)
class ImpactEntry:
    object_id: str
    entity_type: EntityType
    depth: int


def impact_of(repo: Repository, object_id: str) -> list[ImpactEntry]:
    """Every object that depends, directly or transitively, on `object_id`, nearest first."""
    entries: list[ImpactEntry] = []
    for descendant_id, depth in repo.descendants(object_id):
        entity_type = repo.entity_type_of(descendant_id)
        if entity_type is None:
            raise InvalidLineage()
        entries.append(ImpactEntry(object_id=descendant_id, entity_type=entity_type, depth=depth))
    return sorted(entries, key=lambda entry: (entry.depth, entry.object_id))
