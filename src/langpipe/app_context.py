from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from langpipe.config.revision import code_revision
from langpipe.config.settings import Settings
from langpipe.domain.ids import IdFactory, new_id
from langpipe.domain.models.base import UTC_NOW
from langpipe.storage.db.engine import make_engine
from langpipe.storage.db.repository import PostgresRepository
from langpipe.storage.objects.base import ContentStore
from langpipe.storage.objects.local import LocalContentStore
from langpipe.storage.repository import Repository


@dataclass(frozen=True)
class AppContext:
    repo: Repository
    raw_store: ContentStore
    artifact_store: ContentStore
    clock: Callable[[], datetime]
    new_id: IdFactory
    actor: str
    code_revision: str


def build_context(settings: Settings) -> AppContext:
    return AppContext(
        repo=PostgresRepository(make_engine(settings.database_url)),
        raw_store=LocalContentStore(settings.raw_dir),
        artifact_store=LocalContentStore(settings.artifact_dir),
        clock=UTC_NOW,
        new_id=new_id,
        actor=settings.actor,
        code_revision=code_revision(),
    )
