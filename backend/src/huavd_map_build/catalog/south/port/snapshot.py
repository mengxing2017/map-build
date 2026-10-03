from typing import Protocol

from huavd_map_build.catalog.domain.snapshot import CatalogSnapshot


class CatalogSnapshotWriter(Protocol):
    def write(self, output_path: str, snapshot: CatalogSnapshot) -> None: ...
