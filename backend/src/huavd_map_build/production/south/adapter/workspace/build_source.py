from __future__ import annotations

from pathlib import Path
import hashlib
import os
import shutil
import tempfile


class FileSystemBuildSourceWorkspace:
    def link(self, input_path: str, workdir: str, session: str) -> str:
        source = Path(input_path)
        if not source.is_absolute():
            source = source.resolve() if source.exists() else Path(workdir) / source
        if not source.is_file():
            raise ValueError(f"required input PBF does not exist: {source}")
        staging = Path(workdir) / "staging" / session
        staging.mkdir(parents=True, exist_ok=True)
        target = staging / "source.osm.pbf"
        if source.resolve() == target.resolve() and not target.is_symlink():
            return str(target)
        def digest(path):
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        before = digest(source)
        with tempfile.NamedTemporaryFile(dir=staging, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(source, temporary)
            if digest(temporary) != before or digest(source) != before:
                raise ValueError("input PBF changed while freezing build source")
            temporary.chmod(0o444)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return str(target)
