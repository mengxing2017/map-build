from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.island_anchor import (
    IslandAnchorRequest,
    IslandAnchorResult,
)
from huavd_map_build.production.south.port.island_anchor import IslandAnchorStore


class IslandAnchorService:
    def __init__(self, catalog: CatalogService, store: IslandAnchorStore) -> None:
        self._catalog = catalog
        self._store = store

    def run(self, request: IslandAnchorRequest) -> IslandAnchorResult:
        self._catalog.region(request.region)
        root = request.workdir.rstrip("/")
        return self._store.derive(
            f"{root}/staging/{request.session}/layers/island.geojsonseq",
            f"{root}/cache/island-anchor/{request.session}",
            f"{root}/staging/{request.session}/island_anchor_report.json",
            request.region.value,
        )
