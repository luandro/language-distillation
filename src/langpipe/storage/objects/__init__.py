"""Immutable content-addressed object stores (raw sources and artifacts)."""

from langpipe.storage.objects.base import ContentStore, StoredObject
from langpipe.storage.objects.local import LocalContentStore

__all__ = ["ContentStore", "LocalContentStore", "StoredObject"]
