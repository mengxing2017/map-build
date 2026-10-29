from __future__ import annotations

from pathlib import Path

from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.south.adapter.yaml.loader import PyYamlConfigurationRepository
from huavd_map_build.catalog.south.adapter.yaml.repository import (
    PyYamlRegionCatalogRepository,
)
from huavd_map_build.catalog.north.local.snapshot import CatalogSnapshotService
from huavd_map_build.catalog.south.adapter.filesystem.snapshot import (
    JsonCatalogSnapshotWriter,
)
from huavd_map_build.catalog.north.local.skeleton import RegionSkeletonService
from huavd_map_build.catalog.south.adapter.filesystem.skeleton import (
    FileSystemSkeletonSource,
)
from huavd_map_build.catalog.south.adapter.filesystem.yaml_json import (
    YamlJsonTranscoder,
)
from huavd_map_build.production.north.local.planner import BuildPlanner
from huavd_map_build.production.north.local.workspace import WorkspaceInitializer
from huavd_map_build.production.north.local.fetch import RegionFetchService
from huavd_map_build.production.north.local.export import LayerExportService
from huavd_map_build.production.north.local.normalize import LayerNormalizationService
from huavd_map_build.production.north.local.tippecanoe import TippecanoeService
from huavd_map_build.production.north.local.profile_transform import ProfileTransformService
from huavd_map_build.production.north.local.island_anchor import IslandAnchorService
from huavd_map_build.production.north.local.island_water import IslandWaterService
from huavd_map_build.production.north.local.admin_line import AdminLineService
from huavd_map_build.production.north.local.place_admin import PlaceAdminService
from huavd_map_build.production.north.local.style import StyleService
from huavd_map_build.production.north.local.sprite import SpriteService
from huavd_map_build.production.north.local.glyph import GlyphService
from huavd_map_build.production.north.local.raster import RasterPlanningService
from huavd_map_build.production.north.local.raster_bake import RasterBakeService
from huavd_map_build.production.north.local.raster_finalize import RasterFinalizationService
from huavd_map_build.production.south.adapter.process.raster_readback import ProcessRasterArchiveVerifier
from huavd_map_build.production.north.local.raster_request import RasterBakeRequestFactory
from huavd_map_build.production.north.local.raster_render import RasterRenderService
from huavd_map_build.production.north.local.raster_runtime import RasterRuntimeService
from huavd_map_build.production.north.local.raster_assembly import RasterAssemblyService
from huavd_map_build.production.north.local.orchestration import BuildOrchestrationPlanner
from huavd_map_build.production.north.local.base_stage import (
    BaseBuildStageExecutor,
    VectorBuildStageExecutor,
)
from huavd_map_build.production.north.local.execution import BuildExecutionService
from huavd_map_build.production.north.local.recovery import (
    BaseBuildPreparationService,
    VectorBuildPreparationService,
)
from huavd_map_build.production.north.local.vector_finalize import VectorFinalizationService
from huavd_map_build.delivery.north.local.bundle import BundleService
from huavd_map_build.production.north.local.tags_filter import TagsFilterService
from huavd_map_build.production.south.adapter.process.osmium import OsmiumTagsFilterRunner
from huavd_map_build.production.south.adapter.process.osmium_export import OsmiumExportRunner
from huavd_map_build.production.south.adapter.process.tippecanoe import ProcessTippecanoeRunner
from huavd_map_build.production.south.adapter.process.wget import WgetDownloader
from huavd_map_build.production.south.adapter.process.osmium_relations import OsmiumRelationLevelReader
from huavd_map_build.production.south.adapter.process.osmium_place_admin import OsmiumPlaceAdminTool
from huavd_map_build.production.south.adapter.process.pmtiles_viewport import PmtilesViewportReader
from huavd_map_build.production.south.adapter.workspace.fetch_store import (
    FileSystemFetchStore,
)
from huavd_map_build.production.south.adapter.workspace.filesystem import (
    FileSystemWorkspaceStore,
)
from huavd_map_build.production.south.adapter.workspace.tags_filter import (
    FileSystemTagsFilterWorkspace,
)
from huavd_map_build.production.south.adapter.workspace.export import (
    FileSystemExportWorkspace,
)
from huavd_map_build.production.south.adapter.workspace.normalize import (
    FileSystemGeoJsonSeqNormalizer,
)
from huavd_map_build.production.south.adapter.workspace.tippecanoe import (
    FileSystemTippecanoeWorkspace,
)
from huavd_map_build.production.south.adapter.workspace.profile_transform import (
    FileSystemProfileTransformer,
)
from huavd_map_build.production.south.adapter.workspace.island_anchor import (
    FileSystemIslandAnchorStore,
)
from huavd_map_build.production.south.adapter.workspace.island_water import (
    FileSystemIslandWaterStore,
)
from huavd_map_build.production.south.adapter.workspace.admin_line import FileSystemAdminLineStore
from huavd_map_build.production.south.adapter.workspace.place_admin import FileSystemPlaceAdminIndexStore
from huavd_map_build.production.south.adapter.workspace.build_source import (
    FileSystemBuildSourceWorkspace,
)
from huavd_map_build.production.south.adapter.workspace.recovery import (
    FileSystemBuildArtifactStore,
)
from huavd_map_build.production.south.adapter.workspace.style import FileSystemStyleStore, FileSystemRasterClientStyleBinder
from huavd_map_build.production.south.adapter.workspace.sprite import FileSystemSpriteStore
from huavd_map_build.production.south.adapter.workspace.glyph import FileSystemGlyphWorkspace
from huavd_map_build.production.south.adapter.process.glyph import ProcessGlyphGenerator
from huavd_map_build.production.south.adapter.process.raster import (
    ProcessRasterTileRenderer,
    ProcessWebpEncoder,
)
from huavd_map_build.production.south.adapter.process.raster_archive import (
    ProcessRasterArchive,
)
from huavd_map_build.production.south.adapter.process.raster_server import (
    ProcessRasterTileServer,
    UrlLibRasterMvtClient,
)
from huavd_map_build.production.south.adapter.process.raster_display import (
    ProcessRasterDisplaySession,
)
from huavd_map_build.production.south.adapter.workspace.raster import (
    FileSystemRasterCacheStore,
)
from huavd_map_build.production.south.adapter.workspace.raster_evidence import (
    FileSystemRasterEvidenceStore,
)
from huavd_map_build.production.south.adapter.workspace.raster_lifecycle import (
    FileSystemRasterCacheLifecycle,
)
from huavd_map_build.production.south.adapter.workspace.raster_mbtiles import (
    SqliteRasterTileArchiveAssembler,
)
from huavd_map_build.production.south.adapter.workspace.raster_queue import (
    FileSystemRasterWorkQueue,
)
from huavd_map_build.production.south.adapter.workspace.raster_style import (
    FileSystemRasterRuntimeStyleStore,
)
from huavd_map_build.delivery.north.local.service import ArtifactQuery
from huavd_map_build.delivery.north.local.verification import ArtifactFileVerifier
from huavd_map_build.delivery.north.local.publication import ArtifactPublicationService
from huavd_map_build.delivery.north.local.attribution import AttributionWriterService
from huavd_map_build.delivery.north.local.sidecar import Sha512SidecarWriterService
from huavd_map_build.delivery.north.local.metadata import (
    RasterMetadataService,
    VectorMetadataService,
)
from huavd_map_build.delivery.north.local.manifest import (
    RasterManifestService,
    VectorManifestService,
)
from huavd_map_build.delivery.north.local.checksum_manifest import ChecksumManifestWriter
from huavd_map_build.delivery.south.adapter.archive.filesystem import (
    FileSystemManifestStore,
)
from huavd_map_build.delivery.south.adapter.filesystem.artifact_store import (
    FileSystemArtifactStore,
)
from huavd_map_build.delivery.south.adapter.filesystem.raster_publication import (
    FileSystemRasterCandidatePublisher,
)
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.delivery.south.adapter.filesystem.atomic_writer import AtomicFileWriter
from huavd_map_build.delivery.south.adapter.filesystem.metadata import (
    FileSystemMetadataStore,
    FileSystemPmtilesHeaderReader,
)
from huavd_map_build.delivery.south.adapter.filesystem.manifest import (
    FileSystemManifestEvidenceReader,
    JsonManifestWriter,
)
from huavd_map_build.delivery.south.adapter.process.pmtiles_metadata import (
    ProcessPmtilesMetadataEditor,
)
from huavd_map_build.delivery.south.adapter.process.tool_versions import (
    ProcessToolVersionReader,
)
from huavd_map_build.quality.north.local.doctor import DoctorQuery
from huavd_map_build.quality.north.local.vector import VectorQualityGate
from huavd_map_build.quality.north.local.raster import RasterQualityGate
from huavd_map_build.quality.north.local.staging import BaseStagingQualityGate
from huavd_map_build.quality.north.local.style import StyleQualityGate
from huavd_map_build.quality.north.local.tile import VectorTileSamplingGate
from huavd_map_build.quality.north.local.base import BaseDeepQualityGate
from huavd_map_build.quality.south.adapter.process.tool_probe import ProcessToolProbe
from huavd_map_build.quality.south.adapter.process.pmtiles_metadata import (
    ProcessPmtilesMetadataReader,
)
from huavd_map_build.quality.south.adapter.filesystem.vector import (
    FileSystemVectorQualityReader,
)
from huavd_map_build.quality.south.adapter.filesystem.staging import (
    FileSystemStagedLayerReader,
)
from huavd_map_build.quality.south.adapter.filesystem.style import (
    FileSystemStyleQualityReader,
)
from huavd_map_build.quality.south.adapter.process.vector_tile import (
    ProcessVectorTileReader,
)
from huavd_map_build.quality.south.adapter.process.raster import (
    ProcessRasterTileSampleVerifier,
)


def repository_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "config/regions.yaml").is_file() and (candidate / "Makefile").is_file():
            return candidate
    raise RuntimeError("cannot locate huavd-map-build repository root")


def catalog_service(root: Path | None = None) -> CatalogService:
    resolved_root = root or repository_root()
    repository = PyYamlRegionCatalogRepository(resolved_root / "config/regions.yaml")
    return CatalogService(repository)


def catalog_snapshot_service(catalog_path: Path) -> CatalogSnapshotService:
    return CatalogSnapshotService(
        PyYamlRegionCatalogRepository(catalog_path), JsonCatalogSnapshotWriter()
    )


def region_skeleton_service() -> RegionSkeletonService:
    return RegionSkeletonService(FileSystemSkeletonSource())


def yaml_json_transcoder() -> YamlJsonTranscoder:
    return YamlJsonTranscoder()


def build_planner(root: Path | None = None) -> BuildPlanner:
    return BuildPlanner(catalog_service(root))


def build_orchestration_planner(
    root: Path | None = None,
) -> BuildOrchestrationPlanner:
    resolved_root = root or repository_root()
    return BuildOrchestrationPlanner(
        catalog_service(resolved_root), build_configuration_service(resolved_root)
    )


def raster_planning_service(
    root: Path | None = None,
) -> RasterPlanningService:
    resolved_root = root or repository_root()
    return RasterPlanningService(
        build_configuration_service(resolved_root), FileSystemPmtilesHeaderReader()
    )


def raster_bake_service() -> RasterBakeService:
    archive = ProcessRasterArchive()
    return RasterBakeService(
        FileSystemRasterCacheLifecycle(),
        FileSystemRasterCacheStore(),
        ProcessRasterDisplaySession(),
        RasterRuntimeService(
            archive, ProcessRasterTileServer(), UrlLibRasterMvtClient(),
            FileSystemRasterRuntimeStyleStore(), FileSystemPmtilesHeaderReader(),
        ),
        RasterRenderService(
            FileSystemRasterWorkQueue(), ProcessRasterTileRenderer(),
            ProcessWebpEncoder(),
        ),
        RasterAssemblyService(SqliteRasterTileArchiveAssembler(), archive, ProcessRasterArchiveVerifier()),
        FileSystemRasterEvidenceStore(AtomicFileWriter(), FileDigestAdapter()),
    )


def raster_bake_request_factory(
    root: Path | None = None,
) -> RasterBakeRequestFactory:
    resolved_root = root or repository_root()
    return RasterBakeRequestFactory(
        build_configuration_service(resolved_root), FileDigestAdapter(),
        str(resolved_root / "config/bake.yaml"), FileSystemPmtilesHeaderReader(),
    )


def raster_metadata_service(
    root: Path | None = None,
) -> RasterMetadataService:
    resolved_root = root or repository_root()
    writer, digest = AtomicFileWriter(), FileDigestAdapter()
    return RasterMetadataService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemPmtilesHeaderReader(), ProcessPmtilesMetadataEditor(),
        FileSystemMetadataStore(writer, digest),
    )


def raster_finalization_service(
    root: Path | None = None,
) -> RasterFinalizationService:
    resolved_root = root or repository_root()
    return RasterFinalizationService(
        catalog_service(resolved_root), raster_metadata_service(resolved_root),
        raster_manifest_service(resolved_root), attribution_writer_service(),
        raster_quality_gate(resolved_root), artifact_file_verifier(),
        FileSystemRasterCandidatePublisher(), artifact_publication_service(),
        FileSystemRasterClientStyleBinder(FileSystemPmtilesHeaderReader(), AtomicFileWriter(), FileDigestAdapter()),
    )


def region_fetch_service(root: Path | None = None) -> RegionFetchService:
    return RegionFetchService(
        catalog_service(root), WgetDownloader(), FileSystemFetchStore(), FileDigestAdapter()
    )


def tags_filter_service(root: Path | None = None) -> TagsFilterService:
    resolved_root = root or repository_root()
    return TagsFilterService(
        catalog_service(resolved_root),
        build_configuration_service(resolved_root),
        FileSystemTagsFilterWorkspace(),
        OsmiumTagsFilterRunner(),
    )


def layer_export_service(root: Path | None = None) -> LayerExportService:
    resolved_root = root or repository_root()
    return LayerExportService(
        catalog_service(resolved_root),
        build_configuration_service(resolved_root),
        FileSystemExportWorkspace(),
        OsmiumExportRunner(),
        str(resolved_root / "config"),
    )


def layer_normalization_service(root: Path | None = None) -> LayerNormalizationService:
    resolved_root = root or repository_root()
    return LayerNormalizationService(
        catalog_service(resolved_root),
        build_configuration_service(resolved_root),
        FileSystemGeoJsonSeqNormalizer(),
    )


def tippecanoe_service(root: Path | None = None) -> TippecanoeService:
    resolved_root = root or repository_root()
    return TippecanoeService(
        catalog_service(resolved_root),
        build_configuration_service(resolved_root),
        FileSystemTippecanoeWorkspace(),
        ProcessTippecanoeRunner(),
    )


def profile_transform_service(root: Path | None = None) -> ProfileTransformService:
    resolved_root = root or repository_root()
    return ProfileTransformService(
        catalog_service(resolved_root),
        build_configuration_service(resolved_root),
        FileSystemProfileTransformer(),
    )


def island_anchor_service(root: Path | None = None) -> IslandAnchorService:
    return IslandAnchorService(catalog_service(root), FileSystemIslandAnchorStore())


def island_water_service(root: Path | None = None) -> IslandWaterService:
    return IslandWaterService(catalog_service(root), FileSystemIslandWaterStore())


def admin_line_service(root: Path | None = None) -> AdminLineService:
    resolved_root = root or repository_root()
    return AdminLineService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemAdminLineStore(), OsmiumRelationLevelReader(),
    )


def place_admin_service(root: Path | None = None) -> PlaceAdminService:
    resolved_root = root or repository_root()
    return PlaceAdminService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemPlaceAdminIndexStore(), OsmiumPlaceAdminTool(),
    )


def style_service(root: Path | None = None) -> StyleService:
    resolved_root = root or repository_root()
    return StyleService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemStyleStore(AtomicFileWriter(), FileDigestAdapter()),
        PmtilesViewportReader(),
    )


def sprite_service(root: Path | None = None) -> SpriteService:
    resolved_root = root or repository_root()
    return SpriteService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemSpriteStore(),
    )


def glyph_service(root: Path | None = None) -> GlyphService:
    resolved_root = root or repository_root()
    return GlyphService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        ProcessGlyphGenerator(), FileSystemGlyphWorkspace(), str(resolved_root),
    )


def workspace_initializer(root: Path | None = None) -> WorkspaceInitializer:
    resolved_root = root or repository_root()
    return WorkspaceInitializer(
        FileSystemWorkspaceStore(), str(resolved_root / "config")
    )


def build_configuration_service(root: Path | None = None) -> BuildConfigurationService:
    resolved_root = root or repository_root()
    repository = PyYamlConfigurationRepository(resolved_root / "config")
    return BuildConfigurationService(repository)


def doctor_query(root: Path | None = None) -> DoctorQuery:
    resolved_root = root or repository_root()
    return DoctorQuery(ProcessToolProbe(resolved_root), catalog_service(resolved_root))


def vector_quality_gate(root: Path | None = None) -> VectorQualityGate:
    resolved_root = root or repository_root()
    return VectorQualityGate(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemPmtilesHeaderReader(),
        FileSystemVectorQualityReader(), ProcessPmtilesMetadataReader(),
        FileDigestAdapter(), FileSystemManifestEvidenceReader(),
    )


def raster_quality_gate(root: Path | None = None) -> RasterQualityGate:
    resolved_root = root or repository_root()
    return RasterQualityGate(
        catalog_service(resolved_root), FileSystemPmtilesHeaderReader(),
        ProcessPmtilesMetadataReader(), FileDigestAdapter(),
        FileSystemManifestEvidenceReader(), ProcessRasterTileSampleVerifier(),
    )


def base_staging_quality_gate(root: Path | None = None) -> BaseStagingQualityGate:
    resolved_root = root or repository_root()
    return BaseStagingQualityGate(
        build_configuration_service(resolved_root), FileSystemStagedLayerReader()
    )


def style_quality_gate(root: Path | None = None) -> StyleQualityGate:
    resolved_root = root or repository_root()
    return StyleQualityGate(
        build_configuration_service(resolved_root), FileSystemStyleQualityReader()
    )


def vector_tile_sampling_gate(root: Path | None = None) -> VectorTileSamplingGate:
    return VectorTileSamplingGate(
        FileSystemStagedLayerReader(), ProcessVectorTileReader(), FileSystemPmtilesHeaderReader(),
        build_configuration_service(root or repository_root()),
    )


def base_deep_quality_gate(root: Path | None = None) -> BaseDeepQualityGate:
    resolved_root = root or repository_root()
    return BaseDeepQualityGate(
        base_staging_quality_gate(resolved_root), vector_tile_sampling_gate(resolved_root)
    )


def vector_build_executor(root: Path | None = None) -> VectorBuildStageExecutor:
    resolved_root = root or repository_root()
    return VectorBuildStageExecutor(
        build_configuration_service(resolved_root), FileSystemBuildSourceWorkspace(),
        tags_filter_service(resolved_root), layer_export_service(resolved_root),
        layer_normalization_service(resolved_root), place_admin_service(resolved_root),
        island_water_service(resolved_root), island_anchor_service(resolved_root),
        admin_line_service(resolved_root), profile_transform_service(resolved_root),
        tippecanoe_service(resolved_root), vector_finalization_service(resolved_root),
        base_deep_quality_gate(resolved_root),
        glyph_service(resolved_root), sprite_service(resolved_root),
        style_service(resolved_root), style_quality_gate(resolved_root),
    )


def vector_build_execution_service(
    root: Path | None = None,
    reporter=None,
) -> BuildExecutionService:
    return BuildExecutionService(vector_build_executor(root), reporter=reporter)


def vector_build_preparation_service() -> VectorBuildPreparationService:
    return VectorBuildPreparationService(FileSystemBuildArtifactStore())


base_build_executor = vector_build_executor
base_build_execution_service = vector_build_execution_service
base_build_preparation_service = vector_build_preparation_service


def vector_finalization_service(
    root: Path | None = None,
) -> VectorFinalizationService:
    resolved_root = root or repository_root()
    return VectorFinalizationService(
        catalog_service(resolved_root), vector_metadata_service(resolved_root),
        vector_manifest_service(resolved_root), attribution_writer_service(),
        vector_quality_gate(resolved_root), artifact_file_verifier(),
    )


def artifact_query() -> ArtifactQuery:
    return ArtifactQuery(FileDigestAdapter())


def artifact_file_verifier() -> ArtifactFileVerifier:
    return ArtifactFileVerifier(FileSystemArtifactStore(), FileDigestAdapter())


def artifact_publication_service() -> ArtifactPublicationService:
    return ArtifactPublicationService(
        FileSystemArtifactStore(), FileDigestAdapter(), AtomicFileWriter()
    )


def attribution_writer_service() -> AttributionWriterService:
    return AttributionWriterService(AtomicFileWriter())


def sha512_sidecar_writer_service() -> Sha512SidecarWriterService:
    return Sha512SidecarWriterService(
        FileSystemArtifactStore(), FileDigestAdapter(), AtomicFileWriter()
    )


def checksum_manifest_writer() -> ChecksumManifestWriter:
    return ChecksumManifestWriter(
        FileSystemManifestStore(), FileDigestAdapter(), AtomicFileWriter()
    )


def bundle_service() -> BundleService:
    return BundleService(PmtilesViewportReader())


def vector_metadata_service(root: Path | None = None) -> VectorMetadataService:
    resolved_root = root or repository_root()
    writer, digest = AtomicFileWriter(), FileDigestAdapter()
    return VectorMetadataService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemPmtilesHeaderReader(), ProcessPmtilesMetadataEditor(),
        FileSystemMetadataStore(writer, digest),
    )


def vector_manifest_service(root: Path | None = None) -> VectorManifestService:
    resolved_root = root or repository_root()
    return VectorManifestService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemPmtilesHeaderReader(), FileSystemManifestEvidenceReader(),
        ProcessToolVersionReader(), FileDigestAdapter(),
        JsonManifestWriter(AtomicFileWriter()),
    )


def raster_manifest_service(root: Path | None = None) -> RasterManifestService:
    resolved_root = root or repository_root()
    return RasterManifestService(
        catalog_service(resolved_root), build_configuration_service(resolved_root),
        FileSystemPmtilesHeaderReader(), FileSystemManifestEvidenceReader(),
        ProcessToolVersionReader(), FileDigestAdapter(),
        JsonManifestWriter(AtomicFileWriter()),
    )
