#!/usr/bin/env bash
# Local CI gate for M1+M2+M3: lint, types, schema drift, migrations and the full test pass.
# The pytest call passes no -m override, so pyproject addopts keep 'realdata' and
# 'native_alignment' deselected (guarded by tests/unit/test_ci_script.py); real-data
# and native tests are opt-in, compiler-free CI baseline.
set -euo pipefail

cd "$(dirname "$0")/.."

export LANGPIPE_TEST_DATABASE_URL="${LANGPIPE_TEST_DATABASE_URL:-postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe_test}"

uv sync --frozen

# Refuse to migrate anything but a *_test database, before any database work.
# Parsed with SQLAlchemy; the message never echoes the URL, which may hold credentials.
uv run python - <<'PY'
import os
import sys

from sqlalchemy.engine import make_url

try:
    url = make_url(os.environ["LANGPIPE_TEST_DATABASE_URL"])
except Exception:
    url = None
if (
    url is None
    or not (url.database or "").endswith("_test")
    or any(key in url.query for key in ("dbname", "database", "service"))
):
    sys.exit(
        "refusing to migrate: LANGPIPE_TEST_DATABASE_URL must name a database ending in _test "
        "and must not use dbname, database or service query overrides"
    )
PY

# Lint gate, in two tiers.
#
# Blocking: src/ and tests/ are the code this gate owns. They must stay clean.
uv run ruff check src tests
uv run ruff format --check src tests
#
# Non-blocking: everything else. notebooks/, scripts/, ops/ and deploy/ still carry known
# findings, and notebooks/ are working documents that drift by nature. Reporting them on every
# run keeps the debt visible and stops it growing silently, without a dirty notebook failing a
# commit that never touched it. Tracked on tsk #273.
if ! uv run ruff check . --exclude src --exclude tests; then
    echo "ci: NOTE - non-blocking ruff findings outside src/ and tests/ (tsk #273)" >&2
fi
if ! uv run ruff format --check . --exclude src --exclude tests; then
    echo "ci: NOTE - non-blocking ruff-format findings outside src/ and tests/ (tsk #273)" >&2
fi

uv run mypy src
uv run python -m langpipe.schemas check
docker compose up -d --wait db
uv run alembic -x url="$LANGPIPE_TEST_DATABASE_URL" upgrade head
LANGPIPE_REQUIRE_POSTGRES=1 uv run pytest -q  # unit + contract + service + golden + integration
