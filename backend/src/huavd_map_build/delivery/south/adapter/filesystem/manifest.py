from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
from typing import Any

from huavd_map_build.delivery.domain.manifest import SourceEvidence
from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter


class FileSystemManifestEvidenceReader:
    def source(self, source_path: str, md5_path: str) -> SourceEvidence:
        source, sidecar = Path(source_path), Path(md5_path)
        size = source.stat().st_size if source.exists() else None
        downloaded = (
            datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ) if source.exists() else None
        )
        md5 = None
        if sidecar.is_file():
            values = sidecar.read_text(encoding="utf-8").split()
            md5 = values[0] if values else None
        digest = None
        if source.is_file():
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return SourceEvidence(size, downloaded, md5, digest)

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
