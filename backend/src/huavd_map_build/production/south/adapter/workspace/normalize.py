from __future__ import annotations

import json
import os
from pathlib import Path

from huavd_map_build.production.domain.normalize import (
    NormalizationPolicy,
    normalize_feature,
)


class FileSystemGeoJsonSeqNormalizer:
    def require_directory(self, path: str) -> None:
        if not Path(path).is_dir():
            raise ValueError(f"required directory does not exist: {path}")

    def require_file(self, path: str) -> None:
        if not Path(path).is_file():
            raise ValueError(f"required file does not exist: {path}")

    def normalize(self, path: str, policy: NormalizationPolicy) -> None:
        source = Path(path)
        temporary = Path(f"{path}.tmp")
        backup = Path(f"{path}.bak")
        try:
            with source.open("r", encoding="utf-8") as input_stream, temporary.open(
                "w", encoding="utf-8", newline="\n"
            ) as output_stream:
                for line_number, line in enumerate(input_stream, 1):
                    payload = line.removeprefix("\x1e").strip()
                    if not payload:
                        continue
                    try:
                        feature = json.loads(payload)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"invalid GeoJSONSeq at {path}:{line_number}: {error.msg}"
                        ) from error
                    if not isinstance(feature, dict):
                        raise ValueError(f"GeoJSONSeq feature must be an object: {path}:{line_number}")
                    normalized = normalize_feature(feature, policy)
                    if normalized is not None:
                        output_stream.write("\x1e")
                        json.dump(normalized, output_stream, ensure_ascii=False, separators=(",", ":"))
                        output_stream.write("\n")
            os.replace(source, backup)
            os.replace(temporary, source)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
