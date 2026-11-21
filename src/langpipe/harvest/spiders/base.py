"""Base spider protocol for linguistic resource harvesting."""

from abc import ABC, abstractmethod

from langpipe.harvest.models import DiscoveredResource, HarvesterTarget


class BaseSpider(ABC):
    """Abstract spider for searching a specific repository or web API."""

    spider_id: str
    name: str

    @abstractmethod
    def search(self, target: HarvesterTarget, limit: int = 20) -> list[DiscoveredResource]:
        """Search the repository for documents related to the target language."""
        pass
