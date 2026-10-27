from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from math import asinh, ceil, floor, hypot, isfinite, pi, radians, tan
from typing import Any, Iterable

from huavd_map_build.quality.domain.tile import TileCoordinate

GRID = 8
POLICY_VERSION = 1


@dataclass(frozen=True, slots=True)
class CoveragePolicy:
    zooms: tuple[int, ...] = (5, 6, 7)
    minimum_source_features: int = 50
    minimum_gap_cells: int = 2
    minimum_line_pixels: float = 2
    samples_per_zoom: int = 8
    gap_mode: str = "report"

    @classmethod
    def from_settings(cls, value: dict[str, Any]) -> CoveragePolicy:
        zooms = value.get("zooms")
        if (not isinstance(zooms, list) or not zooms
            or any(not _integer(z) or not 0 <= z <= 10 for z in zooms)
            or len(set(zooms)) != len(zooms)):
            raise ValueError("low_zoom_quality.zooms must be unique integers in 0..10")
        for key, maximum in (("minimum_source_features", 10000000),
                             ("minimum_gap_cells", 36), ("samples_per_zoom", 8)):
            if not _integer(value.get(key)) or not 1 <= value[key] <= maximum:
                raise ValueError(f"low_zoom_quality.{key} must be an integer in 1..{maximum}")
        pixels = value.get("minimum_line_pixels")
        if not _number(pixels) or not 0 < pixels <= 256:
            raise ValueError("low_zoom_quality.minimum_line_pixels must be in (0, 256]")
        if not isinstance(value.get("gap_mode"), str) or value["gap_mode"] not in {"report", "error"}:
            raise ValueError("low_zoom_quality.gap_mode must be report or error")
        return cls(tuple(sorted(zooms)), value["minimum_source_features"],
                   value["minimum_gap_cells"], float(pixels), value["samples_per_zoom"], value["gap_mode"])

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "zooms": list(self.zooms), "grid": GRID, "version": POLICY_VERSION}


@dataclass(frozen=True, slots=True)
class CoverageSample:
    coordinate: TileCoordinate
    counts: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourceCoverage:
    session: str
    policy: CoveragePolicy
    zooms: tuple[int, ...]
    road_features: int
    eligible_features: tuple[tuple[int, int], ...]
    samples: tuple[CoverageSample, ...]
    available_tiles: int
    audit_points: tuple[tuple[float, float, int, int, float], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "session": self.session, "policy": self.policy.as_dict(), "zooms": list(self.zooms),
            "road_features": self.road_features, "eligible_features": {str(z): count for z, count in self.eligible_features},
            "available_tiles": self.available_tiles,
            "highest_zoom_candidate_points": [list(point) for point in self.audit_points],
            "samples": [{"z": sample.coordinate.zoom, "x": sample.coordinate.x,
                         "y": sample.coordinate.y, "source_counts": list(sample.counts)}
                        for sample in self.samples],
        }


class RoadCoverageAccumulator:
    def __init__(self, session: str, settings: dict[str, Any], policy: CoveragePolicy) -> None:
        self.session, self.policy = session, policy
        self.zooms = tuple(z for z in policy.zooms if settings["min_zoom"] <= z <= settings["max_zoom"])
        self.counts: dict[TileCoordinate, Counter[int]] = {}
        self.road_features = 0
        self.eligible = Counter()
        self.audit_points: dict[tuple[float, float, int, int, float], None] = {}

    def add(self, feature: dict[str, Any]) -> None:
        self.road_features += 1
        declaration = feature.get("tippecanoe", {})
        if not isinstance(declaration, dict):
            raise ValueError("road tippecanoe member must be an object")
        minimum, maximum = declaration.get("minzoom", 0), declaration.get("maxzoom", 24)
        if not _integer(minimum) or not _integer(maximum) or not 0 <= minimum <= maximum <= 24:
            raise ValueError("invalid road tippecanoe zoom range")
        lines = list(_lines(feature.get("geometry")))
        projected = []
        spans = []
        for line in lines:
            unwrapped = []
            for point in line:
                x, y = _project(point)
                if unwrapped:
                    x += round(unwrapped[-1][0] - x)
                unwrapped.append((x, y))
            projected.append(unwrapped)
            span = hypot(max(p[0] for p in unwrapped)-min(p[0] for p in unwrapped),
                         max(p[1] for p in unwrapped)-min(p[1] for p in unwrapped))
            spans.append(span)
            if span > 0 and len(self.audit_points) < 256:
                lon, lat = line[0][:2]
                self.audit_points.setdefault((lon, lat, minimum, maximum, span), None)
        for zoom in self.zooms:
            if not minimum <= zoom <= maximum:
                continue
            scale = (1 << zoom) * GRID
            cells = set()
            for line, span in zip(projected, spans):
                if span * (1 << zoom) * 256 < self.policy.minimum_line_pixels:
                    continue
                for a, b in zip(line, line[1:]):
                    cells.update(_segment_cells(a[0]*scale, a[1]*scale, b[0]*scale, b[1]*scale))
            cells = {(gx % scale, gy) for gx, gy in cells if 0 <= gy < scale}
            if cells:
                self.eligible[zoom] += 1
            for gx, gy in cells:
                tile = TileCoordinate(zoom, gx // GRID, gy // GRID)
                self.counts.setdefault(tile, Counter())[gy % GRID * GRID + gx % GRID] += 1

    def finish(self) -> SourceCoverage:
        samples = []
        for zoom in self.zooms:
            candidates = [(tile, counts) for tile, counts in self.counts.items() if tile.zoom == zoom]
            candidates.sort(key=lambda item: (
                -sum(count >= self.policy.minimum_source_features for count in item[1].values()),
                -sum(item[1].values()), item[0].x, item[0].y,
            ))
            samples.extend(CoverageSample(tile, tuple(counts[i] for i in range(GRID*GRID)))
                           for tile, counts in candidates[:self.policy.samples_per_zoom])
        return SourceCoverage(self.session, self.policy, self.zooms, self.road_features,
                              tuple((z, self.eligible[z]) for z in self.zooms), tuple(samples), len(self.counts),
                              tuple(self.audit_points))


def decoded_road_cells(decoded: dict[str, Any]) -> set[int]:
    layer = decoded.get("road", {})
    if not layer:
        return set()
    extent = layer.get("extent")
    if not _number(extent) or extent <= 0:
        raise ValueError("decoded road layer has no valid MVT extent")
    features = layer.get("features")
    if not isinstance(features, list):
        raise ValueError("decoded road layer features must be an array")
    cells = set()
    padding = GRID * .5 / 256
    for feature in features:
        for line in _lines(feature.get("geometry")):
            points = [(p[0] / extent * GRID, (1 - p[1] / extent) * GRID) for p in line]
            for a, b in zip(points, points[1:]):
                clipped = _clip(a, b)
                if clipped is None:
                    continue
                x0, y0, x1, y1 = clipped
                for ox, oy in ((0, 0), (-padding, -padding), (-padding, padding),
                               (padding, -padding), (padding, padding)):
                    cells.update(y*GRID+x for x, y in _segment_cells(x0+ox, y0+oy, x1+ox, y1+oy)
                                 if 0 <= x < GRID and 0 <= y < GRID)
    return cells


def gap_components(sample: CoverageSample, occupied: set[int], policy: CoveragePolicy) -> tuple[tuple[int, ...], ...]:
    missing = {i for i, count in enumerate(sample.counts)
               if count >= policy.minimum_source_features and i not in occupied
               and 0 < i % GRID < GRID-1 and 0 < i // GRID < GRID-1}
    groups = []
    while missing:
        pending = [min(missing)]
        group = set(pending)
        missing.remove(pending[0])
        while pending:
            cell = pending.pop()
            for neighbor in (cell-1, cell+1, cell-GRID, cell+GRID):
                if neighbor in missing:
                    missing.remove(neighbor)
                    group.add(neighbor)
                    pending.append(neighbor)
        if len(group) >= policy.minimum_gap_cells:
            groups.append(tuple(sorted(group)))
    return tuple(groups)


def _segment_cells(x0: float, y0: float, x1: float, y1: float) -> set[tuple[int, int]]:
    times = {0.0, 1.0}
    for start, end in ((x0, x1), (y0, y1)):
        if end != start:
            for boundary in range(floor(min(start, end))+1, ceil(max(start, end))):
                times.add((boundary-start)/(end-start))
    ordered = sorted(times)
    return {(floor(x0+(x1-x0)*(a+b)/2), floor(y0+(y1-y0)*(a+b)/2))
            for a, b in zip(ordered, ordered[1:])}


def _clip(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float, float, float] | None:
    dx, dy = b[0]-a[0], b[1]-a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0]), (dx, GRID-a[0]), (-dy, a[1]), (dy, GRID-a[1])):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            low = max(low, q/p)
        else:
            high = min(high, q/p)
    if low > high:
        return None
    return a[0]+low*dx, a[1]+low*dy, a[0]+high*dx, a[1]+high*dy


def _lines(geometry: Any) -> Iterable[list[list[float]]]:
    if isinstance(geometry, dict) and geometry.get("type") in {
        "Point", "MultiPoint", "Polygon", "MultiPolygon",
    }:
        if not isinstance(geometry.get("coordinates"), list):
            raise ValueError("road coordinates must be arrays")
        return
    if not isinstance(geometry, dict) or geometry.get("type") not in {"LineString", "MultiLineString"}:
        raise ValueError("unsupported road geometry type")
    coordinates = geometry.get("coordinates")
    lines = [coordinates] if geometry["type"] == "LineString" else coordinates
    if not isinstance(lines, list):
        raise ValueError("road coordinates must be arrays")
    for line in lines:
        if not isinstance(line, list) or len(line) < 2 or any(
            not isinstance(p, (list, tuple)) or len(p) < 2 or not _number(p[0]) or not _number(p[1]) for p in line
        ):
            raise ValueError("invalid road LineString coordinates")
        yield line


def _project(point: list[float]) -> tuple[float, float]:
    lon, lat = point[:2]
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("road coordinates outside longitude/latitude bounds")
    lat = max(-85.05112878, min(85.05112878, lat))
    return (lon+180)/360, (1-asinh(tan(radians(lat)))/pi)/2


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
