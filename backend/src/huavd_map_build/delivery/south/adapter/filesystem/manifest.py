from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import re
from typing import Any

from huavd_map_build.delivery.domain.manifest import SourceEvidence
from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter


_MD5_RECORD = re.compile(r"[0-9a-fA-F]{32}(?:[ \t]+[^\r\n]+)?")


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _sidecar_digest(path: Path | None) -> tuple[str | None, os.stat_result | None]:
    if path is None:
        return None, None
    try:
        if not path.exists() and not path.is_symlink():
            return None, None
        if not path.is_file():
            raise ValueError(f"MD5 sidecar is not a readable regular file: {path}")
        info = path.stat()
        record = path.read_text(encoding="utf-8").splitlines()
        if len(record) != 1 or _MD5_RECORD.fullmatch(record[0]) is None:
            raise ValueError(f"invalid MD5 sidecar (expected one digest record): {path}")
        return record[0][:32].lower(), info
    except (OSError, UnicodeError) as error:
        raise ValueError(f"cannot verify MD5 sidecar {path}: {error}") from error


class FileSystemManifestEvidenceReader:
    def source(self, source_path: str, md5_path: str | None) -> SourceEvidence:
        source = Path(source_path)
        try:
            if not source.exists() and not source.is_symlink():
                raise ValueError(f"source PBF is missing: {source}")
            if source.is_symlink() and not source.exists():
                raise ValueError(f"source PBF is a dangling link: {source}")
            if not source.is_file():
                raise ValueError(f"source PBF is not a regular file: {source}")
            expected_md5, sidecar_info = _sidecar_digest(
                Path(md5_path) if md5_path else None
            )
            before = source.stat()
            md5 = hashlib.md5() if expected_md5 is not None else None
            sha256 = hashlib.sha256()
            with source.open("rb") as stream:
                if _identity(before) != _identity(os.fstat(stream.fileno())):
                    raise ValueError(f"source PBF changed before reading: {source}")
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    sha256.update(chunk)
                    if md5 is not None:
                        md5.update(chunk)
                after = os.fstat(stream.fileno())
            current = source.stat()
            if _identity(before) != _identity(after) or _identity(before) != _identity(current):
                raise ValueError(f"source PBF changed while reading: {source}")
            if sidecar_info is not None:
                try:
                    sidecar_after = Path(md5_path).stat()
                except OSError as error:
                    raise ValueError(
                        f"cannot verify MD5 sidecar {md5_path}: {error}"
                    ) from error
                if _identity(sidecar_info) != _identity(sidecar_after):
                    raise ValueError(f"MD5 sidecar changed while reading: {md5_path}")
        except (OSError, UnicodeError) as error:
            raise ValueError(f"cannot read source PBF {source}: {error}") from error
        if md5 is not None and md5.hexdigest() != expected_md5:
            raise ValueError(f"MD5 mismatch for input: {source}")
        return SourceEvidence(
            before.st_size,
            datetime.fromtimestamp(before.st_mtime, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            expected_md5,
            sha256.hexdigest(),
        )

    def size(self, path: str) -> int:
        return Path(path).stat().st_size

    def read_json(self, path: str) -> dict[str, Any]:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"expected JSON object: {path}")
        return document

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")


class JsonManifestWriter:
    def __init__(self, writer: AtomicWriter) -> None:
        self._writer = writer

    def write(self, path: str, document: dict[str, Any]) -> None:
        self._writer.write_text(
            path, json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        )
