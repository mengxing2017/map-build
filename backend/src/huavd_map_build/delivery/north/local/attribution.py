from __future__ import annotations

import json

from huavd_map_build.delivery.domain.artifact import ArtifactPaths
from huavd_map_build.delivery.domain.attribution import AttributionDocument
from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter


class AttributionWriterService:
    def __init__(self, writer: AtomicWriter) -> None:
        self._writer = writer

    def write(self, paths: ArtifactPaths, document: AttributionDocument) -> str:
        content = json.dumps(
            document.as_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        self._writer.write_text(paths.attribution, content)
        return paths.attribution
