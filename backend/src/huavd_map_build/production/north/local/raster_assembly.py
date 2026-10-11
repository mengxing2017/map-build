from __future__ import annotations

from dataclasses import dataclass, replace

from huavd_map_build.production.domain.raster import (
    RasterAssemblyResult,
    RasterAssemblySettings,
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
    ) -> None:
        self._assembler, self._converter, self._verifier = assembler, converter, verifier

    def assemble(self, request: RasterAssemblyRequest) -> RasterAssemblyResult:
        result = self._assembler.assemble(
            request.queue_path, request.mbtiles_path, request.settings
        )
        self._converter.convert(request.mbtiles_path, request.pmtiles_path)
        if self._verifier is not None:
            verified = self._verifier.verify(
                request.pmtiles_path, request.queue_path,
                request.settings.webp_directory, request.settings.tile_size,
            )
            if verified != result.inserted_tiles:
                raise ValueError("raster readback count differs from assembled tiles")
            result = replace(result, verified_tiles=verified)
        return result
