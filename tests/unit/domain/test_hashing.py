import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from langpipe.domain.hashing import (
    SHA256_PATTERN,
    canonical_json,
    config_hash,
    sha256_bytes,
    sha256_file,
)


class _Color(StrEnum):
    RED = "red"


class _Payload(BaseModel):
    name: str
    when: datetime


@given(st.dictionaries(st.text(), st.integers(), max_size=20))
def test_canonical_json_key_order_independent(data: dict[str, int]) -> None:
    forward = dict(sorted(data.items()))
    backward = dict(sorted(data.items(), reverse=True))
    assert canonical_json(forward) == canonical_json(backward)


def test_canonical_json_serializes_domain_values() -> None:
    value = {
        "when": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        "color": _Color.RED,
        "payload": _Payload(name="n", when=datetime(2026, 1, 2, tzinfo=UTC)),
    }
    assert canonical_json(value) == (
        '{"color":"red","payload":{"name":"n","when":"2026-01-02T00:00:00Z"},'
        '"when":"2026-01-02T03:04:05+00:00"}'
    )


def test_canonical_json_keeps_unicode() -> None:
    assert canonical_json({"k": "ŋ"}) == '{"k":"ŋ"}'


def test_sha256_bytes_is_lowercase_hex() -> None:
    digest = sha256_bytes(b"abc")
    assert digest == hashlib.sha256(b"abc").hexdigest()
    assert SHA256_PATTERN.match(digest)


def test_sha256_file_matches_bytes(tmp_path: Path) -> None:
    data = b"x" * (3 * 1024 + 7)
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    digest, size = sha256_file(path, chunk_size=1024)
    assert digest == sha256_bytes(data)
    assert size == len(data)


def test_config_hash_stable_known_vector() -> None:
    assert config_hash({}) == sha256_bytes(b"{}")


def test_sha256_pattern_rejects_uppercase() -> None:
    assert re.match(SHA256_PATTERN, "A" * 64) is None
