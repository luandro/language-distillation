import re
from enum import StrEnum
from typing import Protocol

from ulid import ULID

from langpipe.domain.errors import InvalidId


class IdPrefix(StrEnum):
    SOURCE = "src"
    POLICY = "pol"
    SOURCE_OBJECT = "sobj"
    RUN = "run"
    ARTIFACT = "artifact"
    SEGMENT = "seg"
    TOKEN = "tok"
    FORM = "form"
    EVIDENCE = "ev"
    LINEAGE = "lin"
    AUDIT = "aud"
    # M3 alignment evidence entities (ADR-0011):
    SEGMENT_ALIGNMENT = "sal"
    TOKEN_ALIGNMENT = "tal"
    # reserved for later milestones (define now, unused in M1):
    LEXEME = "lex"
    SENSE = "sense"
    MORPH_ANALYSIS = "ma"
    MORPHEME = "morph"
    REVIEW = "review"
    # M4 lexical evidence and review queue entities (ADR-0013):
    CONCEPT = "cpt"
    FORM_LEXEME = "flx"
    REVIEW_TASK = "rtask"
    REVIEW_DECISION = "rdec"
    # M5 IGT observation and morphology graph entities (ADR-0017):
    IGT_OBSERVATION = "igt"
    FEATURE = "feat"
    MORPH_SEGMENT = "mseg"
    ALLOMORPH = "allo"
    # M5 source-use approvals (ADR-0018). MorphGold files are frozen artifacts,
    # not object_registry rows, so they have no IdPrefix.
    SOURCE_USE_APPROVAL = "sua"


ID_PATTERN: re.Pattern[str] = re.compile(r"^(?P<prefix>[a-z]+)_(?P<ulid>[0-9A-HJKMNP-TV-Z]{26})$")


def new_id(prefix: IdPrefix) -> str:
    return f"{prefix.value}_{ULID()}"


def parse_id(value: str) -> tuple[IdPrefix, str]:
    match = ID_PATTERN.fullmatch(value)
    if match is None:
        raise InvalidId()
    try:
        prefix = IdPrefix(match.group("prefix"))
    except ValueError as exc:
        raise InvalidId() from exc
    return prefix, match.group("ulid")


def is_id(value: str, prefix: IdPrefix | None = None) -> bool:
    try:
        parsed_prefix, _ = parse_id(value)
    except InvalidId:
        return False
    return prefix is None or parsed_prefix is prefix


class IdFactory(Protocol):
    def __call__(self, prefix: IdPrefix) -> str: ...
