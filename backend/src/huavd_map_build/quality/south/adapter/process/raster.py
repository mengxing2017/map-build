from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

from huavd_map_build.production.domain.raster import (
    RasterExecutionError,
    RasterTileCoordinate,
    webp_dimensions,
)
from huavd_map_build.production.south.adapter.process.raster import (
    _environment,
    _executable,
    _run,
)


class ProcessRasterTileSampleVerifier:
    def verify(
        self, pmtiles_path: str, coordinate: RasterTileCoordinate,
        expected_size: int,
    ) -> None:
        pmtiles, dwebp = _executable("pmtiles"), _executable("dwebp")
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as output:
            temporary = Path(output.name)
            try:
                result = subprocess.run(
                    [pmtiles, "tile", pmtiles_path, str(coordinate.zoom),
                     str(coordinate.x), str(coordinate.y)],
                    env=_environment(), stdout=output, stderr=subprocess.PIPE,
                    check=False,
                )
                output.flush()
                if result.returncode != 0:
                    raise RasterExecutionError(
                        "pmtiles tile failed for "
                        f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}"
                    )
                payload = temporary.read_bytes()
                if webp_dimensions(payload) != (expected_size, expected_size):
                    raise RasterExecutionError(
                        "sampled WebP has unexpected dimensions for "
                        f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}"
                    )
                _run([dwebp, str(temporary), "-o", os.devnull], 30, "dwebp")
            finally:
                temporary.unlink(missing_ok=True)
