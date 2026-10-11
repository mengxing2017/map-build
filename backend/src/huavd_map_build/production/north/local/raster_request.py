from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.production.domain.raster import (
    RasterAssemblySettings,
    RasterCacheIdentity,
    RasterDisplaySettings,
    RasterRenderSettings,
    RasterTilePlan,
    RasterSourceMetadata,
    RasterSourceProbe,
    RasterContentSample,
    RasterTileCoordinate,
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
    display_mode: str | None = None
    content_samples: tuple[RasterContentSample, ...] = ()


class RasterBakeRequestFactory:
    def __init__(
        self, configuration: BuildConfigurationService, digest: DigestPort,
        bake_configuration_path: str, headers: PmtilesHeaderReader,
    ) -> None:
        self._configuration = configuration
        self._digest = digest
        self._bake_configuration_path = bake_configuration_path
        self._headers = headers

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
        display = settings.get("display", {})
        native = overrides.renderer_engine == "maplibre-native-headless"
        if native and plan.max_zoom > 24:
            raise ValueError("native renderer only supports zooms 0..24")
        display_mode = overrides.display_mode or (
            "headless" if native else str(display.get("mode", "managed-xvfb"))
        )
        if native != (display_mode == "headless"):
            raise ValueError("headless display requires maplibre-native-headless and vice versa")
        render = RasterRenderSettings(
            str(style), str(png), str(webp), int(settings.get("tile_size", 256)),
            overrides.renderer_engine, overrides.renderer_command,
            bool(cwebp.get("lossless", True)), int(cwebp.get("method", 6)),
            str(cwebp.get("metadata", "none")),
            int(settings.get("tile_timeout_seconds", 120))
            if overrides.timeout_seconds is None else overrides.timeout_seconds,
            (int(settings.get("native_parallel_jobs", 1)) if native else int(settings.get("parallel_jobs", 8)))
            if overrides.parallel_jobs is None else overrides.parallel_jobs,
            settings.get("retries", 2) if overrides.retries is None else overrides.retries,
        )
        source = RasterSourceMetadata.from_header(self._headers.read(base.pmtiles))
        extract = (
            bool(settings.get("pmtiles_extract", False))
            if overrides.extract_pmtiles is None else overrides.extract_pmtiles
        )
        minimum, maximum = max(plan.min_zoom, source.min_zoom), min(plan.max_zoom, source.max_zoom)
        if extract and minimum > maximum:
            raise ValueError("raster subset has no zoom intersection with source")
        subset_bounds = ",".join(str(value) for value in plan.bounds.as_list()) if extract else None
        identity = RasterCacheIdentity(
            self._digest.sha512(base.pmtiles), self._digest.sha512(str(style)),
            self._digest.sha512(self._bake_configuration_path), plan,
            render.tile_size, int(settings.get("pixel_ratio", 1)),
            render.webp_lossless, render.webp_method, render.webp_metadata,
            render.renderer_engine, overrides.renderer_identity, source,
            subset_bounds, (minimum, maximum) if extract else None,
        )
        if native and plan.max_zoom >= 19 and not overrides.content_samples:
            raise ValueError("z19 native raster bake requires at least one --sample=LAYER,LON,LAT known feature")
        probes: list[RasterSourceProbe] = []
        if native:
            high = plan.ranges[-1]
            # Include high-zoom center and all padded corners; emptiness is legal here.
            for x, y in (((high.x_min + high.x_max)//2, (high.y_min + high.y_max)//2),
                         (high.x_min, high.y_min), (high.x_max, high.y_min),
                         (high.x_min, high.y_max), (high.x_max, high.y_max)):
                probe = RasterSourceProbe(RasterTileCoordinate(high.zoom, x, y))
                if probe not in probes:
                    probes.append(probe)
        for sample in overrides.content_samples:
            if not (plan.bounds.west <= sample.longitude <= plan.bounds.east
                    and plan.bounds.south <= sample.latitude <= plan.bounds.north):
                raise ValueError("known feature sample is outside raster bounds")
            probes.append(RasterSourceProbe(sample.coordinate(plan.max_zoom), sample.layer))
        runtime = RasterRuntimeRequest(
            base.pmtiles, str(style), str(cache / "style-render-runtime.json"),
            next(plan.coordinates()),
            str(cache / "base-bake-subset.pmtiles") if extract else None,
            subset_bounds,
            plan.min_zoom, plan.max_zoom, validate_mvt=native, probes=tuple(probes),
        )
        stem = f"{region.slug}-{build_date.value}.raster_bake"
        display_settings = RasterDisplaySettings(
            display_mode,
            str(display.get("screen", "1024x768x24")),
            float(display.get("startup_timeout_seconds", 10)),
            str(cache / "xvfb.log"),
        )
        return RasterBakeRequest(
            identity, plan, str(cache), str(cache / "plan.json"),
            str(cache / "tiles.tsv"), str(cache / "missing.tsv"),
            str(cache / "quarantine"),
            (str(png), str(webp), str(cache / "raster_bake.mbtiles")),
            render, display_settings, runtime,
            RasterAssemblySettings(
                stem, plan.bounds, plan.min_zoom, plan.max_zoom, str(webp),
                render.tile_size,
            ),
            str(cache / "raster_bake.mbtiles"),
            str(cache / "raster_bake.candidate.pmtiles"),
            str(cache / "parameters.json"), str(cache / "metrics.json"),
        )
