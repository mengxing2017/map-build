from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.tags_filter import (
    LayerFilterTask,
    TagsFilterPlan,
    TagsFilterRequest,
)
from huavd_map_build.production.south.port.tags_filter import (
    TagsFilterRunner,
    TagsFilterWorkspace,
)


class TagsFilterService:
    def __init__(
        self,
        catalog: CatalogService,
        configuration: BuildConfigurationService,
        workspace: TagsFilterWorkspace,
        runner: TagsFilterRunner,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._workspace = workspace
        self._runner = runner

    def run(self, request: TagsFilterRequest) -> TagsFilterPlan:
        region = self._catalog.region(request.region)
        input_path = self._workspace.resolve_input(request.input_path, request.workdir)
        self._workspace.require_file(input_path)
        cache = f"{request.workdir.rstrip('/')}/cache/tags-filter"
        self._workspace.ensure_directory(cache)
        tasks = tuple(
            LayerFilterTask(
                layer=name,
                filters=filters,
                output_path=f"{cache}/{region.slug}-{name}.osm.pbf",
            )
            for name, filters in self._configuration.tags_filter_layers(request.layers)
        )
        for task in tasks:
            self._runner.filter(input_path, task.output_path, task.filters)
        return TagsFilterPlan(input_path, cache, tasks)
