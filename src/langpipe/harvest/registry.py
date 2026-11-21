"""Universal Indigenous Resource Registry interface and cross-language indexer."""

import json
from pathlib import Path
from typing import Any

from langpipe.harvest.models import (
    DiscoveredResource,
    HarvesterTarget,
    HarvestStatus,
)

DEFAULT_REGISTRY_PATH = Path("docs/research/universal_sources_registry.json")


class UniversalSourceRegistry:
    """Manages the cross-language repository index, language targets, and discovered assets."""

    def __init__(self, path: Path | str = DEFAULT_REGISTRY_PATH):
        self.path = Path(path)
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load the registry from JSON file or initialize if not present."""
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {
                "title": "Universal Indigenous Resource Registry",
                "version": "1.0.0",
                "repository_taxonomy": {
                    "scholarly_aggregators": [],
                    "linguistic_archives": [],
                    "parallel_corpora": [],
                },
                "language_profiles": {},
                "discovered_resources": [],
            }

    def save(self) -> None:
        """Persist the registry to disk with indentation."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get_target(self, iso639_3: str) -> HarvesterTarget | None:
        """Retrieve the target configuration for a given language code."""
        profile = self.data.get("language_profiles", {}).get(iso639_3)
        if not profile:
            return None
        return HarvesterTarget.model_validate(profile)

    def register_target(self, target: HarvesterTarget) -> None:
        """Add or update a language target in the registry."""
        if "language_profiles" not in self.data:
            self.data["language_profiles"] = {}
        self.data["language_profiles"][target.iso639_3] = target.model_dump()
        self.save()

    def add_resource(self, resource: DiscoveredResource) -> None:
        """Register a newly discovered resource, updating if source_id exists."""
        if "discovered_resources" not in self.data:
            self.data["discovered_resources"] = []

        existing_idx = None
        for i, item in enumerate(self.data["discovered_resources"]):
            if item.get("source_id") == resource.source_id:
                existing_idx = i
                break

        res_dict = resource.model_dump(mode="json")
        if existing_idx is not None:
            self.data["discovered_resources"][existing_idx] = res_dict
        else:
            self.data["discovered_resources"].append(res_dict)
        self.save()

    def list_resources(
        self,
        language_code: str | None = None,
        status: HarvestStatus | None = None,
    ) -> list[DiscoveredResource]:
        """List resources matching optional language and status filters."""
        raw_list = self.data.get("discovered_resources", [])
        results = []
        for r in raw_list:
            if language_code and r.get("language_code") != language_code:
                continue
            if status and r.get("status") != status.value:
                continue
            results.append(DiscoveredResource(**r))
        return results

    def get_cross_language_recommendations(self, language_code: str) -> list[str]:
        """Find sister and neighboring languages that should be crawled next."""
        target = self.get_target(language_code)
        if not target:
            return []

        candidates = set(target.sister_languages)
        for res in self.list_resources(language_code=language_code):
            for rel in res.related_languages:
                if rel != language_code:
                    candidates.add(rel)
        return sorted(list(candidates))
