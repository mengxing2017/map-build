from typing import Any, Protocol

from huavd_map_build.quality.domain.tile import TileCoordinate


class VectorTileReader(Protocol):
    def decode(self, archive: str, coordinate: TileCoordinate) -> dict[str, Any]: ...
