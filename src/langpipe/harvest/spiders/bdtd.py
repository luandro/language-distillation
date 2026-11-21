"""BDTD (Biblioteca Digital Brasileira de Teses e Dissertações) VuFind API spider."""

import json
import urllib.parse
import urllib.request
from typing import cast

from langpipe.harvest.models import (
    DiscoveredResource,
    HarvesterTarget,
    HarvestPolicy,
    HarvestStatus,
)
from langpipe.harvest.spiders.base import BaseSpider


class BdtdSpider(BaseSpider):
    """Searches Brazilian theses and dissertations on indigenous languages."""

    spider_id = "bdtd"
    name = "Biblioteca Digital Brasileira de Teses e Dissertações (IBICT)"
    API_URL = "https://bdtd.ibict.br/vufind/api/v1/search"

    def __init__(self) -> None:
        self.user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"

    def search(self, target: HarvesterTarget, limit: int = 20) -> list[DiscoveredResource]:
        """Query BDTD for academic theses regarding the target language."""
        query = f"{target.language_name} língua"
        params = {
            "lookfor": query,
            "type": "AllFields",
            "limit": str(min(limit, 50)),
        }
        url = f"{self.API_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        resources: list[DiscoveredResource] = []
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return resources

        records = data.get("records", []) or []
        for rec in records:
            title = rec.get("title") or "Tese/Dissertação"
            rec_id = rec.get("id") or ""
            source_id = f"bdtd_{rec_id.replace(':', '_')}"

            # Authors
            primary = rec.get("authors", {}).get("primary", {})
            author_str = (
                "; ".join(primary.keys()) if isinstance(primary, dict) and primary else None
            )

            # URLs and handles
            urls = rec.get("urls", []) or []
            # `rec` is decoded JSON (Any), so this ternary infers as `Any | str | None` while the
            # VuFind API always returns a string `url`; the containment test below needs `str`.
            landing_url = cast(
                str,
                urls[0].get("url")
                if urls and isinstance(urls[0], dict)
                else f"https://bdtd.ibict.br/vufind/Record/{rec_id}",
            )

            # Download URL: if DSpace bitstream handle, we link it
            download_url = None
            if "handle.net" in landing_url or "pantheon.ufrj.br" in landing_url:
                download_url = landing_url

            year_val = rec.get("year")
            year = int(year_val) if year_val and str(year_val).isdigit() else None

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
                    download_url=download_url,
                    policy=HarvestPolicy.DISTILL_ONLY,
                    status=HarvestStatus.INDEXED,
                    features=["academic_thesis", "bdtd", "brazilian_repository"],
                    metadata={
                        "bdtd_id": rec_id,
                        "formats": rec.get("formats", []),
                        "languages": rec.get("languages", []),
                    },
                )
            )

        return resources
