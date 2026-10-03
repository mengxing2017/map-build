from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import subprocess
from typing import Any

from huavd_map_build.production.domain.style import default_zoom


class PmtilesViewportReader:
    def read(self, path: str) -> dict[str, Any]:
        bounds = self._bounds(path)
        center = self._bounds_center(bounds)
        executable = shutil.which("pmtiles")
        decoder = self._decoder()
        if executable is not None and decoder is not None:
            center = self._label_center(executable, path, bounds, decoder)
        return {
            "center": [round(center[0], 6), round(center[1], 6)],
            "default_zoom": default_zoom(bounds), "min_zoom": 0, "max_zoom": 18,
        }

    @staticmethod
    def _bounds(path: str) -> tuple[float, float, float, float]:
        with Path(path).open("rb") as stream:
            stream.seek(102)
            payload = stream.read(16)
        if len(payload) != 16:
            raise ValueError(f"invalid PMTiles header: {path}")
        return tuple(value / 10_000_000 for value in struct.unpack("<iiii", payload))

    @staticmethod
    def _bounds_center(bounds: tuple[float, float, float, float]) -> tuple[float, float]:
        return (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2

    @staticmethod
    def _decoder():
        try:
            import mapbox_vector_tile
        except (ImportError, OSError):
            return None
        return mapbox_vector_tile.decode

    def _label_center(self, executable: str, path: str,
                      bounds: tuple[float, float, float, float], decoder) -> tuple[float, float]:
        zoom = 4
        middle_latitude = (bounds[1] + bounds[3]) / 2
        x_min, y_min = self._lnglat_to_tile(zoom, bounds[0], middle_latitude)
        x_max, y_max = self._lnglat_to_tile(zoom, bounds[2], middle_latitude)
        maximum = (1 << zoom) - 1
        x_min, y_min = max(0, x_min - 1), max(0, y_min - 1)
        x_max, y_max = min(maximum, x_max + 1), min(maximum, y_max + 1)
        best_score = 0
        best = None
        weights = {"country_capital": 1000, "state_capital": 100,
                   "region_capital": 50, "city": 10, "town": 1}
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                result = subprocess.run(
                    [executable, "tile", path, str(zoom), str(x), str(y)],
                    capture_output=True, check=False,
                )
                if result.returncode != 0 or not result.stdout:
                    continue
                try:
                    tile = decoder(result.stdout)
                    features = tile.get("place_label", {}).get("features", [])
                    score = sum(weights.get(
                        feature.get("properties", {}).get("place", ""), 1
                    ) for feature in features)
                except Exception:
                    score = 0
                if score > best_score:
                    best_score, best = score, (x, y)
        return self._tile_to_lnglat(zoom, *best) if best is not None else self._bounds_center(bounds)

    @staticmethod
    def _lnglat_to_tile(zoom: int, longitude: float, latitude: float) -> tuple[int, int]:
        x = int((longitude + 180.0) / 360.0 * (2 ** zoom))
        y = int((1.0 - math.asinh(math.tan(math.radians(latitude))) / math.pi)
                / 2.0 * (2 ** zoom))
        return x, y

    @staticmethod
    def _tile_to_lnglat(zoom: int, x: int, y: int) -> tuple[float, float]:
        scale = 2 ** zoom
        longitude = x / scale * 360.0 - 180.0
        latitude = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale))))
        return longitude, latitude
