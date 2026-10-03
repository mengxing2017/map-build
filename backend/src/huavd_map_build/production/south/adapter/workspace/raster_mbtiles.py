from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import tempfile

from huavd_map_build.production.domain.raster import (
    RasterAssemblyResult,
    RasterAssemblySettings,
    RasterExecutionError,
    webp_dimensions,
)
from huavd_map_build.production.south.adapter.workspace.raster_queue import (
    FileSystemRasterWorkQueue,
)


class SqliteRasterTileArchiveAssembler:
    def __init__(self, queue: FileSystemRasterWorkQueue | None = None) -> None:
        self._queue = queue or FileSystemRasterWorkQueue()

    def assemble(
        self, queue_path: str, output_path: str, settings: RasterAssemblySettings,
    ) -> RasterAssemblyResult:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", suffix=".mbtiles", delete=False,
        )
        temporary = Path(temporary_file.name)
        temporary_file.close()
        expected = inserted = tile_bytes = 0
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(temporary)
            connection.execute("create table metadata (name text, value text)")
            connection.execute(
                "create table tiles (zoom_level integer, tile_column integer, "
                "tile_row integer, tile_data blob)"
            )
            metadata = {
                "name": settings.name,
                "format": "webp",
                "bounds": ",".join(str(value) for value in settings.bounds.as_list()),
                "minzoom": str(settings.min_zoom),
                "maxzoom": str(settings.max_zoom),
                "type": "baselayer",
                "version": "1",
                "description": settings.description,
                "attribution": settings.attribution,
            }
            connection.executemany(
                "insert into metadata(name, value) values (?, ?)", metadata.items()
            )
            for coordinate in self._queue.coordinates(queue_path):
                expected += 1
                if not settings.min_zoom <= coordinate.zoom <= settings.max_zoom:
                    raise RasterExecutionError(
                        f"tile {coordinate.zoom}/{coordinate.x}/{coordinate.y} "
                        "is outside the archive zoom range"
                    )
                tile = (
                    Path(settings.webp_directory) / str(coordinate.zoom) /
                    str(coordinate.x) / f"{coordinate.y}.webp"
                )
                payload = self._verified_payload(tile, settings.tile_size)
                tile_row = (1 << coordinate.zoom) - 1 - coordinate.y
                connection.execute(
                    "insert into tiles(zoom_level, tile_column, tile_row, tile_data) "
                    "values (?, ?, ?, ?)",
                    (coordinate.zoom, coordinate.x, tile_row, payload),
                )
                inserted += 1
                tile_bytes += len(payload)
            if inserted == 0:
                raise RasterExecutionError("raster tile queue is empty")
            connection.execute(
                "insert into metadata(name, value) values (?, ?)",
                ("tile_count", str(inserted)),
            )
            connection.execute(
                "create unique index tile_index on tiles "
                "(zoom_level, tile_column, tile_row)"
            )
            if inserted != expected:
                raise RasterExecutionError(
                    f"MBTiles tile count mismatch: inserted={inserted} expected={expected}"
                )
            connection.commit()
            connection.close()
            connection = None
            temporary.replace(target)
        except sqlite3.Error as error:
            raise RasterExecutionError(f"failed to assemble raster MBTiles: {error}") from error
        finally:
            if connection is not None:
                connection.close()
            temporary.unlink(missing_ok=True)
        return RasterAssemblyResult(expected, inserted, tile_bytes)

    @staticmethod
    def _verified_payload(tile: Path, tile_size: int) -> bytes:
        try:
            payload = tile.read_bytes()
            dimensions = webp_dimensions(payload)
            marker = Path(f"{tile}.sha512").read_text(encoding="utf-8").split(maxsplit=1)[0]
        except (OSError, ValueError, IndexError) as error:
            raise RasterExecutionError(f"invalid raster cache tile: {tile}: {error}") from error
        if dimensions != (tile_size, tile_size):
            raise RasterExecutionError(
                f"unexpected raster cache tile dimensions {dimensions}: {tile}"
            )
        if marker != hashlib.sha512(payload).hexdigest():
            raise RasterExecutionError(f"raster cache tile digest mismatch: {tile}")
        return payload
