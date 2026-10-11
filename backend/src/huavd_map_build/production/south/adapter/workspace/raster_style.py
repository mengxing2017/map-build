from __future__ import annotations

import json
from pathlib import Path
import tempfile

from huavd_map_build.production.domain.raster import RasterSourceMetadata, rewrite_bake_source


class FileSystemRasterRuntimeStyleStore:
    def write(self, source_path: str, output_path: str, tile_url: str,
              metadata: RasterSourceMetadata) -> None:
        source, target = Path(source_path), Path(output_path)
        document = json.loads(source.read_text(encoding="utf-8"))
        runtime = rewrite_bake_source(document, tile_url=tile_url, metadata=metadata)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", delete=False,
        ) as output:
            temporary = Path(output.name)
            try:
                json.dump(runtime, output, ensure_ascii=False, separators=(",", ":"))
                output.write("\n")
                output.flush()
                temporary.replace(target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
