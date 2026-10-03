from __future__ import annotations

import hashlib
import os
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import tempfile
import uuid

from huavd_map_build.production.domain.sprite import SpriteDocuments


class FileSystemSpriteStore:
    _ARTIFACTS = (
        ("sprite.json", "index"),
        ("sprite.png", "image"),
        ("sprite@2x.json", "index_2x"),
        ("sprite@2x.png", "image_2x"),
    )

    def publish(
        self, output_directory: str, documents: SpriteDocuments, force: bool
    ) -> tuple[str, ...]:
        target = Path(output_directory)
        if target.exists() and not force:
            raise ValueError(
                f"sprite output already exists: {target}; pass --force or clean first"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        backup: Path | None = None
        try:
            paths = []
            for name, attribute in self._ARTIFACTS:
                data = getattr(documents, attribute)
                artifact = temporary / name
                self._write_bytes(artifact, data)
                digest = hashlib.sha512(data).hexdigest()
                self._write_bytes(
                    Path(f"{artifact}.sha512"),
                    f"{digest}  {PurePosixPath(name).name}\n".encode("ascii"),
                )
                paths.append(str(target / name))
            if target.exists():
                backup = target.with_name(f".{target.name}.old-{uuid.uuid4().hex}")
                os.replace(target, backup)
            os.replace(temporary, target)
            temporary = Path()
            self._sync_directory(target.parent)
            if backup is not None:
                self._remove(backup)
            return tuple(paths)
        except BaseException:
            if backup is not None and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        finally:
            if temporary != Path() and temporary.exists():
                self._remove(temporary)

    @staticmethod
    def _write_bytes(path: Path, content: bytes) -> None:
        with path.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
