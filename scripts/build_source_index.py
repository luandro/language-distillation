#!/usr/bin/env python3
"""Generate ``var/exports/source_index.generated.json`` from registered sources.

The generated index maps a provenance prefix to the trace ids a downstream consumer needs:
``{prefix: {"source_id", "policy_id", "run_id"}}``, where ``run_id`` is the source's
registration run and ``policy_id`` is the persisted ``SourcePolicy`` row it points at.
ADR-0025: these ids are traceability, never authorization.

Read-only against the database. The committed ``var/exports/source_index.json`` is never
read or overwritten; this script only writes the ``.generated.json`` sibling. The
prefix-to-source-key table is explicit on purpose: a new provenance prefix is a reviewable
change here, not something inferred from filenames.

Exit codes: 0 on success, 1 when any mapped source key is absent from the store (the
missing keys are named on stderr), 2 for a store/CLI error reported by ``langpipe``.
"""

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from langpipe.app_context import build_context
from langpipe.config.settings import Settings
from langpipe.domain.errors import LangpipeError

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "var" / "exports" / "source_index.generated.json"

# Provenance prefix written on derived rows -> registered source key.
PREFIX_SOURCE_KEYS: Mapping[str, str] = {
    "corpus:": "scriptureearth-mzr",
    "harvested:zenodo_1008779_cesarino_marubo_2017_parallel": "cesarino-marubo-2017-death-path",
    "harvested:cesarino_2018_wenia_parallel": "wenia-2018",
    "harvested:costa_2002_parallel": "costa-2002-ergatividade-cindida",
}


class MissingSources(LookupError):
    """One or more mapped source keys are not registered in the store."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        super().__init__(", ".join(keys))
        self.keys = keys


@dataclass(frozen=True)
class RegisteredSource:
    """The three trace ids the index needs from one source row."""

    source_id: str
    policy_id: str
    registration_run_id: str


def build_source_index(
    sources: Mapping[str, RegisteredSource],
) -> dict[str, dict[str, str]]:
    """Pure mapping from ``{source_key: record}`` to the sorted prefix index.

    Raises ``MissingSources`` when a mapped key has no record, so the caller can fail
    before writing anything.
    """
    missing = tuple(sorted({key for key in PREFIX_SOURCE_KEYS.values() if key not in sources}))
    if missing:
        raise MissingSources(missing)
    return {
        prefix: {
            "source_id": sources[key].source_id,
            "policy_id": sources[key].policy_id,
            "run_id": sources[key].registration_run_id,
        }
        for prefix, key in sorted(PREFIX_SOURCE_KEYS.items())
    }


def render(index: Mapping[str, Mapping[str, str]]) -> str:
    """Deterministic JSON text: sorted keys, stable indent, trailing newline."""
    return json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load_sources(wanted_keys: tuple[str, ...]) -> tuple[dict[str, RegisteredSource], list[str]]:
    """Read the mapped sources from the store. Returns records plus missing keys."""
    repo = build_context(Settings.from_env()).repo
    records: dict[str, RegisteredSource] = {}
    missing: list[str] = []
    for key in wanted_keys:
        source = repo.find_source_by_key(key)
        if source is None:
            missing.append(key)
            continue
        records[key] = RegisteredSource(
            source_id=source.id,
            policy_id=source.policy_id,
            registration_run_id=source.registration_run_id,
        )
    return records, sorted(missing)


def main() -> int:
    wanted = tuple(sorted(set(PREFIX_SOURCE_KEYS.values())))
    try:
        sources, missing = load_sources(wanted)
    except LangpipeError as error:
        print(f"error={type(error).__name__}", file=sys.stderr)
        return 2
    if missing:
        for key in missing:
            print(f"missing_source_key={key}", file=sys.stderr)
        return 1
    index = build_source_index(sources)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render(index), encoding="utf-8")
    print(f"output={OUTPUT_PATH.relative_to(REPO_ROOT)} prefixes={len(index)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
