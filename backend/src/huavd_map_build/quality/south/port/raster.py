from typing import Protocol

from huavd_map_build.production.domain.raster import RasterTileCoordinate


class RasterTileSampleVerifier(Protocol):
    def verify(
        self, pmtiles_path: str, coordinate: RasterTileCoordinate,
        expected_size: int,
    ) -> None: ...
