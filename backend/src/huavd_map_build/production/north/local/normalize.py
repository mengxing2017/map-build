from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.normalize import (
    NormalizationPolicy,
    NormalizeRequest,
)
from huavd_map_build.production.south.port.normalize import GeoJsonSeqNormalizer


class LayerNormalizationService:
    def __init__(
        self,
        catalog: CatalogService,
        configuration: BuildConfigurationService,
        normalizer: GeoJsonSeqNormalizer,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._normalizer = normalizer

    def run(self, request: NormalizeRequest) -> str:
        self._catalog.region(request.region)
        layers_directory = (
            f"{request.workdir.rstrip('/')}/staging/{request.session}/layers"
        )
        self._normalizer.require_directory(layers_directory)
        name_order = self._catalog.name_locale_priority(request.region)
        if not name_order:
            name_order = self._configuration.default_name_locale_priority()
        field_types = self._configuration.final_field_types(request.layers)
        policies = tuple(
            NormalizationPolicy(
                name, name_order, allowed, post_filter, field_types[name]
            )
            for name, allowed, post_filter in self._configuration.normalization_layers(
                request.layers
            )
        )
        paths = tuple(f"{layers_directory}/{policy.layer}.geojsonseq" for policy in policies)
        for path in paths:
            self._normalizer.require_file(path)
        for path, policy in zip(paths, policies, strict=True):
            self._normalizer.normalize(path, policy)
        return layers_directory
