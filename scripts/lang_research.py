#!/usr/bin/env python3
"""Language-agnostic resource-search harness built on DeepSeek web search.

Given a language ISO code, this renders the same lane query set the manual surveys used
(catalogues, academic literature, archives, parallel corpora, living platforms, government
school materials, NLP datasets) and runs them through DeepSeek search, then writes a
deduplicated, sourced digest for that language.

It reads canonical identifiers from the repo when available:

- ``docs/languages/<iso>.md`` YAML block (``name``, ``iso639_3``, ``family``);
- ``docs/research/universal_sources_registry.json`` ``language_profiles`` entry
  (``query_aliases``, ``sister_languages``, ``glottocode``).

Every hit is recorded with the query that produced it and a verification status of ``[U]``
(search snippet only — nothing was fetched). Fetching a cited URL before trusting it stays
the caller's job; see ``docs/research/pano-survey-2026-10/FINDINGS.md`` §method.

Examples
--------

    # one language, default lanes, writes docs/research/mpu-research-2026-10-18/
    uv run python scripts/lang_research.py --iso mpu

    # explicit identity when no profile exists yet, limited lanes
    uv run python scripts/lang_research.py --iso xor --name Korubo --family Pano \\
        --lanes academic,archives,parallel

    # see the rendered queries without calling the API
    uv run python scripts/lang_research.py --iso mcf --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from deepseek_search import (  # noqa: E402
    SearchHit,
    announce_billing_status,
    confirm_billing,
    server_tool_search,
)

LANE_TEMPLATES: dict[str, list[str]] = {
    "catalogues": [
        "{name} {family} CLDF wordlist lexibank",
        "{name} language Swadesh wordlist concepts",
        "{name} {family} Glottolog bibliography",
        "{name} {iso} ASJP Phonobank typology database",
    ],
    "academic": [
        "{name} language grammar thesis dissertation pdf",
        "{name} {family} phonology morphology article",
        "{name} indigenous language documentation fieldwork",
        "{name} dicionário OR vocabulário OR léxico",
    ],
    "archives": [
        "{name} AILLA OR ELAR OR PARADISEC language archive",
        "{name} ethnographic collection recordings museum",
        "{name} audio recordings transcription archive",
        "{name} language documentation corpus deposit",
    ],
    "parallel": [
        "{name} Bible translation USFM parallel corpus",
        "{name} ScriptureEarth OR eBible OR YouVersion",
        "{name} bilingual text parallel sentences {family}",
        "{name} bilingual education book pdf",
    ],
    "media": [
        "{name} YouTube channel language videos",
        "{name} podcast OR radio interview indigenous",
        "{name} language TikTok OR Instagram OR Facebook",
    ],
    "government": [
        '"{name}" cartilha OR "livro didático" OR alfabetização pdf',
        "{name} indigenous school material ministry of education",
        "{name} FUNAI OR SESAI OR secretaria de educação material",
        "{name} health booklet bilingual pdf",
    ],
    "nlp": [
        "{name} dataset huggingface OR kaggle OR zenodo",
        "{name} automatic speech recognition text-to-speech model",
        "{name} machine translation {family} corpus",
        "{name} treebank OR POS tagger OR morphological analyzer",
    ],
}

_LANG_PROFILE_RE = re.compile(r"```yaml\n(?P<body>.*?)```", re.S)
_YAML_LINE_RE = re.compile(r"^(?P<key>[a-z0-9_]+):\s*(?P<value>.+)$")


@dataclass
class LanguageIdentity:
    """Identifiers used to build queries."""

    iso: str
    name: str
    family: str = ""
    glottolog: str = ""
    aliases: list[str] = field(default_factory=list)
    sisters: list[str] = field(default_factory=list)

    @property
    def primary_names(self) -> list[str]:
        """Names to query: the primary name plus aliases, de-duplicated case-insensitively."""
        seen: set[str] = set()
        names: list[str] = []
        for candidate in [self.name, *self.aliases]:
            key = candidate.strip().lower()
            if key and key not in seen:
                seen.add(key)
                names.append(candidate.strip())
        return names


def load_identity(
    iso: str,
    name: str = "",
    family: str = "",
    aliases: list[str] | None = None,
    repo_root: Path = REPO_ROOT,
) -> LanguageIdentity:
    """Merge explicit CLI identity with the repo's language profile and registry."""
    identity = LanguageIdentity(iso=iso, name=name, family=family, aliases=list(aliases or []))
    profile = repo_root / "docs" / "languages" / f"{iso}.md"
    if profile.exists():
        text = profile.read_text(encoding="utf-8")
        heading = re.search(r"^#\s+(?P<title>[^\n]+)", text, re.M)
        if heading and not identity.name:
            title = re.sub(r"\([a-z0-9]{3}\)", "", heading.group("title"))
            title = re.sub(r"\bLanguage Profile\b", "", title, flags=re.I)
            identity.name = title.strip() or identity.name
        family_field = re.search(r"\*\*Family:\*\*\s*(?P<family>[^\n]+)", text)
        if family_field and not identity.family:
            identity.family = family_field.group("family").strip()
        match = _LANG_PROFILE_RE.search(text)
        if match:
            for line in match.group("body").splitlines():
                parsed = _YAML_LINE_RE.match(line.strip())
                if not parsed:
                    continue
                key, value = parsed.group("key"), parsed.group("value").strip()
                if key == "name" and not identity.name:
                    identity.name = value
                elif key in {"iso639_3", "glottocode"}:
                    identity.glottolog = value if key == "glottocode" else identity.glottolog
                elif key == "family" and not identity.family:
                    identity.family = value
    registry = repo_root / "docs" / "research" / "universal_sources_registry.json"
    if registry.exists():
        try:
            payload = json.loads(registry.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        entry: dict[str, Any] = (payload.get("language_profiles") or {}).get(iso, {})
        if isinstance(entry, dict):
            if not identity.name:
                identity.name = str(entry.get("name") or "")
            if not identity.family:
                identity.family = str(entry.get("family") or "")
            if not identity.glottolog:
                identity.glottolog = str(entry.get("glottocode") or "")
            identity.aliases.extend(str(alias) for alias in entry.get("query_aliases") or [])
            identity.sisters.extend(str(sister) for sister in entry.get("sister_languages") or [])
    if not identity.name:
        identity.name = iso.upper()
    return identity


def render_queries(identity: LanguageIdentity, lanes: list[str]) -> list[tuple[str, str]]:
    """Render ``(lane, query)`` pairs for the requested lanes."""
    values = {
        "name": identity.name,
        "iso": identity.iso,
        "family": identity.family or "language family",
    }
    queries: list[tuple[str, str]] = []
    for lane in lanes:
        if lane not in LANE_TEMPLATES:
            raise SystemExit(f"unknown lane {lane!r}; choose from {sorted(LANE_TEMPLATES)}")
        for template in LANE_TEMPLATES[lane]:
            for query_name in identity.primary_names:
                values["name"] = query_name
                queries.append((lane, template.format(**values)))
    return queries


def normalize_url(url: str) -> str:
    """Canonical URL key for deduplication: drop scheme, www, trailing slash and fragment."""
    key = re.sub(r"^https?://", "", url.strip(), flags=re.I)
    key = re.sub(r"^www\.", "", key, flags=re.I)
    key = key.split("#", 1)[0].rstrip("/")
    return key.lower()


def merge_hits(
    hits: list[tuple[str, str, SearchHit]],
) -> dict[str, dict[str, Any]]:
    """Group hits by normalized URL, keeping the best rank and every producing query."""
    merged: dict[str, dict[str, Any]] = {}
    for lane, query, hit in hits:
        if not hit.url.lower().startswith(("http://", "https://")):
            continue
        key = normalize_url(hit.url)
        if not key:
            continue
        entry = merged.setdefault(
            key,
            {
                "url": hit.url,
                "title": hit.title,
                "snippet": hit.snippet,
                "lanes": [],
                "queries": [],
                "best_rank": 10_000,
            },
        )
        if lane not in entry["lanes"]:
            entry["lanes"].append(lane)
        if query not in entry["queries"]:
            entry["queries"].append(query)
        if not entry["title"] and hit.title:
            entry["title"] = hit.title
        if not entry["snippet"] and hit.snippet:
            entry["snippet"] = hit.snippet
    return merged


def render_digest(
    identity: LanguageIdentity, merged: dict[str, dict[str, Any]], survey_date: date
) -> str:
    """Render the merged hits as a markdown digest grouped by lane."""
    lines = [
        f"# {identity.name} (`{identity.iso}`) — resource search "
        f"({survey_date.isoformat()})",
        "",
        f"Generated by `scripts/lang_research.py` with DeepSeek search. Family: "
        f"{identity.family or 'unknown'}"
        + (f"; Glottolog: `{identity.glottolog}`" if identity.glottolog else "")
        + ".",
        "",
        "**Every URL here is search-result evidence only (`[U]`).** Nothing was fetched. A hit "
        "becomes a finding only after the page is loaded and its language coverage checked; "
        "search snippets routinely mislabel languages.",
        "",
    ]
    by_lane: dict[str, list[dict[str, Any]]] = {}
    for entry in merged.values():
        for lane in entry["lanes"]:
            by_lane.setdefault(lane, []).append(entry)
    for lane in ("catalogues", "academic", "archives", "parallel", "media", "government", "nlp"):
        entries = by_lane.get(lane)
        if not entries:
            continue
        lines.extend(
            [
                f"## {lane.title()}",
                "",
                "| # | Title | URL | Also seen in |",
                "|---|---|---|---|",
            ]
        )
        for index, entry in enumerate(sorted(entries, key=lambda item: str(item["url"])), start=1):
            title = str(entry["title"] or "").replace("|", "/")[:90]
            also = ", ".join(sorted(set(entry["lanes"]) - {lane}))
            lines.append(f"| {index} | {title} | {entry['url']} | {also} |")
        lines.append("")
    lines.append(f"Total unique URLs: **{len(merged)}**.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = argparse.ArgumentParser(description="Multi-lane language resource search (DeepSeek)")
    parser.add_argument("--iso", required=True, help="ISO 639-3 code, e.g. mpu")
    parser.add_argument("--name", default="", help="language name if no profile exists")
    parser.add_argument("--family", default="", help="language family if no profile exists")
    parser.add_argument(
        "--alias", action="append", default=[], help="extra query name (repeatable)"
    )
    parser.add_argument(
        "--lanes",
        default=",".join(LANE_TEMPLATES),
        help=f"comma-separated lanes from {sorted(LANE_TEMPLATES)}",
    )
    parser.add_argument("--count", type=int, default=8, help="results per query (1-10)")
    parser.add_argument(
        "--max-queries", type=int, default=0, help="cap queries (0 = all)"
    )
    parser.add_argument("--outdir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="print queries and exit")
    parser.add_argument(
        "--yes-paid",
        action="store_true",
        help="authorize billed requests after the free window without an interactive prompt",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.25, help="seconds between queries (QPS is 5)"
    )
    args = parser.parse_args(argv)

    identity = load_identity(args.iso, args.name, args.family, args.alias)
    lanes = [lane.strip() for lane in args.lanes.split(",") if lane.strip()]
    queries = render_queries(identity, lanes)
    if args.max_queries:
        queries = queries[: args.max_queries]
    if args.dry_run:
        for lane, query in queries:
            print(f"[{lane}] {query}")
        return 0

    announce_billing_status(len(queries))
    confirm_billing(len(queries), assume_yes=args.yes_paid)

    outdir = args.outdir or (
        REPO_ROOT / "docs" / "research" / f"{identity.iso}-research-{date.today().isoformat()}"
    )
    outdir.mkdir(parents=True, exist_ok=True)
    raw_hits: list[tuple[str, str, SearchHit]] = []
    for index, (lane, query) in enumerate(queries, start=1):
        try:
            report = server_tool_search(query, count=max(1, min(args.count, 10)))
        except Exception as error:  # noqa: BLE001 - one failed query must not end the sweep
            print(f"[{index}/{len(queries)}] {lane}: error {type(error).__name__}", file=sys.stderr)
            continue
        raw_hits.extend((lane, query, hit) for hit in report.hits)
        print(f"[{index}/{len(queries)}] {lane}: {len(report.hits)} hits — {query[:70]}")
        time.sleep(max(0.0, args.sleep))

    merged = merge_hits(raw_hits)
    (outdir / "hits.jsonl").write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in merged.values()) + "\n",
        encoding="utf-8",
    )
    digest = render_digest(identity, merged, date.today())
    (outdir / "FINDINGS-search.md").write_text(digest, encoding="utf-8")
    print(f"\n{len(merged)} unique URLs from {len(queries)} queries -> {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
