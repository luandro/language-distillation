from pathlib import Path

import yaml

from langpipe.domain.enums import SourceType
from langpipe.extraction.registry import default_extractor_for

FIXTURE_SOURCES = Path(__file__).parents[2] / "golden" / "fixture" / "sources"

# Expected M2 extractor per golden fixture source directory (C8, §4.3).
EXPECTED_BY_DIRECTORY: dict[str, str | None] = {
    "01-parallel-distill": "tsv@0.1.0",
    "02-educational-direct": "tsv@0.1.0",
    "03-wordlist": "tsv@0.1.0",
    "04-igt": None,
    "05-monolingual": "plain_lines@0.1.0",
}


def test_default_extractor_table() -> None:
    seen: set[str] = set()
    for directory in sorted(FIXTURE_SOURCES.iterdir()):
        manifest = yaml.safe_load((directory / "manifest.yaml").read_text(encoding="utf-8"))
        source_type = SourceType(manifest["source_type"])
        for obj in manifest["objects"]:
            seen.add(directory.name)
            got = default_extractor_for(source_type, obj["media_type"])
            assert got == EXPECTED_BY_DIRECTORY[directory.name], directory.name
    assert seen == set(EXPECTED_BY_DIRECTORY)


def test_default_extractor_media_type_defaults() -> None:
    assert default_extractor_for(SourceType.PUBLICATION, "text/x-usfm") == "usfm@0.1.0"
    assert default_extractor_for(SourceType.OTHER, "text/x-usfm") == "usfm@0.1.0"
    assert default_extractor_for(SourceType.MONOLINGUAL_TEXT, "application/pdf") is None
    assert default_extractor_for(SourceType.DICTIONARY, "text/plain") is None


def test_default_extractor_skips_igt_audio_and_video() -> None:
    assert default_extractor_for(SourceType.IGT, "text/plain") is None
    assert default_extractor_for(SourceType.IGT, "text/tab-separated-values") is None
    assert default_extractor_for(SourceType.AUDIO, "text/plain") is None
    assert default_extractor_for(SourceType.VIDEO, "text/x-usfm") is None
