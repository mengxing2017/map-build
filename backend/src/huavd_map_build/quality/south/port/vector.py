from typing import Any, Protocol


class VectorQualityFileReader(Protocol):
    def read_json(self, path: str) -> dict[str, Any]: ...
    def size(self, path: str) -> int: ...


class EmbeddedMetadataReader(Protocol):
    def embedded_metadata(self, path: str) -> dict[str, Any]: ...
