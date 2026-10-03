from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from huavd_map_build.production.domain.raster import RasterTileCoordinate


class FileSystemRasterWorkQueue:
    def coordinates(self, path: str) -> Iterator[RasterTileCoordinate]:
        with Path(path).open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    yield RasterTileCoordinate.from_tsv(line)
                except ValueError as error:
                    raise ValueError(
                        f"invalid raster work queue row {line_number}: {error}"
                    ) from error
