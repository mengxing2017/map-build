from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from huavd_map_build.shared.kernel import RegionId, SessionId


@dataclass(frozen=True, slots=True)
class IslandAnchorRequest:
    region: RegionId
    session: SessionId
    workdir: str


@dataclass(frozen=True, slots=True)
class IslandAnchorResult:
    polygon_count: int
    anchor_count: int
    point_feature_count_before: int
    tier_counts: dict[str, int]
    report_path: str


def derive_island_anchor(
    feature: dict[str, Any], grid_divisions: int = 7
) -> tuple[dict[str, Any], str] | None:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") == "Polygon":
        polygons = [geometry.get("coordinates")]
    elif geometry.get("type") == "MultiPolygon":
        polygons = geometry.get("coordinates")
    else:
        return None
    if not isinstance(polygons, list) or not polygons:
        return None
    polygons = [polygon for polygon in polygons if _valid_polygon(polygon)]
    if not polygons:
        return None
    point, tier = _interior(polygons, grid_divisions)
    square_degrees = sum(_ring_area(polygon[0]) for polygon in polygons)
    area = math.floor(square_degrees * 111.0 * 110.6 * 1000 + 0.5) / 1000
    source_properties = feature.get("properties")
    properties = dict(source_properties) if isinstance(source_properties, dict) else {}
    properties.pop("in_water", None)
    properties.update(
        {"island_anchor": True, "island_area_km2": area, "_anchor_tier": tier}
    )
    return (
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": point},
         "properties": properties},
        tier,
    )


def _valid_polygon(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and isinstance(value[0], list) and bool(value[0])


def _ring_area(ring: list[Any]) -> float:
    if len(ring) < 3:
        return 0.0
    total = 0.0
    for index, first in enumerate(ring):
        second = ring[(index + 1) % len(ring)]
        total += first[0] * second[1] - second[0] * first[1]
    return abs(total) / 2


def _ring_centroid(ring: list[Any]) -> list[float] | None:
    if len(ring) < 3:
        return None
    area_sum = x_sum = y_sum = 0.0
    for index, first in enumerate(ring):
        second = ring[(index + 1) % len(ring)]
        cross = first[0] * second[1] - second[0] * first[1]
        area_sum += cross
        x_sum += (first[0] + second[0]) * cross
        y_sum += (first[1] + second[1]) * cross
    if area_sum == 0:
        return None
    return [x_sum / (3 * area_sum), y_sum / (3 * area_sum)]


def _inside_ring(point: list[float], ring: list[Any]) -> bool:
    crossings = 0
    count = len(ring)
    if count < 3:
        return False
    for index in range(count):
        previous = (index - 1 + count) % count
        xi, yi = ring[index][0], ring[index][1]
        xj, yj = ring[previous][0], ring[previous][1]
        if (yi > point[1]) != (yj > point[1]) and point[0] < (
            (xj - xi) * (point[1] - yi) / (yj - yi) + xi
        ):
            crossings += 1
    return crossings % 2 == 1


def _inside_polygon(point: list[float], polygon: list[Any]) -> bool:
    return _inside_ring(point, polygon[0]) and not any(
        _inside_ring(point, hole) for hole in polygon[1:]
    )


def _inside(point: list[float], polygons: list[Any]) -> bool:
    return any(_inside_polygon(point, polygon) for polygon in polygons)


def _interior(polygons: list[Any], grid: int) -> tuple[list[float], str]:
    candidates = sorted(
        ((_ring_area(polygon[0]), _ring_centroid(polygon[0])) for polygon in polygons),
        key=lambda item: -item[0],
    )
    for _area, candidate in candidates:
        if candidate is not None and _inside(candidate, polygons):
            return candidate, "centroid"
    largest = max(polygons, key=lambda polygon: _ring_area(polygon[0]))
    outer = largest[0]
    xs = [point[0] for point in outer]
    ys = [point[1] for point in outer]
    for x_index in range(1, grid + 1):
        for y_index in range(1, grid + 1):
            point = [
                min(xs) + (max(xs) - min(xs)) * x_index / (grid + 1),
                min(ys) + (max(ys) - min(ys)) * y_index / (grid + 1),
            ]
            if _inside(point, polygons):
                return point, "grid"
    return list(outer[0]), "vertex"
