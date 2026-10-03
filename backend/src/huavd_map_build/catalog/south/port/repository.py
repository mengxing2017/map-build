from typing import Protocol

from huavd_map_build.catalog.domain import RegionCatalog


class RegionCatalogRepository(Protocol):
    def load(self) -> RegionCatalog: ...
