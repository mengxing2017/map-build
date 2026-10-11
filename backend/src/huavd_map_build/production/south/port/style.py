from typing import Any, Protocol

from huavd_map_build.production.domain.style import StyleDocuments


class StyleViewportReader(Protocol):
    def read(self, path: str) -> dict[str, Any]: ...


class StyleStore(Protocol):
    def is_file(self, path: str) -> bool: ...

    def publish(self, vector_path: str, bake_path: str, raster_path: str,
                documents: StyleDocuments) -> tuple[str, str, str]: ...


class RasterClientStyleBinder(Protocol):
    def bind(self, archive_path: str, style_path: str, tile_size: int) -> None: ...
