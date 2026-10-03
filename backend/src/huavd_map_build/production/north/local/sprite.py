from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.sprite import (
    SpriteDocuments,
    SpriteRequest,
    plan_sprite,
    render_sprite,
)
from huavd_map_build.production.south.port.sprite import SpriteStore


class SpriteService:
    def __init__(
        self,
        catalog: CatalogService,
        configuration: BuildConfigurationService,
        store: SpriteStore,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._store = store

    def run(self, request: SpriteRequest) -> tuple[str, ...]:
        self._catalog.region(request.region)
        manifest = self._configuration.sprite_manifest()
        index, image = render_sprite(plan_sprite(manifest, 1))
        index_2x, image_2x = render_sprite(plan_sprite(manifest, 2))
        documents = SpriteDocuments(index, image, index_2x, image_2x)
        output = (
            f"{request.workdir.rstrip('/')}/outputs/{request.session.value}.sprite"
        )
        return self._store.publish(output, documents, request.force)
