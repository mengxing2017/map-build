from __future__ import annotations

from dataclasses import dataclass
from math import asinh, floor, pi, radians, tan
from typing import Any

from huavd_map_build.quality.domain.vector import QualityFinding


@dataclass(frozen=True, slots=True)
class TileCoordinate:
    zoom: int
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class VectorTilePayload:
    decoded: dict[str, Any]
    compressed_bytes: int
    uncompressed_bytes: int


@dataclass(frozen=True, slots=True)
class TileSamplePlan:
    island: tuple[TileCoordinate, ...]
    river: tuple[TileCoordinate, ...]

    @property
    def coordinates(self) -> tuple[TileCoordinate, ...]:
        return tuple(dict.fromkeys((*self.island, *self.river)))


@dataclass(frozen=True, slots=True)
class TileSamplingReport:
    sampled_tiles: tuple[TileCoordinate, ...]
    findings: tuple[QualityFinding, ...]
    coverage_audit: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, object]:
        result = {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "sampled_tiles": [
                {"z": item.zoom, "x": item.x, "y": item.y}
                for item in self.sampled_tiles
            ],
            "findings": [finding.as_dict() for finding in self.findings],
        }
        if self.coverage_audit is not None:
            result["low_zoom_coverage"] = self.coverage_audit
        return result


def representative_lonlat(feature: dict[str, Any]) -> tuple[float, float] | None:
    geometry = feature.get("geometry")
    coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
    return _first_lonlat(coordinates)


def lonlat_to_tile(longitude: float, latitude: float, zoom: int) -> TileCoordinate:
    latitude = max(-85.05112878, min(85.05112878, latitude))
    scale = 1 << zoom
    x = floor((longitude + 180.0) / 360.0 * scale)
    value = asinh(tan(radians(latitude)))
    y = floor((1.0 - value / pi) / 2.0 * scale)
    return TileCoordinate(zoom, max(0, min(scale - 1, x)), max(0, min(scale - 1, y)))


def verify_sampled_tiles(
    plan: TileSamplePlan, decoded: dict[TileCoordinate, dict[str, Any]]
) -> TileSamplingReport:
    findings: list[QualityFinding] = []
    island_tiles = [decoded[item] for item in plan.island if item in decoded]
    river_tiles = [decoded[item] for item in plan.river if item in decoded]
    if plan.island:
        water_islands = sum(
            _count(layer, "water", "place", {"island", "islet"})
            for layer in island_tiles
        )
        island_features = sum(
            _count(layer, "island", "place", {"island", "islet"})
            for layer in island_tiles
        )
        if water_islands:
            findings.append(QualityFinding(
                "tile-water-island",
                f"sampled water layer contains {water_islands} island/islet features",
            ))
        if island_features == 0:
            findings.append(QualityFinding(
                "tile-island-missing",
                "sampled island tiles contain no place=island/islet feature",
            ))
    if plan.river:
        waterway = _features(river_tiles, "waterway")
        subtype = [
            feature for feature in waterway
            if isinstance(feature.get("properties", {}).get("waterway"), str)
            and feature["properties"]["waterway"]
        ]
        rivers = [
            feature for feature in subtype
            if feature["properties"].get("waterway") == "river"
        ]
        if not waterway:
            findings.append(QualityFinding(
                "tile-waterway-missing", "sampled river tiles contain no waterway features"
            ))
        elif not subtype:
            findings.append(QualityFinding(
                "tile-waterway-subtype", "sampled waterway features have no subtype"
            ))
        if not rivers:
            findings.append(QualityFinding(
                "tile-river-missing", "sampled river tiles contain no waterway=river feature"
            ))
    return TileSamplingReport(plan.coordinates, tuple(findings))


def _first_lonlat(value: object) -> tuple[float, float] | None:
    if (
        isinstance(value, list) and len(value) >= 2
        and _number(value[0]) and _number(value[1])
    ):
        longitude, latitude = float(value[0]), float(value[1])
        if -180 <= longitude <= 180 and -90 <= latitude <= 90:
            return longitude, latitude
        return None
    if isinstance(value, list):
        for child in value:
            result = _first_lonlat(child)
            if result is not None:
                return result
    return None


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _features(tiles: list[dict[str, Any]], layer: str) -> list[dict[str, Any]]:
    result = []
    for tile in tiles:
        value = tile.get(layer, {})
        features = value.get("features", []) if isinstance(value, dict) else []
        result.extend(feature for feature in features if isinstance(feature, dict))
    return result


def _count(
    tile: dict[str, Any], layer: str, field: str, values: set[str]
) -> int:
    return sum(
        feature.get("properties", {}).get(field) in values
        for feature in _features([tile], layer)
    )
