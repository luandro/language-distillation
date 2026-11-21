from pathlib import Path

import pytest
from pydantic import ValidationError

from langpipe.domain.errors import SchemaViolation
from langpipe.languages.inventory import Inventory, inventory_diagnostics, load_inventory


def _inventory(**overrides: object) -> Inventory:
    fields: dict[str, object] = {
        "language": "qaa",
        "status": "unverified",
        "characters": (),
        "digraphs": (),
        "reviewed_by": None,
        "notes": None,
    }
    fields.update(overrides)
    return Inventory(**fields)  # type: ignore[arg-type]


def test_inventory_unverified_disables_diagnostics() -> None:
    assert inventory_diagnostics("kanu 12, tx!", _inventory()) == {}


def test_inventory_requires_reviewer_unless_unverified() -> None:
    for status in ("provisional", "verified"):
        with pytest.raises(ValidationError):
            _inventory(status=status)
        reviewed = _inventory(status=status, reviewed_by="reviewer")
        assert reviewed.reviewed_by == "reviewer"


def test_inventory_diagnostics_counts_codepoints_not_text() -> None:
    inv = _inventory(status="verified", reviewed_by="reviewer", characters=("a",))

    diagnostics = inventory_diagnostics("ab ab! ç", inv)

    assert diagnostics == {
        "char_outside_inventory:U+0062": 2,
        "char_outside_inventory:U+00E7": 1,
    }
    assert all("b" not in key and "ç" not in key for key in diagnostics)


def test_inventory_multicodepoint_grapheme_covers_its_codepoints() -> None:
    # k + combining tilde has no precomposed NFC form, so it stays a valid multi-codepoint grapheme.
    inv = _inventory(status="verified", reviewed_by="reviewer", characters=("k\u0303",))

    assert inventory_diagnostics("k\u0303", inv) == {}


def test_inventory_accepts_nfc_multicodepoint_grapheme() -> None:
    inv = _inventory(characters=("k\u0303",))

    assert inv.characters == ("k\u0303",)


@pytest.mark.parametrize(
    "entry", ["", "ab", "a\u0303", "\u0303a", "\u0303", "\n\u0303", "\r\u0303"]
)
def test_inventory_rejects_non_single_nfc_grapheme(entry: str) -> None:
    with pytest.raises(ValidationError):
        _inventory(characters=(entry,))


def test_inventory_digraphs_are_kept_separate_from_characters() -> None:
    inv = _inventory(status="verified", reviewed_by="reviewer", digraphs=("tx", "sh"))

    assert inv.digraphs == ("tx", "sh")
    with pytest.raises(ValidationError):
        _inventory(characters=("tx",))


@pytest.mark.parametrize("entry", ["ab", "a\u0303"])
def test_load_inventory_rejects_invalid_character_entry_without_echoing(
    tmp_path: Path, entry: str
) -> None:
    bad = tmp_path / "inventory.yaml"
    bad.write_text(
        f"language: qaa\nstatus: unverified\ncharacters: ['{entry}']\n",
        encoding="utf-8",
    )

    with pytest.raises(SchemaViolation) as err:
        load_inventory(bad)

    assert str(err.value) == "schema violation"
    assert entry not in str(err.value)
    assert str(tmp_path) not in str(err.value)


def test_inventory_ignores_ascii_space_and_punct() -> None:
    inv = _inventory(status="verified", reviewed_by="reviewer", characters=("a",))

    assert inventory_diagnostics("a a,;.!? ", inv) == {}


def test_load_inventory_rejects_malformed_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "inventory.yaml"
    bad.write_text("language: [unclosed\n", encoding="utf-8")

    with pytest.raises(SchemaViolation):
        load_inventory(bad)


def test_load_inventory_rejects_invalid_model(tmp_path: Path) -> None:
    bad = tmp_path / "inventory.yaml"
    bad.write_text("language: qaa\nstatus: nonsense\ncharacters: []\n", encoding="utf-8")

    with pytest.raises(SchemaViolation):
        load_inventory(bad)


def test_load_inventory_missing_file_is_schema_violation(tmp_path: Path) -> None:
    with pytest.raises(SchemaViolation):
        load_inventory(tmp_path / "absent.yaml")


def test_load_inventory_roundtrips_valid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "inventory.yaml"
    path.write_text(
        "language: qaa\n"
        "status: unverified\n"
        "characters: []\n"
        "digraphs: []\n"
        "reviewed_by: null\n"
        "notes: null\n",
        encoding="utf-8",
    )

    loaded = load_inventory(path)

    assert loaded.language == "qaa"
    assert loaded.status == "unverified"
    assert loaded.characters == ()
