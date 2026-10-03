from typing import Protocol


class AtomicWriter(Protocol):
    def write_text(self, path: str, content: str) -> None: ...
