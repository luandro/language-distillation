"""OpenAlex scholarly graph spider for open access linguistic research."""

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


class OpenAlexSpider(BaseSpider):
    """Searches the OpenAlex 250M+ scholarly works graph for linguistic papers and theses."""

    spider_id = "openalex"
    name = "OpenAlex Global Scholarly Graph"
    API_URL = "https://api.openalex.org/works"

    def __init__(self, user_agent_email: str = "linguistics-research@vale-javari.org"):
        self.user_agent = f"Mozilla/5.0 (mailto:{user_agent_email})"

    def search(self, target: HarvesterTarget, limit: int = 20) -> list[DiscoveredResource]:
        """Search OpenAlex for academic works on target language."""
        query = f"{target.language_name} {target.family}".strip()
        params = {
            "search": query,
            "per_page": str(min(limit, 50)),
        }
        url = f"{self.API_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        resources: list[DiscoveredResource] = []
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return resources

        results = data.get("results", [])
        for work in results:
            title = work.get("title") or "Untitled Work"
            oa_dict = work.get("open_access", {}) or {}
            oa_url = oa_dict.get("oa_url")
            doi = work.get("doi") or ""
            landing_url = work.get("primary_location", {}).get("landing_page_url") or doi or oa_url
            if not landing_url:
                continue

            # Generate deterministic source_id
            clean_id = work.get("id", "").split("/")[-1].lower()
            source_id = f"openalex_{clean_id}"

            authorships = work.get("authorships", []) or []
            authors = [
                a.get("author", {}).get("display_name", "")
                for a in authorships
                if a.get("author", {}).get("display_name")
            ]
            author_str = "; ".join(authors) if authors else None
            year = work.get("publication_year")

            # Determine policy
            is_oa = oa_dict.get("is_oa", False)
            policy = HarvestPolicy.PERMISSIVE_ACADEMIC if is_oa else HarvestPolicy.DISTILL_ONLY

            # Detect mentioned sister languages in title / abstract
            related = []
            abstract_blob = work.get("abstract_inverted_index")
            combined_text = (title + " " + (abstract_blob and str(abstract_blob) or "")).lower()
            synonyms_map = {
                "mcf": ["mcf", "matses", "matsés", "mayoruna"],
                "cul": ["cul", "culina", "kulina", "madija"],
                "tca": ["tca", "tikuna", "ticuna"],
                "kax": ["kax", "kaxinawá", "kaxinawa", "huni kuin"],
                "shn": ["shn", "shipibo", "conibo"],
            }
            for sister in target.sister_languages:
                aliases = synonyms_map.get(sister.lower(), [sister.lower()])
                if any(alias in combined_text for alias in aliases):
                    related.append(sister)

            resources.append(
                DiscoveredResource(
                    source_id=source_id,
                    language_code=target.iso639_3,
                    glottocode=target.glottocode,
                    title=title,
                    author=author_str,
                    year=year,
                    repository_id=self.spider_id,
                    url=landing_url,
                    download_url=oa_url,
                    policy=policy,
                    status=HarvestStatus.INDEXED,
                    related_languages=related,
                    features=["scholarly_paper", "openalex"],
                    metadata={
                        "openalex_id": work.get("id"),
                        "doi": doi,
                        "is_oa": is_oa,
                        "type": work.get("type"),
                        "cited_by_count": work.get("cited_by_count", 0),
                    },
                )
            )

        return resources
