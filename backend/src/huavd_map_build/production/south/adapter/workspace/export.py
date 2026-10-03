from pathlib import Path
import shutil


class FileSystemExportWorkspace:
    def require_file(self, path: str) -> None:
        if not Path(path).is_file():
            raise ValueError(f"required file does not exist: {path}")

    def ensure_directory(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)

    def copy_file(self, source: str, destination: str) -> None:
        shutil.copy2(source, destination)
