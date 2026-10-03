from typing import Protocol


class TagsFilterRunner(Protocol):
    def filter(
        self, input_path: str, output_path: str, filters: tuple[str, ...]
    ) -> None: ...


class TagsFilterWorkspace(Protocol):
    def resolve_input(self, path: str, workdir: str) -> str: ...

    def require_file(self, path: str) -> None: ...

    def ensure_directory(self, path: str) -> None: ...
