from typing import Any, Protocol

from huavd_map_build.delivery.domain.metadata import PmtilesHeader


class PmtilesHeaderReader(Protocol):
    def read(self, path: str) -> PmtilesHeader: ...


class PmtilesMetadataEditor(Protocol):
    def edit(self, pmtiles_path: str, metadata_path: str) -> None: ...


class MetadataStore(Protocol):
    def is_file(self, path: str) -> bool: ...

    def write_document(self, path: str, document: dict[str, Any]) -> None: ...

    def write_sidecar(self, path: str) -> str: ...
