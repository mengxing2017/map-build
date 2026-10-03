from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.south.port.manifest import ManifestEvidenceReader
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader
from huavd_map_build.quality.domain.vector import (
    VectorContractExpectations,
    VectorQualityReport,
    verify_vector_contract,
)
from huavd_map_build.quality.south.port.vector import (
    EmbeddedMetadataReader,
    VectorQualityFileReader,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


class VectorQualityGate:
    def __init__(
        self, catalog: CatalogService, configuration: BuildConfigurationService,
        headers: PmtilesHeaderReader, files: VectorQualityFileReader,
        metadata: EmbeddedMetadataReader, digest: DigestPort,
        evidence: ManifestEvidenceReader,
    ) -> None:
        self._catalog, self._configuration = catalog, configuration
        self._headers, self._files = headers, files
        self._metadata, self._digest, self._evidence = metadata, digest, evidence

    def verify(
        self, *, region: RegionId, build_date: BuildDate, role: Role, workdir: str
    ) -> VectorQualityReport:
        if role not in (Role.BASE, Role.BUILDING):
            raise ValueError("vector quality role must be base or building")
        paths = ArtifactPaths(
            ArtifactIdentity(region, build_date, role),
            f"{workdir.rstrip('/')}/outputs",
        )
        header = self._headers.read(paths.pmtiles)
        manifest = self._files.read_json(paths.manifest)
        attribution = self._files.read_json(paths.attribution)
        metadata = self._metadata.embedded_metadata(paths.pmtiles)
        tippecanoe = self._configuration.tippecanoe(region.value, role.value)
        settings = self._catalog.region_settings(
            region, role.value, build_date.value
        )
        available_locales = tuple(
            locale["tag"] for locale in self._configuration.glyph_manifest()["locales"]
        )
        style_locales = tuple(
            locale["tag"]
            for locale in self._configuration.style(region.value)["config"]["locales"]
        )
        profile = (
            self._configuration.profile_transform(region.value)
            if role is Role.BASE else None
        )
        stem = paths.identity.stem
        root = workdir.rstrip("/")
        source_evidence = self._evidence.source(
            f"{root}/staging/{paths.identity.session.value}/source.osm.pbf",
            f"{root}/mirror/{self._catalog.pbf_basename(region)}.md5",
        )
        return verify_vector_contract(
            header=header, metadata=metadata, manifest=manifest,
            attribution=attribution,
            expected_metadata_layers=self._configuration.vector_layers(
                region.value, role.value, header.max_zoom
            ),
            expected_layer_names=list(tippecanoe["source_layers"]),
            expected_tippecanoe=tippecanoe,
            actual_size=self._files.size(paths.pmtiles),
            actual_sha512=self._digest.sha512(paths.pmtiles),
            expected_profile=profile["name"] if profile else None,
            expected_profile_schema=(
                self._configuration.tier_profile_schema_version() if profile else None
            ),
            expectations=VectorContractExpectations(
                region=region.value, build_date=build_date.value,
                role=role.value, stem=stem,
                output_path=f"outputs/{stem}.pmtiles",
                min_zoom=int(tippecanoe["min_zoom"]),
                max_zoom=int(tippecanoe["max_zoom"]),
                source_url=self._catalog.pbf_url(region),
                source_id=str(settings.get("source_id") or ""),
                offline_map_id=str(settings.get("region_id") or ""),
                package_version=str(settings.get("package_version") or ""),
                style_id=str(settings.get("style_id") or ""),
                available_locales=available_locales,
                style_locales=style_locales,
                source_evidence=source_evidence,
            ),
        )
