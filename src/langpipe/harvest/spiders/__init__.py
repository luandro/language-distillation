"""Harvest repository spiders package."""

from langpipe.harvest.spiders.base import BaseSpider
from langpipe.harvest.spiders.bdtd import BdtdSpider
from langpipe.harvest.spiders.etnolinguistica import EtnolinguisticaSpider
from langpipe.harvest.spiders.glottolog import GlottologSpider
from langpipe.harvest.spiders.openalex import OpenAlexSpider
from langpipe.harvest.spiders.wikipedia import WikipediaSpider
from langpipe.harvest.spiders.zenodo import ZenodoSpider

__all__ = [
    "BaseSpider",
    "OpenAlexSpider",
    "BdtdSpider",
    "ZenodoSpider",
    "GlottologSpider",
    "EtnolinguisticaSpider",
    "WikipediaSpider",
]
