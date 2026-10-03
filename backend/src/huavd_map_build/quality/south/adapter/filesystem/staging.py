from __future__ import annotations

from collections.abc import Iterator
import hashlib
import json
from pathlib import Path
from typing import Any


class FileSystemStagedLayerReader:
    def exists(self, path: str) -> bool:
        return Path(path).is_file()

    def features(self, path: str) -> Iterator[tuple[int, dict[str, Any]]]:
        with Path(path).open("r", encoding="utf-8") as stream:
            for line_number, raw in enumerate(stream, 1):
                value = raw.lstrip("\x1e").strip()
                if not value:
                    continue
                try:
                    document = json.loads(value)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"invalid GeoJSONSeq at {path}:{line_number}: {error.msg}"
                    ) from error
                if not isinstance(document, dict):
                    raise ValueError(
                        f"GeoJSONSeq feature must be an object at {path}:{line_number}"
                    )
                yield line_number, document

    def json_document(self, path: str) -> dict[str, Any]:
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON at {path}: {error.msg}") from error
        if not isinstance(document, dict):
            raise ValueError(f"JSON document must be an object: {path}")
        return document

    def sha512(self, path: str) -> str:
        digest = hashlib.sha512()
        with Path(path).open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()
