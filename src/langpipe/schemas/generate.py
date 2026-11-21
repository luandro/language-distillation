import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from langpipe.domain.models.base import DomainModel
from langpipe.schemas.registry import SCHEMA_MODELS

SCHEMA_SUFFIX = ".schema.json"
DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"
_JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _schema_name(model: type[DomainModel]) -> str:
    name = model.SCHEMA_NAME
    if name is None:
        raise ValueError(f"{model.__name__} is not a schema-exported model")
    return name


def schema_filename(model: type[DomainModel]) -> str:
    return f"{_schema_name(model)}.v{model.SCHEMA_VERSION}{SCHEMA_SUFFIX}"


def render_schema(model: type[DomainModel]) -> str:
    name = _schema_name(model)
    version = model.SCHEMA_VERSION
    schema = model.model_json_schema(mode="serialization")
    schema["$id"] = f"urn:langpipe:schema:{name}:{version}"
    schema["$schema"] = _JSON_SCHEMA_DIALECT
    schema["x-schema-name"] = name
    schema["x-schema-version"] = version
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate(schema_dir: Path) -> list[Path]:
    # Writes every schema file and removes nothing; stale files are reported by check().
    schema_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for model in SCHEMA_MODELS:
        path = schema_dir / schema_filename(model)
        path.write_text(render_schema(model), encoding="utf-8")
        written.append(path)
    return written


def check(schema_dir: Path) -> list[str]:
    expected = {schema_filename(model): render_schema(model) for model in SCHEMA_MODELS}
    present: set[str] = set()
    if schema_dir.is_dir():
        present = {path.name for path in schema_dir.glob(f"*{SCHEMA_SUFFIX}")}
    drift = [
        name
        for name, content in expected.items()
        if name not in present or (schema_dir / name).read_text(encoding="utf-8") != content
    ]
    drift.extend(sorted(present - expected.keys()))
    return sorted(drift)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m langpipe.schemas")
    parser.add_argument("command", choices=["generate", "check"])
    parser.add_argument("--dir", type=Path, default=DEFAULT_SCHEMA_DIR, dest="schema_dir")
    args = parser.parse_args(argv)
    if args.command == "generate":
        written = generate(args.schema_dir)
        print(f"wrote {len(written)} schema files to {args.schema_dir}")
        return 0
    drift = check(args.schema_dir)
    if drift:
        for name in drift:
            print(f"schema drift: {name}", file=sys.stderr)
        return 1
    print(f"schemas up to date in {args.schema_dir}")
    return 0
