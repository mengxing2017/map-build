import json
import os
import tempfile
from pathlib import Path

from huavd_map_build.catalog.domain.snapshot import CatalogSnapshot


class JsonCatalogSnapshotWriter:
    def write(self, output_path: str, snapshot: CatalogSnapshot) -> None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            snapshot.as_dict(), ensure_ascii=False, indent=2, separators=(",", ": ")
        ) + "\n"
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
