"""Curt Nimuendajú Digital Library (etnolinguistica.org) spider."""

import re
import urllib.parse
import urllib.request

from langpipe.harvest.models import (
    DiscoveredResource,
    HarvesterTarget,
    HarvestPolicy,
    HarvestStatus,
)
from langpipe.harvest.spiders.base import BaseSpider


class EtnolinguisticaSpider(BaseSpider):
    """Searches the Curt Nimuendajú Digital Library for South American indigenous language
    assets."""

    spider_id = "etnolinguistica"
    name = "Biblioteca Digital Curt Nimuendajú / Etnolinguistica.org"
    SEARCH_URL = "http://www.etnolinguistica.org/search:site/q/{query}"

    def __init__(self) -> None:
        self.user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"

    def search(self, target: HarvesterTarget, limit: int = 10) -> list[DiscoveredResource]:
        """Query Curt Nimuendaju digital library for documents on target language."""
        query = urllib.parse.quote(target.language_name.lower())
        url = self.SEARCH_URL.format(query=query)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        resources: list[DiscoveredResource] = []
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return resources

        # Extract links matching biblio, artigo, livro, tese
        links = set(re.findall(r'href="(\/(?:biblio|artigo|livro|tese):[a-z0-9\-_]+)"', html))
        for rel_link in sorted(list(links))[:limit]:
            landing_url = f"http://www.etnolinguistica.org{rel_link}"
            slug = rel_link.lstrip("/").replace(":", "_").replace("-", "_")
            source_id = f"etnolinguistica_{slug}"

            # Guess author and year from slug like biblio:ferreira-2026-memorias
            parts = rel_link.split(":")[-1].split("-")
            author = parts[0].capitalize() if parts else None
            year = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

            resources.append(
                DiscoveredResource(
                    source_id=source_id,
                    language_code=target.iso639_3,
                    glottocode=target.glottocode,
                    title=f"Curt Nimuendajú Document: {rel_link.split(':')[-1]}",
                    author=author,
                    year=year,
                    repository_id=self.spider_id,
                    url=landing_url,
                    policy=HarvestPolicy.DISTILL_ONLY,
                    status=HarvestStatus.INDEXED,
                    features=["rare_grammar", "amazonian_linguistics", "nimuendaju"],
                    metadata={"slug": rel_link},
                )
            )

        return resources
