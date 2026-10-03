import json
from pathlib import Path
from pathlib import PurePosixPath

from huavd_map_build.delivery.south.port.atomic_writer import AtomicWriter
from huavd_map_build.delivery.south.port.digest import DigestPort
from huavd_map_build.production.domain.style import StyleDocuments


class FileSystemStyleStore:
    def __init__(self, writer: AtomicWriter, digest: DigestPort) -> None:
        self._writer, self._digest = writer, digest

    def is_file(self, path: str) -> bool:
        return Path(path).is_file()

    def publish(self, vector_path: str, bake_path: str, raster_path: str,
                documents: StyleDocuments) -> tuple[str, str, str]:
        paths = (vector_path, bake_path, raster_path)
        values = (documents.vector, documents.bake, documents.raster)
        for path, document in zip(paths, values, strict=True):
            self._writer.write_text(
                path, json.dumps(document, ensure_ascii=False, indent=2) + "\n"
            )
            digest = self._digest.sha512(path)
            self._writer.write_text(
                f"{path}.sha512", f"{digest}  {PurePosixPath(path).name}\n"
            )
        return paths
