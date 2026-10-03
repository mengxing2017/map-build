from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader
from huavd_map_build.production.domain.raster import (
    RasterBounds,
    RasterTilePlan,
    create_raster_tile_plan,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


@dataclass(frozen=True, slots=True)
class RasterPlanRequest:
    region: RegionId
    build_date: BuildDate
    workdir: str
    bounds: RasterBounds | None = None
    min_zoom: int | None = None
    max_zoom: int | None = None
    max_tiles: int | None = None


class RasterPlanningService:
    def __init__(
        self, configuration: BuildConfigurationService, headers: PmtilesHeaderReader
    ) -> None:
        self._configuration, self._headers = configuration, headers

    def plan(self, request: RasterPlanRequest) -> RasterTilePlan:
        settings = self._configuration.raster_bake(request.region.value)
        bounds = request.bounds
        if bounds is None:
            paths = ArtifactPaths(
                ArtifactIdentity(request.region, request.build_date, Role.BASE),
                f"{request.workdir.rstrip('/')}/outputs",
            )
            header = self._headers.read(paths.pmtiles)
            bounds = RasterBounds(*header.bounds)
        return create_raster_tile_plan(
            bounds,
            request.min_zoom if request.min_zoom is not None else int(settings["min_zoom"]),
            request.max_zoom if request.max_zoom is not None else int(settings["max_zoom"]),
            int(settings["bbox_padding_tiles"]),
            request.max_tiles if request.max_tiles is not None else settings.get("max_tiles"),
        )
