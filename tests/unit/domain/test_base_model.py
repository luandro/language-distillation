from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.base import DomainModel, id_field


class _Sample(DomainModel):
    id: str
    created_at: datetime


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        _Sample(id=new_id(IdPrefix.SOURCE), created_at=datetime(2026, 1, 1))  # noqa: DTZ001


def test_non_utc_datetime_rejected() -> None:
    cet = timezone(timedelta(hours=1))
    with pytest.raises(ValidationError):
        _Sample(id=new_id(IdPrefix.SOURCE), created_at=datetime(2026, 1, 1, tzinfo=cet))


def test_utc_datetime_accepted() -> None:
    value = datetime(2026, 1, 1, tzinfo=UTC)
    model = _Sample(id=new_id(IdPrefix.SOURCE), created_at=value)
    assert model.created_at == value


def test_domain_model_frozen_and_forbids_extra() -> None:
    model = _Sample(id=new_id(IdPrefix.SOURCE), created_at=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(ValidationError):
        model.id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _Sample(
            id=new_id(IdPrefix.SOURCE),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            extra_field=1,  # type: ignore[call-arg]
        )


def test_id_field_pattern() -> None:
    adapter: TypeAdapter[str] = TypeAdapter(id_field(IdPrefix.SOURCE))
    valid = new_id(IdPrefix.SOURCE)
    assert adapter.validate_python(valid) == valid
    with pytest.raises(ValidationError):
        adapter.validate_python(new_id(IdPrefix.RUN))
    with pytest.raises(ValidationError):
        adapter.validate_python("src_01m4q2cbk756ex2y10qtp6sxm")
