from typing import Any

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.profile_transform import (
    FeatureRule,
    LayerProfilePolicy,
    ProfileTransformRequest,
)
from huavd_map_build.production.south.port.profile_transform import ProfileTransformer


class ProfileTransformService:
    def __init__(
        self,
        catalog: CatalogService,
        configuration: BuildConfigurationService,
        transformer: ProfileTransformer,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._transformer = transformer

    def run(self, request: ProfileTransformRequest) -> str | None:
        self._catalog.region(request.region)
        if not request.layers or request.layers == "all":
            raise ValueError("--layers must name the effective base layers")
        profile = self._configuration.profile_transform(request.region.value)
        if profile is None:
            return None
        selected = tuple(name for name in request.layers.split(",") if name)
        expected = tuple(layer["name"] for layer in profile["layers"])
        if selected != expected:
            raise ValueError("profile transform layers do not match effective base layers")
        policies = tuple(self._policy(layer) for layer in profile["layers"])
        directory = f"{request.workdir.rstrip('/')}/staging/{request.session}/layers"
        paths = tuple(f"{directory}/{policy.layer}.geojsonseq" for policy in policies)
        for path in paths:
            self._transformer.require_file(path)
        for path, policy in zip(paths, policies, strict=True):
            if self._transformer.is_nonempty(path):
                self._transformer.transform(path, policy)
        return str(profile["name"])

    @staticmethod
    def _policy(value: dict[str, Any]) -> LayerProfilePolicy:
        raw_rules = value.get("rules")
        rules = None if raw_rules is None else tuple(
            FeatureRule(rule["when"], rule["min_zoom"], rule["max_zoom"])
            for rule in raw_rules["rules"]
        )
        return LayerProfilePolicy(
            value["name"], value["min_zoom"], value["max_zoom"], rules
        )
