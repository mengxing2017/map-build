import hashlib
import json
from pathlib import Path
from typing import Any


class FileSystemStyleQualityReader:
    def read_json(self, path: str) -> dict[str, Any]:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"expected JSON object: {path}")
        return document

    def matching_files(self, directory: str, suffix: str) -> tuple[str, ...]:
        root = Path(directory)
        if not root.is_dir():
            return ()
        return tuple(str(path) for path in sorted(root.rglob(f"*{suffix}")) if path.is_file())

    def sidecar_matches(self, path: str) -> bool:
        source = Path(path)
        sidecar = Path(f"{path}.sha512")
        if not source.is_file() or not sidecar.is_file():
            return False
        fields = sidecar.read_text(encoding="utf-8").split()
        if not fields:
            return False
        digest = hashlib.sha512(source.read_bytes()).hexdigest()
        return fields[0].lower() == digest
