"""HarvestService orchestrating discovery, acquisition, verification, and extraction."""

import hashlib
import json
import urllib.request
from pathlib import Path

from langpipe.harvest.extractors.igt_parser import IgtObservationParser
from langpipe.harvest.extractors.pdf_extractor import PdfExtractor
from langpipe.harvest.models import (
    DiscoveredResource,
    HarvesterTarget,
    HarvestStatus,
)
from langpipe.harvest.registry import UniversalSourceRegistry
from langpipe.harvest.spiders.bdtd import BdtdSpider
from langpipe.harvest.spiders.etnolinguistica import EtnolinguisticaSpider
from langpipe.harvest.spiders.glottolog import GlottologSpider
from langpipe.harvest.spiders.openalex import OpenAlexSpider
from langpipe.harvest.spiders.wikipedia import WikipediaSpider
from langpipe.harvest.spiders.zenodo import ZenodoSpider


class HarvestService:
    """End-to-end service for autonomous resource discovery and ingestion."""

    def __init__(
        self,
        registry: UniversalSourceRegistry | None = None,
        storage_root: Path | str = "var/external",
    ):
        self.registry = registry or UniversalSourceRegistry()
        self.storage_root = Path(storage_root)
        self.spiders = [
            OpenAlexSpider(),
            BdtdSpider(),
            ZenodoSpider(),
            GlottologSpider(),
            EtnolinguisticaSpider(),
            WikipediaSpider(),
        ]
        self.pdf_extractor = PdfExtractor()

    def discover(
        self, target: HarvesterTarget, limit_per_spider: int = 10
    ) -> list[DiscoveredResource]:
        """Run all spiders to discover resources for target language and update registry."""
        all_discovered = []
        for spider in self.spiders:
            try:
                found = spider.search(target, limit=limit_per_spider)
                for res in found:
                    self.registry.add_resource(res)
                    all_discovered.append(res)
            except Exception:
                continue
        return all_discovered

    def download_resource(
        self, resource: DiscoveredResource, dest_dir: Path | None = None
    ) -> DiscoveredResource:
        """Download asset to immutable storage, calculate SHA-256, and update status."""
        if not resource.download_url:
            raise ValueError(f"Resource {resource.source_id} has no download_url")

        if dest_dir is None:
            dest_dir = self.storage_root / f"{resource.language_code}_sources"
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = (
            f"{resource.source_id}.pdf"
            if resource.mime_type == "application/pdf"
            else f"{resource.source_id}.dat"
        )
        dest_path = dest_dir / filename

        req = urllib.request.Request(
            resource.download_url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as f:
            h = hashlib.sha256()
            total_size = 0
            while chunk := resp.read(1024 * 1024):
                f.write(chunk)
                h.update(chunk)
                total_size += len(chunk)

        resource.sha256 = h.hexdigest()
        resource.file_size_bytes = total_size
        resource.local_path = str(dest_path)
        resource.status = HarvestStatus.DOWNLOADED
        self.registry.add_resource(resource)
        return resource

    def process_igt_resource(
        self,
        text_path: Path | str,
        source_id: str,
        run_id: str | None = None,
        source_object_id: str | None = None,
    ) -> tuple[int, int, Path]:
        """Parse IGT text, save observations and export parallel sentences."""
        from langpipe.domain.ids import ID_PATTERN, IdPrefix, new_id

        valid_source_id = source_id if ID_PATTERN.fullmatch(source_id) else new_id(IdPrefix.SOURCE)
        valid_run_id = run_id if (run_id and ID_PATTERN.fullmatch(run_id)) else new_id(IdPrefix.RUN)
        valid_source_object_id = (
            source_object_id
            if (source_object_id and ID_PATTERN.fullmatch(source_object_id))
            else new_id(IdPrefix.SOURCE_OBJECT)
        )

        text = Path(text_path).read_text(encoding="utf-8")
        parser = IgtObservationParser(
            source_id=valid_source_id,
            run_id=valid_run_id,
            source_object_id=valid_source_object_id,
        )
        observations, parallel_pairs = parser.parse_blocks(text)

        # Export parallel pairs as jsonl
        export_dir = Path("exports/harvested_parallel")
        export_dir.mkdir(parents=True, exist_ok=True)
        pairs_file = export_dir / f"{source_id}_parallel.jsonl"
        with open(pairs_file, "w", encoding="utf-8") as f:
            for pair in parallel_pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")

        return len(observations), len(parallel_pairs), pairs_file
