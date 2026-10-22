from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from huavd_map_build.delivery.domain.metadata import PmtilesHeader
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


@dataclass(frozen=True, slots=True)
class ManifestRequest:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    role: Role
    workdir: str
    bundle_id: str | None = None
    activation: str = "manual"


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    size_bytes: int | None
    downloaded_at: str | None
    md5: str | None


@dataclass(frozen=True, slots=True)
class RasterManifestRequest:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    workdir: str
    pmtiles_path: str
    manifest_path: str
    tile_count: int
    tile_size: int
    bundle_id: str | None = None
    activation: str = "manual"


def compile_vector_manifest(
    *, request: ManifestRequest, header: PmtilesHeader, output_path: str,
    output_size: int, sha512: str, source_vendor: str, source_url: str | None,
    source_revision: str, evidence: SourceEvidence,
    tools: dict[str, str], tippecanoe: dict[str, Any], vector_layers: list[str],
    source_id: str, offline_map_id: str, package_version: str, style_id: str,
    available_locales: tuple[str, ...], style_locales: tuple[str, ...],
    build_id: str, build_profile: str | None = None,
    build_profile_schema: int | None = None,
) -> dict[str, Any]:
    if request.role not in (Role.BASE, Role.BUILDING):
        raise ValueError(f"vector manifest does not support role: {request.role.value}")
    if not source_id or not offline_map_id:
        raise ValueError("manifest source_id and offline map id are required")
    asset_role = "building-vector" if request.role is Role.BUILDING else "base-vector"
    bundle_id = request.bundle_id or (
        f"{request.region.slug}-{request.build_date.value}-standard"
    )
    document: dict[str, Any] = {
        "schema": "huavd-map-build/v1",
        "region": request.region.value,
        "yyyymmdd": request.build_date.value,
        "build_id": build_id,
        "source": {
            "vendor": source_vendor, "url": source_url,
            "downloaded_at": evidence.downloaded_at,
            "size_bytes": evidence.size_bytes, "md5": evidence.md5,
            "osm_timestamp": None,
        },
        "tools": {**tools, "huavd-map-build": "python"},
        "tippecanoe": tippecanoe,
        "output": {
            "path": output_path, "size_bytes": output_size, "sha512": sha512,
            "tile_range": {
                "min_zoom": header.min_zoom, "max_zoom": header.max_zoom,
                "bounds": list(header.bounds),
            },
        },
        "vector_layers": vector_layers,
        "huavd_record": {
            "id": offline_map_id,
            "name": f"{request.session.value}.{request.role.value}",
            "source_id": source_id, "asset_role": asset_role,
            "source_type": "osm-pbf", "package_version": package_version,
            "source_revision": source_revision,
            "transport": "offline", "coord_system": "EPSG:3857",
            "style_id": style_id, "format": "pmtiles",
            "available_locales": list(available_locales),
            "style_locales": list(style_locales), "released_at": build_id,
            "activation": request.activation, "bundle_id": bundle_id,
        },
        "license": {
            "data_license": "ODbL-1.0",
            "attribution": "© OpenStreetMap contributors",
        },
    }
    if build_profile:
        if build_profile_schema is None:
            raise ValueError("build profile manifest requires schema version")
        document["build_profile"] = {
            "name": build_profile, "schema_version": build_profile_schema
        }
    return document


def compile_raster_manifest(
    *, request: RasterManifestRequest, header: PmtilesHeader,
    output_path: str, output_size: int, sha512: str,
    source_vendor: str, source_url: str | None, evidence: SourceEvidence,
    tools: dict[str, str],
    source_id: str, offline_map_id: str, package_version: str, style_id: str,
    available_locales: tuple[str, ...], style_locales: tuple[str, ...],
    build_id: str, source_revision: str, base_input: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    if header.tile_type != 4 or header.tile_compression != 1:
        raise ValueError("raster manifest requires WebP tile_type=4 and compression=none")
    if request.tile_count <= 0 or request.tile_size <= 0:
        raise ValueError("raster manifest tile count and tile size must be positive")
    if not source_id or not offline_map_id:
        raise ValueError("raster manifest source_id and offline map id are required")
    bundle_id = request.bundle_id or (
        f"{request.region.slug}-{request.build_date.value}-standard"
    )
    return {
        "schema": "huavd-map-build/v1",
        "region": request.region.value,
        "yyyymmdd": request.build_date.value,
        "build_id": build_id,
        "source": {
            "vendor": source_vendor, "url": source_url,
            "downloaded_at": evidence.downloaded_at,
            "size_bytes": evidence.size_bytes, "md5": evidence.md5,
            "osm_timestamp": None,
        },
        "tools": {**tools, "huavd-map-build": "python"},
        "tippecanoe": None,
        "output": {
            "path": output_path, "size_bytes": output_size, "sha512": sha512,
            "tile_range": {
                "min_zoom": header.min_zoom, "max_zoom": header.max_zoom,
                "bounds": list(header.bounds),
            },
        },
        "vector_layers": [],
        "huavd_record": {
            "id": offline_map_id,
            "name": f"{request.session.value}.raster_bake",
            "source_id": source_id,
            "asset_role": "raster-baked",
            "source_type": "osm-raster-baked",
            "package_version": package_version,
            "source_revision": source_revision,
            "transport": "offline", "coord_system": "EPSG:3857",
            "style_id": style_id, "format": "pmtiles",
            "available_locales": list(available_locales),
            "style_locales": list(style_locales), "released_at": build_id,
            "activation": request.activation, "bundle_id": bundle_id,
        },
        "license": {
            "data_license": "ODbL-1.0",
            "attribution": "\u00a9 OpenStreetMap contributors",
        },
        "raster_bake": {
            "encoding": "webp", "tile_count": request.tile_count,
            "tile_type": header.tile_type,
            "tile_compression": header.tile_compression,
            "tile_size": request.tile_size, "base_input": base_input,
            "plan": plan,
        },
    }
