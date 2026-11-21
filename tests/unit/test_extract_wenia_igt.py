"""Offline tests for scripts/extract_wenia_igt.py.

No PDF and no subprocess: the group parser and checks run on tier lines copied from the annex
(Cesarino 2018, PDF pp. 52-53) exactly as ``pdftotext -bbox`` groups them.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "extract_wenia_igt.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("extract_wenia_igt", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wi = _load()

# Verse 560 group: the segmented tier wraps after a hyphen ("Ato-vo-" / "ki"), and so does the
# gloss ("3pDEM-" / "GENR-ASS").
GROUP_560 = [
    "560. “Nõ maposhoinõ” / Iki avainiki / Atovoki",
    "“Nõ mapo-sho-i-nõ” / Iki a-vaini-ki / Ato-vo-",
    "ki",
    "1pINCL.ERG caçarLE-DB-PR-FIN HSAY AUX-CON-ASS 3pDEM-",
    "GENR-ASS",
]
# Verse 575 group: the segmented tier wraps at a space ("Wa ravosh" / "matxi-ki /").
GROUP_575 = [
    "575. A awẽ mapoki / Kocha akevaiki / Wa ravosh matxiki /",
    "A awẽ mapo-ki / Kocha-ake-vaiki / Wa ravosh",
    "matxi-ki /",
    "3DEM POSS cabeça-ASS despir-CMPL-CON DEMdist. joelho cima-",
    "LOC",
]
# Verse 555 group: one surface line printed as two (segmented, gloss) chunk pairs.
GROUP_555 = [
    "555. Aki ainaiya / Yora popo shavo / Saiainaiya /",
    "A-ki a-ina-ya / Yora popo shavo /",
    "AUX-ASS 3DEM-CONfin-PRF gente coruja mulher",
    "Sai-ai-ina-ya /",
    "gritocanto-PR-CONfin-PRF",
]
# Verse 550 group: five segmented words but four printed glosses.
GROUP_550 = [
    "550. Atõ roaroai / Shavá karãkarãi /",
    "Atõ roa-roa-i / Shavá ka-rã ka-rã-i /",
    "3pDEM.ERG dia Mov.sing-DIRcentrip. Mov.sing-DIRcentrip.-PR",
]
NEXT_GROUP = [
    "Amaĩnõ / “ píti anõnã / Patxotã itirao",
    "a-maĩnõ / “E píti anõ-nã / Patxo tã i-ti-rao",
    "AUX-CON 1s.ERG comida FIN-FC árvore onomat. AUXintr-?-IMP.LE",
]


def test_hyphen_wrap_is_rejoined_and_aligned() -> None:
    units, consumed = wi.parse_group(GROUP_560 + NEXT_GROUP, 52)
    assert consumed == len(GROUP_560)
    assert units[0].label == 560
    assert [u.segmented for u in units] == ["“Nõ mapo-sho-i-nõ”", "Iki a-vaini-ki", "Ato-vo-ki"]
    assert units[2].gloss == "3pDEM-GENR-ASS"
    for unit in units:
        assert unit.gloss is not None
        assert wi.alignment_problems(unit.segmented, unit.gloss) == []
        assert wi.round_trip_ok(unit.segmented, unit.surface)


def test_space_wrap_is_rejoined_and_round_trips() -> None:
    units, _ = wi.parse_group(GROUP_575, 53)
    last = units[2]
    assert last.segmented == "Wa ravosh matxi-ki"
    assert last.gloss == "DEMdist. joelho cima-LOC"
    assert wi.alignment_problems(last.segmented, last.gloss) == []
    # Spaces and hyphens both disappear in the round trip: "Kocha-ake-vaiki" -> "Kocha akevaiki".
    assert units[1].segmented == "Kocha-ake-vaiki"
    assert wi.round_trip_ok(units[1].segmented, units[1].surface)
    assert wi.round_trip_ok("Shavá ka-rã ka-rã-i", "Shavá karãkarãi")


def test_chunked_group_assigns_glosses_per_verse() -> None:
    units, consumed = wi.parse_group(GROUP_555, 52)
    assert consumed == 5
    assert [u.gloss for u in units] == [
        "AUX-ASS 3DEM-CONfin-PRF",
        "gente coruja mulher",
        "gritocanto-PR-CONfin-PRF",
    ]
    # The annex prints Sai-ai-ina-ya under Saiainaiya: reported, never repaired.
    assert not wi.round_trip_ok(units[2].segmented, units[2].surface)


def test_unsplittable_gloss_is_kept_whole_not_guessed() -> None:
    units, _ = wi.parse_group(GROUP_550, 52)
    assert [u.gloss for u in units] == [None, None]
    assert units[0].gloss_unaligned == GROUP_550[2]


def test_alignment_reports_word_and_morpheme_mismatches() -> None:
    assert wi.alignment_problems("Atõ roa-roa-i", "3pDEM.ERG") == ["words: 2 segmented vs 1 gloss"]
    assert wi.alignment_problems("A-ki-ri", "DEM-LOC") == ["A-ki-ri (3) vs DEM-LOC (2)"]
    assert wi.alignment_problems("Patxo tã i-ti-rao", "árvore onomat. AUXintr-?-IMP.LE") == []


def test_units_merge_to_cover_one_main_text_verse() -> None:
    units, _ = wi.parse_group(GROUP_560 + NEXT_GROUP, 52)
    tail, _ = wi.parse_group(NEXT_GROUP, 52)
    main = [
        wi.MainVerse(512, "“Nõ maposhoinõ”", "“Vamos caçar!”", 32),
        wi.MainVerse(513, "Iki avainiki", "Assim mesmo dizem", 32),
        wi.MainVerse(514, "Atovoki amaĩnõ", "E enquanto isso", 32),
        wi.MainVerse(515, "“E píti anõnã", "“Comida farei", 32),
        wi.MainVerse(516, "Patxo tã itirao", "Na árvore batam", 32),
    ]
    matched = wi.group_into_verses(units + tail, main)
    assert [len(verse.units) for verse, _, _ in matched] == [1, 1, 2, 1, 1]
    assert matched[2][1].number == 514
    # The text layer drops the Ẽ of "“Ẽ píti": matched by similarity, ratio reported.
    assert 0.8 <= matched[3][2] < 1.0


def test_main_text_rows_are_numbered_and_footnotes_stripped() -> None:
    rows = [
        (32, None, "Yora chĩchĩ shavo", "Mulheres gavião"),
        (32, None, "Yora chĩchĩ shavo", "Mulheres gavião50"),
        (32, 500, "Atõ shavo akaki", "Com elas ficam"),
    ]
    verses = wi.number_rows(rows)
    assert [v.number for v in verses] == [498, 499, 500]
    assert verses[1].por == "Mulheres gavião"
    assert verses[1].por_raw == "Mulheres gavião50"
    with pytest.raises(ValueError):
        wi.number_rows([(32, 500, "a", "b"), (32, 502, "c", "d")])


def test_legend_rows_skip_running_heads() -> None:
    page = "\n".join(
        [
            "                                   ––––––––––––        Wenía",
            "ABS                           Absolutivo",
            "DIRcentrip.                   Direção centrípeta",
            "   estudos de literatura brasileira contemporânea, n. 53   98",
        ]
    )
    entries = wi.parse_legend([page], 54)
    assert [e["abbreviation"] for e in entries] == ["ABS", "DIRcentrip."]
    assert entries[1]["expansion"] == "Direção centrípeta"
