from typing import Any, Protocol


class RelationLevelReader(Protocol):
    def read(self, pbf_path: str) -> dict[str, tuple[int, ...]]: ...


class AdminLineStore(Protocol):
    def require_file(self, path: str) -> None: ...

    def is_nonempty(self, path: str) -> bool: ...

    def sha512(self, path: str) -> str: ...

    def write_empty_report(self, path: str, target: str) -> None: ...

    def transform(
        self,
        input_path: str,
        filtered_pbf: str,
        derived_directory: str,
        target: str,
        relation_levels: dict[str, tuple[int, ...]],
        hierarchy: dict[str, dict[str, Any]],
    ) -> str: ...
