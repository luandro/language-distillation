"""Wikipedia MediaWiki external links and bibliography spider."""

import json
import urllib.parse
import urllib.request

from langpipe.harvest.models import (
    DiscoveredResource,
    HarvesterTarget,
    HarvestPolicy,
    HarvestStatus,
)
from langpipe.harvest.spiders.base import BaseSpider


class WikipediaSpider(BaseSpider):
    """Mines Wikipedia articles for external repository links, SIL archives, and bibliography."""

    spider_id = "wikipedia"
    name = "Wikipedia MediaWiki Reference Graph"
    API_URL = "https://pt.wikipedia.org/w/api.php"

    def __init__(self) -> None:
        self.user_agent = "Mozilla/5.0 (LinguisticResearchBot/1.0; mailto:dev@coolab.org)"

    def search(self, target: HarvesterTarget, limit: int = 15) -> list[DiscoveredResource]:
        """Query MediaWiki API for external links and bibliographic references on target
        language."""
        page_titles = [
            f"Língua_{target.language_name.lower()}",
            f"{target.language_name.capitalize()}",
            f"Língua_{target.language_name.capitalize()}",
        ]

        resources: list[DiscoveredResource] = []
        found_urls = set()

        for page in page_titles:
            params = {
                "action": "parse",
                "page": page,
                "prop": "externallinks|sections",
                "format": "json",
            }
            url = f"{self.API_URL}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                continue

            links = data.get("parse", {}).get("externallinks", []) or []
            for link in links:
                if link in found_urls:
                    continue
                found_urls.add(link)

                # Filter out generic social media or Wikipedia internal links
                if any(
                    bad in link for bad in ["vimeo", "youtube", "facebook", "twitter", "instagram"]
                ):
                    continue

                source_id = f"wiki_ext_{abs(hash(link)) % 10000000}"
                features = ["wikipedia_external_ref"]
                if ".pdf" in link.lower():
                    features.append("direct_pdf")
                if (
                    "sil.org" in link.lower()
                    or "etnolinguistica" in link.lower()
                    or "cultura.gob" in link.lower()
                ):
                    features.append("institutional_repository")

                resources.append(
                    DiscoveredResource(
                        source_id=source_id,
                        language_code=target.iso639_3,
                        glottocode=target.glottocode,
                        title=f"Curated Reference: {link.split('/')[-1] or link}",
                        repository_id=self.spider_id,
                        url=link,
                        download_url=link if ".pdf" in link.lower() else None,
                        policy=(
                            HarvestPolicy.PERMISSIVE_ACADEMIC
                            if ".pdf" in link.lower()
                            else HarvestPolicy.DISTILL_ONLY
                        ),
                        status=HarvestStatus.INDEXED,
                        features=features,
                        metadata={"referring_page": page},
                    )
                )
                if len(resources) >= limit:
                    break

            if resources:
                break

        return resources
