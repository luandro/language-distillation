import getpass
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql+psycopg://langpipe:langpipe@localhost:55432/langpipe"


def _default_actor() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return "unknown"


def _value(source: Mapping[str, str], key: str, default: str) -> str:
    return source.get(key) or default


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    actor: str
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source: Mapping[str, str] = os.environ if env is None else env
        return cls(
            database_url=_value(source, "LANGPIPE_DATABASE_URL", DEFAULT_DATABASE_URL),
            data_dir=Path(_value(source, "LANGPIPE_DATA_DIR", "var")),
            actor=_value(source, "LANGPIPE_ACTOR", _default_actor()),
            log_level=_value(source, "LANGPIPE_LOG_LEVEL", "INFO"),
        )

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"
