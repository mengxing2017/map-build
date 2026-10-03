from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.production.domain.raster import (
    RasterAssemblyResult,
    RasterAssemblySettings,
)
from huavd_map_build.production.south.port.raster import (
    RasterArchiveConverter,
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
        converter: RasterArchiveConverter,
    ) -> None:
        self._assembler, self._converter = assembler, converter

    def assemble(self, request: RasterAssemblyRequest) -> RasterAssemblyResult:
        result = self._assembler.assemble(
            request.queue_path, request.mbtiles_path, request.settings
        )
        self._converter.convert(request.mbtiles_path, request.pmtiles_path)
        return result
