from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from huavd_map_build.delivery.domain.manifest import SourceEvidence
from huavd_map_build.delivery.domain.metadata import PmtilesHeader


_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class QualityFinding:
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class VectorQualityReport:
    findings: tuple[QualityFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass(frozen=True, slots=True)
class VectorContractExpectations:
    region: str
    build_date: str
    role: str
    stem: str
    output_path: str
    min_zoom: int
    max_zoom: int
    source_url: str
    source_id: str
    offline_map_id: str
    package_version: str
    style_id: str
    available_locales: tuple[str, ...]
    style_locales: tuple[str, ...]
    source_evidence: SourceEvidence

    @property
    def asset_role(self) -> str:
        return "building-vector" if self.role == "building" else "base-vector"


def verify_vector_contract(
    *, header: PmtilesHeader, metadata: dict[str, Any],
    manifest: dict[str, Any], attribution: dict[str, Any],
    expected_metadata_layers: list[dict[str, Any]],
    expected_layer_names: list[str], expected_tippecanoe: dict[str, Any],
    actual_size: int, actual_sha512: str,
    expected_profile: str | None, expected_profile_schema: int | None,
    expectations: VectorContractExpectations,
) -> VectorQualityReport:
    findings: list[QualityFinding] = []

    def check(code: str, condition: bool, detail: str) -> None:
        if not condition:
            findings.append(QualityFinding(code, detail))

    check("header-internal-compression", header.internal_compression == 2,
          f"expected gzip (2), got {header.internal_compression}")
    check("header-tile-compression", header.tile_compression == 2,
          f"expected gzip (2), got {header.tile_compression}")
    check("header-tile-type", header.tile_type == 1,
          f"expected MVT (1), got {header.tile_type}")
    check("header-root-directory", header.root_offset + header.root_length <= 16384,
          "root directory exceeds 16 KiB range")
    check("header-zoom-range",
          header.min_zoom == expectations.min_zoom
          and header.max_zoom == expectations.max_zoom,
          "PMTiles zoom range does not match effective configuration")
    check("manifest-schema", manifest.get("schema") == "huavd-map-build/v1",
          "manifest schema is invalid")
    check("manifest-identity",
          manifest.get("region") == expectations.region
          and manifest.get("yyyymmdd") == expectations.build_date,
          "manifest region or build date does not match the artifact")
    build_id = manifest.get("build_id")
    check("manifest-build-time", _is_utc_timestamp(build_id),
          "manifest build id is not a valid UTC timestamp")
    source = manifest.get("source", {})
    check("manifest-source",
          source == {
              "vendor": "geofabrik", "url": expectations.source_url,
              "downloaded_at": expectations.source_evidence.downloaded_at,
              "size_bytes": expectations.source_evidence.size_bytes,
              "md5": expectations.source_evidence.md5,
              "osm_timestamp": None,
          }, "manifest source evidence does not match the configured input")
    check("manifest-size", manifest.get("output", {}).get("size_bytes") == actual_size,
          "manifest output size does not match PMTiles")
    check("manifest-sha512", manifest.get("output", {}).get("sha512") == actual_sha512,
          "manifest SHA-512 does not match PMTiles")
    output = manifest.get("output", {})
    check("manifest-output-path", output.get("path") == expectations.output_path,
          "manifest output path does not match the artifact")
    check("manifest-tile-range", output.get("tile_range") == {
        "min_zoom": header.min_zoom, "max_zoom": header.max_zoom,
        "bounds": list(header.bounds),
    }, "manifest tile range does not match the PMTiles header")
    check("manifest-layers", manifest.get("vector_layers") == expected_layer_names,
          "manifest vector layers do not match effective configuration")
    check("manifest-tippecanoe", manifest.get("tippecanoe") == expected_tippecanoe,
          "manifest Tippecanoe parameters do not match effective configuration")
    record = manifest.get("huavd_record", {})
    check("manifest-record-identity",
          record.get("name") == f"{expectations.stem}"
          and record.get("asset_role") == expectations.asset_role
          and record.get("format") == "pmtiles"
          and record.get("transport") == "offline"
          and record.get("coord_system") == "EPSG:3857",
          "manifest HUAVD record identity does not match the artifact")
    check("manifest-record-catalog",
          record.get("id") == expectations.offline_map_id
          and record.get("source_id") == expectations.source_id
          and record.get("package_version") == expectations.package_version
          and record.get("style_id") == expectations.style_id
          and record.get("source_type") == "osm-pbf",
          "manifest HUAVD record does not match the region catalog")
    check("manifest-record-locales",
          record.get("available_locales") == list(expectations.available_locales)
          and record.get("style_locales") == list(expectations.style_locales),
          "manifest locale declarations do not match glyph/style configuration")
    expected_revision = (
        f"geofabrik-{expectations.region.rsplit('/', 1)[-1]}-"
        f"{expectations.build_date[:4]}-{expectations.build_date[4:6]}-"
        f"{expectations.build_date[6:]}"
    )
    check("manifest-record-release",
          record.get("source_revision") == expected_revision
          and record.get("released_at") == build_id
          and _is_utc_timestamp(record.get("released_at"))
          and isinstance(record.get("bundle_id"), str)
          and bool(record.get("bundle_id"))
          and isinstance(record.get("activation"), str)
          and bool(record.get("activation")),
          "manifest release identity or timestamp is invalid")
    license_document = manifest.get("license", {})
    check("manifest-license",
          license_document.get("data_license") == "ODbL-1.0"
          and "OpenStreetMap contributors" in str(
              license_document.get("attribution", "")
          ), "manifest license or attribution is invalid")
    check("attribution-contract", attribution == {
        "data_license": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
        "sources": [{"vendor": "geofabrik", "url": expectations.source_url}],
    }, "attribution document does not match the configured OSM source")
    check("metadata-layers", metadata.get("vector_layers") == expected_metadata_layers,
          "PMTiles metadata vector layers do not match effective configuration")
    check("metadata-identity",
          metadata.get("name") == expectations.stem
          and metadata.get("format") == "pbf"
          and metadata.get("huavd:region") == expectations.region
          and metadata.get("huavd:asset-role") == expectations.asset_role,
          "PMTiles metadata identity does not match the artifact")
    check("metadata-source-id",
          metadata.get("huavd:source-id") == expectations.source_id,
          "PMTiles metadata source id does not match the region catalog")
    check("metadata-build-time", _is_utc_timestamp(metadata.get("huavd:build-time")),
          "PMTiles metadata build time is not a valid UTC timestamp")
    check("metadata-zoom-range",
          metadata.get("minzoom") == header.min_zoom
          and metadata.get("maxzoom") == header.max_zoom,
          "PMTiles metadata zoom range does not match the header")
    center = metadata.get("center")
    expected_center = header.center
    center_match = (
        isinstance(center, list) and len(center) == 3
        and all(isinstance(value, (int, float)) for value in center)
        and abs(float(center[0]) - expected_center[0]) <= 1e-7
        and abs(float(center[1]) - expected_center[1]) <= 1e-7
        and center[2] == expected_center[2]
    )
    check("metadata-center", center_match,
          "PMTiles metadata center does not match header bounds")
    bounds = metadata.get("bounds")
    bounds_match = (
        isinstance(bounds, list) and len(bounds) == 4
        and all(isinstance(value, (int, float)) for value in bounds)
        and all(abs(float(bounds[index]) - header.bounds[index]) <= 1e-7
                for index in range(4))
    )
    check("metadata-bounds", bounds_match,
          "PMTiles metadata bounds do not match header")
    check("metadata-attribution",
          "OpenStreetMap contributors" in str(metadata.get("attribution", "")),
          "PMTiles metadata attribution is missing")
    check("metadata-license", metadata.get("huavd:data-license") == "ODbL-1.0",
          "PMTiles metadata data license is invalid")
    check("metadata-available-locales",
          metadata.get("huavd:available-locales")
          == list(expectations.available_locales),
          "PMTiles available locales do not match glyph configuration")
    check("metadata-style-locales",
          metadata.get("huavd:style-locales") == list(expectations.style_locales),
          "PMTiles style locales do not match style configuration")
    package_version = manifest.get("huavd_record", {}).get("package_version")
    check("manifest-package-version",
          isinstance(package_version, str)
          and re.fullmatch(r"[A-Za-z0-9._+\-]+", package_version) is not None
          and package_version == expectations.package_version,
          "manifest package version is invalid or does not match the catalog")
    if expected_profile:
        profile = manifest.get("build_profile")
        check("manifest-build-profile", isinstance(profile, dict)
              and profile.get("name") == expected_profile
              and profile.get("schema_version") == expected_profile_schema,
              "manifest build profile does not match configuration")
        check("metadata-build-profile",
              metadata.get("huavd:build-profile") == expected_profile
              and metadata.get("huavd:build-profile-schema") == expected_profile_schema,
              "PMTiles metadata build profile does not match configuration")
    return VectorQualityReport(tuple(findings))
