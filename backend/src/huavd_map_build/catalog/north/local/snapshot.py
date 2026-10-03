from huavd_map_build.catalog.domain.snapshot import CatalogSnapshot
from huavd_map_build.catalog.south.port.repository import RegionCatalogRepository
from huavd_map_build.catalog.south.port.snapshot import CatalogSnapshotWriter


class CatalogSnapshotService:
    def __init__(
        self, repository: RegionCatalogRepository, writer: CatalogSnapshotWriter
    ) -> None:
        self._repository = repository
        self._writer = writer

    def write(self, output_path: str) -> CatalogSnapshot:
        snapshot = CatalogSnapshot.from_catalog(self._repository.load())
        self._writer.write(output_path, snapshot)
        return snapshot
