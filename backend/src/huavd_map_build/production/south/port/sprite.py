from typing import Protocol

from huavd_map_build.production.domain.sprite import SpriteDocuments


class SpriteStore(Protocol):
    def publish(
        self, output_directory: str, documents: SpriteDocuments, force: bool
    ) -> tuple[str, ...]: ...
