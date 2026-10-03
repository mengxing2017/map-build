import json
from pathlib import Path
from typing import Any


class FileSystemVectorQualityReader:
    def read_json(self, path: str) -> dict[str, Any]:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"expected JSON object: {path}")
        return document

    def size(self, path: str) -> int:
        return Path(path).stat().st_size
