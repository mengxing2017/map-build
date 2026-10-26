from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import math
import struct
from copy import deepcopy
from typing import Any


WEB_MERCATOR_LIMIT = 85.05112878


class MissingRasterToolError(RuntimeError):
    pass


class RasterExecutionError(RuntimeError):
    pass


class RasterNonRetryableError(RasterExecutionError):
    """A fixed input or installation error cannot improve by retrying a tile."""


class RasterBatchExecutionError(RasterExecutionError):
    def __init__(self, failed_tiles: int, samples: tuple[str, ...],
                 metrics: dict[str, Any] | None = None) -> None:
        detail = "; ".join(samples)
        super().__init__(
            f"raster tile execution failed for {failed_tiles} tile(s)"
            + (f": {detail}" if detail else "")
        )
        self.failed_tiles = failed_tiles
        self.samples = samples
        self.metrics = metrics or {}


@dataclass(frozen=True, slots=True)
class RasterBounds:
    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("raster bounds must satisfy -180 <= west < east <= 180")
        if not (-WEB_MERCATOR_LIMIT <= self.south < self.north <= WEB_MERCATOR_LIMIT):
            raise ValueError("raster bounds exceed the Web Mercator latitude range")

    def as_list(self) -> list[float]:
        return [self.west, self.south, self.east, self.north]


@dataclass(frozen=True, slots=True)
class RasterTileRange:
    zoom: int
    x_min: int
    x_max: int
    y_min: int
    y_max: int

    @property
    def tile_count(self) -> int:
        return (self.x_max - self.x_min + 1) * (self.y_max - self.y_min + 1)

    def as_dict(self) -> dict[str, object]:
        return {
            "zoom": self.zoom,
            "tile_count": self.tile_count,
            "x_range": [self.x_min, self.x_max],
            "y_range": [self.y_min, self.y_max],
        }


@dataclass(frozen=True, slots=True)
class RasterTileCoordinate:
    zoom: int
    x: int
    y: int

    @property
    def center(self) -> tuple[float, float]:
        size = 1 << self.zoom
        longitude = (self.x + 0.5) / size * 360.0 - 180.0
        latitude = math.degrees(math.atan(math.sinh(
            math.pi * (1.0 - 2.0 * (self.y + 0.5) / size)
        )))
        return longitude, latitude

    @property
    def bounds(self) -> RasterBounds:
        size = 1 << self.zoom
        west = self.x / size * 360.0 - 180.0
        east = (self.x + 1) / size * 360.0 - 180.0
        north = math.degrees(math.atan(math.sinh(
            math.pi * (1.0 - 2.0 * self.y / size)
        )))
        south = math.degrees(math.atan(math.sinh(
            math.pi * (1.0 - 2.0 * (self.y + 1) / size)
        )))
        return RasterBounds(west, south, east, north)

    def tsv(self) -> str:
        longitude, latitude = self.center
        bounds = self.bounds
        return (
            f"{self.zoom}\t{self.x}\t{self.y}\t{longitude:.8f}\t{latitude:.8f}\t"
            f"{bounds.west:.12f},{bounds.south:.12f},"
            f"{bounds.east:.12f},{bounds.north:.12f}\n"
        )

    @classmethod
    def from_tsv(cls, line: str) -> RasterTileCoordinate:
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 3:
            raise ValueError("raster tile row must contain zoom, x, and y")
        try:
            coordinate = cls(*(int(value) for value in fields[:3]))
        except ValueError as error:
            raise ValueError("raster tile coordinates must be integers") from error
        size = 1 << coordinate.zoom if coordinate.zoom >= 0 else 0
        if coordinate.zoom < 0 or coordinate.x < 0 or coordinate.y < 0:
            raise ValueError("raster tile coordinates must be non-negative")
        if coordinate.x >= size or coordinate.y >= size:
            raise ValueError("raster tile coordinate exceeds its zoom extent")
        return coordinate


@dataclass(frozen=True, slots=True)
class RasterRenderSettings:
    style_path: str
    png_directory: str
    webp_directory: str
    tile_size: int = 256
    renderer_engine: str = "mbgl-renderer"
    renderer_command: str = "mbgl-render"
    webp_lossless: bool = True
    webp_method: int = 6
    webp_metadata: str = "none"
    timeout_seconds: int = 120
    parallel_jobs: int = 1
    retries: int = 0
    batch_tiles: int | None = None
    display: str | None = None

    def __post_init__(self) -> None:
        if self.renderer_engine not in ("mbgl-renderer", "maplibre-native", "maplibre-native-headless"):
            raise ValueError(f"unsupported raster renderer: {self.renderer_engine}")
        if not self.style_path or not self.renderer_command:
            raise ValueError("raster style and renderer command must not be empty")
        if self.tile_size <= 0 or self.timeout_seconds <= 0:
            raise ValueError("raster tile size and timeout must be positive")
        if not 0 <= self.webp_method <= 6:
            raise ValueError("raster WebP method must be between 0 and 6")
        if self.parallel_jobs <= 0 or self.retries < 0:
            raise ValueError("raster parallel jobs must be positive and retries non-negative")
        validate_raster_batch_tiles(self.batch_tiles)
        if self.renderer_engine == "maplibre-native-headless":
            if self.tile_size not in (256, 512):
                raise ValueError("native headless tile size must be 256 or 512")
            if self.display:
                raise ValueError("native headless renderer cannot use DISPLAY")


@dataclass(frozen=True, slots=True)
class RasterDisplaySettings:
    mode: str = "managed-xvfb"
    screen: str = "1024x768x24"
    startup_timeout_seconds: float = 10.0
    log_path: str = "xvfb.log"

    def __post_init__(self) -> None:
        if self.mode not in ("managed-xvfb", "external-x11", "headless"):
            raise ValueError(f"unsupported raster display mode: {self.mode}")
        if not self.screen or self.startup_timeout_seconds <= 0:
            raise ValueError("raster display screen and startup timeout must be valid")


@dataclass(frozen=True, slots=True)
class RasterDisplayEndpoint:
    display: str
    mode: str
    server_pid: int | None
    startup_ms: float


@dataclass(frozen=True, slots=True)
class RasterRenderResult:
    planned_tiles: int
    rendered_tiles: int
    attempts: int
    retried_tiles: int
    failure_counts: dict[str, int] = field(default_factory=dict)
    exit_code_counts: dict[str, int] = field(default_factory=dict)


def validate_raster_batch_tiles(batch_tiles: int | None) -> int | None:
    if batch_tiles is not None and (
        isinstance(batch_tiles, bool) or not isinstance(batch_tiles, int)
        or batch_tiles <= 0
    ):
        raise ValueError("raster batch_tiles must be a positive integer when set")
    return batch_tiles


@dataclass(frozen=True, slots=True)
class RasterRenderBatchResult:
    index: int
    planned_tiles: int
    rendered_tiles: int
    failed_tiles: int
    failed_samples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.index <= 0 or self.planned_tiles < 0 or self.rendered_tiles < 0:
            raise ValueError("raster batch counters must be non-negative with a positive index")
        if self.rendered_tiles + self.failed_tiles > self.planned_tiles:
            raise ValueError("raster batch counters exceed the planned tiles")


@dataclass(frozen=True, slots=True)
class RasterAssemblySettings:
    name: str
    bounds: RasterBounds
    min_zoom: int
    max_zoom: int
    webp_directory: str
    tile_size: int = 256
    description: str = "HUAVD raster baked non-label base map"
    attribution: str = "\u00a9 OpenStreetMap contributors"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("raster archive name must not be empty")
        if self.min_zoom < 0 or self.max_zoom < self.min_zoom:
            raise ValueError("raster archive zoom range is invalid")
        if self.tile_size <= 0:
            raise ValueError("raster archive tile size must be positive")


@dataclass(frozen=True, slots=True)
class RasterAssemblyResult:
    expected_tiles: int
    inserted_tiles: int
    tile_bytes: int
    verified_tiles: int = 0
    timings: tuple[RasterStageTiming, ...] = ()


@dataclass(frozen=True, slots=True)
class RasterTileServerEndpoint:
    tile_url: str
    port: int


@dataclass(frozen=True, slots=True)
class RasterMvtPreflightResult:
    url: str
    payload_bytes: int
    elapsed_ms: float
    layers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RasterCachePreparation:
    identity: str
    invalidated: bool


@dataclass(frozen=True, slots=True)
class RasterStageTiming:
    stage: str
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class RasterBakeResult:
    cache: RasterCachePreparation
    initial_scan: RasterCacheScanResult
    final_scan: RasterCacheScanResult
    render: RasterRenderResult | None
    assembly: RasterAssemblyResult
    preflight: RasterMvtPreflightResult
    timings: tuple[RasterStageTiming, ...]
    runtime_evidence: tuple[dict[str, Any], ...] = ()
    source_metadata: RasterSourceMetadata | None = None
    run_identity: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "cache_identity": self.cache.identity,
            "run_identity": self.run_identity,
            "cache_invalidated": self.cache.invalidated,
            "planned_tiles": self.initial_scan.planned_tiles,
            "initial_cache_hits": self.initial_scan.cache_hits,
            "rendered_tiles": 0 if self.render is None else self.render.rendered_tiles,
            "final_cache_hits": self.final_scan.cache_hits,
            "assembled_tiles": self.assembly.inserted_tiles,
            "readback_tiles": self.assembly.verified_tiles,
            "preflight": {
                "url": self.preflight.url,
                "bytes": self.preflight.payload_bytes,
                "elapsed_ms": self.preflight.elapsed_ms,
            },
            "runtime_source": None if self.source_metadata is None else self.source_metadata.as_dict(),
            "preflight_samples": list(self.runtime_evidence),
            "phases_ms": {item.stage: item.elapsed_ms for item in self.timings},
            "assembly_phases_ms": {
                item.stage: item.elapsed_ms for item in self.assembly.timings
            },
        }


def raster_parameters_document(
    identity: RasterCacheIdentity, settings: RasterRenderSettings,
    display: RasterDisplaySettings,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cache_identity": identity.digest,
        "run_identity": identity.run_digest,
        "runtime_source": identity.runtime_document(),
        "plan": identity.plan.as_dict(),
        "renderer": {
            "engine": settings.renderer_engine,
            "command": settings.renderer_command,
            "identity": identity.renderer_identity,
            "timeout_seconds": settings.timeout_seconds,
        },
        "execution": {
            "parallel_jobs": settings.parallel_jobs,
            "retries": settings.retries,
            "batch_tiles": settings.batch_tiles,
            "display": {
                "mode": display.mode,
                "screen": display.screen,
                "startup_timeout_seconds": display.startup_timeout_seconds,
            },
        },
        "effective": {
            "bounds": ",".join(str(value) for value in identity.plan.bounds.as_list()),
            "min_zoom": identity.plan.min_zoom,
            "max_zoom": identity.plan.max_zoom,
            "tile_size": settings.tile_size,
            "parallel_jobs": settings.parallel_jobs,
            "webp_lossless": settings.webp_lossless,
            "max_tiles": identity.plan.max_tiles,
            "tile_timeout_seconds": settings.timeout_seconds,
            "renderer": {
                "engine": settings.renderer_engine,
                "identity": identity.renderer_identity,
            },
        },
        "image": {
            "tile_size": settings.tile_size,
            "pixel_ratio": identity.pixel_ratio,
            "encoding": "webp",
            "lossless": settings.webp_lossless,
            "method": settings.webp_method,
            "metadata": settings.webp_metadata,
        },
        "inputs": {
            "base_sha512": identity.base_sha512,
            "style_sha512": identity.style_sha512,
            "configuration_sha512": identity.configuration_sha512,
        },
    }


def raster_metrics_document(
    result: RasterBakeResult, mbtiles_bytes: int, pmtiles_bytes: int,
) -> dict[str, Any]:
    render = result.render
    return {
        "schema_version": 1,
        "cache_identity": result.cache.identity,
        "run_identity": result.run_identity,
        "cache_invalidated": result.cache.invalidated,
        "planned_tiles": result.initial_scan.planned_tiles,
        "cache": {
            "initial_hits": result.initial_scan.cache_hits,
            "initial_missing": result.initial_scan.missing_tiles,
            "structurally_invalid": result.initial_scan.structurally_invalid_tiles,
            "unverified": result.initial_scan.unverified_tiles,
            "final_hits": result.final_scan.cache_hits,
            "final_missing": result.final_scan.missing_tiles,
        },
        "render": {
            "worker_queue_tiles": 0 if render is None else render.planned_tiles,
            "rendered_tiles": 0 if render is None else render.rendered_tiles,
            "attempts": 0 if render is None else render.attempts,
            "retried_tiles": 0 if render is None else render.retried_tiles,
            "failure_counts": {} if render is None else render.failure_counts,
            "exit_code_counts": {} if render is None else render.exit_code_counts,
        },
        "mvt_service_preflight": {
            "url": result.preflight.url,
            "bytes": result.preflight.payload_bytes,
            "elapsed_ms": result.preflight.elapsed_ms,
        },
        "mbtiles_assembly": {
            "expected_tiles": result.assembly.expected_tiles,
            "inserted_tiles": result.assembly.inserted_tiles,
            "tile_bytes": result.assembly.tile_bytes,
        },
        "runtime_source": None if result.source_metadata is None else result.source_metadata.as_dict(),
        "preflight_samples": list(result.runtime_evidence),
        "phases_ms": {item.stage: item.elapsed_ms for item in result.timings},
        "assembly_phases_ms": {
            item.stage: item.elapsed_ms for item in result.assembly.timings
        },
        "quality": {"visual_grid_validation": "not-run",
                    "readback_tiles": result.assembly.verified_tiles},
        "artifacts": {
            "mbtiles_bytes": mbtiles_bytes,
            "pmtiles_bytes": pmtiles_bytes,
        },
    }


def rewrite_bake_source(
    document: dict[str, Any], tile_url: str | None = None,
    archive_path: str | None = None,
    metadata: RasterSourceMetadata | None = None,
) -> dict[str, Any]:
    if (tile_url is None) == (archive_path is None):
        raise ValueError("exactly one raster runtime source must be provided")
    sources = document.get("sources")
    if not isinstance(sources, dict) or len(sources) != 1:
        raise ValueError("bake style must contain exactly one source")
    source_id, source = next(iter(sources.items()))
    if not isinstance(source, dict) or source.get("type") != "vector":
        raise ValueError("bake style source must be vector")
    result = deepcopy(document)
    runtime_source = result["sources"][source_id]
    if tile_url is not None:
        runtime_source.pop("url", None)
        runtime_source["tiles"] = [tile_url]
    else:
        runtime_source.pop("tiles", None)
        runtime_source["url"] = f"pmtiles://{archive_path}"
    if metadata is not None:
        runtime_source.update(metadata.as_dict())
    return result


@dataclass(frozen=True, slots=True)
class RasterContentSample:
    layer: str
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if (not self.layer or not math.isfinite(self.longitude) or not math.isfinite(self.latitude)
            or not -180 <= self.longitude < 180 or not -WEB_MERCATOR_LIMIT < self.latitude < WEB_MERCATOR_LIMIT):
            raise ValueError("sample requires LAYER,LON,LAT within Web Mercator bounds")

    def coordinate(self, zoom: int) -> RasterTileCoordinate:
        size = 1 << zoom
        x = int((self.longitude + 180) / 360 * size)
        y = int((1 - math.asinh(math.tan(math.radians(self.latitude))) / math.pi) / 2 * size)
        return RasterTileCoordinate(zoom, min(size-1, max(0, x)), min(size-1, max(0, y)))


@dataclass(frozen=True, slots=True)
class RasterSourceProbe:
    output_coordinate: RasterTileCoordinate
    expected_layer: str | None = None


@dataclass(frozen=True, slots=True)
class RasterSourceMetadata:
    min_zoom: int
    max_zoom: int
    bounds: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        if (isinstance(self.min_zoom, bool) or not isinstance(self.min_zoom, int)
            or isinstance(self.max_zoom, bool) or not isinstance(self.max_zoom, int)
            or not 0 <= self.min_zoom <= self.max_zoom <= 24):
            raise ValueError("source zooms must satisfy 0 <= min_zoom <= max_zoom <= 24")
        if len(self.bounds) != 4 or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) for value in self.bounds
        ):
            raise ValueError("source bounds must contain four finite numbers")
        west, south, east, north = self.bounds
        # PMTiles e7 header coordinates round the Mercator limit to 85.0511288.
        if not (-180 <= west < east <= 180 and -85.051129 <= south < north <= 85.051129):
            raise ValueError("source bounds exceed ordered Web Mercator extent")

    @classmethod
    def from_header(cls, header) -> RasterSourceMetadata:
        if header.tile_type != 1:
            raise ValueError("raster source archive must contain MVT tiles")
        return cls(header.min_zoom, header.max_zoom, tuple(header.bounds))

    def as_dict(self) -> dict[str, Any]:
        return {"minzoom": self.min_zoom, "maxzoom": self.max_zoom,
                "bounds": list(self.bounds), "scheme": "xyz"}

    def coordinate(self, coordinate: RasterTileCoordinate) -> RasterTileCoordinate:
        zoom = min(max(coordinate.zoom, self.min_zoom), self.max_zoom)
        if zoom <= coordinate.zoom:
            shift = coordinate.zoom - zoom
            return RasterTileCoordinate(zoom, coordinate.x >> shift, coordinate.y >> shift)
        longitude, latitude = coordinate.center
        size = 1 << zoom
        x = int((longitude + 180) / 360 * size)
        y = int((1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2 * size)
        return RasterTileCoordinate(zoom, min(size - 1, max(0, x)), min(size - 1, max(0, y)))


@dataclass(frozen=True, slots=True)
class RasterTilePlan:
    bounds: RasterBounds
    min_zoom: int
    max_zoom: int
    padding: int
    ranges: tuple[RasterTileRange, ...]
    max_tiles: int | None = None
    configured_max_tiles: int | None = None
    max_tiles_source: str = "config"

    @property
    def tile_count(self) -> int:
        return sum(item.tile_count for item in self.ranges)

    @property
    def within_limit(self) -> bool:
        return self.max_tiles is None or self.tile_count <= self.max_tiles

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "coverage_strategy": "bbox-rectangle-with-padding",
            "bounds": self.bounds.as_list(),
            "min_zoom": self.min_zoom,
            "max_zoom": self.max_zoom,
            "bbox_padding_tiles": self.padding,
            "max_tiles": self.max_tiles,
            "configured_max_tiles": self.configured_max_tiles,
            "max_tiles_source": self.max_tiles_source,
            "tile_count": self.tile_count,
            "tiles_by_zoom": [item.as_dict() for item in self.ranges],
        }

    def coordinates(self):
        for item in self.ranges:
            for x in range(item.x_min, item.x_max + 1):
                for y in range(item.y_min, item.y_max + 1):
                    yield RasterTileCoordinate(item.zoom, x, y)


@dataclass(frozen=True, slots=True)
class RasterCacheScanResult:
    planned_tiles: int
    cache_hits: int
    missing_tiles: int
    structurally_invalid_tiles: int
    unverified_tiles: int


@dataclass(frozen=True, slots=True)
class RasterCacheIdentity:
    base_sha512: str
    style_sha512: str
    configuration_sha512: str
    plan: RasterTilePlan
    tile_size: int
    pixel_ratio: int
    webp_lossless: bool
    webp_method: int
    webp_metadata: str
    renderer_engine: str
    renderer_identity: str
    source_metadata: RasterSourceMetadata | None = None
    subset_bounds: str | None = None
    subset_zooms: tuple[int, int] | None = None
    runtime_source_policy: str = "served-archive-v2"

    def __post_init__(self) -> None:
        for name in ("base_sha512", "style_sha512", "configuration_sha512"):
            value = getattr(self, name)
            if len(value) != 128 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a lowercase SHA-512 digest")
        if self.tile_size <= 0 or self.pixel_ratio != 1:
            raise ValueError("raster cache identity requires positive tile size and pixel_ratio=1")
        if not 0 <= self.webp_method <= 6:
            raise ValueError("raster WebP method must be between 0 and 6")
        if not self.renderer_engine or not self.renderer_identity:
            raise ValueError("raster renderer identity must not be empty")

    def runtime_document(self) -> dict[str, Any]:
        return {
            "policy": self.runtime_source_policy,
            "source": None if self.source_metadata is None else self.source_metadata.as_dict(),
            "subset_bounds": self.subset_bounds,
            "subset_zooms": self.subset_zooms,
        }

    @property
    def digest(self) -> str:
        document = {
            "schema_version": 2,
            "base_sha512": self.base_sha512,
            "style_sha512": self.style_sha512,
            "tile_size": self.tile_size,
            "pixel_ratio": self.pixel_ratio,
            "webp": {
                "lossless": self.webp_lossless,
                "method": self.webp_method,
                "metadata": self.webp_metadata,
            },
            "renderer": {
                "engine": self.renderer_engine,
                "identity": self.renderer_identity,
            },
            "tile_bounds_contract": "tile-bounds-v1",
            "runtime_source": self.runtime_document(),
        }
        return _sha512_document(document)

    @property
    def run_digest(self) -> str:
        document = {
            "schema_version": 2,
            "pixel_identity": self.digest,
            "configuration_sha512": self.configuration_sha512,
            "plan": self.plan.as_dict(),
        }
        return _sha512_document(document)


def _sha512_document(document: dict[str, Any]) -> str:
    payload = json.dumps(
        document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha512(payload).hexdigest()


def raster_progress_document(
    identity: RasterCacheIdentity, *, status: str,
    planned_tiles: int, queued_tiles: int, batch_tiles: int | None,
    batches_total: int, batches_completed: int,
    rendered_tiles: int, failed_tiles: int,
    failed_samples: tuple[str, ...] = (),
) -> dict[str, Any]:
    if status not in ("rendering", "rendered", "complete", "failed"):
        raise ValueError(f"unsupported raster progress status: {status}")
    return {
        "schema_version": 1,
        "status": status,
        "cache_identity": identity.digest,
        "run_identity": identity.run_digest,
        "planned_tiles": planned_tiles,
        "queued_tiles": queued_tiles,
        "batch_tiles": batch_tiles,
        "batches_total": batches_total,
        "batches_completed": batches_completed,
        "rendered_tiles": rendered_tiles,
        "failed_tiles": failed_tiles,
        "failed_samples": list(failed_samples),
    }


def webp_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 16 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        raise ValueError("invalid WebP container")
    offset = 12
    while offset + 8 <= len(payload):
        kind = payload[offset:offset + 4]
        length = struct.unpack_from("<I", payload, offset + 4)[0]
        chunk = payload[offset + 8:offset + 8 + length]
        if len(chunk) != length:
            raise ValueError("truncated WebP chunk")
        if kind == b"VP8 " and len(chunk) >= 10 and chunk[3:6] == b"\x9d\x01\x2a":
            return (
                struct.unpack_from("<H", chunk, 6)[0] & 0x3FFF,
                struct.unpack_from("<H", chunk, 8)[0] & 0x3FFF,
            )
        if kind == b"VP8L" and len(chunk) >= 5 and chunk[0] == 0x2F:
            bits = struct.unpack_from("<I", chunk, 1)[0]
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if kind == b"VP8X" and len(chunk) >= 10:
            return (
                int.from_bytes(chunk[4:7], "little") + 1,
                int.from_bytes(chunk[7:10], "little") + 1,
            )
        offset += 8 + length + (length & 1)
    raise ValueError("WebP dimensions are unreadable")


def create_raster_tile_plan(
    bounds: RasterBounds, min_zoom: int, max_zoom: int, padding: int,
    max_tiles: int | None = None,
    *, enforce_limit: bool = True,
) -> RasterTilePlan:
    if min_zoom < 0 or max_zoom < min_zoom or max_zoom > 30:
        raise ValueError("raster zooms must satisfy 0 <= min_zoom <= max_zoom <= 30")
    if padding < 0:
        raise ValueError("raster tile padding must be non-negative")
    if max_tiles is not None and (
        isinstance(max_tiles, bool) or not isinstance(max_tiles, int) or max_tiles <= 0
    ):
        raise ValueError("raster max_tiles must be a positive integer when set")
    ranges = tuple(
        _tile_range(bounds, zoom, padding)
        for zoom in range(min_zoom, max_zoom + 1)
    )
    plan = RasterTilePlan(
        bounds, min_zoom, max_zoom, padding, ranges, max_tiles, max_tiles,
    )
    if enforce_limit and not plan.within_limit:
        coverage = ",".join(str(value) for value in bounds.as_list())
        raise ValueError(
            f"raster bake plan exceeds max_tiles: planned={plan.tile_count} "
            f"max_tiles={max_tiles} bounds={coverage} "
            f"min_zoom={min_zoom} max_zoom={max_zoom} bbox_padding_tiles={padding}; "
            "inspect coverage with 'build raster-plan'; "
            "set --max-tiles explicitly for the total job budget"
        )
    return plan


def validate_raster_headroom_ratio(ratio: float | None) -> float | None:
    if ratio is None:
        return None
    if (
        isinstance(ratio, bool) or not isinstance(ratio, (int, float))
        or not math.isfinite(ratio) or ratio < 0
    ):
        raise ValueError(
            "raster max_tiles_headroom_ratio must be a non-negative finite number or null"
        )
    return float(ratio)


def extend_raster_plan_budget(
    plan: RasterTilePlan, ratio: float | None,
) -> RasterTilePlan:
    if ratio is None or plan.configured_max_tiles is None:
        return plan
    if plan.tile_count <= plan.configured_max_tiles:
        return plan
    effective = math.ceil(plan.tile_count * (1.0 + ratio))
    return replace(
        plan, max_tiles=effective, max_tiles_source="auto-headroom",
    )


def _tile_range(bounds: RasterBounds, zoom: int, padding: int) -> RasterTileRange:
    size = 1 << zoom
    maximum = size - 1

    def longitude_x(value: float) -> int:
        return math.floor((value + 180.0) / 360.0 * size)

    def latitude_y(value: float) -> int:
        radians = math.radians(value)
        projected = math.log(math.tan(radians) + 1.0 / math.cos(radians))
        return math.floor((1.0 - projected / math.pi) / 2.0 * size)

    x_min = max(0, min(maximum, longitude_x(bounds.west)) - padding)
    x_max = min(maximum, max(0, longitude_x(bounds.east)) + padding)
    y_min = max(0, min(maximum, latitude_y(bounds.north)) - padding)
    y_max = min(maximum, max(0, latitude_y(bounds.south)) + padding)
    return RasterTileRange(zoom, x_min, x_max, y_min, y_max)
