from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from huavd_map_build.delivery.domain.metadata import PmtilesHeader
from huavd_map_build.delivery.domain.attribution import AttributionDocument
from huavd_map_build.quality.domain.vector import QualityFinding


@dataclass(frozen=True, slots=True)
class RasterContractExpectations:
    region: str
    stem: str
    output_path: str
    source_id: str
    tile_count: int
    tile_size: int
    actual_size: int
    actual_sha512: str
    base_file: str
    base_sha512: str
    plan_sha512: str
    tiles_sha512: str
    input_fingerprint: str
    base_source: dict[str, Any]
    source_revision: str


@dataclass(frozen=True, slots=True)
class RasterQualityReport:
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


def verify_raster_contract(
    *, header: PmtilesHeader, metadata: dict[str, Any],
    manifest: dict[str, Any], attribution: dict[str, Any],
    expectations: RasterContractExpectations,
) -> RasterQualityReport:
    findings: list[QualityFinding] = []

    def check(code: str, condition: bool, detail: str) -> None:
        if not condition:
            findings.append(QualityFinding(code, detail))

    source = manifest.get("source")
    check("source-base-consistency", source == expectations.base_source,
          "raster source must equal verified base source")
    try:
        if not isinstance(source, dict) or "vendor" not in source or "url" not in source:
            raise ValueError("raster manifest source is incomplete")
        expected_attribution = AttributionDocument.osm(source["vendor"], source["url"]).as_dict()
        check("attribution-contract", attribution == expected_attribution,
              "attribution does not match raster source")
    except ValueError as error:
        check("attribution-contract", False, str(error))
    record = manifest.get("huavd_record")
    check("manifest-source-revision", isinstance(record, dict)
          and record.get("source_revision") == expectations.source_revision,
          "raster source_revision does not match verified base lineage")

    check("header-tile-type", header.tile_type == 4,
          f"expected WebP (4), got {header.tile_type}")
    check("header-tile-compression", header.tile_compression == 1,
          f"expected none (1), got {header.tile_compression}")
    check("header-internal-compression", header.internal_compression == 2,
          f"expected gzip (2), got {header.internal_compression}")
    check("header-addressed-tiles",
          header.addressed_tiles_count == expectations.tile_count,
          f"expected {expectations.tile_count} addressed tiles, "
          f"got {header.addressed_tiles_count}")
    output = manifest.get("output", {})
    check("manifest-output", output.get("path") == expectations.output_path
          and output.get("size_bytes") == expectations.actual_size
          and output.get("sha512") == expectations.actual_sha512,
          "manifest output identity, size, or digest does not match candidate")
    raster = manifest.get("raster_bake", {})
    check("manifest-raster", raster.get("encoding") == "webp"
          and raster.get("tile_count") == expectations.tile_count
          and raster.get("tile_size") == expectations.tile_size
          and raster.get("tile_type") == 4
          and raster.get("tile_compression") == 1,
          "manifest raster encoding or dimensions do not match the bake")
    base = raster.get("base_input", {})
    check("manifest-base", base.get("file") == expectations.base_file
          and base.get("sha512") == expectations.base_sha512,
          "manifest base input does not match verified vector input")
    plan = raster.get("plan", {})
    check("manifest-plan", plan.get("plan_sha512") == expectations.plan_sha512
          and plan.get("tiles_sha512") == expectations.tiles_sha512
          and plan.get("input_fingerprint") == expectations.input_fingerprint
          and plan.get("requested_tile_count") == expectations.tile_count,
          "manifest plan evidence does not match bake cache")
    check("manifest-layers", manifest.get("vector_layers") == [],
          "raster manifest must not declare vector layers")
    check("metadata-identity", metadata.get("name") == expectations.stem
          and metadata.get("format") == "webp"
          and metadata.get("huavd:region") == expectations.region
          and metadata.get("huavd:source-id") == expectations.source_id
          and metadata.get("huavd:asset-role") == "raster-baked",
          "embedded metadata identity does not match raster artifact")
    check("metadata-raster", metadata.get("vector_layers") == []
          and metadata.get("huavd:raster-encoding") == "webp"
          and metadata.get("huavd:tile-count") == expectations.tile_count
          and metadata.get("huavd:raster-tile-size") == expectations.tile_size,
          "embedded raster metadata does not match bake parameters")
    check("metadata-range", metadata.get("minzoom") == header.min_zoom
          and metadata.get("maxzoom") == header.max_zoom
          and metadata.get("bounds") == list(header.bounds),
          "embedded metadata range does not match PMTiles header")
    return RasterQualityReport(tuple(findings))
