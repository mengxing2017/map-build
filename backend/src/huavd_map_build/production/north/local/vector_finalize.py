from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.domain.attribution import AttributionDocument
from huavd_map_build.delivery.domain.integrity import ArtifactIntegrityReport
from huavd_map_build.delivery.domain.manifest import ManifestRequest
from huavd_map_build.delivery.domain.metadata import MetadataRequest
from huavd_map_build.delivery.north.local.attribution import AttributionWriterService
from huavd_map_build.delivery.north.local.manifest import VectorManifestService
from huavd_map_build.delivery.north.local.source import read_manifest_source
from huavd_map_build.delivery.north.local.metadata import VectorMetadataService
from huavd_map_build.delivery.north.local.verification import ArtifactFileVerifier
from huavd_map_build.quality.domain.vector import VectorQualityReport
from huavd_map_build.quality.north.local.vector import VectorQualityGate
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


@dataclass(frozen=True, slots=True)
class VectorFinalizationRequest:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    role: Role
    workdir: str
    bundle_id: str | None = None
    activation: str = "manual"


@dataclass(frozen=True, slots=True)
class VectorFinalizationResult:
    paths: ArtifactPaths
    metadata_path: str
    semantic: VectorQualityReport
    integrity: ArtifactIntegrityReport

    @property
    def passed(self) -> bool:
        return self.semantic.passed and self.integrity.passed

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "paths": self.paths.as_dict(),
            "metadata_path": self.metadata_path,
            "semantic": self.semantic.as_dict(),
            "integrity": self.integrity.as_dict(),
        }


class VectorFinalizationService:
    def __init__(
        self, catalog: CatalogService, metadata: VectorMetadataService,
        manifest: VectorManifestService, attribution: AttributionWriterService,
        quality: VectorQualityGate, integrity: ArtifactFileVerifier,
    ) -> None:
        self._catalog, self._metadata = catalog, metadata
        self._manifest, self._attribution = manifest, attribution
        self._quality, self._integrity = quality, integrity

    def run(self, request: VectorFinalizationRequest) -> VectorFinalizationResult:
        if request.role not in (Role.BASE, Role.BUILDING):
            raise ValueError("vector finalization role must be base or building")
        paths = ArtifactPaths(
            ArtifactIdentity(request.region, request.build_date, request.role),
            f"{request.workdir.rstrip('/')}/outputs",
        )
        metadata_path = self._metadata.run(MetadataRequest(
            request.region, request.build_date, request.session, request.role,
            request.workdir,
        ))
        manifest_path = self._manifest.run(ManifestRequest(
            request.region, request.build_date, request.session, request.role,
            request.workdir, request.bundle_id, request.activation,
        ))
        source = read_manifest_source(manifest_path)
        self._attribution.write(
            paths, AttributionDocument.osm(source.vendor, source.url)
        )
        semantic = self._quality.verify(
            region=request.region, build_date=request.build_date,
            role=request.role, workdir=request.workdir,
        )
        integrity = self._integrity.verify(paths)
        return VectorFinalizationResult(paths, metadata_path, semantic, integrity)
