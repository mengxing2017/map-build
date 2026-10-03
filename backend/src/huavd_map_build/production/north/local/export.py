from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.export import (
    ExportPlan,
    ExportRequest,
    LayerExportTask,
)
from huavd_map_build.production.south.port.export import ExportRunner, ExportWorkspace


class LayerExportService:
    def __init__(
        self,
        catalog: CatalogService,
        configuration: BuildConfigurationService,
        workspace: ExportWorkspace,
        runner: ExportRunner,
        config_root: str,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._workspace = workspace
        self._runner = runner
        self._config_root = config_root.rstrip("/")

    def run(self, request: ExportRequest) -> ExportPlan:
        region = self._catalog.region(request.region)
        cache = f"{request.workdir.rstrip('/')}/cache/tags-filter"
        staging = f"{request.workdir.rstrip('/')}/staging/{request.session}"
        staged_configs = f"{staging}/export-config"
        layers_directory = f"{staging}/layers"
        self._workspace.ensure_directory(staged_configs)
        self._workspace.ensure_directory(layers_directory)
        tasks = tuple(
            LayerExportTask(
                layer=name,
                input_path=f"{cache}/{region.slug}-{name}.osm.pbf",
                source_config=f"{self._config_root}/export-config/{name}.json",
                staged_config=f"{staged_configs}/{name}.json",
                output_path=f"{layers_directory}/{name}.geojsonseq",
                keep_untagged=keep_untagged,
            )
            for name, keep_untagged in self._configuration.export_layers(request.layers)
        )
        for task in tasks:
            self._workspace.require_file(task.source_config)
            self._workspace.require_file(task.input_path)
        for task in tasks:
            self._workspace.copy_file(task.source_config, task.staged_config)
            self._runner.export(
                task.input_path,
                task.output_path,
                task.staged_config,
                task.keep_untagged,
            )
        return ExportPlan(layers_directory, tasks)
