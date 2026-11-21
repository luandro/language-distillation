"""Zenodo Open Science spider for linguistic corpora, IGT texts, and datasets."""

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


class ZenodoSpider(BaseSpider):
    """Searches Zenodo for open datasets, IGT texts, and Language Science Press publications."""

    spider_id = "zenodo"
    name = "Zenodo Open Science Archive"
    API_URL = "https://zenodo.org/api/records"

    def __init__(self) -> None:
        self.user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"

    def search(self, target: HarvesterTarget, limit: int = 15) -> list[DiscoveredResource]:
        """Search Zenodo records for target language."""
        query = f"{target.language_name}"
        params = {
            "q": query,
            "size": str(min(limit, 30)),
        }
        url = f"{self.API_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        resources: list[DiscoveredResource] = []
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return resources

        hits = data.get("hits", {}).get("hits", []) or []
        for hit in hits:
            meta = hit.get("metadata", {}) or {}
            title = meta.get("title") or "Zenodo Publication"
            rec_id = str(hit.get("id"))
            source_id = f"zenodo_{rec_id}"

            # Creators / Authors
            creators = meta.get("creators", []) or []
            author_names = [c.get("name") for c in creators if c.get("name")]
            author_str = "; ".join(author_names) if author_names else None

            # Year
            pub_date = meta.get("publication_date", "")
            year = int(pub_date[:4]) if pub_date and pub_date[:4].isdigit() else None

            # License & Policy
            lic_dict = meta.get("license", {}) or {}
            lic_id = (
                lic_dict.get("id", "").lower()
                if isinstance(lic_dict, dict)
                else str(lic_dict).lower()
            )
            if "cc-by" in lic_id or "open" in meta.get("access_right", ""):
                policy = HarvestPolicy.PERMISSIVE_ACADEMIC
            else:
                policy = HarvestPolicy.DISTILL_ONLY

            # Files attached
            files = hit.get("files", []) or []
            download_url = None
            file_size = None
            md5_checksum = None
            if files:
                first_file = files[0]
                download_url = first_file.get("links", {}).get("self")
                file_size = first_file.get("size")
                md5_checksum = first_file.get("checksum")

            landing_url = hit.get("links", {}).get("html") or f"https://zenodo.org/records/{rec_id}"

            # Features
            features = ["zenodo_record", "open_science"]
            description = (meta.get("description", "") or "").lower()
            if "igt" in description or "gloss" in description:
                features.append("igt_interlinear")
            if any(c.get("id") == "langscipress" for c in meta.get("communities", [])):
                features.append("language_science_press")

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
                    file_size_bytes=file_size,
                    policy=policy,
                    status=HarvestStatus.INDEXED,
                    features=features,
                    metadata={
                        "zenodo_id": rec_id,
                        "doi": hit.get("doi"),
                        "license": lic_id,
                        "md5": md5_checksum,
                        "communities": [
                            c.get("id") for c in meta.get("communities", []) if isinstance(c, dict)
                        ],
                    },
                )
            )

        return resources
