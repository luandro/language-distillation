"""Offline tests for scripts/lang_research.py (identifier loading, query rendering, dedupe)."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "lang_research.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lang_research", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lr = _load()


def test_load_identity_reads_profile_and_registry(tmp_path: Path) -> None:
    (tmp_path / "docs" / "languages").mkdir(parents=True)
    (tmp_path / "docs" / "research").mkdir(parents=True)
    (tmp_path / "docs" / "languages" / "mpu.md").write_text(
        "# Matis (mpu)\n\n```yaml\nname: Matis\niso639_3: mpu\nfamily: Pano\n```\n",
        encoding="utf-8",
    )
    registry = {
        "language_profiles": {
            "mpu": {"query_aliases": ["Matís", "Matis"], "glottocode": "mati1255"}
        }
    }
    (tmp_path / "docs" / "research" / "universal_sources_registry.json").write_text(
        json.dumps(registry), encoding="utf-8"
    )

    identity = lr.load_identity("mpu", repo_root=tmp_path)

    assert identity.name == "Matis"
    assert identity.family == "Pano"
    assert identity.glottolog == "mati1255"
    # alias equal to the name (case-insensitive) is not duplicated
    assert identity.primary_names == ["Matis", "Matís"]


def test_render_queries_covers_requested_lanes() -> None:
    identity = lr.LanguageIdentity(iso="xor", name="Korubo", family="Pano")

    queries = lr.render_queries(identity, ["archives", "parallel"])

    assert len(queries) == len(lr.LANE_TEMPLATES["archives"]) + len(lr.LANE_TEMPLATES["parallel"])
    assert all(lane in {"archives", "parallel"} for lane, _ in queries)
    assert any("AILLA" in query for _, query in queries)
    assert all("{name}" not in query and "{iso}" not in query for _, query in queries)


def test_render_queries_rejects_unknown_lane() -> None:
    identity = lr.LanguageIdentity(iso="mzr", name="Marúbo")

    try:
        lr.render_queries(identity, ["nope"])
    except SystemExit as error:
        assert "unknown lane" in str(error)
    else:  # pragma: no cover - the assertion above must trigger
        raise AssertionError("unknown lane was accepted")


def test_normalize_url_dedupes_scheme_www_and_fragment() -> None:
    variants = [
        "https://www.example.org/a/b/",
        "http://example.org/a/b",
        "https://example.org/a/b#section",
    ]

    keys = {lr.normalize_url(url) for url in variants}

    assert keys == {"example.org/a/b"}


def test_merge_hits_keeps_best_lane_and_queries() -> None:
    hits = [
        (
            "academic",
            "q1",
            lr.SearchHit(url="https://www.example.org/a", title="A", snippet="s1"),
        ),
        ("archives", "q2", lr.SearchHit(url="http://example.org/a", title="", snippet="")),
        ("media", "q3", lr.SearchHit(url="https://other.example/b", title="B", snippet="s2")),
    ]

    merged = lr.merge_hits(hits)

    assert len(merged) == 2
    entry = merged["example.org/a"]
    assert entry["lanes"] == ["academic", "archives"]
    assert entry["queries"] == ["q1", "q2"]
    assert entry["title"] == "A"
    assert merged["other.example/b"]["title"] == "B"


def test_merge_hits_drops_non_http_urls() -> None:
    hits = [
        ("archives", "q", lr.SearchHit(url="/hdd/m0103/datasets/x", title="local")),
        ("archives", "q", lr.SearchHit(url="https://example.org/ok", title="ok")),
    ]

    merged = lr.merge_hits(hits)

    assert list(merged) == ["example.org/ok"]


def test_render_digest_marks_hits_unverified() -> None:
    import datetime

    identity = lr.LanguageIdentity(iso="mzr", name="Marúbo", family="Pano")
    merged = lr.merge_hits(
        [("academic", "q", lr.SearchHit(url="https://example.org/x", title="X", snippet="s"))]
    )

    digest = lr.render_digest(identity, merged, datetime.date(2026, 10, 18))

    assert "search-result evidence only" in digest
    assert "https://example.org/x" in digest
    assert "Total unique URLs: **1**" in digest
