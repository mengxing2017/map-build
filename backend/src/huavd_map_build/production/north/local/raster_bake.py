from __future__ import annotations

from dataclasses import dataclass, replace
import time

from huavd_map_build.production.domain.raster import (
    RasterAssemblySettings,
    RasterBakeResult,
    RasterCacheIdentity,
    RasterDisplaySettings,
    RasterExecutionError,
    RasterRenderSettings,
    RasterStageTiming,
    RasterTilePlan,
)
from huavd_map_build.production.north.local.raster_assembly import (
    RasterAssemblyRequest,
    RasterAssemblyService,
)
from huavd_map_build.production.north.local.raster_render import RasterRenderService
from huavd_map_build.production.north.local.raster_runtime import (
    RasterRuntimeRequest,
    RasterRuntimeService,
)
from huavd_map_build.production.south.port.raster import (
    RasterCacheLifecycle,
    RasterCacheStore,
    RasterDisplaySession,
    RasterEvidenceStore,
)


@dataclass(frozen=True, slots=True)
class RasterBakeRequest:
    identity: RasterCacheIdentity
    plan: RasterTilePlan
    workspace: str
    plan_path: str
    tiles_path: str
    missing_path: str
    quarantine_directory: str
    invalidation_paths: tuple[str, ...]
    render_settings: RasterRenderSettings
    display_settings: RasterDisplaySettings
    runtime_request: RasterRuntimeRequest
    assembly_settings: RasterAssemblySettings
    mbtiles_path: str
    pmtiles_path: str
    parameters_path: str | None = None
    metrics_path: str | None = None


class RasterBakeService:
    def __init__(
        self, lifecycle: RasterCacheLifecycle, cache: RasterCacheStore,
        display: RasterDisplaySession, runtime: RasterRuntimeService,
        renderer: RasterRenderService,
        assembly: RasterAssemblyService, evidence: RasterEvidenceStore | None = None,
        clock=time.perf_counter,
    ) -> None:
        self._lifecycle, self._cache = lifecycle, cache
        self._display, self._runtime, self._renderer = display, runtime, renderer
        self._assembly, self._evidence, self._clock = assembly, evidence, clock

    def bake(self, request: RasterBakeRequest) -> RasterBakeResult:
        timings: list[RasterStageTiming] = []
        with self._lifecycle.open(
            request.identity.digest, request.workspace, request.invalidation_paths
        ) as preparation:
            if self._evidence is not None and request.parameters_path is not None:
                self._evidence.write_parameters(
                    request.parameters_path, request.identity, request.render_settings,
                    request.display_settings,
                )
            self._timed(
                "plan", timings,
                lambda: self._cache.write_plan(
                    request.plan, request.plan_path, request.tiles_path
                ),
            )
            with self._display.open(request.display_settings) as display:
                with self._runtime.open(request.runtime_request) as runtime:
                    initial = self._timed(
                        "cache-scan-initial", timings,
                        lambda: self._cache.scan(
                            request.plan, request.render_settings.webp_directory,
                            request.missing_path, request.quarantine_directory,
                            request.render_settings.tile_size,
                        ),
                    )
                    render_result = None
                    if initial.missing_tiles:
                        settings = replace(
                            request.render_settings, style_path=runtime.style_path,
                            display=display.display,
                        )
                        render_result = self._timed(
                            "render", timings,
                            lambda: self._renderer.render(request.missing_path, settings),
                        )
                    final = self._timed(
                        "cache-scan-final", timings,
                        lambda: self._cache.scan(
                            request.plan, request.render_settings.webp_directory,
                            request.missing_path, request.quarantine_directory,
                            request.render_settings.tile_size,
                        ),
                    )
                    if final.missing_tiles:
                        raise RasterExecutionError(
                            f"raster cache remains incomplete: {final.missing_tiles} tile(s)"
                        )
            assembly_result = self._timed(
                "assembly", timings,
                lambda: self._assembly.assemble(RasterAssemblyRequest(
                    request.tiles_path, request.mbtiles_path, request.pmtiles_path,
                    request.assembly_settings,
                )),
            )
        result = RasterBakeResult(
            preparation, initial, final, render_result, assembly_result,
            runtime.preflight, tuple(timings), runtime.evidence, runtime.source_metadata,
        )
        if self._evidence is not None and request.metrics_path is not None:
            self._evidence.write_metrics(
                request.metrics_path, result, request.mbtiles_path, request.pmtiles_path
            )
        return result

    def _timed(self, stage: str, timings: list[RasterStageTiming], operation):
        started = self._clock()
        try:
            return operation()
        finally:
            timings.append(RasterStageTiming(
                stage, round((self._clock() - started) * 1000, 3)
            ))
