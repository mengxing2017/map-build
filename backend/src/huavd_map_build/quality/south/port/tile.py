from typing import Any, Protocol

from huavd_map_build.quality.domain.tile import TileCoordinate, VectorTilePayload


class VectorTileReader(Protocol):
    def read(self, archive: str, coordinate: TileCoordinate) -> VectorTilePayload: ...
    def decode(self, archive: str, coordinate: TileCoordinate) -> dict[str, Any]: ...
