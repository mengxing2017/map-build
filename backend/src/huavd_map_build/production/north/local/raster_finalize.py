from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.domain.attribution import AttributionDocument
from huavd_map_build.delivery.domain.integrity import ArtifactIntegrityReport
from huavd_map_build.delivery.domain.manifest import RasterManifestRequest
from huavd_map_build.delivery.domain.metadata import RasterMetadataRequest
from huavd_map_build.delivery.north.local.attribution import AttributionWriterService
from huavd_map_build.delivery.north.local.manifest import RasterManifestService
from huavd_map_build.delivery.north.local.metadata import RasterMetadataService
from huavd_map_build.delivery.north.local.publication import ArtifactPublicationService
from huavd_map_build.delivery.north.local.verification import ArtifactFileVerifier
from huavd_map_build.delivery.south.port.raster_publication import RasterCandidatePublisher
from huavd_map_build.quality.domain.raster import RasterQualityReport
from huavd_map_build.quality.north.local.raster import RasterQualityGate
from huavd_map_build.production.south.port.style import RasterClientStyleBinder
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


@dataclass(frozen=True, slots=True)
class RasterFinalizationRequest:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    workdir: str
    candidate_pmtiles: str
    tile_count: int
    tile_size: int
    bundle_id: str | None = None
    activation: str = "manual"


@dataclass(frozen=True, slots=True)
class RasterFinalizationResult:
    paths: ArtifactPaths
    metadata_path: str
    semantic: RasterQualityReport
    integrity: ArtifactIntegrityReport
    published: bool

    @property
    def passed(self) -> bool:
        return self.published and self.semantic.passed and self.integrity.passed

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "published": self.published,
            "paths": self.paths.as_dict(),
            "metadata_path": self.metadata_path,
            "semantic": self.semantic.as_dict(),
            "integrity": self.integrity.as_dict(),
        }


class RasterFinalizationService:
    def __init__(
        self, catalog: CatalogService, metadata: RasterMetadataService,
        manifest: RasterManifestService, attribution: AttributionWriterService,
        quality: RasterQualityGate, integrity: ArtifactFileVerifier,
        candidates: RasterCandidatePublisher, publication: ArtifactPublicationService,
        styles: RasterClientStyleBinder | None = None,
    ) -> None:
        self._catalog, self._metadata, self._manifest = catalog, metadata, manifest
        self._attribution, self._quality, self._integrity = attribution, quality, integrity
        self._candidates, self._publication, self._styles = candidates, publication, styles

    def run(self, request: RasterFinalizationRequest) -> RasterFinalizationResult:
        identity = ArtifactIdentity(request.region, request.build_date, Role.RASTER_BAKE)
        final = ArtifactPaths(identity, f"{request.workdir.rstrip('/')}/outputs")
        staged = self._candidates.stage(
            request.candidate_pmtiles, identity, final.outputs_directory
        )
        metadata_path = ""
        try:
            metadata_path = self._metadata.run(RasterMetadataRequest(
                request.region, request.build_date, request.session, request.workdir,
                staged.pmtiles, request.tile_count, request.tile_size,
            ))
            manifest_request = RasterManifestRequest(
                request.region, request.build_date, request.session, request.workdir,
                staged.pmtiles, staged.manifest, request.tile_count, request.tile_size,
                request.bundle_id, request.activation,
            )
            self._manifest.run(manifest_request)
            self._attribution.write(
                staged,
                AttributionDocument.geofabrik_osm(self._catalog.source_pbf_url(request.region)),
            )
            semantic = self._quality.verify(manifest_request)
            staged_integrity = self._integrity.verify(staged)
            if not semantic.passed or not staged_integrity.passed:
                return RasterFinalizationResult(
                    final, metadata_path, semantic, staged_integrity, False
                )
            self._candidates.promote(staged, final)
            if self._styles is not None:
                self._styles.bind(final.pmtiles,
                    f"{request.workdir.rstrip('/')}/outputs/{request.session.value}.style-raster.json", request.tile_size)
            published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._publication.publish_integrity_metadata(final, published_at=published_at)
            integrity = self._integrity.verify(
                final, require_consumer_closure=True, require_ready_marker=True
            )
            return RasterFinalizationResult(
                final, metadata_path, semantic, integrity, integrity.passed
            )
        finally:
            self._candidates.discard(staged)
