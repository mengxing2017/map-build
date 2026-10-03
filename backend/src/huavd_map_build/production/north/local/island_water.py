from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.island_water import (
    IslandWaterRequest,
    IslandWaterResult,
)
from huavd_map_build.production.south.port.island_water import IslandWaterStore


class IslandWaterService:
    def __init__(self, catalog: CatalogService, store: IslandWaterStore) -> None:
        self._catalog = catalog
        self._store = store

    def run(self, request: IslandWaterRequest) -> IslandWaterResult:
        self._catalog.region(request.region)
        root = request.workdir.rstrip("/")
        layers = f"{root}/staging/{request.session}/layers"
        return self._store.flag(
            f"{layers}/island.geojsonseq",
            f"{layers}/water.geojsonseq",
            f"{root}/cache/island-water/{request.session}",
            f"{root}/staging/{request.session}/island_water_report.json",
            request.region.value,
        )
