from typing import Protocol


class ManifestFileStore(Protocol):
    def list_regular_files(self, root: str) -> tuple[str, ...]: ...
