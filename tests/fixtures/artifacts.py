"""Guards for tests that need locally built artifacts.

``exports/`` and ``var/`` are gitignored: they embed third-party text this repository is not
licensed to redistribute, so every export is a local build product. Tests that exercise the
built lexicon or the built web dictionary must say so instead of failing with a
``FileNotFoundError`` on a bare clone. Build the artifacts first:

    uv run langpipe lexicon export --language mzr   # writes exports/mzr/dictionary.json
    uv run langpipe lexicon web --language mzr      # writes exports/web/dictionary.js

Skipping (rather than deselecting) keeps these tests running in the maintainer's environment,
where the artifacts exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

BUILT_LEXICON = REPO_ROOT / "exports" / "mzr" / "dictionary.json"
BUILT_WEB_DATA = REPO_ROOT / "exports" / "web" / "dictionary.js"
BUILT_WEB_DB = REPO_ROOT / "exports" / "web" / "db_data.js"

requires_built_lexicon = pytest.mark.skipif(
    not BUILT_LEXICON.exists(),
    reason=(
        f"needs the built Marúbo lexicon ({BUILT_LEXICON.relative_to(REPO_ROOT)}); "
        "build it with `langpipe lexicon`"
    ),
)

requires_built_web_data = pytest.mark.skipif(
    not (BUILT_WEB_DATA.exists() and BUILT_WEB_DB.exists()),
    reason=(
        "needs the built web dictionary data (exports/web/dictionary.js, db_data.js); "
        "build it with `langpipe lexicon`"
    ),
)
