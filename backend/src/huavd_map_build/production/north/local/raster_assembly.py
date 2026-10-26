from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import Callable

from huavd_map_build.production.domain.raster import (
    RasterAssemblyResult,
    RasterAssemblySettings,
    RasterStageTiming,
)
from huavd_map_build.production.south.port.raster import (
    RasterArchiveConverter,
    RasterArchiveVerifier,
    RasterTileArchiveAssembler,
)


@dataclass(frozen=True, slots=True)
class RasterAssemblyRequest:
    queue_path: str
    mbtiles_path: str
    pmtiles_path: str
    settings: RasterAssemblySettings


class RasterAssemblyService:
    def __init__(
        self, assembler: RasterTileArchiveAssembler,
        converter: RasterArchiveConverter, verifier: RasterArchiveVerifier | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._assembler, self._converter, self._verifier = assembler, converter, verifier
        self._clock = clock

    def assemble(self, request: RasterAssemblyRequest) -> RasterAssemblyResult:
        timings = []
        started = self._clock()
        result = self._assembler.assemble(
            request.queue_path, request.mbtiles_path, request.settings
        )
        timings.append(RasterStageTiming("mbtiles-assembly", (self._clock() - started) * 1000))
        started = self._clock()
        self._converter.convert(request.mbtiles_path, request.pmtiles_path)
        timings.append(RasterStageTiming("pmtiles-convert", (self._clock() - started) * 1000))
        if self._verifier is not None:
            started = self._clock()
            verified = self._verifier.verify(
                request.pmtiles_path, request.queue_path,
                request.settings.webp_directory, request.settings.tile_size,
            )
            if verified != result.inserted_tiles:
                raise ValueError("raster readback count differs from assembled tiles")
            timings.append(RasterStageTiming("pmtiles-readback", (self._clock() - started) * 1000))
            result = replace(result, verified_tiles=verified)
        return replace(result, timings=tuple(timings))
