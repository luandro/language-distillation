"""WP5.0 (C-1) contract tests: the M4 lexical and review models are schema-exported.

The JSON Schemas in `schemas/` are the serialized contract for every persisted
`SCHEMA_MODELS` member. These tests guard that the M4 models (`concept`, `lexeme`,
`form-lexeme-link`, `sense`, `review-task`, `review-decision`) joined the registry
and that the committed files match generated output byte for byte.
"""

import json
from pathlib import Path

from langpipe.schemas.generate import check, render_schema
from langpipe.schemas.registry import SCHEMA_MODELS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas"

M4_SCHEMA_NAMES = (
    "concept",
    "lexeme",
    "form-lexeme-link",
    "sense",
    "review-task",
    "review-decision",
)


def test_m4_lexical_and_review_models_are_schema_exported() -> None:
    names = {model.SCHEMA_NAME for model in SCHEMA_MODELS}
    assert set(M4_SCHEMA_NAMES) <= names


def test_m4_schema_files_are_committed_and_drift_free() -> None:
    for name in M4_SCHEMA_NAMES:
        path = SCHEMA_DIR / f"{name}.v1.schema.json"
        assert path.is_file(), f"missing committed schema: {path.name}"
    assert check(SCHEMA_DIR) == []


def test_lexeme_schema_keeps_register_property() -> None:
    # `register` is a persisted contract (database column, JSON key, golden snapshot);
    # its JSON Schema property must survive the C-3 warning-filter work unchanged.
    lexeme = next(model for model in SCHEMA_MODELS if model.SCHEMA_NAME == "lexeme")
    document = json.loads(render_schema(lexeme))
    assert "register" in document["properties"]
