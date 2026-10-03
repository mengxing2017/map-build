from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.place_admin import PlaceAdminRequest, enrich_place_labels
from huavd_map_build.production.south.port.place_admin import PlaceAdminIndexStore, PlaceAdminTool


class PlaceAdminService:
    def __init__(self, catalog: CatalogService, configuration: BuildConfigurationService,
                 store: PlaceAdminIndexStore, tool: PlaceAdminTool) -> None:
        self._catalog, self._configuration = catalog, configuration
        self._store, self._tool = store, tool

    def run(self, request: PlaceAdminRequest) -> str:
        self._catalog.region(request.region)
        hierarchy = self._configuration.place_label_hierarchy(request.region.value)
        root, session = request.workdir.rstrip("/"), request.session.value
        source = self._store.resolve_workspace_path(request.input_path, root)
        labels = f"{root}/staging/{session}/layers/place_label.geojsonseq"
        report = f"{root}/staging/{session}/place_label_dedup_report.json"
        self._store.require_file(source)
        self._store.require_file(labels)
        if not self._store.is_nonempty(labels):
            self._store.write_empty_report(report)
            return report
        cache = f"{root}/cache/place-admin/{session}"
        relations_pbf, relations_index, nodes_index, export_config = self._store.prepare(cache)
        boundaries_geojsonseq = f"{cache}/admin-boundaries.geojsonseq"
        boundaries_index = f"{cache}/admin-boundaries.ndjson"
        self._tool.filter_source(source, relations_pbf)
        relations, node_wikidata = self._tool.read_relations_and_nodes(relations_pbf)
        self._store.write_relation_indexes(
            relations_index, nodes_index, relations, node_wikidata
        )
        self._tool.export_boundaries(relations_pbf, boundaries_geojsonseq, export_config)
        boundaries = self._store.read_boundaries(boundaries_geojsonseq)
        self._store.write_boundary_index(boundaries_index, boundaries)
        result = enrich_place_labels(
            self._store.read_features(labels), relations, node_wikidata,
            boundaries, hierarchy,
        )
        self._store.publish(labels, report, result.features, result.report)
        return report
