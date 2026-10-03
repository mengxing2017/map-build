from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import PurePosixPath

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity
from huavd_map_build.delivery.domain.manifest import (
    ManifestRequest,
    RasterManifestRequest,
    compile_raster_manifest,
    compile_vector_manifest,
)
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.delivery.south.port.manifest import (
    ManifestEvidenceReader,
    ManifestWriter,
    ToolVersionReader,
)
from huavd_map_build.delivery.south.port.metadata import PmtilesHeaderReader
from huavd_map_build.shared.kernel import Role


class VectorManifestService:
    def __init__(
        self, catalog: CatalogService, configuration: BuildConfigurationService,
        headers: PmtilesHeaderReader, evidence: ManifestEvidenceReader,
        versions: ToolVersionReader, digest: DigestPort, writer: ManifestWriter,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._catalog, self._configuration = catalog, configuration
        self._headers, self._evidence = headers, evidence
        self._versions, self._digest, self._writer = versions, digest, writer
        self._clock = clock or self._utc_now

    def run(self, request: ManifestRequest) -> str:
        if request.role not in (Role.BASE, Role.BUILDING):
            raise ValueError("vector manifest role must be base or building")
        identity = ArtifactIdentity(request.region, request.build_date, request.role)
        root = request.workdir.rstrip("/")
        pmtiles = f"{root}/outputs/{identity.stem}.pmtiles"
        header = self._headers.read(pmtiles)
        pbf_basename = self._catalog.pbf_basename(request.region)
        source = self._evidence.source(
            f"{root}/staging/{request.session.value}/source.osm.pbf",
            f"{root}/mirror/{pbf_basename}.md5",
        )
        settings = self._catalog.region_settings(
            request.region, request.role.value, request.build_date.value
        )
        tippecanoe = self._configuration.tippecanoe(
            request.region.value, request.role.value
        )
        glyphs = self._configuration.glyph_manifest()
        styles = self._configuration.style(request.region.value)["config"]
        profile = (
            self._configuration.profile_transform(request.region.value)
            if request.role is Role.BASE else None
        )
        document = compile_vector_manifest(
            request=request, header=header,
            output_path=f"outputs/{PurePosixPath(pmtiles).name}",
            output_size=self._evidence.size(pmtiles),
            sha512=self._digest.sha512(pmtiles),
            source_url=self._catalog.pbf_url(request.region), evidence=source,
            tools=self._versions.versions(("osmium", "tippecanoe", "pmtiles")),
            tippecanoe=tippecanoe,
            vector_layers=list(tippecanoe["source_layers"]),
            source_id=str(settings.get("source_id") or ""),
            offline_map_id=str(settings.get("region_id") or ""),
            package_version=str(settings["package_version"]),
            style_id=str(settings["style_id"]),
            available_locales=tuple(locale["tag"] for locale in glyphs["locales"]),
            style_locales=tuple(locale["tag"] for locale in styles["locales"]),
            build_id=self._clock(), build_profile=profile["name"] if profile else None,
            build_profile_schema=(
                self._configuration.tier_profile_schema_version() if profile else None
            ),
        )
        output = f"{root}/outputs/{identity.stem}.manifest.json"
        self._writer.write(output, document)
        return output

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RasterManifestService:
    def __init__(
        self, catalog: CatalogService, configuration: BuildConfigurationService,
        headers: PmtilesHeaderReader, evidence: ManifestEvidenceReader,
        versions: ToolVersionReader, digest: DigestPort, writer: ManifestWriter,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._catalog, self._configuration = catalog, configuration
        self._headers, self._evidence = headers, evidence
        self._versions, self._digest, self._writer = versions, digest, writer
        self._clock = clock or VectorManifestService._utc_now

    def run(self, request: RasterManifestRequest) -> str:
        root = request.workdir.rstrip("/")
        base_identity = ArtifactIdentity(
            request.region, request.build_date, Role.BASE
        )
        base_pmtiles = f"{root}/outputs/{base_identity.stem}.pmtiles"
        base_manifest_path = f"{root}/outputs/{base_identity.stem}.manifest.json"
        cache = f"{root}/cache/bake/{request.session.value}"
        plan_path, tiles_path = f"{cache}/plan.json", f"{cache}/tiles.tsv"
        inputs_path = f"{cache}/inputs.sha512"
        plan_document = self._evidence.read_json(plan_path)
        base_manifest = self._evidence.read_json(base_manifest_path)
        base_header = self._headers.read(base_pmtiles)
        header = self._headers.read(request.pmtiles_path)
        settings = self._catalog.region_settings(
            request.region, Role.RASTER_BAKE.value, request.build_date.value
        )
        glyphs = self._configuration.glyph_manifest()
        styles = self._configuration.style(request.region.value)["config"]
        source = self._evidence.source(
            f"{root}/staging/{request.session.value}/source.osm.pbf",
            f"{root}/mirror/{self._catalog.pbf_basename(request.region)}.md5",
        )
        source_basename = self._catalog.pbf_basename(request.region)
        source_revision_name = source_basename.removesuffix(".osm.pbf").removesuffix(
            "-latest"
        )
        dashed_date = (
            f"{request.build_date.value[:4]}-{request.build_date.value[4:6]}-"
            f"{request.build_date.value[6:]}"
        )
        base_input = {
            "file": PurePosixPath(base_pmtiles).name,
            "sha512": self._digest.sha512(base_pmtiles),
            "size_bytes": self._evidence.size(base_pmtiles),
            "bounds": list(base_header.bounds),
            "min_zoom": base_header.min_zoom, "max_zoom": base_header.max_zoom,
            "vector_layers": base_manifest.get("vector_layers", []),
        }
        plan = {
            "plan_sha512": self._digest.sha512(plan_path),
            "tiles_sha512": self._digest.sha512(tiles_path),
            "input_fingerprint": self._evidence.read_text(inputs_path).strip(),
            "requested_tile_count": plan_document["tile_count"],
            "tiles_by_zoom": plan_document["tiles_by_zoom"],
            "bounds": plan_document["bounds"],
            "bbox_padding_tiles": plan_document["bbox_padding_tiles"],
        }
        document = compile_raster_manifest(
            request=request, header=header,
            output_path=f"outputs/{request.session.value}.raster_bake.pmtiles",
            output_size=self._evidence.size(request.pmtiles_path),
            sha512=self._digest.sha512(request.pmtiles_path),
            source_url=self._catalog.pbf_url(request.region), evidence=source,
            tools=self._versions.versions(("osmium", "tippecanoe", "pmtiles")),
            source_id=str(settings.get("source_id") or ""),
            offline_map_id=str(settings.get("region_id") or ""),
            package_version=str(settings["package_version"]),
            style_id=str(settings["style_id"]),
            available_locales=tuple(locale["tag"] for locale in glyphs["locales"]),
            style_locales=tuple(locale["tag"] for locale in styles["locales"]),
            build_id=self._clock(),
            source_revision=f"geofabrik-{source_revision_name}-{dashed_date}",
            base_input=base_input, plan=plan,
        )
        self._writer.write(request.manifest_path, document)
        return request.manifest_path
