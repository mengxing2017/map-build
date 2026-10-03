from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.admin_line import AdminLineRequest
from huavd_map_build.production.south.port.admin_line import AdminLineStore, RelationLevelReader
from huavd_map_build.shared.kernel import RegionId


class AdminLineService:
    def __init__(self, catalog: CatalogService, configuration: BuildConfigurationService,
                 store: AdminLineStore, relation_reader: RelationLevelReader) -> None:
        self._catalog, self._configuration = catalog, configuration
        self._store, self._relation_reader = store, relation_reader

    def run(self, request: AdminLineRequest) -> str:
        root = request.workdir.rstrip("/")
        if request.overview:
            self._configuration.require_overview(request.target)
            stage = f"{root}/staging/overviews/{request.target}-{request.build_date}"
            input_path = request.input_path or f"{stage}/layers/admin_line.geojsonseq"
            if request.filtered_pbf:
                filtered_pbf = request.filtered_pbf
            else:
                source = f"{stage}/source.osm.pbf"
                self._store.require_file(source)
                digest = self._store.sha512(source)
                filtered_pbf = (f"{root}/cache/overview-tags-filter/{request.target}/"
                                f"{digest}/admin_line.osm.pbf")
            derived = f"{root}/derived/overview/{request.target}-{request.build_date}"
            hierarchy = self._configuration.admin_line_hierarchy(default_only=True)
        else:
            region = RegionId(request.target)
            configured = self._catalog.region(region)
            input_path = request.input_path or (
                f"{root}/staging/{request.session}/layers/admin_line.geojsonseq")
            filtered_pbf = request.filtered_pbf or (
                f"{root}/cache/tags-filter/{configured.slug}-admin_line.osm.pbf")
            derived = f"{root}/derived/{request.session}"
            hierarchy = self._configuration.admin_line_hierarchy(request.target)
        self._store.require_file(input_path)
        self._store.require_file(filtered_pbf)
        report = f"{derived}/admin-line-tier-report.json"
        if not self._store.is_nonempty(input_path):
            self._store.write_empty_report(report, request.target)
            return report
        levels = self._relation_reader.read(filtered_pbf)
        return self._store.transform(
            input_path, filtered_pbf, derived, request.target, levels, hierarchy)
