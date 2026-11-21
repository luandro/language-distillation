import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from langpipe.domain.errors import InvalidId
from langpipe.domain.ids import ID_PATTERN, IdPrefix, is_id, new_id, parse_id


def test_new_id_has_prefix_and_ulid() -> None:
    value = new_id(IdPrefix.SEGMENT)
    assert value.startswith("seg_")
    assert ID_PATTERN.match(value)
    assert len(value) == len("seg_") + 26


@given(st.sampled_from(list(IdPrefix)))
def test_parse_id_roundtrip(prefix: IdPrefix) -> None:
    value = new_id(prefix)
    parsed_prefix, ulid = parse_id(value)
    assert parsed_prefix is prefix
    assert f"{parsed_prefix.value}_{ulid}" == value
    assert is_id(value, prefix)
    assert is_id(value)


def test_parse_id_rejects_lowercase_ulid() -> None:
    value = new_id(IdPrefix.SOURCE).lower()
    with pytest.raises(InvalidId):
        parse_id(value)
    assert not is_id(value)


def test_parse_id_rejects_unknown_prefix() -> None:
    with pytest.raises(InvalidId):
        parse_id("zzz_" + new_id(IdPrefix.SOURCE)[4:])


def test_parse_id_rejects_trailing_newline() -> None:
    value = new_id(IdPrefix.SOURCE) + "\n"
    with pytest.raises(InvalidId):
        parse_id(value)
    assert not is_id(value)


def test_is_id_checks_prefix_when_given() -> None:
    value = new_id(IdPrefix.RUN)
    assert not is_id(value, IdPrefix.SOURCE)


def test_ids_are_unique_over_10k() -> None:
    ids = {new_id(IdPrefix.TOKEN) for _ in range(10_000)}
    assert len(ids) == 10_000


def test_id_pattern_is_compiled_regex() -> None:
    assert isinstance(ID_PATTERN, re.Pattern)
