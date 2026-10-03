import os
from pathlib import Path


class FileSystemManifestStore:
    def list_regular_files(self, root: str) -> tuple[str, ...]:
        base = Path(root)
        if not base.is_dir():
            raise ValueError(f"manifest root is not a directory: {root}")
        files = (
            f"./{path.relative_to(base).as_posix()}"
            for path in base.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        return tuple(sorted(files, key=os.fsencode))
