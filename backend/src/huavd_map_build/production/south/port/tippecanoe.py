from typing import Protocol


class TippecanoeRunner(Protocol):
    def run(self, arguments: tuple[str, ...]) -> None: ...


class TippecanoeWorkspace(Protocol):
    def require_file(self, path: str) -> None: ...

    def ensure_directory(self, path: str) -> None: ...
