from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile

from huavd_map_build.production.domain.raster import (
    RasterCachePreparation,
    RasterExecutionError,
)


class FileSystemRasterCacheLifecycle:
    @contextmanager
    def open(
        self, identity: str, workspace: str, invalidation_paths: tuple[str, ...],
    ):
        root = Path(workspace).resolve()
        root.mkdir(parents=True, exist_ok=True)
        lock = root / ".bake.lock"
        try:
            lock.mkdir()
        except FileExistsError as error:
            raise RasterExecutionError(
                f"raster bake cache is already in use: {root}"
            ) from error
        try:
            (lock / "owner").write_text(f"{os.getpid()}\n", encoding="ascii")
            marker = root / "inputs.sha512"
            try:
                previous = marker.read_text(encoding="ascii").strip()
            except FileNotFoundError:
                previous = ""
            invalidated = previous != identity
            if invalidated:
                paths = tuple(Path(value).resolve() for value in invalidation_paths)
                for path in paths:
                    if path == root or root not in path.parents:
                        raise RasterExecutionError(
                            f"raster cache invalidation path escapes workspace: {path}"
                        )
                for path in paths:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                self._write_marker(marker, identity)
            yield RasterCachePreparation(identity, invalidated)
        finally:
            (lock / "owner").unlink(missing_ok=True)
            try:
                lock.rmdir()
            except FileNotFoundError:
                pass

    @staticmethod
    def _write_marker(marker: Path, identity: str) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="ascii", dir=marker.parent,
            prefix=f".{marker.name}.", delete=False,
        ) as output:
            temporary = Path(output.name)
            try:
                output.write(f"{identity}\n")
                output.flush()
                temporary.replace(marker)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
