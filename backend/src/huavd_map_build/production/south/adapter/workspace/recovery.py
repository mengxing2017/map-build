from pathlib import Path


class FileSystemBuildArtifactStore:
    def existing(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            path for path in paths
            if Path(path).exists() or Path(path).is_symlink()
        )

    def remove(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        removed: list[str] = []
        for value in paths:
            path = Path(value)
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_dir() and not path.is_symlink():
                raise ValueError(f"refusing to remove artifact directory: {path}")
            path.unlink()
            removed.append(value)
        return tuple(removed)
