import warnings
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from langpipe.domain.ids import IdPrefix

# Pydantic warns when a model field name shadows an attribute on ABCMeta (which Pydantic's
# metaclass inherits). The field `register` on Lexeme, Sense, and EvidenceItem is a persisted
# contract (database column, JSON key, golden snapshot). We filter this specific warning narrowly.
warnings.filterwarnings(
    "ignore",
    message=r'Field name "register" in "(Lexeme|Sense|EvidenceItem)" shadows',
    category=UserWarning,
)

UTC_NOW: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731

LANG_CODE = Annotated[str, StringConstraints(pattern=r"^[a-z]{3}$")]
VERSIONED_NAME = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.-]*@[0-9A-Za-z_.-]+$")
]
SHA256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def id_field(prefix: IdPrefix) -> Any:
    return Annotated[str, StringConstraints(pattern=rf"^{prefix.value}_[0-9A-HJKMNP-TV-Z]{{26}}$")]


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    SCHEMA_NAME: ClassVar[str | None] = None
    SCHEMA_VERSION: ClassVar[int] = 1

    @model_validator(mode="after")
    def _datetimes_are_utc(self) -> "DomainModel":
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime) and value.utcoffset() != timedelta(0):
                raise ValueError(f"datetime field {name} must be timezone-aware UTC")
        return self
