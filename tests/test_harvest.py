"""Unit tests for universal indigenous resource harvesting."""

import json
from pathlib import Path

import pytest

from langpipe.harvest.extractors.igt_parser import IgtObservationParser
from langpipe.harvest.models import (
    DiscoveredResource,
    HarvesterTarget,
    HarvestPolicy,
    HarvestStatus,
)
from langpipe.harvest.registry import UniversalSourceRegistry


@pytest.fixture
def temp_registry(tmp_path: Path) -> UniversalSourceRegistry:
    reg_file = tmp_path / "test_registry.json"
    return UniversalSourceRegistry(path=reg_file)


def test_registry_target_and_resources(temp_registry: UniversalSourceRegistry):
    target = HarvesterTarget(
        iso639_3="mzr",
        language_name="Marúbo",
        family="Pano",
        glottocode="maru1252",
        sister_languages=["mcf", "cul", "kax"],
    )
    temp_registry.register_target(target)
    retrieved = temp_registry.get_target("mzr")
    assert retrieved is not None
    assert retrieved.language_name == "Marúbo"
    assert "mcf" in retrieved.sister_languages

    res = DiscoveredResource(
        source_id="zenodo_1008779",
        language_code="mzr",
        glottocode="maru1252",
        title="Teachings of the Death-Path",
        author="Cesarino et al.",
        year=2017,
        repository_id="zenodo",
        url="https://zenodo.org/records/1008779",
        policy=HarvestPolicy.PERMISSIVE_ACADEMIC,
        status=HarvestStatus.INDEXED,
        related_languages=["mcf"],
    )
    temp_registry.add_resource(res)

    listed = temp_registry.list_resources(language_code="mzr")
    assert len(listed) == 1
    assert listed[0].source_id == "zenodo_1008779"

    recs = temp_registry.get_cross_language_recommendations("mzr")
    assert "mcf" in recs
    assert "cul" in recs


def test_igt_parser_parses_leipzig_blocks():
    sample_igt = """
(1) Txõtxõ Koro shavo, winin aká shavo,
Txõtxo Koro shavo winin aká shavo
bird grey women erection aux.trns women
‘Bird-women, seductive women,’
‘Mulheres-pássaro, as mulheres sedutoras,’

(2) Atisho vei ooki vei oo atisho.
a-ti-sho vei oo-iki vei oo a-ti-sho
3dem-nmlz-sssa death cry-vblz death cry 3dem-nmlz-sssa
‘women of the death-cry, of the death-cry.’
‘aquelas que soltaram o grito-morte, aquelas do grito-morte.’
"""
    from langpipe.domain.ids import IdPrefix, new_id

    parser = IgtObservationParser(
        source_id=new_id(IdPrefix.SOURCE),
        run_id=new_id(IdPrefix.RUN),
        source_object_id=new_id(IdPrefix.SOURCE_OBJECT),
    )
    observations, parallel_pairs = parser.parse_blocks(sample_igt)

    assert len(observations) == 2
    assert len(parallel_pairs) == 2

    obs1 = observations[0]
    assert obs1.record_ref == "(1)"
    assert len(obs1.tiers) >= 4
    assert obs1.translations.get("por") == ["Mulheres-pássaro, as mulheres sedutoras,"]
    assert obs1.translations.get("eng") == ["Bird-women, seductive women,"]

    pair1 = parallel_pairs[0]
    assert pair1["ref"] == "Cesarino-2017:(1)"
    assert "Txõtxõ Koro" in pair1["src"]
    assert "Mulheres-pássaro" in pair1["tgt"]


def test_openalex_spider_mocked(monkeypatch):
    import urllib.request
    from unittest.mock import MagicMock

    from langpipe.harvest.spiders.openalex import OpenAlexSpider

    mock_resp_data = {
        "results": [
            {
                "id": "https://openalex.org/W12345",
                "title": "Aspectos de Marubo e Matsés",
                "publication_year": 2017,
                "open_access": {"is_oa": True, "oa_url": "https://repo.example/paper.pdf"},
                "authorships": [{"author": {"display_name": "Test Author"}}],
                "type": "article",
            }
        ]
    }

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: mock_cm)

    spider = OpenAlexSpider()
    target = HarvesterTarget(
        iso639_3="mzr", language_name="Marúbo", family="Pano", sister_languages=["mcf"]
    )
    res = spider.search(target, limit=5)

    assert len(res) == 1
    assert res[0].source_id == "openalex_w12345"
    assert res[0].policy == HarvestPolicy.PERMISSIVE_ACADEMIC
    assert res[0].download_url == "https://repo.example/paper.pdf"
    assert "mcf" in res[0].related_languages


def test_zenodo_spider_mocked(monkeypatch):
    import urllib.request
    from unittest.mock import MagicMock

    from langpipe.harvest.spiders.zenodo import ZenodoSpider

    mock_resp = {
        "hits": {
            "hits": [
                {
                    "id": 1008779,
                    "doi": "10.5281/zenodo.1008779",
                    "metadata": {
                        "title": "Marubo IGT Chapter",
                        "publication_date": "2017-10-10",
                        "access_right": "open",
                        "license": {"id": "cc-by-4.0"},
                        "creators": [{"name": "Cesarino, Pedro"}],
                        "communities": [{"id": "langscipress"}],
                    },
                    "files": [
                        {
                            "links": {
                                "self": "https://zenodo.org/api/records/1008779/files/4.pdf/content"
                            },
                            "size": 507588,
                            "checksum": "md5:a4a006e",
                        }
                    ],
                }
            ]
        }
    }

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: mock_cm)

    spider = ZenodoSpider()
    target = HarvesterTarget(iso639_3="mzr", language_name="Marúbo", family="Pano")
    res = spider.search(target, limit=5)

    assert len(res) == 1
    assert res[0].source_id == "zenodo_1008779"
    assert res[0].policy == HarvestPolicy.PERMISSIVE_ACADEMIC
    assert "language_science_press" in res[0].features


def test_glottolog_spider_mocked(monkeypatch):
    import urllib.request
    from unittest.mock import MagicMock

    from langpipe.harvest.spiders.glottolog import GlottologSpider

    mock_resp = {
        "id": "maru1252",
        "name": "Marúbo",
        "latitude": -6.8,
        "longitude": -70.5,
        "classification": [{"name": "Panoan", "id": "pano1256"}],
    }

    mock_cm = MagicMock()
    mock_cm.__enter__.return_value.read.return_value = json.dumps(mock_resp).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=20: mock_cm)

    spider = GlottologSpider()
    target = HarvesterTarget(
        iso639_3="mzr", language_name="Marúbo", glottocode="maru1252", family="Pano"
    )
    res = spider.search(target)

    assert len(res) == 1
    assert res[0].source_id == "glottolog_maru1252"
    assert res[0].metadata["latitude"] == -6.8


def test_igt_parser_strips_footnote_digit_glued_after_closing_quote():
    """Zenodo 1008779 (54): ``‘outro já está morrido,’5`` must not keep the footnote digit."""
    from langpipe.domain.ids import IdPrefix, new_id

    sample_igt = """
(54) wetsaro vei ikitai,
wetsa-ro vei iki-tai
other-ins death be-prog
‘this one is dead,’
‘outro já está morrido,’5

(55) ato chinãmakĩ.
ato chinã-ma-kĩ
3pl think-caus-pst
‘About them she was thinking.’3
‘Sobre eles pensou.’
"""
    parser = IgtObservationParser(
        source_id=new_id(IdPrefix.SOURCE),
        run_id=new_id(IdPrefix.RUN),
        source_object_id=new_id(IdPrefix.SOURCE_OBJECT),
    )
    _, pairs = parser.parse_blocks(sample_igt)
    assert pairs[0]["tgt"] == "outro já está morrido,"
    assert pairs[1]["eng"] == "About them she was thinking."
    assert pairs[1]["tgt"] == "Sobre eles pensou."
