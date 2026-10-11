from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Protocol

from huavd_map_build.production.domain.raster import (
    RasterCacheScanResult,
    RasterCachePreparation,
    RasterBakeResult,
    RasterCacheIdentity,
    RasterAssemblyResult,
    RasterAssemblySettings,
    RasterDisplayEndpoint,
    RasterDisplaySettings,
    RasterRenderSettings,
    RasterMvtPreflightResult,
    RasterTileServerEndpoint,
    RasterTileCoordinate,
    RasterTilePlan,
    RasterSourceMetadata,
)


class RasterCacheStore(Protocol):
    def write_plan(self, plan: RasterTilePlan, plan_path: str, tiles_path: str) -> None: ...

    def scan(
        self, plan: RasterTilePlan, webp_directory: str, missing_path: str,
        quarantine_directory: str, tile_size: int,
    ) -> RasterCacheScanResult: ...


class RasterWorkQueue(Protocol):
    def coordinates(self, path: str) -> Iterator[RasterTileCoordinate]: ...


class RasterTileRenderer(Protocol):
    def render(
        self, coordinate: RasterTileCoordinate, settings: RasterRenderSettings,
        output_path: str,
    ) -> None: ...


class RasterDisplaySession(Protocol):
    def open(
        self, settings: RasterDisplaySettings,
    ) -> AbstractContextManager[RasterDisplayEndpoint]: ...


class RasterTileEncoder(Protocol):
    def encode(
        self, input_path: str, output_path: str, settings: RasterRenderSettings,
    ) -> None: ...


class RasterTileArchiveAssembler(Protocol):
    def assemble(
        self, queue_path: str, output_path: str, settings: RasterAssemblySettings,
    ) -> RasterAssemblyResult: ...


class RasterArchiveConverter(Protocol):
    def convert(self, input_path: str, output_path: str) -> None: ...


class RasterArchiveSubsetter(Protocol):
    def extract(
        self, input_path: str, output_path: str, bounds: str,
        min_zoom: int, max_zoom: int,
    ) -> None: ...


class RasterTileServer(Protocol):
    def open(self, archive_path: str) -> AbstractContextManager[RasterTileServerEndpoint]: ...


class RasterMvtClient(Protocol):
    def fetch(
        self, tile_url: str, coordinate: RasterTileCoordinate,
        validate: bool = False,
    ) -> RasterMvtPreflightResult: ...


class RasterRuntimeStyleStore(Protocol):
    def write(self, source_path: str, output_path: str, tile_url: str,
              metadata: RasterSourceMetadata) -> None: ...


class RasterCacheLifecycle(Protocol):
    def open(
        self, identity: str, workspace: str, invalidation_paths: tuple[str, ...],
    ) -> AbstractContextManager[RasterCachePreparation]: ...


class RasterEvidenceStore(Protocol):
    def write_parameters(
        self, path: str, identity: RasterCacheIdentity,
        settings: RasterRenderSettings, display: RasterDisplaySettings,
    ) -> None: ...

    def write_metrics(
        self, path: str, result: RasterBakeResult,
        mbtiles_path: str, pmtiles_path: str,
    ) -> None: ...


class RasterArchiveVerifier(Protocol):
    def verify(self, archive: str, queue: str, webp_directory: str, tile_size: int) -> int: ...
