from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from huavd_map_build.shared.kernel import RegionId, SessionId

_REFINE_DEPTH = 24
_REFINE_VISITS = 4096


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
    segments = _ring_segments(polygons)
    for polygon in sorted(polygons, key=lambda item: -_ring_area(item[0])):
        point = _refined_interior(polygon, polygons, segments)
        if point is not None:
            return point, "grid"
    return list(outer[0]), "vertex"


def _refined_interior(
    polygon: list[Any], polygons: list[Any], segments: list[tuple[Any, Any]]
) -> list[float] | None:
    outer = polygon[0]
    xs = [point[0] for point in outer]
    ys = [point[1] for point in outer]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    if max_x <= min_x or max_y <= min_y or not segments:
        return None
    half = max(max_x - min_x, max_y - min_y) / 2
    stack = [((min_x + max_x) / 2, (min_y + max_y) / 2, half, 0)]
    visits = 0
    while stack and visits < _REFINE_VISITS:
        x, y, size, depth = stack.pop()
        visits += 1
        if depth >= _REFINE_DEPTH:
            continue
        quarter = size / 2
        children = []
        found = None
        for x_offset in (-quarter, quarter):
            for y_offset in (-quarter, quarter):
                point = [x + x_offset, y + y_offset]
                if _inside(point, polygons):
                    found = point
                    break
                distance = _boundary_distance(point, segments)
                if distance <= quarter * math.sqrt(2):
                    children.append((point[0], point[1], quarter, distance))
            if found is not None:
                break
        if found is not None:
            return found
        children.sort(key=lambda child: (child[3], child[0], child[1]))
        for child_x, child_y, child_half, _distance in reversed(children):
            stack.append((child_x, child_y, child_half, depth + 1))
    return None


def _ring_segments(polygons: list[Any]) -> list[tuple[Any, Any]]:
    segments = []
    for polygon in polygons:
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 2:
                continue
            for index, first in enumerate(ring):
                segments.append((first, ring[(index + 1) % len(ring)]))
    return segments


def _boundary_distance(point: list[float], segments: list[tuple[Any, Any]]) -> float:
    return min(
        _segment_distance(point, first, second) for first, second in segments
    )


def _segment_distance(point: list[float], first: Any, second: Any) -> float:
    x, y = point
    start_x, start_y = first[0], first[1]
    delta_x, delta_y = second[0] - start_x, second[1] - start_y
    span = delta_x * delta_x + delta_y * delta_y
    if span == 0:
        return math.hypot(x - start_x, y - start_y)
    ratio = max(
        0.0, min(1.0, ((x - start_x) * delta_x + (y - start_y) * delta_y) / span)
    )
    return math.hypot(
        x - (start_x + ratio * delta_x), y - (start_y + ratio * delta_y)
    )
