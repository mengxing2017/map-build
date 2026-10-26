from __future__ import annotations

from dataclasses import dataclass, replace

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader
from huavd_map_build.production.domain.raster import (
    RasterBounds,
    RasterTilePlan,
    create_raster_tile_plan,
    extend_raster_plan_budget,
    validate_raster_headroom_ratio,
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
        return self._plan(request, enforce_limit=True)

    def estimate(self, request: RasterPlanRequest) -> RasterTilePlan:
        return self._plan(request, enforce_limit=False)

    def _plan(
        self, request: RasterPlanRequest, *, enforce_limit: bool,
    ) -> RasterTilePlan:
        settings = self._configuration.raster_bake(request.region.value)
        bounds = request.bounds
        if bounds is None:
            paths = ArtifactPaths(
                ArtifactIdentity(request.region, request.build_date, Role.BASE),
                f"{request.workdir.rstrip('/')}/outputs",
            )
            header = self._headers.read(paths.pmtiles)
            bounds = RasterBounds(*header.bounds)
        plan = create_raster_tile_plan(
            bounds,
            request.min_zoom if request.min_zoom is not None else int(settings["min_zoom"]),
            request.max_zoom if request.max_zoom is not None else int(settings["max_zoom"]),
            int(settings["bbox_padding_tiles"]),
            request.max_tiles if request.max_tiles is not None else settings.get("max_tiles"),
            enforce_limit=False,
        )
        return self._resolve_budget(
            request, settings, plan, enforce_limit=enforce_limit
        )

    def _resolve_budget(
        self, request: RasterPlanRequest, settings: dict, plan: RasterTilePlan,
        *, enforce_limit: bool,
    ) -> RasterTilePlan:
        ratio = validate_raster_headroom_ratio(
            settings.get("max_tiles_headroom_ratio")
        )
        if request.max_tiles is None and ratio is not None:
            return extend_raster_plan_budget(plan, ratio)
        if request.max_tiles is not None:
            plan = replace(plan, max_tiles_source="override")
        if enforce_limit and not plan.within_limit:
            coverage = ",".join(str(value) for value in plan.bounds.as_list())
            raise ValueError(
                f"raster bake plan exceeds max_tiles (explicit hard cap): "
                f"planned={plan.tile_count} max_tiles={plan.max_tiles} "
                f"bounds={coverage} min_zoom={plan.min_zoom} "
                f"max_zoom={plan.max_zoom} bbox_padding_tiles={plan.padding}; "
                "omit --max-tiles to use the configured baseline with automatic headroom"
            )
        return plan
