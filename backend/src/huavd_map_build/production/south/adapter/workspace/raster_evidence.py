from __future__ import annotations

import json
from pathlib import Path

from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.production.domain.raster import (
    RasterBakeResult,
    RasterCacheIdentity,
    RasterDisplaySettings,
    RasterRenderSettings,
    raster_metrics_document,
    raster_parameters_document,
)


class FileSystemRasterEvidenceStore:
    def __init__(self, writer: AtomicWriter, digest: DigestPort) -> None:
        self._writer, self._digest = writer, digest

    def write_parameters(
        self, path: str, identity: RasterCacheIdentity,
        settings: RasterRenderSettings, display: RasterDisplaySettings,
    ) -> None:
        self._write(path, raster_parameters_document(identity, settings, display))

    def write_metrics(
        self, path: str, result: RasterBakeResult,
        mbtiles_path: str, pmtiles_path: str,
    ) -> None:
        document = raster_metrics_document(
            result, Path(mbtiles_path).stat().st_size, Path(pmtiles_path).stat().st_size
        )
        self._write(path, document)

    def _write(self, path: str, document: dict[str, object]) -> None:
        self._writer.write_text(
            path, json.dumps(document, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":")) + "\n"
        )
        digest = self._digest.sha512(path)
        self._writer.write_text(
            f"{path}.sha512", f"{digest}  {Path(path).name}\n"
        )
