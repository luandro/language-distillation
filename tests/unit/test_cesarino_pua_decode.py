"""Offline tests for scripts/cesarino_pua_decode.py.

Inline strings copy real ``pdftotext -layout`` lines of the Cesarino 2008 thesis; the
expected outputs are the readings of the page crops in
``var/artifacts/cesarino_2008_thesis/evidence.json``. One regression test reads the PDF and
is skipped when it or ``pdftotext`` is absent.
"""

import importlib.util
import shutil
import sys
import unicodedata
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "cesarino_pua_decode.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cesarino_pua_decode", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pd = _load()

F017, F018, F01C = "", "", ""


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


@pytest.mark.parametrize("code", [F017, F018, F01C])
def test_each_mapped_code_is_a_combining_tilde_on_the_preceding_letter(code: str) -> None:
    assert pd.PUA_TABLE[code] == "̃"
    assert pd.decode_text(f"yochi{code}") == "yochĩ"
    assert pd.decode_text(f"noke{code}") == "nokẽ"
    assert pd.decode_text(f"E{code} isi{code}") == "Ẽ isĩ"


@pytest.mark.parametrize(
    ("raw", "decoded"),
    [
        (f"Lauro Brasil, Pani{F018}papa", "Lauro Brasil, Panĩpapa"),
        (f"ke{F018}chi{F018}txo, um shane ke{F018}chi{F018},", "kẽchĩtxo, um shane kẽchĩ,"),
        (f"do veneno do sapo ka{F018}pô.", "do veneno do sapo kãpô."),
        (f"nao vaki{F017}vaki{F01C}ki", "nao vakĩvakĩki"),
        (f"Noke{F01C} shovõ-se", "Nokẽ shovõ-se"),
        (f"A      yoi{F017}ni a", "A      yoĩni a"),
    ],
)
def test_real_lines_decode_to_the_image_reading(raw: str, decoded: str) -> None:
    assert pd.decode_text(raw) == nfc(decoded)


@pytest.mark.parametrize(
    ("raw", "decoded"),
    [
        (f"yochi-{F018}ra", "yochĩ-ra"),  # p282
        (f"Askátski {F018}shokoa", "Askátskĩ shokoa"),  # p333
        (f"oi{F018}ma {F018}", "oĩmã "),  # p98
        (f"410. nao vaki{F017}vaki {F01C}", "410. nao vakĩvakĩ "),  # p407
    ],
)
def test_one_space_or_hyphen_between_letter_and_mark_is_bridged(raw: str, decoded: str) -> None:
    stats = pd.DecodeStats()
    assert pd.decode_text(raw, stats) == nfc(decoded)
    assert sum(stats.bridged.values()) == 1
    assert not stats.unattached


@pytest.mark.parametrize(
    "raw",
    [
        f"{F018}abc",  # nothing before the mark
        f"ki  {F018}",  # two spaces: could be a column gap
        f"ki\n{F018}",  # line break
        f"12{F018}",  # digit, not a letter
        f"ki--{F018}",
    ],
)
def test_mark_without_an_adjacent_letter_stays_a_visible_marker(raw: str) -> None:
    stats = pd.DecodeStats()
    out = pd.decode_text(raw, stats)
    assert "<U+F018>" in out
    assert pd.remaining_pua(out) == 0
    assert stats.unattached[""] == 1


def test_unknown_pua_code_is_kept_as_marker_never_guessed() -> None:
    stats = pd.DecodeStats()
    out = pd.decode_text("yochi e", stats)
    assert out == "yochi<U+F019> e<U+E000>"
    assert stats.unmapped == {"": 1, "": 1}
    assert not stats.mapped


def test_no_mapped_code_leaves_pua_behind() -> None:
    raw = "".join(f"ki{c} ke{c} ka{c}" for c in pd.PUA_TABLE)
    out = pd.decode_text(raw)
    assert pd.remaining_pua(out) == 0
    assert "<U+" not in out


def test_decode_is_idempotent() -> None:
    raw = f"Pani{F018}papa yochi-{F017}ro {F018}x "
    once = pd.decode_text(raw)
    assert pd.decode_text(once) == once


def test_text_without_pua_is_unchanged() -> None:
    line = "Awẽ aki amaĩnõ, chinã nató (‘duplo’)"
    assert pd.decode_text(line) == line


PDF = ROOT / "var" / "external" / "cesarino_2008_thesis" / "cesarino_2008_thesis.pdf"


@pytest.mark.realdata
@pytest.mark.skipif(not PDF.exists() or shutil.which("pdftotext") is None, reason="needs PDF")
def test_full_thesis_decodes_without_leftover_pua() -> None:
    raw = pd.extract_layout_text(PDF)
    stats = pd.DecodeStats()
    out = pd.decode_text(raw, stats)
    assert {f"{ord(k):04X}": v for k, v in stats.seen.items()} == {
        "F017": 293,
        "F018": 652,
        "F01C": 402,
    }
    assert pd.remaining_pua(out) == 0
    assert not stats.unmapped and not stats.unattached
