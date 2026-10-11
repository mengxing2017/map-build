from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader

from huavd_map_build.production.domain.raster import (
    RasterMvtPreflightResult,
    RasterSourceMetadata,
    RasterSourceProbe,
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
    validate_mvt: bool = False
    probes: tuple[RasterSourceProbe, ...] = ()


@dataclass(frozen=True, slots=True)
class RasterRuntimeResult:
    style_path: str
    tile_url: str
    preflight: RasterMvtPreflightResult
    served_archive: str
    source_metadata: RasterSourceMetadata
    evidence: tuple[dict, ...] = ()


class RasterRuntimeService:
    def __init__(
        self, subsetter: RasterArchiveSubsetter, server: RasterTileServer,
        client: RasterMvtClient, styles: RasterRuntimeStyleStore,
        headers: PmtilesHeaderReader,
    ) -> None:
        self._subsetter = subsetter
        self._server = server
        self._client = client
        self._styles, self._headers = styles, headers

    @contextmanager
    def open(self, request: RasterRuntimeRequest):
        served_archive = request.archive_path
        source = RasterSourceMetadata.from_header(self._headers.read(served_archive))
        if request.subset_path is not None:
            if request.subset_bounds is None:
                raise ValueError("raster subset bounds are required")
            minimum = max(request.min_zoom, source.min_zoom)
            maximum = min(request.max_zoom, source.max_zoom)
            if minimum > maximum:
                raise ValueError("raster subset has no zoom intersection with source")
            self._subsetter.extract(
                request.archive_path, request.subset_path, request.subset_bounds,
                minimum, maximum,
            )
            served_archive = request.subset_path
        source = RasterSourceMetadata.from_header(self._headers.read(served_archive))
        coordinate = source.coordinate(request.preflight_coordinate)
        with self._server.open(served_archive) as endpoint:
            if request.validate_mvt:
                preflight = self._client.fetch(
                    endpoint.tile_url, coordinate, validate=True
                )
            else:
                preflight = self._client.fetch(
                    endpoint.tile_url, coordinate
                )
            evidence = []
            for probe in request.probes:
                actual = source.coordinate(probe.output_coordinate)
                sample = self._client.fetch(endpoint.tile_url, actual, validate=True)
                if probe.expected_layer is not None and probe.expected_layer not in sample.layers:
                    raise ValueError(f"known feature sample has no {probe.expected_layer} content at "
                                     f"{actual.zoom}/{actual.x}/{actual.y}")
                output = probe.output_coordinate
                evidence.append({"output_xyz": [output.zoom, output.x, output.y],
                                 "source_xyz": [actual.zoom, actual.x, actual.y],
                                 "expected_layer": probe.expected_layer,
                                 "url": sample.url, "bytes": sample.payload_bytes,
                                 "layers": list(sample.layers)})
            self._styles.write(
                request.style_path, request.runtime_style_path, endpoint.tile_url, source
            )
            yield RasterRuntimeResult(
                request.runtime_style_path, endpoint.tile_url, preflight, served_archive, source, tuple(evidence)
            )
