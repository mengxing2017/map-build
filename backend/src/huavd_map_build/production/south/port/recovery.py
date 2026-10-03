from typing import Protocol


class BuildArtifactStore(Protocol):
    def existing(self, paths: tuple[str, ...]) -> tuple[str, ...]: ...

    def remove(self, paths: tuple[str, ...]) -> tuple[str, ...]: ...
