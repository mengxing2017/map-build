from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from huavd_map_build.production.domain.raster import (
    RasterCacheScanResult,
    RasterTilePlan,
    webp_dimensions,
)


class FileSystemRasterCacheStore:
    def write_plan(self, plan: RasterTilePlan, plan_path: str, tiles_path: str) -> None:
        plan_target, tiles_target = Path(plan_path), Path(tiles_path)
        plan_target.parent.mkdir(parents=True, exist_ok=True)
        tiles_target.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(
            plan_target,
            json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        )
        self._write_atomic(
            tiles_target, (coordinate.tsv() for coordinate in plan.coordinates())
        )

    def scan(
        self, plan: RasterTilePlan, webp_directory: str, missing_path: str,
        quarantine_directory: str, tile_size: int,
    ) -> RasterCacheScanResult:
        root, quarantine = Path(webp_directory), Path(quarantine_directory)
        missing_target = Path(missing_path)
        missing_target.parent.mkdir(parents=True, exist_ok=True)
        hits = missing = invalid = unverified = 0
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=missing_target.parent,
            prefix=f".{missing_target.name}.", delete=False,
        ) as output:
            temporary = Path(output.name)
            try:
                for coordinate in plan.coordinates():
                    tile = root / str(coordinate.zoom) / str(coordinate.x) / f"{coordinate.y}.webp"
                    try:
                        payload = tile.read_bytes()
                        valid = webp_dimensions(payload) == (tile_size, tile_size)
                    except (OSError, ValueError):
                        payload, valid = b"", False
                    if not valid:
                        if tile.exists():
                            self._quarantine(tile, quarantine, root)
                            invalid += 1
                        output.write(coordinate.tsv())
                        missing += 1
                        continue
                    marker = Path(f"{tile}.sha512")
                    try:
                        recorded = marker.read_text(encoding="utf-8").split(maxsplit=1)[0]
                    except (OSError, IndexError):
                        recorded = ""
                    if recorded != hashlib.sha512(payload).hexdigest():
                        output.write(coordinate.tsv())
                        missing += 1
                        unverified += 1
                    else:
                        hits += 1
                output.flush()
                temporary.replace(missing_target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        return RasterCacheScanResult(
            plan.tile_count, hits, missing, invalid, unverified
        )

    @staticmethod
    def _quarantine(tile: Path, quarantine: Path, root: Path) -> None:
        destination = quarantine / tile.relative_to(root)
        destination = destination.with_name(f"{destination.name}.invalid")
        destination.parent.mkdir(parents=True, exist_ok=True)
        suffix = 0
        candidate = destination
        while candidate.exists():
            suffix += 1
            candidate = destination.with_name(f"{destination.name}.{suffix}")
        shutil.move(tile, candidate)
        marker = Path(f"{tile}.sha512")
        if marker.exists():
            shutil.move(marker, Path(f"{candidate}.sha512"))

    @staticmethod
    def _write_atomic(path: Path, content) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as output:
            temporary = Path(output.name)
            try:
                if isinstance(content, str):
                    output.write(content)
                else:
                    output.writelines(content)
                output.flush()
                temporary.replace(path)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
