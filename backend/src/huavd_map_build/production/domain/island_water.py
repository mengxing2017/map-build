from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from huavd_map_build.shared.kernel import RegionId, SessionId


@dataclass(frozen=True, slots=True)
class IslandWaterRequest:
    region: RegionId
    session: SessionId
    workdir: str


@dataclass(frozen=True, slots=True)
class IslandCandidate:
    index: int
    bbox: tuple[float, float, float, float]
    area: float
    samples: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class WaterMatch:
    index: int
    area: float
    inside_ratio: float
    water_index: int


@dataclass(frozen=True, slots=True)
class IslandWaterResult:
    island_feature_count: int
    island_polygon_count: int
    water_feature_count: int
    in_water_count: int
    report_path: str


def polygon_parts(geometry: Any) -> list[Any]:
    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") == "Polygon":
        value = geometry.get("coordinates")
        return [value] if isinstance(value, list) else []
    if geometry.get("type") == "MultiPolygon":
        value = geometry.get("coordinates")
        return value if isinstance(value, list) else []
    return []


def candidate_from_feature(
    index: int, feature: dict[str, Any], max_samples: int = 120
) -> IslandCandidate | None:
    polygons = polygon_parts(feature.get("geometry"))
    if not polygons:
        return None
    points = [point for polygon in polygons for ring in polygon for point in ring]
    outer = [point for polygon in polygons for point in polygon[0]]
    if not points or not outer:
        return None
    step = max(1, math.ceil(len(outer) / max_samples))
    samples = tuple((point[0], point[1]) for point in outer[::step][:max_samples])
    return IslandCandidate(
        index,
        (min(p[0] for p in points), min(p[1] for p in points),
         max(p[0] for p in points), max(p[1] for p in points)),
        sum(_ring_area(polygon[0]) for polygon in polygons),
        samples,
    )


def match_water(
    candidate: IslandCandidate,
    water_geometry: dict[str, Any],
    water_index: int,
    minimum_ratio: float = 0.999,
) -> WaterMatch | None:
    matches = match_water_candidates(
        (candidate,), water_geometry, water_index, minimum_ratio
    )
    return matches[0] if matches else None


def match_water_candidates(
    candidates: tuple[IslandCandidate, ...] | list[IslandCandidate],
    water_geometry: dict[str, Any],
    water_index: int,
    minimum_ratio: float = 0.999,
) -> tuple[WaterMatch, ...]:
    polygons = polygon_parts(water_geometry)
    if not polygons:
        return ()
    points = [point for polygon in polygons for ring in polygon for point in ring]
    if not points:
        return ()
    bbox = (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))
    water_area = sum(_ring_area(polygon[0]) for polygon in polygons)
    result = []
    for candidate in candidates:
        island_bbox = candidate.bbox
        if not (
            candidate.area <= water_area
            and island_bbox[0] >= bbox[0] and island_bbox[1] >= bbox[1]
            and island_bbox[2] <= bbox[2] and island_bbox[3] <= bbox[3]
        ):
            continue
        inside = sum(
            1 for point in candidate.samples
            if any(_inside_polygon(point, polygon) for polygon in polygons)
        )
        ratio = inside / len(candidate.samples) if candidate.samples else 0.0
        if ratio >= minimum_ratio:
            result.append(
                WaterMatch(candidate.index, candidate.area, ratio, water_index)
            )
    return tuple(result)


def _ring_area(ring: list[Any]) -> float:
    if len(ring) < 3:
        return 0.0
    return abs(sum(
        first[0] * ring[(index + 1) % len(ring)][1]
        - ring[(index + 1) % len(ring)][0] * first[1]
        for index, first in enumerate(ring)
    )) / 2


def _inside_ring(point: tuple[float, float], ring: list[Any]) -> bool:
    inside = False
    previous = len(ring) - 1
    for index, current in enumerate(ring):
        xi, yi = current[0], current[1]
        xj, yj = ring[previous][0], ring[previous][1]
        if (yi > point[1]) != (yj > point[1]) and point[0] < (
            (xj - xi) * (point[1] - yi) / (yj - yi) + xi
        ):
            inside = not inside
        previous = index
    return inside


def _inside_polygon(point: tuple[float, float], polygon: list[Any]) -> bool:
    return bool(polygon) and _inside_ring(point, polygon[0]) and not any(
        _inside_ring(point, hole) for hole in polygon[1:]
    )
