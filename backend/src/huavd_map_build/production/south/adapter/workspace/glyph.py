from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import tempfile
import uuid


class FileSystemGlyphWorkspace:
    _SYSTEM_FONTS = {
        "NotoSans-Regular.ttf": (
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ),
        "NotoSansCJKsc-Regular.otf": (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/source-han-cjk/SourceHanSansSC-Regular.otf",
        ),
        "NotoSansCJKjp-Regular.otf": (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/source-han-cjk/SourceHanSansSC-Regular.otf",
        ),
        "NotoSansCJKkr-Regular.otf": (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/source-han-cjk/SourceHanSansSC-Regular.otf",
        ),
    }

    def resolve_font(self, configured: str, repository_root: str) -> str:
        candidate = Path(configured)
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
        candidate = Path(repository_root) / configured
        if candidate.is_file():
            return str(candidate)
        for fallback in self._SYSTEM_FONTS.get(Path(configured).name, ()):
            if Path(fallback).is_file():
                return fallback
        raise ValueError(f"required file does not exist: {candidate}")

    def stage(self, output_directory: str, force: bool) -> str:
        target = Path(output_directory)
        if target.exists() and not force:
            raise ValueError(
                f"glyph output already exists: {target}; pass --force or clean first"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        return tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent)

    def prepare_generation(self, staging_directory: str, name: str) -> str:
        path = Path(staging_directory) / name
        path.mkdir()
        return str(path)

    def install_fontstack(
        self, generated_directory: str, target_directory: str, fontstack: str
    ) -> None:
        generated, target = Path(generated_directory), Path(target_directory)
        named = generated / fontstack
        candidates = [named] if named.is_dir() else sorted(
            path for path in generated.iterdir()
            if path.is_dir() and next(path.rglob("*.pbf"), None) is not None
        )
        if not candidates:
            raise GlyphOutputError(
                f"glyph generator did not create pbf output under {generated}"
            )
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidates[0], target)

    def publish(
        self, staging_directory: str, output_directory: str, manifest: dict
    ) -> tuple[str, ...]:
        staging, target = Path(staging_directory), Path(output_directory)
        artifacts = sorted(staging.rglob("*.pbf"))
        if not artifacts:
            raise GlyphOutputError(f"glyph output has no pbf files: {staging}")
        for artifact in artifacts:
            self._write_sidecar(artifact)
        manifest_path = staging / "manifest.json"
        self._write_bytes(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        self._write_sidecar(manifest_path)
        backup: Path | None = None
        try:
            if target.exists():
                backup = target.with_name(f".{target.name}.old-{uuid.uuid4().hex}")
                os.replace(target, backup)
            os.replace(staging, target)
            self._sync_directory(target.parent)
            if backup is not None:
                self.discard(str(backup))
            return tuple(
                str(target / artifact.relative_to(staging))
                for artifact in (*artifacts, manifest_path)
            )
        except BaseException:
            if backup is not None and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise

    def discard(self, staging_directory: str) -> None:
        path = Path(staging_directory)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    @classmethod
    def _write_sidecar(cls, artifact: Path) -> None:
        digest = hashlib.sha512(artifact.read_bytes()).hexdigest()
        cls._write_bytes(
            Path(f"{artifact}.sha512"),
            f"{digest}  {PurePosixPath(artifact.name).name}\n".encode("ascii"),
        )

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


class GlyphOutputError(RuntimeError):
    pass
