import json
import os
import tempfile
from pathlib import Path

import yaml

from huavd_map_build.catalog.south.adapter.yaml.loader import _SAFE_LOADER


class YamlJsonTranscoder:
    def transcode(self, source_path: str, output_path: str) -> None:
        source = Path(source_path)
        target = Path(output_path)
        try:
            with source.open("r", encoding="utf-8") as stream:
                document = yaml.load(stream, Loader=_SAFE_LOADER)
        except (OSError, yaml.YAMLError) as error:
            raise RuntimeError(f"cannot decode {source}: {error}") from error
        target.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        descriptor, temporary = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
