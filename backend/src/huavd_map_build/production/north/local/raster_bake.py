from __future__ import annotations

from dataclasses import dataclass, replace
import math
import time

from huavd_map_build.production.domain.raster import (
    RasterAssemblySettings,
    RasterBatchExecutionError,
    RasterBakeResult,
    RasterCacheIdentity,
    RasterDisplaySettings,
    RasterExecutionError,
    RasterRenderBatchResult,
    RasterRenderSettings,
    RasterStageTiming,
    RasterTilePlan,
    raster_progress_document,
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


class _BakeProgress:
    def __init__(
        self, evidence: RasterEvidenceStore | None, path: str | None,
        identity: RasterCacheIdentity, planned_tiles: int, queued_tiles: int,
        batch_tiles: int | None,
    ) -> None:
        self._evidence, self._path = evidence, path
        self._identity, self._planned = identity, planned_tiles
        self._queued, self._batch_tiles = queued_tiles, batch_tiles
        self._total = 0 if not queued_tiles else (
            math.ceil(queued_tiles / batch_tiles) if batch_tiles else 1
        )
        self._completed = self._rendered = self._failed = 0
        self._samples: list[str] = []

    def record(self, batch: RasterRenderBatchResult) -> None:
        self._completed += 1
        self._rendered += batch.rendered_tiles
        self._failed += batch.failed_tiles
        self._samples.extend(batch.failed_samples)
        self.write("rendering")

    def write(self, status: str) -> None:
        if self._evidence is None or self._path is None:
            return
        self._evidence.write_progress(self._path, raster_progress_document(
            self._identity, status=status, planned_tiles=self._planned,
            queued_tiles=self._queued, batch_tiles=self._batch_tiles,
            batches_total=self._total, batches_completed=self._completed,
            rendered_tiles=self._rendered, failed_tiles=self._failed,
            failed_samples=tuple(self._samples),
        ))


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
    progress_path: str | None = None


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
                    progress = _BakeProgress(
                        self._evidence, request.progress_path, request.identity,
                        request.plan.tile_count, initial.missing_tiles,
                        request.render_settings.batch_tiles,
                    )
                    progress.write("rendering")
                    render_result = None
                    if initial.missing_tiles:
                        settings = replace(
                            request.render_settings, style_path=runtime.style_path,
                            display=display.display,
                        )
                        try:
                            render_result = self._timed(
                                "render", timings,
                                lambda: self._renderer.render(
                                    request.missing_path, settings, on_batch=progress.record,
                                ),
                            )
                        except RasterBatchExecutionError as error:
                            try:
                                progress.write("failed")
                            except Exception as evidence_error:
                                raise RasterExecutionError(
                                    f"raster render failed; progress could not be written: {evidence_error}"
                                ) from error
                            if self._evidence is not None and request.metrics_path is not None:
                                try:
                                    self._evidence.write_failure_metrics(
                                        f"{request.metrics_path}.failed.json", {
                                            "schema_version": 1, "status": "failed",
                                            "cache_identity": request.identity.digest,
                                            "run_identity": request.identity.run_digest,
                                            "planned_tiles": initial.planned_tiles,
                                            "render": error.metrics,
                                            "phases_ms": {item.stage: item.elapsed_ms for item in timings},
                                        },
                                    )
                                except Exception as evidence_error:
                                    raise RasterExecutionError(
                                        f"raster render failed; failure metrics could not be written: {evidence_error}"
                                    ) from error
                            raise
                    final = self._timed(
                        "cache-scan-final", timings,
                        lambda: self._cache.scan(
                            request.plan, request.render_settings.webp_directory,
                            request.missing_path, request.quarantine_directory,
                            request.render_settings.tile_size,
                        ),
                    )
                    if final.missing_tiles:
                        progress.write("failed")
                        raise RasterExecutionError(
                            f"raster cache remains incomplete: {final.missing_tiles} tile(s)"
                        )
                    progress.write("rendered")
            assembly_result = self._timed(
                "assembly", timings,
                lambda: self._assembly.assemble(RasterAssemblyRequest(
                    request.tiles_path, request.mbtiles_path, request.pmtiles_path,
                    request.assembly_settings,
                )),
            )
            progress.write("complete")
        result = RasterBakeResult(
            preparation, initial, final, render_result, assembly_result,
            runtime.preflight, tuple(timings), runtime.evidence, runtime.source_metadata,
            request.identity.run_digest,
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
