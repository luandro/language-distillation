from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from langpipe.domain.enums import EvidenceKind, EvidencePolarity, LineageKind
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _evidence(**overrides: object) -> EvidenceItem:
    values: dict[str, object] = {
        "id": new_id(IdPrefix.EVIDENCE),
        "kind": EvidenceKind.TOKEN_ALIGNMENT,
        "polarity": EvidencePolarity.SUPPORTS,
        "target_id": new_id(IdPrefix.TOKEN),
        "run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    values.update(overrides)
    return EvidenceItem(**values)  # type: ignore[arg-type]


def test_lineage_rejects_self_edge() -> None:
    node = new_id(IdPrefix.TOKEN)
    with pytest.raises(ValidationError):
        LineageEdge(
            id=new_id(IdPrefix.LINEAGE),
            from_id=node,
            to_id=node,
            kind=LineageKind.DERIVED_FROM,
            run_id=new_id(IdPrefix.RUN),
            created_at=NOW,
        )


def test_lineage_accepts_child_to_parent_edge() -> None:
    edge = LineageEdge(
        id=new_id(IdPrefix.LINEAGE),
        from_id=new_id(IdPrefix.EVIDENCE),
        to_id=new_id(IdPrefix.TOKEN),
        kind=LineageKind.DERIVED_FROM,
        run_id=new_id(IdPrefix.RUN),
        created_at=NOW,
    )
    assert edge.from_id.startswith("ev_")
    assert edge.to_id.startswith("tok_")


def test_evidence_extensions_namespaced() -> None:
    _evidence(extensions={"ext.acme-1_x": {"score": 1}})
    with pytest.raises(ValidationError):
        _evidence(extensions={"Bad Namespace": {"score": 1}})
    with pytest.raises(ValidationError):
        _evidence(extensions={"UPPER": {"score": 1}})


def test_evidence_is_frozen() -> None:
    item = _evidence()
    with pytest.raises(ValidationError):
        item.polarity = EvidencePolarity.CONTRADICTS  # type: ignore[misc]


def test_evidence_target_must_be_valid_id() -> None:
    with pytest.raises(ValidationError):
        _evidence(target_id="not-an-id")
