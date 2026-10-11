from __future__ import annotations

import gzip
import subprocess
from typing import Any

from huavd_map_build.quality.domain.tile import TileCoordinate


class ProcessVectorTileReader:
    def decode(self, archive: str, coordinate: TileCoordinate) -> dict[str, Any]:
        result = subprocess.run(
            [
                "pmtiles", "tile", archive, str(coordinate.zoom),
                str(coordinate.x), str(coordinate.y),
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"pmtiles tile failed for {coordinate.zoom}/{coordinate.x}/{coordinate.y}: "
                f"{message or f'exit {result.returncode}'}"
            )
        if not result.stdout:
            return {}
        try:
            import mapbox_vector_tile
        except ImportError as error:
            raise RuntimeError(
                f"mapbox_vector_tile cannot be loaded for tile sampling: {error}; "
                "run inside devbox and check make python-doctor"
            ) from error
        payload = result.stdout
        if payload.startswith(b"\x1f\x8b"):
            try:
                payload = gzip.decompress(payload)
            except OSError as error:
                raise RuntimeError(
                    f"invalid gzip vector tile for "
                    f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}: {error}"
                ) from error
        try:
            decoded = mapbox_vector_tile.decode(payload)
        except Exception as error:
            raise RuntimeError(
                f"invalid vector tile for "
                f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}: {error}"
            ) from error
        if not isinstance(decoded, dict):
            raise RuntimeError("decoded vector tile must be an object")
        return decoded
