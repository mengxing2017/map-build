from typing import Any

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.tippecanoe import (
    TippecanoePlan,
    TippecanoeRequest,
)
from huavd_map_build.production.south.port.tippecanoe import (
    TippecanoeRunner,
    TippecanoeWorkspace,
)
from huavd_map_build.shared.kernel import Role


class TippecanoeService:
    _FLAGS = (
        ("drop_densest_as_needed", "--drop-densest-as-needed"),
        ("extend_zooms_if_still_dropping", "--extend-zooms-if-still-dropping"),
        ("detect_shared_borders", "--detect-shared-borders"),
        ("coalesce_densest_as_needed", "--coalesce-densest-as-needed"),
        ("read_parallel", "--read-parallel"),
        ("no_tile_size_limit", "--no-tile-size-limit"),
        ("force_feature_limit", "--force-feature-limit"),
        ("simplify_only_low_zooms", "--simplify-only-low-zooms"),
    )

    def __init__(
        self,
        catalog: CatalogService,
        configuration: BuildConfigurationService,
        workspace: TippecanoeWorkspace,
        runner: TippecanoeRunner,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._workspace = workspace
        self._runner = runner

    def run(self, request: TippecanoeRequest) -> TippecanoePlan:
        if request.role not in {Role.BASE, Role.BUILDING}:
            raise ValueError("tippecanoe role must be base or building")
        region = self._catalog.region(request.region)
        settings = self._configuration.tippecanoe(region.id.value, request.role.value)
        layers = self._string_list(settings, "source_layers")
        root = request.workdir.rstrip("/")
        layers_directory = f"{root}/staging/{request.session}/layers"
        output_directory = f"{root}/outputs"
        self._workspace.ensure_directory(output_directory)
        output = (
            f"{output_directory}/{region.slug}-{request.build_date}.{request.role.value}.pmtiles"
        )
        layer_paths = tuple(
            (layer, f"{layers_directory}/{layer}.geojsonseq") for layer in layers
        )
        for _layer, path in layer_paths:
            self._workspace.require_file(path)

        arguments = [
            f"-Z{self._integer(settings, 'min_zoom')}",
            f"-z{self._integer(settings, 'max_zoom')}",
            f"--maximum-tile-bytes={self._integer(settings, 'maximum_tile_bytes')}",
            f"--name={region.slug}-{request.build_date}.{request.role.value}",
            f"--attribution={settings.get('attribution', '© OpenStreetMap contributors')}",
            f"--output={output}",
        ]
        for key, flag in self._FLAGS:
            if settings.get(key) is True:
                arguments.append(flag)
        simplification = settings.get("simplification_at_maximum_zoom")
        if simplification is not None and simplification != "":
            arguments.append(f"--simplification-at-maximum-zoom={simplification}")
        for layer, path in layer_paths:
            arguments.extend(("-L", f"{layer}:{path}"))
        plan = TippecanoePlan(output, layer_paths, tuple(arguments))
        self._runner.run(plan.arguments)
        return plan

    @staticmethod
    def _integer(settings: dict[str, Any], key: str) -> int:
        value = settings.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"tippecanoe setting must be an integer: {key}")
        return value

    @staticmethod
    def _string_list(settings: dict[str, Any], key: str) -> tuple[str, ...]:
        value = settings.get(key)
        if not isinstance(value, list) or not value or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise ValueError(f"tippecanoe setting must be a non-empty string list: {key}")
        return tuple(value)
