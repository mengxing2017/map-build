from __future__ import annotations

import os
import shutil
from pathlib import Path


class FileSystemWorkspaceStore:
    @staticmethod
    def _path(root: str, relative_path: str) -> Path:
        return Path(root) / relative_path if relative_path else Path(root)

    def ensure_directory(self, root: str, relative_path: str) -> None:
        self._path(root, relative_path).mkdir(parents=True, exist_ok=True)

    def set_directory_mode(self, root: str, relative_path: str, mode: int) -> None:
        os.chmod(self._path(root, relative_path), mode)

    def copy_configuration(self, source: str, root: str) -> None:
        shutil.copytree(source, self._path(root, "config"), dirs_exist_ok=True)

    def set_configuration_modes(
        self, root: str, directory_mode: int, file_mode: int
    ) -> None:
        config = self._path(root, "config")
        for directory, _, files in os.walk(config):
            os.chmod(directory, directory_mode)
            for filename in files:
                path = Path(directory) / filename
                if not path.is_symlink():
                    os.chmod(path, file_mode)
