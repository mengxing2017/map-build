from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from huavd_map_build.production.domain.raster import (
    RasterMvtPreflightResult,
    RasterTileCoordinate,
)
from huavd_map_build.production.south.port.raster import (
    RasterArchiveSubsetter,
    RasterMvtClient,
    RasterRuntimeStyleStore,
    RasterTileServer,
)


@dataclass(frozen=True, slots=True)
class RasterRuntimeRequest:
    archive_path: str
    style_path: str
    runtime_style_path: str
    preflight_coordinate: RasterTileCoordinate
    subset_path: str | None = None
    subset_bounds: str | None = None
    min_zoom: int = 0
    max_zoom: int = 14


@dataclass(frozen=True, slots=True)
class RasterRuntimeResult:
    style_path: str
    tile_url: str
    preflight: RasterMvtPreflightResult
    served_archive: str


class RasterRuntimeService:
    def __init__(
        self, subsetter: RasterArchiveSubsetter, server: RasterTileServer,
        client: RasterMvtClient, styles: RasterRuntimeStyleStore,
    ) -> None:
        self._subsetter = subsetter
        self._server = server
        self._client = client
        self._styles = styles

    @contextmanager
    def open(self, request: RasterRuntimeRequest):
        served_archive = request.archive_path
        if request.subset_path is not None:
            if request.subset_bounds is None:
                raise ValueError("raster subset bounds are required")
            self._subsetter.extract(
                request.archive_path, request.subset_path, request.subset_bounds,
                request.min_zoom, request.max_zoom,
            )
            served_archive = request.subset_path
        with self._server.open(served_archive) as endpoint:
            preflight = self._client.fetch(
                endpoint.tile_url, request.preflight_coordinate
            )
            self._styles.write(
                request.style_path, request.runtime_style_path, endpoint.tile_url
            )
            yield RasterRuntimeResult(
                request.runtime_style_path, endpoint.tile_url, preflight, served_archive
            )
