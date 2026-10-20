from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity
from huavd_map_build.delivery.domain.metadata import (
    MetadataRequest,
    RasterMetadataRequest,
    compile_raster_metadata,
    compile_vector_metadata,
)
from huavd_map_build.delivery.south.port.metadata import (
    MetadataStore,
    PmtilesHeaderReader,
    PmtilesMetadataEditor,
)
from huavd_map_build.shared.kernel import Role


class VectorMetadataService:
    def __init__(
        self,
        catalog: CatalogService,
        configuration: BuildConfigurationService,
        headers: PmtilesHeaderReader,
        editor: PmtilesMetadataEditor,
        store: MetadataStore,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._headers = headers
        self._editor = editor
        self._store = store
        self._clock = clock or self._utc_now

    def run(self, request: MetadataRequest) -> str:
        if request.role not in (Role.BASE, Role.BUILDING):
            raise ValueError("vector metadata role must be base or building")
        identity = ArtifactIdentity(request.region, request.build_date, request.role)
        root = request.workdir.rstrip("/")
        pmtiles = request.pmtiles_path or f"{root}/outputs/{identity.stem}.pmtiles"
        if not self._store.is_file(pmtiles):
            raise ValueError(f"required file does not exist: {pmtiles}")
        header = self._headers.read(pmtiles)
        settings = self._catalog.region_settings(
            request.region, request.role.value, request.build_date.value
        )
        source_id = settings.get("source_id")
        glyphs = self._configuration.glyph_manifest()
        styles = self._configuration.style(request.region.value)["config"]
        profile = (
            self._configuration.profile_transform(request.region.value)
            if request.role is Role.BASE else None
        )
        document = compile_vector_metadata(
            stem=identity.stem,
            region=request.region,
            role=request.role,
            header=header,
            vector_layers=self._configuration.vector_layers(
                request.region.value, request.role.value, header.max_zoom
            ),
            source_id=source_id if isinstance(source_id, str) else "",
            available_locales=tuple(locale["tag"] for locale in glyphs["locales"]),
            style_locales=tuple(locale["tag"] for locale in styles["locales"]),
            build_time=self._clock(),
            build_profile=profile["name"] if profile else None,
            build_profile_schema=(
                self._configuration.tier_profile_schema_version() if profile else None
            ),
        )
        metadata_path = (
            f"{root}/staging/{request.session.value}/metadata.{request.role.value}.json"
        )
        self._store.write_document(metadata_path, document)
        self._editor.edit(pmtiles, metadata_path)
        self._store.write_sidecar(pmtiles)
        return metadata_path

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RasterMetadataService:
    def __init__(
        self, catalog: CatalogService, configuration: BuildConfigurationService,
        headers: PmtilesHeaderReader, editor: PmtilesMetadataEditor,
        store: MetadataStore, clock: Callable[[], str] | None = None,
    ) -> None:
        self._catalog, self._configuration = catalog, configuration
        self._headers, self._editor, self._store = headers, editor, store
        self._clock = clock or VectorMetadataService._utc_now

    def run(self, request: RasterMetadataRequest) -> str:
        if not self._store.is_file(request.pmtiles_path):
            raise ValueError(f"required file does not exist: {request.pmtiles_path}")
        header = self._headers.read(request.pmtiles_path)
        settings = self._catalog.region_settings(
            request.region, Role.RASTER_BAKE.value, request.build_date.value
        )
        source_id = settings.get("source_id")
        glyphs = self._configuration.glyph_manifest()
        styles = self._configuration.style(request.region.value)["config"]
        identity = ArtifactIdentity(
            request.region, request.build_date, Role.RASTER_BAKE
        )
        document = compile_raster_metadata(
            stem=identity.stem, region=request.region, header=header,
            source_id=source_id if isinstance(source_id, str) else "",
            available_locales=tuple(locale["tag"] for locale in glyphs["locales"]),
            style_locales=tuple(locale["tag"] for locale in styles["locales"]),
            build_time=self._clock(), tile_count=request.tile_count,
            tile_size=request.tile_size,
        )
        root = request.workdir.rstrip("/")
        metadata_path = (
            f"{root}/staging/{request.session.value}/metadata.raster_bake.json"
        )
        self._store.write_document(metadata_path, document)
        self._editor.edit(request.pmtiles_path, metadata_path)
        self._store.write_sidecar(request.pmtiles_path)
        return metadata_path
