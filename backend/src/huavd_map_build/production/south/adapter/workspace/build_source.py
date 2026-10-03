from __future__ import annotations

from pathlib import Path


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
        if target.is_symlink() or target.exists():
            target.unlink()
        target.symlink_to(source.resolve())
        return str(target)
