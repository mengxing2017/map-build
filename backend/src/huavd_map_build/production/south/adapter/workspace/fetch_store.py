from pathlib import Path


class FileSystemFetchStore:
    def ensure_directory(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    def is_file(self, path: str) -> bool:
        return Path(path).is_file()

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")
