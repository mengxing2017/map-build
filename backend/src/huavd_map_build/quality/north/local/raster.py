from pathlib import PurePosixPath

from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity
from huavd_map_build.delivery.domain.manifest import RasterManifestRequest
from huavd_map_build.delivery.north.local.source import raster_source_revision, validated_base_source
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.delivery.south.port.manifest import ManifestEvidenceReader
from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader
from huavd_map_build.quality.domain.raster import (
    RasterContractExpectations,
    RasterQualityReport,
    verify_raster_contract,
)
from huavd_map_build.quality.south.port.vector import EmbeddedMetadataReader
from huavd_map_build.quality.south.port.raster import RasterTileSampleVerifier
from huavd_map_build.production.domain.raster import RasterTileCoordinate
from huavd_map_build.quality.domain.vector import QualityFinding
from huavd_map_build.shared.kernel import Role


class RasterQualityGate:
    def __init__(
        self, catalog: CatalogService, headers: PmtilesHeaderReader,
        metadata: EmbeddedMetadataReader, digest: DigestPort,
        evidence: ManifestEvidenceReader,
        samples: RasterTileSampleVerifier | None = None,
    ) -> None:
        self._catalog, self._headers, self._metadata = catalog, headers, metadata
        self._digest, self._evidence = digest, evidence
        self._samples = samples

    def verify(self, request: RasterManifestRequest) -> RasterQualityReport:
        root = request.workdir.rstrip("/")
        cache = f"{root}/cache/bake/{request.session.value}"
        plan_path, tiles_path = f"{cache}/plan.json", f"{cache}/tiles.tsv"
        base = f"{root}/outputs/{ArtifactIdentity(request.region, request.build_date, Role.BASE).stem}.pmtiles"
        manifest = self._evidence.read_json(request.manifest_path)
        try:
            base_sha512 = self._digest.sha512(base)
            base_manifest = self._evidence.read_json(base.removesuffix(".pmtiles") + ".manifest.json")
            base_source = validated_base_source(
                base_manifest, region=request.region, build_date=request.build_date,
                actual_size=self._evidence.size(base), actual_sha512=base_sha512,
            )
            revision = raster_source_revision(
                self._catalog, base_manifest, request.region, request.build_date
            )
        except (OSError, ValueError, RuntimeError) as error:
            return RasterQualityReport((QualityFinding("source-base-consistency", str(error)),))
        try:
            attribution = self._evidence.read_json(
                request.manifest_path.removesuffix(".manifest.json") + ".attribution.json"
            )
        except (OSError, ValueError, RuntimeError) as error:
            return RasterQualityReport((QualityFinding("attribution-contract", str(error)),))
        settings = self._catalog.region_settings(
            request.region, Role.RASTER_BAKE.value, request.build_date.value
        )
        report = verify_raster_contract(
            header=self._headers.read(request.pmtiles_path),
            metadata=self._metadata.embedded_metadata(request.pmtiles_path),
            manifest=manifest, attribution=attribution,
            expectations=RasterContractExpectations(
                region=request.region.value,
                stem=f"{request.session.value}.raster_bake",
                output_path=f"outputs/{request.session.value}.raster_bake.pmtiles",
                source_id=str(settings.get("source_id") or ""),
                tile_count=request.tile_count, tile_size=request.tile_size,
                actual_size=self._evidence.size(request.pmtiles_path),
                actual_sha512=self._digest.sha512(request.pmtiles_path),
                base_file=PurePosixPath(base).name,
                base_sha512=base_sha512,
                base_source=base_source, source_revision=revision,
                plan_sha512=self._digest.sha512(plan_path),
                tiles_sha512=self._digest.sha512(tiles_path),
                input_fingerprint=self._evidence.read_text(
                    f"{cache}/inputs.sha512"
                ).strip(),
            ),
        )
        if self._samples is None:
            return report
        findings = list(report.findings)
        ranges = self._evidence.read_json(plan_path).get("tiles_by_zoom", [])
        indexes = sorted({0, len(ranges) // 2, len(ranges) - 1}) if ranges else []
        for index in indexes:
            item = ranges[index]
            coordinate = RasterTileCoordinate(
                int(item["zoom"]),
                (int(item["x_range"][0]) + int(item["x_range"][1])) // 2,
                (int(item["y_range"][0]) + int(item["y_range"][1])) // 2,
            )
            try:
                self._samples.verify(
                    request.pmtiles_path, coordinate, request.tile_size
                )
            except (OSError, RuntimeError, ValueError) as error:
                findings.append(QualityFinding(
                    "webp-sample",
                    f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}: {error}",
                ))
        return RasterQualityReport(tuple(findings))
