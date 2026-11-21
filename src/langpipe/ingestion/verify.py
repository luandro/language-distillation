"""Integrity check of stored raw objects against the sha256 recorded at registration."""

from dataclasses import dataclass
from typing import Literal

from langpipe.app_context import AppContext
from langpipe.domain.errors import HashMismatch, ObjectMissing
from langpipe.domain.models.source import SourceObject
from langpipe.ingestion.ingest import resolve_source


@dataclass(frozen=True)
class ObjectCheck:
    source_object_id: str
    sha256: str
    status: Literal["ok", "missing", "mismatch", "not_ingested"]


def verify_source(ctx: AppContext, source_ref: str) -> list[ObjectCheck]:
    """Check every object of a source. Per-object store problems are reported, not raised."""
    source = resolve_source(ctx, source_ref)
    return [
        ObjectCheck(
            source_object_id=obj.id,
            sha256=obj.sha256,
            status=_status(ctx, obj),
        )
        for obj in ctx.repo.list_source_objects(source.id)
    ]


def _status(
    ctx: AppContext, obj: SourceObject
) -> Literal["ok", "missing", "mismatch", "not_ingested"]:
    if ctx.repo.get_raw_blob(obj.sha256) is None:
        return "not_ingested"
    try:
        ctx.raw_store.verify(obj.sha256)
    except ObjectMissing:
        return "missing"
    except HashMismatch:
        return "mismatch"
    except OSError:
        # An unreadable stored file cannot be shown to match; it is reported as missing.
        return "missing"
    return "ok"
