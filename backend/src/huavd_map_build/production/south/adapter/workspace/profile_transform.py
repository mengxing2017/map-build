import json
import os
from pathlib import Path

from huavd_map_build.production.domain.profile_transform import (
    LayerProfilePolicy,
    transform_profile_feature,
)


class FileSystemProfileTransformer:
    def require_file(self, path: str) -> None:
        if not Path(path).is_file():
            raise ValueError(f"required file does not exist: {path}")

    def is_nonempty(self, path: str) -> bool:
        return Path(path).stat().st_size > 0

    def transform(self, path: str, policy: LayerProfilePolicy) -> None:
        source = Path(path)
        temporary = Path(f"{path}.profile.tmp")
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
                    transformed = transform_profile_feature(feature, policy)
                    if transformed is not None:
                        output_stream.write("\x1e")
                        json.dump(transformed, output_stream, ensure_ascii=False, separators=(",", ":"))
                        output_stream.write("\n")
            os.replace(temporary, source)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
