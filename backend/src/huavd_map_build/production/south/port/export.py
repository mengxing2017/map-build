from typing import Protocol


class ExportRunner(Protocol):
    def export(
        self,
        input_path: str,
        output_path: str,
        config_path: str,
        keep_untagged: bool,
    ) -> None: ...


class ExportWorkspace(Protocol):
    def require_file(self, path: str) -> None: ...

    def ensure_directory(self, path: str) -> None: ...

    def copy_file(self, source: str, destination: str) -> None: ...
