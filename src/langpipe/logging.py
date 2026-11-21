import logging
import re
import sys
from typing import TextIO

from langpipe.domain.enums import Operation, PolicyDecision, PolicyMode, RunStatus, SourceStatus
from langpipe.domain.ids import IdPrefix, is_id

LOGGER_NAME = "langpipe"
SAFE_VALUE = re.compile(r"^([a-z]+_[0-9A-HJKMNP-TV-Z]{26}|[0-9a-f]{64})$")
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_FORMAT = "%(levelname)s %(name)s %(message)s"

_ID_FIELDS: dict[str, IdPrefix] = {
    "source_id": IdPrefix.SOURCE,
    "source_object_id": IdPrefix.SOURCE_OBJECT,
    "run_id": IdPrefix.RUN,
    "artifact_id": IdPrefix.ARTIFACT,
    "policy_id": IdPrefix.POLICY,
}
_ENUM_FIELDS: dict[str, frozenset[str]] = {
    "operation": frozenset(m.value for m in Operation),
    "decision": frozenset(m.value for m in PolicyDecision),
    "mode": frozenset(m.value for m in PolicyMode),
    "status": frozenset(m.value for m in (*SourceStatus, *RunStatus)),
}
_COUNT_FIELDS = frozenset({"objects", "blobs", "count"})
_BOOL_FIELDS = frozenset({"reused"})
_ALLOWED_FIELDS = (
    frozenset(_ID_FIELDS) | frozenset(_ENUM_FIELDS) | _COUNT_FIELDS | _BOOL_FIELDS | {"sha256"}
)


class UnsafeLogValue(ValueError):
    """Raised when a log event or field would expose non-allowlisted content.

    The message never echoes the offending value.
    """


class _StderrHandler(logging.StreamHandler[TextIO]):
    """Marks the handler installed by configure_logging so repeat calls can detect it."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)


def configure_logging(level: str = "INFO") -> None:
    logger = logging.getLogger(LOGGER_NAME)
    if not any(isinstance(handler, _StderrHandler) for handler in logger.handlers):
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(level)


def _render_field(key: str, value: str | int | bool | None) -> str:
    if key not in _ALLOWED_FIELDS:
        raise UnsafeLogValue("log field is not allowlisted")
    if value is None:
        return "None"
    if key in _COUNT_FIELDS:
        if type(value) is not int or value < 0:
            raise UnsafeLogValue(f"field {key} requires a nonnegative int")
        return str(value)
    if key in _BOOL_FIELDS:
        if type(value) is not bool:
            raise UnsafeLogValue(f"field {key} requires a bool")
        return "true" if value else "false"
    if not isinstance(value, str):
        raise UnsafeLogValue(f"field {key} requires a string")
    if key in _ID_FIELDS:
        if SAFE_VALUE.fullmatch(value) is None or not is_id(value, _ID_FIELDS[key]):
            raise UnsafeLogValue(f"field {key} is not a valid identifier")
    elif key == "sha256":
        if _SHA256_HEX.fullmatch(value) is None:
            raise UnsafeLogValue("field sha256 is not a valid digest")
    elif value not in _ENUM_FIELDS[key]:
        raise UnsafeLogValue(f"field {key} is not an allowed value")
    return value


def log_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    **fields: str | int | bool | None,
) -> None:
    if _EVENT_NAME.fullmatch(event) is None:
        raise UnsafeLogValue("event name is not valid")
    rendered = {key: _render_field(key, value) for key, value in fields.items()}
    parts = [f"event={event}", *(f"{key}={rendered[key]}" for key in sorted(rendered))]
    logger.log(level, " ".join(parts))
