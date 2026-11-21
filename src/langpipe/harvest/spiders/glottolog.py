"""Glottolog languoid and typology metadata spider."""

import json
import urllib.request

from langpipe.harvest.models import (
    DiscoveredResource,
    HarvesterTarget,
    HarvestPolicy,
    HarvestStatus,
)
from langpipe.harvest.spiders.base import BaseSpider


class GlottologSpider(BaseSpider):
    """Fetches languoid structure, family tree, coordinates, and bibliography from Glottolog."""

    spider_id = "glottolog"
    name = "Glottolog Language Reference"
    API_URL_TEMPLATE = "https://glottolog.org/resource/languoid/id/{glottocode}.json"

    def __init__(self) -> None:
        self.user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"

    def search(self, target: HarvesterTarget, limit: int = 5) -> list[DiscoveredResource]:
        """Fetch Glottolog metadata for the target languoid."""
        if not target.glottocode:
            return []

        url = self.API_URL_TEMPLATE.format(glottocode=target.glottocode)
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []

        source_id = f"glottolog_{target.glottocode}"
        classification = data.get("classification", []) or []
        family_names = [
            c.get("name") for c in classification if isinstance(c, dict) and c.get("name")
        ]

        resource = DiscoveredResource(
            source_id=source_id,
            language_code=target.iso639_3,
            glottocode=target.glottocode,
            title=f"Glottolog Languoid Reference: {data.get('name', target.language_name)}",
            author="Hammarström, Harald & Forkel, Robert & Haspelmath, Martin & Bank, Sebastian",
            year=2024,
            repository_id=self.spider_id,
            url=f"https://glottolog.org/resource/languoid/id/{target.glottocode}",
            download_url=url,
            policy=HarvestPolicy.PERMISSIVE_ACADEMIC,
            status=HarvestStatus.INDEXED,
            features=["typology", "classification", "family_tree", "geocoordinates"],
            metadata={
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "macroareas": data.get("macroareas", []),
                "classification_tree": family_names,
                "child_dialect_count": data.get("child_dialect_count", 0),
            },
        )

        return [resource]
