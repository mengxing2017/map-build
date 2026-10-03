from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.production.domain.raster import (
    RasterAssemblySettings,
    RasterCacheIdentity,
    RasterRenderSettings,
    RasterTilePlan,
)
from huavd_map_build.production.north.local.raster_bake import RasterBakeRequest
from huavd_map_build.production.north.local.raster_runtime import RasterRuntimeRequest
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


@dataclass(frozen=True, slots=True)
class RasterBakeOverrides:
    renderer_engine: str = "mbgl-renderer"
    renderer_command: str = "mbgl-render"
    renderer_identity: str = "unknown"
    parallel_jobs: int | None = None
    retries: int | None = None
    timeout_seconds: int | None = None
    extract_pmtiles: bool | None = None


class RasterBakeRequestFactory:
    def __init__(
        self, configuration: BuildConfigurationService, digest: DigestPort,
        bake_configuration_path: str,
    ) -> None:
        self._configuration = configuration
        self._digest = digest
        self._bake_configuration_path = bake_configuration_path

    def create(
        self, region: RegionId, build_date: BuildDate, workdir: str,
        plan: RasterTilePlan, overrides: RasterBakeOverrides,
    ) -> RasterBakeRequest:
        settings = self._configuration.raster_bake(region.value)
        outputs = Path(workdir) / "outputs"
        cache = Path(workdir) / "cache" / "bake" / f"{region.slug}-{build_date.value}"
        base = ArtifactPaths(
            ArtifactIdentity(region, build_date, Role.BASE), str(outputs)
        )
        style = cache / "style-render.json"
        for required in (Path(base.pmtiles), style, Path(self._bake_configuration_path)):
            if not required.is_file():
                raise ValueError(f"required raster bake input does not exist: {required}")
        webp = cache / "webp"
        png = cache / "png"
        cwebp = settings.get("cwebp", {})
        render = RasterRenderSettings(
            str(style), str(png), str(webp), int(settings.get("tile_size", 256)),
            overrides.renderer_engine, overrides.renderer_command,
            bool(cwebp.get("lossless", True)), int(cwebp.get("method", 6)),
            str(cwebp.get("metadata", "none")),
            int(settings.get("tile_timeout_seconds", 120))
            if overrides.timeout_seconds is None else overrides.timeout_seconds,
            int(settings.get("parallel_jobs", 8))
            if overrides.parallel_jobs is None else overrides.parallel_jobs,
            settings.get("retries", 2) if overrides.retries is None else overrides.retries,
        )
        identity = RasterCacheIdentity(
            self._digest.sha512(base.pmtiles), self._digest.sha512(str(style)),
            self._digest.sha512(self._bake_configuration_path), plan,
            render.tile_size, int(settings.get("pixel_ratio", 1)),
            render.webp_lossless, render.webp_method, render.webp_metadata,
            render.renderer_engine, overrides.renderer_identity,
        )
        extract = (
            bool(settings.get("pmtiles_extract", False))
            if overrides.extract_pmtiles is None else overrides.extract_pmtiles
        )
        runtime = RasterRuntimeRequest(
            base.pmtiles, str(style), str(cache / "style-render-runtime.json"),
            next(plan.coordinates()),
            str(cache / "base-bake-subset.pmtiles") if extract else None,
            ",".join(str(value) for value in plan.bounds.as_list()) if extract else None,
            plan.min_zoom, plan.max_zoom,
        )
        stem = f"{region.slug}-{build_date.value}.raster_bake"
        return RasterBakeRequest(
            identity, plan, str(cache), str(cache / "plan.json"),
            str(cache / "tiles.tsv"), str(cache / "missing.tsv"),
            str(cache / "quarantine"),
            (str(png), str(webp), str(cache / "raster_bake.mbtiles")),
            render, runtime,
            RasterAssemblySettings(
                stem, plan.bounds, plan.min_zoom, plan.max_zoom, str(webp),
                render.tile_size,
            ),
            str(cache / "raster_bake.mbtiles"),
            str(cache / "raster_bake.candidate.pmtiles"),
            str(cache / "parameters.json"), str(cache / "metrics.json"),
        )
