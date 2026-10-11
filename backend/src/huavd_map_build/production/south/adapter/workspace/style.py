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


class FileSystemRasterClientStyleBinder:
    """Bind the published raster's own header before the ready marker is written."""
    def __init__(self, headers, writer: AtomicWriter, digest: DigestPort) -> None:
        self._headers, self._writer, self._digest = headers, writer, digest

    def bind(self, archive_path: str, style_path: str, tile_size: int) -> None:
        from huavd_map_build.production.domain.raster import RasterSourceMetadata

        header = self._headers.read(archive_path)
        if header.tile_type != 4:
            raise ValueError("client raster style requires a WebP archive")
        metadata = RasterSourceMetadata(header.min_zoom, header.max_zoom, tuple(header.bounds))
        document = json.loads(Path(style_path).read_text(encoding="utf-8"))
        layers = [layer for layer in document.get("layers", []) if layer.get("type") == "raster"]
        if len(layers) != 1:
            raise ValueError("client raster style must have exactly one raster layer")
        source = document["sources"][layers[0]["source"]]
        if source.get("type") != "raster":
            raise ValueError("client raster layer must reference a raster source")
        source.update(metadata.as_dict())
        source["tileSize"] = tile_size
        from huavd_map_build.production.domain.style import default_zoom

        west, south, east, north = metadata.bounds
        document.setdefault("metadata", {})["huavd:viewport"] = {
            "min_zoom": metadata.min_zoom, "max_zoom": metadata.max_zoom,
            "bounds": list(metadata.bounds), "center": [(west+east)/2, (south+north)/2],
            "default_zoom": min(max(default_zoom(metadata.bounds), metadata.min_zoom), metadata.max_zoom),
        }
        self._writer.write_text(style_path, json.dumps(document, ensure_ascii=False, indent=2)+"\n")
        digest = self._digest.sha512(style_path)
        self._writer.write_text(f"{style_path}.sha512", f"{digest}  {Path(style_path).name}\n")
