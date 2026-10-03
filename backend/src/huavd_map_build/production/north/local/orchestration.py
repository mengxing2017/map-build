from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.model import BuildPlan
from huavd_map_build.production.domain.orchestration import (
    BuildExecutionPlan,
    create_execution_plan,
)
from huavd_map_build.shared.kernel import Role


class BuildOrchestrationPlanner:
    def __init__(
        self, catalog: CatalogService, configuration: BuildConfigurationService
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration

    def plan(
        self, build: BuildPlan, glyph: bool, force_building: bool = False
    ) -> BuildExecutionPlan:
        settings = self._catalog.region_settings(
            build.region, "base", build.build_date.value
        )
        skipped: tuple[Role, ...] = ()
        if Role.BUILDING in build.roles and not settings["building_enabled"]:
            if len(build.roles) == 1 and not force_building:
                raise ValueError(
                    f"building role is not enabled for region {build.region.value}"
                )
            if not force_building:
                skipped = (Role.BUILDING,)
        effective_roles = tuple(role for role in build.roles if role not in skipped)
        layers: list[str] = []
        for role in effective_roles:
            if role not in (Role.BASE, Role.BUILDING):
                continue
            for layer in self._configuration.tippecanoe(
                build.region.value, role.value
            )["source_layers"]:
                if layer not in layers:
                    layers.append(layer)
        has_profile = self._configuration.profile_transform(
            build.region.value
        ) is not None
        return create_execution_plan(
            build, tuple(layers), glyph, has_profile, skipped
        )
