from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


class MissingPmtilesToolError(RuntimeError):
    pass


class MetadataEditError(RuntimeError):
    pass


class MetadataVerificationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PmtilesHeader:
    tile_type: int
    tile_compression: int
    min_zoom: int
    max_zoom: int
    bounds: tuple[float, float, float, float]
    internal_compression: int = 2
    root_offset: int = 0
    root_length: int = 0
    addressed_tiles_count: int = 0

    @property
    def center(self) -> tuple[float, float, int]:
        west, south, east, north = self.bounds
        return ((west + east) / 2, (south + north) / 2, 6)


@dataclass(frozen=True, slots=True)
class MetadataRequest:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    role: Role
    workdir: str
    pmtiles_path: str | None = None


@dataclass(frozen=True, slots=True)
class RasterMetadataRequest:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    workdir: str
    pmtiles_path: str
    tile_count: int
    tile_size: int


def compile_vector_metadata(
    *, stem: str, region: RegionId, role: Role, header: PmtilesHeader,
    vector_layers: list[dict[str, Any]], source_id: str,
    available_locales: tuple[str, ...], style_locales: tuple[str, ...],
    build_time: str, build_profile: str | None = None,
    build_profile_schema: int | None = None,
) -> dict[str, Any]:
    if role not in (Role.BASE, Role.BUILDING):
        raise MetadataVerificationError(
            f"vector metadata does not support role: {role.value}"
        )
    if header.tile_type != 1:
        raise MetadataVerificationError(
            f"PMTiles tile_type must be 1 (MVT), got {header.tile_type}"
        )
    if not source_id:
        raise ValueError(f"region has no source_id for metadata: {region.value}")
    document: dict[str, Any] = {
        "name": stem,
        "format": "pbf",
        "bounds": list(header.bounds),
        "center": list(header.center),
        "minzoom": header.min_zoom,
        "maxzoom": header.max_zoom,
        "attribution": "© OpenStreetMap contributors",
        "vector_layers": vector_layers,
        "huavd:source-id": source_id,
        "huavd:asset-role": (
            "building-vector" if role is Role.BUILDING else "base-vector"
        ),
        "huavd:available-locales": list(available_locales),
        "huavd:style-locales": list(style_locales),
        "huavd:build-time": build_time,
        "huavd:region": region.value,
        "huavd:data-license": "ODbL-1.0",
    }
    if build_profile:
        if build_profile_schema is None:
            raise ValueError("build profile metadata requires schema version")
        document["huavd:build-profile"] = build_profile
        document["huavd:build-profile-schema"] = build_profile_schema
    return document


def compile_raster_metadata(
    *, stem: str, region: RegionId, header: PmtilesHeader, source_id: str,
    available_locales: tuple[str, ...], style_locales: tuple[str, ...],
    build_time: str, tile_count: int, tile_size: int,
) -> dict[str, Any]:
    if header.tile_type != 4:
        raise MetadataVerificationError(
            f"raster PMTiles tile_type must be 4 (WebP), got {header.tile_type}"
        )
    if header.tile_compression != 1:
        raise MetadataVerificationError(
            "raster PMTiles tile_compression must be 1 (none), "
            f"got {header.tile_compression}"
        )
    if not source_id:
        raise ValueError(f"region has no source_id for metadata: {region.value}")
    if tile_count <= 0 or tile_size <= 0:
        raise ValueError("raster metadata tile count and tile size must be positive")
    return {
        "name": stem,
        "format": "webp",
        "bounds": list(header.bounds),
        "center": list(header.center),
        "minzoom": header.min_zoom,
        "maxzoom": header.max_zoom,
        "attribution": "\u00a9 OpenStreetMap contributors",
        "vector_layers": [],
        "huavd:source-id": source_id,
        "huavd:asset-role": "raster-baked",
        "huavd:available-locales": list(available_locales),
        "huavd:style-locales": list(style_locales),
        "huavd:build-time": build_time,
        "huavd:region": region.value,
        "huavd:data-license": "ODbL-1.0",
        "huavd:tile-count": tile_count,
        "huavd:raster-tile-size": tile_size,
        "huavd:raster-encoding": "webp",
    }
