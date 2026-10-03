from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.style import StyleRequest, compile_styles
from huavd_map_build.production.south.port.style import StyleStore, StyleViewportReader


class StyleService:
    def __init__(self, catalog: CatalogService, configuration: BuildConfigurationService,
                 store: StyleStore, viewport: StyleViewportReader) -> None:
        self._catalog, self._configuration = catalog, configuration
        self._store, self._viewport = store, viewport

    def run(self, request: StyleRequest) -> tuple[str, str, str]:
        self._catalog.region(request.region)
        resolved = self._configuration.style(request.region.value, request.locale)
        root, session = request.workdir.rstrip("/"), request.session.value
        base = f"{root}/outputs/{session}.base.pmtiles"
        viewport = self._viewport.read(base) if self._store.is_file(base) else {}
        documents = compile_styles(
            resolved["config"], resolved["locale"], resolved["effective_base_layers"],
            viewport, request.pmtiles_url,
        )
        return self._store.publish(
            f"{root}/outputs/{session}.style.json",
            f"{root}/cache/bake/{session}/style-render.json",
            f"{root}/outputs/{session}.style-raster.json",
            documents,
        )
