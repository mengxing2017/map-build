from pathlib import Path


class FileSystemArtifactStore:
    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def is_file(self, path: str) -> bool:
        return Path(path).is_file()

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")
